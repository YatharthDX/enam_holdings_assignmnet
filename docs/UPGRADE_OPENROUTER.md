# M6.1: OpenRouter default provider

This cumulative overlay applies over integrated M6 or M5. It includes the M6 workflows and adds OpenRouter as the default optional provider, retaining Gemini/OpenAI. It contains no real API key, local database, private workspace or Git metadata. Runtime dependencies and Dockerfile are unchanged.

## 1. Unzip in the repository root

```bash
unzip -o "$HOME/Downloads/FINN_M6_1_OpenRouter_Default_Update.zip"
```

## 2. Update the existing .env

Change the old provider line, even if it currently says Gemini. Add your actual key only to your local ignored file:

```dotenv
FINN_PUBLIC_DEMO=0
FINN_ENABLE_LLM=1
FINN_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=YOUR_ACTUAL_OPENROUTER_KEY
FINN_OPENROUTER_MODEL=openrouter/free
```

Keep the rest of your settings. Existing Gemini/OpenAI keys may remain private; explicit OpenRouter selection does not use them. Do not paste your key into chat, source code, README or a commit. The ZIP deliberately does not overwrite `.env`.

`openrouter/free` dynamically picks an available compatible free model. You can pin an available `author/model:free` ID for repeatable evaluation. FINN rejects paid OpenRouter IDs, requires JSON-schema support, requests zero prompt/completion/request prices and disables provider fallback. Provider quota/capacity can still prevent a free request. Missing cost stays unknown; only a reported zero is displayed as zero.

Core workflows remain key-free. Set `FINN_ENABLE_LLM=0` at any time to disable optional synthesis. Public-demo mode always forces all model providers off, so local synthesis needs `FINN_PUBLIC_DEMO=0`.

## 3. Recreate the container with the cached image

```bash
export FINN_PORT=8090
docker compose -f compose.yaml -f compose.local.yaml up --no-build --pull never --force-recreate --wait
curl -fsS http://localhost:8090/health
curl -fsS http://localhost:8090/api/llm/status
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.diagnose
```

Expect release `0.6.1`; when configured as above, AI status shows `provider: openrouter`, `model: openrouter/free`, `configured: true`. These flags indicate configuration, not a successful inference.

The diagnostic makes a read-only authenticated key-metadata GET, not a generation. `KEY_ACCESS_OK` verifies that check only. `python -m finn.diagnose --models` lists bounded catalog IDs that are free and advertise schema support; it does not prove endpoint capacity or exact-schema acceptance.

The cached-image override needs your existing compatible `enamholdings-app:latest`. A fresh machine instead follows README's normal Docker build. Do not remove the data volume. Schema/result caches and workspace signing state remain intact.

## 4. Try the optional reading

Open http://localhost:8090, refresh the page, choose **Open my workspace** if needed, then:

1. Open Research and choose INFY or a ticker with indexed originals.
2. Expand **Optional AI synthesis**.
3. Confirm **OpenRouter · openrouter/free · Key configured**.
4. Select a lens and explicitly press **Analyze documents**.
5. Inspect the citations and original source pages. The saved result shows the served model, tokens and provider-reported cost when available.

Opening a section never generates. Later views reuse a completed result until its provider/model/lens/document identity changes. Paid fallback and automatic retries are disabled. An old Gemini result remains in its separate cache and is available if you explicitly select Gemini again.

If an error appears, inspect its safe code. Authentication 401 calls for checking the local key; 404 can mean no schema-capable free endpoint; 429 is a quota/rate limit; 503 is provider availability. Failures can count against free quotas. The main research tools remain usable throughout.

## 5. Verify and commit

```bash
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m unittest discover -s tests -v
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.smoke
docker compose -f compose.yaml -f compose.local.yaml exec -T app python -m finn.acceptance --sessions-only
git diff --check
git status --short
git add .env.example .gitignore .dockerignore .github/workflows/ci.yml compose.yaml render.yaml README.md REVIEWER_GUIDE.md docs finn tests
git diff --cached --stat
git commit -m "Add free-only OpenRouter as the default optional AI provider"
```

The suite passed 153 tests in the build environment with controlled provider responses. Browser UI and HTTP result/cache checks passed with a synthetic OpenRouter reply. No real model request or user key was used, and Docker was not available in the build environment; run the container checks above on your Mac.

If upgrading directly from M5, the M6 session/24-hour expiry behavior also applies. Read [UPGRADE_M6.md](UPGRADE_M6.md) and export useful private work before expiry.

## Official references checked 11 November 2026

- [Chat API](https://openrouter.ai/docs/api_reference/overview), [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection).
- [Free models and quotas](https://openrouter.ai/collections/free-models), [current-key metadata](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key), [model catalog](https://openrouter.ai/docs/api/api-reference/models/get-models).

Free `:free` variants currently need no credit purchase and have documented rate/day limits. Availability may change; FINN makes no uptime or unlimited-quota promise.

