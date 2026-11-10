# Apply M6 over integrated M5

Run from the existing EnamHoldings repository root. Keep your current data volume and `.env`.

## Apply and run

```bash
git status --short
unzip -o "$HOME/Downloads/FINN_M6_Complete_Workflows_Update.zip"
```

In the existing `.env`, set:

```dotenv
FINN_PUBLIC_DEMO=0
FINN_INTERACTIVE_DEMO=0
FINN_TRUST_PROXY=0
FINN_ENABLE_LLM=0
```

No new key is needed. Leave existing keys private. Leave `FINN_SESSION_SECRET` blank/absent for a persistent database-generated secret, or use your own random secret of at least 32 characters. Never commit it.

```bash
export FINN_PORT=8090
docker compose -f compose.yaml -f compose.local.yaml up --no-build --pull never --force-recreate --wait
curl -fsS http://localhost:8090/health
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m unittest discover -s tests -v
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.smoke
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.acceptance --sessions-only
```

The override uses the existing `enamholdings-app:latest` runtime and mounts updated source/tests. There are no dependency or Dockerfile changes. A fresh clone instead uses the normal build described in README.

## First visit and data migration

Open http://localhost:8090, refresh the page and choose **Open my workspace**. The first normal local workspace adopts M5 alert rules and existing alert history/read state once. Automated acceptance uses disposable sessions and does not consume this adoption.

Source documents, filing/price records and public model caches remain in the named volume. SQL schema additions happen on startup/access; no volume reset is needed.

Browser workspaces now expire after 24 hours. This includes adopted alert preferences/history and newly added private profiles, notes and reviewed facts. Export useful holdings/settings/profiles/notes/facts before expiry from Workspace. Alerts are not included in the export. The JSON snapshot is readable; only profiles/edges currently support re-import. Closing a tab does not delete its workspace, but clearing cookies loses access until expiry cleanup.

Do not run `down -v`. M6 is not intended to be rolled back to M5 against a database whose legacy alert state has already been adopted; use a separate disposable checkout/volume for older releases.

## Verify and commit

Try an unseen ticker, review a fact pair and inspect the evidence. Open two separate browser contexts to check private note isolation. Test on the phone.

```bash
git diff --check
git status --short
git add .env.example .gitignore .dockerignore .github/workflows/ci.yml compose.yaml render.yaml README.md REVIEWER_GUIDE.md docs finn tests
git diff --cached --stat
git commit -m "Complete source-first research and private demo workspaces"
```

Inspect staged files before committing. `.env`, local databases, exports and cached PDFs do not belong in the public repository. Push to your existing remote when ready and inspect the actual Actions run. No remote or branch is assumed by this guide.
