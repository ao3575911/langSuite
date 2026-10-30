"""Polite, cached HTTP fetches (SPEC §2c: conditional requests first, backoff, cache everything)."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from langsuite import __version__
from langsuite.core.errors import DataError
from langsuite.ingest.sources import Source

USER_AGENT = f"langsuite/{__version__} (+https://github.com/ao3575911/langsuite)"
MAX_BYTES = 128 * 1024 * 1024
RETRIES = 3


@dataclass(frozen=True)
class Fetched:
    source: Source
    data: bytes
    retrieved_at: str
    sha256: str
    origin: str  # "network" | "not-modified" | "cache" | "file"
    note: str = ""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _meta_path(cache: Path, source: Source) -> Path:
    return cache / f"{source.filename}.meta.json"


def _read_cache(cache: Path, source: Source) -> tuple[bytes, dict[str, str]] | None:
    body, meta = cache / source.filename, _meta_path(cache, source)
    if not body.is_file() or not meta.is_file():
        return None
    try:
        info = json.loads(meta.read_text(encoding="utf-8"))
        data = body.read_bytes()
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or hashlib.sha256(data).hexdigest() != info.get("sha256"):
        return None
    return data, {str(k): str(v) for k, v in info.items()}


def _write_cache(cache: Path, source: Source, data: bytes, info: dict[str, str]) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    tmp = cache / f".{source.filename}.tmp"
    tmp.write_bytes(data)
    tmp.replace(cache / source.filename)
    _meta_path(cache, source).write_text(json.dumps(info, indent=2), encoding="utf-8")


def from_file(source: Source, path: Path) -> Fetched:
    """Use a local copy (tests, air-gapped builds). Its mtime stands in for retrieval time."""
    try:
        data = path.read_bytes()
        mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC).replace(microsecond=0)
    except OSError as err:
        raise DataError(
            f"Cannot read {source.title} file {path}: {err.strerror or err}.",
            hint=f"Put {source.filename} in the --from directory.",
        ) from err
    stamp = mtime.isoformat().replace("+00:00", "Z")
    return Fetched(source, data, stamp, hashlib.sha256(data).hexdigest(), "file")


def fetch(
    source: Source,
    cache: Path,
    *,
    offline: bool = False,
    timeout: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Fetched:
    """Fetch `source`, revalidating the cache with ETag/Last-Modified.

    Falls back to the cache, with a note, when the network fails. Raises DataError
    only when there is neither a response nor a usable cache.
    """
    cached = _read_cache(cache, source)
    if offline:
        if cached is None:
            raise DataError(
                f"No cached copy of {source.title} for an offline build.",
                hint="Run `langsuite base build` once with network access.",
            )
        data, info = cached
        return Fetched(source, data, info["retrieved_at"], info["sha256"], "cache", "offline")

    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if cached is not None:
        if cached[1].get("etag"):
            headers["If-None-Match"] = cached[1]["etag"]
        if cached[1].get("last_modified"):
            headers["If-Modified-Since"] = cached[1]["last_modified"]

    last_error = ""
    for attempt in range(RETRIES):
        if attempt:
            sleep(2 ** (attempt - 1))
        if not source.url.startswith(("https://", "http://")):
            raise DataError(f"Refusing to fetch {source.url}: only http(s) is allowed.")
        request = urllib.request.Request(source.url, headers=headers)  # noqa: S310 - scheme checked
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URLs
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise DataError(
                        f"{source.title} response is larger than {MAX_BYTES // 2**20} MB.",
                        hint="Upstream may have changed; please open an issue.",
                    )
                info = {
                    "url": source.url,
                    "retrieved_at": _now(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "etag": response.headers.get("ETag", ""),
                    "last_modified": response.headers.get("Last-Modified", ""),
                }
                _write_cache(cache, source, data, info)
                return Fetched(source, data, info["retrieved_at"], info["sha256"], "network")
        except urllib.error.HTTPError as err:
            if err.code == 304 and cached is not None:
                data, info = cached
                info["retrieved_at"] = _now()
                _write_cache(cache, source, data, info)
                return Fetched(source, data, info["retrieved_at"], info["sha256"], "not-modified")
            last_error = f"HTTP {err.code}"
            if 400 <= err.code < 500 and err.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            reason = getattr(err, "reason", None) or err
            last_error = str(reason)

    if cached is not None:
        data, info = cached
        note = f"network failed ({last_error}); used cache from {info['retrieved_at']}"
        return Fetched(source, data, info["retrieved_at"], info["sha256"], "cache", note)
    raise DataError(
        f"Could not download {source.title} ({last_error}).",
        hint="Check your connection and try again; later builds can use --offline.",
    )
