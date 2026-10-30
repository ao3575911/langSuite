# Changelog

## Unreleased
### Added
- Renamed langwish → langsuite.
- Spec: Textual app as a first-class interface (§6e), new M0b app-shell milestone, CLI + pane per milestone; `docs/BUILD_PROMPT.md` added with uniform commit/PR conventions.
- README and spec positioning: audience, aim, built-vs-planned table.
- M0: uv/Python 3.12 package layout (`core`, `cli`, `tui`, `bot`, `api`, `ingest`, `verify`, `score`, `discover`, `saas`).
- Typer CLI: 31 commands grouped by pillar, one alias each, stubs that exit 2 naming their milestone.
- Typed errors with SPEC §7 exit codes; `--json`, `--plain`, `NO_COLOR`, `-m/--mode`, `--debug`.
- Rich `langsuite` theme stub.
- CI: lint, typecheck, tests (Linux, macOS), licence-pack check with planted-GFDL test, pip-audit, gitleaks.
- `data-packs/` layout for GFDL and CC BY-SA content.
