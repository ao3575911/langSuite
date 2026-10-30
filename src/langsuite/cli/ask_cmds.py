"""ask, guide (SPEC §7, M5d): cited answers from the knowledge base, or an abstention."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.markup import escape

from langsuite.cli.kb_cmds import _console, _emit, _json, _mode
from langsuite.core import ask as qa
from langsuite.core.modes import Mode
from langsuite.core.workspace import open_kb, remember


def _show(ctx: typer.Context, ans: qa.Answer) -> None:
    if _json(ctx):
        _emit("answer", ans.to_json())
        return
    con = _console(ctx)
    data = ans.to_json()
    for s in data["sentences"]:
        marks = "".join(f"[{n}]" for n in s["cites"])
        con.print(f"{escape(s['text'])} [lw.muted]{escape(marks)}[/]")
    if ans.code:
        from rich.syntax import Syntax

        con.print(Syntax(ans.code, ans.code_lang or "text", word_wrap=True))
    if data["citations"]:
        con.print("[b]Sources[/]")
        thorough = _mode(ctx) is Mode.THOROUGH
        for c in data["citations"]:
            con.print(
                f"  [{c['n']}] {escape(c['source'])} · {escape(c['url'])} [lw.muted]{c['id']}[/]"
            )
            if thorough:
                con.print(f"      [lw.muted]{escape(c['excerpt'][:200])}[/]")
    con.print(f"[lw.muted]{qa.METHOD} · every sentence cited or no answer · {ans.snapshot}[/]")


def ask(
    ctx: typer.Context,
    question: Annotated[list[str], typer.Argument(help="Your question, in plain words.")],
) -> None:
    """Ask a question; answers cite the knowledge base, or say they can't.

    Example: langsuite ask "does haskell have type inference"
    """
    text = " ".join(question)
    with open_kb() as kb:
        ans = qa.answer(kb, text)
    remember("ask", {"question": text})
    _show(ctx, ans)


def guide(
    ctx: typer.Context,
    lang: Annotated[str, typer.Argument(help="Language to get started with.")],
) -> None:
    """How to start with a language and when it fits, from sourced facts.

    Example: langsuite guide haskell
    """
    with open_kb() as kb:
        ans = qa.guide(kb, lang)
    remember("guide", {"lang": lang})
    _show(ctx, ans)
