# M6 audit against the original design plan

Audit basis: the eight-page “FINN design and build plan” dated 9 November 2026, the ENAM main challenge and reference taxonomy/glossary. M5 is the integration baseline. This audit distinguishes working code from an external check or an intentionally changed design; file/config existence is not execution evidence.

The assignment asks for a focused working prototype across Push, Pull and Network. Its eight research views and Push enrichment examples are options, not eight mandatory dashboards. The original plan itself prioritized business snapshot, guidance and narrative versus numbers.

## 1. Assignment and scope — plan page 1

| Plan item | M6 implementation / evidence | Qualification |
| --- | --- | --- |
| Filing → evidence → person journey | Inline source/person sheets, Research and People links in historical/live Brief and Pull | Real-source/source-link audit and second-person phone timing still required |
| 15–20 holdings, 3–5 ad-hoc names | 16 holdings; LTTS/SRF/HAVELLS; editable private portfolio | Current seed-symbol and source coverage must be checked against official sources |
| Generalise beyond seeds | Generic NSE-symbol discovery; original-PDF search/extractive brief; reviewed fact comparison for any indexed symbol | Controlled cold-ticker HTTP/indexer test passes; independent real ticker remains operator acceptance |
| Four inputs and source provenance | Yahoo EOD, NSE announcements, issuer-original PDFs, synthetic/attested local profiles | No news/broker/model-memory evidence enters Pull |
| Optional result/executive enrichments | Reviewed revenue/EBITDA/PBT/PAT with eligible deltas in Pull; conservative incoming-person corroboration | No automatic four-line results extraction in Push or general executive biography |
| Phone-accessible submission | Interactive public Blueprint plus reproducible local container | Actual hosted URL, public repo and build-history links are not created by code |

## 2. Mobile interaction — plan page 2

| Plan item | M6 behavior | Evidence / boundary |
| --- | --- | --- |
| Priority before chronology, event/time/reason | Materiality ranking, filing counts, routine group, IST windows, coverage and controls | Threshold/window/source fixture tests |
| Figure opens evidence | Quote/title/date/PDF page, issuer URL and retained cached original | Actual browser source-sheet check; registered revision HTTP test |
| Back preserves context | Hash routes preserve ticker/query/date/window; per-route scroll positions; sheets close in place | Browser navigation reviewed; second-device usability check remains |
| One reusable person card | Brief, Research, People and identity results share source/person-sheet primitives | Direct/two-hop and dated tenure shown |
| 360–430 px | One-column phone navigation and readable controls; financial table scrolls inside its container | Checked 360/390/430 px without page-level horizontal overflow |
| Loading/empty/offline/slow source states | Polling, explicit missing evidence/coverage, retries and cached usable sources | Controlled failures; live host cold-start/outage run still pending |

## 3. Push and Network — plan page 3

| Plan item | Implementation | Qualification |
| --- | --- | --- |
| 24h, 7d, custom IST windows | Source-timestamp filtering, custom IST day boundaries | Public preview intentionally opens historical 7d |
| Materiality distinction | Results/deals/substantive changes prioritized; notices/routine grouped with reasons | Metadata rules, not full-document event interpretation |
| Configurable filing/price/volume alerts | Private rules and history; defaults ≥5% price, >2× prior-20 volume | Active/invalid/insufficient/split-affected bases suppressed |
| Idempotency and revisions | Stable per-workspace/event/session/signal identities, exact duplicate groups and retained attachment amendments | Does not guess that different URLs are the same underlying event |
| 12 fictional profiles and breadth | Direct/two-hop seed; portfolio/peer/off-portfolio/unrelated employment coverage | No real profile scraping |
| Relevant employer/topic/path/recency | Private-network recommendations in both Push/Pull and direct query | Shared employer/school alone never creates an edge |
| Incoming-person corroboration | Explicit appointment metadata nominates name/role; full name/employer/role/tenure checked | Unknown/ambiguous stays unresolved; no automatic bio |
| Quiet window | Actual window, coverage, wider selectors and dated replay | Empty partial feed does not claim completeness |
| Reconnect value | Private last-contact/note; event or research reason after 90 days | No person-directed communication is sent |

## 4. Pull and evidence — plan page 4

| Plan item | Implementation | Qualification |
| --- | --- | --- |
| Historical known-answer test | All four FY25 INFY CC-growth ranges plus 4.2% actual, cited pages and Decimal math | Preserve late miss rather than showing only original target |
| Generic discovery | Verify NSE symbol on public link index; annual report + up to four transcripts | Link ordering does not guarantee exactly four completed quarters |
| Business snapshot and missing guidance | Exact source-topic brief and explicit missing coverage | Rule-selected excerpts, not a generated comprehensive company assessment |
| Speaker, period, units, scope, basis | Candidate labels plus explicit reviewed fact schema and exact-quote/literal-value checks | Human reviewer confirms semantic/accounting interpretation |
| Revisions and comparison states | Separate forecasts; above/within/below/pending/not-comparable; stale/conflicting/unknown cases withheld | Universal automatic financial table/guidance extraction remains outside scope |
| Qualitative statements | Reviewed qualitative record with source quote; displayed as evidence | Not automatically scored into quantitative verdicts |
| As-of evidence | Cutoff excludes later/undated sources/facts; private confirmed dates stay private | Not an exchange-authoritative point-in-time data archive |
| Financial snapshot/deltas | Reviewed metrics with eligible QoQ/YoY and baseline source links | Full trajectory/balance-sheet/bull-bear dashboards remain optional future views |

