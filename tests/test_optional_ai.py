"""Optional AI must never be required by the core workflows or trigger itself."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from finn import analysis, diagnose, llm


class OptionalAITests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": folder.name, "FINN_ENABLE_LLM": "0",
                                     "FINN_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "fixture-key",
                                     "FINN_GEMINI_MODEL": "", "FINN_LLM_TIMEOUT_SECONDS": ""})
        env.start()
        self.addCleanup(env.stop)

    def test_disabled_by_default_even_when_key_is_present(self):
        with patch.dict(os.environ):
            os.environ.pop("FINN_ENABLE_LLM", None)
            self.assertFalse(llm.enabled())
            self.assertFalse(llm.public_config()["enabled"])

    def test_disabled_status_does_not_parse_provider_or_retrieve_ai_context(self):
        with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "invalid"}), patch("finn.analysis.retrieve") as retrieve:
            status = analysis.status("INFY", "guidance")
            self.assertFalse(status["enabled"])
            self.assertIsNone(status["job"])
            retrieve.assert_not_called()

    def test_api_and_transport_both_block_disabled_generation(self):
        with patch("finn.llm.post_json") as post:
            with self.assertRaisesRegex(llm.ProviderError, "disabled"):
                analysis.begin("INFY", "guidance")
            with self.assertRaisesRegex(llm.ProviderError, "disabled"):
                llm.generate("gemini", llm.GEMINI_MODEL, "unused", {}, {})
            post.assert_not_called()

    def test_disabled_diagnostic_does_not_contact_provider(self):
        with patch("finn.llm.get_json") as get:
            result = diagnose.check()
            self.assertEqual(result["code"], "OPTIONAL_AI_DISABLED")
            get.assert_not_called()

    def test_queued_job_is_not_sent_if_feature_is_disabled_before_execution(self):
        with patch.dict(os.environ, {"FINN_ENABLE_LLM": "1"}):
            _, work = analysis.begin("INFY", "guidance")
        caller = MagicMock()
        analysis.run(*work, caller=caller)
        caller.assert_not_called()
        with patch.dict(os.environ, {"FINN_ENABLE_LLM": "1"}):
            self.assertEqual(analysis.status("INFY", "guidance")["job"]["status"], "error")
