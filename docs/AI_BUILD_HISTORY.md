# AI build history

How I worked with AI tools to build YFINN.

## Tools

| Tool                             | Used for                                                                                                          |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| ChatGPT (browser)                | Breaking down the problem statement, and devising a high level development outline                                |
| Claude Code (VS Code extension)  | Planning, implementation, testing and verification in the repository                                              |
| Web search                       | Checking current NSE/BSE endpoints, PDF-parsing options and free LLM tiers before choosing                        |
| `ui-ux-pro-max` skill            | Generating a design-system recommendation, then auditing accessibility, contrast, touch targets and mobile layout |
| `/code-review`                   | A final review of the whole repository against the brief, which produced ten findings that were then fixed        |
| Manual checking on phone browser | Make it compatible for phone browser and prevent overflowing buttons                                              |

## Understanding and initial planning (ChatGPT)

After reading the problem statement on my own, I used ChatGPT to verify that I haven't missed anything.
Breaking the problem statements into part and then finally creating a high level plan.

> "Explain the whole task to me in detail. Include all the constraints, requirements and deliverables.
> Then create a high level structured plan considering all of the above findings. Break the problem statement into parts for better understanding and code design.
> Dont start coding as of now."

What came back: Suggested stack:
Frontend - HTML, CSS, JavaScript
Backend - FastAPI
Database - SQLite
Deployment - Docker
PDF processing - pypdf + PDFium
After reviewing the doc I moved to Claude Code for the development part.

My Call: As I was familiar with JavaScript and FastAPI, I agreed with the plan after some minor fixes.
I then asked it to build a demo prototype, not including all the detailed feature.

## Final planning and start of development

> "Read both PDFs (assignment details), then list every constraint, requirements and deliverables. Research the best tools for each step.
> Then finally draft a plan for our development, then compare it with my old plan, and highlight the gaps"

What came back: a requirement-by-requirement comparison table. The biggest gaps: the three Push examples the brief highlights were missing or manual; the promised-vs-delivered analysis needed human review for every figure; the hosted demo showed an empty live feed; and models were not used for bulk work at all.

My call: I reviewed the whole plan in detail, decided on certain design details and then modified some parts in the plan (small changes manually and large changes by claude).
For the LLM part I researched and chose to use OpenRouter's free API key. (before coming to this conclusion I also tried Gemini free API key, but it was not working properly)
Then I asked it to "work through the ranked list in order, and verify against real data at every step rather than fixtures alone"

This created our first working prototype. We then manually checked the website and dug deeper on certain aspects.

## For Real data on the hosted demo

> "NSE blocks cloud IPs. Ship a dated snapshot of real filings, prices and results, and anchor the brief's time windows to it until a live fetch succeeds."

Built `python -m finn.snapshot build`: 394 real NSE filings over 50 days, Yahoo daily bars and XBRL results for all 19 companies.
Course correction: Yahoo left the latest close empty; the settled price is now taken from quote metadata, but only when it is stamped after market close.

## Results without PDF parsing

> "Find a structured source for quarterly results so Revenue, EBITDA, PBT and PAT come out exact."

Found NSE's integrated-filing XBRL listing (from Q4 FY25) and the legacy listing for earlier quarters. Decisions I made: EBITDA is computed with a stated formula; lenders show net interest income instead of EBITDA; consolidated is preferred and scopes are never mixed.

## Management changes with context

> "When a CEO or CFO changes, read the company's own Regulation 30 profile, then tell me who in my network overlapped with the incoming person and how strong each link is."

Found a logic gap in the original matcher: it required the incoming person to already work at the company, so it could never match a genuinely new executive. Rebuilt it to extract the name, change type, role, employers with joining years and schools from the filing. On real filings this surfaced, for example, Anup Bagchi's ICICI career (since 1992, IIM Bangalore, IIT Kanpur) for HDFC Bank's CEO change. I iterated on the extraction rules several times against real PDFs: name variants, role words leaking into organisation names, and profiles split across two filings.

