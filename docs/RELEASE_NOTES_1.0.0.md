# langsuite 1.0.0 — release notes

A research knowledge base of programming languages, with evidence, from the CLI, a Textual app, or a Telegram bot.

Install: `pipx install langsuite` or `uv tool install langsuite`. Published from a signed tag; see [RELEASING.md](RELEASING.md).

## What's in 1.0.0

- **Knowledge base (M1).** 5,000+ languages from PLDB and Linguist, each fact with its source. `base build/status`, `lang list/show --evidence`, `feature list/show`.
- **Query and similarity (M2).** A structured `query` DSL, and `similar` with a shuffled-feature baseline that reports z-scores.
- **Workspaces and findings (M3).** Findings record the command, snapshot, evidence ids and a result hash, and `finding verify` re-runs them bit-for-bit. Also notes, saved queries, your own languages overlaid on the base, and `base pin`.
- **Verified snippets (M4).** `verify` runs code in an offline Docker sandbox pinned by digest, with 20 toolchains. `snippet` shows attributed Rosetta Code solutions, marked verified only when they actually ran.
- **Telegram bot (M5e).** `langsuite bot run` exposes the same commands and aliases as the CLI. Each chat gets its own workspace, with admin/contributor/viewer roles, authored findings and rate limits. Code runs are off until an admin turns them on. `/start` walks you through claiming a handle and a workspace, and replies are headed `$langsuite/<handle>/<workspace>`. `bot try` simulates the bot offline.
- **App (M0b).** Seven panes, a command palette, themes including high contrast, plain mode, and a browser view via `ui --serve`.
- **Data hygiene (M0).** Data packs are kept separate by licence, and CI checks that the wheel contains no copyleft documentation content.

## Requirements

Python 3.12+ on Linux or macOS. Docker is optional and only needed for `verify` and verified snippets. Running the bot needs a BotFather token in `LANGSUITE_TELEGRAM_TOKEN`.

## Not in 1.0.0 (planned)

| Milestone | Scope |
|---|---|
| M5, M5b, M5c | Code similarity, clusters, scores and grades |
| M5d | Cited answers, how/when guides, bot `/ask` |
| M5f | Signed snapshots, `base pull`, `base changelog`, data CI |
| M5g | Accounts, handles, opt-in gamification |
| M5h | CLI modes and output bounds; bot inline mode, digests, webhooks, MCP |
| M5i | Hosted SaaS, `workspace sync`, billing (test mode first) |
| M6 (rest) | xAI explanations with citations, hosted `serve`, a11y audit, sync bundle, GIFs |

## Known limits

- The bot uses long polling only (no webhooks yet).
- Rosetta Code snippets cover 7 tasks so far.
