"""login, logout, usage (SPEC M5i): device login, local quota and invoice preview."""

from __future__ import annotations

import typer

from langsuite.cli.kb_cmds import _console, _emit, _json
from langsuite.core import saas


def login(ctx: typer.Context) -> None:
    """Sign in with a device code (needs LANGSUITE_API_URL; the hosted service is not live).

    Example: langsuite login
    """
    server = saas.server_url()
    con = _console(ctx)

    def show(uri: str, code: str) -> None:
        con.print(f"Open {uri} and enter the code {code}")

    res = saas.device_login(server, show=show)
    if _json(ctx):
        _emit("login", res)
        return
    con.print(f"Signed in to {res['server']} on the {res['plan']} plan.")


def logout(ctx: typer.Context) -> None:
    """Sign out and forget the saved token.

    Example: langsuite logout
    """
    had = saas.logout()
    if _json(ctx):
        _emit("logout", {"signed_out": had})
        return
    _console(ctx).print("Signed out." if had else "You were not signed in.")


def usage(ctx: typer.Context) -> None:
    """Plan, this month's metered use and quota, and an invoice preview.

    Example: langsuite usage
    """
    u = saas.usage()
    if _json(ctx):
        _emit("usage", u.to_json())
        return
    con = _console(ctx)
    con.print(f"Plan: {u.plan} · {u.period} · {u.used}/{u.quota} metered runs ({u.percent}%)")
    for k, n in u.by_kind.items():
        con.print(f"  {k}: {n}")
    inv = saas.invoice_preview(u)
    con.print(
        f"Invoice preview: {inv['total_cents'] / 100:.2f} {inv['currency'].upper()} "
        "(nothing is charged)"
    )
