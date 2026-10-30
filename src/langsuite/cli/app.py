"""Typer app: commands grouped by pillar, each with exactly one alias (SPEC §6c, §7)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import typer

from langsuite import __version__
from langsuite.cli.aliases import COMMANDS, Command, help_line
from langsuite.cli.output import make_console, plain_wanted, to_json
from langsuite.core.errors import LangsuiteError, NotBuiltYetError
from langsuite.core.modes import Mode, resolve_mode


@dataclass
class Ctx:
    mode: Mode
    json: bool
    plain: bool
    local: bool
    debug: bool


app = typer.Typer(
    name="langsuite",
    help="Research knowledge base of programming languages, with evidence.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
    pretty_exceptions_enable=False,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"langsuite {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    mode: Annotated[Mode | None, typer.Option("-m", "--mode", help="Output mode.")] = None,
    json_: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    plain: Annotated[bool, typer.Option("--plain", help="No colour or boxes.")] = False,
    local: Annotated[bool, typer.Option("--local", help="Local mode.")] = False,
    debug: Annotated[bool, typer.Option("--debug", help="Show tracebacks.")] = False,
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    ctx.obj = Ctx(resolve_mode(mode), json_, plain_wanted(plain), local, debug)


def _make_stub(cmd: Command) -> Callable[[typer.Context], None]:
    def stub(ctx: typer.Context) -> None:
        raise NotBuiltYetError(cmd.name, cmd.milestone)

    stub.__doc__ = cmd.help
    return stub


for _cmd in COMMANDS:
    _fn = _make_stub(_cmd)
    app.command(_cmd.name, help=help_line(_cmd), rich_help_panel=_cmd.panel)(_fn)
    app.command(_cmd.alias, help=f"Alias of {_cmd.name}.", hidden=True)(_fn)


def main(argv: list[str] | None = None) -> None:
    """Entry point with typed error handling: short messages, no tracebacks unless --debug."""
    args = sys.argv[1:] if argv is None else argv
    debug = "--debug" in args
    try:
        app(args=args, prog_name="langsuite")
    except LangsuiteError as err:
        if debug:
            raise
        if "--json" in args:
            payload = {"error": err.message, "hint": err.hint, "exit": int(err.exit_code)}
            typer.echo(to_json("error", payload))
        else:
            console = make_console(plain=plain_wanted("--plain" in args), stderr=True)
            console.print(f"[lw.error]error:[/] {err.message}")
            if err.hint:
                console.print(f"[lw.muted]hint: {err.hint}[/]")
        raise SystemExit(int(err.exit_code)) from None
