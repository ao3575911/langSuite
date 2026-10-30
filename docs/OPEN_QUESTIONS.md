# Open questions and deviations

| # | Milestone | Item | Status |
|---|---|---|---|
| 1 | M0 | `main` was bootstrapped with GitHub's own signed initial commit (README + MIT LICENSE via `gh repo create --add-readme --license mit`) instead of `createCommitOnBranch`, which cannot run on an empty repo. Commit is Verified. | Deviation, logged |
| 2 | M0 | Commands are stubs that exit 2 with their milestone; `ls`/`sh`/`rm` sub-aliases are declared and wired from M1 when subcommands exist. | Logged |
| 3 | — | Usernames unique across all installs? Keep the E grade? (from spec review) | Open, non-blocking |
