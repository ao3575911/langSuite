# Open questions and deviations

| # | Milestone | Item | Status |
|---|---|---|---|
| 1 | M0 | `main` was bootstrapped with GitHub's own signed initial commit (README + MIT LICENSE via `gh repo create --add-readme --license mit`) instead of `createCommitOnBranch`, which cannot run on an empty repo. Commit is Verified. | Deviation, logged |
| 2 | M0 | Commands are stubs that exit 2 with their milestone; `ls`/`sh`/`rm` sub-aliases are declared and wired from M1 when subcommands exist. | Logged |
| 3 | — | Usernames unique across all installs? Keep the E grade? (from spec review) | Open, non-blocking |
| 4 | M0 | Project renamed langwish → langsuite (Adam, 2026-10-30); the former langSuite repo is now `ao3575911/semdrift`. Handle is `$langsuite/<username>/<workspace>`. | Done |
| 5 | M0b | CLI command `tui` renamed `ui` (alias `t`) in the spec; code still has `tui` until the M0b implementation PR. No-args on a TTY launches the app (replaces `no_args_is_help`) in M0b. | Done (M0b) |
| 6 | M0b | Mode switch key is `F2`, not `ctrl+m`: terminals send `ctrl+m` as Enter. Clicking the mode chip also cycles. | Deviation |
| 7 | M0b | Start-up test bound is 1.5 s in CI (headless, includes test harness); spec target 600 ms is for interactive start on a dev machine. | Deviation |
| 8 | M0b | Handle shows `$langsuite/guest/default` until accounts land (M5g); base age shows `base: none` until M1. | Logged |
| 9 | M1 | `base build` added (spec lists `base pull/status/pin/changelog`, M5f): until signed snapshots are published, users build locally. `pull`, `pin`, `changelog` stay stubs (M5f). | Deviation, logged |
| 10 | M1 | Feature vocabulary v1 is PLDB's `has*`/`is*` traits, auto-categorised, plus Linguist/PLDB facts. The spec's higher-level facets (evaluation strategy, syntax family, model) are derived in M2 with `query`. PLDB trait coverage is sparse (~950 languages have any). | Logged |
| 11 | M1 | `confidence` is 1.0 for values stated verbatim by a source; derived values (M2+) get lower values. | Logged |
| 12 | M1 | Inclusion criteria (§2a) are not yet applied: every PLDB/Linguist entry is stored; liveness checks arrive with data CI. | Logged |
| 13 | M2 | Higher-level facets are reached with the `key=value` shorthand (`eval=lazy` → `lazy-evaluation`) rather than a separate derived-facet table; `paradigm=` is planned with cluster labels (M5b). | Logged |
| 14 | M2 | Shuffled baseline (`shuffled-features/2`): both languages' trait sets are redrawn with the same size, by trait frequency, 1,000 seeded rounds. A plain column permutation ignores how much is known per language and inflates variance for sparse rows. | Decision, logged |
| 15 | M2 | Golden set: Scheme–Racket, Clojure–ClojureScript, OCaml–Reason, Java–Kotlin (all z ≥ 3 on the live base). C–C++ and JavaScript–TypeScript score low because PLDB lists few overlapping traits for them; they are shown as feature/code disagreement candidates once code similarity lands (M5). | Logged |
| 16 | M3 | Workspaces are folders of small JSON files rather than a DuckDB file: diffable, easy to back up, and safe for the CLI and app to touch at once (atomic replace). Findings are self-contained, so `workspace sync` (M5i) can upload them as-is. | Decision, logged |
| 17 | M3 | "Bit-for-bit" is defined as the SHA-256 of the canonical JSON result (sorted keys, no whitespace) re-run on the same snapshot and own data. Similarity floats come from seeded numpy; a numpy major upgrade could in theory change the last digit, which `finding verify` would then flag. | Logged |
| 18 | M3 | Own data can add new languages and add or override traits on base languages for one workspace; it cannot rename or delete base languages. Overlay facts carry `source: user`. | Logged |
| 19 | M4 | `base pull` and `base changelog` are assigned to M5f, with cosign-signed snapshots and data CI; `base build` remains the way to get a base until then (Adam, 2026-10-30). | Decision |
| 20 | M4 | Rosetta blocks often need boilerplate or are for old runtimes. Racket gets `#lang racket` and Erlang an escript header when missing; up to 5 variants per language are tried. On the 7-task pack, 99 of 134 solutions across the 20 toolchains verify; the rest fail honestly (e.g. Rust FizzBuzz printing lowercase). | Logged |
| 21 | M4 | `verify` exits 1 when code fails, a code not in SPEC §7; 3 when the sandbox refuses (no Docker, digest mismatch). | Deviation, logged |
| 22 | M4 | Common Lisp uses `clfoundation/sbcl:latest` pinned by digest: the project publishes no versioned tags that include an amd64 and arm64 manifest. | Logged |
| 23 | M4 | Go gets a 512 MB cap and `GOMAXPROCS=1`: its build cache lives on the in-memory /tmp, and CI runners report many cores. All other toolchains keep 256 MB. | Logged |
