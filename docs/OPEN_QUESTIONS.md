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

