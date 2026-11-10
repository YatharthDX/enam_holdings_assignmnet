# FINN

A mobile-first Indian-equity investor desk. The primary experience uses sourced documents, deterministic calculations and a fictional professional network. **No LLM or model API key is required for the core workflows.**

**Reviewers:** start with [REVIEWER_GUIDE.md](REVIEWER_GUIDE.md). Optional AI synthesis is disabled by default and appears in a collapsed section after the main research tools.

## Core workflows

| Layer | Working workflow | Method |
| --- | --- | --- |
| Push | Portfolio filing brief, source coverage, daily price/volume signals and saved alert rules | Public-source acquisition, metadata rules and deterministic thresholds |
| Pull | Search primary documents with PDF-page evidence; compare original/revised guidance with an outcome in the historical INFY example | PDF text indexing, keyword retrieval and Decimal arithmetic |
| Network | Relevant contacts alongside filings/research and direct People queries | Explicit synthetic profiles, employer/topic matching and recorded paths up to two hops |

Source search works for any valid NSE ticker whose original documents have been indexed. Deterministic financial/guidance comparisons currently have a curated historical Infosys example; the app does not claim automated financial interpretation for every ticker. Other seeded company snapshots are explicitly historical. Data availability, period and source coverage stay visible.

## Apply the review and deployment update

`FINN_M5_Review_and_Deploy_Update.zip` applies directly over the M2 alerts/announcements/report-indexing milestone, M3 or M4. It includes the optional-AI changes and the diagnostic/timeout fixes, so those earlier ZIPs can be skipped. Existing `.env`, source data, saved settings, caches and Git history are retained. No dependency or Dockerfile changed.

Unzip in the repository root. Set or update this entry in your existing `.env`:

```dotenv
FINN_PUBLIC_DEMO=0
FINN_ENABLE_LLM=0
```

This is also the default if the setting is absent. Existing Gemini/OpenAI keys may remain in `.env`; their presence does not enable generation. Only explicit true values (`1`, `true`, `yes`, `on`) enable the feature. The server blocks generation endpoints and queued requests when disabled, not just their buttons.

For your existing cached Docker image:

```bash
export FINN_PORT=8090
docker compose -f compose.yaml -f compose.local.yaml up --no-build --pull never --force-recreate --wait
curl -fsS http://localhost:8090/health
curl -fsS http://localhost:8090/api/llm/status
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m unittest discover -s tests -v
```

Health should show `version: 0.5.0`, `public_demo: false` and `llm_enabled: false`. Model status should show `enabled: false`. A fresh clone uses `cp .env.example .env` followed by `docker compose up --build --wait`; the cached-image override is for an image that already exists. Its default tag is `enamholdings-app:latest`, configurable through `FINN_RUNTIME_IMAGE`. Named data volumes persist across restarts; do not use `down -v` to apply updates.

Verify the running app without creating jobs or making model calls:

```bash
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.smoke
```

## Public phone demo and delivery

[DEPLOYMENT.md](docs/DEPLOYMENT.md) explains the Render Free Blueprint in `render.yaml` and a temporary HTTPS option for a running Mac. The public configuration sets `FINN_PUBLIC_DEMO=1`: visitors can inspect the historical brief, evidence, guidance comparison and fictional network. The server rejects writes, disables the refresher and forces AI off even if a key and `FINN_ENABLE_LLM=1` are present. The UI opens the dated seven-day replay and explains the read-only boundary.

This public presentation is distinct from the full local workspace, where document discovery, live refresh and alert controls remain available. A free hosted instance can sleep and lose its local filesystem; the built-in historical source set survives because it ships with the code. No real contact data, local database or model credentials belong in the public deployment.

The repository also includes:

- [Architecture and privacy decisions](docs/ARCHITECTURE.md), including changes from the initial plan and deployment limitations.
- [Requirement coverage and final acceptance checks](docs/RELEASE_CHECKLIST.md), with operator checks still marked pending.
- [Covering-email draft](docs/SUBMISSION_EMAIL.md), with link placeholders to complete before sending.
- `.github/workflows/ci.yml`, which builds the actual Docker image, runs tests and checks both local and public modes without real model requests. The workflow has not run on GitHub until the changes are pushed.

## Review the main experience

