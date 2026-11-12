# M6.4: faster document indexing

This cumulative overlay applies over M6.2 or M6.3. It includes the 800-page hosted fix, preserves local `.env`/data/Git history and leaves the existing Render environment settings effective. No model key is needed for document indexing.

## What changed

- A pinned native PDFium text reader replaces the slow Python page-text extraction loop. Each PDF runs in a disposable subprocess with no provider credentials in its environment. The prior pypdf reader remains for metadata/encryption validation and fixture creation.
- Find documents still checks the company link listing, but reuses exact-source indexes whose bytes were checked within six hours. It skips both their PDF downloads and text extraction. A new source URL is still fetched immediately.
- Refresh sources explicitly bypasses that recent-source cache. Automatic refreshes caused by relevant new/material filing revisions bypass it too. Same-URL changes can otherwise remain unseen until the six-hour check expires, so the UI states the cache policy.
- The status identifies the current document and physical PDF page. Browser polling updates progress without rerunning full-corpus research every four seconds. Searchable evidence updates when an entire document commits.
- A PDF worker is terminated after 180 seconds publicly or 300 seconds locally. A failed/timed-out replacement preserves the last searchable revision. Public limits remain one indexing job at a time, 20 MiB/file, 800 pages/file and 64 MiB of retained originals. Extracted text is bounded to eight million characters/file.

Existing indexes built by the older parser are rebuilt once when next checked. The parser version and original SHA-256 revision remain part of provenance; no source pages are silently truncated.

## Measured improvement

One 11,304,000-byte, 352-page [Infosys FY2024 annual report](https://www.infosys.com/investors/reports-filings/annual-report/annual/documents/infosys-ar-24.pdf) was tested on the same Linux scratch machine:

| Extraction path | Time | Text pages |
| --- | ---: | ---: |
| Previous pypdf page loop | 28.220 seconds | 352 |
| New native worker, including startup, metadata checks and byte-snapshot copy | 2.450 seconds | 352 |

That is approximately **11.5 times faster for this one file**. Both reached page 352. Download time was excluded. These are single-file/single-run measurements on the test machine, not Render latency guarantees or a claim that every extracted character is semantically verified. Source-page inspection remains part of the research workflow. Real upstream downloads, cold starts, complex/scanned PDFs and free-host resources still affect end-to-end time.

## Apply and rebuild locally

Run in your existing EnamHoldings repository:

```bash
unzip -o "$HOME/Downloads/FINN_M6_4_Fast_Indexing_Update.zip"
git diff --stat
export FINN_PORT=8090
docker compose -f compose.yaml up --build --wait
curl -fsS http://localhost:8090/health
```

**This release changes `requirements.txt` by adding `pypdfium2==5.15.2`. Rebuild the Docker image once.** The old M1/M6.3 image with `--no-build` does not contain the native dependency. `compose.local.yaml` may be used for later source-only work after building a compatible image.

Commit and push:

```bash
git add requirements.txt compose.local.yaml finn tests README.md REVIEWER_GUIDE.md docs
git commit -m "Speed up PDF indexing with native extraction and source caching"
git push
```

## Hosted verification

Render's ordinary Docker deployment installs the new pinned requirement. Wait for that deployment to finish. If auto-deploy is disabled, deploy the latest commit from the service dashboard. Keep the existing API key and public-demo flags; no new environment variable or paid service is required.

1. Check `/health` for version `0.6.4`.
2. Open your workspace and choose a ticker. Press Find documents once and observe document/page progress.
3. After completion, check a source passage and the cited PDF page.
4. Press Find documents again within six hours: the final status should report reused saved indexes, with no repeat PDF download for those sources.
5. Press Refresh sources once to check originals again deliberately. The normal acquisition quotas still apply.

The cache lives on the free host's temporary filesystem. Restart/redeploy/spin-down can erase it; the first subsequent request must acquire and index documents again. This release does not add permanent cloud storage, OCR, a paid server, automatic model calls or unlimited parallel downloads. An inaccessible upstream still produces an explicit error rather than being bypassed.

## Validation

The suite checks exact page references, 677-page public-mode ingestion, same-URL forced refreshes, cache expiry, no-repeat download/parse behavior, progress, actual stalled-worker termination, concurrent caller isolation, immutable original/text provenance, and preserving earlier evidence after failure. The suite also covers the existing core, privacy and optional-AI behavior with controlled provider responses. It does not spend a real model key or change the deployed service.
