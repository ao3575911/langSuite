"""Controlled feature vocabulary (SPEC §3). Bump VOCAB_VERSION on any id or category change."""

from __future__ import annotations

import re

VOCAB_VERSION = 1

# Facts are descriptive attributes; traits are yes/no language features.
FACTS: dict[str, tuple[str, str]] = {
    "appeared": ("Year first appeared", "Year the language was first released or described."),
    "creators": ("Creators", "People or organisations credited with creating it."),
    "website": ("Website", "Official home page."),
    "kind": ("Kind", "What sort of language it is (programming, markup, data, ...)."),
    "latest-version": ("Latest version", "Most recent version named by the source."),
    "extensions": ("File extensions", "File extensions used for source files."),
    "aliases": ("Aliases", "Other names and short names."),
    "interpreters": ("Interpreters", "Interpreter commands named in shebang lines."),
    "influenced-by": ("Influenced by", "Languages named as influences."),
}

# First matching rule wins; order matters.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Evaluation", ("Lazy", "Eval", "Strict")),
    (
        "Types",
        ("Typ", "Generic", "Inference", "Unions", "Enums", "Structs", "Null", "Variance"),
    ),
    ("Memory", ("Garbage", "Memory", "Pointer", "Reference", "Ownership")),
    (
        "Paradigm",
        (
            "Class",
            "Inherit",
            "Monad",
            "Pattern",
            "FirstClass",
            "Closure",
            "Function",
            "Method",
            "Trait",
            "Mixin",
            "Actor",
            "Macro",
            "Homoicon",
            "Polymorph",
            "Operator",
            "Async",
            "Coroutine",
            "Thread",
            "Concurren",
        ),
    ),
    ("Control flow", ("Loop", "Conditional", "Exception", "Switch", "Goto", "Iterator", "Break")),
    ("Modules", ("Import", "Module", "Package", "Namespace", "Librar", "Export")),
    (
        "Syntax",
        (
            "Comment",
            "Indent",
            "Semicolon",
            "Token",
            "String",
            "Literal",
            "Hex",
            "Octal",
            "Binary",
            "Integer",
            "Float",
            "Character",
            "Case",
            "Whitespace",
            "Line",
            "Assignment",
            "Parser",
            "Directive",
            "Regular",
            "Unicode",
            "Doc",
            "Terminator",
        ),
    ),
)

_TRAIT_KEY = re.compile(r"^(has|is)([A-Z][A-Za-z0-9]*)$")
# Booleans that describe the record, not the language's design.
_NOT_TRAITS = frozenset({"isLanguage", "isFinished", "isOpenSource"})


def is_trait_key(key: str) -> bool:
    return key not in _NOT_TRAITS and _TRAIT_KEY.match(key) is not None


def _kebab(text: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "-", text).lower()


def trait_id(key: str) -> str:
    """`hasTypeInference` -> `type-inference`; `isCaseSensitive` -> `case-sensitive`."""
    match = _TRAIT_KEY.match(key)
    if match is None:
        raise ValueError(key)
    return _kebab(match.group(2))


def trait_label(key: str) -> str:
    words = trait_id(key).replace("-", " ")
    return words[:1].upper() + words[1:]


def trait_category(key: str) -> str:
    stem = key[3:] if key.startswith("has") else key[2:]
    for category, needles in _CATEGORY_RULES:
        if any(n in stem for n in needles):
            return category
    return "Other"
