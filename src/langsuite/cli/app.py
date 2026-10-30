"""Typer app: commands grouped by pillar, each with exactly one alias (SPEC §6c, §7)."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, NoReturn

import typer
from rich.markup import escape
from typer import Abort
from typer._click.exceptions import ClickException, NoArgsIsHelpError, UsageError

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


ISSUES_URL = "https://github.com/ao3575911/langsuite/issues/new/choose"
EXIT_INTERRUPTED = 130
EXIT_INTERNAL = 70


def _fail(args: list[str], message: str, hint: str | None, code: int) -> NoReturn:
    """One friendly line (plus a hint) on stderr, or a JSON error object with --json."""
    if "--json" in args:
        typer.echo(to_json("error", {"error": message, "hint": hint, "exit": code}))
    else:
        console = make_console(plain=plain_wanted("--plain" in args), stderr=True)
        console.print(f"[lw.error]error:[/] {escape(message)}")
        if hint:
            console.print(f"[lw.muted]hint: {escape(hint)}[/]")
    raise SystemExit(code)


def main(argv: list[str] | None = None) -> None:
    """Entry point with typed error handling: short messages, no tracebacks unless --debug."""
    args = sys.argv[1:] if argv is None else argv
    if not args and _interactive():
        args = ["ui"]
    debug = "--debug" in args
    try:
        rv = app(args=args, prog_name="langsuite", standalone_mode=False)
    except LangsuiteError as err:
        if debug:
            raise
        _fail(args, err.message, err.hint, int(err.exit_code))
    except NoArgsIsHelpError as err:
        err.show()
        raise SystemExit(err.exit_code) from None
    except UsageError as err:
        if debug:
            raise
        path = err.ctx.command_path if err.ctx else "langsuite"
        _fail(args, err.format_message(), f"See `{path} -h`.", err.exit_code)
    except ClickException as err:
        if debug:
            raise
        _fail(args, err.format_message(), None, err.exit_code)
    except (KeyboardInterrupt, Abort):
        if debug:
            raise
        _fail(args, "Interrupted.", None, EXIT_INTERRUPTED)
    except BrokenPipeError:
        # Output piped into `head` and friends: stop quietly, like other CLI tools.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0) from None
    except Exception as err:
        if debug:
            raise
        _fail(
            args,
            f"Unexpected {type(err).__name__}: {err}".rstrip(": "),
            f"Re-run with --debug for details, and report it at {ISSUES_URL}",
            EXIT_INTERNAL,
        )
    if rv == EXIT_INTERRUPTED:  # typer turns Ctrl-C into Exit(130)
        _fail(args, "Interrupted.", None, EXIT_INTERRUPTED)
    raise SystemExit(rv if isinstance(rv, int) else 0)
