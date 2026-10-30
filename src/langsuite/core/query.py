"""Structured query DSL (SPEC §7 `query`, §6b `/q`; M2).

Grammar (case-insensitive keywords)::

    query   := expr? control*            control := sort=[-]FIELD | top=N
    expr    := term_or
    term_or := term_and ("or" term_and)*
    term_and:= unary (["and"] unary)*    # juxtaposition means "and"
    unary   := ("not" | "!") unary | "(" expr ")" | cond
    cond    := NAME [OP VALUE]           OP := = != >= <= > < ~

A bare NAME means "has this feature". ``feature=yes|no|unknown`` tests the sourced
value (unknown = no source says either way). Language fields: name, id, kind, year
(alias appeared), rank, traits (number of known traits), ext, alias, creator, source,
website. Any other ``key=value`` is a feature shorthand: ``eval=lazy`` finds the one
feature whose id contains ``lazy`` and relates to ``eval`` (``lazy-evaluation``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langsuite.core.errors import LangsuiteError, NoResultError
from langsuite.core.kb import Feature, KnowledgeBase, Language

QUERY_VERSION = 1
OPS = ("!=", ">=", "<=", "=", ">", "<", "~")
NUMERIC = {"year": "appeared", "appeared": "appeared", "rank": "rank", "traits": "traits"}
TEXT = {"name": "name", "id": "id", "kind": "kind", "website": "website"}
MULTI = {
    "ext": "extensions",
    "extension": "extensions",
    "alias": "aliases",
    "creator": "creators",
    "creators": "creators",
    "source": "sources",
}
SORTABLE = ("rank", "name", "year", "traits", "id", "kind")
RANK_FIELDS = ("score", "grade", "paradigm")
FEATURE_VALUES = {"yes": "yes", "true": "yes", "no": "no", "false": "no", "unknown": "unknown"}
MAX_QUERY_LEN = 2000


class QueryError(LangsuiteError):
    """Invalid query text. `position` is the 0-based character offset of the problem."""

    exit_code = NoResultError.exit_code

    def __init__(self, message: str, position: int, text: str, hint: str | None = None) -> None:
        caret = f"{text}\n{' ' * position}^"
        super().__init__(message, hint=(hint + "\n" if hint else "") + caret)
        self.position = position
        self.text = text


@dataclass(frozen=True)
class Token:
    kind: str  # word | op | lparen | rparen
    value: str
    pos: int


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<lparen>\() | (?P<rparen>\)) |
        (?P<op>!=|>=|<=|=|>|<|~) |
        (?P<bang>!) |
        "(?P<dq>[^"]*)" | '(?P<sq>[^']*)' |
        (?P<word>[^\s()=!<>~"']+)
    )""",
    re.VERBOSE,
)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        m = _TOKEN.match(text, pos)
        if m is None or m.end() == pos:
            start = pos + (len(text[pos:]) - len(text[pos:].lstrip()))
            raise QueryError(f"Unexpected character `{text[start]}`.", start, text)
        start = m.start(m.lastgroup or 0)
        group = m.lastgroup
        if group in ("dq", "sq"):
            tokens.append(Token("word", m.group(group), start - 1))
        elif group == "bang":
            tokens.append(Token("word", "not", start))
        elif group is not None:
            tokens.append(Token(group, m.group(group), start))
        pos = m.end()
    return tokens


# ----- AST -------------------------------------------------------------------


@dataclass(frozen=True)
class Cond:
    key: str
    op: str | None
    value: str | None
    pos: int


@dataclass(frozen=True)
class Not:
    node: Node


@dataclass(frozen=True)
class BoolOp:
    op: str  # and | or
    nodes: tuple[Node, ...]


Node = Cond | Not | BoolOp


