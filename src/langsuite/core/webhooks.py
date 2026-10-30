"""Outbound webhooks (SPEC §6d, M5h): signed JSON on workspace events.

HTTPS only; private, loopback and link-local addresses refused; HMAC-SHA256 over
`<timestamp>.<body>` in `Langsuite-Signature: t=<ts>,v1=<hex>`; three tries with backoff;
a hook is disabled after 5 failed deliveries in a row. Hooks live in the workspace's
`webhooks.json`, secrets included, like any other local credential file.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from langsuite.core.errors import UsageError

EVENTS = ("finding.saved", "digest.ready")
HEADER = "Langsuite-Signature"
TOLERANCE = 300
MAX_FAILS = 5
_ALLOW_PRIVATE = "LANGSUITE_WEBHOOK_ALLOW_PRIVATE"  # tests only: local receivers


def sign(secret: str, body: bytes, ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify(secret: str, body: bytes, header: str, now: int | None = None) -> bool:
    """For receivers: constant-time check of signature and freshness (5 minutes)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (KeyError, ValueError):
        return False
    now = int(time.time()) if now is None else now
    if abs(now - ts) > TOLERANCE:
        return False
    return hmac.compare_digest(sign(secret, body, ts), header)


def check_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    allow_private = os.environ.get(_ALLOW_PRIVATE) == "1"
    if parsed.scheme != "https" and not (allow_private and parsed.scheme == "http"):
        raise UsageError("Webhook URLs must use https://.")
    host = parsed.hostname or ""
    if not host:
        raise UsageError("Webhook URL has no host.")
    if allow_private:
        return url
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as err:
        raise UsageError(f"Cannot resolve `{host}`.") from err
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise UsageError(f"`{host}` resolves to a private address ({ip}); refused.")
    return url


def _path(ws_path: Path) -> Path:
    return ws_path / "webhooks.json"


def load(ws_path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(_path(ws_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(data) if isinstance(data, list) else []


def _save(ws_path: Path, hooks: list[dict[str, Any]]) -> None:
    path = _path(ws_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(hooks, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def add(ws_path: Path, url: str, events: list[str]) -> dict[str, Any]:
    bad = [e for e in events if e not in EVENTS]
    if bad:
        raise UsageError(f"Unknown event `{bad[0]}`.", hint=f"Use {', '.join(EVENTS)}.")
    hooks = load(ws_path)
    n = max((int(h["id"][1:]) for h in hooks), default=0) + 1
    hook = {
        "id": f"h{n}",
        "url": check_url(url),
        "events": sorted(set(events or EVENTS)),
        "secret": "whsec_" + secrets.token_hex(24),
        "active": True,
        "fails": 0,
    }
    _save(ws_path, [*hooks, hook])
    return hook


def remove(ws_path: Path, hook_id: str) -> None:
    hooks = load(ws_path)
    if not any(h["id"] == hook_id for h in hooks):
        raise UsageError(f"No webhook `{hook_id}`.", hint="See `langsuite webhook list`.")
    _save(ws_path, [h for h in hooks if h["id"] != hook_id])


def _post(url: str, body: bytes, sig: str, event: str) -> bool:
    req = urllib.request.Request(  # noqa: S310 - scheme checked in check_url
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", HEADER: sig, "Langsuite-Event": event},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            return bool(200 <= int(resp.status) < 300)
    except (urllib.error.URLError, OSError):
        return False


def deliver(ws_path: Path, event: str, payload: dict[str, Any], tries: int = 3) -> list[str]:
    """POST to every active hook for `event`; returns the ids delivered."""
    hooks = load(ws_path)
    if not hooks:
        return []
    body = json.dumps({"event": event, "data": payload}, sort_keys=True).encode()
    done: list[str] = []
    for hook in hooks:
        if not hook.get("active") or event not in hook.get("events", []):
            continue
        ok = False
        for attempt in range(tries):
            if _post(hook["url"], body, sign(hook["secret"], body), event):
                ok = True
                break
            time.sleep(min(0.2 * 2**attempt, 2.0))
        hook["fails"] = 0 if ok else int(hook.get("fails", 0)) + 1
        if hook["fails"] >= MAX_FAILS:
            hook["active"] = False
        if ok:
            done.append(hook["id"])
    _save(ws_path, hooks)
    return done
