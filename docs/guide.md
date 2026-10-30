# langsuite guide


A research knowledge base of programming languages: how they work, how they relate, with evidence.

**For** language researchers and developers in training.
**Aim:** a fully featured, state-of-the-art research tool, usable from the CLI, a TUI, or the langsuite Telegram bot.

| Capability | Status |
|---|---|
| CLI: grouped help, one alias per command, `--json` / `--plain`, exit codes | Built (M0) |
| Textual app shell: header with handle and mode, 8 panes, command palette, `g`+alias keys, themes incl. high-contrast, plain mode, browser via `ui --serve` | Built (M0b) |
| Licence-separated data packs, enforced in CI | Built (M0) |
| Knowledge base of 5,000+ languages (PLDB + Linguist) with sourced evidence: `base build/status`, `lang list/show --evidence`, `feature list/show`, Explore pane with live search | Built (M1) |
| Structured `query` DSL and feature `similar` with a shuffled-feature baseline (z-scores); Query pane and Similar tab | Built (M2) |
| Code similarity, clusters, scores and grades | Built (M5, M5b, M5c): `similar --by code`, `like`, `diff`, `cluster`, `dashboard` (renames kept across base upgrades), `influence`, `rank`, `compare`, `settings profile` for a custom score; Dashboard and Analyse panes |
| Verified snippets: `verify` runs code in a digest-pinned, offline Docker sandbox (20 toolchains); `snippet` shows attributed Rosetta Code solutions marked verified only when they ran; Write pane | Built (M4) |
| Cited answers that abstain when the base cannot support them (`ask`), `guide <lang>`; `extract` keeps citations | Built (M5d), template-based (no LLM) |
| `docs search/quote/ingest` (verbatim quotes with link, version and anchor; short excerpts for UNKNOWN licences), `inclusion` and dead-link archiving; signed snapshots (`base publish`, `base pull` refuses unsigned or tampered ones; cosign-compatible), `base changelog`, weekly data CI with a score-jump gate; Docs pane | Built (M5f); signing key not yet issued |
| Workspaces: findings re-runnable bit-for-bit on their pinned snapshot, notes, saved queries, own-data overlay (custom languages), `base pin`; Workspace pane with `Ctrl+S` to save | Built (M3) |
| Telegram bot (`langsuite bot run`): same commands and aliases as the CLI, a workspace per chat, admin/contributor/viewer roles, findings with authors, rate limits, code runs off unless an admin enables them; `bot try` and the Account pane simulate it offline | Built (M5e) |
| Bot `/ask`, `/guide`, `/mode`, `/digest` schedules, inline mode; signed outbound `webhook`s; `mcp` stdio server for agents | Built (M5d, M5h) |
| `account` handles (`$langsuite/<user>/<ws>`): nominations, look-alike/profanity checks, 30-day renames with 180-day redirect hold, privacy, `/link` to Telegram; `badges`, `streak`, `settings gamification` | Built (M5g); local registry until hosted accounts (M5i) |
| `mode` per workspace or global (flag > workspace > global) | Built (M5h); LLM output bounds wait for xAI answers |
| `login` (device code, RFC 8628), `logout`, `usage` (monthly quota, exit 5 at 100%, invoice preview from the local ledger); Stripe test-mode webhook handling (signed, replay-safe, live mode refused) | Client side built (M5i) |
| Hosted service: tenants with RLS, object store, `workspace sync`, backups, load tests | Not deployed (M5i) |
| Release prep: 1.0.0, release notes, PyPI trusted-publishing workflow (tag-triggered; 1.0.0 published 30 Oct 2026) | Built (M6, release prep) |
| xAI explanations with citations, hosted `serve`, a11y audit, sync bundle, GIFs | Planned (M6, after 1.0.0) |

> **Status: 1.0.0, released on PyPI; built through M5i on the client side; the hosted service is not deployed. PyPI releases are published from signed tags ([`docs/RELEASING.md`](RELEASING.md)).** Release notes: [`1.0.1`](RELEASE_NOTES_1.0.1.md), [`1.0.0`](RELEASE_NOTES_1.0.0.md). Planned commands are listed and say which milestone brings them. Spec: [`docs/SPEC.md`](SPEC.md).

## Install

```sh
pipx install langsuite        # or: uv tool install langsuite
langsuite --help
```

Python 3.12+. Docker is optional and only used by `verify`. From source: `git clone https://github.com/ao3575911/langsuite && cd langsuite && uv sync && uv run langsuite --help`.

## App

