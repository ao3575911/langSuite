"""M5h: modes, MCP server, signed webhooks; bot /mode, digests and inline mode."""

from __future__ import annotations

import io
import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from langsuite.bot.core import Bot, Chat, last_slot, parse_digest
from langsuite.cli import mcp_server
from langsuite.cli.app import app
from langsuite.core import webhooks
from langsuite.core.errors import UsageError


def _cli(*args: str) -> Any:
    return CliRunner().invoke(app, list(args))


def test_mode_precedence_flag_workspace_global(kb_home: Path) -> None:
    def eff(*flag: str) -> str:
        return str(json.loads(_cli(*flag, "--json", "mode").stdout)["data"]["effective"])

    assert eff() == "default"
    assert _cli("mode", "concise", "--global").exit_code == 0
    assert eff() == "concise"
    assert _cli("mode", "thorough").exit_code == 0
    assert eff() == "thorough"  # workspace beats global
    out = _cli("--mode", "concise", "--plain", "rank", "--top", "2", "--min-criteria", "1")
    assert out.exit_code == 0 and "safet" not in out.stdout  # flag beats workspace
    assert _cli("mode", "--reset").exit_code == 0
    assert eff() == "concise"


def _rpc(*msgs: dict[str, Any]) -> list[dict[str, Any]]:
    inp = io.StringIO("".join(json.dumps(m) + "\n" for m in msgs))
    out = io.StringIO()
    mcp_server.serve(inp, out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_mcp_lists_and_answers_similar(kb_home: Path) -> None:
    init, tools, call, bad = _rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "similar", "arguments": {"lang": "scheme", "k": 3}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}},
    )  # fmt: skip
    assert init["result"]["serverInfo"]["name"] == "langsuite"
    assert {"similar", "ask", "query"} <= {t["name"] for t in tools["result"]["tools"]}
    data = json.loads(call["result"]["content"][0]["text"])
    assert not call["result"]["isError"] and len(data["data"]["neighbours"]) == 3
    assert bad["error"]["code"] == -32602


def test_webhook_signature_round_trip() -> None:
    body = b'{"x":1}'
    sig = webhooks.sign("s3cret", body, ts=1_000)
    assert webhooks.verify("s3cret", body, sig, now=1_100)
    assert not webhooks.verify("other", body, sig, now=1_100)
    assert not webhooks.verify("s3cret", body + b" ", sig, now=1_100)
    assert not webhooks.verify("s3cret", body, sig, now=2_000)  # stale: replay refused


@pytest.mark.parametrize(
    "url", ["http://example.org/h", "https://127.0.0.1/h", "https://10.0.0.5/"]
)
def test_webhook_urls_refused(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGSUITE_WEBHOOK_ALLOW_PRIVATE", raising=False)
    with pytest.raises(UsageError):
        webhooks.check_url(url)


def test_finding_saved_posts_signed_event(kb_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[tuple[bytes, str]] = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            got.append((body, self.headers[webhooks.HEADER]))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *a: Any) -> None:
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("LANGSUITE_WEBHOOK_ALLOW_PRIVATE", "1")
    try:
        added = _cli("--json", "webhook", "add", f"http://127.0.0.1:{srv.server_port}/h")
        secret = json.loads(added.stdout)["data"]["secret"]
        assert "secret" not in _cli("--json", "webhook", "list").stdout
        assert _cli("similar", "scheme", "--k", "2").exit_code == 0
        assert _cli("extract", "last").exit_code == 0
    finally:
        srv.shutdown()
    body, sig = got[-1]
    assert json.loads(body)["event"] == "finding.saved"
    assert webhooks.verify(secret, body, sig)


def test_failing_hook_disables_after_five(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSUITE_WEBHOOK_ALLOW_PRIVATE", "1")
    monkeypatch.setattr("langsuite.core.webhooks.time.sleep", lambda s: None)
    webhooks.add(tmp_path, "http://127.0.0.1:9/none", ["finding.saved"])
    for _ in range(5):
        webhooks.deliver(tmp_path, "finding.saved", {}, tries=1)
    assert webhooks.load(tmp_path)[0]["active"] is False


def test_digest_parse_and_slots() -> None:
    d = parse_digest(["weekly", "mon", "09:00", "macros", "top=3"])
    assert d == {"every": "weekly", "day": "mon", "time": "09:00", "tz": "Australia/Perth",
                 "query": "macros top=3"}  # fmt: skip
    # Tue 2026-11-03 02:00 UTC = 10:00 Perth, so the last slot is Mon 2 Nov 09:00 Perth
    slot = last_slot(d, datetime(2026, 11, 3, 2, 0, tzinfo=UTC))
    assert slot.isoformat() == "2026-11-02T09:00:00+08:00"
    for bad in (
        ["hourly"],
        ["weekly", "xyz", "09:00", "q"],
        ["daily", "25:00", "q"],
        ["daily", "09:00"],
    ):
        with pytest.raises(ValueError, match=r"\w"):
            parse_digest(bad)


def test_bot_digest_runs_once_per_slot(kb_home: Path) -> None:
    bot = Bot()
    chat = Chat(-5, 1, "ada", group=True, telegram_admin=True)
    assert "Digest set" in bot.handle("/digest daily 09:00 homoiconicity top=2", chat).plain  # type: ignore[union-attr]
    now = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)
    first = bot.due_digests(now)
    assert len(first) == 1 and "digest" in first[0][1].plain
    assert bot.due_digests(now) == []
    viewer = Chat(-5, 2, "bob", group=True)
    assert "Not allowed" in bot.handle("/digest off", viewer).plain  # type: ignore[union-attr]


def test_bot_mode_and_inline(kb_home: Path) -> None:
    bot = Bot()
    me = Chat(7, 7, "ada")
    assert "concise" in bot.handle("/mode concise", me).plain  # type: ignore[union-attr]
    assert "--mode" not in bot.handle("/r --top 2 --min-criteria 1", me).plain  # type: ignore[union-attr]
    cards = bot.inline("similar scheme --k 2", 7)
    assert cards and cards[0][0].startswith("/s scheme") and "Scheme" in cards[0][1]
    assert bot.inline("who designed haskell", 7)[0][0].startswith("/a")
    assert bot.inline("snippet fizzbuzz --lang python -o /etc/x", 7) == []