## Promised vs delivered, automated

> "Extract management's numeric guidance from the last eight transcripts with a cheap model and rules, verify every quote and number against the page, and let code score it against filed results."

Problems I caught along the way:

- Discovery was silently skipping recent transcripts, whose links point to BSE `.aspx` handlers, so LTTS was getting 2018–2020 calls.
- A free model returned `0.16` for "16%"; the literal-number verifier rejected it, as designed.
- The rule pass mistook past results ("grew 11.3%") for promises; it now requires forward-looking language.
- Constant-currency revenue guidance is shown but not scored against INR filings.

Result: Infosys FY26 guidance was raised three times and FY27's was lowered twice, and the operating-margin band was delivered. LTTS's "mid-16% EBIT margin" target is being met ahead of schedule.

## Taxonomy, network depth, search, concurrency

> "Map filings to the reference taxonomy using NSE's own subject. Give the network dated careers, link strength and competitor/supplier relevance. Replace keyword scanning with a real index."

Added a classifier over the full reference taxonomy, link strength with weakest-link path ranking, and SQLite FTS5 (BM25). Two bugs surfaced in testing and were fixed: a self-deadlock between two SQLite connections, and a race between readers and the importer; WAL mode fixed the latter.

## Model routing and the free tier

> "The AI reading fails on every call. I think we are not managing/limiting on tokens used in input and output."

Diagnosed instead of guessing: the free "thinking" models used the whole 8k-token output budget before answering. I measured four models and three parameter settings; only a larger output budget plus a pinned model worked. Bulk extraction is routed to a cheaper model setting; the optional synthesis uses the main model.

## Design pass with `ui-ux-pro-max`

> "Review the whole site and polish every page for mobile interface."

The skill recommended a fintech palette with IBM Plex type. I adopted the type and the dark palette, but kept a light default because this is a daily-use desk. A scripted audit then ran in both themes: text contrast, minimum text size, tap targets and horizontal overflow. Fixes included a full-reload bug on mobile hash navigation, and keeping each section's state and scroll position across updates.

## Review before submission

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

## Testing on a real phone

I tested the hosted demo on my own phone after each round of changes. Most fixes in the later stages came from bugs I found there rather than from automated checks:

| What I saw on the phone | Root cause | Fix |
| --- | --- | --- |
| Tapping an option jumped the page to the top and briefly showed "Opening the portfolio brief…" | The mobile browser treated in-app `#` links as full page navigations, and phones could keep stale scripts | The app handles its own link taps (no reload, back/forward still work); scripts and styles are served with `no-cache` |
| Choosing an option in one section reset the others | Each control's link carried only its own setting, and every re-render closed expanded panels | Choices in other sections are carried over; expanded panels stay as left |
| The date field overlapped the Apply button | A flexible row that phones sized badly (iOS date inputs have a fixed width) | A two-column grid where the field can shrink; the filter is collapsed by default |
| AI readings came back empty | Free "thinking" models used the whole output budget, and the quote check was too strict (next section) | Larger output budget, pinned model, tolerant quote matching |
| The "Find documents" button seemed to disappear | The panel was hidden in read-only mode or while a past date was active | The panel always shows, with the reason and a way back |

## Making the AI output usable

"Evidence gaps & limits" was often the only thing an AI reading showed. The model had produced findings, but YFINN discarded them because every quote had to match the document character for character. A curly quote, a dash or a word split across PDF lines rejected the whole finding, even when its other citations were correct.

> "Why is 'evidence gaps and limits' sometimes the only output? We can improve this."

What changed:
- quotes are matched after normalising typography, with a close-match fallback;
- the quote shown is always the document's own text, so provenance is unchanged;
- a finding survives if at least one citation verifies;
- invented numbers are still rejected.

