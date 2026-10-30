# langwish

A research knowledge base of programming languages: how they work, how they relate, with evidence.

> **Status: M0 scaffold.** Commands are listed but not built yet; each one says which milestone brings it. Spec: [`docs/SPEC.md`](docs/SPEC.md).

## Install

Not on PyPI yet. From source:

```sh
# prerequisites: Python 3.12+, uv (https://docs.astral.sh/uv/)
git clone https://github.com/ao3575911/langwish && cd langwish
uv sync
uv run langwish --help
```

Planned one-liner once published: `pipx install langwish && langwish login`.

## Use

```sh
langwish --help          # commands grouped by pillar, alias in brackets
langwish l show haskell  # every command has a short alias (l = lang)
langwish -m concise ...  # modes: default | concise | thorough
langwish --json ...      # stable JSON; --plain for no colour
```

Exit codes: `0` ok · `2` no result · `3` data error · `4` auth · `5` quota.

## Develop

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

## Licence

Code: MIT. Share-alike data (Rosetta Code GFDL 1.2, CC BY-SA) lives in [`data-packs/`](data-packs/) and never ships in the MIT wheel; CI enforces this.
