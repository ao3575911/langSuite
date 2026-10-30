"""`verify` and `snippet` (SPEC §7, §10 M4). Thin adapters over langsuite.verify."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.markup import escape
from rich.syntax import Syntax
from rich.table import Table

from langsuite.cli.kb_cmds import _console, _emit, _json, _mode
from langsuite.core import saas
from langsuite.core.errors import DataError, ExitCode, UsageError
from langsuite.core.lazy import lazy
from langsuite.core.modes import Mode
from langsuite.core.workspace import open_kb, remember
from langsuite.verify import evidence as vev
from langsuite.verify.sandbox import (
    DockerUnavailableError,
    Limits,
    Status,
    VerifyResult,
    docker_available,
    run_code,
)
from langsuite.verify.toolchains import BY_LANG, TOOLCHAINS, Toolchain, toolchain_for

if TYPE_CHECKING:
    from langsuite.verify import rosetta
else:
    rosetta = lazy("langsuite.verify.rosetta")


FAILED_EXIT = 1  # the code ran and failed (like a test runner); refusals exit 3
_STYLE = {
    Status.PASS: "lw.ok",
    Status.FAIL: "lw.error",
    Status.TIMEOUT: "lw.warn",
    Status.MEMORY: "lw.warn",
    Status.REFUSED: "lw.error",
    Status.ERROR: "lw.error",
}
_EXT = {Path(t.filename).suffix.lower(): t.lang for t in TOOLCHAINS}


def badge(res: VerifyResult) -> str:
    mark = "✓ verified" if res.ok else f"✗ {res.status.value}"
    return f"[{_STYLE[res.status]}]{mark}[/]"


def _resolve_lang(raw: str) -> str:
    with open_kb() as kb:
        return kb.resolve(raw).id


def _langs(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [_resolve_lang(x.strip()) for x in raw.split(",") if x.strip()]


def _need_docker() -> None:
    if not docker_available():
        raise DockerUnavailableError()


def _print_toolchains(ctx: typer.Context) -> None:
    if _json(ctx):
        _emit("toolchains", [t.to_json() for t in TOOLCHAINS])
        return
    con = _console(ctx)
    table = Table(box=None, header_style="lw.title", pad_edge=False)
    for col in ("lang", "toolchain", "image", "digest", "timeout"):
        table.add_column(col, style="lw.accent" if col == "lang" else None, no_wrap=True)
    for t in TOOLCHAINS:
        table.add_row(t.lang, t.name, t.ref, t.digest[:19] + "…", f"{t.timeout_s:g}s")
    con.print(table)
    con.print(
        f"[lw.muted]{len(TOOLCHAINS)} toolchains · images pinned by digest · no network, "
        "read-only root, non-root, caps dropped, 256 MB, 64 pids[/]"
    )


def _print_result(ctx: typer.Context, res: VerifyResult, label: str) -> None:
    con = _console(ctx)
    con.print(f"{badge(res)} {escape(label)} [lw.muted]· {escape(res.reason)}[/]")
    mode = _mode(ctx)
    if res.stdout and mode is not Mode.CONCISE:
        con.print("[lw.title]stdout[/]")
        con.print(escape(res.stdout.rstrip("\n")), markup=False)
    if res.stderr and (not res.ok or mode is Mode.THOROUGH):
        con.print("[lw.title]stderr[/]")
        con.print(escape(res.stderr.rstrip("\n")[-2000:]), markup=False)
    foot = f"{res.toolchain} · {res.image}@{res.digest[:19]}… · {res.duration_ms} ms"
    if res.cached:
        foot += " · cached"
    foot += f" · {res.evidence_id}"
    con.print(f"[lw.muted]{escape(foot)}[/]")


def _exit_for(res: VerifyResult) -> None:
    if res.status is Status.REFUSED:
        raise typer.Exit(int(ExitCode.DATA))
    if res.status is not Status.PASS:
        raise typer.Exit(FAILED_EXIT)


def verify(
    ctx: typer.Context,
    file: Annotated[str | None, typer.Argument(help="Source file to run, or - for stdin.")] = None,
    lang: Annotated[
        str | None, typer.Option("--lang", "-L", help="Language (default: from extension).")
    ] = None,
    expect: Annotated[
        str | None, typer.Option("--expect", help="Expected stdout (trailing space ignored).")
    ] = None,
    expect_file: Annotated[
        Path | None, typer.Option("--expect-file", help="File with the expected stdout.")
    ] = None,
    stdin_file: Annotated[
        Path | None, typer.Option("--stdin", help="File fed to the program's stdin.")
    ] = None,
    timeout: Annotated[
        float | None, typer.Option("--timeout", min=1, max=120, help="Seconds (wall clock).")
    ] = None,
    pull: Annotated[
        bool, typer.Option("--pull/--no-pull", help="Pull the pinned image if missing.")
    ] = True,
    cache: Annotated[bool, typer.Option("--cache/--no-cache", help="Reuse a cached run.")] = True,
    toolchains: Annotated[
        bool, typer.Option("--toolchains", help="List the 20 pinned toolchains.")
    ] = False,
    task: Annotated[
        str | None, typer.Option("--task", help="Verify Rosetta solutions for a task.")
    ] = None,
) -> None:
    """Run code in the Docker sandbox and report pass/fail.

    Example: langsuite verify hello.rs --expect "Hello world!"
    """
    if toolchains:
        _print_toolchains(ctx)
        return
    if task:
        _verify_task(ctx, task, lang, pull)
        return
    if not file:
        raise UsageError(
            "Give a file to verify, --task, or --toolchains.",
            hint="e.g. langsuite verify main.py, or langsuite verify --toolchains",
        )
    saas.meter("verify")
    if file == "-":
        code = sys.stdin.read()
    else:
        path = Path(file)
        if not path.is_file():
            raise UsageError(f"No such file: {file}")
        code = path.read_text(encoding="utf-8")
    if lang:
        lang_id = _resolve_lang(lang)
    else:
        suffix = Path(file).suffix.lower() if file != "-" else ""
        if suffix not in _EXT:
            raise UsageError("Cannot tell the language.", hint="Pass --lang, e.g. --lang python.")
        lang_id = _EXT[suffix]
    tc = toolchain_for(lang_id)
    if expect_file:
        expect = expect_file.read_text(encoding="utf-8")
    stdin = stdin_file.read_text(encoding="utf-8") if stdin_file else ""
    _need_docker()
    res = run_code(
        tc,
        code,
        stdin=stdin,
        expected=expect,
        limits=Limits(timeout_s=timeout),
        pull=pull,
        use_cache=cache,
    )
    remember(
        "verify",
        {"lang": lang_id, "code": code, "code_sha256": res.code_sha256, "expected": expect},
    )
    if _json(ctx):
        _emit("verify", res.to_json())
    else:
        _print_result(ctx, res, f"{file} ({tc.name})")
    _exit_for(res)


def _verify_task(ctx: typer.Context, query: str, langs_raw: str | None, pull: bool) -> None:
    task = rosetta.find_task(rosetta.load_tasks(), query)
    langs = _langs(langs_raw) or sorted(set(task.solutions) & set(BY_LANG))
    missing = [x for x in langs if x not in task.solutions or x not in BY_LANG]
    _need_docker()
    checks = vev.check_many([(task, x) for x in langs], pull=pull)
    if _json(ctx):
        _emit(
            "verify-task",
            {"task": task.to_json() | {"solutions": None}, "checks": [c.to_json() for c in checks]},
        )
    else:
        con = _console(ctx)
        con.print(f"[lw.title]{escape(task.title)}[/] [lw.muted]({task.permalink})[/]")
        table = Table(box=None, header_style="lw.title", pad_edge=False)
        for col in ("lang", "status", "variant", "reason"):
            table.add_column(col, style="lw.accent" if col == "lang" else None)
        for c in checks:
            variant = f"{(c.variant or 0) + 1}/{len(c.task.solutions[c.lang].variants)}"
            table.add_row(c.lang, badge(c.result), variant, escape(c.result.reason))
        con.print(table)
        ok = sum(c.verified for c in checks)
        oracle = "output checked" if task.expected else "exit code only"
        con.print(f"[lw.muted]{ok} of {len(checks)} verified · {oracle} · {task.licence}[/]")
        if missing:
            con.print(f"[lw.muted]No solution or toolchain: {', '.join(missing)}[/]")
    if not any(c.verified for c in checks):
        raise typer.Exit(FAILED_EXIT)


def snippet(
    ctx: typer.Context,
    task: Annotated[str | None, typer.Argument(help='Task, e.g. "fizzbuzz".')] = None,
    lang: Annotated[
        str | None, typer.Option("--lang", "-L", help="Languages, comma separated.")
    ] = None,
    run: Annotated[
        bool, typer.Option("--verify/--no-verify", help="Run it in the sandbox first.")
    ] = True,
    tasks: Annotated[bool, typer.Option("--tasks", help="List tasks in the Rosetta pack.")] = False,
    fetch: Annotated[
        bool, typer.Option("--fetch", help="Download Rosetta tasks into your data dir.")
    ] = False,
) -> None:
    """A verified, attributed code snippet for a task (Rosetta pack).

    Example: langsuite snippet fizzbuzz --lang python,rust
    """
    if fetch:
        _fetch(ctx, task)
        return
    pack = rosetta.load_tasks()
    if tasks:
        _list_tasks(ctx, pack)
        return
    if not task:
        raise UsageError("Name a task.", hint="See `langsuite snippet --tasks`.")
    found = rosetta.find_task(pack, task)
    langs = _langs(lang) or ["python"]
    can_run = run and docker_available()
    out: list[dict[str, object]] = []
    con = _console(ctx)
    for n, lid in enumerate(langs):
        if lid not in found.solutions:
            msg = f"No {lid} solution for “{found.title}” in the pack."
            if _json(ctx):
                out.append({"lang": lid, "missing": True})
            else:
                con.print(f"[lw.warn]{escape(msg)}[/]")
            continue
        sol = found.solutions[lid]
        check = vev.check_solution(found, lid) if can_run and lid in BY_LANG else None
        code = check.code if check else sol.code
        if n == 0 or not out:
            remember("snippet", {"task": found.title, "lang": lid})
        if _json(ctx):
            item: dict[str, object] = {
                "task": found.title,
                "lang": lid,
                "code": code,
                "attribution": found.attribution,
                "verified": bool(check and check.verified),
            }
            if check:
                item["check"] = check.to_json()
            out.append(item)
            continue
        _print_snippet(ctx, found, lid, code, check, run, lid in BY_LANG)
    if _json(ctx):
        _emit("snippet", out)
    if not any(lid in found.solutions for lid in langs):
        raise typer.Exit(int(ExitCode.NO_RESULT))


def _print_snippet(
    ctx: typer.Context,
    task: rosetta.Task,
    lid: str,
    code: str,
    check: vev.SolutionCheck | None,
    asked: bool,
    has_tc: bool,
) -> None:
    con = _console(ctx)
    if check and check.verified:
        status = badge(check.result)
    elif check:
        status = f"{badge(check.result)} [lw.muted](no page variant passed)[/]"
    elif not has_tc:
        status = "[lw.muted]unverified · no toolchain for this language[/]"
    elif asked:
        status = "[lw.warn]unverified · Docker not available[/]"
    else:
        status = "[lw.muted]unverified · --no-verify[/]"
    con.print(f"[lw.title]{escape(task.title)}[/] · [lw.accent]{lid}[/] {status}")
    lexer = {"cpp": "cpp", "common-lisp": "common-lisp", "r": "r"}.get(lid, lid)
    con.print(Syntax(code.rstrip("\n"), lexer, theme="ansi_dark", word_wrap=True))
    con.print(f"[lw.cite]{escape(task.attribution)}[/]")
    if check and _mode(ctx) is not Mode.CONCISE:
        r = check.result
        con.print(
            f"[lw.muted]{escape(r.toolchain)} · {escape(r.reason)} · "
            f"{'output checked' if r.expected_checked else 'exit code only'} · {r.evidence_id}[/]"
        )


def _list_tasks(ctx: typer.Context, pack: dict[str, rosetta.Task]) -> None:
    if _json(ctx):
        _emit(
            "snippet-tasks",
            [
                {"task": t.title, "slug": s, "languages": len(t.solutions), "url": t.permalink}
                for s, t in sorted(pack.items())
            ],
        )
        return
    con = _console(ctx)
    if not pack:
        raise DataError("No Rosetta pack found.", hint="Run `langsuite snippet --fetch`.")
    table = Table(box=None, header_style="lw.title", pad_edge=False)
    for col in ("slug", "task", "languages", "oracle", "with toolchain"):
        table.add_column(col, style="lw.accent" if col == "slug" else None)
    for slug, t in sorted(pack.items()):
        tc = len(set(t.solutions) & set(BY_LANG))
        table.add_row(
            slug, escape(t.title), str(len(t.solutions)), "✓" if t.expected else "", str(tc)
        )
    con.print(table)
    con.print("[lw.muted]Rosetta Code · share-alike data pack, kept outside the package[/]")


def _fetch(ctx: typer.Context, task: str | None) -> None:
    titles = [task] if task else list(rosetta.DEFAULT_TASKS)
    dest = rosetta.user_pack_dir()
    con = _console(ctx)
    with open_kb() as kb:
        known = {lang.id for lang in kb.languages}

        def resolve(header: str) -> str | None:
            try:
                return kb.resolve(header).id
            except UsageError:
                return None
            except Exception:
                return None

        saved = []
        for title in titles:
            t = rosetta.fetch_task(title, resolve)
            path = rosetta.save_task(t, dest, [k for k in t.solutions if k in known])
            saved.append({"task": t.title, "revid": t.revid, "path": str(path)})
            if not _json(ctx):
                con.print(f"Fetched [lw.accent]{escape(t.title)}[/] rev {t.revid} → {path}")
    if _json(ctx):
        _emit("snippet-fetch", saved)
    else:
        con.print("[lw.muted]Licence and attribution kept per task.[/]")


__all__ = ["Toolchain", "badge", "snippet", "verify"]
