"""M5i (client side): quota exit 5, ledger equals invoice preview, Stripe test-mode webhook
idempotency and signature, device-code login, honest login without a server."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import pytest

from langsuite.cli.app import main
from langsuite.core import saas
from langsuite.core.errors import AuthError, QuotaError

SECRET = "whsec_test_dummy"  # noqa: S105


def _signed(event: dict[str, Any], ts: int = 1_000) -> tuple[bytes, str]:
    body = json.dumps(event).encode()
    sig = hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


def test_quota_reaches_100_percent_then_exit_5(tmp_path: Path) -> None:
    for _ in range(saas.PLANS["free"]["quota"]):
        saas.meter("verify", tmp_path)
    u = saas.usage(tmp_path)
    assert u.percent == 100.0
    with pytest.raises(QuotaError) as err:
        saas.meter("verify", tmp_path)
    assert err.value.exit_code == 5 and "quota" in str(err.value)
    saas.meter("lang", tmp_path)  # unmetered commands still work


def test_usage_events_sum_to_invoice_preview(tmp_path: Path) -> None:
    for kind in ["verify", "verify", "ask", "guide"]:
        saas.meter(kind, tmp_path)
    u = saas.usage(tmp_path)
    inv = saas.invoice_preview(u)
    assert inv["metered_units"] == len(saas.ledger(tmp_path)) == u.used == 4
    assert inv["total_cents"] == sum(x["cents"] for x in inv["lines"])


def test_stripe_checkout_upgrades_cancel_downgrades_replay_ignored(tmp_path: Path) -> None:
    body, hdr = _signed({"id": "evt_1", "type": "checkout.session.completed", "livemode": False})
    assert saas.handle_webhook(body, hdr, SECRET, tmp_path, now=1_000) == "applied"
    assert saas.load(tmp_path)["plan"] == "pro"
    assert saas.handle_webhook(body, hdr, SECRET, tmp_path, now=1_000) == "ignored-replay"
    body2, hdr2 = _signed({"id": "evt_2", "type": "customer.subscription.deleted"})
    assert saas.handle_webhook(body2, hdr2, SECRET, tmp_path, now=1_000) == "applied"
    assert saas.load(tmp_path)["plan"] == "read-only"
    with pytest.raises(QuotaError, match="quota"):
        saas.meter("verify", tmp_path)


def test_stripe_rejects_bad_signature_old_and_live(tmp_path: Path) -> None:
    body, hdr = _signed({"id": "evt_3", "type": "checkout.session.completed"})
    with pytest.raises(AuthError, match="does not match"):
        saas.handle_webhook(body + b" ", hdr, SECRET, tmp_path, now=1_000)
    with pytest.raises(AuthError, match="too old"):
        saas.handle_webhook(body, hdr, SECRET, tmp_path, now=10_000)
    live, lhdr = _signed({"id": "evt_4", "type": "checkout.session.completed", "livemode": True})
    with pytest.raises(AuthError, match="Live-mode"):
        saas.handle_webhook(live, lhdr, SECRET, tmp_path, now=1_000)
    assert saas.load(tmp_path)["plan"] == "free"


def test_device_code_login_and_logout(tmp_path: Path) -> None:
    replies = iter(
        [
            {"device_code": "d", "user_code": "ABCD-EFGH", "verification_uri": "https://x/d"},
            {"error": "authorization_pending"},
            {"access_token": "tok", "plan": "pro"},
        ]
    )
    shown: list[str] = []
    res = saas.device_login(
        "https://x",
        post=lambda _u, _f: next(replies),
        show=lambda _u, c: shown.append(c),
        sleep=lambda _s: None,
        home=tmp_path,
    )
    assert res["plan"] == "pro" and shown == ["ABCD-EFGH"]
    assert saas.load(tmp_path)["token"] == "tok"  # noqa: S105
    assert saas.logout(tmp_path) is True and saas.load(tmp_path)["token"] is None


def test_login_without_server_is_honest(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LANGSUITE_API_URL", raising=False)
    with pytest.raises(SystemExit) as ex:
        main(["--plain", "login"])
    assert ex.value.code == 4
    assert "not live yet" in capsys.readouterr().err


def test_usage_cli(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ex:
        main(["--json", "usage"])
    assert ex.value.code in (0, None)
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["plan"] == "free" and "invoice_preview" in data
