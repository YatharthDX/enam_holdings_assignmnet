# Deploying FINN

## Render (free)

`render.yaml` defines one free Docker web service in public interactive mode: anonymous visitors see the snapshot brief and research; **Open my workspace** creates an isolated 24-hour workspace for alert rules, holdings and contacts.

1. Push the repository to GitHub (`.env`, SQLite files and exports are git-ignored).
2. In Render: **New → Blueprint** from the repo. Keep the Blueprint's environment values.
3. Optional free AI: add `OPENROUTER_API_KEY` in the Render dashboard (never in the repo). Public generation stays bounded (3 starts per workspace/hour, 5/hour and 15/day globally, one at a time). Transcript guidance in public mode uses the rule pass, so a key is not needed for the core flows.
4. After the deploy is healthy: `curl https://<service>.onrender.com/health` should report version `0.7.0`.
5. Keep it warm: the `Keep demo warm` workflow pings `/health` every 10 minutes. Set the repository variable `FINN_DEMO_URL` if your URL differs.

## Refreshing the shipped data

The hosted service usually cannot reach NSE, so refresh the snapshot locally and redeploy:

```bash
python -m finn.snapshot build --days 50                      # filings, prices, XBRL, appointees
python -m finn.snapshot build --days 50 --research LTTS,INFY  # choose which transcripts to read for guidance
git add finn/data/snapshot.json && git commit -m "Refresh data snapshot" && git push
```

With `FINN_ENABLE_LLM=1` and a key in `.env`, the build uses the model for guidance and appointee extraction and falls back to rules when the provider is unavailable or rate-limited. Without a key it uses rules only.

## Local

```bash
cp .env.example .env
docker compose up --build --wait     # http://localhost:8090, scheduled refresh on
```

On the same Wi-Fi a phone can open `http://<mac-ip>:8090`. For a temporary public HTTPS link: `cloudflared tunnel --url http://localhost:8090` with `FINN_PUBLIC_DEMO=1`, `FINN_INTERACTIVE_DEMO=1` and `FINN_TRUST_PROXY=1`.

## Checks

```bash
docker compose exec -T app python -m unittest discover -s tests
python -m finn.smoke --base-url https://<service>.onrender.com --expect-public-demo --timeout 60
python -m finn.acceptance --base-url https://<service>.onrender.com --sessions-only
```
