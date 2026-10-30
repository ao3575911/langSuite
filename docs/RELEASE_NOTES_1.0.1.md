# langsuite 1.0.1

A hardening release: friendlier errors, a sturdier Telegram bot and faster startup. No data or workspace format changes; upgrade with `pipx upgrade langsuite`.

## Fixed
- Every CLI error is now one `error:` line plus a `hint:` line, with no Click boxes or tracebacks (use `--debug` for those). Bad options exit 2; Ctrl-C prints "Interrupted." and exits 130; an unexpected crash exits 70 with a link to report it; a closed pipe (`| head`) exits quietly.
- `query "score>=70"` and `rank --filter "grade>=Z"` gave a stale "not built yet (M5c)" error; they now explain score fields and valid grades.
- The Explore pane listed Docs, Score and Snippets as "planned"; they are built.
- Finding commands kept `\uXXXX` escapes for non-ASCII text; they now show the text.
- An unreadable `account.json` was silently replaced; it is now kept as `account.json.bad` with a warning.
- `dashboard rename 3 x` now explains that rename takes the medoid language, not a cluster number.
- The no-base hint said a 15 MB download; it is about 11 MB.
- `bot try` with a non-command now says the bot answers only /commands.

## Bot
- Global error handler: any failure is logged (token redacted) and the person always gets a reply.
- Telegram calls have connect/read/write timeouts and retry flood waits and network errors (3 tries); a reply Telegram will not parse as MarkdownV2 is resent as plain text; one command is capped at 120 s.
- CLI usage errors in the bot point to /help instead of `-h`.

## Performance
- Lazy imports: numpy, telegram, textual and urllib load only when a command needs them; `import langsuite.cli.app` went from about 228 ms to 125 ms, and `--version` from 312 ms to 236 ms.
- Similarity baselines are cached on disk per base snapshot (`<home>/cache/baselines/`), so repeat `similar`/`compare` runs skip the permutation baseline; `similar` went from 529 ms to 385 ms.

## Exit codes

`0` ok · `1` verification failed · `2` no result or bad input · `3` data error · `4` auth · `5` quota · `70` internal error · `130` interrupted.