@dataclass(frozen=True)
class ParsedQuery:
    text: str
    expr: Node | None
    sort: str = "rank"
    descending: bool = False
    top: int | None = None


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = tokenize(text)
        self.i = 0
        self.sort = "rank"
        self.desc = False
        self.top: int | None = None

    def peek(self, offset: int = 0) -> Token | None:
        j = self.i + offset
        return self.tokens[j] if j < len(self.tokens) else None

    def take(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def end_pos(self) -> int:
        return len(self.text)

    def parse(self) -> ParsedQuery:
        self._controls()
        expr = None if self.peek() is None else self.parse_or()
        self._controls()
        tok = self.peek()
        if tok is not None:
            raise QueryError(f"Unexpected `{tok.value}`.", tok.pos, self.text)
        return ParsedQuery(self.text, expr, self.sort, self.desc, self.top)

    def _controls(self) -> None:
        while True:
            tok, op, val = self.peek(), self.peek(1), self.peek(2)
            if not (tok and op and val and tok.kind == "word" and op.value == "="):
                return
            key = tok.value.lower()
            if key not in ("sort", "top", "limit"):
                return
            self.i += 3
            if key == "sort":
                name = val.value.lower()
                self.desc = name.startswith("-")
                name = name.lstrip("-+")
                if name in RANK_FIELDS:
                    raise QueryError(
                        f"Can't sort a query by `{name}`.",
                        val.pos,
                        self.text,
                        hint="Rank by score with `langsuite rank`.",
                    )
                if name not in SORTABLE and name != "appeared":
                    raise QueryError(
                        f"Can't sort by `{name}`.",
                        val.pos,
                        self.text,
                        hint="Sort by one of: " + ", ".join(SORTABLE) + ".",
                    )
                self.sort = "year" if name == "appeared" else name
            else:
                if not val.value.isdigit() or int(val.value) < 1:
                    raise QueryError("`top` needs a whole number ≥ 1.", val.pos, self.text)
                self.top = int(val.value)
            self._controls_tail()

    def _controls_tail(self) -> None:
        # allow "and" between controls and filters: "top=5 and kind=pl"
        tok = self.peek()
        if tok is not None and tok.kind == "word" and tok.value.lower() == "and":
            nxt = self.peek(1)
            if nxt is not None:
                self.i += 1

    def _at_control(self) -> bool:
        tok, op = self.peek(), self.peek(1)
        return bool(
            tok
            and op
            and tok.kind == "word"
            and op.value == "="
            and tok.value.lower() in ("sort", "top", "limit")
        )

    def parse_or(self) -> Node:
        nodes = [self.parse_and()]
        while (tok := self.peek()) and tok.kind == "word" and tok.value.lower() == "or":
            self.take()
            nodes.append(self.parse_and())
        return nodes[0] if len(nodes) == 1 else BoolOp("or", tuple(nodes))

    def parse_and(self) -> Node:
        nodes = [self.parse_unary()]
        while True:
            self._controls()
            tok = self.peek()
            if tok is None or tok.kind == "rparen":
                break
            if tok.kind == "word" and tok.value.lower() == "or":
                break
            if tok.kind == "word" and tok.value.lower() == "and":
                self.take()
                if self.peek() is None:
                    raise QueryError("Expected a condition after `and`.", self.end_pos(), self.text)
            nodes.append(self.parse_unary())
        return nodes[0] if len(nodes) == 1 else BoolOp("and", tuple(nodes))

    def parse_unary(self) -> Node:
        tok = self.peek()
        if tok is None:
            raise QueryError("Expected a condition.", self.end_pos(), self.text)
        if tok.kind == "word" and tok.value.lower() == "not":
            self.take()
            return Not(self.parse_unary())
        if tok.kind == "lparen":
            self.take()
            if self.peek() is None or self.peek().kind == "rparen":  # type: ignore[union-attr]
                raise QueryError("Empty parentheses.", tok.pos, self.text)
            node = self.parse_or()
            close = self.peek()
            if close is None or close.kind != "rparen":
                raise QueryError("Missing `)`.", tok.pos, self.text, hint="Close the bracket.")
            self.take()
            return node
        if tok.kind != "word" or tok.value.lower() in ("and", "or"):
            raise QueryError(f"Unexpected `{tok.value}`.", tok.pos, self.text)
        self.take()
        op = self.peek()
        if op is not None and op.kind == "op":
            self.take()
            val = self.peek()
            if val is None or val.kind != "word":
                raise QueryError(
                    f"Expected a value after `{op.value}`.",
                    val.pos if val else self.end_pos(),
                    self.text,
                )
            self.take()
            return Cond(tok.value.lower(), op.value, val.value, tok.pos)
        return Cond(tok.value.lower(), None, None, tok.pos)


def parse(text: str) -> ParsedQuery:
    if len(text) > MAX_QUERY_LEN:
        raise QueryError(f"Query is too long (max {MAX_QUERY_LEN} characters).", 0, text[:40])
    return _Parser(text).parse()


# ----- evaluation --------------------------------------------------------------

Pred = Callable[[Language], bool]


@dataclass(frozen=True)
class QueryRow:
    language: Language
    traits: int

    def to_json(self) -> dict[str, Any]:
        return {**self.language.to_json(), "traits": self.traits}


@dataclass(frozen=True)
class QueryResult:
    text: str
    normalised: str
    snapshot_id: str
    total: int
    rows: list[QueryRow]
    sort: str
    descending: bool
    top: int | None
    features: list[str] = field(default_factory=list)
    version: int = QUERY_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "query": self.text,
            "normalised": self.normalised,
            "snapshot_id": self.snapshot_id,
            "version": self.version,
            "total": self.total,
            "sort": ("-" if self.descending else "") + self.sort,
            "top": self.top,
            "features": self.features,
            "rows": [r.to_json() for r in self.rows],
        }


