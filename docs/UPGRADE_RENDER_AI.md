# Enable optional OpenRouter synthesis on Render (0.6.2)

This overlay applies to the M6.1 OpenRouter build. It preserves your local `.env`, data and Git history. The core research, monitoring and network workflows still work without a model key.

## 1. Apply and push

From your existing EnamHoldings repository on the Mac:

```bash
unzip -o "$HOME/Downloads/FINN_M6_2_Render_AI_Update.zip"
git diff --stat
git add finn tests compose.yaml render.yaml .env.example README.md REVIEWER_GUIDE.md docs
git commit -m "Enable bounded free OpenRouter synthesis in public demo"
git push
```

Wait for Render to deploy that commit. If automatic deployment is disabled, use **Manual Deploy → Deploy latest commit** on the service. The new `/health` version is `0.6.2`.

## 2. Configure the hosted service

In Render, open the existing **finn-demo** web service, then **Environment**. Add or update these environment variables:

| Key | Value |
| --- | --- |
| `FINN_PUBLIC_DEMO` | `1` |
| `FINN_INTERACTIVE_DEMO` | `1` |
| `FINN_TRUST_PROXY` | `1` |
| `FINN_AUTO_REFRESH` | `0` |
| `FINN_ENABLE_LLM` | `1` |
| `FINN_PUBLIC_LLM` | `1` |
| `FINN_LLM_PROVIDER` | `openrouter` |
| `FINN_OPENROUTER_MODEL` | `openrouter/free` |
| `OPENROUTER_API_KEY` | Paste your actual OpenRouter key directly into Render |

Select **Save and deploy**. No local Docker restart is needed for the hosted service. The Blueprint contains the non-secret defaults; add the actual key in Render, not in `render.yaml`, `.env.example`, GitHub, a browser script or a screenshot. Do not upload your whole local `.env`: its local deployment settings differ.

The old 0.6.1 code forces AI off publicly even when a key is present. Apply this update first. Keep `FINN_PUBLIC_DEMO=1` so the public source/network limits remain enabled. Public mode permits only the explicit `openrouter` selection; Gemini, OpenAI and `auto` remain local options.

## 3. Check the result

```bash
curl -fsS https://finn-demo-ojov.onrender.com/health
curl -fsS https://finn-demo-ojov.onrender.com/api/llm/status
```

Expected health fields: `version: "0.6.2"`, `public_demo: true`, `interactive_demo: true`, `llm_enabled: true`. Model status should show `provider: "openrouter"`, `model: "openrouter/free"`, `configured: true` and `free_only: true`. Neither endpoint returns the key.

Open the site on a phone using mobile data. Open your workspace, select INFY, open **Optional AI synthesis**, and press **Analyze documents**. You can first choose **Find documents** to review indexed originals. The first run makes one provider request; opening a saved reading again does not. Your Mac's saved results are separate and are not uploaded to Render.

## Public request limits

- One generation job at a time across the deployment.
- Three new starts per workspace per rolling hour, five globally per rolling hour, fifteen globally per rolling 24 hours.
- Completed readings are shared using only public evidence, and do not consume a new attempt.
- Failed provider attempts count too. There are no automatic retries or provider changes. Limits return HTTP 429 while core workflows and saved readings remain available.
- OpenRouter model IDs must be `openrouter/free` or end in `:free`; requests require zero-priced endpoints. Free availability and account quotas remain external.

The counters and saved readings use SQLite on the host. Render Free can reset them on a restart, redeploy or spin-down, so these are prototype limits rather than durable account-level abuse protection. Deleting a workspace does not reset the global allowance while that SQLite database remains. Only public passages go to the provider; keys and private workspace data remain server-side.

To turn synthesis off, set `FINN_ENABLE_LLM=0` in Render and save/deploy. If you want it to remain off across Blueprint updates, also change that non-secret default to `"0"` in `render.yaml`. Keep all credentials out of the repository.

Configuration reference: [Render environment variables and secrets](https://render.com/docs/configure-environment-variables).

Validation uses controlled provider responses; it does not consume your real key or prove live OpenRouter availability. After deployment, make one deliberate live analysis request to check your key and provider quota.
