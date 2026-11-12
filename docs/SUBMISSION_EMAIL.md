# Covering email draft (fill the links before sending)

To: assessment@enam.com
Subject: IIT Kanpur – Founding AI Engineer - 2027

Dear ENAM team,

- Phone demo: https://finn-demo-ojov.onrender.com
- Repository: [GITHUB URL]
- AI build history: [SESSION LINKS / EXPORTS]

**What I built.** FINN is a mobile-first desk around one loop: something changed → is it material → what do the primary sources say → who do I know who can explain it.

- *Push:* portfolio filings ranked by materiality using NSE's own subject plus the filing text. Results arrive with Revenue/EBITDA/PBT/PAT, QoQ and YoY, computed from the company's XBRL filing rather than a PDF. A management change arrives with the appointee's career read from the company's Regulation 30 profile, and the contacts whose dated careers overlap it. Price, volume and filing-type alerts are configurable per workspace.
- *Pull:* for any NSE ticker FINN reads the last eight call transcripts and two annual reports and extracts management's numeric guidance (quote and figures verified against the page). It then scores it against filed results: delivered, missed, tracking, or not comparable (e.g. constant-currency guidance vs INR filings), with revisions shown as a chain (Infosys FY27 revenue: 1.5–3.5% → 1.5–3% → 1–2%; operating margin 20–22%, delivered 20.9% in FY26).
- *Network:* fictional contacts with dated careers, schools and link strength. FINN finds overlaps the investor would not remember (an ICICI colleague for HDFC Bank's new CEO, a Reliance Energy colleague for Tata Power's), ranks two-hop introductions by their weakest link, explains competitor/supplier relevance, and prompts a reconnect when a contact's former employer files something material.

**Key decisions.** Numbers are computed in code from exchange XBRL; models only read prose (transcripts, profiles), every string they return must exist in the source, and every verdict is made by code. A cheap/free model handles bulk extraction with rules as the fallback; an optional stronger call does synthesis. Everything is cached by document revision, so the demo runs at zero cost. Because NSE blocks most cloud IPs, a dated snapshot of real data ships with the image and a live refresh supersedes it.

**Architecture, security and privacy.** One FastAPI service, native JS, SQLite (WAL, FTS5), one Docker image on Render Free. Each browser gets a signed, expiring, erasable workspace; contacts and notes never leave it or reach a model. Real-profile imports require recorded consent, purpose and provenance; the public demo accepts fictional profiles only. Details and production next steps are in docs/ARCHITECTURE.md.

**Left out.** OCR, a security master, real accounts and backups, native push notifications. Next: web-push/Telegram alerts, a nightly ingestion job on an Indian-IP runner, segment/constant-currency actuals from results releases, and a grounded narrative-vs-numbers pass.

Regards,
Yatharth Sharma