Result on the same real LTTS request: 0 published findings (6 withheld) before, 5 verified findings (1 left out) after. The gaps became three specific "questions these documents leave open". A reading with no verified finding can now be run again instead of being cached.

## Robustness to real-world data

- **Moved attachments:** NSE moved filing attachments to a new host (`nseindia.in`). Its stricter host check was silently dropping these filings; it now accepts the new host, and lookalike domains are still rejected.
- **Unreachable issuer sites:** SRF's website serves an incomplete HTTPS certificate chain. Instead of bypassing verification, YFINN fetches the copy of the same transcript filed with NSE; SRF went from 2 of 9 to 10 of 10 documents.
- **Readable failures:** documents that still cannot be fetched are grouped into one line per reason, instead of the same error repeated seven times.

## Point-in-time correctness

The "view as of a past date" filter was hiding every discovered document, because discovered transcripts and annual reports had no publication date. Each document now gets a separate, deliberately late "available by" date: end of the call month plus 10 days for transcripts, and 30 September of the report year for annual reports. The real publication date is kept apart, so it can still be entered during fact review.

I caught a leak during testing: "Annual Report 2025-26" was briefly dated 2025, which would have shown a report before it existed. Fiscal-year ranges now use the end year.

## Product decisions

- Rebranded the product to YFINN.
- Folded the manual "statements to review" and "review a fact" tools into one optional section, once the automatic promised-vs-delivered panel worked.
- Made the brief open on the last 24 hours, as the assignment specifies.
- Kept the point-in-time filter but collapsed it, since it is valuable but used occasionally.
- Kept a light default theme with dark mode following the phone, rather than the dark-only style the design tool suggested.

## Mistakes the AI made that I caught

| AI output | How it was caught | Outcome |
| --- | --- | --- |
| "Strike off" (closing a subsidiary) classified as a labour strike | Reading the classified real filings | Rule reordered; covered by a test |
| A revenue share ("contributes 36% of revenue") read as growth guidance | Reviewing extracted LTTS guidance | Share-of-revenue figures are excluded |
| A free model returned 0.16 for "16%" | The literal-number verifier rejected it | Kept as designed; prompt asks for numbers exactly as written |
| "Overlapped" network links that ignored when the person had left an employer | Code review against Sanjay Banga's career (NTPC 1989, Reliance Energy 1996) | A person's stint ends when their next employer begins |
| A snapshot merge that duplicated every filing | The check showed 394 "new" filings | Replaced and remapped to unique IDs before shipping |
| PAT compared across quarters using two different measures | Code review; LTTS PAT appeared above PBT | One measure per card; discontinued operations explained |

## How I verified

- **Automated tests:** grew from 178 to 213, covering XBRL parsing, classification, appointee extraction, network ties, guidance verdicts, point-in-time dates and quote verification.
- **Real data:** checked against live sources, for example TCS Q2 FY27 revenue of ₹73,188 crore and an EBITDA margin of 25.7% computed from its XBRL filing.
- **Browser checks:** headless-browser checks at phone width in both light and dark themes, covering text contrast, minimum text size, tap targets, overflow, scroll and navigation.
- **Release checks:** the repository's own smoke and session-isolation checks, plus green CI before pushing.

## Cost and efficiency

- Total spend: ₹0. The default provider is OpenRouter's free tier with zero-price caps and no paid fallback.
- Each transcript is read by a model once: extraction is cached by document revision.
- Bulk extraction uses a cheaper model setting; only the optional synthesis uses the main model.
- Numbers come from exchange XBRL, so no model is spent on arithmetic or table parsing.
- The public demo caps model requests per workspace, per hour and per day.

## Privacy in AI use

- API keys stayed in a git-ignored `.env` and the hosting dashboard; they were never pasted into prompts and are never logged.
- Only public filing and transcript text is sent to a model. Holdings, contacts and notes never leave the workspace.
- The demo network is synthetic. Real use would rely on the investor's own data export with consent recorded per profile.