class _Compiler:
    def __init__(self, kb: KnowledgeBase, text: str) -> None:
        self.kb = kb
        self.text = text
        self.values = kb.trait_values()
        self.traits = {f.id: f for f in kb.features if f.kind == "trait"}
        self.used: list[str] = []

    def compile(self, node: Node) -> tuple[Pred, str]:
        if isinstance(node, Not):
            pred, txt = self.compile(node.node)
            return (lambda lang: not pred(lang)), f"not {txt}"
        if isinstance(node, BoolOp):
            parts = [self.compile(n) for n in node.nodes]
            preds = [p for p, _ in parts]
            joined = f" {node.op} ".join(t for _, t in parts)
            if node.op == "and":
                return (lambda lang: all(p(lang) for p in preds)), f"({joined})"
            return (lambda lang: any(p(lang) for p in preds)), f"({joined})"
        return self.cond(node)

    def _err(self, msg: str, cond: Cond, hint: str | None = None) -> QueryError:
        return QueryError(msg, cond.pos, self.text, hint=hint)

    def cond(self, c: Cond) -> tuple[Pred, str]:
        key, op, val = c.key, c.op, c.value
        if key in RANK_FIELDS:
            raise self._err(
                f"`{key}` is a score field, not a query field.",
                c,
                hint=f'Use `langsuite rank --filter "{key}{op or "="}{val or "..."}"`.',
            )
        if op is None:
            feat = self.feature(key, c)
            return self.feature_pred(feat.id, "yes"), feat.id
        assert val is not None
        if key in NUMERIC:
            return self.numeric(c, NUMERIC[key], op, val)
        if key in TEXT or key in MULTI:
            return self.textual(c, key, op, val)
        if key in ("has", "feature", "with"):
            if op != "=":
                raise self._err(f"`{key}` only supports `=`.", c)
            feat = self.feature(val, c)
            return self.feature_pred(feat.id, "yes"), feat.id
        if key in ("without", "lacks"):
            feat = self.feature(val, c)
            return self.feature_pred(feat.id, "no"), f"{feat.id}=no"
        feat_direct = self._exact_feature(key)
        if feat_direct is not None:
            if op not in ("=", "!="):
                raise self._err(f"Features compare with `=` or `!=`, not `{op}`.", c)
            want = FEATURE_VALUES.get(val.lower())
            if want is None:
                raise self._err(
                    f"`{val}` isn't a feature value.", c, hint="Use yes, no or unknown."
                )
            pred = self.feature_pred(feat_direct.id, want)
            if op == "!=":
                return (lambda lang: not pred(lang)), f"{feat_direct.id}!={want}"
            return pred, f"{feat_direct.id}={want}"
        if op not in ("=", "!="):
            raise self._err(f"Unknown field `{key}`.", c, hint=self._fields_hint())
        feat = self.shorthand(key, val, c)
        pred = self.feature_pred(feat.id, "yes")
        if op == "!=":
            return (lambda lang: not pred(lang)), f"not {feat.id}"
        return pred, feat.id

    @staticmethod
    def _fields_hint() -> str:
        names = sorted({*NUMERIC, *TEXT, *MULTI})
        return "Fields: " + ", ".join(names) + ". Or name a feature (`langsuite feature list`)."

    def _exact_feature(self, name: str) -> Feature | None:
        q = name.replace("_", "-")
        if q in self.traits:
            return self.traits[q]
        compact = q.replace("-", "")
        for fid, feat in self.traits.items():
            if fid.replace("-", "") == compact:
                return feat
        return None

    def feature(self, name: str, c: Cond) -> Feature:
        exact = self._exact_feature(name)
        if exact is not None:
            self._use(exact.id)
            return exact
        try:
            feat = self.kb.resolve_feature(name)
        except NoResultError as err:
            raise self._err(err.message, c, hint=err.hint) from None
        if feat.kind != "trait":
            raise self._err(
                f"`{feat.id}` is a fact, not a yes/no feature.",
                c,
                hint="Use a field such as year, kind or ext.",
            )
        self._use(feat.id)
        return feat

    def shorthand(self, key: str, val: str, c: Cond) -> Feature:
        v = val.lower().replace("_", "-")
        hits = [f for f in self.traits.values() if v in f.id]
        if len(hits) > 1:
            stem = key[:3]
            narrowed = [f for f in hits if stem in f.id or f.category.lower().startswith(stem)]
            hits = narrowed or hits
        if len(hits) == 1:
            self._use(hits[0].id)
            return hits[0]
        if not hits:
            raise self._err(f"Unknown field `{key}`.", c, hint=self._fields_hint())
        options = ", ".join(f"`{f.id}`" for f in hits[:5])
        raise self._err(f"`{key}={val}` is ambiguous.", c, hint=f"Did you mean {options}?")

    def _use(self, fid: str) -> None:
        if fid not in self.used:
            self.used.append(fid)

    def feature_pred(self, fid: str, want: str) -> Pred:
        values = self.values

        def pred(lang: Language) -> bool:
            got = values.get(lang.id, {}).get(fid, "unknown")
            return got == want

        return pred

    def numeric(self, c: Cond, attr: str, op: str, val: str) -> tuple[Pred, str]:
        if op == "~":
            raise self._err(f"`~` works on text fields, not `{c.key}`.", c)
        try:
            target = int(val)
        except ValueError:
            raise self._err(f"`{c.key}` needs a number, got `{val}`.", c) from None
        counts = self.kb.trait_matrix().counts
        index = self.kb.trait_matrix().index

        def get(lang: Language) -> int | None:
            if attr == "traits":
                i = index.get(lang.id)
                return int(counts[i]) if i is not None else 0
            value = getattr(lang, attr)
            return int(value) if value is not None else None

        cmp: dict[str, Callable[[int, int], bool]] = {
            "=": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
        }
        fn = cmp[op]

        def pred(lang: Language) -> bool:
            got = get(lang)
            return got is not None and fn(got, target)

        name = "year" if attr == "appeared" else attr
        return pred, f"{name}{op}{target}"

    def textual(self, c: Cond, key: str, op: str, val: str) -> tuple[Pred, str]:
        if op not in ("=", "!=", "~"):
            raise self._err(f"`{key}` supports =, != and ~, not `{op}`.", c)
        attr = TEXT.get(key) or MULTI[key]
        want = val.lower().lstrip(".") if attr == "extensions" else val.lower()

        def values_of(lang: Language) -> list[str]:
            raw = getattr(lang, attr)
            if raw is None:
                return []
            if isinstance(raw, tuple):
                return [str(x).lower() for x in raw]
            if attr == "creators":
                return [p.strip().lower() for p in str(raw).split(" and ")] + [str(raw).lower()]
            return [str(raw).lower()]

        if op == "~":

            def pred(lang: Language) -> bool:
                return any(want in v for v in values_of(lang))
        else:

            def pred(lang: Language) -> bool:
                return want in values_of(lang)

        if op == "!=":
            inner = pred
            return (lambda lang: not inner(lang)), f"{key}!={want}"
        return pred, f"{key}{op}{want}"


