# Publish the phone demo

The provided `render.yaml` requests one Free Docker web service, with **public interactive synthetic workspaces** and no model keys, paid database, disk or scheduler. Local persistent Docker remains the best development workspace. Public free-host state is ephemeral.

## Check the integrated release locally

Follow [UPGRADE_M6.md](UPGRADE_M6.md). Keep local flags:

```dotenv
FINN_PUBLIC_DEMO=0
FINN_INTERACTIVE_DEMO=0
FINN_TRUST_PROXY=0
FINN_ENABLE_LLM=0
```

Confirm `/health` version `0.6.4`. Run the container suite, smoke and `python -m finn.acceptance --sessions-only`. A fresh machine uses the normal Docker build from README; the cached-image override requires an existing compatible image.

## Render Free

1. Commit/push the full repository to public GitHub. Exclude `.env`, private exports, SQLite files and cached originals. Inspect the actual Actions run; configuration alone is not a passing run.
2. In Render create a Blueprint from the repository/root `render.yaml`. Inspect the resource list: one Free web service, no paid add-ons. Keep the zero-spend route free of payment details; if the account cannot use Free without them, use the temporary option below.
3. Keep `PORT=8080`, `FINN_PUBLIC_DEMO=1`, `FINN_INTERACTIVE_DEMO=1`, `FINN_TRUST_PROXY=1`, `FINN_ENABLE_LLM=0`, `FINN_AUTO_REFRESH=0`. Do not add model keys. The Blueprint sets these values. Render terminates HTTPS at its edge; the trusted-proxy flag lets cookie/origin validation use its forwarded HTTPS scheme.
4. Wait for build/health success and copy the actual returned HTTPS URL. No deployment exists merely because the Blueprint is committed.
5. Open that URL in a fresh browser. The initial view is the dated seven-day historical brief. Inspect the guidance/source/contact path, then **Open my workspace**. Check private note and alert controls. Another browser must not see that private note.
6. Test generic document discovery if upstreams are accessible from the host. It is bounded to five starts/workspace/hour and 20 globally/hour. Manual live refresh is globally limited to once/15 minutes. Scheduled source acquisition remains disabled. Optional public synthesis is restricted to free-only OpenRouter, isolated workspaces and fixed global/per-workspace budgets. Configure its key in Render using [Render AI setup](UPGRADE_RENDER_AI.md); a key is not required for core workflows.
7. Check `/health`: version `0.6.4`, public true; LLM true with both opt-in flags, or false when switched off. Run against the actual origin:

```bash
python -m finn.smoke --base-url https://YOUR-SERVICE.onrender.com --expect-public-demo --timeout 60
python -m finn.acceptance --base-url https://YOUR-SERVICE.onrender.com --sessions-only
```

The smoke command uses GETs. Session acceptance creates/erases only its disposable test workspaces; no discovery or model generation is requested. A cold-ticker test must be requested separately and needs working upstream access.

To retain strict M5-style public read-only behavior, set `FINN_INTERACTIVE_DEMO=0`. All non-read HTTP methods are then rejected and session acceptance is intentionally unavailable.

Free services can sleep after 15 minutes of inactivity and take time to wake. Their local filesystem can disappear on restart, redeployment or spin-down. Export useful private demo work before expiry/restart; do not place real contacts on this public host. Historical JSON evidence and fictional seeds ship with the image and survive a fresh start. No keep-alive automation is included.

Provider eligibility/limits remain external. The Free plan has monthly service-hour/build/bandwidth limits; without a payment method the provider documents suspension/limits instead of supplementary charging. Recheck the actual account's resource plan before creation. No paid service is needed for this repository's core workflows.

## Temporary HTTPS from the Mac

Useful for same-day phone review while the Mac runs; it does not replace a stable submission URL.

Stop any previous tunnel first. Recreate the container with:

```dotenv
FINN_PUBLIC_DEMO=1
FINN_INTERACTIVE_DEMO=1
FINN_TRUST_PROXY=1
FINN_ENABLE_LLM=0
FINN_AUTO_REFRESH=0
```

Install `cloudflared` from [Cloudflare's official downloads](https://developers.cloudflare.com/tunnel/downloads/), or use Homebrew on macOS:

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8090
```

Open the generated HTTPS URL on the phone. Keep Docker, the terminal and Mac running. Anyone with the link can inspect the public evidence and create a bounded fictional workspace. The address changes on the next tunnel; closing it stops access. Verify its HTTPS cookie/origin behavior before relying on private demo controls.

Stop the tunnel before returning to local mode; reset public/interactive/proxy flags to 0 and recreate the container. This flag switch does not erase stored workspaces by itself; their normal expiry still applies. Use a separate Docker project/data volume for a completely fresh public demo if the local workspace contains real private data.

## Sources checked 10 November 2026

- [Render Free limits](https://render.com/docs/free), [Docker deployment](https://render.com/docs/docker), [Blueprint specification](https://render.com/docs/blueprint-spec).
- [Render web services and HTTPS termination](https://render.com/docs/web-services), [TLS](https://render.com/docs/tls).
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), [downloads](https://developers.cloudflare.com/tunnel/downloads/).
- [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage). Standard public-repository hosted runners are free; private-repository allowances differ.

No deployment, real upstream run or cloud-account action was performed merely by writing this guide.
