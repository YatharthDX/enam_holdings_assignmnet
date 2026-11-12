# FINN

A mobile-first Indian-equity research desk for the ENAM Founding AI Engineer Build Challenge. **Push, Pull and Network work without an LLM key.** Optional OpenRouter/Gemini/OpenAI synthesis is secondary and off by default.

**M6.1 adds default, free-only OpenRouter support.** Existing users: follow [UPGRADE_OPENROUTER.md](docs/UPGRADE_OPENROUTER.md); update the provider line in your existing `.env`. The AI feature remains optional and off in a fresh setup.

Start with [REVIEWER_GUIDE.md](REVIEWER_GUIDE.md). See [the plan audit](docs/PLAN_AUDIT.md) for what M6 implements, deliberate design changes and external acceptance checks.

## What works

| Workflow | Behavior |
| --- | --- |
| Push | Portfolio filing brief with IST windows, materiality reasons, routine disclosures, source coverage, completed-session price/volume signals and private alert rules/history |
| Pull | Discover issuer-original PDFs for an NSE ticker, select exact business/outlook/cash/risk passages, search by phrase and inspect page evidence |
| Guidance and figures | Preserve the historical INFY benchmark; review sourced facts for any indexed ticker, compare matching guidance/results and calculate eligible QoQ/YoY changes |
| Network | Relevant contacts inside Push/Pull plus People search, dated employment, explicit paths up to two hops, corroborated identity checks and private reconnect notes |
| Private demo work | Signed browser sessions, workspace-owned holdings/profiles/notes/facts/alerts, consent-gated local profile import, export, withdrawal, erasure and 24-hour expiry |

There are 16 mock holdings, three off-portfolio examples and 12 fictional contacts. Generic discovery and reviewed comparisons do not depend on that seed universe. Quantitative facts require a person to inspect the original and confirm the fields; this is not a universal automatic financial extractor.

## Upgrade an integrated M5 or M6 repository

Apply `FINN_M6_1_OpenRouter_Default_Update.zip` in the repository root. It contains changed/new files relative to M5, including the M6 workflows and OpenRouter update. It does not contain your `.env`, database, credentials or Git history. No Python dependency or Dockerfile changed.

Keep or update these entries in your existing `.env`:

```dotenv
FINN_PUBLIC_DEMO=0
FINN_INTERACTIVE_DEMO=0
FINN_TRUST_PROXY=0
FINN_ENABLE_LLM=0
```

Leave `FINN_SESSION_SECRET` absent or blank to generate a persistent signing secret in the protected database. An explicit override needs at least 32 characters. Changing it invalidates existing access cookies.

For the cached image already built on the Mac:

```bash
export FINN_PORT=8090
docker compose -f compose.yaml -f compose.local.yaml up --no-build --pull never --force-recreate --wait
curl -fsS http://localhost:8090/health
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m unittest discover -s tests -v
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.smoke
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.acceptance --sessions-only
```

Health should show `version: 0.6.2`, `public_demo: false` and `llm_enabled: false`. Open http://localhost:8090 and select **Open my workspace**. Until then the browser sees public evidence and fictional seeds.

The **first normal local workspace** adopts M5 alert preferences and alert read/history state once. Disposable acceptance sessions skip that adoption. Source indexes, public model-result caches and market/filing records remain shared and are not removed by the upgrade. Private workspace data now expire after 24 hours as specified in the design plan. Export before expiry using **Workspace → Export workspace**. The export is a readable snapshot; network profiles/edges can be re-imported, but there is no one-click restore of notes, facts or alerts.

Do not use `docker compose down -v` to update: it removes the named data volume. See [UPGRADE_M6.md](docs/UPGRADE_M6.md) for the commit and validation sequence.

## Fresh clone

Docker with Compose is the simplest option:

```bash
cp .env.example .env
docker compose up --build --wait
curl -fsS http://localhost:8090/health
docker compose exec -T app python -m finn.acceptance --sessions-only
```

The first build needs Docker Hub/PyPI access. `.env.example` selects port 8090; `FINN_PORT` can override it. `compose.local.yaml` is only for an existing compatible image, default `enamholdings-app:latest`; override that tag with `FINN_RUNTIME_IMAGE` if necessary.

