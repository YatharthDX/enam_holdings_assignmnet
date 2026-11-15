# Using the YFINN repository

How to run YFINN, configure it, refresh its data and find your way around the code. The product overview is in the [README](../README.md); design decisions are in [ARCHITECTURE.md](ARCHITECTURE.md); hosting is in [DEPLOYMENT.md](DEPLOYMENT.md).

## 1. Run it

**Docker (recommended)**

```bash
cp .env.example .env              # then edit .env (section 2)
docker compose up --build --wait  # http://localhost:8090
docker compose down               # stop; add -v only if you want to erase the data volume
```

**Python 3.12**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
set -a && source .env && set +a   # load your settings into the shell
python -m uvicorn finn.app:app --host 0.0.0.0 --port 8090
```

Open http://localhost:8090. On a phone on the same Wi-Fi, open `http://<your-computer's-IP>:8090` (on a Mac: `ipconfig getifaddr en0`).

There is no frontend build step: `finn/assets/` is served as is.

## 2. Environment variables

Copy `.env.example` to `.env`. `.env` is git-ignored; never commit keys.

### Server and data

| Variable | Default | What it does |
| --- | --- | --- |
| `FINN_PORT` | `8090` | Host port used by `docker compose` (the container listens on 8080). |
| `FINN_DATA_DIR` | `.finn` locally, `/data` in Docker | Where the SQLite database (`desk.sqlite3`) and cached PDF originals are kept. |
| `FINN_AUTO_REFRESH` | `1` | Fetch NSE filings and Yahoo prices on a schedule (local mode only; public mode never schedules). |
| `FINN_REFRESH_SECONDS` | `900` | Interval between scheduled refreshes (minimum 60). |

### Deployment mode and security

| Variable | Default | What it does |
| --- | --- | --- |
| `FINN_PUBLIC_DEMO` | `0` | `1` = public hosting: anonymous visitors get read-only views and fictional data only; scheduled refresh is off. |
| `FINN_INTERACTIVE_DEMO` | `0` | With `FINN_PUBLIC_DEMO=1`, lets visitors open isolated 24-hour workspaces (alert rules, holdings, contacts, bounded indexing). `0` keeps the public site strictly read-only. |
| `FINN_TRUST_PROXY` | `0` | `1` only behind a trusted HTTPS proxy (e.g. Render) so secure cookies and origin checks use the forwarded scheme. Keep `0` for direct local HTTP. |
| `FINN_SESSION_SECRET` | blank | Signing secret for workspace cookies (at least 32 characters). Blank generates one and stores it in the database; changing it signs everyone out. |

### Optional AI

The Brief, results cards, people matching, rule-based guidance and search all work without a model. These settings only affect AI features.

| Variable | Default | What it does |
| --- | --- | --- |
| `FINN_ENABLE_LLM` | `0` | `1` turns on AI features (synthesis, and model-assisted guidance and appointee extraction). |
| `FINN_PUBLIC_LLM` | `0` | In public mode, AI also needs this set to `1`. Public AI is limited to free OpenRouter models and capped at 3 runs per workspace per hour, 5 per hour and 15 per day across all visitors, one at a time. |
| `FINN_LLM_PROVIDER` | `openrouter` | `openrouter`, `gemini`, `openai`, or `auto` (first provider with a key, in that order). There is no automatic fallback after an error. |
| `OPENROUTER_API_KEY` | blank | OpenRouter key. Only `:free` models are allowed. |
| `FINN_OPENROUTER_MODEL` | `dots-studio/dots-3-note-preview:free` | Pinned free model, tested end to end. `openrouter/free` picks a random free model per request, and some cannot finish within the output budget. |
| `GEMINI_API_KEY` / `FINN_GEMINI_MODEL` | blank / `gemini-3.8-flash` | Google Gemini key and model. |
| `OPENAI_API_KEY` / `FINN_OPENAI_MODEL` | blank / `gpt-5.4-mini-2026-03-17` | OpenAI key and model. `FINN_RESEARCH_MODEL` is an older alias for the OpenAI model. |
| `FINN_OPENROUTER_BULK_MODEL`, `FINN_GEMINI_BULK_MODEL`, `FINN_OPENAI_BULK_MODEL` | blank | A cheaper model for high-volume extraction (transcript guidance, appointee profiles). Blank uses the main model. |
| `FINN_LLM_TIMEOUT_SECONDS` | `240` | Per-request network timeout, 30–600. |

### Typical setups

| Goal | Settings |
| --- | --- |
| Local, no AI | `FINN_PUBLIC_DEMO=0`, `FINN_ENABLE_LLM=0` |
| Local with free AI | `FINN_ENABLE_LLM=1`, `FINN_LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY=…` |
| Public demo (as on Render) | `FINN_PUBLIC_DEMO=1`, `FINN_INTERACTIVE_DEMO=1`, `FINN_TRUST_PROXY=1`, `FINN_AUTO_REFRESH=0`; optional AI: `FINN_ENABLE_LLM=1`, `FINN_PUBLIC_LLM=1` and the OpenRouter key in the host's dashboard |

## 3. Command-line tools

Run these from the repository root (inside Docker: `docker compose exec -T app python -m …`).

