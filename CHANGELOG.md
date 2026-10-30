# Changelog

## Unreleased
### Added
- M5: code similarity from the Rosetta pack (`code-shingles-jaccard/1`): `similar --by code|both`, `like <task> --as <lang> --in <lang>`, `diff <task> --lang a,b`; feature/code disagreements listed on the dashboard.
- M5b: `cluster` / `dashboard`: deterministic k-medoids over rarity-weighted traits, k by silhouette (4 to 12) or `--k`, bootstrap support per cluster, labels = top 3 traits by lift with evidence ids, `dashboard rename <medoid> <name>` per workspace; `influence <lang> --depth N`.
- M5c: `rank` / `compare`: transparent scores from `criteria/1` (safety, expressiveness, modularity, popularity, maturity), grades A ≥ 85, B ≥ 70, C ≥ 55, D ≥ 40, else E; missing criteria lower confidence and never count as zero; `--by custom --profile`, `--filter "grade>=B paradigm=functional"`.
- Dashboard and Analyse panes run these commands in-process with presets.
- M5d: `ask` (method `kb-templates/1`): when/who/what, does X have Y, which languages have Y, influence, how do I write T in X; every sentence cites evidence, PLDB facts or a Rosetta permalink; anything else abstains. `guide <lang>`. Findings from `ask`/`guide` keep their citations. Golden set: 25 simple, 25 advanced, 20 out-of-KB.
- M5h: `mode [concise|default|thorough] [--global|--reset]`; `webhook add|list|remove|test` (HTTPS only, private IPs refused, HMAC-SHA256 with timestamp, retries, auto-disable after 5 failures) firing on `finding.saved` and `digest.ready`; workspace event log (`events.jsonl`); `mcp`: stdio MCP server with `similar`, `ask`, `lang_show`, `query`, `rank`.
- Bot: `/ask`, `/guide`, `/mode`, `/digest daily|weekly …` (Australia/Perth, checked each minute), inline mode (`@langsuite_bot similar haskell`).

