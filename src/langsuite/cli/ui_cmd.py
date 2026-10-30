"""`langsuite ui` — open the Textual app in the terminal, or serve it to a browser."""

from __future__ import annotations

import os
import shlex
import sys
from typing import Annotated

import typer

from langsuite.core.errors import DataError


def ui(
    ctx: typer.Context,
    serve: Annotated[bool, typer.Option("--serve", help="Serve the app to a browser.")] = False,
    host: Annotated[str, typer.Option("--host", help="Bind address for --serve.")] = "localhost",
    port: Annotated[int, typer.Option("--port", help="Port for --serve.", min=1, max=65535)] = 8000,
) -> None:
    """Open the app (terminal or browser).

    Example: langsuite ui --serve --port 8000
    """
    obj = ctx.obj
    plain = bool(getattr(obj, "plain_flag", False)) or os.environ.get("LANGSUITE_A11Y") == "1"
    mode = str(getattr(obj, "mode", "default"))
    if serve:
        _serve(host, port, plain, mode)
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise DataError(
            "The app needs an interactive terminal.",
            hint="Run it in a terminal, or use `langsuite ui --serve` for a browser.",
        )
    from langsuite.tui.app import LangsuiteApp

    LangsuiteApp(plain=plain, mode=mode).run()


def serve_command(plain: bool, mode: str) -> str:
    parts = [sys.executable, "-m", "langsuite", "--mode", mode]
    if plain:
        parts.append("--plain")
    parts.append("ui")
    return shlex.join(parts)


def _serve(host: str, port: int, plain: bool, mode: str) -> None:  # pragma: no cover - network
    from textual_serve.server import Server

    typer.echo(f"Serving langsuite at http://{host}:{port}  (ctrl+c to stop)")
    try:
        Server(serve_command(plain, mode), host=host, port=port, title="langsuite").serve()
    except OSError as err:
        raise DataError(
            f"Could not serve on {host}:{port}: {err.strerror or err}.",
            hint="Pick another port with --port.",
        ) from err