Alternatively use Python 3.12:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
set -a
source .env
set +a
python -m uvicorn finn.app:app --host 0.0.0.0 --port 8090 --no-access-log
```

Load only your own trusted `.env` with that shell command. Local data use `.finn/desk.sqlite3` unless `FINN_DATA_DIR` selects another directory; Docker stores them under `/data`. There is no frontend build step.

For a phone on the same Wi-Fi, run `ipconfig getifaddr en0` on the Mac and open `http://<printed-IP>:8090`. Public HTTPS delivery is covered in [DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Walk through the product

1. Open **Historical replay → 7 days**. Follow a material filing to its evidence and relevant fictional contact. Routine disclosures remain accessible.
2. Open **INFY research**. Inspect all four FY25 constant-currency revenue forecasts and the 4.2% outcome. Original 1–3% guidance was beaten by 1.2 percentage points; final 4.5–5% guidance was missed by 0.3 points.
3. Enter another NSE ticker and select **Find documents**. Wait for per-document status, then inspect the topic brief or search a phrase from an original PDF.
4. Expand **Statements to review**. Inspect a source, then **Review fields**. Draft suggestions are conveniences, not accepted facts. Confirm authority, metric, fiscal period, units, scope, currency basis, values and publication date; tick the explicit review confirmation.
5. Save a guidance statement and a reported actual on the same basis. **Promises and delivery** compares them in code. Missing, conflicting, stale or incompatible records produce pending/not-comparable states instead of a fabricated verdict. Source buttons retain the quote, PDF page, issuer URL and cached original when retained.
6. Add reviewed revenue/EBITDA/PBT/PAT, cash-flow or debt figures. **Financial record** calculates QoQ/YoY only when comparable quarterly baselines exist. Percentage metrics use percentage-point differences; amount growth needs a positive base.
7. Apply **Evidence available by**. Later and undated shared sources are excluded. A private fact can retain a publication date explicitly verified by its reviewer; that confirmation does not change the shared document metadata.
8. Query **People** by company, role, education or topic. Inspect dated experience and the recorded introduction path. Identity matching also requires employer, role and event date; namesakes remain unresolved/ambiguous.
9. Add a private contact note and last-contact date. Relevant contacts last contacted at least 90 days earlier can surface a reconnect prompt inside research or an actual filing context.
10. Open **Workspace** for export and fictional network import. Merge by profile ID to correct a record or explicitly replace the network. Withdrawing a profile removes its owned links/notes. **Portfolio** lets you edit up to 20 holdings.
11. Use **Live sources** to refresh current data and edit alert rules. Coverage and source dates stay visible; historical fixtures are never substituted for live records.

## Data pipelines and reliability

**Market data.** Yahoo Finance completed daily bars supply close prices, volume and split events. Today's candle is excluded until the closing buffer (at least 16:15 IST and, when known, 15 minutes after session end). Price change uses two completed closes. Volume uses the previous 20 completed sessions excluding the current one. Insufficient history, missing volume, invalid bases or splits suppress the affected signal.

**Exchange filings.** NSE date-filtered announcements are acquired over a rolling seven-day range. Its RSS fallback is explicitly partial. Metadata rules distinguish notices from published results, retain routine items and explain priority. Repeat acquisition is idempotent. Exact duplicate metadata groups preserve original links; amendments to a known attachment preserve revisions. Different records are not merged speculatively.

**Primary documents.** Screener is a public link index, matched to the requested NSE symbol. FINN selects the first annual report and up to four transcript originals. It does not import Screener financial tables, summaries, broker research or news. “Latest four transcripts” does not guarantee exactly four completed quarters for every issuer; inspect the titles/coverage.

Documents have SHA-256 revisions and parser-version identities. Unchanged bytes reuse the page index. A failed replacement preserves the previous usable revision. Indexed tickers are checked again after relevant new/material filing revisions, with one bounded automatic document refresh per acquisition cycle. A failed lookup can be retried explicitly; there is no unbounded retry loop.

PDF limits are 50 MiB/800 pages locally and 20 MiB/600 pages in public mode. Encrypted PDFs and scans without selectable text produce explicit errors; OCR is deferred. Retained raw originals are capped at 256 MiB locally and 64 MiB publicly. Old originals can be evicted while indexed text/metadata and issuer links remain. Registered retained revisions can be opened from source sheets.

