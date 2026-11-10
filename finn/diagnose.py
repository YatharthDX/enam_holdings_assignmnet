"""Read-only API diagnostics: python -m finn.diagnose [--models]."""
import argparse
import json
import re
import time
from decimal import Decimal, InvalidOperation

from . import llm


def check(list_models=False, fetch=None):
    started = time.monotonic()
    result = {"generation_attempted": False, "operation": "list_models" if list_models else "model_metadata"}
    try:
        info = llm.public_config()
        if not info.get("enabled"):
            result.update(enabled=False, ok=False, code="OPTIONAL_AI_DISABLED",
                          action="Core workflows need no model. Set FINN_ENABLE_LLM=1 only to diagnose optional AI.")
            return result
        result.update({k: info[k] for k in ("provider", "model", "configured")})
        if not info["configured"]:
            result.update(ok=False, code="KEY_NOT_CONFIGURED", action="Set " + info["key_env"] + " in .env and recreate the container.")
            return result
        provider, model = info["provider"], info["model"]
        if provider == "openrouter":
            headers = {"Authorization": "Bearer " + llm.key(provider)}
            endpoint = llm.OPENROUTER_API + ("/models?max_price=0&supported_parameters=structured_outputs&output_modalities=text" if list_models else "/key")
            body = (fetch or llm.get_json)(endpoint, headers, provider, timeout=15)
            if list_models:
                names = []
                records = body.get("data")
                for row in records if isinstance(records, list) else []:
                    if not isinstance(row, dict) or not llm.valid_model(provider, row.get("id")):
                        continue
                    pricing = row.get("pricing")
                    try:
                        free = isinstance(pricing, dict) and all(Decimal(str(pricing.get(k, "0" if k == "request" else "NaN"))) == 0
                                                                for k in ("prompt", "completion", "request"))
                    except (InvalidOperation, ValueError):
                        free = False
                    parameters = row.get("supported_parameters")
                    if free and isinstance(parameters, list) and "structured_outputs" in parameters:
                        names.append(row["id"])
                result.update(ok=True, code="MODEL_CATALOG_ACCESS_OK", models=sorted(set(names))[:100], more_pages=False)
            else:
                if not isinstance(body.get("data"), dict):
                    raise llm.ProviderError("OpenRouter returned invalid key metadata.", "KEY_METADATA_INVALID")
                result.update(ok=True, code="KEY_ACCESS_OK", operation="key_metadata")
            result["note"] = "Read-only key/catalog access does not prove generation quota, schema acceptance or free-model availability. No answer was generated."
            return result
        if provider == "gemini":
            endpoint = llm.GEMINI_ENDPOINT.rstrip("/") + ("?pageSize=100" if list_models else "/" + model)
            headers = {"x-goog-api-key": llm.key(provider)}
        else:
            endpoint = "https://api.openai.com/v1/models" + ("" if list_models else "/" + model)
            headers = {"Authorization": "Bearer " + llm.key(provider)}
        body = (fetch or llm.get_json)(endpoint, headers, provider, timeout=15)
        if list_models:
            records = body.get("models" if provider == "gemini" else "data", [])
            names = []
            for row in records if isinstance(records, list) else []:
                if not isinstance(row, dict): continue
                if provider == "gemini" and "generateContent" not in row.get("supportedGenerationMethods", []):
                    continue
                name = str(row.get("name" if provider == "gemini" else "id", "")).removeprefix("models/")
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", name): names.append(name)
            result.update(ok=True, models=sorted(set(names))[:100], more_pages=bool(body.get("nextPageToken") or body.get("has_more")))
        else:
            actual = body.get("name" if provider == "gemini" else "id", "")
            expected = "models/" + model if provider == "gemini" else model
            if actual != expected:
                raise llm.ProviderError("The metadata response did not identify the requested model.", "MODEL_METADATA_MISMATCH")
            supported = provider != "gemini" or "generateContent" in body.get("supportedGenerationMethods", [])
            result.update(ok=bool(supported), code="METADATA_ACCESS_OK" if supported else "GENERATION_METHOD_UNAVAILABLE")
        result["note"] = "Metadata access does not prove generation quota, free-tier eligibility, schema acceptance or inference availability. No answer was generated."
    except llm.ProviderError as exc:
        result.update(ok=False, code=exc.code, message=str(exc), **exc.details)
    except Exception:
        # Avoid a traceback that might echo a malformed URL or credential.
        result.update(ok=False, code="DIAGNOSTIC_ERROR", message="The diagnostic could not complete; raw exception text was withheld.")
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", action="store_true", help="List bounded model metadata; OpenRouter lists schema-capable free IDs. Never generates.")
    args = parser.parse_args()
    result = check(list_models=args.models)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