## 1.0.0 — release candidate (not tagged or published)
### Release
- Version 1.0.0; PyPI metadata (classifiers, project URLs, keywords).
- `.github/workflows/release.yml`: on a `v*.*.*` tag only, checks tag = package version, runs lint, types and tests, builds, runs the licence-pack and `twine check`, then publishes with PyPI trusted publishing (OIDC, `pypi` environment, no stored token).
- Release notes (`docs/RELEASE_NOTES_1.0.0.md`) and maintainer steps (`docs/RELEASING.md`).
- README marks M5, M5b, M5c, M5d, M5f, M5g, M5h, M5i and the rest of M6 as planned.
### Added
- M5e: Telegram bot on python-telegram-bot 22.8: `bot run` (token from `LANGSUITE_TELEGRAM_TOKEN`, redacted from logs), `bot try` (offline), `bot commands`. Commands mirror the CLI and its aliases (`/q`, `/s`, `/l`, `/ft`, `/sn`, `/v`, `/f`, `/x`, `/n`, `/b`) and run the same code path, so `/q` prints what `langsuite q` prints. Per-chat workspaces; admin/contributor/viewer roles (`/role`), `/settings coderuns on|off`; findings store their author; token-bucket rate limits with a polite reply; central MarkdownV2 escaping; long output as a file; risky options (`-o`, `--fetch`, `--from`, `--debug`) refused.
- M5e: onboarding: `/start` suggests three handles as buttons, and `/handle` claims or renames one (lowercase ASCII, unique ignoring case and look-alikes, reserved words refused). `/space` creates or switches workspace. Replies are headed `$langsuite/<handle>/<workspace>`. Group admins set a group handle. `setMyDescription` and short description are set at start-up. `scripts/run_bot_forever.sh` provides a restart loop.
- M5e: Account pane shows the bot: token status, commands, and a local chat simulator.
- M4: `verify [FILE|-] --lang --expect --stdin --timeout`: runs code in a Docker sandbox (no network, read-only root, uid 65534, no capabilities, no-new-privileges, 256 MB, 64 pids, 1 CPU, file-size and timeout caps, 64 KB output). 20 toolchains pinned by image digest (`verify --toolchains`); tag/digest mismatch is refused. Results cached by code hash with evidence ids (`vr-…`).
- M4: `snippet TASK --lang a,b`: Rosetta Code solutions (up to 5 variants per language, tried in order), each verified in the sandbox; fixed-output tasks are checked against an oracle; attribution and licence on every snippet; unverified when Docker is absent. `snippet --tasks`, `snippet --fetch`. Findings: `finding save snippet|verify`.
- M4: Write pane (Snippet and Verify tabs).
- M4: `data-packs/rosetta/` with 7 tasks (renamed from `rosetta-gfdl`); the licence name now comes from pack data and the wiki's siteinfo, so the wheel has none.
- Decision: `base pull` and `base changelog` are assigned to M5f (signed snapshots, data CI).
- M3: workspaces (`workspace init|use|list|show|import|export|forget-data`; `sync` planned M5i). Findings (`finding save|list|show|verify|export|remove`, `extract last|<id>`) record command, snapshot, own-data copy, evidence ids and a result SHA-256; `--verify` re-runs bit-for-bit on the original snapshot. Notes (`note add|list|remove`, optionally `--on` a finding or language). Saved queries (`query --save/--saved`).
- M3: own-data overlay: import custom languages, traits and influence edges from YAML/JSON (`examples/own-data.yml`); they appear in `lang`, `query`, `similar` and the app for that workspace only, with validation against the base and the feature vocabulary.
- M3: snapshot retention: every build keeps its snapshot under `base/snapshots/`; the newest five plus any pinned or cited by a finding are kept. `base pin [ID] [--clear]` and `base snapshots`.
- M3: Workspace pane (findings table, Finding · Notes · Saved queries · Own data tabs, `v` verify, `Del` remove, Enter runs a saved query) and `Ctrl+S` "save finding" in Explore and Query.
- `ls`, `sh`, `rm` sub-command aliases now work on every group (`f ls`, `l sh haskell`).
- M2: `query` DSL (`and`/`or`/`not`, brackets, fields with `= != >= <= > < ~`, feature `=yes|no|unknown`, `key=value` feature shorthand, `sort=[-]field`, `top=N`); errors point at the exact column with a hint; planned fields (`score`, `grade`, `paradigm`) name their milestone.
- M2: `similar <lang> [--k] [--min-traits] [--vs <lang>]`: rarity-weighted Jaccard over sourced traits with shared/only-in lists, and a seeded shuffled-feature baseline (z-score) per pair; deterministic output; `--by code|both` planned for M5.
- M2: Query pane (validated as you type, sortable columns) and Similar tab in Explore; `g q` focuses the query, `g s` opens Similar.
- M1: knowledge base. `base build [--offline] [--from DIR]` ingests PLDB (public domain) and GitHub Linguist (MIT) into a DuckDB snapshot with a manifest (snapshot hash, source sha256, licences, retrieval times). Cached, conditional (ETag) downloads with retries and cache fallback; atomic swap so failed builds never damage the current base.
- M1: feature vocabulary v1 (166 PLDB traits in 8 categories plus 9 facts); every assertion stores source, URL, excerpt, retrieved_at and confidence; conflicting values kept side by side; influence edges.
- M1: `lang list [query] [--kind] [--feature]`, `lang show <lang> [--evidence]` (lookup by id, name, alias or .ext, "did you mean" on misses), `feature list [--category] [--all]`, `feature show`, `base status`; JSON for all; modes change detail.
- M1: Explore pane: debounced live search, results table, Features · Lineage · Evidence tabs (Docs, Score, Snippets planned); header shows snapshot id and age.
- M0b: Textual app shell (`langsuite` / `langsuite ui`): header with `$langsuite/<username>/<workspace>`, mode and base age; 7 section panes (planned states); command palette with every command and alias; `g`+alias leader keys and `1`–`7` section keys; mode switcher (F2 or click); themes `langsuite`, `langsuite-light`, `langsuite-high-contrast`; plain mode (`--plain` / `LANGSUITE_A11Y=1`); `ui --serve` via textual-serve. 42 SVG snapshots (7 panes × 3 themes × 2 sizes) and Pilot tests.
- CLI command `tui` renamed `ui` (alias `t`); no args on a TTY opens the app.
- Renamed langwish → langsuite.
- Spec: Textual app as a first-class interface (§6e), new M0b app-shell milestone, CLI + pane per milestone; `docs/BUILD_PROMPT.md` added with uniform commit/PR conventions.
- README and spec positioning: audience, aim, built-vs-planned table.
- M0: uv/Python 3.12 package layout (`core`, `cli`, `tui`, `bot`, `api`, `ingest`, `verify`, `score`, `discover`, `saas`).
- Typer CLI: 31 commands grouped by pillar, one alias each, stubs that exit 2 naming their milestone.
- Typed errors with SPEC §7 exit codes; `--json`, `--plain`, `NO_COLOR`, `-m/--mode`, `--debug`.
- Rich `langsuite` theme stub.
- CI: lint, typecheck, tests (Linux, macOS), licence-pack check with planted-GFDL test, pip-audit, gitleaks.
- `data-packs/` layout for GFDL and CC BY-SA content.