```sh
langsuite                 # in a terminal: opens the app (same as `langsuite ui`)
langsuite ui --serve      # same app in a browser at http://localhost:8000
langsuite --plain ui      # screen-reader friendly: no borders, terminal colours
```

Keys: `1`–`8` sections · `g` + a CLI alias (e.g. `g s` = similar) · `ctrl+p` palette · `F2` mode · `F3` theme · `ctrl+q` quit. Mouse works everywhere.

## Knowledge base

```sh
langsuite base build                  # downloads PLDB + Linguist (~11 MB), builds in ~1 s
langsuite lang list scheme -f macros   # search by name, alias or .ext; filter by feature
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

## Verify and snippets

```sh
langsuite verify hello.py                       # language from the extension; exit 1 if it fails
echo 'main = putStrLn "hi"' | langsuite v - --lang haskell --expect hi
langsuite verify --toolchains                   # 20 pinned images (image@sha256 digest)
langsuite snippet fizzbuzz --lang python,go,rust  # Rosetta Code, verified per language
langsuite snippet --tasks                       # tasks in your pack
langsuite snippet --fetch                       # fetch the default tasks into your data dir
```

Code runs in Docker with no network, a read-only root, a non-root user, all capabilities dropped, 256 MB memory, 64 processes, 1 CPU and a timeout. Images are pulled by digest; a local tag pointing at another digest is refused, never run. A snippet is marked **verified** only when it ran and (for tasks with a fixed answer) its output matched; without Docker every snippet says **unverified**. Results are cached by code hash and carry an evidence id (`vr-…`) that findings cite. Rosetta Code solutions are share-alike, kept in `data-packs/rosetta/` or your data dir, and always shown with their attribution line. In the app, press `6` for the Write pane (Snippet and Verify tabs, `Ctrl+R` runs, `Ctrl+S` saves a finding).

## Telegram bot

```sh
export LANGSUITE_TELEGRAM_TOKEN=...        # from @BotFather; never printed or logged
langsuite bot run                          # long polling; Ctrl+C stops
langsuite bot try "/s scheme --k 3"        # answer locally exactly as the bot would (no token)
langsuite bot try "/x pick" --group --role viewer   # → Not allowed
langsuite bot commands                     # commands, aliases, token set / not set
```

Getting started: open @langsuite_bot and press Start. The bot suggests three handles; tap one, or send `/handle yourname`. Then pick a first workspace (tap `main`, `research` or `notes`, or send `/space name`). Replies are then headed `$langsuite/<handle>/<workspace>`. `/space other` creates or switches workspace, and `/handle new` renames you. In a group, a group admin runs `/start` to give the group a handle; members then share `$langsuite/<group>/<workspace>`. Handles are 3–20 characters of `a-z 0-9 _`, unique ignoring case and look-alike digits (`l4ngsuite` = `langsuite`), and reserved words are refused.

In Telegram: `/q homoiconicity year<1990` (no quotes needed), `/s scheme`, `/l show haskell`, `/sn fizzbuzz --lang python`, `/x My title` saves the last result, `/f ls`, `/n add …`, `/b status`. Each chat gets its own workspaces. In groups, Telegram admins are admins, everyone else starts as viewer; an admin replies to someone with `/role contributor`. Findings record the author. `/v python` with code on the next lines runs only after an admin sends `/settings coderuns on`; snippets are shown unverified until then. Limits: 20 commands a minute per user, 60 per group. Long replies arrive as a file. The bot only reads commands (privacy mode). To keep the bot running on a server, run `nohup bash scripts/run_bot_forever.sh &`, which restarts it with backoff and logs to `$LANGSUITE_BOT_LOG`. Press `7` in the app for the bot pane: token status, the command list and a local chat to try commands.

## Use

```sh
langsuite --help          # commands grouped by pillar, alias in brackets
langsuite l show haskell  # every command has a short alias (l = lang)
langsuite -m concise ...  # modes: default | concise | thorough
langsuite --json ...      # stable JSON; --plain for no colour
```

Exit codes: `0` ok · `1` verification failed · `2` no result or bad input · `3` data error · `4` auth · `5` quota · `70` unexpected internal error (rerun with `--debug` and report it) · `130` interrupted (Ctrl-C). Errors print one `error:` line and a `hint:` line on stderr; `--debug` shows the traceback.

## Develop

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

## Licence

Code: MIT. Share-alike data (Rosetta Code GFDL 1.2, CC BY-SA) lives in [`data-packs/`](data-packs/) and never ships in the MIT wheel; CI enforces this.
