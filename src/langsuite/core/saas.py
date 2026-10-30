"""Plan, quota, usage and Stripe test-mode entitlements (SPEC M5i), local part.

The hosted service (tenants, RLS, object store, backups) is not deployed. This module is
the client side: a device-code login against `LANGSUITE_API_URL` when one is set, a local
usage ledger with monthly quotas (exit 5 at 100%), an invoice preview that sums the ledger,
and an idempotent, signature-checked Stripe webhook handler that only accepts test mode.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from langsuite.core.errors import AuthError, DataError, QuotaError
from langsuite.core.paths import data_home

TZ = ZoneInfo("Australia/Perth")
PLANS: dict[str, dict[str, Any]] = {
    "free": {"quota": 100, "price_cents": 0, "write": True},
    "pro": {"quota": 5000, "price_cents": 900, "write": True},
    "read-only": {"quota": 0, "price_cents": 0, "write": False},
}
METERED = {"verify": 1, "ask": 1, "guide": 1}
UNIT_CENTS = 0  # metered units are included in the plan; preview shows them at zero
WEBHOOK_TOLERANCE = 300


def _path(name: str, home: Path | None) -> Path:
    return (home or data_home()) / name


def load(home: Path | None = None) -> dict[str, Any]:
    p = _path("saas.json", home)
    data: dict[str, Any] = {"plan": "free", "token": None, "server": None, "seen_events": []}
    if p.is_file():
        data.update(json.loads(p.read_text("utf-8")))
    return data


def save(data: dict[str, Any], home: Path | None = None) -> None:
    p = _path("saas.json", home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), "utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def month(now: datetime | None = None) -> str:
    return (now or datetime.now(TZ)).astimezone(TZ).strftime("%Y-%m")


def ledger(home: Path | None = None, period: str | None = None) -> list[dict[str, Any]]:
    p = _path("usage.jsonl", home)
    if not p.is_file():
        return []
    rows = [json.loads(line) for line in p.read_text("utf-8").splitlines() if line.strip()]
    return [r for r in rows if period is None or r["month"] == period]


@dataclass(frozen=True)
class Usage:
    plan: str
    period: str
    used: int
    quota: int
    by_kind: dict[str, int]

    @property
    def percent(self) -> float:
        return 100.0 if self.quota == 0 else round(100.0 * self.used / self.quota, 1)

    def to_json(self) -> dict[str, Any]:
        return {
            "plan": self.plan,
            "period": self.period,
            "used": self.used,
            "quota": self.quota,
            "percent": self.percent,
            "by_kind": self.by_kind,
            "invoice_preview": invoice_preview(self),
        }


def usage(home: Path | None = None, now: datetime | None = None) -> Usage:
    plan = str(load(home)["plan"])
    period = month(now)
    by: dict[str, int] = {}
    for r in ledger(home, period):
        by[r["kind"]] = by.get(r["kind"], 0) + int(r["units"])
    return Usage(
        plan, period, sum(by.values()), int(PLANS[plan]["quota"]), dict(sorted(by.items()))
    )


def invoice_preview(u: Usage) -> dict[str, Any]:
    lines = [{"item": f"{u.plan} plan", "units": 1, "cents": int(PLANS[u.plan]["price_cents"])}]
    lines += [{"item": k, "units": n, "cents": n * UNIT_CENTS} for k, n in u.by_kind.items()]
    return {
        "period": u.period,
        "lines": lines,
        "metered_units": sum(n for n in u.by_kind.values()),
        "total_cents": sum(int(str(x["cents"])) for x in lines),
        "currency": "aud",
        "note": "Preview from the local ledger; nothing is charged.",
    }


def meter(kind: str, home: Path | None = None, now: datetime | None = None) -> None:
    """Count one metered command; refuse politely (exit 5) once the month's quota is used."""
    units = METERED.get(kind)
    if units is None:
        return
    u = usage(home, now)
    if u.used + units > u.quota:
        hint = (
            "Your plan is read-only. Upgrade to run metered commands."
            if u.plan == "read-only"
            else "Quota resets at the start of next month (Australia/Perth). "
            f"Used {u.used}/{u.quota}."
        )
        raise QuotaError(f"You've used this month's {kind} quota on the {u.plan} plan.", hint=hint)
    p = _path("usage.jsonl", home)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"month": u.period, "kind": kind, "units": units, "at": int(time.time())}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


