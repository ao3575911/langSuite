"""Run a CLI command in-process and capture its output (panes, MCP server)."""

from __future__ import annotations

import contextlib
import io
import os


def run_plain(args: list[str], width: int = 100) -> tuple[int, str]:
    from langsuite.cli.app import main

    out = io.StringIO()
    saved = {k: os.environ.get(k) for k in ("COLUMNS", "NO_COLOR")}
    os.environ.update(COLUMNS=str(width), NO_COLOR="1")
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                main(["--plain", *args])
            except SystemExit as stop:
                code = stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return code, out.getvalue().rstrip()
