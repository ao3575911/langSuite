"""1.0.1 hardening: friendly errors, exit codes, bot retries and error replies."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from langsuite.bot import telegram as tg
from langsuite.cli import app as cli
from langsuite.core.workspace import command_line


def test_usage_error_is_one_line(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(["--plain", "similar", "scheme", "--k", "-1"])
    err = capsys.readouterr().err
    assert stop.value.code == 2 and err.startswith("error:") and "Traceback" not in err
    assert "hint:" in err and "╭" not in err


def test_unexpected_error_exits_70(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("kaput")

    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(SystemExit) as stop:
        cli.main(["--plain", "--version"])
    assert stop.value.code == cli.EXIT_INTERNAL
    assert "Unexpected RuntimeError: kaput" in capsys.readouterr().err
    with pytest.raises(RuntimeError):
        cli.main(["--debug", "--version"])


def test_ctrl_c_exits_130(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def stop(*a: Any, **k: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "app", stop)
    with pytest.raises(SystemExit) as info:
        cli.main(["--plain", "--version"])
    assert info.value.code == 130 and "Interrupted." in capsys.readouterr().err


def test_finding_commands_keep_unicode() -> None:
    assert command_line("ask", {"question": "what is λ? 🐍"}) == 'langsuite ask "what is λ? 🐍"'


def test_corrupt_account_is_kept(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from langsuite.cli.account_cmds import local_key

    (tmp_path / "account.json").write_text("{not json", encoding="utf-8")
    key = local_key(tmp_path)
    assert key.startswith("c") and (tmp_path / "account.json.bad").exists()
    assert "unreadable" in capsys.readouterr().err
    assert json.loads((tmp_path / "account.json").read_text())["key"] == key


def test_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from telegram.error import TimedOut

    calls = []

    async def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise TimedOut()
        return "ok"

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    assert asyncio.run(tg.with_retries(flaky, "t")) == "ok" and len(calls) == 3


def test_retries_give_up(monkeypatch: pytest.MonkeyPatch) -> None:
    from telegram.error import NetworkError

    calls = []

    async def down() -> None:
        calls.append(1)
        raise NetworkError("down")

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    with pytest.raises(NetworkError):
        asyncio.run(tg.with_retries(down, "t"))
    assert len(calls) == tg.TRIES


def test_error_handler_always_replies() -> None:
    sent: list[str] = []

    class Msg:
        async def reply_text(self, text: str) -> None:
            sent.append(text)

    class Update:
        effective_message = Msg()

    class Ctx:
        error = RuntimeError("x")

    asyncio.run(tg.on_error(Update(), Ctx()))
    assert sent == [tg.SORRY]
    asyncio.run(tg.on_error(None, Ctx()))  # no message: logs only, no crash


def test_build_application_registers_error_handler() -> None:
    app = tg.build_application("123:abc")
    assert app.error_handlers