## 5. Data and demo selection — plan page 5

| Plan item | Implementation | Qualification |
| --- | --- | --- |
| Completed-session EOD bars | Session buffer, source/session date, previous-close and split-aware prior-volume baseline | Yahoo adapter; no real-time/intraday quote feed |
| Filing acquisition and gaps | Overlapping range acquisition, partial RSS fallback, official CSV import and attempt/success coverage | Real exchange-window reconciliation remains pending |
| New filings refresh tracked reports | Material/new metadata revision queues bounded document re-index | One queued issuer per acquisition cycle; no paid hosted scheduler |
| Source hash + parser version | Stable indexed identities, no-op unchanged parser cache, transactional replacement | No OCR/complex table reconstruction |
| Original retention | Bounded hash-addressed PDF cache with registered revision access | Old bytes may be evicted; text/metadata/issuer URL remain |
| Private dated profile import | Seed once/session; JSON merge/replace, separate employment/edges, explicit unknowns | Real local consent is attested, not independently verified |
| Security master | Shared validated NSE symbol links all four inputs | ISIN/alias history and BSE-only coverage not implemented; deliberate prototype scope |

## 6. Architecture and code design — plan page 6

| Plan item | M6 implementation | Change from proposal |
| --- | --- | --- |
| Small reproducible web/API | FastAPI, native JS modules, one Docker image | Native JS replaces React/TypeScript |
| Persistent public/private rows | SQLite with explicit owner keys, restricted files and foreign-key cascades | PostgreSQL/RLS replaced for prototype; not claimed production-equivalent |
| Worker/scheduler ownership | Bounded background jobs with tokens/leases, local refresher and idle expiry janitor | No independent managed queue/worker fleet |
| Original/page storage | Local bounded hash cache and transactional page index | No managed private object bucket |
| Shared public / private split | Public source cache; private holdings/rules/profiles/notes/facts/alerts | Both boundaries implemented within one SQLite service |
| Capabilities and public delivery | Local, public interactive and strict public read-only modes | Free demo state can disappear; durable hosted private state remains future infrastructure |

## 7. Privacy, models and verification — plan page 7

| Plan item | M6 implementation | Remaining boundary / check |
| --- | --- | --- |
| Signed sessions and owner checks | HMAC cookie, stored token hash, CSRF/origin checks, server-selected owner, no-store API | Browser possession, not verified investor membership/recovery |
| HTTPS/secrets | Secure cookie over HTTPS; trusted-proxy flag; keys server-side | Actual deployment TLS/proxy check remains required |
| 24h expiry and erasure | Immediate expiry rejection plus startup/access/idle cleanup; cascading delete and export | User exports and external host logs outside app control |
| Consent/correction/withdrawal | Local real import requires recorded purpose/provenance/expiry; ID merge and delete controls | Attestation only; public imports synthetic only |
| Postgres non-owner RLS | Explicit SQLite owner filtering tested across two cookie jars | Stack deviation; production RLS not implemented |
| Deleted-data backups ≤30 days | No application backup service exists | Proposed policy must be implemented/tested if backups are introduced |
| Model privacy/efficiency | Optional OpenRouter/Gemini/OpenAI, public passages only, citation/number checks, result cache, token/latency records | No live inference/cost benchmark in this build; no paid fallback |
| Code handles matching/arithmetic/permissions | Deterministic retrieval/ranking/thresholds/comparisons/paths; explicit review | No autonomous agent actions or inferred contact outreach |
| Push/Pull/People acceptance | Controlled HTTP/indexer, arithmetic, isolation, namesake and recovery tests | Ten-claim manual source audit, real ticker and full exchange window remain operator work |
| 90-second phone journey | Phone layout and new controls checked | A second person's timed run remains pending |

## 8. Execution and delivery — plan page 8

Code, migration, automated checks, CI configuration, reviewer instructions, public deployment configuration and covering draft are included. The remaining steps need the actual Mac/repository/hosting account and human evidence:

1. Apply the overlay and run the actual container suite/smoke/session acceptance.
2. Choose an independent unseeded ticker with a cold cache; fetch real originals and inspect citations.
3. Reconcile a live exchange window, verify current seed symbols and inspect ten original claim/page references.
4. Commit/push the public repository; inspect its actual CI run.
5. Create the Free hosted service, verify cold/warm phone access and try the flow with a second person.
6. Export/share genuine build sessions, remove secrets and verify external link access.
7. Fill the short covering note and submit by 15 November 2026.

Voice, native notifications, a graph view and automatic biographies were explicitly deferred by the original plan and remain deferred. Multi-year financial dashboards, universal OCR/table extraction, verified-account production hosting and backup operations are not represented as completed features.

See [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for the final evidence record and exact submission details.
