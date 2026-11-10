"""Safe classification and metadata diagnostics; no inference or external calls."""
import json
import os
import socket
import ssl
import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from finn import diagnose, llm


def http_error(body, code=400):
    return HTTPError("https://api.example/never-echo?key=private-secret", code, "private-secret", {},
                     BytesIO(json.dumps(body).encode()))


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"FINN_ENABLE_LLM": "1", "FINN_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "private-secret-key",
                                     "FINN_GEMINI_MODEL": llm.GEMINI_MODEL})
        env.start()
        self.addCleanup(env.stop)

    def test_network_errors_are_distinct_and_do_not_echo_exception_text(self):
        errors = [(socket.gaierror(-2, "private-secret"), "DNS_ERROR"),
                  (TimeoutError("private-secret"), "NETWORK_TIMEOUT"),
                  (ssl.SSLCertVerificationError(1, "private-secret"), "TLS_CERTIFICATE_ERROR"),
                  (ConnectionRefusedError("private-secret"), "CONNECTION_REFUSED"),
                  (ConnectionResetError("private-secret"), "CONNECTION_RESET"),
                  (OSError("private-secret"), "NETWORK_ERROR")]
        for error, expected in errors:
            with self.subTest(expected=expected):
                result = llm.network_error(URLError(error), "gemini")
                self.assertEqual(result.code, expected)
                self.assertNotIn("private-secret", str(result))
                self.assertIn("may have used quota", str(result))
                metadata = llm.network_error(URLError(error), "gemini", generation=False)
                self.assertIn("no answer was generated", str(metadata))

    def test_key_error_keeps_only_allowed_reason_and_status(self):
        raw = {"error": {"status": "INVALID_ARGUMENT", "message": "private-secret-key and private document",
                         "details": [{"reason": "API_KEY_INVALID", "metadata": {"key": "private-secret-key"}},
                                     {"reason": "PRIVATE_SECRET_REASON"}]}}
        exc = llm.http_error(http_error(raw), "gemini")
        self.assertEqual(exc.code, "API_KEY_REJECTED")
        self.assertEqual(exc.details["reasons"], ["API_KEY_INVALID"])
        self.assertEqual(exc.details["status"], "INVALID_ARGUMENT")
        for private in ["private-secret", "private document", "PRIVATE_SECRET_REASON"]:
            self.assertNotIn(private, str(exc) + json.dumps(exc.details))

    def test_format_error_exposes_parameter_name_without_raw_field_path(self):
        raw = {"error": {"status": "INVALID_ARGUMENT", "message": "private-secret-key",
                         "details": [{"fieldViolations": [{
                             "field": "generation_config.response_json_schema.properties.private_secret_document",
                             "description": "private-secret-key"}]}]}}
        exc = llm.http_error(http_error(raw), "gemini")
        self.assertEqual(exc.code, "REQUEST_FORMAT_REJECTED")
        self.assertEqual(exc.details["fields"], ["responseJsonSchema"])
        self.assertNotIn("private_secret_document", str(exc) + json.dumps(exc.details))

    def test_project_preconditions_do_not_recommend_enabling_billing(self):
        exc = llm.http_error(http_error({"error": {"status": "FAILED_PRECONDITION",
                                                 "message": "private-secret-key"}}), "gemini")
        self.assertEqual(exc.code, "PROJECT_PRECONDITION")
        self.assertIn("leave billing disabled", str(exc))

    def test_unreadable_or_large_errors_never_echo_body(self):
        for body in [b"private-secret-key", b"private-secret-key" * 4000, b'{"error":{"status":{}}}']:
            exc = HTTPError("https://api.example", 400, "private-secret-key", {}, BytesIO(body))
            result = llm.http_error(exc, "gemini")
            self.assertEqual(result.details["http_status"], 400)
            self.assertNotIn("private-secret-key", str(result))

    def test_metadata_get_uses_headers_without_generating_or_echoing_key(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps({
            "name": "models/" + llm.GEMINI_MODEL, "supportedGenerationMethods": ["generateContent"]}).encode()
        with patch("finn.llm.build_opener", return_value=opener), patch("finn.llm.post_json") as generate:
            result = diagnose.check()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertIsNone(request.data)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)
        self.assertEqual(dict(request.header_items())["X-goog-api-key"], "private-secret-key")
        self.assertEqual(request.full_url, llm.GEMINI_ENDPOINT + llm.GEMINI_MODEL)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "METADATA_ACCESS_OK")
        self.assertFalse(result["generation_attempted"])
        self.assertFalse(generate.called)
        self.assertNotIn("private-secret-key", json.dumps(result))

    def test_metadata_failures_preserve_safe_network_category(self):
        opener = MagicMock()
        opener.open.side_effect = URLError(socket.gaierror(-2, "private-secret-key"))
        with patch("finn.llm.build_opener", return_value=opener):
            result = diagnose.check()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DNS_ERROR")
        self.assertFalse(result["generation_attempted"])
        self.assertEqual(opener.open.call_count, 1)
        self.assertNotIn("private-secret-key", json.dumps(result))

    def test_no_key_no_network_and_unexpected_metadata_is_rejected(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}), patch("finn.llm.get_json") as get:
            result = diagnose.check()
            self.assertEqual(result["code"], "KEY_NOT_CONFIGURED")
            self.assertFalse(get.called)
        result = diagnose.check(fetch=lambda *args, **kwargs: {"name": "models/different"})
        self.assertEqual(result["code"], "MODEL_METADATA_MISMATCH")

    def test_model_list_filters_generation_methods_and_flags_pagination(self):
        body = {"models": [{"name": "models/gemini-example", "supportedGenerationMethods": ["generateContent"]},
                           {"name": "models/embedding-example", "supportedGenerationMethods": ["embedContent"]},
                           {"name": "https://private.example", "supportedGenerationMethods": ["generateContent"]}],
                "nextPageToken": "opaque-private-token"}
        result = diagnose.check(list_models=True, fetch=lambda *args, **kwargs: body)
        self.assertEqual(result["models"], ["gemini-example"])
        self.assertTrue(result["more_pages"])
        self.assertNotIn("opaque-private-token", json.dumps(result))

    def test_openai_metadata_uses_bearer_and_does_not_generate(self):
        with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "openai-private", "FINN_OPENAI_MODEL": "test-model"}):
            def fetch(endpoint, headers, provider, timeout):
                self.assertEqual(endpoint, "https://api.openai.com/v1/models/test-model")
                self.assertEqual(headers["Authorization"], "Bearer openai-private")
                self.assertEqual(provider, "openai")
                return {"id": "test-model"}
            result = diagnose.check(fetch=fetch)
        self.assertTrue(result["ok"])
        self.assertNotIn("openai-private", json.dumps(result))
