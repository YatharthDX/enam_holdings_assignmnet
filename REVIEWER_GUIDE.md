# FINN: reviewer quickstart

FINN's core prototype requires no LLM credentials. It combines a portfolio brief, source-backed research and a clearly fictional professional network. Optional AI synthesis is off by default.

## Start a fresh clone

Requirements: Docker with Compose. From the repository root:

```bash
cp .env.example .env
docker compose up --build --wait
curl -fsS http://localhost:8090/health
```

Health should report version `0.4.0` and `llm_enabled:false`. No model key is required. The first build needs Docker Hub/PyPI access. Port 8090 can be changed with `FINN_PORT`.

Existing users applying the update should follow the cached-image instructions in README. The ZIP preserves an existing `.env`; add `FINN_ENABLE_LLM=0` to keep the secondary feature disabled.

## Three-minute core review

1. [Historical brief, seven-day window](http://localhost:8090/#brief?mode=replay&window=7d): inspect a material result and lower-priority disclosures. Open the original evidence and a relevant fictional contact.
2. [INFY research](http://localhost:8090/#research?ticker=INFY): compare original/revised FY25 guidance with the reported outcome. The arithmetic is deterministic and the historical period is labelled. Open a forecast source and the outcome source to inspect quotes and PDF pages.
3. Search `currency` or choose the `guidance` topic. Inspect a page-linked passage, then the original PDF.
4. Open **Who can help?** or query **People** by company/topic. Inspect direct and recorded two-hop paths. All 12 profiles are fictional.

## Review public-source acquisition

Enter another NSE ticker in Research and select **Find documents**. FINN discovers the latest annual-report original and up to four transcript originals, indexes selectable PDF text, then supports keyword search with source/page links. Discovery uses Screener as a link index; it does not import its summaries, financial tables, broker commentary or news as evidence.

**Brief → Live sources** shows current filing acquisition, completed daily market sessions, alert controls and provider freshness/coverage. These operations need public NSE/Yahoo/Screener access. Errors and partial coverage stay visible; fictional fixtures are never supplied as live data. A zero count with incomplete coverage is not proof of no filings.

Generic document retrieval/search works for indexed tickers. Structured deterministic financial/guidance comparison has a curated historical Infosys example; the prototype does not claim automated comparison for every issuer. Other supplied snapshots are explicitly historical.

## Run checks without external API costs

```bash
docker compose exec -T app python -m unittest discover -s tests -v
```

Tests use controlled upstream/model responses and make no real generation requests. They cover HTTP entry points, PDF ingestion/search, comparison boundaries, network paths, provider failures, optional-feature isolation, blocked generation while disabled, both model transports and cache/ownership behavior.

## Optional AI review

The primary workflows above are sufficient to inspect the working prototype without a model provider. The collapsed **Optional AI synthesis** section below evidence search adds a generated reading only if enabled.

1. Set `FINN_ENABLE_LLM=1` in `.env`.
2. Set either `GEMINI_API_KEY` or `OPENAI_API_KEY`. `FINN_LLM_PROVIDER=auto` uses the available key and prefers Gemini if both exist; explicit `gemini` / `openai` selects only that provider.
3. Recreate the container: `docker compose up -d --force-recreate --wait`.
4. Expand **Optional AI synthesis**, choose a lens and explicitly select **Analyze documents**. Inspect its quotations, source pages and limitations. Reopening a saved lens makes no new model call.

Opening the optional section never triggers generation. A provider error or invalid optional configuration does not prevent primary research. Keys stay server-side. Provider access/quotas are the reviewer's responsibility; live inference was not run during build verification. There is no automatic retry or paid fallback. Keep Gemini billing disabled when zero spend is required.

`GET /api/llm/status` is read-only. `python -m finn.diagnose` performs metadata access only when optional AI is enabled and never generates an answer. The README describes provider setup, data/privacy boundaries and architectural limitations.

This is a local single synthetic workspace, without production investor authentication or tenant isolation. No real contact data are included.
