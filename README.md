# FINN

A phone interface for an Indian-equity portfolio. Read a filing, inspect company evidence and see who in a fictional investor network has relevant experience.

## Apply Milestone 2

This update adds live acquisition and monitoring to Milestone 1. Extract the update ZIP into the same repository, replacing its included files. The existing SQLite volume holds its documents. New tables are created automatically.

Start Docker Desktop, then run from the repository root.

```bash
export FINN_PORT=8090
docker compose up --build --wait
curl -fsS http://localhost:8090/health
docker compose exec -T app python -m unittest discover -s tests -v
```

The health response includes `"mode":"live_and_replay"`. Open **http://localhost:8090** and select **Live sources**. Initial acquisition runs in the background, then every 15 minutes while the container runs. The interface polls for completed refreshes and new alerts. **Refresh sources** requests an immediate update.

The settings in `.env.example` can be merged into your existing `.env`. `FINN_PORT` selects the Mac's port. `FINN_AUTO_REFRESH=0` disables scheduled acquisition. `FINN_REFRESH_SECONDS` sets its interval, with a minimum of 60 seconds. API keys and a frontend build are unnecessary for this milestone.

For a phone on the same Wi-Fi, run `ipconfig getifaddr en0` on your Mac and open `http://<the-printed-IP>:8090` on the phone. Stop the service with `docker compose down`. Its named volume persists across restarts.

### Python option

Use Python 3.11 or newer. Python 3.12 is the verified runtime.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
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

After indexing, search a distinctive phrase from the company PDF. Each hit includes its original URL and PDF page. This milestone retrieves evidence and computes existing comparisons. LLM extraction and synthesis are subsequent work.

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
| `finn/app.py` | HTTP routes, validation, background refresh startup and document-job initiation. |
| `finn/desk.py` | Historical brief, forecast comparisons, source search and network matching. |
| `finn/providers.py` | Public source requests, NSE JSON/RSS/CSV normalization and completed Yahoo daily bars. |
| `finn/live_store.py` | SQLite records, source coverage, refresh ownership and persistent alert history. |
| `finn/live.py` | Scheduled acquisition, filing ranking, daily signals, alert evaluation and live snapshots. |
| `finn/discovery.py` | Generic ticker document discovery, original PDF retrieval and indexing-job state. |
| `finn/documents.py` | Idempotent PDF indexing and consistent page/source reads. |
| `finn/assets/` | Interface for the live brief, evidence, source status, alert controls and fictional contacts. |

Run `python -m unittest discover -s tests -v` in the Python environment, or use the Docker command above. The suite includes actual HTTP entry points and controlled upstream responses for exact threshold boundaries, IST windows, duplicate refreshes, source failure recovery, corporate actions, unknown tickers, document discovery, replacement safety and origin checks. It does not require external provider access.

This milestone makes zero model calls. Subsequent work includes LLM-assisted extraction and analysis, hosted deployment, authenticated investor workspaces and production retention controls.

Preserve the actual coding-agent and ChatGPT session exports/share links for ENAM's AI build-history requirement. Keep credentials and real contact data out of the public repository and those exports.

## Source references

- [NSE announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements) and [NSE's published RSS feeds](https://www.nseindia.com/static/rss-feed).
- [Yahoo Finance price history](https://finance.yahoo.com/quote/INFY.NS/history/).
- [Screener document links](https://www.screener.in/company/INFY/consolidated/).
- Curated historical source URLs and locators are stored in `finn/data/sources.json`.
