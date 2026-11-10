# Requirement coverage and final checks

The brief asks for a focused working prototype, not every research view. This file distinguishes implemented functionality from execution evidence that still needs to be collected. It does not assert that a URL has been deployed or a local checkout committed.

## Coverage against the challenge

| Requirement | Current implementation | Status / remaining evidence |
| --- | --- | --- |
| Mobile-first prototype | Brief, Research, People, shared source/person sheets and phone navigation | Implemented; verify the actual public URL on a second phone |
| 15–20 portfolio holdings and 3–5 ad-hoc names | 16 holdings; LTTS, SRF, HAVELLS research examples | Implemented; current source availability must be checked locally |
| Working Push | Prioritized digest, 24h/7d/custom windows, routine group, configurable filing/price/volume alerts | Implemented and fixture-tested; reconcile one live window with the exchange |
| Working Pull with primary evidence | Generic original-PDF discovery/indexing/search; dated snapshots; sourced INFY guidance comparison | Implemented; run an unseeded ticker against actual upstreams from an empty document cache |
| Generalises beyond demo names | Discovery verifies the requested NSE symbol; generic PDF import and source/page search | Engine implemented; live independent-ticker acceptance remains pending |
| Network integrated into Push/Pull and directly queryable | 12 fictional profiles, relevance reasons, explicit direct/two-hop paths | Implemented; no real profile scraping or contact import |
| Four inputs | EOD prices, exchange announcements, originals, synthetic profiles | Adapters/seeds implemented; live connectivity is not established by fixture tests |
| Primary sources only for Pull | Issuer originals and labelled historical excerpts | Implemented; no secondary research imported as evidence |
| Architecture, privacy, models/agents, cloud explanation | `ARCHITECTURE.md` | Written; current controls and future private-workspace design are distinguished |
| Phone-accessible delivery | Render Free Blueprint and temporary-tunnel instructions | Configuration prepared; actual public URL still pending |
| Public GitHub repository | Existing operator-maintained repository workflow | Operator must commit/push and verify public access; URL not supplied here |
| Genuine AI build history | Actual ChatGPT/coding sessions from the build | Operator must export/share, redact credentials and verify reviewer access |
| Short covering email | `SUBMISSION_EMAIL.md` | Drafted; fill links and verification details after final checks |

## Deliberate omissions

The eight Pull views and example Push enrichments are a menu in the brief. Broad financial dashboards, automatic quarterly table extraction, OCR, voice, native push notifications, autonomous agents and executive biography/name resolution are not claimed. The deterministic financial comparison is the curated INFY case. Generic structured guidance extraction/comparison, authentication, private multi-user workspaces, consent/deletion automation and durable hosted live ingestion are future work.

Public demo mode is read-only and uses historical sources; fresh document lookup, live refresh and alert editing are available in local mode. Do not present the hosted replay as a current live feed or production-private workspace.

## Final operator acceptance

Record the commit SHA, date, observed result and a short issue note for each item. Do not tick a check because its instructions exist.

- [ ] Apply the ZIP, set `FINN_PUBLIC_DEMO=0` / `FINN_ENABLE_LLM=0`, recreate Docker and confirm release `0.5.0`.
- [ ] Run `python -m unittest discover -s tests -v` in the container. Save the actual output.
- [ ] Run `python -m finn.smoke` against that running service. The command makes GET requests only.
- [ ] On a clean checkout with a new named data volume, build using README instructions and inspect all three core workflows. Preserve the original checkout/data; do not use `down -v` there.
- [ ] Refresh live sources locally. Review NSE coverage and completed-session dates. Compare one chosen filing window with the exchange website or an official CSV import; record denied/partial sources honestly.
- [ ] Choose a document-rich NSE ticker outside the 19 demo names. Confirm it is not already indexed, then Find documents, inspect the original annual report/transcripts, and search an actual phrase from a PDF. Inspect its page link. This is an indexing/search acceptance, not proof of automatic financial interpretation.
- [ ] Inspect ten material quote/page references in issuer originals, including all four INFY forecasts and its outcome. Check 4.2% versus original 1–3% (+1.2 pp over the upper bound) and final 4.5–5% (−0.3 pp below the lower bound).
- [ ] Try a quiet window, a ticker without sources and a blocked upstream. Existing evidence must remain available and incomplete coverage must be explicit.
- [ ] Deploy the Render Free configuration. Confirm health `public_demo:true`, `llm_enabled:false`; no paid resources or model keys. Run the hosted smoke check with `--expect-public-demo`.
- [ ] On a phone using mobile data, open the hosted link from a fresh browser. Follow filing → evidence → relevant contact and ask another person to try it. Check a cold start as well as a warm visit.
- [ ] Inspect the public GitHub Actions run. Its Docker build, suite, local smoke and public-mode smoke must actually pass.
- [ ] Verify GitHub, demo and AI-session links from an external/private browser. Remove secrets and real contact data from repository/history/session exports.
- [ ] Fill the covering note, recheck the exact submission address/subject against the assignment, and send before the deadline. No email is sent by this repository.

## Build verification evidence

The M5 source suite passes 101 Python tests in the build environment, including actual loopback HTTP entry points with controlled upstream/model responses. Browser module syntax was checked. No live model inference was run here. Docker and Render are not available as authenticated deployment targets in the build environment, so their actual run/deployment must not be marked complete until the operator or GitHub CI supplies that result.

## Submission from the brief

- Deadline: **15 November 2026**; the brief specifies a date without a clock time. Aim to send early.
- To: **assessment@enam.com**
- Subject: **IIT Kanpur – Founding AI Engineer - 2027**
- Include: phone-accessible prototype, public GitHub repository, genuine AI build-history links/attachments, short covering writeup.
