# Open questions and deviations

| # | Milestone | Item | Status |
|---|---|---|---|
| 1 | M0 | `main` was bootstrapped with GitHub's own signed initial commit (README + MIT LICENSE via `gh repo create --add-readme --license mit`) instead of `createCommitOnBranch`, which cannot run on an empty repo. Commit is Verified. | Deviation, logged |
| 2 | M0 | Commands are stubs that exit 2 with their milestone; `ls`/`sh`/`rm` sub-aliases are declared and wired from M1 when subcommands exist. | Logged |
| 3 | — | Usernames unique across all installs? Keep the E grade? (from spec review) | Open, non-blocking |
| 4 | M0 | Project renamed langwish → langsuite (Adam, 2026-10-30); the former langSuite repo is now `ao3575911/semdrift`. Handle is `$langsuite/<username>/<workspace>`. | Done |
| 5 | M0b | CLI command `tui` renamed `ui` (alias `t`) in the spec; code still has `tui` until the M0b implementation PR. No-args on a TTY launches the app (replaces `no_args_is_help`) in M0b. | Planned |
