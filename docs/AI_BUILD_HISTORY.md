# AI build history

How I worked with AI tools to build YFINN. Requests below are condensed versions of my prompts; routine requests (git commands, small copy changes, local-hosting help) are left out.

## Tools

| Tool                                      | Used for                                                                                                          |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Claude Code (VS Code extension)           | Planning, implementation, testing and verification in the repository                                              |
| Web search (inside Claude Code)           | Checking current NSE/BSE endpoints, PDF-parsing options and free LLM tiers before choosing                        |
| `ui-ux-pro-max` skill                     | Generating a design-system recommendation, then auditing accessibility, contrast, touch targets and mobile layout |
| `/code-review`                            | A final review of the whole repository against the brief, which produced ten findings that were then fixed        |
| Headless Chrome (driven from the session) | Phone-width screenshots and scripted checks: contrast, overflow, scroll and navigation behaviour                  |

## Earlier sessions (initial prototype)

The first prototype (Push digest, document indexing, fictional network, workspaces, optional AI synthesis) was built in earlier sessions before the work below.

## Session: gap analysis to v0.8

### 1. Audit the build against the brief before writing code

> "Read both PDFs and list every constraint and deliverable. Research the best tools for each pipeline step, write the plan you would build, then compare it with my repository and rank the gaps."

What came back: a requirement-by-requirement comparison table. The biggest gaps: the three Push examples the brief highlights were missing or manual; the promised-vs-delivered analysis needed human review for every figure; the hosted demo showed an empty live feed; and models were not used for bulk work at all.

My call: work through the ranked list in order, and verify against real data at every step rather than fixtures alone.

### 2. Real data on the hosted demo

> "NSE blocks cloud IPs. Ship a dated snapshot of real filings, prices and results, and anchor the brief's time windows to it until a live fetch succeeds."

Built `python -m finn.snapshot build`: 394 real NSE filings over 50 days, Yahoo daily bars and XBRL results for all 19 companies.
Course correction: Yahoo left the latest close empty; the settled price is now taken from quote metadata, but only when it is stamped after market close.

### 3. Results without PDF parsing

> "Find a structured source for quarterly results so Revenue, EBITDA, PBT and PAT come out exact."

Found NSE's integrated-filing XBRL listing (from Q4 FY25) and the legacy listing for earlier quarters. Decisions I made: EBITDA is computed with a stated formula; lenders show net interest income instead of EBITDA; consolidated is preferred and scopes are never mixed.

### 4. Management changes with context

> "When a CEO or CFO changes, read the company's own Regulation 30 profile, then tell me who in my network overlapped with the incoming person and how strong each link is."

Found a logic gap in the original matcher: it required the incoming person to already work at the company, so it could never match a genuinely new executive. Rebuilt it to extract the name, change type, role, employers with joining years and schools from the filing. On real filings this surfaced, for example, Anup Bagchi's ICICI career (since 1992, IIM Bangalore, IIT Kanpur) for HDFC Bank's CEO change. I iterated on the extraction rules several times against real PDFs: name variants, role words leaking into organisation names, and profiles split across two filings.

### 5. Promised vs delivered, automated

> "Extract management's numeric guidance from the last eight transcripts with a cheap model and rules, verify every quote and number against the page, and let code score it against filed results."

Problems I caught along the way:

- Discovery was silently skipping recent transcripts, whose links point to BSE `.aspx` handlers, so LTTS was getting 2018–2020 calls.
- A free model returned `0.16` for "16%"; the literal-number verifier rejected it, as designed.
- The rule pass mistook past results ("grew 11.3%") for promises; it now requires forward-looking language.
- Constant-currency revenue guidance is shown but not scored against INR filings.

Result: Infosys FY26 guidance was raised three times and FY27's was lowered twice, and the operating-margin band was delivered. LTTS's "mid-16% EBIT margin" target is being met ahead of schedule.

### 6. Taxonomy, network depth, search, concurrency

> "Map filings to the reference taxonomy using NSE's own subject. Give the network dated careers, link strength and competitor/supplier relevance. Replace keyword scanning with a real index."

Added a classifier over the full reference taxonomy, link strength with weakest-link path ranking, and SQLite FTS5 (BM25). Two bugs surfaced in testing and were fixed: a self-deadlock between two SQLite connections, and a race between readers and the importer; WAL mode fixed the latter.

### 7. Model routing and the free tier

> "The AI reading fails on every call. Is it the free quota?"

Diagnosed instead of guessing: the free "thinking" models used the whole 8k-token output budget before answering. I measured four models and three parameter settings; only a larger output budget plus a pinned model worked. Bulk extraction is routed to a cheaper model setting; the optional synthesis uses the main model.

### 8. Design pass with `ui-ux-pro-max`

> "Review the whole site and polish every page for mobile."

The skill recommended a fintech palette with IBM Plex type. I adopted the type and the dark palette, but kept a light default because this is a daily-use desk. A scripted audit then ran in both themes: text contrast, minimum text size, tap targets and horizontal overflow. Fixes included a full-reload bug on mobile hash navigation, and keeping each section's state and scroll position across updates.

### 9. Review before submission

> "Run `/code-review` on the whole assignment. Have we met every constraint, and are all deliverables ready?"

Ten findings were fixed. Among them:

- alerts are now measured from the data's own time;
- a partial refresh can no longer move the shared demo window;
- live guidance merges with, rather than replaces, the shipped readings;
- estimated "available by" dates are kept apart from real publication dates;
- tenure overlap stops when the person's next employer begins;
- PAT uses one measure across quarters, with discontinued operations explained.

## Decisions I overrode or kept deliberately

- Numbers are computed in code. Models only read prose, and every string they return must exist in the source.
- No paid fallback and no bypassing TLS verification. One issuer's site has a broken certificate chain; its documents are reported as failed rather than fetched insecurely.
- The point-in-time ("view as of a past date") filter was kept but collapsed, since it is valuable for avoiding hindsight but rarely needed.
- The dark-only style the design tool suggested was not adopted as the default.