1. Open [the historical portfolio brief](http://localhost:8090/#brief?mode=replay&window=7d). Inspect a material filing, routine disclosures and relevant fictional contacts.
2. Open [INFY research](http://localhost:8090/#research?ticker=INFY). The primary view shows the historical guidance comparison, then evidence search. Choose a forecast and inspect both its quote and the outcome source.
3. Search `currency`, or choose the `guidance` topic. Inspect a matching passage and its original PDF page.
4. Enter an off-portfolio ticker. Choose **Find documents**, wait for indexing, then search words used in the issuer's original PDF. This requires public source connectivity, not an LLM.
5. Inspect **Who can help?**, then search People by company or expertise. Every profile and introduction path is explicitly synthetic.
6. Choose **Live sources** for current acquisition, market signals, coverage and alert settings. Provider failures are surfaced with the last usable records; historical samples are never substituted as live events.

The primary research page is served even when optional AI settings are invalid or its status is unavailable. With AI disabled, it does not retrieve AI context, poll model jobs or make model requests. The collapsed **Optional AI synthesis** section explains the extra feature without obstructing evidence research.

## Optional secondary AI synthesis

AI synthesis is an enhancement for reading selected public passages. It is not needed to demonstrate Push, Pull or Network. Both Gemini and OpenAI remain supported. Enable it only if desired:

```dotenv
FINN_ENABLE_LLM=1
FINN_LLM_PROVIDER=gemini
GEMINI_API_KEY=your_actual_gemini_key
```

Alternatively use `FINN_LLM_PROVIDER=openai` and `OPENAI_API_KEY`. `auto` selects whichever key is present, preferring Gemini if both exist. Recreate the container after editing `.env`, expand **Optional AI synthesis**, choose a lens and explicitly press **Analyze documents**. Opening the section never makes a generation request. A failed provider call remains confined to this secondary section.

Gemini uses `FINN_GEMINI_MODEL` (default `gemini-3.8-flash`); OpenAI uses `FINN_OPENAI_MODEL` (default `gpt-5.4-mini-2026-03-17`). The old `FINN_RESEARCH_MODEL` variable remains an OpenAI-only override when its newer setting is absent. Model keys stay server-side and are not returned through the UI or API. Keep `.env` out of the public repository and build-session exports.

Public passages are selected deterministically, capped at 18 passages and 36,000 characters across at most five originals. Where no originals are indexed, explicitly labelled historical excerpts can be used. Both providers feed the same structured-output and quotation/page/numerical-literal checks. These establish provenance, not semantic entailment or investment accuracy. Interpretations and evidence gaps are labelled; inspect the source. The core Infosys comparison still uses deterministic arithmetic.

Generation is capped at 3,500 output tokens for OpenAI and 8,192 including thinking for Gemini. The default generation socket timeout is 240 seconds (`FINN_LLM_TIMEOUT_SECONDS`, range 30–600), with job-ownership renewal while a worker waits. It is not an end-to-end completion guarantee. Provider/model/lens/document/prompt identities separate saved results; changing only timeout settings reuses the same answer cache. At most two jobs run concurrently, with no automatic retries or provider fallback.

Optional Gemini free-tier eligibility and quotas depend on the project/model; FINN cannot inspect the Google billing plan. Keep billing disabled if zero spend is required. No Gemini dollar estimate is invented. Provider-reported tokens are recorded; default OpenAI mini estimates use the listed 10 November 2026 rates and exclude project-specific pricing/taxes. Provider billing is authoritative. Google HTTP 503 indicates temporary unavailability; increasing the client timeout cannot resolve a returned 503. Core workflows remain available during provider failures.

For an optional read-only metadata diagnostic after enabling AI:

```bash
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.diagnose
```

This performs a model-metadata GET with a separate 15-second socket timeout, never a generation request. Its safe output distinguishes DNS, TLS, timeouts, authentication, quota and known request parameters. Metadata success does not prove inference capacity, free-tier eligibility or schema acceptance. `--models` lists one bounded page of model IDs. With AI disabled, the diagnostic performs no provider request.

## Milestone 2 operations

Milestone 2 introduced live acquisition and monitoring. Those workflows remain available alongside the new document analysis. New SQLite tables are created automatically when needed.

Start Docker Desktop, then run from the repository root.

```bash
export FINN_PORT=8090
docker compose up --build --wait
curl -fsS http://localhost:8090/health
docker compose exec -T app python -m unittest discover -s tests -v
```

The health response includes `"mode":"live_and_replay"`. Open **http://localhost:8090** and select **Live sources**. Initial acquisition runs in the background, then every 15 minutes while the container runs. The interface polls for completed refreshes and new alerts. **Refresh sources** requests an immediate update.

The settings in `.env.example` can be merged into your existing `.env`. `FINN_PORT` selects the Mac's port. `FINN_AUTO_REFRESH=0` disables scheduled acquisition. `FINN_REFRESH_SECONDS` sets its interval, with a minimum of 60 seconds. Live acquisition and the existing replay do not require API keys. Document analysis uses the optional server-side key configured above. There is no frontend build step.

For a phone on the same Wi-Fi, run `ipconfig getifaddr en0` on your Mac and open `http://<the-printed-IP>:8090` on the phone. Stop the service with `docker compose down`. Its named volume persists across restarts. When using the cached-image override, include both `-f` arguments for subsequent Compose commands as in the existing-repository start instructions above.

### Python option

Use Python 3.11 or newer. Python 3.12 is the verified runtime.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# For this Bash option, load your own local .env if you configured a key there.
set -a
source .env
set +a
python -m uvicorn finn.app:app --host 0.0.0.0 --port 8090
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1`. The app's background refresher starts with the server. Imported and fetched data use `.finn/desk.sqlite3` locally. `FINN_DATA_DIR` selects another directory.

## Live portfolio brief

- **NSE announcements.** The adapter requests a date-filtered seven-day range from NSE, then filters the returned disclosures to the 16 portfolio companies. An ordinary public site session supplies its cookies. If that range is unavailable, the app tries NSE's published RSS feed and labels the result as partial coverage.
- **Time windows.** Last 24 hours and seven days use source timestamps and rolling elapsed time. Custom dates use IST calendar-day boundaries. The filing register keeps fetched routine disclosures accessible.
- **Price and volume.** Yahoo Finance daily series provide provider close prices, volumes and split events. Today's changing candle is excluded until at least 16:15 IST and, when reported, 15 minutes after the provider's session-end time. Each quote shows its session date. Price compares the last two completed sessions. Volume compares the latest session with the preceding 20 sessions, excluding itself.
- **Alerts.** Expand **Alert rules** to enable monitoring, choose filing categories and set the absolute daily price threshold or volume multiple. Price triggers at or above the configured percentage. Volume triggers strictly above the multiple. Insufficient history, missing volume or a split in the baseline suppresses the affected comparison.
- **Persistence.** Repeated acquisition updates existing source attachments and daily bars. Each filing, session and alert type has a stable identity. Marked alerts remain read on refresh. Alert history records signals generated under saved rules; changing rules also evaluates recent cached observations.

NSE subject classification is deterministic and based on filing metadata. A board-meeting notice ranks below published results. Inspect the source document for interpretation. Live filings link to the Research index and the existing fictional network. The historical FY25 comparison is labeled as historical when opened from a current company filing.

### Coverage and recovery

**Source details** reports the latest attempt, last success and failures. Existing records remain available after a failed fetch. RSS contains the latest published items and may omit older records from a requested window. A zero filing count can therefore reflect incomplete source coverage.

Some source endpoints restrict automated access. FINN reports that response. The operator can also download the announcements CSV from [NSE's public page](https://www.nseindia.com/companies-listing/corporate-filings-announcements), choose the intended dates there, and import its actual records.

```bash
docker compose cp /path/to/announcements.csv app:/tmp/announcements.csv
docker compose exec -T app python -m finn.sync --nse-csv /tmp/announcements.csv
```

The CSV needs NSE's SYMBOL, SUBJECT, ATTACHMENT and BROADCAST DATE/TIME columns. Its rows use the same identities as automatically acquired announcements. Operator imports are recorded in Source details. The import confirms the supplied rows rather than asserting completeness of the selected range.

For diagnostics, use these commands.

```bash
docker compose exec -T app python -m finn.sync --status
docker compose logs --tail=80 app
```

An explicit refresh can also run with `python -m finn.sync --once`. A partial result exits with status 1 and prints the per-source errors.

## Automatic primary-document discovery

Open **Research**, enter any NSE ticker and choose **Find documents**. FINN verifies that Screener's public document index names that NSE ticker, selects the latest annual-report PDF and up to four transcript PDFs, downloads their originals, and indexes their text-bearing pages. Repeated indexing at the same source URL replaces the existing revision atomically.

Screener supplies document links only. Financial tables, generated summaries, broker commentary and news from that page do not enter the research evidence index. **Discovered originals** retains links even when a PDF could not be indexed. A document with an unknown exact release date is labeled **Publication date unverified**. The reporting period remains in its title.

Discovery and acquisition can fail independently. An unreadable or denied replacement leaves the last indexed revision available. PDFs over 50 MiB, encrypted PDFs, files over 800 pages and scans without selectable text produce an explicit error. Public HTTPS addresses and redirect targets are checked before downloading.

After indexing, search a distinctive phrase from the company PDF. Each hit includes its original URL and PDF page. After discovery, the Milestone 3 research lenses can synthesize selected passages with checked citations. Existing deterministic historical comparisons remain available.

### Manual PDF import

An operator can retain a verified publication date by importing a downloaded public original directly.

```bash
python -m finn.import_pdf \
  --file /path/to/original.pdf \
  --ticker SYMBOL \
  --kind annual_report \
  --title "Annual report FY 2024–25" \
  --published 2025-07-01 \
  --url "https://issuer.example/investors/original.pdf"
```

For Docker, copy the PDF with `docker compose cp /path/to/original.pdf app:/tmp/primary.pdf`, then run the same import using `docker compose exec -T app python -m finn.import_pdf` and `--file /tmp/primary.pdf`. Accepted kinds are `annual_report` and `transcript`.

## Historical replay and the network

The **Historical replay** selector retains the first milestone's curated issue ending on 17 April 2025. Its 16 holdings, five filings, three off-portfolio snapshots and Infosys comparison remain available.

In the historical research example, Infosys's FY25 constant-currency revenue growth was 4.2%. Select original or revised guidance to see how the comparison changes. Forecasts and outcomes retain their original issuer passages and page references. The historical business snapshots are dated FY24.

People includes 12 fictional profiles with explicit direct and second-degree relationships. Search by company, role or expertise. Inspect an introduction path and a relevant question. This build uses one shared synthetic workspace and public company documents.

## Code and verification

| Module | Responsibility |
| --- | --- |
| `finn/app.py` | HTTP routes, validation, refresh startup and background document/research jobs. |
| `finn/analysis.py` | Optional synthesis context, shared citation checks, usage, ownership and result cache. |
| `finn/llm.py` | Provider selection, HTTPS transports, safe error classification and response normalization. |
| `finn/diagnose.py` | Read-only model-metadata diagnostics with redacted output. |
| `finn/desk.py` | Historical brief, forecast comparisons, source search and network matching. |
| `finn/providers.py` | Public source requests, NSE JSON/RSS/CSV normalization and completed Yahoo daily bars. |
| `finn/live_store.py` | SQLite records, source coverage, refresh ownership and persistent alert history. |
| `finn/live.py` | Scheduled acquisition, filing ranking, daily signals, alert evaluation and live snapshots. |
| `finn/discovery.py` | Generic ticker document discovery, original PDF retrieval and indexing-job state. |
| `finn/documents.py` | Idempotent PDF indexing and consistent page/source reads. |
| `finn/assets/` | Interface for the live brief, evidence, source status, alert controls and fictional contacts. |

Run `python -m unittest discover -s tests -v` in the Python environment, or use the Docker command above. The suite includes actual HTTP entry points and controlled upstream responses for exact threshold boundaries, IST windows, duplicate refreshes, source failure recovery, corporate actions, unknown tickers, document discovery, replacement safety and origin checks. It does not require external provider access.

The default tests make zero external model calls. They exercise controlled model responses over the real HTTP routes, including citations, number rejection, cache invalidation, concurrency, refusal/truncation, redacted provider errors and no-key behavior. JavaScript syntax and the mobile UI were also checked. Live Gemini/OpenAI inference requires the operator’s own key and project access and was not run in the build environment. Docker itself must be verified on the operator’s machine.

This is a single synthetic workspace on a local server. It has same-origin mutation checks, not investor authentication or tenant isolation. Public document text goes only to the selected provider on an explicit analysis request. OpenAI requests set `store: false`, which does not promise zero provider retention; see [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data). Gemini Free-tier content may be used to improve Google products; see [Gemini terms](https://ai.google.dev/gemini-api/terms). Only public issuer evidence is sent; real personal-network data are not part of this prototype. SQLite data/results persist until the operator removes or replaces them; automated retention/deletion and access controls are future deployment work. Do not expose this prototype publicly with a funded key. Production design needs authentication, per-investor authorization, spend limits, encrypted secret storage, consent and deletion controls before real network/contact data are introduced.

The current public demo is intentionally anonymous and read-only; authentication and private multi-user workspaces remain future work. Before submission, publish and test the actual public URL, run the clean-clone and live-source checks, complete the link placeholders and preserve genuine build sessions. See the release checklist for the remaining evidence.

Preserve the actual coding-agent and ChatGPT session exports/share links for ENAM's AI build-history requirement. Keep credentials and real contact data out of the public repository and those exports.

## Source references

- [NSE announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements) and [NSE's published RSS feeds](https://www.nseindia.com/static/rss-feed).
- [Yahoo Finance price history](https://finance.yahoo.com/quote/INFY.NS/history/).
- [Screener document links](https://www.screener.in/company/INFY/consolidated/).
- Curated historical source URLs and locators are stored in `finn/data/sources.json`.

- [OpenAI GPT-5.4 mini model and pricing](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) and [Responses API migration/configuration](https://developers.openai.com/api/docs/guides/migrate-to-responses).

- [Gemini generateContent structured outputs](https://ai.google.dev/gemini-api/docs/generate-content/structured-output), [thinking settings](https://ai.google.dev/gemini-api/docs/generate-content/thinking) and [API reference](https://ai.google.dev/api/generate-content).

- [Google API error codes](https://ai.google.dev/gemini-api/docs/generate-content/api-errors) and [model pricing/tier availability](https://ai.google.dev/gemini-api/docs/pricing).
