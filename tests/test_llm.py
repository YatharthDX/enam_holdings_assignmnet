"""Provider selection and real HTTP adapters exercised with controlled responses."""
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from finn import analysis, live_store, llm
from test_analysis import response_for


def gemini_reply(data, finish="STOP"):
    reply = response_for(data)
    text = reply["output"][0]["content"][0]["text"]
    return {"candidates": [{"finishReason": finish, "content": {"parts": [
        {"thought": True, "text": "Internal thought text must never be persisted."}, {"text": text}]}}],
        "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 160,
                          "thoughtsTokenCount": 300, "cachedContentTokenCount": 100},
        "modelVersion": llm.GEMINI_MODEL, "responseId": "gemini_fixture"}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"FINN_ENABLE_LLM": "1", "FINN_DATA_DIR": folder.name, "GEMINI_API_KEY": "", "OPENAI_API_KEY": "",
                         "FINN_LLM_PROVIDER": "auto", "FINN_GEMINI_MODEL": "", "FINN_OPENAI_MODEL": "",
                         "FINN_RESEARCH_MODEL": ""})
        env.start()
        self.addCleanup(env.stop)

    def test_no_key_defaults_to_unconfigured_gemini_without_network(self):
        with patch("finn.llm.post_json") as post:
            info = llm.public_config()
            self.assertFalse(info["configured"])
            self.assertEqual(info["provider"], "gemini")
            self.assertEqual(info["model"], llm.GEMINI_MODEL)
            self.assertFalse(post.called)
        with self.assertRaisesRegex(analysis.AnalysisError, "GEMINI_API_KEY"):
            analysis.begin("INFY", "guidance")

    def test_auto_with_each_key_and_both_keys(self):
        for keys, expected in [({"GEMINI_API_KEY": "gemini-fixture"}, "gemini"),
                               ({"OPENAI_API_KEY": "openai-fixture"}, "openai"),
                               ({"GEMINI_API_KEY": "gemini-fixture", "OPENAI_API_KEY": "openai-fixture"}, "gemini")]:
            with patch.dict(os.environ, keys):
                info = llm.public_config()
                self.assertEqual(info["provider"], expected)
                self.assertTrue(info["configured"])
                self.assertFalse(info["fallback_enabled"])
                self.assertNotIn("fixture", json.dumps(info))

    def test_explicit_provider_never_uses_other_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fixture-g", "FINN_LLM_PROVIDER": "openai"}):
            self.assertFalse(llm.public_config()["configured"])
            with self.assertRaisesRegex(analysis.AnalysisError, "OPENAI_API_KEY"):
                analysis.begin("INFY", "guidance")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-o", "FINN_LLM_PROVIDER": "gemini"}):
            self.assertFalse(llm.public_config()["configured"])

    def test_invalid_provider_and_model_are_rejected_before_network(self):
        with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "other"}):
            with self.assertRaises(llm.ProviderError): llm.public_config()
        with patch.dict(os.environ, {"FINN_GEMINI_MODEL": "https://other.example/steal"}):
            with self.assertRaises(llm.ProviderError): llm.public_config()

    def test_model_overrides_are_independent_and_legacy_is_openai_only(self):
        with patch.dict(os.environ, {"FINN_RESEARCH_MODEL": "legacy-openai-model"}):
            self.assertEqual(llm.model("openai"), "legacy-openai-model")
            self.assertEqual(llm.model("gemini"), llm.GEMINI_MODEL)
        with patch.dict(os.environ, {"FINN_OPENAI_MODEL": "explicit-openai", "FINN_RESEARCH_MODEL": "legacy",
                                    "FINN_GEMINI_MODEL": "gemini-custom"}):
            self.assertEqual(llm.model("openai"), "explicit-openai")
            self.assertEqual(llm.model("gemini"), "gemini-custom")

    def test_gemini_transport_uses_header_key_schema_and_public_passages_only(self):
        data = analysis.retrieve("INFY", "guidance")
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(gemini_reply(data)).encode()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-fixture"}), patch(
                "finn.llm.build_opener", return_value=opener):
            result = analysis.call_model(llm.GEMINI_MODEL, data, "guidance")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, llm.GEMINI_ENDPOINT + llm.GEMINI_MODEL + ":generateContent")
        self.assertNotIn("gemini-fixture", request.full_url)
        self.assertEqual(dict(request.header_items())["X-goog-api-key"], "gemini-fixture")
        self.assertNotIn("Authorization", dict(request.header_items()))
        payload = json.loads(request.data)
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 8192)
        self.assertNotIn("minLength", json.dumps(payload["generationConfig"]["responseJsonSchema"]))
        self.assertNotIn("tools", payload)
        self.assertNotIn("Mira Shah", json.dumps(payload))
        self.assertNotIn("gemini-fixture", json.dumps(payload))
        self.assertTrue(analysis.verify(result, data)["findings"])
        self.assertNotIn("Internal thought", json.dumps(result))

    def test_gemini_usage_includes_thought_tokens_without_inventing_a_free_bill(self):
        data = analysis.retrieve("INFY", "guidance")
        result = llm.normalize_gemini(gemini_reply(data))
        usage = analysis.usage_record(result, llm.GEMINI_MODEL, 2)
        self.assertEqual(usage["input_tokens"], 1200)
        self.assertEqual(usage["output_tokens"], 460)
        self.assertEqual(usage["reasoning_tokens"], 300)
        self.assertEqual(usage["cached_input_tokens"], 100)
        self.assertIsNone(usage["estimated_usd"])
        self.assertEqual(usage["actual_model"], llm.GEMINI_MODEL)

    def test_gemini_truncation_block_and_bad_output_never_publish(self):
        data = analysis.retrieve("INFY", "guidance")
        empty = {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}
        malformed = gemini_reply(data)
        malformed["candidates"][0]["content"]["parts"] = [{"text": "not JSON"}]
        for reply in [gemini_reply(data, "MAX_TOKENS"), gemini_reply(data, "SAFETY"), empty, malformed, {}]:
            with self.assertRaises(analysis.AnalysisError):
                analysis.verify(llm.normalize_gemini(reply), data)

    def test_thinking_only_truncation_retains_reported_usage(self):
        raw = {"candidates": [{"finishReason": "MAX_TOKENS"}],
               "usageMetadata": {"promptTokenCount": 100, "thoughtsTokenCount": 8192}}
        result = llm.normalize_gemini(raw)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["usage"]["output_tokens"], 8192)
        self.assertEqual(result["usage"]["reasoning_tokens"], 8192)

    def test_gemini_bad_citation_is_rejected_by_shared_verifier(self):
        data = analysis.retrieve("INFY", "guidance")
        reply = gemini_reply(data)
        output = json.loads(reply["candidates"][0]["content"]["parts"][1]["text"])
        output["findings"][0]["evidence"][0]["passage_id"] = "P999"
        reply["candidates"][0]["content"]["parts"][1]["text"] = json.dumps(output)
        self.assertEqual(analysis.verify(llm.normalize_gemini(reply), data)["withheld"], 1)

    def test_quota_key_and_connection_errors_do_not_retry_or_fallback(self):
        data = analysis.retrieve("INFY", "guidance")
        for error in [HTTPError(llm.GEMINI_ENDPOINT, 429, "private", {}, BytesIO(b"private")),
                      HTTPError(llm.GEMINI_ENDPOINT, 400, "private", {}, BytesIO(b"private")), URLError("private")]:
            opener = MagicMock()
            opener.open.side_effect = error
            with patch.dict(os.environ, {"GEMINI_API_KEY": "fixture-g", "OPENAI_API_KEY": "fixture-o"}), patch(
                    "finn.llm.build_opener", return_value=opener):
                with self.assertRaises(llm.ProviderError) as exc:
                    analysis.call_model(llm.GEMINI_MODEL, data, "guidance")
            self.assertNotIn("private", str(exc.exception))
            self.assertEqual(opener.open.call_count, 1)
            self.assertIn("generativelanguage.googleapis.com", opener.open.call_args.args[0].full_url)

    def test_provider_is_part_of_cache_key_even_for_same_model_name(self):
        with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "gemini", "FINN_GEMINI_MODEL": "same-model"}):
            _, _, gemini_key = analysis.context("INFY", "guidance")
        with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "openai", "FINN_OPENAI_MODEL": "same-model"}):
            _, _, openai_key = analysis.context("INFY", "guidance")
        self.assertNotEqual(gemini_key, openai_key)

    def test_running_job_keeps_provider_selected_at_creation(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fixture-g", "OPENAI_API_KEY": "fixture-o"}):
            _, work = analysis.begin("INFY", "guidance")
            data = work[-1]
            with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "openai"}), patch(
                    "finn.llm.post_json", return_value=gemini_reply(data)) as post:
                analysis.run(*work)
            self.assertTrue(post.call_args.args[0].startswith(llm.GEMINI_ENDPOINT))
            status = analysis.status("INFY", "guidance")
            self.assertEqual(status["job"]["provider"], "gemini")
            self.assertEqual(status["job"]["status"], "complete")

    def test_old_database_adds_provider_without_losing_results(self):
        with live_store.connection() as db:
            db.execute(analysis.SCHEMA.replace(", provider TEXT NOT NULL DEFAULT 'openai'", ""))
            db.execute("INSERT INTO research_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                "old-key", "INFY", "guidance", "token", "complete", "2026-01-01", "2026-01-01", "2026-01-02",
                "Saved old result", '{"findings":[]}', None, llm.OPENAI_MODEL))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: analysis.status("INFY", "guidance"), range(2)))
        with live_store.connection() as db:
            row = db.execute("SELECT provider,result FROM research_runs WHERE cache_key='old-key'").fetchone()
            self.assertEqual(row["provider"], "openai")
            self.assertEqual(json.loads(row["result"]), {"findings": []})
