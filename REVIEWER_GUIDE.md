# FINN reviewer quickstart

FINN links a material portfolio filing to primary evidence and a relevant person. The core needs no LLM key. Data/source dates and synthetic contacts are labelled.

## Start

```bash
cp .env.example .env
docker compose up --build --wait
curl -fsS http://localhost:8090/health
```

Expect version `0.6.4`, `public_demo:false`, `llm_enabled:false`. Existing M5 users should preserve their `.env` and use [the upgrade steps](docs/UPGRADE_M6.md), including the existing-image override.

Open http://localhost:8090. Anonymous visitors can inspect the supplied evidence/network; **Open my workspace** creates an isolated 24-hour demo workspace without email or keys. Export useful notes/facts before expiry. This is browser-possession access, not a verified investor account.

## Core review

1. **Brief → Historical replay → 7 days**: inspect a material filing, routine disclosures and a fictional contact. All 16 holdings are visible from Portfolio.
2. **Research → INFY**: inspect four FY25 guidance revisions and the 4.2% outcome. Compare original 1–3% (+1.2 pp above the upper bound) with final 4.5–5% (0.3 pp below the lower bound). Open quoted evidence and original PDF pages.
3. Search `currency`; open a hit and its original. Three off-portfolio examples are LTTS, SRF and HAVELLS.
4. Enter a different NSE ticker, choose **Find documents**, wait for status and inspect its exact business/outlook/cash/risk passages. These are extractive passages, not generated financial opinions.
5. Expand **Statements to review**, inspect an original and choose **Review fields**. Confirm the exact quote, numeric values, fiscal period, speaker authority, units, scope, currency basis and publication date. Save a guidance statement and a compatible actual. **Promises and delivery** compares them deterministically for any indexed ticker.
6. Apply an earlier **Evidence available by** date. Later/undated evidence is excluded. A private, explicitly confirmed publication date applies only to the reviewer's fact.
7. **People**: search IT delivery or SRF. Inspect direct/two-hop paths. Try identity checking with Mira Shah / INFY / Delivery lead / 2022-01-01. Name, employer, role and recorded tenure must corroborate a match.
8. Save a fictional contact's private note and last-contact date. In a separate browser/incognito workspace, verify that note is absent. Each workspace has its own holdings, alert preferences/history, profiles and facts.
9. **Workspace**: download/import the fictional JSON example, inspect export and erasure controls. Correction merges by profile ID; withdrawing a profile removes its owned links and notes.
10. **Brief → Live sources**: inspect fresh-source status, completed sessions and alert settings. Refresh needs public-source connectivity; failures stay explicit. Do not treat the historical replay as current data.

Generic arithmetic requires human-reviewed facts. Missing or mismatched periods/bases, unknown authority, changed sources or conflicting actuals do not receive a successful comparison. QoQ/YoY needs matching quarterly baselines; percentage metrics use pp differences.

## Checks

```bash
docker compose exec -T app python -m unittest discover -s tests -v
docker compose exec -T app python -m finn.smoke
docker compose exec -T app python -m finn.acceptance --sessions-only
docker compose exec -T app python -m finn.acceptance --ticker HCLTECH --query revenue
```

Include both Compose `-f` arguments if using the existing-image override. Tests use controlled external responses and no real generation. Smoke uses GETs only. Session acceptance creates two disposable workspaces, checks private-note isolation and erases only those test workspaces. It skips legacy M5 adoption.

Ticker acceptance explicitly starts public document acquisition. Pick a document-rich NSE ticker outside the 19 seed names with no existing source cache. It reports source/page/search coverage and a cold-cache flag. Partial sources/no phrase matches are reported as partial, not silently passed. It does not create reviewed financial facts or demonstrate automated semantic extraction.

## Public demo and optional model

The provided Render configuration opens an anonymous historical preview and allows isolated synthetic workspaces, bounded discovery/refresh and private controls. Scheduled acquisition stays off. The Render preset opts into bounded, free-only OpenRouter synthesis once a server-side key is configured; core workflows still need no key. See [Render AI setup](docs/UPGRADE_RENDER_AI.md). Free-host state may disappear; the dated source seeds remain. A strictly read-only public setting is also available. See [DEPLOYMENT.md](docs/DEPLOYMENT.md).

Local optional AI synthesis is collapsed and off by default. OpenRouter is the default provider: set `FINN_ENABLE_LLM=1`, `FINN_LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY` and `FINN_OPENROUTER_MODEL=openrouter/free` in the ignored `.env`, then recreate the container. Existing explicit Gemini/OpenAI selections must be changed in `.env`; they remain supported as alternatives. Explicitly press Analyze; no generation occurs merely by opening the section. A provider error does not obstruct the main workflows. No automatic paid fallback exists.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md), [PLAN_AUDIT.md](docs/PLAN_AUDIT.md) and [RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) for isolation boundaries, source limitations and checks still requiring an actual deployment or operator.

The OpenRouter option accepts only `openrouter/free` or `author/model:free`, requires JSON-schema support and requests zero-priced endpoints. Its free router is dynamic; the saved result displays the served model and reported cost when supplied. See [the OpenRouter upgrade guide](docs/UPGRADE_OPENROUTER.md).


Indexing performance (M6.4): the local image must be rebuilt for the native parser. Find documents shows the current PDF/page; pressing it again reuses recent indexes for up to six hours. Refresh sources explicitly checks original bytes again. The benchmark and upgrade steps are in [UPGRADE_FAST_INDEXING.md](docs/UPGRADE_FAST_INDEXING.md). Public acquisition limits and the optional free-only OpenRouter policy remain in force.
