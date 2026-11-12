# M6.3: fix hosted annual-report page limits

This overlay applies over M6.2. It preserves `.env`, Render's API-key settings, stored data and Git history. No dependency, Dockerfile or environment-variable changes are required.

## Cause

M6.2 allowed 800 PDF pages locally but only 600 in public mode. A report with 677 indexed text pages necessarily exceeds the public cap, even though the local importer accepts it. Discovery had already fetched the PDF before hitting that validation check. The old error combined encryption and page-count failures, so it did not identify which check had failed.

M6.3 uses the same 800-page limit in both modes. It gives separate messages for encrypted, empty, oversized and over-page-limit PDFs. The page-limit message includes the actual PDF page count. Complete accepted documents are indexed; this fix does not silently truncate a report to its first 600 pages.

Public downloads remain limited to 20 MiB, retained originals to 64 MiB, and document discovery to one concurrent job. Workspace/source quotas, optional free-only OpenRouter routing and public-AI budgets are unchanged. Local PDF downloads retain their 50 MiB limit.

## Apply and deploy

Run from the existing EnamHoldings repository on the Mac:

```bash
unzip -o "$HOME/Downloads/FINN_M6_3_Hosted_PDF_Fix.zip"
git diff --stat
git add finn tests README.md REVIEWER_GUIDE.md docs
git commit -m "Align hosted PDF page limits and clarify indexing errors"
git push
```

Wait for Render to deploy that commit. If automatic deployment is disabled, deploy the latest commit from the service dashboard. Leave `FINN_PUBLIC_DEMO=1`; do not switch the internet-facing service into local mode.

```bash
curl -fsS https://finn-demo-ojov.onrender.com/health
```

Expect `version: "0.6.3"` and `public_demo: true`. Existing optional-AI settings remain effective.

Open your workspace, research **HDFCBANK**, and press **Find documents** once. Let the job finish. This starts a new discovery attempt, replacing the old failed job status. Accepted reports should show indexed originals and source-linked passages. If the same 600-page error appears, confirm the deployment version and deployed commit first.

## Verification and limits

The regression uses generated, text-searchable 677-page PDFs in public mode and checks evidence on the last page. A discovery-to-search test exercises that flow too. Tests verify that an 801-page replacement remains rejected in both modes without overwriting previous evidence, encryption has its own error, and the public file-size cap remains enforced.

This corrects the validation mismatch. Large PDFs can still take time to parse on the free host; this patch does not add a faster parser, page progress, a parser deadline, or persistent cloud storage. Report sizes above 800 pages or 20 MiB still produce an explicit hosted error. A live HDFCBANK rerun is needed after deployment; generating this patch does not change the deployed service.
