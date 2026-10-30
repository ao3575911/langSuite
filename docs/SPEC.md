# langwish — build spec (no code)

**Tagline:** A research knowledge base of programming languages: how they work, how they relate, with evidence.

## Vision
> A highly valuable resource you can explore to discover, and extract your findings from into your workspace, from research done by analysis and by querying the resource. It writes snippets on demand, explains how to use different languages and when, and answers simple and advanced questions on languages and syntax.

Everything in this spec serves one of five pillars. Every answer carries evidence and provenance.

_Example outputs below are illustrative; numbers, citations and section refs are not real results._

**Distinct from:** langSuite measures natural-language text; glossa is a corpus workbench. langwish studies programming languages.

## Five pillars
| # | Pillar | Commands | Dashboard view | Telegram |
|---|---|---|---|---|
| 1 | Explore and discover | `lang list/show`, `similar`, `cluster`, `influence`, `like` | **Explore**: cluster tree + map + evidence panel (§4a) | /explore, /similar, /cluster |
| 2 | Query | `query` (structured), `ask` (natural language), `docs search/quote` (official docs) | **Ask**: query bar, answer with citations, abstain notice | /ask, /q (DSL), /saved |
| 3 | Analyse | `rank`, `compare`, `diff`, `score` | **Analyse**: sortable score table, breakdown, side-by-side compare (§4b) | /rank, /compare, /diff |
| 4 | Extract to workspace | `extract`, `finding save/list/show/export`, `note`, `workspace` | **Workspace**: findings, notes, saved queries, renames, weight profiles | /extract, /finding, /note, /digest |
| 5 | Write and explain | `snippet`, `guide how`, `guide when` | **Write**: verified snippet, run result, citations, guide pages | /snippet, /how, /when |

**Pillar examples:**
```
$ langwish cluster labels --top 3      # C12 lazy · pure · functional (7 langs, support 0.91)
$ langwish ask "Tail calls guaranteed by spec?"   # Scheme, Lua [R7RS §3.5] [Lua 5.4 §3.4.10] conf 0.82
$ langwish ask "Does Zig have closures?"          # abstains, shows closest sources
$ langwish rank --by score --desc --filter paradigm=functional --top 3
$ langwish compare rust go --criteria all ; langwish diff "binary search" --lang ocaml,haskell
$ langwish extract last --title "Lazy functional cluster"   # saved F-0012 (base-2026.11, 9 evidence ids)
$ langwish snippet "read a CSV and sum a column" --lang rust,python   # python verified ✓ [Python docs csv]
```
**Anti-hallucination (Q&A, guides, explanations):** retrieval-only from KB assertions, docs excerpts and verified evidence; every sentence cites ids, uncited ones removed; below coverage threshold → **abstain** with nearest sources; syntax claims run in the Docker verifier, failures dropped/flagged; levels: simple (lookup, no LLM) / advanced (multi-hop + xAI drafting, same rules); confidence + snapshot hash shown. `extract` saves any result with provenance; guides built from cited assertions, scores and verified snippets.