# ----- Stripe (test mode only) -----------------------------------------------------------


def verify_stripe_signature(payload: bytes, header: str, secret: str, now: float) -> None:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        ts = int(parts["t"])
        sig = parts["v1"]
    except (KeyError, ValueError):
        raise AuthError("Stripe signature header is malformed.") from None
    if abs(now - ts) > WEBHOOK_TOLERANCE:
        raise AuthError("Stripe webhook is too old; refusing a possible replay.")
    want = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, sig):
        raise AuthError("Stripe signature does not match.")


def handle_webhook(
    payload: bytes, header: str, secret: str, home: Path | None = None, now: float | None = None
) -> str:
    """Apply a Stripe event once. Returns 'applied', 'ignored-replay' or 'ignored-type'."""
    verify_stripe_signature(payload, header, secret, time.time() if now is None else now)
    event = json.loads(payload)
    if event.get("livemode"):
        raise AuthError("Live-mode Stripe events are refused; only test mode is enabled.")
    data = load(home)
    if event["id"] in data["seen_events"]:
        return "ignored-replay"
    kind = event.get("type")
    if kind == "checkout.session.completed":
        data["plan"] = "pro"
    elif kind == "customer.subscription.deleted":
        data["plan"] = "read-only"
    else:
        data["seen_events"].append(event["id"])
        save(data, home)
        return "ignored-type"
    data["seen_events"] = [*data["seen_events"], event["id"]][-1000:]
    save(data, home)
    return "applied"


# ----- device-code login (RFC 8628) -------------------------------------------------------

Post = Callable[[str, dict[str, str]], dict[str, Any]]


def http_post(url: str, form: dict[str, str]) -> dict[str, Any]:
    if not url.startswith("https://"):
        raise AuthError("The login server must use https.")
    body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=body, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            out: dict[str, Any] = json.loads(resp.read())
            return out
    except urllib.error.HTTPError as err:
        out = json.loads(err.read() or b"{}")
        return out
    except OSError as err:
        raise AuthError(f"Could not reach the login server: {err}") from None


def server_url() -> str:
    url = os.environ.get("LANGSUITE_API_URL", "").rstrip("/")
    if not url:
        raise AuthError(
            "The hosted langsuite service is not live yet, so there is nothing to sign in to.",
            hint="Everything else works locally on the free plan. "
            "Set LANGSUITE_API_URL to a langsuite server to use device login.",
        )
    return url


def device_login(
    server: str,
    post: Post = http_post,
    show: Callable[[str, str], None] = lambda _u, _c: None,
    sleep: Callable[[float], None] = time.sleep,
    home: Path | None = None,
) -> dict[str, Any]:
    start = post(f"{server}/oauth/device/code", {"client_id": "langsuite-cli"})
    if "device_code" not in start:
        raise AuthError("The login server did not start a device login.")
    show(str(start["verification_uri"]), str(start["user_code"]))
    interval = float(start.get("interval", 5))
    deadline = time.monotonic() + float(start.get("expires_in", 600))
    while time.monotonic() < deadline:
        sleep(interval)
        tok = post(
            f"{server}/oauth/token",
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": str(start["device_code"]),
                "client_id": "langsuite-cli",
            },
        )
        err = tok.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            raise AuthError(f"Sign-in failed: {err}.")
        data = load(home)
        data.update(token=tok["access_token"], server=server, plan=tok.get("plan", data["plan"]))
        save(data, home)
        return {"server": server, "plan": data["plan"]}
    raise AuthError("The sign-in code expired. Run `langsuite login` again.")


def logout(home: Path | None = None) -> bool:
    data = load(home)
    had = bool(data.get("token"))
    data.update(token=None, server=None)
    save(data, home)
    return had


def require_plan_known(plan: str) -> None:
    if plan not in PLANS:
        raise DataError(f"Unknown plan `{plan}` in saas.json.")