| Command | What it does |
| --- | --- |
| `python -m finn.snapshot build --days 50` | Rebuilds `finn/data/snapshot.json` from live sources: NSE filings, Yahoo prices, XBRL results and appointee profiles. `--research LTTS,INFY` chooses which companies' transcripts are read for guidance; `--out PATH` writes elsewhere. Run it where NSE is reachable, then commit the file. |
| `python -m finn.sync --once` | One live refresh of filings and prices. Exits non-zero on a partial refresh. |
| `python -m finn.sync --status` | Last refresh and the state of each source. |
| `python -m finn.sync --nse-csv FILE` | Imports a CSV downloaded from NSE's announcements page. |
| `python -m finn.import_pdf --file F --ticker SYM --kind transcript --title T --url URL --published YYYY-MM-DD` | Indexes a PDF you downloaded yourself (`--kind annual_report` or `transcript`). |
| `python -m finn.diagnose` / `--models` | Checks the configured AI key, or lists the free models that support structured output. No generation is attempted. |
| `python -m finn.smoke --base-url URL [--expect-public-demo]` | Read-only health check of a running deployment. |
| `python -m finn.acceptance --base-url URL --sessions-only` | Opens two test workspaces, checks they are isolated, then erases them. `--ticker SYM` instead tests document discovery for a new company. |
| `python -m unittest discover -s tests` | Full test suite (no network or model calls; external responses are simulated). |

## 4. Repository layout

```
finn/
  app.py            HTTP API, sessions, CSRF/origin checks, static files
  runtime.py        Deployment mode flags
  workspaces.py     Signed, expiring per-browser workspaces; holdings, alert rules, export and erase
  live.py           Brief assembly, filing classifier, price/volume/filing alerts, scheduled refresh
  live_store.py     SQLite connection (WAL), shared tables for filings, prices and alerts
  providers.py      NSE announcements and Yahoo daily-bar adapters
  snapshot.py       Builds and loads the shipped real-data snapshot
  results.py        Quarterly results cards from NSE XBRL (Revenue, EBITDA/NII, PBT, PAT; QoQ/YoY)
  people_filings.py Names, roles and career profiles from Regulation 30 disclosures
  network.py        Contacts, introduction paths, link strength, ties to people in filings, reconnect prompts
  discovery.py      Finds annual reports and transcripts for any NSE ticker and indexes them
  documents.py      PDF index, SHA-256 revisions, FTS5 full-text search, cached originals
  pdf_text.py       PDFium text extraction in a time-limited subprocess
  guidance.py       Management guidance from transcripts vs filed results (promised vs delivered)
  research.py       Topic passages, reviewed facts and their comparisons, point-in-time filtering
  analysis.py       Optional AI synthesis: passage selection, one model call, quote verification, caching
  llm.py            OpenRouter / Gemini / OpenAI adapters, model routing, free-only guard
  public_ai.py      Public-demo AI quotas
  desk.py           Seed company list, historical replay, research entry point
  sync.py, import_pdf.py, diagnose.py, smoke.py, acceptance.py   Command-line tools (section 3)
  assets/           Mobile-first web app (HTML, CSS, JS modules), web manifest
  data/
    companies.json  16 portfolio holdings and 3 research names
    network.json    29 synthetic contacts, edges with link strength, investor profile
    relations.json  Competitor / supplier / customer map
    snapshot.json   Shipped real-data snapshot (filings, prices, results, appointees, guidance)
    filings.json, sources.json, research.json   Historical replay and the Infosys FY25 case
tests/              Unit and HTTP tests (python -m unittest)
docs/               Architecture, deployment, usage and AI build history
Dockerfile, compose.yaml, render.yaml   Container, local compose and Render blueprint
.github/workflows/  CI (build the container and run all checks) and the keep-warm ping
```

## 5. HTTP API (summary)

All routes are under `/api/`. Read routes work anonymously; anything that changes data needs a workspace cookie plus the `X-FINN-CSRF` header from `/api/session`, and a same-origin request.

| Route | Purpose |
| --- | --- |
| `GET /health` | Status, version and mode flags |
| `GET/POST /api/session`, `GET /api/workspace/export`, `DELETE /api/workspace` | Open, export and erase a workspace |
| `GET /api/catalog` | Companies, holdings and runtime capabilities |
| `GET /api/brief?mode=live&window=24h\|7d\|custom` | The brief: ranked filings, results cards, people, alerts, prices |
| `GET /api/live/status`, `POST /api/live/refresh` | Refresh state; start a refresh |
| `GET/PUT /api/alert-settings`, `POST /api/alerts/read` | Alert thresholds and read state |
| `PUT /api/portfolio` | Edit holdings (up to 20) |
| `GET /api/research/{symbol}?q=&as_of=` | Research view: passages, promised vs delivered, people, sources |
| `POST /api/research/{symbol}/discover`, `GET …/discovery` | Find and index documents; poll progress |
| `POST /api/research/{symbol}/analyze`, `GET …/analysis?lens=` | Optional AI reading |
| `POST/DELETE /api/research/{symbol}/facts…` | Save or remove a reviewed figure |
| `GET /api/people?q=&symbol=`, `GET /api/people/resolve` | Network search; identity check |
| `POST /api/network/import`, `PUT /api/people/{id}/note`, `DELETE /api/people/{id}` | Import contacts, private notes, withdraw a contact |
| `GET /api/documents/{id}/original` | Cached original PDF |

## 6. Data and privacy notes

- `FINN_DATA_DIR` holds everything that changes at runtime. Deleting it resets the app; the shipped snapshot is reloaded on the next start.
- Workspaces expire after 24 hours. Use **Workspace → Export** to keep notes or facts.
- The public demo accepts fictional profiles only. Real local imports must carry consent, purpose, provenance and an expiry date (see `finn/assets/network-example.json` for the format).
- Only public filing and transcript text is ever sent to a model.