## 1. Prior art and wedge (checked live 30 Oct 2026 unless marked)
| Source | What it has | What it lacks |
|---|---|---|
| [PLDB](https://pldb.io/) | "over 5,000" languages, 135,000+ facts, public domain | No mechanism-level similarity, no code evidence, no per-user research workspace |
| [HOPL](https://hopl.info/) | 8,945 languages, ~7,800 influence links | Historical roster only; no features or code; licence UNKNOWN |
| Wikipedia infobox "Influenced by/Influenced" | Influence graph used by many hobby visualisations | Unsourced edges common; no features; count UNKNOWN |
| [GitHub Linguist](https://github.com/github-linguist/linguist) | 836 entries (incl. data/markup), MIT | Identification metadata only |
| [Rosetta Code](https://rosettacode.org/wiki/Rosetta_Code) | 1,362 tasks + 423 drafts, 1,016 languages, GFDL 1.2 | Parallel code, but no analysis layer |
| [Nanz & Furia, ICSE 2015](https://arxiv.org/abs/1409.0252) | 7,087 Rosetta solutions, 745 tasks, 8 languages: conciseness, speed, failures | 8 languages; no similarity or clustering |
| [Beyond Language Boundaries (ACM, doi 10.1145/3797138)](https://doi.org/10.1145/3797138) | Embeddings of feature-aligned code, 19 languages, hierarchical clustering into families | LLM-generated samples, 19 languages, aimed at LLM training, not a tool |
| [WSC19 phylogenetic graphs](https://community.wolfram.com/t/wsc19-phylogenetic-graphs-of-programming-languages-using-machine-learning/14436) | Rosetta-based ML language tree | Student project; not reproducible tool (UNKNOWN detail) |
| aichat, sgpt, llm, Copilot CLI | LLM answers | No provenance, no verification (not re-checked live) |

**Wedge:** the first *tool* that joins declared features (PLDB, Linguist), lineage (HOPL, Wikipedia) and code-level evidence (verified Rosetta solutions, structure and embeddings) into one queryable model, at 1,000+ languages, where every similarity claim shows its evidence and source. Academic work proves the method on 8–19 languages; nobody ships it as a research instrument.

## 2. Data sources and licences
| Source | Use | Licence | Count |
|---|---|---|---|
| PLDB | Features, year, creators, lineage | Public domain ([readme](https://github.com/breck7/pldb)) | over 5,000 languages |
| Linguist | Canonical IDs, extensions, aliases | MIT | 836 entries |
| Rosetta Code | Parallel solutions (code evidence) | [GFDL 1.2](https://rosettacode.org/wiki/Rosetta_Code:Copyrights) — **separate data pack**, attributed | 1,362 tasks, 1,016 languages |
| HOPL | Lineage cross-check, names | UNKNOWN — link only, no copying | 8,945 languages |
| Wikipedia | Influence edges | CC BY-SA 4.0 (standard Wikipedia licence; not re-checked) — separate pack if stored | UNKNOWN |
| DevDocs / learnxinyminutes | Doc citations | DevDocs app MPL-2.0, but each bundled doc keeps its upstream licence (apply §2b per doc) / CC BY-SA 3.0 (separate pack) | UNKNOWN |

Code is MIT. GFDL and CC BY-SA material never enters the MIT package; CI fails the wheel build if any file from those packs is inside. Any served Rosetta snippet or share-alike quote carries its attribution and licence line. xAI-generated snippets are labelled "generated" with no licence claim beyond MIT for our wrapper.

## 2a. Inclusion criteria
A language is in the database only if **all three** are publicly reachable on the web or in version control: (1) the language (spec or homepage), (2) an interpreter or compiler, (3) its documentation.

**Inclusion record** (per language, machine-checked): `id, language_url, implementation{repo,kind}, docs{url,format,licence,licence_source}, liveness{…}, last_checked, status: included|flagged|archived`.
- Liveness: HTTP HEAD/GET 2xx–3xx (following redirects); git `ls-remote` succeeds.
- Fails 2 consecutive checks (from 2 regions, to avoid transient blips) → **flagged** (still visible, banner shown, score confidence reduced). Fails continuously for 30 days → **archived**: kept read-only with its last data and history, excluded from default rank/cluster. Never silently deleted. Archive and restore appear in the data changelog.
- Languages in PLDB/HOPL that fail inclusion stay as *reference-only* names (link, no grade).

## 2b. Official docs ingestion
- **Formats:** HTML (readability-style main-content extraction), man pages (mandoc → text), Markdown/reST/AsciiDoc from repos, PDF only if no other format (poppler).
- **Versioning:** docs stored per language version (e.g. Python 3.13, 3.14); default answers use latest stable; `--version` to pin.
- **Chunking:** by heading structure, ~300–800 tokens, never across sections; keep heading path and anchor (`#id`) per chunk.
- **Indexing:** SQLite/DuckDB full-text (BM25) + embeddings (hnswlib); hybrid retrieval then re-rank.
- **Quoting:** answers quote the docs verbatim with link, version and anchor, e.g. `> "..." — Python 3.14 docs, library/csv.html#csv.reader`.

**Licence policy (per docs source, recorded in the inclusion record):**
| Docs licence | Stored | Served |
|---|---|---|
| Permissive / public domain (e.g. MIT, CC0) | Full text | Full quotes |
| Share-alike (CC BY-SA, GFDL) | Full text in a separate data pack, attributed | Quotes with attribution |
| Proprietary / unclear / UNKNOWN | Index + embeddings + link only | Short excerpt (≤ ~2 sentences) + link |
Licence unknown means the strict row. Licences are found from the docs footer or repo licence file and stored with their source URL; per-language licences are UNKNOWN until checked.

## 2c. Data CI
Scheduled GitHub Actions in a separate `langwish-data` repo (nightly liveness, weekly full run, manual trigger):
1. **Liveness** → status. 2. **Change detection:** releases (GitHub tags, PyPI/npm/crates.io…), docs via ETag/Last-Modified → hash → diff. 3. **Re-ingest** changes only. 4. **Re-verify** affected snippets. 5. **Recompute** scores, clusters.
6. **Gates (block publish):** any score moves > 15 points; > 5% of languages flip status; verified-run rate drops > 10 points overall; > 20% of a language's docs chunks vanish; cluster label churn > 30%. Thresholds are starting values. A blocked run opens an issue for review.
7. **Publish** a versioned base snapshot (`base-YYYY.MM.DD`), signed (Sigstore/cosign), as a GitHub release; subscribers `langwish base pull` and verify the signature.
8. **Data changelog:** added/flagged/archived languages, new versions, docs changes, score and cluster changes with reasons.

**Cost and rate limits:** conditional requests (ETag) first; per-host concurrency 1–2 and backoff; respect robots.txt; authenticated GitHub API with request budget per run (limits per GitHub docs, not re-checked); cache all fetches; Docker runs only for changed snippets; shard the weekly run across jobs. Actions minutes on a public repo: free per GitHub's policy (not re-checked; UNKNOWN for private).

**Freshness SLA (max age):** liveness 2 d · release/version 7 d · docs 7 d · snippet re-verify 14 d after toolchain change · scores/clusters 7 d · PLDB/Linguist/Rosetta 30 d. Every field shows its age; past-SLA marked stale.

## 3. Data model
- **Language**: id (Linguist/PLDB key), names, years, sources.
- **Feature** (controlled vocabulary, versioned): evaluation strategy (strict/lazy/call-by-need), type system (static/dynamic, nominal/structural, inference), paradigms, syntax family (C-like, ML, Lisp/S-expr, APL, Forth, …), model (term-rewriting, symbolic, array, stack, logic, actor, dataflow), memory model, homoiconicity.
- **Assertion**: (language, feature, value, source, excerpt, retrieved_at, confidence). Conflicting assertions kept side by side, never merged silently.
- **Edge**: influence (from, to, source) or similarity (from, to, score, method, evidence ids).
- **Evidence**: Rosetta solution (task, hash, verify result), AST/structural feature vector, embedding (model + version).
- **Finding**: query + result + all evidence ids + data snapshot hash. Reproducible.

## 4. Discovery methods
- **Feature similarity:** Jaccard/weighted Hamming on feature vectors.
- **Code similarity:** per task, embed equivalent solutions; average over shared tasks. Structural: tree-sitter node-type histograms, control-flow shape. Only tasks with verified solutions count.
- **Agreement check:** a pair is reported "related" only when feature and code similarity agree, or the disagreement is shown as a finding.
- **Clustering:** hierarchical clustering + bootstrap over tasks for stability; output a tree with support values.
- **Influence graph:** HOPL/PLDB/Wikipedia edges, each edge sourced; compare to similarity ("influenced but dissimilar", "similar but no recorded link" = discovery candidates).
- **"Do X the way Y does":** pick a mechanism from Y (e.g. pattern-matching dispatch in Haskell); rank languages by feature match + code similarity on tasks that exercise it.
- **Baselines:** shuffled-feature and random-task baselines so a score means something.

## 4a. Discovery dashboard and cluster labels
**Layout (TUI and web, same data):**
- Left: cluster tree (dendrogram), each node titled with its label, e.g. **lazy · pure · functional**, plus member count and bootstrap support.
- Centre: cluster map (2-D projection of language vectors, coloured by cluster); select a cluster or language to focus.
- Right: evidence panel for the selection: the label's top features with scores, member coverage ("lazy: 6/7 members, base rate 4%"), sources per assertion, verified Rosetta tasks behind code similarity.
- Bottom: actions: rename label, save as finding, export, compare two clusters.

**Labelling method:**
1. Treat each cluster as one document of its members' feature values (plus structural code features, kept separate).
2. Score features with c-TF-IDF: (share of members with the feature) × log(1 + mean cluster size / feature frequency across all clusters).
3. Cross-check with a one-vs-rest logistic regression; keep features that rank high in both.
4. Keep the top 3 that cover ≥60% of members, drop near-duplicates (e.g. "functional" when "pure functional" is present). Order: evaluation → typing → paradigm/model.
5. Low support (bootstrap <0.5 or coverage <60%) gets a "weak" tag instead of a confident title.
6. Labels are deterministic from data; xAI may only suggest a phrasing, which is shown as a suggestion and must use the same features.

**Evidence and provenance:** every label stores its features, scores, coverage, snapshot hash and method version. Clicking a word shows which members have it and the sources.

**User renames:** stored in the workspace as an overlay (cluster id + snapshot → custom title). The auto label stays visible underneath. When the base updates, clusters are matched by member overlap (Jaccard ≥0.7) and renames carry over; anything below that is flagged for review.

CLI: `langwish dashboard`, `langwish cluster labels [--explain <id>]`, `langwish cluster rename <id> "<title>"`.

## 4b. Language score and grade
**What it means:** the score measures how well-supported and well-evidenced a language is *in this knowledge base*. It does not say which language is "best" for anything.

**Checklist (same for every language, weights published, method versioned `score-v1`):**
| # | Criterion | Definition | Source | Normalisation | Weight |
|---|---|---|---|---|---|
| 1 | Documentation | Beyond the reference required by §2a: tutorial, versioned docs, searchable API index | Inclusion record, DevDocs presence, link check | count / 3 | 12 |
| 2 | Tooling | Package manager, LSP, formatter, test runner present | PLDB, Linguist, LSP registries | count / 4 | 14 |
| 3 | Rosetta coverage | Share of Rosetta tasks with a solution | Rosetta pack | percentile rank across languages | 12 |
| 4 | Verified-run rate | Share of its solutions that pass our Docker verifier | Verifier results | raw rate (0–1); needs ≥20 runs | 12 |
| 5 | Ecosystem size | Packages in main registry | Registry APIs, PLDB | log10, percentile rank | 10 |
| 6 | Maintenance | Release or commit in last 12 months on reference implementation | GitHub/GitLab API, PLDB | 1 / 0.5 (12–36 mo) / 0 | 12 |
| 7 | Standardisation | Formal spec or ISO/ECMA/ANSI standard | PLDB, standards bodies | 0 / 0.5 (spec) / 1 (standard) | 8 |
| 8 | Safety features | Memory safety, type safety, null safety | Feature assertions | count / 3 | 8 |
| 9 | Performance class | Native/JIT/bytecode/tree-walking interpreter | Feature assertions | 1 / 0.75 / 0.5 / 0.25 | 6 |
| 10 | Learning resources | learnxinyminutes page, books, courses listed | learnxinyminutes, PLDB | min(count/3, 1) | 6 |
Weights sum to 100.

**Formula:** score = round(100 × Σ wᵢ·xᵢ / Σ wᵢ over *available* criteria), clamped to 1–100. Missing criteria are excluded, never set to zero.
**Coverage and confidence:** "based on N of 10 criteria"; confidence = (sum of available weights / 100) × mean source confidence. Below 0.5 confidence the grade shows as e.g. "C (low confidence)"; below 4 criteria, no grade ("insufficient evidence").
**Grades:** A ≥ 85, B 70–84, C 55–69, D 40–54, E 25–39, F < 25 (E band pending Adam; if dropped, D 25–54).
**Breakdown:** each score lists per-criterion value, weight, points, evidence ids, sources, and snapshot hash + method version. Points sum exactly to the total before rounding; rounding residue shown.
**User weight profiles:** stored in the workspace (`profile.toml`), shown as "custom score" next to the canonical one. The canonical score never changes per user.

**Rank and sort:**
```
langwish rank --by score|<criterion> [--desc|--asc] [--filter grade>=B paradigm=functional] [--top N] [--profile <name>] [--json]
```
Ties broken by confidence, then name. The dashboard sorts clusters and members by score, grade or any criterion.

## 5. Architecture
```
Data CI (langwish-data, scheduled): liveness → change detect → re-ingest → re-verify/recompute → gates → signed release + changelog | issue
Shared base (read-only snapshots): PLDB, Linguist, Rosetta (GFDL pack), HOPL/Wikipedia, licence-gated docs → ingest → KB (DuckDB+Parquet)
                                   Verifier (Docker per toolchain) → Evidence (verified solutions, ASTs, embeddings)
Front ends: CLI · TUI · Telegram bot · HTTP API + MCP → langwish.core → query engine (base snapshot + tenant overlay)
            → discovery (similarity, clustering, influence, mechanism) → xAI explainer (cited) → finding → workspace → export (CSV/Parquet/JSON/MD/BibTeX)
            core → outbound webhooks → other bots/tools → API
```
- **xAI** only explains and drafts; scores come from deterministic code. Explanations must cite evidence ids; uncited claims are dropped. Non-LLM features work without it (and in local mode).
- **Cache:** content-hashed (inputs + model + snapshot); embeddings and verify results reused.

## 5a. Security and abuse (all front ends)
| Area | Rule |
|---|---|
| Prompt injection | Docs/KB text sent to xAI as quoted data, never instructions; model has no tools; citation filter; ingest strips scripts/hidden text |
| Verifier | Images pinned by digest, rebuilt by data CI; no network, read-only root, seccomp, non-root; CPU/mem/pids/time/output caps |
| Code from chat | Only vetted (KB or previously verified) snippets; arbitrary code off, admin opt-in per group, still sandboxed + daily quota |
| Telegram | Privacy mode on (commands, replies, inline only); token buckets 20/min user, 60/min group (tunable) + PTB limiter |
| Abuse | Input size caps, query timeouts, ban list, admin-only settings, audit log of role changes and code runs |
| Webhooks | HTTPS only; private/loopback/link-local IPs blocked; HMAC + timestamp; backoff; auto-disable on repeated failure |
| Tokens/secrets | API/MCP tokens scoped, hashed, expiring, revocable; BotFather/xAI keys in env or Docker secret, never in DB; logs redact |
| Snapshots | cosign-verified before load; unsigned/mismatched refused (`--allow-unsigned` dev only) |
| Personal data | Only username, Telegram link, settings, events; `account delete` erases (export on request) |

## 6. SaaS (decided: v1 is hosted; CLI, TUI and Telegram are clients)
- **Topology:** `api.langwish.<tld>` (domain TBD) runs core, verifier queue, xAI calls. Clients call it over HTTPS with a device-code login. **Optional local mode** (`langwish --local`, Could): same core against a pulled signed base + local DuckDB workspace, no billing, no Telegram; kept only because core is already client-agnostic.
- **Tenancy:** one tenant = user or team. Shared base read-only (DuckDB/Parquet snapshot per region). Tenant data in Postgres, schema per tenant + row-level security keyed by `tenant_id`; verifier jobs labelled with tenant, no shared scratch; object storage prefixes per tenant; per-tenant encryption keys for exports. Overlay never edits the base; findings pin snapshot hash.
- **Auth:** OIDC (provider TBD, e.g. Auth0/Clerk) for web; device-code flow for CLI/TUI; Telegram via `/start` link code (§6b). Sessions short-lived, refresh tokens revocable; team roles admin/contributor/viewer (same as §6a).
- **Billing:** Stripe Checkout + Customer Portal + webhooks (signature-verified, idempotent by event id). Entitlements cached in core; downgrade keeps data read-only, never deletes.
- **Plans (prices are placeholders):**

| Plan | Price | Asks (xAI)/mo | Verifier runs/mo | Workspaces | Telegram groups | Extras |
|---|---|---|---|---|---|---|
| Free | $0 | 50 | 20 | 1 | 0 | Explore, query, rank, docs search |
| Pro | $12/mo* | 2,000 | 1,000 | 10 | 3 | Thorough mode, exports, API |
| Team | $30/seat/mo* | 5,000/seat pooled | 3,000/seat | unlimited | 20 | Roles, digests, webhooks, MCP, SSO |
| Enterprise | contact* | custom | custom | custom | custom | Region pinning, DPA, SLA credits |
\*placeholder.
- **Quotas and metering:** every core op emits a usage event (tenant, op, units, cost estimate); per-plan hard caps + per-minute rate limits; 80% and 100% warnings; overage off by default. `langwish usage` shows it.
- **SLOs:** API availability 99.5% monthly (Pro/Team), 99.9% Enterprise; p95 latency: lookup/query ≤ 300 ms, `ask` concise ≤ 4 s, thorough ≤ 12 s, verifier ≤ 30 s; error budget policy freezes feature deploys when spent. Status page.
- **Ops:** containerised, IaC, staged deploys, daily Postgres backups (PITR, 30-day retention), restore drill monthly.
- **Privacy/terms:** Privacy Policy, Terms, DPA (Team+), sub-processor list (xAI, Stripe, host, auth provider). Data minimisation per §5a; tenant data not used to train models; xAI zero-retention setting if offered (UNKNOWN). Export + delete within 30 days of request. Legal review before launch.
- **Licensing:** client + core code MIT (anyone can self-host; competitors too, accepted). Hosted service is the product. Rosetta (GFDL 1.2) and CC BY-SA content stay in separate attributed data packs, served with attribution; GFDL does not reach MIT code, and hosted serving of share-alike content keeps its licence notice. Brand/trademark "langwish" kept by Adam.

## 6a. Interfaces and the Telegram bot
**One core, three front ends.** `langwish.core` is a service layer (typed request/response objects, e.g. `ask(Query, Ctx) -> Answer`). CLI (Typer), TUI (Textual) and bot are thin adapters over it; a parity test checks every core operation is reachable from all three (except where Telegram can't render, which falls back to a file).
- **Library (checked on PyPI 30 Oct 2026):** python-telegram-bot 22.8 (12 Jun 2026, Python ≥3.10); aiogram 3.31.0 (26 Aug 2026, Python ≥3.10,<3.15). **Recommend python-telegram-bot:** mature, broad docs, built-in job queue for digests, rate limiter, webhook and polling. aiogram is a fine async-first alternative; its upper Python pin is a mild risk.
- **Commands (by pillar):** /explore /similar /cluster · /ask /q /saved · /rank /compare /diff · /extract /finding /note /digest · /snippet /how /when · /workspace /role /help.
- Inline mode: `@langwish_bot similar haskell` in any chat returns cards.
- Inline buttons: "Evidence", "Sources", "Next ▸ / ◂ Prev", "Save to workspace".
- Output: Telegram MarkdownV2 with escaping done centrally; long output paginated, or sent as .md/.json file. Charts (cluster map, score bars) rendered to PNG with matplotlib.

**Workspaces in Telegram:**
- One workspace per group chat (keyed by chat id) and one personal workspace per user (keyed by user id). Shared knowledge base stays read-only, as in §6.
- Roles: admin (Telegram group admins by default; can change settings, enable code runs), contributor (save findings, notes, queries), viewer (read and query). `/role @user contributor`.
- Every finding records author (Telegram user id + display name at time), chat, time and snapshot.

**Integrating other bots.** Telegram's FAQ says: "bots will not be able to see messages from other bots regardless of mode" ([Bots FAQ](https://core.telegram.org/bots/faq), checked 30 Oct 2026). Any newer Bot API exception for bot-to-bot messaging: UNKNOWN. So integration goes around the chat:
- **Outbound webhooks:** a group can register URLs; events (finding saved, digest ready) POST signed JSON (HMAC).
- **HTTP API:** the core's operations over HTTP (FastAPI), token per workspace, scoped read/write.
- **MCP server:** the same operations as MCP tools so other agents can query langwish.
- **Optional relay:** a small service that forwards another bot's output into langwish via the API and posts results back to the chat.

**Advanced querying in chat:**
- DSL: `/q eval=lazy typing=static score>=70 sort=-score top=5`; same grammar as `langwish query`.
- Saved queries: `/saved add name <dsl>`, `/saved run name`.
- Scheduled digests: `/digest weekly mon 09:00 <saved>` posts results (new findings, changed scores after base update), in the group's set timezone.
- **Deployment:** one `docker compose` with `core` (API + workers), `bot`, `verifier` (Docker-in-Docker or a socket proxy restricted to the run image), and a volume for DuckDB/Parquet. Polling for a laptop or home server (no public URL); webhook behind HTTPS for a server. Cost: Telegram Bot API is free; a small VPS (UNKNOWN price; check provider) plus xAI usage per question (UNKNOWN; depends on plan).
- **Bot hosting:** one official hosted `@langwish_bot` (SaaS); group workspaces belong to the tenant of the admin who adds it. Self-hosted bot only in local mode.

## 6b. Usernames, handles and gamification
**Handle.** At onboarding each user picks a unique `username`; each workspace gets a `slug`. The handle `$langwish/<username>/<workspace>` (e.g. `$langwish/lazyfox/haskell-notes`) is the input placeholder in the CLI/TUI prompt, the app input and header, and Telegram inline input (`@langwish_bot` placeholder set per user where the Bot API allows; otherwise shown in the reply header). Purpose: identity, show and retention, not security.
- **Nominated usernames.** The system proposes 3 by default, user can edit or pick one. Built from the user's stated interests or top explored languages (e.g. `lispwright`, `ocamlo`, `lazyfox`), 4–12 chars, pronounceable, no digits unless needed, availability-checked before display. Deterministic generator + word lists (no LLM needed; xAI optional for flavour, output still filtered).
- **Validation.** `^[a-z][a-z0-9_-]{2,23}$` (3–24 chars, lowercase ASCII, stored case-folded); no `--`/`__`, no trailing `-`/`_`. Workspace slug: same charset, 1–32 chars, unique per user. Reserved list: `langwish`, `admin`, `root`, `api`, `bot`, `help`, `support`, `official`, `staff`, `system`, `null`, command names, language names marked official (e.g. `python`, `rust` reserved for future verified orgs). Impersonation: Unicode confusables (UTS #39 skeleton) and edit distance ≤1 against reserved and existing handles. Profanity: multilingual block list + leetspeak normalisation; borderline goes to a manual review queue.
- **Uniqueness scope.** Global, one table with a unique index on `username_folded` (SaaS). Local mode: per install.
- **Rename.** Allowed once per 30 days. Old handle redirects for 180 days, then is held 90 more days (not claimable by others) before release. Findings, exports and Telegram links keep the stable `user_id`; handles are display only, so renames never break references.
- **Telegram mapping.** `TelegramLink(telegram_user_id → user_id)`, created by `/start` (new user onboards there) or `langwish account link` (one-time code). Group workspace handle: `$langwish/<group-slug>/<workspace>`, group slug chosen by an admin with the same rules; group namespace and user namespace share one uniqueness pool.
- **Privacy.** Handles are private by default (only visible to you and workspaces you share). Public profile (handle, badges, public findings) is opt-in per user; group members see each other's handles in that group only. Telegram display names are never published. Delete account frees the handle after the hold period and erases badges.
- **Gamification (light, opt-out).** Streaks (days with an explore/query/extract action; one free freeze per week), badges (languages explored 10/50/200, clusters visited, findings extracted, verified snippets, first cited answer saved), and a profile level from those counts. No leaderboards by default (group admin can enable a group-only board), no notifications pushing streaks unless opted in, no loss-framed nags, no paid boosts, no rewards for volume of LLM calls. `settings gamification off` hides everything and stops tracking.
- **Data model.** `User(user_id uuid, username, username_folded, created_at, public bool, gamification bool)`, `UsernameHistory(user_id, old, new, changed_at, redirect_until, hold_until)`, `Workspace(+ slug, owner_id|group_id)`, `TelegramLink(telegram_user_id, user_id, linked_at)`, `Group(chat_id, slug)`, `Event(user_id, kind, at, ref)` (append-only; badges and streaks derived from it, so rules can change and recompute), `Badge(user_id, code, awarded_at, rule_version)`.

## 6c. Install, help, output and modes
**Install (one command):** `pipx install langwish && langwish login` (or `uv tool install langwish`; `curl -fsSL https://get.langwish.<tld> | sh` wraps pipx and verifies a checksum). First run: login → username → workspace in < 60 s. README has a detailed Install section: prerequisites (Python 3.12+), pipx/uv/curl paths, login, Telegram `/start`, local mode (Docker), upgrade, uninstall, troubleshooting, each as exact copy-paste commands. Publishing to PyPI needs Adam's OK.

**Help:** `langwish --help` lists every command, grouped by pillar (Explore · Query · Analyse · Workspace · Write · Account · System), one line each, ≤ 60 chars, alias shown beside the name; `langwish <cmd> --help` shows usage + 1 example. Typer + Rich help panels.

**Aliases (every command; collision-free, unique prefixes not relied on):**

| Cmd | Alias | Cmd | Alias | Cmd | Alias |
|---|---|---|---|---|---|
| lang | l | feature | ft | query | q |
| similar | s | cluster | c | influence | i |
| like | lk | dashboard | db | ask | a |
| docs | dc | rank | r | compare | cp |
| diff | df | snippet | sn | guide | g |
| verify | v | extract | x | finding | f |
| note | n | workspace | w | base | b |
| inclusion | inc | account | ac | badges | bg |
| streak | st | settings | set | usage | u |
| login | li | logout | lo | tui | t |
| mode | m | | | | |
Subcommands keep their names (`f ls` = `finding list`; `ls`, `sh`, `rm` are universal sub-aliases). A test asserts every command has exactly one alias, no alias equals another command or alias, and `--help` lists both. Telegram uses the same aliases (`/a`, `/q`, `/s`…).

**Output:** Rich theme `langwish` (one palette, 256-colour + truecolour): tables with aligned numbers, grade chips, syntax-highlighted code (Pygments, language-tagged), citation footnotes `[1]`, evidence panel, spinners for > 300 ms. Plain fallback when not a TTY, `NO_COLOR` set or `--plain`: no ANSI, ASCII borders, same content. `--json` (stable schema, versioned) on every command. Telegram: MarkdownV2 tables as monospace, code as fenced blocks. Snapshot tests per command for rich, plain and JSON.

**Modes:** `default` (direct + clear), `concise`, `thorough`. Precedence: `-m/--mode` flag > workspace setting > global setting (`langwish mode set concise [--workspace]`) > default. Telegram: `/mode`.

| Mode | Length bound (prose) | Always includes | Never includes |
|---|---|---|---|
| concise | ≤ 2 sentences or ≤ 5 table rows; ≤ 60 words | Direct answer, code if the question is about code (≤ 15 lines), ≥1 citation | Background, alternatives, caveats beyond 1 |
| default | ≤ 150 words; ≤ 10 rows | Answer first line, short why, code when relevant (≤ 40 lines), citations, confidence | Long history, exhaustive lists |
| thorough | ≤ 800 words; ≤ 50 rows | Answer, reasoning, alternatives, caveats, version notes, full code (verified), all citations, evidence panel | Uncited claims |
Rules: code is included whenever the question asks how to do or write something, in every mode; code counts against lines, not words. Abstain messages are the same in all modes. xAI is prompted with the contract; a post-processor validates (word/line/row counts, required parts) and, on breach, re-asks once then trims deterministically (truncate at sentence, keep code + citations). Mode recorded in findings.

## 6d. Competitive bar (top of market)
Beats: generic LLM CLIs (aichat, sgpt, llm, Copilot CLI: no citations, no verified code), PLDB/HOPL (no analysis, no workspace), DevDocs (search, no answers or comparisons). Targets, measured in CI on golden sets:
- Answer correctness ≥ 90% on answered, abstain ≥ 95% on out-of-KB (M5d); 100% sentences cited.
- Snippets: ≥ 95% of returned snippets pass the verifier; 0 unverified shown as verified.
- Coverage ≥ 800 languages with grades; ≥ 20 runnable toolchains at launch.
- Latency: SLOs in §6; CLI cold start ≤ 400 ms (lazy imports).
- Mode compliance 100% on the mode test set.
- Onboarding: install → first answer ≤ 2 min in a fresh container.

## 7. CLI
```
langwish lang list|show <lang> [--evidence]
langwish feature list|show <feature>
langwish query "<filter>"            # e.g. "eval=lazy and model=term-rewriting"
langwish similar <lang> [--by features|code|both] [--k 10]
langwish cluster [--method ward] [--bootstrap 200]
langwish influence <lang> [--depth 2]
langwish like "<mechanism>" --as <lang>     # "do X the way Y does"
langwish snippet "<task>" --lang a,b        # [5] verified, cited
langwish ask "<question>" [--level simple|advanced]   # [2]
langwish compare <a> <b> | diff "<task>" --lang a,b  # [3]
langwish extract <last|id> [--title]        # [4]
langwish guide how <lang> | when <a> vs <b> # [5]
langwish verify <file> --lang <lang>
langwish finding save|list|show|export
langwish note add|list
langwish workspace init|import|export|sync
langwish base pull|status|pin <snapshot>|changelog
langwish docs search "<q>" [--lang] [--version] | docs quote <lang> <anchor>
langwish inclusion check <lang> | inclusion list --status flagged|archived
langwish account init [--username u] | suggest [--n 5] | rename <new> | show | privacy public|private | link telegram | delete
langwish workspace rename <slug> ; langwish badges|streak [--json] ; langwish settings gamification on|off
langwish login|logout ; langwish usage ; langwish mode show|set <m> [--workspace]
langwish tui
```
Every command: `-m <mode>`, `--json`, `--plain`, `--local` (local mode), exit codes 0 ok / 2 no result / 3 data error / 4 auth / 5 quota.

## 8. MoSCoW (pillar in brackets)
- **Must:** username onboarding with validation and handle display [all]; KB from PLDB + Linguist [all]; inclusion records and checks [1]; official docs ingest and quoting [2]; data CI with gates and signed releases [all]; feature vocabulary [1]; structured queries [2]; feature similarity [1]; provenance on every result [all]; local workspace with findings, notes, `extract` [4]; JSON/Markdown export [4].
- **Should:** nominated usernames, badges and streaks (opt-out) [all]; scores, grades, `rank`, `compare`, `diff` [3]; dashboard with cluster labels and renames [1]; Rosetta pack + Docker verify, 20 toolchains [5]; verified `snippet` [5]; code similarity, clustering, influence graph [1]; `ask` Q&A with citations and abstain [2]; `guide how/when` [5]; BibTeX export [4]; TUI [all]; Telegram bot with group workspaces, roles, DSL, digests [all]; HTTP API + MCP server + webhooks [4].
- **Must (SaaS):** hosted API, auth, Stripe billing, quotas/metering, tenant isolation; install one-liner; grouped help + aliases; themed output with plain/JSON; three modes with enforcement.
- **Could:** local mode [all]; sync to object store [4]; web UI [all]; 100+ toolchains [5].
- **Won't (v1):** editing the shared base by users; overage billing; web UI beyond account/billing pages.

## 9. Language (decided by default: Python; Adam may revise)
Use Python 3.12+ (uv, Typer, Textual, DuckDB, tree-sitter bindings, scikit-learn/scipy for clustering, sentence-transformers for embeddings). The work is data wrangling, statistics and orchestration of Docker and xAI, where Python's ecosystem is complete and C would mean rebuilding it by hand with more risk of memory bugs. Hot paths (similarity over 1,000² pairs) are small enough for NumPy. C only makes sense later for a tiny embedded probe, not the tool.

## 10. Milestones
- **M0** Repo, CI (ruff, mypy strict, pytest), MIT licence, data-pack layout. *Test:* CI green; a planted GFDL file in the wheel fails CI; licence-check job runs on every PR.
- **M1** KB ingest PLDB + Linguist, feature vocabulary, provenance. *Test:* ≥800 languages; every assertion has source + retrieved_at; `show haskell --evidence` lists sources.
- **M2** Query + feature similarity + baselines. *Test:* golden: Racket in Scheme's top 3; every golden pair ≥3 SD above shuffled baseline mean; same output on two runs.
- **M3** Workspace: findings, notes, saved queries, own data overlay, pinned snapshots. *Test:* add custom language; base upgrade leaves old finding reproducible bit-for-bit.
- **M4** Rosetta pack + Docker verifier (20 toolchains). *Test:* known-good passes, bad fails, network blocked, timeout, memory and fork-bomb caps enforced, image digest mismatch refused.
- **M5** Code similarity, clustering with bootstrap, influence graph, `like`. *Test:* clusters stable (≥0.7 bootstrap support on known families); feature/code disagreements reported.
- **M5b** Cluster labels + dashboard. *Test:* on the golden set, the ML family (SML, OCaml, F#, Haskell) cluster label includes "static"/"type-inferred" and "functional"; the Lisps (Common Lisp, Scheme, Racket, Clojure) include "homoiconic" or "s-expression"; every label word shows ≥1 sourced assertion per member that has it; a rename persists in the workspace and survives a base snapshot upgrade; labels identical across two runs.
- **M5c** Scores and grades. *Test:* same snapshot + method gives identical scores on two runs and two machines; per-criterion points sum to the unrounded total; missing criterion lowers N and confidence but never adds a zero; grade cut-offs at 84/85, 69/70 etc. map correctly; `rank --by score --desc --top 5` and `--asc` return the same set reversed for a fixture; `--filter grade>=B paradigm=functional` returns only matches; a user profile changes only the custom score.
- **M5d** Q&A and guides. *Test:* 50-question golden set (25 simple, 25 advanced): every answer sentence has a citation; ≥90% correct on answered; out-of-KB questions abstain (≥95%); a deliberately wrong syntax claim is caught by the verifier; `extract` of an answer keeps its citations.
- **M5e** Telegram bot. *Test:* parity test passes for all core operations; in a test group, /ask returns a cited answer with Evidence and paging buttons; MarkdownV2 escaping fuzz test sends without errors; group and personal workspaces are isolated; a viewer cannot save, a contributor can, an admin can change roles; findings show the author; /q DSL gives the same result as the CLI; a scheduled digest fires on time; user code is refused unless an admin enabled it; rate limit returns a polite message; a signed webhook arrives and verifies; the MCP server answers `similar`.
- **M5f** Inclusion, docs and data CI. *Test:* a fixture language with a dead docs URL is flagged, then archived after the threshold, and still readable; a docs page change (new ETag/hash) re-ingests only that page; a docs answer quotes verbatim with link, version and anchor; an UNKNOWN-licence doc serves only a short excerpt + link; a fixture score jump > 15 blocks publish and opens an issue; a published snapshot verifies with cosign and `base pull` rejects a tampered one; changelog lists every change in the run; stale fields are marked.
- **M5g** Accounts, handles, gamification. *Test:* onboarding offers 3 available nominations derived from a fixture profile; `Lazy`/`lazy` collide; `l4ngwish`, `langwísh` (confusable) and a profane fixture are rejected; reserved words rejected; rename redirects old handle for 180 days and blocks reclaim during hold; a second rename within 30 days is refused; findings keep `user_id` after rename; CLI prompt, TUI header and Telegram reply header show `$langwish/<u>/<ws>`; Telegram `/start` creates a link and a group slug resolves; private handle not visible to a non-member; streak/badge counts recompute identically from `Event` log; `gamification off` hides badges and records no new events.
- **M5h** CLI UX: help, aliases, output, modes. *Test:* alias table test (unique, complete, in help); `--help` groups match spec and each line ≤ 60 chars; snapshot tests rich/plain/JSON; `NO_COLOR` and pipe give no ANSI; mode precedence flag > workspace > global; on a 60-prompt mode set (20 per mode, incl. live xAI in nightly), 100% outputs within bounds after validation and ≥ 90% before trimming; how-to questions contain code in all modes; abstain identical across modes.
- **M5i** SaaS. *Test:* tenant A cannot read B (API, SQL with RLS, object store, verifier) in an isolation suite; device-code login works from CLI; Stripe test-mode checkout upgrades entitlement, cancel downgrades to read-only; replayed Stripe webhook is ignored; quota reaches 100% → exit 5 with polite message; usage events sum to the invoice preview; restore from backup into staging passes smoke tests; load test meets p95 SLOs; account delete removes tenant data within the window.
- **M6** xAI explanations with citations, TUI, exports, sync bundle, release candidate (no tag without Adam's OK), GIFs. *Test:* uncited sentences stripped; an injected instruction in a fixture doc does not change the answer; local mode passes all non-LLM tests; one-command install works in fresh Linux/macOS containers (PyPI publish only after Adam's OK); webhook to 127.0.0.1 refused.

## 11. Risks
| Risk | Mitigation |
|---|---|
| Feature data inconsistent across sources | Keep conflicting assertions; show disagreement |
| Rosetta coverage skewed to popular languages | Report evidence count; no code score below N tasks |
| Similarity is circular (features from same source) | Separate feature vs code lenses; require agreement |
| GFDL / CC BY-SA leakage into MIT code | Separate packs, CI licence check |
| HOPL licence unknown | Link only, no bulk copy |
| Docker escape / heavy images | No network, seccomp, read-only FS, pull on demand |
| LLM invents facts | Scores deterministic; xAI text must cite evidence ids |
| Tenant data leak | Schema per tenant + RLS, isolation test suite, per-tenant keys |
| Billing errors / webhook spoofing | Stripe signature check, idempotency, reconciliation job |
| xAI cost overruns margins | Metering, hard quotas, cache, concise default for Free |
| Mode drift in LLM output | Validator, re-ask once, deterministic trim, nightly mode tests |
| MIT lets others host a clone | Accepted; moat is data CI, verified evidence, hosted UX, brand |
| Legal (privacy, terms) | DPA, sub-processor list, legal review before launch |
| Labels misleading or trivial | c-TF-IDF + classifier agreement, coverage threshold, "weak" tag, evidence on click |
| Score read as "best language" / bias claims | Published checklist and weights, explicit meaning note, per-criterion evidence, method versioned |
| Popular languages favoured by coverage | Percentile ranks, missing ≠ zero, confidence shown |
| Q&A hallucination | Retrieval-only, citations per sentence, abstain path, run syntax claims |
| Bot token leak | Env/secret file, redacted logs, rotate via BotFather |
| Group abuse or spam | Privacy mode, rate limits, roles, ban list |
| Code execution from chat | Vetted-only by default, admin opt-in, Docker caps and quota |
| Bots can't see each other in groups | Webhooks, HTTP API, MCP, relay |
| Telegram API/library changes | Pin PTB version, adapter layer, contract tests |
| Docs licence breach | Licence gate per source; UNKNOWN = link + short excerpt only |
| Crawl bans / rate limits | ETag, backoff, robots.txt, per-host limits |
| Bad upstream data published | Drift/regression gates, signed releases, rollback by pinning |
| Link rot removing languages | Flag then archive, never delete |
| Data CI cost grows | Incremental runs, sharding, only changed snippets re-run |
| Handle squatting / impersonation | Reserved list, confusable + edit-distance check, rename hold, review queue (hosted) |
| Offensive usernames | Normalised block list, nominations filtered, report path |
| Gamification feels manipulative | Opt-out, no leaderboards by default, no loss nags, rules published |
| Handle leaks identity | Private by default, `user_id` internal, Telegram names never published |
| Prompt injection via docs | Quoted-data prompts, no model tools, citation filter, injection fixture test |
| Webhook SSRF / replay | Private IPs blocked, HMAC + timestamp |
| Toolchain image supply chain | Digest pinning, CI rebuild, signature check |
| Overlap with langSuite/glossa | Scope rule: programming languages only, no NL corpora |

## 12. Decisions and open items
**Decided:** SaaS hosted v1 (local mode optional) · Python 3.12+ (by default; Adam may revise) · global usernames · MIT code, separate GFDL/CC BY-SA packs · xAI · Docker verifier.
**Open for Adam:** 1. Real prices for plans. 2. Auth provider (Auth0, Clerk, other) and cloud host/region. 3. Domain. 4. Embedding model for code (licence check pending). 5. Store Wikipedia edges (CC BY-SA pack) or link only. 6. Rename limits (30-day cooldown, 180+90-day hold) are guesses. 7. Group leaderboards at all? 8. Reserve major language names for official orgs? 9. Keep or drop grade E band. 10. When to create the repo and when to publish to PyPI.