**Professional profiles.** The supplied data are synthetic. Employment, education and acquaintance edges are separate. Shared employers/schools never manufacture an introduction. Import accepts at most 200 profiles/600 edges within a 256 KiB request. Public deployments accept fictional profiles only. Real local imports need an attested opt-in, investment-research purpose, provenance and an unexpired consent date. FINN validates those records; it does not independently verify that consent or an identity is authentic.

## Sessions, privacy and deployment modes

| Mode | Settings | Behavior |
| --- | --- | --- |
| Local | `FINN_PUBLIC_DEMO=0` | Isolated browser workspaces, source acquisition, private controls; optional model feature can be enabled |
| Public interactive | `FINN_PUBLIC_DEMO=1`, `FINN_INTERACTIVE_DEMO=1` | Anonymous evidence preview plus isolated 24-hour synthetic workspaces; bounded manual discovery/refresh; scheduled acquisition off; optional free-only OpenRouter with explicit public opt-in |
| Public read-only | `FINN_PUBLIC_DEMO=1`, `FINN_INTERACTIVE_DEMO=0` | Historical/source preview; every non-read HTTP method rejected |

The supplied Render Blueprint selects public interactive mode. It is not the M5 read-only-only presentation. Document starts are capped at five per workspace/hour and 20 globally/hour, with one public indexing worker. Manual live refresh is capped globally at one per 15 minutes. Existing evidence remains available when caps are reached. Maximum active workspaces: 100; source acquisition union: 100 tickers.

Cookies are signed, opaque, HttpOnly, SameSite=Lax and Secure over trusted HTTPS. Mutations require the signed session, CSRF token and same-origin validation. API queries cannot select another workspace ID. Private responses are not cacheable. Workspace erasure cascades to sessions, profiles, edges, notes, preferences, alert state and reviewed facts; shared public issuer data remain. Expired tokens are rejected immediately; startup/API access and an idle janitor remove expired rows.

These are browser-possession demo sessions, not verified investor accounts or production organization membership. There is no account recovery or multi-device sign-in. SQLite owner filters and foreign keys provide prototype isolation, not PostgreSQL row-level security. Application access logging is disabled to avoid recording private query strings; hosting/proxy log policies remain outside this app. See [ARCHITECTURE.md](docs/ARCHITECTURE.md).

`FINN_TRUST_PROXY=1` is only for a trusted HTTPS reverse proxy; direct local HTTP uses 0. Without HTTPS, an HTTP LAN demo is not suitable for sensitive real profiles. The app creates no backup service; production backup encryption/deletion policies and durable private hosting are not implemented.

## Source operations

Local acquisition starts with the server when `FINN_AUTO_REFRESH=1` and repeats every `FINN_REFRESH_SECONDS` (default 900, minimum 60). Public mode disables that scheduler regardless of the flag. Source status exposes attempts, last success and partial/error coverage. Empty/failed feeds are not evidence that no filings exist.

Operators can import a downloaded official NSE announcements CSV:

```bash
docker compose cp /path/to/announcements.csv app:/tmp/announcements.csv
docker compose exec -T app python -m finn.sync --nse-csv /tmp/announcements.csv
docker compose exec -T app python -m finn.sync --status
```

Use the same two `-f` arguments on these commands if running the cached-image setup. Expected columns are NSE SYMBOL, SUBJECT, ATTACHMENT and BROADCAST DATE/TIME. Import records the supplied rows and does not assert full-window completeness. `python -m finn.sync --once` performs an explicit source refresh; partial acquisition exits nonzero.

Manual import of a downloaded public original:

```bash
python -m finn.import_pdf --file /path/to/original.pdf --ticker SYMBOL \
  --kind annual_report --title "Annual report FY2025" --published 2025-07-01 \
  --url "https://issuer.example/investors/original.pdf"
```

Accepted kinds: `annual_report`, `transcript`. For Docker copy the file into the container and run the module there. These are operator tools; they do not import private contact data into public evidence.

## Optional secondary AI

OpenRouter is the default provider when optional AI is explicitly enabled. To use it locally, update your existing `.env`, recreate the container, open a workspace and select **Optional AI synthesis → Analyze documents**:

```dotenv
FINN_PUBLIC_DEMO=0
FINN_ENABLE_LLM=1
FINN_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_actual_key
FINN_OPENROUTER_MODEL=openrouter/free
```

