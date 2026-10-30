"""Workspaces: findings, notes, saved queries, own-data overlay, pinned snapshots (SPEC §10 M3).

A workspace is a folder of small JSON files under `<data home>/workspaces/<slug>/`, so it
can be diffed, backed up, or exported as one bundle. Every finding records the command that
produced it, the snapshot it ran on, a copy of the overlay it saw, and the SHA-256 of its
canonical result, so `verify` can re-run it later and prove it is unchanged bit-for-bit.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langsuite.core import query as q
from langsuite.core import similarity as sim
from langsuite.core.errors import DataError, LangsuiteError, NoResultError, UsageError
from langsuite.core.kb import (
    Assertion,
    Edge,
    KnowledgeBase,
    Language,
    Overlay,
    read_manifest,
)
from langsuite.core.paths import data_home

SCHEMA = 1
DEFAULT = "default"
KINDS = ("query", "similar", "pair", "lang")
OVERLAY_SOURCE = "user"
_SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")  # SPEC §6g workspace slug
_LANG_ID = re.compile(r"^[a-z0-9][a-z0-9_.+#-]{0,47}$")
_ID = re.compile(r"^f(\d+)$")


def workspaces_dir(home: Path | None = None) -> Path:
    return (home or data_home()) / "workspaces"


def _config_path(home: Path | None) -> Path:
    return (home or data_home()) / "config.json"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(data: Any) -> str:
    return hashlib.sha256(canonical(data).encode("utf-8")).hexdigest()


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(path)


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as err:
        raise DataError(
            f"{path} is unreadable ({type(err).__name__}).",
            hint="Restore it from `langsuite workspace export` or delete it.",
        ) from err


def check_slug(slug: str) -> str:
    if not _SLUG.match(slug):
        raise UsageError(
            f"`{slug}` is not a valid workspace name.",
            hint="Start with a letter; up to 32 lowercase letters, digits, - or _.",
        )
    return slug


def active_slug(home: Path | None = None) -> str:
    env = os.environ.get("LANGSUITE_WORKSPACE")
    if env:
        return check_slug(env)
    cfg = _read(_config_path(home), {})
    return check_slug(str(cfg.get("workspace") or DEFAULT))


def set_active(slug: str, home: Path | None = None) -> None:
    path = _config_path(home)
    cfg = _read(path, {})
    cfg["workspace"] = check_slug(slug)
    _write(path, cfg)


def list_workspaces(home: Path | None = None) -> list[str]:
    folder = workspaces_dir(home)
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if (p / "workspace.json").is_file())


def pinned_snapshots(home: Path | None = None) -> set[str]:
    """Every snapshot a workspace pin or a saved finding depends on; these are never pruned."""
    out: set[str] = set()
    for slug in list_workspaces(home):
        ws = Workspace(home, slug)
        if ws.meta.get("pinned_snapshot"):
            out.add(str(ws.meta["pinned_snapshot"]))
        out |= {f.snapshot_id for f in ws.findings()}
    return out


# ----- records -------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    id: str
    title: str
    kind: str
    args: dict[str, Any]
    snapshot_id: str
    result: Any
    result_sha256: str
    evidence: list[str]
    created_at: str
    overlay: dict[str, Any] | None = None
    tags: list[str] = field(default_factory=list)
    schema: int = SCHEMA

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Finding:
        return cls(**data)

    @property
    def command(self) -> str:
        return command_line(self.kind, self.args)

    @property
    def number(self) -> int:
        m = _ID.match(self.id)
        return int(m.group(1)) if m else 0


@dataclass(frozen=True)
class Note:
    id: str
    text: str
    created_at: str
    on: str | None = None  # finding id or language id

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Verification:
    finding: Finding
    snapshot_id: str
    expected: str
    actual: str

    @property
    def ok(self) -> bool:
        return self.expected == self.actual

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.finding.id,
            "snapshot": self.snapshot_id,
            "expected_sha256": self.expected,
            "actual_sha256": self.actual,
            "reproducible": self.ok,
        }


# ----- running a recorded command ------------------------------------------------


def command_line(kind: str, args: dict[str, Any]) -> str:
    if kind == "query":
        top = f" --top {args['top']}" if args.get("top") else ""
        return f"langsuite query {json.dumps(args['text'])}{top}"
    if kind == "similar":
        extra = "" if args.get("baseline", True) else " --no-baseline"
        return f"langsuite similar {args['lang']} --k {args.get('k', 10)}{extra}"
    if kind == "pair":
        return f"langsuite similar {args['a']} --vs {args['b']}"
    return f"langsuite lang show {args['lang']}"


def run_recorded(kb: KnowledgeBase, kind: str, args: dict[str, Any]) -> tuple[Any, list[str], str]:
    """(canonical result, evidence ids, default title) for one recorded command."""
    if kind == "query":
        res = q.run(kb, str(args["text"]), top=args.get("top"))
        ids = [row.language.id for row in res.rows]
        ev = _evidence(kb, ids, set(res.features)) if res.features else []
        n = res.total
        return res.to_json(), ev, f"Query: {res.normalised} ({n} language{'s' if n != 1 else ''})"
    if kind == "similar":
        sres = sim.similar(
            kb,
            str(args["lang"]),
            k=int(args.get("k", 10)),
            min_traits=int(args.get("min_traits", sim.DEFAULT_MIN_TRAITS)),
            baseline=bool(args.get("baseline", True)),
        )
        ids = [sres.query.id] + [n.id for n in sres.neighbours]
        shared = {t for n in sres.neighbours for t in n.shared}
        top = sres.neighbours[0].name if sres.neighbours else "nothing"
        return sres.to_json(), _evidence(kb, ids, shared), f"Most like {sres.query.name}: {top}"
    if kind == "pair":
        pair = sim.compare_pair(kb, str(args["a"]), str(args["b"]))
        a = kb.resolve(str(args["a"]))
        data = {"method": sim.METHOD, "query": a.id, **pair.to_json()}
        ev = _evidence(kb, [a.id, pair.id], set(pair.shared))
        return data, ev, f"{a.name} vs {pair.name}: {pair.score:.3f}"
    if kind == "lang":
        lang = kb.resolve(str(args["lang"]))
        rows = kb.assertions(lang.id)
        parents, children = kb.edges(lang.id)
        data = {
            "language": lang.to_json(),
            "assertions": [a.to_json() for a in rows],
            "influenced_by": [e.to_json() for e in parents],
            "influenced": [e.to_json() for e in children],
            "snapshot": kb.manifest.snapshot_id,
        }
        return data, sorted({a.evidence_id for a in rows}), f"{lang.name} profile"
    raise UsageError(f"Unknown finding kind `{kind}`.", hint=f"Use one of {', '.join(KINDS)}.")


def _evidence(kb: KnowledgeBase, lang_ids: list[str], features: set[str]) -> list[str]:
    out: set[str] = set()
    for lid in lang_ids:
        out |= {a.evidence_id for a in kb.assertions(lid) if a.feature_id in features}
    return sorted(out)


# ----- the workspace ------------------------------------------------------------


class Workspace:
    def __init__(self, home: Path | None = None, slug: str | None = None) -> None:
        self.home = home
        self.slug = check_slug(slug or active_slug(home))
        self.path = workspaces_dir(home) / self.slug

    # -- lifecycle

    @classmethod
    def open(cls, home: Path | None = None, slug: str | None = None) -> Workspace:
        """Open a workspace. `default` is created on first use; others need `workspace init`."""
        ws = cls(home, slug)
        if not ws.exists():
            if ws.slug != DEFAULT:
                raise NoResultError(
                    f"No workspace named `{ws.slug}`.",
                    hint=f"Create it with `langsuite workspace init {ws.slug}`.",
                )
            ws.init()
        return ws

    def exists(self) -> bool:
        return (self.path / "workspace.json").is_file()

    def init(self) -> Workspace:
        if not self.exists():
            _write(
                self.path / "workspace.json",
                {
                    "schema": SCHEMA,
                    "slug": self.slug,
                    "created_at": _now(),
                    "pinned_snapshot": None,
                },
            )
        return self

    @property
    def meta(self) -> dict[str, Any]:
        return dict(_read(self.path / "workspace.json", {}))

    def _set_meta(self, **changes: Any) -> None:
        meta = self.meta
        meta.update(changes)
        _write(self.path / "workspace.json", meta)

    # -- snapshot pin

    @property
    def pinned(self) -> str | None:
        value = self.meta.get("pinned_snapshot")
        return str(value) if value else None

    def pin(self, snapshot: str | None) -> str:
        """Pin to a snapshot id, or to the current base when `snapshot` is None."""
        if snapshot is None:
            manifest = read_manifest(self.home)
            if manifest is None:
                from langsuite.core.kb import no_base_error

                raise no_base_error()
            snapshot = manifest.snapshot_id
        KnowledgeBase(self.home, snapshot=snapshot).close()  # proves it is kept here
        self._set_meta(pinned_snapshot=snapshot)
        return snapshot

    def unpin(self) -> None:
        self._set_meta(pinned_snapshot=None)

    # -- overlay

    @property
    def overlay(self) -> Overlay:
        return Overlay.from_json(_read(self.path / "overlay.json", {}))

    def kb(self, snapshot: str | None = None, overlay: Overlay | None = None) -> KnowledgeBase:
        return KnowledgeBase(
            self.home,
            snapshot=snapshot or self.pinned,
            overlay=self.overlay if overlay is None else overlay,
        )

    def import_data(self, data: dict[str, Any]) -> tuple[int, int, int]:
        """Merge languages/assertions/edges from a user file into the overlay. Validated first."""
        langs, asserts, edges = _parse_user_data(data)
        with KnowledgeBase(self.home, snapshot=self.pinned) as base:
            base_ids = {lang.id for lang in base.languages}
            features = {f.id for f in base.features}
        current = self.overlay
        known = base_ids | {lang.id for lang in current.languages}
        clash = sorted(lang.id for lang in langs if lang.id in base_ids)
        if clash:
            raise UsageError(
                f"Language id already in the base: {', '.join(clash)}.",
                hint="Pick a new id; to add facts to a base language, list only assertions.",
            )
        new_ids = {lang.id for lang in langs}
        for a in asserts:
            if a.lang_id not in known | new_ids:
                raise UsageError(
                    f"Assertion for unknown language `{a.lang_id}`.",
                    hint="Add it under `languages:` in the same file.",
                )
            if a.feature_id not in features:
                raise UsageError(
                    f"Unknown feature `{a.feature_id}`.",
                    hint="Feature ids come from `langsuite feature list --all`.",
                )
        merged_langs = {lang.id: lang for lang in current.languages}
        merged_langs.update({lang.id: lang for lang in langs})
        merged_asserts = {(a.lang_id, a.feature_id): a for a in current.assertions}
        merged_asserts.update({(a.lang_id, a.feature_id): a for a in asserts})
        merged_edges = {(e.src, e.dst): e for e in current.edges}
        merged_edges.update({(e.src, e.dst): e for e in edges})
        overlay = Overlay(
            languages=tuple(merged_langs[k] for k in sorted(merged_langs)),
            assertions=tuple(merged_asserts[k] for k in sorted(merged_asserts)),
            edges=tuple(merged_edges[k] for k in sorted(merged_edges)),
        )
        _write(self.path / "overlay.json", overlay.to_json())
        return len(langs), len(asserts), len(edges)

    def clear_overlay(self) -> None:
        (self.path / "overlay.json").unlink(missing_ok=True)

    # -- findings

    def _finding_paths(self) -> Iterator[Path]:
        folder = self.path / "findings"
        if folder.is_dir():
            yield from folder.glob("f*.json")

    def findings(self) -> list[Finding]:
        out = [Finding.from_json(_read(p, {})) for p in self._finding_paths()]
        return sorted(out, key=lambda f: f.number)

    def finding(self, ref: str) -> Finding:
        ref = ref.strip().lower()
        found = self.findings()
        if ref == "last":
            if not found:
                raise NoResultError("No findings yet.", hint="Save one with `langsuite extract`.")
            return found[-1]
        key = ref if ref.startswith("f") else f"f{ref}"
        for f in found:
            if f.id == key:
                return f
        raise NoResultError(
            f"No finding `{ref}` in workspace `{self.slug}`.",
            hint="List them with `langsuite finding list`.",
        )

    def save_finding(
        self,
        kind: str,
        args: dict[str, Any],
        title: str | None = None,
        tags: list[str] | None = None,
    ) -> Finding:
        overlay = self.overlay
        with self.kb(overlay=overlay) as kb:
            result, evidence, default_title = run_recorded(kb, kind, args)
            snapshot = kb.manifest.snapshot_id
        folder = self.path / "findings"
        folder.mkdir(parents=True, exist_ok=True)
        n = max((f.number for f in self.findings()), default=0) + 1
        while True:
            path = folder / f"f{n}.json"
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                n += 1
                continue
            os.close(fd)
            break
        finding = Finding(
            id=f"f{n}",
            title=(title or default_title).strip()[:200],
            kind=kind,
            args=args,
            snapshot_id=snapshot,
            result=result,
            result_sha256=digest(result),
            evidence=evidence,
            created_at=_now(),
            overlay=overlay.to_json() if overlay else None,
            tags=sorted(set(tags or [])),
        )
        _write(path, finding.to_json())
        self._retain(snapshot)
        return finding

    def _retain(self, snapshot: str) -> None:
        """Make sure the snapshot a finding used is kept, even if it is the current base."""
        from langsuite.core.kb import kept_snapshots, retain_snapshot

        if any(m.snapshot_id == snapshot for m in kept_snapshots(self.home)):
            return
        manifest = read_manifest(self.home)
        if manifest is not None and manifest.snapshot_id == snapshot:
            retain_snapshot(self.home, manifest)

    def remove_finding(self, ref: str) -> Finding:
        f = self.finding(ref)
        (self.path / "findings" / f"{f.id}.json").unlink()
        return f

    def verify(self, ref: str) -> Verification:
        """Re-run a finding on its own snapshot and overlay; compare result hashes."""
        f = self.finding(ref)
        overlay = Overlay.from_json(f.overlay) if f.overlay else Overlay()
        with KnowledgeBase(self.home, snapshot=f.snapshot_id, overlay=overlay) as kb:
            result, _ev, _t = run_recorded(kb, f.kind, f.args)
        return Verification(f, f.snapshot_id, f.result_sha256, digest(result))

    # -- the last result, for `extract last`

    def remember(self, kind: str, args: dict[str, Any]) -> None:
        _write(self.path / "last.json", {"kind": kind, "args": args, "at": _now()})

    def last(self) -> tuple[str, dict[str, Any]]:
        data = _read(self.path / "last.json", None)
        if not data:
            raise NoResultError(
                "Nothing to extract yet.",
                hint="Run `langsuite query`, `similar` or `lang show` first.",
            )
        return str(data["kind"]), dict(data["args"])

    # -- notes

    def notes(self, on: str | None = None) -> list[Note]:
        raw = _read(self.path / "notes.json", [])
        notes = [Note(**n) for n in raw]
        return [n for n in notes if on is None or n.on == on]

    def add_note(self, text: str, on: str | None = None) -> Note:
        text = text.strip()
        if not text:
            raise UsageError("A note needs some text.")
        if on and _ID.match(on):
            self.finding(on)
        notes = self.notes()
        n = max((int(x.id[1:]) for x in notes), default=0) + 1
        note = Note(id=f"n{n}", text=text[:4000], created_at=_now(), on=on)
        _write(self.path / "notes.json", [x.to_json() for x in [*notes, note]])
        return note

    def remove_note(self, note_id: str) -> Note:
        notes = self.notes()
        for x in notes:
            if x.id == note_id:
                _write(self.path / "notes.json", [n.to_json() for n in notes if n is not x])
                return x
        raise NoResultError(f"No note `{note_id}`.", hint="List them with `langsuite note list`.")

    # -- saved queries

    def saved_queries(self) -> dict[str, str]:
        return dict(sorted(_read(self.path / "queries.json", {}).items()))

    def save_query(self, name: str, text: str) -> None:
        check_slug(name)
        if len(text) > q.MAX_QUERY_LEN:
            raise UsageError("That query is too long to save.")
        q.parse(text)
        saved = self.saved_queries()
        saved[name] = text
        _write(self.path / "queries.json", saved)

    def saved_query(self, name: str) -> str:
        saved = self.saved_queries()
        if name not in saved:
            raise NoResultError(
                f"No saved query `{name}`.",
                hint='Save one with `langsuite query "..." --save NAME`.',
            )
        return saved[name]

    def forget_query(self, name: str) -> None:
        saved = self.saved_queries()
        if saved.pop(name, None) is None:
            self.saved_query(name)
        _write(self.path / "queries.json", saved)

    # -- bundle export / import

    def bundle(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "kind": "langsuite-workspace",
            "workspace": self.meta,
            "findings": [f.to_json() for f in self.findings()],
            "notes": [n.to_json() for n in self.notes()],
            "queries": self.saved_queries(),
            "overlay": self.overlay.to_json(),
        }

    def load_bundle(self, data: dict[str, Any]) -> int:
        if data.get("kind") != "langsuite-workspace" or data.get("schema") != SCHEMA:
            raise UsageError(
                "That file is not a langsuite workspace bundle.",
                hint="Bundles come from `langsuite workspace export`.",
            )
        if self.findings() or self.notes() or self.saved_queries():
            raise UsageError(
                f"Workspace `{self.slug}` is not empty.",
                hint="Import into a new workspace: `langsuite workspace import FILE --as NAME`.",
            )
        self.init()
        pinned = data.get("workspace", {}).get("pinned_snapshot")
        self._set_meta(pinned_snapshot=pinned)
        for raw in data.get("findings", []):
            f = Finding.from_json(raw)
            if digest(f.result) != f.result_sha256:
                raise DataError(f"Finding {f.id} in the bundle was altered; its hash is wrong.")
            _write(self.path / "findings" / f"{f.id}.json", f.to_json())
        _write(self.path / "notes.json", list(data.get("notes", [])))
        _write(self.path / "queries.json", dict(data.get("queries", {})))
        if data.get("overlay"):
            _write(self.path / "overlay.json", Overlay.from_json(data["overlay"]).to_json())
        return len(data.get("findings", []))


def _parse_user_data(
    data: dict[str, Any],
) -> tuple[list[Language], list[Assertion], list[Edge]]:
    """User files: {languages: [{id, name, ...traits: {feature: yes|no}}], assertions: [...]}."""
    if not isinstance(data, dict):
        raise UsageError("Own-data files must be a mapping with `languages` and/or `assertions`.")
    now = _now()
    langs: list[Language] = []
    asserts: list[Assertion] = []
    edges: list[Edge] = []
    try:
        for raw in data.get("languages") or []:
            lid = str(raw["id"])
            if not _LANG_ID.match(lid):
                raise UsageError(
                    f"`{lid}` is not a valid language id.",
                    hint="Lowercase letters, digits and . + # - _, e.g. `my-lang`.",
                )
            langs.append(
                Language(
                    id=lid,
                    name=str(raw.get("name") or lid),
                    kind=str(raw.get("kind") or "pl"),
                    appeared=int(raw["appeared"]) if raw.get("appeared") else None,
                    website=raw.get("website"),
                    creators=raw.get("creators"),
                    rank=None,
                    aliases=tuple(str(a) for a in raw.get("aliases") or ()),
                    extensions=tuple(str(e).lstrip(".") for e in raw.get("extensions") or ()),
                    sources=(OVERLAY_SOURCE,),
                )
            )
            for fid, value in sorted((raw.get("traits") or {}).items()):
                asserts.append(_user_assertion(lid, str(fid), value, raw.get("source"), now))
            for parent in raw.get("influenced_by") or []:
                edges.append(Edge(str(parent), lid, "influenced", OVERLAY_SOURCE, ""))
        for raw in data.get("assertions") or []:
            asserts.append(
                _user_assertion(
                    str(raw["lang"]), str(raw["feature"]), raw["value"], raw.get("source"), now
                )
            )
    except (KeyError, TypeError, ValueError) as err:
        if isinstance(err, LangsuiteError):
            raise
        raise UsageError(f"Own-data file is malformed: {err!r}.") from err
    return langs, asserts, edges


def _user_assertion(lang: str, feature: str, value: Any, source: Any, now: str) -> Assertion:
    if isinstance(value, bool):
        value = "yes" if value else "no"
    value = str(value).lower()
    if value not in ("yes", "no"):
        raise UsageError(f"`{lang}.{feature}` must be yes or no, not `{value}`.")
    return Assertion(
        lang_id=lang,
        feature_id=feature,
        value=value,
        source=OVERLAY_SOURCE,
        source_url=str(source or ""),
        excerpt="",
        retrieved_at=now,
        confidence=1.0,
    )


def open_kb(home: Path | None = None) -> KnowledgeBase:
    """The knowledge base as the active workspace sees it: pinned snapshot plus overlay."""
    return Workspace.open(home).kb()


def remember(kind: str, args: dict[str, Any], home: Path | None = None) -> None:
    """Best effort: record the last result for `extract last`; never fail the command."""
    with contextlib.suppress(OSError, LangsuiteError):
        Workspace.open(home).remember(kind, args)
