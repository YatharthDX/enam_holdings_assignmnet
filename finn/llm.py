"""Three explicit model transports with one response envelope and no fallback.

Only public passages reach a provider. Keys stay in server environment variables;
no request body, provider error body or credential is written to logs.
"""
import json
import errno
import os
import re
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

OPENAI_MODEL = "gpt-5.4-mini-2026-03-17"
GEMINI_MODEL = "gemini-3.8-flash"
OPENROUTER_MODEL = "openrouter/free"
OPENROUTER_API = "https://openrouter.ai/api/v1"
OPENROUTER_ENDPOINT = OPENROUTER_API + "/chat/completions"
OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/"
KEY_ENV = {"openrouter": "OPENROUTER_API_KEY", "gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}
LABEL = {"openrouter": "OpenRouter", "gemini": "Google Gemini", "openai": "OpenAI"}
DEFAULT_PROVIDER = "openrouter"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 240


class ProviderError(ValueError):
    def __init__(self, message, code="PROVIDER_ERROR", details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def network_error(exc, selected, generation=True):
    reason = exc.reason if isinstance(exc, URLError) else exc
    label = LABEL[selected]
    if isinstance(reason, ssl.SSLCertVerificationError):
        code, explanation = "TLS_CERTIFICATE_ERROR", "TLS certificate verification failed. Check the machine's trusted certificates or network proxy; keep certificate verification enabled."
    elif isinstance(reason, ssl.SSLError):
        code, explanation = "TLS_ERROR", "The secure connection failed during TLS negotiation."
    elif isinstance(reason, socket.gaierror):
        code, explanation = "DNS_ERROR", "The API hostname could not be resolved. Check Docker/network DNS connectivity."
    elif isinstance(reason, (TimeoutError, socket.timeout)) or (isinstance(reason, str) and "timed out" in reason.lower()):
        code, explanation = "NETWORK_TIMEOUT", "The connection or response exceeded its time limit. This alone does not establish whether Google/provider processing began."
    elif isinstance(reason, ConnectionRefusedError):
        code, explanation = "CONNECTION_REFUSED", "The network connection was refused."
    elif isinstance(reason, ConnectionResetError):
        code, explanation = "CONNECTION_RESET", "The network connection was reset."
    elif isinstance(reason, OSError) and reason.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        code, explanation = "NETWORK_UNREACHABLE", "The API network could not be reached."
    else:
        code, explanation = "NETWORK_ERROR", "The API connection failed. Run python -m finn.diagnose to check metadata access."
    note = (" The generation request may have used quota or incurred charges; inspect provider usage before retrying."
            if generation else " This was a read-only metadata request; no answer was generated.")
    # Never echo exception text: it may contain proxy credentials or request URLs.
    return ProviderError(label + " [" + code + "]: " + explanation + note, code)


def response_error(body, code, selected):
    """Expose only allowlisted codes and field names, never raw provider text."""
    label = LABEL[selected]
    statuses = {"INVALID_ARGUMENT", "FAILED_PRECONDITION", "PERMISSION_DENIED", "UNAUTHENTICATED",
                "RESOURCE_EXHAUSTED", "NOT_FOUND", "UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL"}
    known_reasons = {"API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_BLOCKED", "API_KEY_SERVICE_BLOCKED",
                     "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED", "SERVICE_DISABLED",
                     "BILLING_DISABLED", "RATE_LIMIT_EXCEEDED", "QUOTA_EXCEEDED", "CONSUMER_INVALID"}
    field_names = {"responseJsonSchema", "responseSchema", "responseFormat", "responseMimeType",
                   "maxOutputTokens", "thinkingConfig", "thinkingLevel", "thinkingBudget",
                   "systemInstruction", "contents"}
    if selected == "openrouter":
        field_names.update({"response_format", "json_schema", "max_tokens", "require_parameters"})
    status, reasons, fields = "", set(), set()
    try:
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if not isinstance(error, dict):
            error = {}
        status = error.get("status") if error.get("status") in statuses else ""
        messages = [str(error.get("message", ""))]
        for detail in error.get("details", []) if isinstance(error.get("details"), list) else []:
            if not isinstance(detail, dict): continue
            if detail.get("reason") in known_reasons:
                reasons.add(detail["reason"])
            for violation in detail.get("fieldViolations", []) if isinstance(detail.get("fieldViolations"), list) else []:
                if isinstance(violation, dict):
                    messages.append(str(violation.get("field", "")))
        # Reduce arbitrary text to fixed public parameter names; discard the text.
        mentioned = " ".join(messages).replace("_", "").lower()
        fields = {name for name in field_names if name.replace("_", "").lower() in mentioned}
    except Exception:
        pass
    messages = {
        400: "The provider rejected the request. The cause is not established without a more specific code.",
        401: "The provider rejected authentication. Check the selected server-side API key.",
        402: "The provider reports a credit or account limit. FINN's OpenRouter integration permits free models only; inspect the selected free model and account limits.",
        403: "The provider denied access. Check API/key restrictions and model permissions.",
        404: "The model or API resource is unavailable for this project.",
        429: "A rate or project quota limit was reached. Check quota or wait for reset; keep billing disabled for zero spend.",
        502: "The provider could not complete the request. Inspect service availability and retry explicitly if needed.",
        503: "The provider is temporarily unavailable. Retry explicitly after recovery.",
        504: "The provider reported a processing deadline. This differs from a local network timeout.",
    }
    http_status = code
    code = "HTTP_" + str(http_status)
    message = messages.get(http_status, "The provider returned an HTTP error.")
    if selected == "openrouter" and http_status == 404:
        message = "No matching free endpoint was available for this model and required JSON schema. Try later or explicitly select another schema-capable :free model."
    if reasons & {"API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_BLOCKED"}:
        code, message = "API_KEY_REJECTED", "The provider reports an invalid, expired or blocked key. Replace the local key from the provider's key page."
    elif any(reason.startswith("API_KEY_") for reason in reasons):
        code, message = "API_KEY_RESTRICTED", "The provider reports an API-key restriction. Check the key's API, application and IP restrictions."
    elif "SERVICE_DISABLED" in reasons:
        code, message = "API_SERVICE_DISABLED", "The provider reports that API access is disabled for this project. Check the project's API settings."
    elif "BILLING_DISABLED" in reasons or status == "FAILED_PRECONDITION":
        code, message = "PROJECT_PRECONDITION", "The project does not satisfy a provider prerequisite. Check free-tier/model/region eligibility; leave billing disabled when zero spend is required."
    elif status == "INVALID_ARGUMENT" and fields:
        code, message = "REQUEST_FORMAT_REJECTED", "The provider rejected request formatting or settings. Mentioned request parameters: " + ", ".join(sorted(fields)) + "."
    details = {"http_status": http_status, "status": status, "reasons": sorted(reasons), "fields": sorted(fields)}
    tags = ["HTTP " + str(http_status), *([status] if status else []), *sorted(reasons)]
    return ProviderError(label + " [" + "; ".join(tags) + "]: " + message
                         + " No automatic retry or provider fallback was made.", code, details)


def http_error(exc, selected):
    try:
        raw = exc.read(32769)
        body = json.loads(raw) if len(raw) <= 32768 else {}
    except Exception:
        body = {}
    return response_error(body, exc.code, selected)


def key(provider):
    return os.environ.get(KEY_ENV[provider], "").strip()


def enabled():
    from .runtime import interactive, public_demo
    flags = {"1", "true", "yes", "on"}
    if os.environ.get("FINN_ENABLE_LLM", "0").strip().lower() not in flags:
        return False
    if not public_demo():
        return True
    # Public generation is a separate opt-in, restricted to the free-only adapter.
    return (interactive() and
            os.environ.get("FINN_PUBLIC_LLM", "0").strip().lower() in flags and
            os.environ.get("FINN_LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower() == "openrouter")


def provider():
    selected = os.environ.get("FINN_LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
    if selected not in ("auto", *KEY_ENV):
        raise ProviderError("Set FINN_LLM_PROVIDER to openrouter, gemini, openai or auto.")
    if selected != "auto":
        return selected
    # Choose once at job creation. An error never changes that selection.
    return next((name for name in KEY_ENV if key(name)), DEFAULT_PROVIDER)


def valid_model(selected, value):
    if not isinstance(value, str):
        return False
    if selected == "openrouter":
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,149}:free", value)
                    or value == OPENROUTER_MODEL)
    return selected in KEY_ENV and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value))


def model(selected=None):
    selected = selected or provider()
    if selected == "gemini":
        value = os.environ.get("FINN_GEMINI_MODEL", "").strip() or GEMINI_MODEL
    elif selected == "openrouter":
        value = os.environ.get("FINN_OPENROUTER_MODEL", "").strip() or OPENROUTER_MODEL
    else:
        value = (os.environ.get("FINN_OPENAI_MODEL", "").strip()
                 or os.environ.get("FINN_RESEARCH_MODEL", "").strip() or OPENAI_MODEL)
    if not valid_model(selected, value):
        if selected == "openrouter":
            raise ProviderError("Use openrouter/free or an author/model:free ID in FINN_OPENROUTER_MODEL. Paid OpenRouter model IDs are disabled.")
        raise ProviderError("The selected model must be a model identifier, not a URL or path.")
    return value


def timeout_seconds():
    raw = os.environ.get("FINN_LLM_TIMEOUT_SECONDS", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        raise ProviderError("FINN_LLM_TIMEOUT_SECONDS must be an integer between 30 and 600.") from None
    if not 30 <= value <= 600:
        raise ProviderError("FINN_LLM_TIMEOUT_SECONDS must be between 30 and 600.")
    return value


def public_config():
    if not enabled():
        return {"enabled": False, "provider": None, "model": None, "configured": False,
                "fallback_enabled": False}
    selected = provider()
    return {"enabled": True, "provider": selected, "provider_label": LABEL[selected], "model": model(selected),
            "configured": bool(key(selected)), "key_env": KEY_ENV[selected],
            "selection": os.environ.get("FINN_LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER,
            "automatic_order": list(KEY_ENV), "fallback_enabled": False,
            "free_only": selected == "openrouter", "dynamic_model": selected == "openrouter" and model(selected) == OPENROUTER_MODEL,
            "timeout_seconds": timeout_seconds()}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(endpoint, payload, headers, selected, timeout=None):
    label = LABEL[selected]
    if timeout is None:
        timeout = timeout_seconds() if payload is not None else 15
    request = Request(endpoint, data=json.dumps(payload).encode() if payload is not None else None,
                      method="POST" if payload is not None else "GET", headers={
        "Content-Type": "application/json", "User-Agent": "FINN/0.6.2", **headers})
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ProviderError(label + " response exceeded FINN's size limit.")
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ProviderError(label + " returned an invalid response object.")
            if "error" in body:
                error = body["error"] if isinstance(body["error"], dict) else {}
                code = error.get("code")
                raise response_error(body, code if type(code) is int and 400 <= code <= 599 else 502, selected)
            return body
    except HTTPError as exc:
        raise http_error(exc, selected) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise network_error(exc, selected, generation=payload is not None) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ProviderError(label + " returned unreadable JSON. No automatic retry was made.") from None


def post_json(endpoint, payload, headers, selected):
    return request_json(endpoint, payload, headers, selected)


def get_json(endpoint, headers, selected, timeout=15):
    return request_json(endpoint, None, headers, selected, timeout=timeout)


def gemini_schema(value):
    """Gemini supports a JSON Schema subset; full constraints still run locally."""
    if isinstance(value, list):
        return [gemini_schema(item) for item in value]
    if isinstance(value, dict):
        return {k: gemini_schema(v) for k, v in value.items() if k not in ("minLength", "maxLength")}
    return value


def normalize_gemini(body):
    """Retain visible text and usage, excluding thought text and signatures."""
    candidates = body.get("candidates") or []
    blocked = bool((body.get("promptFeedback") or {}).get("blockReason"))
    candidate = candidates[0] if len(candidates) == 1 else {}
    finish = candidate.get("finishReason", "")
    refusal = blocked or finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII")
    text = "".join(part.get("text", "") for part in (candidate.get("content") or {}).get("parts", [])
                   if isinstance(part.get("text"), str) and not part.get("thought"))
    content = [{"type": "refusal"}] if refusal else [{"type": "output_text", "text": text}]
    raw_usage = body.get("usageMetadata") or {}
    usage = None
    prompt, visible, thoughts = (raw_usage.get("promptTokenCount"), raw_usage.get("candidatesTokenCount", 0),
                                 raw_usage.get("thoughtsTokenCount", 0))
    if all(type(n) is int and n >= 0 for n in (prompt, visible, thoughts)):
        usage = {"input_tokens": prompt, "output_tokens": visible + thoughts, "reasoning_tokens": thoughts,
                 "input_tokens_details": {"cached_tokens": raw_usage.get("cachedContentTokenCount", 0)}}
    return {"status": "completed" if refusal or finish == "STOP" else "incomplete",
            "output": [{"type": "message", "content": content}], "usage": usage,
            "id": str(body.get("responseId", ""))[:100], "_provider": "gemini",
            "_actual_model": str(body.get("modelVersion", ""))[:100]}


def normalize_openrouter(body):
    """Map visible chat output/usage to FINN's verifier; discard reasoning text."""
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderError("OpenRouter returned no single usable answer.", "INVALID_RESPONSE")
    choice = choices[0]
    if "error" in choice:
        error = choice["error"] if isinstance(choice["error"], dict) else {}
        code = error.get("code")
        raise response_error({"error": error}, code if type(code) is int and 400 <= code <= 599 else 502, "openrouter")
    message = choice.get("message")
    message = message if isinstance(message, dict) else {}
    finish = choice.get("finish_reason")
    refused = finish == "content_filter" or bool(message.get("refusal"))
    visible = message.get("content")
    if not isinstance(visible, str):
        visible = ""
    content = [{"type": "refusal"}] if refused else [{"type": "output_text", "text": visible}]
    raw_usage = body.get("usage")
    raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
    prompt, completion = raw_usage.get("prompt_tokens"), raw_usage.get("completion_tokens")
    usage = None
    if all(type(n) is int and n >= 0 for n in (prompt, completion)):
        def tokens(name, field):
            details = raw_usage.get(name)
            n = details.get(field) if isinstance(details, dict) else None
            return n if type(n) is int and n >= 0 else 0
        usage = {"input_tokens": prompt, "output_tokens": completion,
                 "input_tokens_details": {"cached_tokens": tokens("prompt_tokens_details", "cached_tokens")},
                 "reasoning_tokens": tokens("completion_tokens_details", "reasoning_tokens")}
        cost = raw_usage.get("cost")
        if type(cost) in (int, float) and 0 <= cost < float("inf"):
            usage["provider_reported_usd"] = cost
    actual = body.get("model")
    # Never persist arbitrary provider identifiers/error text as model metadata.
    if not isinstance(actual, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,249}", actual):
        actual = ""
    return {"status": "completed" if refused or finish == "stop" and not message.get("tool_calls") else "incomplete",
            "output": [{"type": "message", "content": content}], "usage": usage,
            "id": str(body.get("id", ""))[:100], "_provider": "openrouter", "_actual_model": actual}


def generate(selected, selected_model, instructions, evidence, schema):
    if not enabled():
        raise ProviderError("Optional AI synthesis is disabled. Set FINN_ENABLE_LLM=1 to enable it.")
    from .runtime import public_demo
    if public_demo() and selected != "openrouter":
        raise ProviderError("Public AI synthesis permits free-only OpenRouter requests only.")
    if selected not in KEY_ENV or not key(selected):
        raise ProviderError("Configure the selected provider's server-side API key before analysis.")
    # selected_model comes from validated configuration frozen when the job began.
    if not valid_model(selected, selected_model):
        raise ProviderError("Invalid model identifier.")
    text = json.dumps(evidence, ensure_ascii=False)
    if selected == "openrouter":
        payload = {"model": selected_model, "stream": False, "max_tokens": 8192,
                   "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": text}],
                   "response_format": {"type": "json_schema", "json_schema": {
                       "name": "finn_research", "strict": True, "schema": schema}},
                   "provider": {"require_parameters": True, "allow_fallbacks": False,
                                "max_price": {"prompt": 0, "completion": 0, "request": 0}}}
        body = post_json(OPENROUTER_ENDPOINT, payload, {"Authorization": "Bearer " + key(selected),
                                                     "X-OpenRouter-Title": "FINN"}, selected)
        return normalize_openrouter(body)
    if selected == "openai":
        payload = {"model": selected_model, "store": False, "max_output_tokens": 3500,
                   "instructions": instructions, "input": text,
                   "text": {"format": {"type": "json_schema", "name": "finn_research",
                                        "strict": True, "schema": schema}}}
        body = post_json(OPENAI_ENDPOINT, payload, {"Authorization": "Bearer " + key(selected)}, selected)
        body["_provider"] = selected
        body["_actual_model"] = str(body.get("model", ""))[:100]
        return body
    config = {"responseMimeType": "application/json", "responseJsonSchema": gemini_schema(schema),
              "maxOutputTokens": 8192}
    if selected_model.startswith("gemini-3"):
        config["thinkingConfig"] = {"thinkingLevel": "low"}
    elif selected_model.startswith("gemini-2.5"):
        config["thinkingConfig"] = {"thinkingBudget": 1024}
    payload = {"systemInstruction": {"parts": [{"text": instructions}]},
               "contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": config}
    body = post_json(GEMINI_ENDPOINT + selected_model + ":generateContent", payload,
                     {"x-goog-api-key": key(selected)}, selected)
    return normalize_gemini(body)