An existing explicit `FINN_LLM_PROVIDER=gemini` or `openai` remains effective until you change that line. The update does not overwrite `.env`. OpenRouter keys are separate from Google/OpenAI keys and stay server-side.

`openrouter/free` chooses an available compatible free model dynamically. FINN records the returned actual model with the saved result. For repeatable evaluation, you can explicitly pin a currently available `author/model:free` ID through `FINN_OPENROUTER_MODEL`. Paid OpenRouter model IDs are rejected before network access; the request also requires schema-capable endpoints, disables provider fallback and caps prompt/completion/request pricing at zero. A missing compatible endpoint is an explicit error, not a reason to drop validation or switch to a paid model. OpenRouter/provider capacity and quota remain external.

Gemini and OpenAI remain available by setting `FINN_LLM_PROVIDER=gemini` / `openai`, their corresponding API key and optional model override. `auto` selects the first configured key in this order: OpenRouter, Gemini, OpenAI. With no keys, it shows the unconfigured OpenRouter option. Selection is frozen when a job starts; no runtime provider fallback or automatic retry occurs. Key presence alone never enables generation, and expanding the section does not generate.

Only up to 18 public source passages/36,000 characters enter a request, across at most five originals. Private contact names, notes, holdings and reviewed facts are excluded. Source-span/page/number checks establish traceability, not semantic entailment. OpenRouter and its selected downstream provider process those public passages under their respective policies. As-of research disables synthesis. Public AI additionally requires `FINN_PUBLIC_LLM=1` and an explicit `FINN_LLM_PROVIDER=openrouter`. Only the free-only adapter is permitted. See [Render AI setup](docs/UPGRADE_RENDER_AI.md).

OpenRouter uses non-streaming Chat Completions with a strict JSON schema and an 8,192-token output cap. Reasoning text is discarded; visible content is normalized into the shared verifier. Refusals, truncation, tool calls, malformed output and error envelopes are not published. Provider/model/lens/document/prompt identities separate result caches; a changed provider does not erase old results. The free router's cache uses its requested route identity while the served model is recorded in usage.

Jobs renew ownership while waiting, with at most two concurrent generations. Default socket timeout is 240 seconds, configurable from 30–600; it is not an end-to-end guarantee. Provider-reported cost (including a reported zero), token counts, actual model and latency are recorded when supplied. Missing cost remains unknown; FINN does not infer a bill of zero from the model name. Existing OpenAI estimates remain separate. No real inference or user-key request was run in build verification.

For a read-only check after restart:

```bash
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.diagnose
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.diagnose --models
```

For OpenRouter, the first checks key metadata and the second lists bounded free schema-capable catalog IDs. These GETs do not generate or prove inference capacity. Disabled AI causes no provider access. Keep keys out of Git and shared AI-session exports.

Official integration references checked 11 November 2026: [Chat API](https://openrouter.ai/docs/api_reference/overview), [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [routing](https://openrouter.ai/docs/guides/routing/provider-selection), [free models and quotas](https://openrouter.ai/collections/free-models). Free availability is quota-limited and can change; no credit purchase is required for the documented `:free` variants.

## Verification and submission

```bash
python -m unittest discover -s tests -v
python -m finn.smoke --base-url http://localhost:8090
python -m finn.acceptance --base-url http://localhost:8090 --sessions-only
python -m finn.acceptance --base-url http://localhost:8090 --ticker HCLTECH --query revenue
```

The first three do not start model calls or upstream indexing. The last explicitly fetches public originals for an unseeded ticker and tests a cold source cache; choose another unseeded symbol if that one is already indexed. `--allow-cached` weakens that condition deliberately and is reported. Partial indexing or no chosen-phrase matches returns status `partial`/exit 2. A pass is not proof of automatic financial interpretation.

Tests exercise actual loopback HTTP routes with controlled upstream/model responses. Browser checks cover the new research/review/source, identity, note and workspace controls at desktop/phone widths. Real source connectivity, an independent live ticker, Docker/CI execution, public deployment and second-person phone usability still require the operator checks in [RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).

The public repository, phone-accessible URL, genuine AI-build sessions and short covering email are the submission. See [SUBMISSION_EMAIL.md](docs/SUBMISSION_EMAIL.md). No public URL, repository push or email is created simply by including their instructions.
