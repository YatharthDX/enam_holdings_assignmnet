# Publish the phone demo

The main workspace runs locally with a persistent Docker volume. The public presentation uses only the dated historical source set and fictional profiles. Public mode provides no investor authentication or private storage: it blocks all HTTP writes, turns off automatic acquisition, and forces the model integration off. Use a fresh deployment with the supplied synthetic seeds.

## Check locally first

In your existing `.env`, keep full local controls:

```dotenv
FINN_PUBLIC_DEMO=0
FINN_ENABLE_LLM=0
```

```bash
export FINN_PORT=8090
docker compose -f compose.yaml -f compose.local.yaml up --no-build --pull never --force-recreate --wait
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m unittest discover -s tests -v
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.smoke
```

The cached-image override needs your previously built `enamholdings-app:latest` image. A new machine uses `cp .env.example .env` and `docker compose up --build --wait` instead. Do not overwrite an existing `.env` or remove its data volume to update.

## Render Free: a hosted link

1. Commit the update and push the full repository to GitHub. The required public repository URL is also a submission deliverable. Keep `.env` and `.finn/` excluded. The included Actions workflow will build/test the real container after the push; inspect that run before calling CI verified.
2. Sign in to Render. Create a **Blueprint** from that repository, using `render.yaml` in the root. The Blueprint requests a single Docker web service on the **Free** plan. Inspect the resources before creation: no paid plan, persistent disk, database or other paid service is included. Do not add a payment method for this zero-spend route. If Free is unavailable for your account without payment details, use the temporary option below.
3. Keep `FINN_PUBLIC_DEMO=1`, `FINN_ENABLE_LLM=0`, `FINN_AUTO_REFRESH=0` and `PORT=8080` as declared. Add no Gemini/OpenAI secret. Render builds the existing Dockerfile and checks `/health`.
4. When deployment succeeds, copy the actual `https://...onrender.com` URL. A public URL has not been created merely by adding the Blueprint file.
5. Open the URL on a phone. The default view must be the historical seven-day brief with **Public demo · Read only** visible. Inspect INFY guidance, an original source page, and a fictional contact. Also test People search and an empty research ticker.
6. Check `/health`: `version` must be `0.5.0`, `public_demo` true and `llm_enabled` false. Verify the running hosted API from the local container:

```bash
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.smoke \
  --base-url https://YOUR-SERVICE.onrender.com --expect-public-demo --timeout 60
```

Replace `YOUR-SERVICE` with the actual returned hostname. The smoke command makes GET requests only. It is not a substitute for testing the phone layout, live upstream access or a fresh unseen ticker in local mode.

Free services can spin down after 15 minutes of inactivity and take about a minute to wake. Local filesystem changes are lost on restart, redeployment or spin-down. The historical source JSON and fictional network ship in the image, so this demo does not depend on ephemeral user edits or PDF downloads. No keep-alive automation is configured.

Render applies free-hour, build and bandwidth limits. Its documentation says that without a payment method excess usage causes suspension/build limits rather than supplementary charges. Check the account's current plan and usage before deploying. Availability and account eligibility remain the provider's decision.

## Temporary HTTPS link from the Mac

This is useful for a same-day phone review while the Mac is running. It is temporary and does not replace a durable submission link.

Set `FINN_PUBLIC_DEMO=1` and `FINN_ENABLE_LLM=0` in `.env`, then recreate the container with the cached-image command above. Confirm `/health` reports public mode. Install `cloudflared` using [Cloudflare's platform instructions](https://developers.cloudflare.com/tunnel/downloads/). On macOS with Homebrew:

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8090
```

Open the generated HTTPS `trycloudflare.com` URL on the phone. Keep the terminal, Mac and Docker running. The URL changes on the next tunnel and stops working when the tunnel stops. Anyone with the link can access the public read-only presentation. Stop the tunnel before returning to local mode; set `FINN_PUBLIC_DEMO=0` and recreate the container to restore indexing and alert changes.

## Sources checked on 10 November 2026

- [Render Free limits and billing behavior](https://render.com/docs/free).
- [Render Docker deployment](https://render.com/docs/docker) and [Blueprint fields](https://render.com/docs/blueprint-spec).
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) and [downloads](https://developers.cloudflare.com/tunnel/downloads/).
- [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage): standard hosted runners in public repositories are free. Private-repository allowances differ; no private-repository spending is requested by this guide.