def _sort_key(sort: str, traits: Callable[[Language], int]) -> Callable[[Language], Any]:
    big = 10**9
    if sort == "name":
        return lambda lang: (lang.name.lower(), lang.id)
    if sort == "id":
        return lambda lang: lang.id
    if sort == "kind":
        return lambda lang: (lang.kind, lang.rank if lang.rank is not None else big, lang.id)
    if sort == "year":
        return lambda lang: (lang.appeared if lang.appeared is not None else big, lang.id)
    if sort == "traits":
        return lambda lang: (traits(lang), lang.id)
    return lambda lang: (lang.rank if lang.rank is not None else big, lang.name.lower(), lang.id)


def run(kb: KnowledgeBase, text: str, top: int | None = None) -> QueryResult:
    """Parse and run a query. Deterministic: every sort ends with the language id."""
    parsed = parse(text)
    compiler = _Compiler(kb, text)
    if parsed.expr is None:
        pred: Pred = lambda lang: True  # noqa: E731
        normalised = "all"
    else:
        pred, normalised = compiler.compile(parsed.expr)
        if normalised.startswith("(") and normalised.endswith(")"):
            normalised = normalised[1:-1]
    tm = kb.trait_matrix()

    def traits(lang: Language) -> int:
        i = tm.index.get(lang.id)
        return int(tm.counts[i]) if i is not None else 0

    hits = [lang for lang in kb.languages if pred(lang)]
    key = _sort_key(parsed.sort, traits)
    if parsed.descending and parsed.sort in ("year", "traits", "rank"):
        # missing values stay last when reversing numeric sorts
        present = [h for h in hits if not (parsed.sort == "year" and h.appeared is None)]
        present = [h for h in present if not (parsed.sort == "rank" and h.rank is None)]
        missing = [h for h in hits if h not in set(present)]
        hits = sorted(present, key=key, reverse=True) + sorted(missing, key=lambda x: x.id)
    else:
        hits = sorted(hits, key=key, reverse=parsed.descending)
    limit = top if top is not None else parsed.top
    rows = [QueryRow(lang, traits(lang)) for lang in (hits[:limit] if limit else hits)]
    return QueryResult(
        text=text,
        normalised=normalised,
        snapshot_id=kb.manifest.snapshot_id,
        total=len(hits),
        rows=rows,
        sort=parsed.sort,
        descending=parsed.descending,
        top=limit,
        features=compiler.used,
    )


def validate(kb: KnowledgeBase | None, text: str) -> QueryError | LangsuiteError | None:
    """None when the query is valid (used for as-you-type checks in the app)."""
    try:
        if kb is None:
            parse(text)
        else:
            run(kb, text, top=1)
    except LangsuiteError as err:
        return err
    return None
