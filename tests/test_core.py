from __future__ import annotations

import json

from langwish.cli.output import THEME, make_console, plain_wanted, to_json
from langwish.core.errors import AuthError, DataError, ExitCode, QuotaError
from langwish.core.modes import Mode, resolve_mode


def test_mode_precedence() -> None:
    assert resolve_mode() is Mode.DEFAULT
    assert resolve_mode(global_=Mode.CONCISE) is Mode.CONCISE
    assert resolve_mode(workspace=Mode.THOROUGH, global_=Mode.CONCISE) is Mode.THOROUGH
    assert resolve_mode(Mode.CONCISE, Mode.THOROUGH, Mode.DEFAULT) is Mode.CONCISE


def test_exit_codes() -> None:
    assert DataError("x").exit_code is ExitCode.DATA
    assert int(ExitCode.DATA) == 3
    assert AuthError("x").exit_code == 4
    assert QuotaError("x", hint="h").hint == "h"


def test_plain_detection(monkeypatch: object) -> None:
    import pytest

    mp = monkeypatch
    assert isinstance(mp, pytest.MonkeyPatch)
    assert plain_wanted(True)
    mp.setenv("NO_COLOR", "1")
    assert plain_wanted(False)


def test_console_and_json() -> None:
    assert "lw.title" in THEME.styles
    c = make_console(plain=True)
    with c.capture() as cap:
        c.print("[lw.ok]ok[/]")
    assert cap.get() == "ok\n"
    assert make_console().stderr is False
    assert json.loads(to_json("k", {"b": 1}))["data"] == {"b": 1}
