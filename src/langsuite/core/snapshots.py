"""Published snapshots: pack, sign, verify, pull; changelog and the data-CI gate (SPEC M5f).

Signatures use the `cosign sign-blob --key` format: a base64 ECDSA P-256 signature over
the SHA-256 of the bundle, checked against a PEM public key. A bundle is a tar.gz with
`current.duckdb` and `manifest.json`; `base pull` refuses it unless the signature verifies
and the manifest hash matches the database inside.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langsuite.core.errors import AuthError, DataError
from langsuite.core.kb import DB_NAME, MANIFEST_NAME, KnowledgeBase, Manifest, retain_snapshot
from langsuite.core.paths import base_dir

BUNDLE = "snapshot.tar.gz"
SIG = BUNDLE + ".sig"
JUMP_LIMIT = 15.0
STALE_FIELD_DAYS = 365


def pack(home: Path | None, out: Path) -> Path:
    """Write the current base as OUT/snapshot.tar.gz (deterministic member order and times)."""
    src = base_dir(home)
    if not (src / DB_NAME).is_file():
        raise DataError("No knowledge base to publish.", hint="Run `langsuite base build`.")
    out.mkdir(parents=True, exist_ok=True)
    target = out / BUNDLE
    with tarfile.open(target, "w:gz") as tar:
        for name in (DB_NAME, MANIFEST_NAME):
            info = tar.gettarinfo(str(src / name), arcname=name)
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            with (src / name).open("rb") as fh:
                tar.addfile(info, fh)
    return target


def sign(bundle: Path, private_key_pem: bytes) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise AuthError("The signing key must be an ECDSA P-256 key (cosign generate-key-pair).")
    sig = key.sign(bundle.read_bytes(), ec.ECDSA(hashes.SHA256()))
    text = base64.b64encode(sig).decode()
    bundle.with_name(bundle.name + ".sig").write_text(text, encoding="utf-8")
    return text


def verify(data: bytes, sig_b64: str, public_key_pem: bytes) -> None:
    """Raise AuthError unless SIG is a valid signature of DATA (cosign verify-blob semantics)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        key = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(key, ec.EllipticCurvePublicKey):
            raise ValueError("not an EC key")
        key.verify(base64.b64decode(sig_b64.strip()), data, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError) as err:
        raise AuthError(
            "Snapshot signature does not verify; refusing it.",
            hint="The bundle may be tampered with or signed by another key.",
        ) from err


def _read(src: str, name: str) -> bytes:
    if src.startswith("https://"):
        url = src.rstrip("/") + "/" + name
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - https only
            data: bytes = resp.read(512_000_000)
            return data
    if src.startswith("http://"):
        raise DataError("Snapshots are only pulled over https.")
    return (Path(src).expanduser() / name).read_bytes()


def pull(src: str, public_key_pem: bytes, home: Path | None = None) -> Manifest:
    """Verify and install a published snapshot as the current base (old one is kept)."""
    bundle = _read(src, BUNDLE)
    verify(bundle, _read(src, SIG).decode("utf-8"), public_key_pem)
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as tar:
            names = set(tar.getnames())
            if names != {DB_NAME, MANIFEST_NAME}:
                raise AuthError(f"Unexpected files in the snapshot: {sorted(names)}.")
            tar.extractall(tmp, filter="data")
        manifest = Manifest.from_json(json.loads((Path(tmp) / MANIFEST_NAME).read_text("utf-8")))
        dst = base_dir(home)
        dst.mkdir(parents=True, exist_ok=True)
        old = (
            Manifest.from_json(json.loads((dst / MANIFEST_NAME).read_text("utf-8")))
            if (dst / MANIFEST_NAME).is_file()
            else None
        )
        if old is not None:
            retain_snapshot(home, old)
        for name in (DB_NAME, MANIFEST_NAME):
            shutil.copyfile(Path(tmp) / name, dst / f".{name}.new")
            (dst / f".{name}.new").replace(dst / name)
    retain_snapshot(home, manifest)
    return manifest


@dataclass
class Changelog:
    old: str
    new: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)
    scores: list[dict[str, Any]] = field(default_factory=list)
    stale: list[dict[str, Any]] = field(default_factory=list)

    @property
    def jumps(self) -> list[dict[str, Any]]:
        return [s for s in self.scores if abs(s["delta"]) > JUMP_LIMIT]

    def to_json(self) -> dict[str, Any]:
        return {
            "old": self.old,
            "new": self.new,
            "added": self.added,
            "removed": self.removed,
            "changes": self.changes,
            "scores": self.scores,
            "stale": self.stale,
            "jumps": self.jumps,
            "jump_limit": JUMP_LIMIT,
            "publish_ok": not self.jumps,
        }


def _facts(kb: KnowledgeBase) -> dict[str, dict[str, tuple[str, str]]]:
    out: dict[str, dict[str, tuple[str, str]]] = {}
    for lang in kb.languages:
        out[lang.id] = {a.feature_id: (a.value, a.retrieved_at) for a in kb.assertions(lang.id)}
    return out


def _scores(kb: KnowledgeBase) -> dict[str, float]:
    from langsuite.core import analysis

    cache: dict[str, Any] = {}
    out = {}
    for lang in kb.languages:
        s = analysis.score(kb, lang, _cache=cache)
        if s.n:
            out[lang.id] = s.total
    return out


def changelog(old: KnowledgeBase, new: KnowledgeBase, now: datetime | None = None) -> Changelog:
    """Every change between two snapshots, score moves, and fields older than a year."""
    a, b = _facts(old), _facts(new)
    log = Changelog(old.manifest.snapshot_id, new.manifest.snapshot_id)
    log.added = sorted(set(b) - set(a))
    log.removed = sorted(set(a) - set(b))
    for lang in sorted(set(a) & set(b)):
        for fid in sorted(set(a[lang]) | set(b[lang])):
            va, vb = a[lang].get(fid, (None, ""))[0], b[lang].get(fid, (None, ""))[0]
            if va != vb:
                log.changes.append({"lang": lang, "feature": fid, "old": va, "new": vb})
    sa, sb = _scores(old), _scores(new)
    for lang in sorted(set(sa) & set(sb)):
        delta = round(sb[lang] - sa[lang], 2)
        if delta:
            log.scores.append(
                {"lang": lang, "old": round(sa[lang], 2), "new": round(sb[lang], 2), "delta": delta}
            )
    cutoff = (now or datetime.now(UTC)) - timedelta(days=STALE_FIELD_DAYS)
    for lang in sorted(b):
        for fid, (_, at) in sorted(b[lang].items()):
            try:
                when = datetime.fromisoformat(at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if when < cutoff:
                log.stale.append({"lang": lang, "feature": fid, "retrieved_at": at})
    return log


def issue_body(log: Changelog) -> str:
    rows = "\n".join(
        f"| {j['lang']} | {j['old']} | {j['new']} | {j['delta']:+} |" for j in log.jumps
    )
    return (
        f"Data CI blocked publishing {log.new}: {len(log.jumps)} score(s) moved more than "
        f"{JUMP_LIMIT:g} points since {log.old}.\n\n| language | old | new | change |\n"
        f"|---|---|---|---|\n{rows}\n\nCheck the source changes with "
        f"`langsuite base changelog {log.old} {log.new}`, then rerun the workflow."
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
