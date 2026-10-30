from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

from langsuite.cli.aliases import COMMANDS, PANELS, SUB_ALIASES, help_line
from langsuite.cli.app import app, main
from langsuite.cli.implemented import COMMAND_FUNCS, GROUP_APPS
from langsuite.core.errors import ExitCode

runner = CliRunner()
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_every_command_has_exactly_one_unique_alias() -> None:
    names = [c.name for c in COMMANDS]
    aliases = [c.alias for c in COMMANDS]
    assert len(set(names)) == len(names)
    assert len(set(aliases)) == len(aliases)
    assert not set(names) & set(aliases)
    assert not set(SUB_ALIASES) & (set(names) | set(aliases))


def test_spec_alias_table() -> None:
    expected = {
        "lang": "l",
        "feature": "ft",
        "query": "q",
        "similar": "s",
        "cluster": "c",
        "influence": "i",
        "like": "lk",
        "dashboard": "db",
        "ask": "a",
        "docs": "dc",
        "rank": "r",
        "compare": "cp",
        "diff": "df",
        "snippet": "sn",
        "guide": "g",
        "verify": "v",
        "extract": "x",
        "finding": "f",
        "note": "n",
        "workspace": "w",
        "base": "b",
        "inclusion": "inc",
        "account": "ac",
        "badges": "bg",
        "streak": "st",
        "settings": "set",
        "usage": "u",
        "login": "li",
        "logout": "lo",
        "ui": "t",
        "bot": "bt",
        "mode": "m",
    }
    assert {c.name: c.alias for c in COMMANDS} == expected


def test_help_lines_short_and_panels_valid() -> None:
    for c in COMMANDS:
        assert len(help_line(c)) <= 60, c.name
        assert c.panel in PANELS


def test_help_lists_names_aliases_and_groups() -> None:
    res = runner.invoke(app, ["--help"], env={"COLUMNS": "200", "NO_COLOR": "1"})
    assert res.exit_code == 0
    out = ANSI.sub("", res.output)
    for panel in PANELS:
        assert panel in out
    for c in COMMANDS:
        assert re.search(rf"\b{re.escape(c.name)}\b", out), c.name
        assert f"({c.alias})" in out, c.alias


STUBS = [c for c in COMMANDS if c.name not in COMMAND_FUNCS and c.name not in GROUP_APPS]


@pytest.mark.parametrize("cmd", STUBS, ids=lambda c: c.name)
def test_stub_and_alias_exit_no_result(cmd: object, capsys: pytest.CaptureFixture[str]) -> None:
    from langsuite.cli.aliases import Command

    assert isinstance(cmd, Command)
    for word in (cmd.name, cmd.alias):
        with pytest.raises(SystemExit) as ex:
            main(["--plain", word])
        assert ex.value.code == ExitCode.NO_RESULT
        err = capsys.readouterr().err
        assert "not built yet" in err and cmd.milestone in err
        assert "\x1b[" not in err and "Traceback" not in err


def test_json_error_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ex:
        main(["--json", "ask"])
    assert ex.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == 1 and payload["kind"] == "error"
    assert payload["data"]["exit"] == 2


def test_debug_reraises() -> None:
    from langsuite.core.errors import NotBuiltYetError

    with pytest.raises(NotBuiltYetError):
        main(["--debug", "cluster"])


def test_version_and_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ex:
        main(["--version"])
    assert ex.value.code == 0
    assert "langsuite" in capsys.readouterr().out
    with pytest.raises(SystemExit) as ex:
        main(["no-such-command"])
    assert ex.value.code == 2


def test_no_args_non_tty_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ex:
        main([])
    assert ex.value.code in (0, 2)
    assert "Usage" in capsys.readouterr().out


def test_ui_needs_tty(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ex:
        main(["--plain", "ui"])
    assert ex.value.code == ExitCode.DATA
    assert "interactive terminal" in capsys.readouterr().err


def test_ui_serve_command_line() -> None:
    from langsuite.cli.ui_cmd import serve_command

    cmd = serve_command(plain=True, mode="concise")
    assert cmd.endswith("-m langsuite --mode concise --plain ui")
