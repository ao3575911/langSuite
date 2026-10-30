# Changelog

## Unreleased
### Added
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
