"""mode (M5h): show or set the output mode for this workspace or everywhere."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from langsuite.cli.kb_cmds import _console, _emit, _json
from langsuite.core import settings
from langsuite.core.modes import Mode
from langsuite.core.workspace import Workspace, active_slug


def workspace_mode() -> Mode | None:
    try:
        ws = Workspace(None, active_slug())
        value = ws.meta.get("mode") if ws.exists() else None
        return Mode(value) if value else None
    except Exception:
        return None


def global_mode() -> Mode | None:
    value = settings.load().get("mode")
    try:
        return Mode(value) if value else None
    except ValueError:
        return None


def mode(
    ctx: typer.Context,
    value: Annotated[Mode | None, typer.Argument(help="concise, default or thorough.")] = None,
    everywhere: Annotated[
        bool, typer.Option("--global", help="Set for all workspaces, not just this one.")
    ] = False,
    reset: Annotated[bool, typer.Option("--reset", help="Clear the saved mode.")] = False,
) -> None:
    """Show or set the output mode. Precedence: --mode flag > workspace > global > default.

    Example: langsuite mode concise --global
    """
    if value is not None or reset:
        saved = None if reset or value is None else value.value
        if everywhere:
            settings.save({"mode": saved})
        else:
            Workspace.open()._set_meta(mode=saved)
    ws, gl = workspace_mode(), global_mode()
    eff = ws or gl or Mode.DEFAULT
    data: dict[str, Any] = {
        "effective": eff.value,
        "workspace": ws.value if ws else None,
        "global": gl.value if gl else None,
    }
    if _json(ctx):
        _emit("mode", data)
        return
    con = _console(ctx)
    con.print(f"mode: [b]{eff.value}[/]")
    where = f"workspace: {data['workspace'] or '—'} · global: {data['global'] or '—'}"
    con.print(f"[lw.muted]{where} · a --mode flag wins over both[/]")


# ----- webhooks (M5h) ------------------------------------------------------------

webhook_app = typer.Typer(help="Signed outbound webhooks for this workspace.", no_args_is_help=True)


@webhook_app.command("add")
def webhook_add(
    ctx: typer.Context,
    url: Annotated[str, typer.Argument(help="https:// receiver URL.")],
    event: Annotated[
        list[str] | None, typer.Option("--event", "-e", help="finding.saved or digest.ready.")
    ] = None,
) -> None:
    """Register a receiver; the signing secret is shown once.

    Example: langsuite webhook add https://example.org/hooks/langsuite -e finding.saved
    """
    from langsuite.core import webhooks

    hook = webhooks.add(Workspace.open().path, url, list(event or webhooks.EVENTS))
    if _json(ctx):
        _emit("webhook", hook)
        return
    con = _console(ctx)
    con.print(f"{hook['id']} → {hook['url']} ({', '.join(hook['events'])})")
    con.print(f"secret (shown once, verify `{webhooks.HEADER}`): {hook['secret']}")


@webhook_app.command("list")
def webhook_list(ctx: typer.Context) -> None:
    """List receivers (secrets hidden)."""
    from langsuite.core import webhooks

    rows = [
        {k: v for k, v in h.items() if k != "secret"} for h in webhooks.load(Workspace.open().path)
    ]
    if _json(ctx):
        _emit("webhooks", rows)
        return
    con = _console(ctx)
    if not rows:
        con.print("No webhooks. Add one with `langsuite webhook add https://…`.")
    for h in rows:
        state = "active" if h["active"] else f"disabled after {h['fails']} failures"
        con.print(f"{h['id']}  {h['url']}  {', '.join(h['events'])}  [lw.muted]{state}[/]")


@webhook_app.command("remove")
def webhook_remove(ctx: typer.Context, hook_id: Annotated[str, typer.Argument()]) -> None:
    """Remove a receiver."""
    from langsuite.core import webhooks

    webhooks.remove(Workspace.open().path, hook_id)
    _console(ctx).print(f"Removed {hook_id}.")


@webhook_app.command("test")
def webhook_test(ctx: typer.Context) -> None:
    """Send a signed `digest.ready` test event to every receiver that wants it."""
    ws = Workspace.open()
    from langsuite.core import webhooks

    done = webhooks.deliver(ws.path, "digest.ready", {"workspace": ws.slug, "test": True})
    _console(ctx).print(f"Delivered to: {', '.join(done) or 'none'}")
