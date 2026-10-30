# langsuite

A research knowledge base of programming languages: how they work, how they relate, with evidence.

**For** language researchers and developers in training.
**Aim:** a fully featured, state-of-the-art research tool, usable from the CLI, a TUI, or the langsuite Telegram bot.

| Capability | Status |
|---|---|
| CLI: grouped help, one alias per command, `--json` / `--plain`, exit codes | Built (M0) |
| Textual app shell: header with handle and mode, 7 panes, command palette, `g`+alias keys, themes incl. high-contrast, plain mode, browser via `ui --serve` | Built (M0b) |
| Licence-separated data packs, enforced in CI | Built (M0) |
| Knowledge base of 5,000+ languages (PLDB + Linguist) with sourced evidence: `base build/status`, `lang list/show --evidence`, `feature list/show`, Explore pane with live search | Built (M1) |
| Structured `query` DSL and feature `similar` with a shuffled-feature baseline (z-scores); Query pane and Similar tab | Built (M2) |
| Code similarity, clusters, scores and grades | Planned (M5–M5c) |
| Verified snippets, cited answers, how/when guides | Planned (M4, M5d) |
| Workspaces: findings re-runnable bit-for-bit on their pinned snapshot, notes, saved queries, own-data overlay (custom languages), `base pin`; Workspace pane with `Ctrl+S` to save | Built (M3) |
| Telegram bot with group workspaces | Planned (M5e) |
| Hosted SaaS | Planned (M5i) |

> **Status: M0 scaffold.** Commands are listed but not built yet; each one says which milestone brings it. Spec: [`docs/SPEC.md`](docs/SPEC.md).

## Install

Not on PyPI yet. From source:

```sh
# prerequisites: Python 3.12+, uv (https://docs.astral.sh/uv/)
git clone https://github.com/ao3575911/langsuite && cd langsuite
uv sync
uv run langsuite --help
```

Planned one-liner once published: `pipx install langsuite && langsuite login`.

## App

```sh
langsuite                 # in a terminal: opens the app (same as `langsuite ui`)
langsuite ui --serve      # same app in a browser at http://localhost:8000
langsuite --plain ui      # screen-reader friendly: no borders, terminal colours
```

Keys: `1`–`7` sections · `g` + a CLI alias (e.g. `g s` = similar) · `ctrl+p` palette · `F2` mode · `F3` theme · `ctrl+q` quit. Mouse works everywhere.

## Knowledge base

```sh
langsuite base build                  # downloads PLDB + Linguist (~11 MB), builds in ~1 s
langsuite lang list lisp -f macros    # search by name, alias or .ext; filter by feature
langsuite lang show haskell --evidence  # every fact with its source, URL and retrieval time
langsuite feature show type-inference # which languages have it
langsuite base status                 # snapshot id, sources, licences, age
```

Sources: [PLDB](https://pldb.io) (public domain) and [GitHub Linguist](https://github.com/github-linguist/linguist) (MIT). Wikipedia-derived PLDB fields (CC BY-SA) are never ingested. Builds are atomic: a failed download or bad upstream data leaves the current base untouched, and `--offline` rebuilds from the cache. In the app, press `2` (Explore) to search live.

## Query and similarity

```sh
langsuite query "homoiconicity year<1990 sort=year"         # bare name = has feature
langsuite q "(macros or pattern-matching) static-typing top=10"
langsuite q "eval=lazy"                    # key=value shorthand finds lazy-evaluation
langsuite q "monads=unknown kind=pl"       # yes | no | unknown (no source says)
langsuite similar scheme --k 5             # shared traits + z vs shuffled baseline
langsuite s scheme --vs racket             # one pair, with the baseline spelled out
```

Fields: `name id kind year rank traits ext alias creator source website`; operators `= != >= <= > < ~`; `and`, `or`, `not`, brackets; `sort=[-]field`, `top=N`. Similarity is a rarity-weighted Jaccard over sourced traits (`features-idf-jaccard/1`); each score comes with a z-score against 1,000 seeded shuffles that keep each language's trait count and each trait's frequency (`shuffled-features/2`). z ≥ 3 is strong. Unknown is never treated as "no". In the app, press `3` for the Query pane (validated as you type, click a column to sort) or open the Similar tab in Explore.

## Workspaces and findings

```sh
langsuite q "homoiconicity year<1990" --save old-lisps   # saved query (run: --saved old-lisps)
langsuite x --title "Early Lisps"                       # extract the last result as finding f1
langsuite finding save similar scheme                   # or save any query/similar/pair/lang run
langsuite f show f1 --verify                            # re-run on its own snapshot: sha256 must match
langsuite f verify                                      # all findings; exit 3 if any changed
langsuite f export --format md|json|csv -o report.md
langsuite n add "check macro hygiene" --on f1
langsuite w import examples/own-data.yml                # your own languages and traits (overlay)
langsuite w init lisp-survey && langsuite w export lisp-survey.json
langsuite base pin            # freeze this workspace on the current snapshot; --clear to follow
langsuite base snapshots      # kept snapshots; pinned or cited ones are never pruned
```

A finding stores the command, snapshot id, a copy of any own data it saw, its evidence ids (`ev-…`, one per sourced assertion) and the SHA-256 of its canonical result. Every `base build` keeps the old snapshot (the newest five plus any pinned or cited), so a finding saved today still re-runs to the identical bytes after the base is upgraded. Workspaces are plain JSON folders under `<data home>/workspaces/<name>/`; own data never touches the shared base. In the app, press `Ctrl+S` in Explore (profile, or the Similar tab) or Query to save a finding, and `5` for the Workspace pane (`v` verify, `Del` remove, notes, saved queries, own data).

## Use

```sh
langsuite --help          # commands grouped by pillar, alias in brackets
langsuite l show haskell  # every command has a short alias (l = lang)
langsuite -m concise ...  # modes: default | concise | thorough
langsuite --json ...      # stable JSON; --plain for no colour
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
