# Build prompt: langsuite

You are a coding agent building **langsuite** from `SPEC.md` (in this folder; copy it to `docs/SPEC.md` in the repo). SPEC.md is the source of truth. If it is ambiguous or contradicts itself, stop and ask instead of guessing; record the question in `docs/OPEN_QUESTIONS.md`.

## Hard rules (need Adam's explicit OK to break)
- Repo: `ao3575911/langsuite` on GitHub. Create it only after Adam confirms. Public, MIT licence.
- **PR-only:** no direct pushes to `main`. Ruleset: PR required, squash merge only, linear history, signed commits, required checks green, no bypass.
- **No tags, no GitHub releases, no PyPI/npm registration or publish** without Adam's OK. Build release candidates as CI artefacts only.
- No real Stripe live keys, no production deploys, no paid cloud resources without Adam's OK. Use Stripe test mode and local/staging containers.
- Secrets only from env/secret stores; never committed or logged.
- Rosetta (GFDL 1.2) and CC BY-SA content live in separate data packs, never in the MIT package.

## Stack (SPEC §9, decided by default)
Python 3.12+, uv, Typer + Rich (CLI), Textual (TUI), FastAPI (API), python-telegram-bot 22.x, DuckDB + Parquet (base), Postgres with RLS (tenants), Docker (verifier), tree-sitter, scikit-learn/scipy, hnswlib, Stripe SDK, xAI API.

## Conventions
- **Textual app is first-class (SPEC §6e).** `textual` and `pytest-textual-snapshot` are added in the M0b implementation PR, not before.
- **Commits and PRs (uniform):** Conventional Commits `type(scope): summary` (≤ 72 chars; types feat, fix, docs, refactor, test, ci, build, chore; scope = milestone or area, e.g. `feat(m0b): …`). Body: what changed, why, spec section, tests run. PR body sections: **Summary**, **Why**, **Changes**, **Spec**, **Tests**, **Demo**, **Out of scope / follow-ups**, **Checklist** (CI green, CHANGELOG, docs, aliases/bindings).
- Layout: `src/langsuite/{core,cli,tui,bot,api,ingest,verify,score,discover,saas}`, `tests/`, `data-packs/`, `docs/`.
- `core` is the only place with business logic; front ends are thin adapters (parity test).
- Typing: mypy strict; ruff lint + format; pytest with ≥ 85% coverage on `core`; snapshot tests for CLI output (rich, plain, JSON).
- Conventional Commits; one milestone or sub-milestone per PR (split large ones); PR description = what, why, tests, spec section, screenshots/GIFs for UI.
- Errors: typed exceptions, user-facing messages short and actionable, exit codes per SPEC §7; no stack traces unless `--debug`.
- Determinism: seeded randomness, pinned snapshots; same input → same output.
- Every result carries provenance (sources, evidence ids, snapshot hash, method version).
- Docs: README (short, with detailed Install section of exact commands), `docs/` for method notes, CHANGELOG.

## CI (required checks from M0)
- From M0b: Textual snapshot tests (`pytest-textual-snapshot`) and Pilot flow tests run in the `tests` job on Linux + macOS; snapshot diffs fail the build and are reviewed as SVG artefacts.
lint, typecheck, tests (Linux + macOS, incl. Textual snapshots from M0b), licence-pack check (wheel must not contain GFDL/CC BY-SA files), dependency audit (pip-audit), secret scan, alias/help test once CLI exists, mode-compliance test once `ask` exists (nightly live xAI job non-blocking, offline fixture job blocking).

## Milestone order
M0 → M0b → M1 → M2 → M3 → M4 → M5 → M5b → M5c → M5f → M5h → M5d → M5g → M5i → M5e → M6.
(Data CI and CLI UX early because later milestones depend on them; SaaS before the Telegram bot because the bot is a SaaS client.)

## Definition of done (every milestone)
0. From M1 on, the milestone ships the CLI command **and** its Textual pane (SPEC §6e) with snapshots, a Pilot flow and parity coverage.
1. All SPEC §10 acceptance tests for that milestone exist, run in CI, and pass.
2. Required checks green; PR squash-merged after review.
3. No new UNKNOWN-licence content stored beyond link + short excerpt.
4. README/docs/CHANGELOG updated; `--help` and alias table updated if commands changed.
5. Demo: a short transcript or GIF of the new capability in the PR.
6. Open questions and deviations logged in `docs/OPEN_QUESTIONS.md`.

## Acceptance gates between milestones
- Do not start the next milestone while the previous one's tests are failing or skipped.
- Before M5d (Q&A): citation filter and abstain path proven on fixtures.
- Before M5i (SaaS): tenant isolation suite written first (test-first).
- Before M6: competitive-bar targets in SPEC §6d measured and reported in the PR; anything missed is listed with a plan.

## Start now
1. Confirm with Adam that the repo may be created (or use an existing empty one he names).
2. M0: scaffold the layout, pyproject (uv), CI with the required checks, MIT licence, `data-packs/` layout with a planted-GFDL test, README skeleton with Install section, `docs/SPEC.md`.
3. Open the M0 PR, get it green, report back with the PR link and the next milestone plan.
