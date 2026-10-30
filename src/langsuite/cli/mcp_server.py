"""`langsuite mcp`: a stdio MCP server exposing read-only langsuite tools (SPEC §6d, M5h).

Newline-delimited JSON-RPC 2.0. Tools run the CLI in-process with `--json`, so agents get the
same data, citations and evidence ids as the CLI. Nothing here writes to a workspace.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import IO, Any

from langsuite import __version__
from langsuite.cli.inproc import run_plain

PROTOCOL = "2025-06-18"


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


_STR = {"type": "string"}
TOOLS: dict[str, tuple[str, dict[str, Any], Callable[[dict[str, Any]], list[str]]]] = {
    "similar": (
        "Languages most like a language, with shared traits and evidence.",
        _schema({"lang": _STR, "k": {"type": "integer", "minimum": 1, "maximum": 50}}, ["lang"]),
        lambda a: ["similar", str(a["lang"]), "--k", str(a.get("k", 10))],
    ),
    "ask": (
        "A cited answer from the knowledge base, or an explicit abstention.",
        _schema({"question": _STR}, ["question"]),
        lambda a: ["ask", str(a["question"])],
    ),
    "lang_show": (
        "One language's sourced profile.",
        _schema({"lang": _STR}, ["lang"]),
        lambda a: ["lang", "show", str(a["lang"])],
    ),
    "query": (
        "Filter languages with the query DSL, e.g. 'homoiconicity year<1990'.",
        _schema({"text": _STR}, ["text"]),
        lambda a: ["query", str(a["text"])],
    ),
    "rank": (
        "Scores and grades (criteria/1), optionally filtered.",
        _schema({"filter": _STR, "top": {"type": "integer", "minimum": 1}}, []),
        lambda a: (
            ["rank", "--top", str(a.get("top", 10))]
            + (["--filter", str(a["filter"])] if a.get("filter") else [])
        ),
    ),
}


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    mid = msg.get("id")
    method = msg.get("method", "")
    if mid is None:
        return None  # notification
    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "langsuite", "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {
            "tools": [
                {"name": n, "description": d, "inputSchema": s} for n, (d, s, _) in TOOLS.items()
            ]
        }
    elif method == "tools/call":
        params = msg.get("params") or {}
        tool = TOOLS.get(str(params.get("name")))
        if tool is None:
            return _err(mid, -32602, f"Unknown tool {params.get('name')!r}")
        try:
            args = tool[2](params.get("arguments") or {})
        except KeyError as missing:
            return _err(mid, -32602, f"Missing argument {missing}")
        code, out = run_plain(["--json", *args])
        result = {"content": [{"type": "text", "text": out}], "isError": code != 0}
    else:
        return _err(mid, -32601, f"Method not found: {method}")
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve(inp: IO[str] = sys.stdin, out: IO[str] = sys.stdout) -> None:
    for line in inp:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply: dict[str, Any] | None = _err(None, -32700, "Parse error")
        else:
            reply = handle(msg) if isinstance(msg, dict) else _err(None, -32600, "Invalid")
        if reply is not None:
            out.write(json.dumps(reply) + "\n")
            out.flush()


def mcp() -> None:
    """Serve langsuite tools over MCP (stdio) for other agents; read-only.

    Example: langsuite mcp   (configure your MCP client to run this command)
    """
    serve()
