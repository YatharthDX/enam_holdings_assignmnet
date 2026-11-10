"""Free-only OpenRouter transport, privacy, metadata and actual HTTP workflow."""
import json
import os
import tempfile
import time
import unittest
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request
from unittest.mock import MagicMock, patch

import test_http
from test_analysis import response_for
from finn import analysis, diagnose, llm


def router_reply(data, finish="stop"):
    visible = response_for(data)["output"][0]["content"][0]["text"]
    return {"id": "gen-fixture", "model": "fixture/source-reader", "choices": [{"finish_reason": finish,
            "message": {"role": "assistant", "content": visible, "reasoning": "private thought fixture",
                        "reasoning_details": [{"text": "private thought fixture"}]}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 400, "cost": 0,
                      "prompt_tokens_details": {"cached_tokens": 100},
                      "completion_tokens_details": {"reasoning_tokens": 200}}}


class OpenRouterTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": folder.name, "FINN_PUBLIC_DEMO": "0", "FINN_ENABLE_LLM": "1",
                                     "FINN_LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "router-fixture-not-real",
                                     "FINN_OPENROUTER_MODEL": "", "GEMINI_API_KEY": "", "OPENAI_API_KEY": ""})
        env.start(); self.addCleanup(env.stop)

    def test_default_and_auto_prefer_router_while_explicit_selection_is_respected(self):
        for value in (None, "", "auto", "openrouter"):
            with patch.dict(os.environ, {"GEMINI_API_KEY": "other-g", "OPENAI_API_KEY": "other-o"}):
                if value is None: os.environ.pop("FINN_LLM_PROVIDER", None)
                else: os.environ["FINN_LLM_PROVIDER"] = value
                config = llm.public_config()
                self.assertEqual(config["provider"], "openrouter")
                self.assertEqual(config["model"], "openrouter/free")
                self.assertTrue(config["free_only"]); self.assertTrue(config["dynamic_model"])
                self.assertFalse(config["fallback_enabled"])
                self.assertNotIn("fixture", json.dumps(config))
        with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "gemini"}):
            self.assertFalse(llm.public_config()["configured"])

    def test_paid_or_malformed_ids_are_rejected_without_any_request(self):
        for model in ("openai/gpt-4o", "openrouter/auto", "https://bad.example/free", "../secret:free",
                      "author/name:free?key=secret", "author/name:free/other", "author/name:free#fragment"):
            with self.subTest(model=model), patch.dict(os.environ, {"FINN_OPENROUTER_MODEL": model}), patch("finn.llm.post_json") as post:
                with self.assertRaises(llm.ProviderError): llm.public_config()
                with self.assertRaises(llm.ProviderError): llm.generate("openrouter", model, "unused", {}, {})
                post.assert_not_called()
        with patch.dict(os.environ, {"FINN_OPENROUTER_MODEL": "fixture/pinned-model:free"}):
            self.assertEqual(llm.model(), "fixture/pinned-model:free")
            self.assertFalse(llm.public_config()["dynamic_model"])

    def test_transport_sends_strict_free_only_schema_and_only_public_evidence(self):
        data, model, _ = analysis.context("INFY", "guidance")
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(router_reply(data)).encode()
        with patch("finn.llm.build_opener", return_value=opener):
            result = analysis.call_model(model, data, "guidance")
        request = opener.open.call_args.args[0]; payload = json.loads(request.data)
        self.assertEqual(request.full_url, llm.OPENROUTER_ENDPOINT)
        self.assertEqual(dict(request.header_items())["Authorization"], "Bearer router-fixture-not-real")
        self.assertNotIn("router-fixture", request.full_url)
        self.assertEqual(payload["model"], "openrouter/free")
        self.assertEqual(payload["provider"], {"require_parameters": True, "allow_fallbacks": False,
                                             "max_price": {"prompt": 0, "completion": 0, "request": 0}})
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(payload["response_format"]["json_schema"]["schema"], analysis.ResearchOutput.model_json_schema())
        self.assertEqual(payload["max_tokens"], 8192); self.assertFalse(payload["stream"])
        self.assertNotIn("tools", payload); self.assertNotIn("models", payload)
        for private in ("Mira Shah", "router-fixture-not-real", "workspace", "private note"):
            self.assertNotIn(private, json.dumps(payload))
        self.assertTrue(analysis.verify(result, data)["findings"])
        self.assertNotIn("private thought", json.dumps(result))

    def test_usage_preserves_actual_model_and_reported_zero_without_inventing_an_estimate(self):
        data = analysis.retrieve("INFY", "guidance")
        record = analysis.usage_record(llm.normalize_openrouter(router_reply(data)), "openrouter/free", 1.25)
        self.assertEqual(record["input_tokens"], 1200); self.assertEqual(record["output_tokens"], 400)
        self.assertEqual(record["reasoning_tokens"], 200); self.assertEqual(record["cached_input_tokens"], 100)
        self.assertEqual(record["provider_reported_usd"], 0); self.assertIsNone(record["estimated_usd"])
        self.assertEqual(record["actual_model"], "fixture/source-reader")
        for invalid in (None, True, -1, "0", float("nan"), float("inf")):
            body = router_reply(data); body["usage"]["cost"] = invalid
            record = analysis.usage_record(llm.normalize_openrouter(body), "openrouter/free", 1)
            self.assertIsNone(record["provider_reported_usd"])

    def test_refusal_truncation_tools_and_bad_json_never_publish(self):
        data = analysis.retrieve("INFY", "guidance")
        replies = [router_reply(data, finish) for finish in ("length", "content_filter", "tool_calls", "error")]
        refused = router_reply(data); refused["choices"][0]["message"]["refusal"] = "blocked"
        tools = router_reply(data); tools["choices"][0]["message"]["tool_calls"] = [{"type": "function"}]
        malformed = router_reply(data); malformed["choices"][0]["message"]["content"] = "```json\n{}\n```"
        for reply in [*replies, refused, tools, malformed]:
            with self.assertRaises(analysis.AnalysisError): analysis.verify(llm.normalize_openrouter(reply), data)
        for choices in ([], [{}, {}], [None]):
            with self.assertRaises(llm.ProviderError): llm.normalize_openrouter({"choices": choices})

    def test_shared_verifier_withholds_an_openrouter_finding_with_an_invented_number(self):
        data = analysis.retrieve("INFY", "guidance"); body = router_reply(data)
        output = json.loads(body["choices"][0]["message"]["content"])
        output["findings"][0]["text"] = "Revenue grew 99999%."
        body["choices"][0]["message"]["content"] = json.dumps(output)
        checked = analysis.verify(llm.normalize_openrouter(body), data)
        self.assertEqual(checked["withheld"], 1); self.assertFalse(checked["findings"])

    def test_http_errors_are_redacted_and_never_retry_or_switch_provider(self):
        for code in (401, 402, 404, 429, 502, 503):
            opener = MagicMock()
            opener.open.side_effect = HTTPError(llm.OPENROUTER_ENDPOINT, code, "private-secret", {},
                                               BytesIO(b'{"error":{"message":"private-secret and private document"}}'))
            with patch("finn.llm.build_opener", return_value=opener), patch.dict(os.environ, {"GEMINI_API_KEY": "unused-g", "OPENAI_API_KEY": "unused-o"}):
                with self.assertRaises(llm.ProviderError) as error:
                    llm.generate("openrouter", "openrouter/free", "unused", {}, {})
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(opener.open.call_args.args[0].full_url, llm.OPENROUTER_ENDPOINT)
            self.assertNotIn("private-secret", str(error.exception))
            self.assertEqual(error.exception.details["http_status"], code)

    def test_http_200_and_choice_error_envelopes_never_become_successes(self):
        for body in ({"error": {"code": 429, "message": "private-secret"}},
                     {"choices": [{"finish_reason": "error", "error": {"code": 503, "message": "private-secret"}}]}):
            opener = MagicMock(); opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(body).encode()
            with patch("finn.llm.build_opener", return_value=opener), self.assertRaises(llm.ProviderError) as error:
                llm.generate("openrouter", "openrouter/free", "unused", {}, {})
            self.assertEqual(opener.open.call_count, 1); self.assertNotIn("private-secret", str(error.exception))

    def test_read_only_key_diagnostic_hides_key_labels_and_account_identity(self):
        def fetch(endpoint, headers, provider, timeout):
            self.assertEqual(endpoint, llm.OPENROUTER_API + "/key")
            self.assertEqual(headers["Authorization"], "Bearer router-fixture-not-real")
            self.assertEqual(timeout, 15); self.assertEqual(provider, "openrouter")
            return {"data": {"label": "private-secret", "creator_user_id": "private-user", "is_free_tier": True}}
        with patch("finn.llm.post_json") as generate:
            result = diagnose.check(fetch=fetch)
        self.assertEqual(result["code"], "KEY_ACCESS_OK"); self.assertTrue(result["ok"])
        self.assertFalse(result["generation_attempted"]); generate.assert_not_called()
        for private in ("private-secret", "private-user", "router-fixture-not-real"):
            self.assertNotIn(private, json.dumps(result))

    def test_model_catalog_lists_only_free_schema_capable_ids(self):
        free = {"id": "fixture/reader:free", "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["structured_outputs"]}
        rows = [free, {**free, "id": "fixture/paid"}, {**free, "id": "fixture/fake-free:free", "pricing": {"prompt": "0", "completion": "1"}},
                {**free, "id": "fixture/no-schema:free", "supported_parameters": []}, {**free, "id": "fixture/unknown:free", "pricing": {}}]
        def fetch(endpoint, headers, provider, timeout):
            self.assertIn("/models?max_price=0&supported_parameters=structured_outputs", endpoint)
            return {"data": rows}
        result = diagnose.check(list_models=True, fetch=fetch)
        self.assertEqual(result["models"], ["fixture/reader:free"])
        self.assertFalse(result["generation_attempted"])

    def test_public_demo_and_disabled_feature_never_send_openrouter_requests(self):
        for interactive in ("0", "1"):
            with patch.dict(os.environ, {"FINN_PUBLIC_DEMO": "1", "FINN_INTERACTIVE_DEMO": interactive}), patch("finn.llm.post_json") as post:
                self.assertFalse(llm.public_config()["enabled"])
                with self.assertRaises(llm.ProviderError): llm.generate("openrouter", "openrouter/free", "unused", {}, {})
                post.assert_not_called()
        with patch.dict(os.environ, {"FINN_ENABLE_LLM": "0"}), patch("finn.llm.get_json") as get:
            self.assertEqual(diagnose.check()["code"], "OPTIONAL_AI_DISABLED"); get.assert_not_called()

    def test_job_freezes_router_and_reopening_uses_its_saved_result(self):
        _, work = analysis.begin("INFY", "guidance")
        with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "gemini"}), patch("finn.llm.post_json", return_value=router_reply(work[-1])) as post:
            analysis.run(*work)
        self.assertEqual(post.call_args.args[0], llm.OPENROUTER_ENDPOINT)
        job = analysis.status("INFY", "guidance")["job"]
        self.assertEqual(job["status"], "complete"); self.assertEqual(job["provider"], "openrouter")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), patch("finn.llm.post_json") as post:
            cached, work = analysis.begin("INFY", "guidance")
            self.assertTrue(cached["cached"]); self.assertIsNone(work); post.assert_not_called()


class OpenRouterHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_http.HttpTests.setUpClass.__func__(cls)

    def test_signed_http_analysis_routes_normalize_check_and_cache_router_output(self):
        def reply(endpoint, payload, headers, selected):
            self.assertEqual(endpoint, llm.OPENROUTER_ENDPOINT); self.assertEqual(selected, "openrouter")
            return router_reply(json.loads(payload["messages"][1]["content"]))
        with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "router-fixture-not-real",
                                     "FINN_OPENROUTER_MODEL": "openrouter/free"}), patch("finn.llm.post_json", side_effect=reply) as post:
            with self.client.open(self.base + "/api/llm/status") as response:
                self.assertEqual(json.load(response)["provider"], "openrouter")
            request = Request(self.base + "/api/research/INFY/analyze", data=b'{"lens":"guidance"}', method="POST", headers={"Content-Type": "application/json"})
            with self.client.open(request): pass
            deadline = time.monotonic() + 3
            while True:
                with self.client.open(self.base + "/api/research/INFY/analysis?lens=guidance") as response: result = json.load(response)
                if result["job"]["status"] != "running": break
                if time.monotonic() >= deadline: self.fail("Controlled OpenRouter HTTP job did not finish")
                time.sleep(.01)
            job = result["job"]
            self.assertEqual(job["status"], "complete"); self.assertTrue(job["result"]["findings"])
            self.assertEqual(job["usage"]["actual_model"], "fixture/source-reader")
            self.assertEqual(job["usage"]["provider_reported_usd"], 0)
            self.assertNotIn("router-fixture-not-real", json.dumps(result))
            with self.client.open(request) as response: self.assertTrue(json.load(response)["cached"])
            self.assertEqual(post.call_count, 1)
