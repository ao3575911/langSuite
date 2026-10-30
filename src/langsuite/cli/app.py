"""Typer app: commands grouped by pillar, each with exactly one alias (SPEC §6c, §7)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import typer

from langsuite import __version__
from langsuite.cli.aliases import COMMANDS, SUB_ALIASES, Command, help_line
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
    plain_flag: bool = False


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
    from langsuite.cli.system_cmds import global_mode, workspace_mode

    chosen = resolve_mode(mode, workspace_mode(), global_mode())
    ctx.obj = Ctx(chosen, json_, plain_wanted(plain), local, debug, plain)


def _make_stub(cmd: Command) -> Callable[[typer.Context], None]:
    def stub(ctx: typer.Context) -> None:
        raise NotBuiltYetError(cmd.name, cmd.milestone)

    stub.__doc__ = cmd.help
    return stub


def _add_sub_aliases(sub: typer.Typer) -> None:
    """`ls`, `sh`, `rm` work wherever `list`, `show`, `remove` exist (SPEC §7)."""
    names = {c.name: c for c in sub.registered_commands}
    for short, full in SUB_ALIASES.items():
        target = names.get(full)
        if target is not None and short not in names and target.callback is not None:
            sub.command(short, hidden=True, help=f"Alias of {full}.")(target.callback)


def _register() -> None:
    from langsuite.cli.implemented import COMMAND_FUNCS, GROUP_APPS

    for cmd in COMMANDS:
        if cmd.name in GROUP_APPS:
            sub = GROUP_APPS[cmd.name]
            _add_sub_aliases(sub)
            app.add_typer(sub, name=cmd.name, help=help_line(cmd), rich_help_panel=cmd.panel)
            app.add_typer(sub, name=cmd.alias, help=f"Alias of {cmd.name}.", hidden=True)
            continue
        fn = COMMAND_FUNCS.get(cmd.name) or _make_stub(cmd)
        app.command(cmd.name, help=help_line(cmd), rich_help_panel=cmd.panel)(fn)
        app.command(cmd.alias, help=f"Alias of {cmd.name}.", hidden=True)(fn)


_register()


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def main(argv: list[str] | None = None) -> None:
    """Entry point with typed error handling: short messages, no tracebacks unless --debug."""
    args = sys.argv[1:] if argv is None else argv
    if not args and _interactive():
        args = ["ui"]
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
