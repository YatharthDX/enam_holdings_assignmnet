"""Public AI is explicit, free-only, bounded and shared without real API calls."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from finn import analysis, documents, live_store, llm, public_ai, workspaces
from test_analysis import response_for
from test_import import make_pdf


class PublicAITests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        env = patch.dict(os.environ, {
            "FINN_DATA_DIR": folder.name, "FINN_PUBLIC_DEMO": "1", "FINN_INTERACTIVE_DEMO": "1",
            "FINN_ENABLE_LLM": "1", "FINN_PUBLIC_LLM": "1", "FINN_LLM_PROVIDER": "openrouter",
            "FINN_OPENROUTER_MODEL": "openrouter/free", "OPENROUTER_API_KEY": "test-not-a-real-key",
            "OPENAI_API_KEY": "test-not-a-real-key", "FINN_SESSION_SECRET": ""})
        env.start()
        self.addCleanup(env.stop)
        token = workspaces._current.set("public")
        self.addCleanup(workspaces._current.reset, token)
        self.enter_new_workspace()

    def enter_new_workspace(self):
        _, session = workspaces.create()
        workspaces._current.set(session["workspace"])

    def start(self, index):
        symbol = "CHECK" + str(index)
        path = self.root / (symbol + ".pdf")
        make_pdf(path, ["Revenue grew 12% in FY 2025 on a consolidated basis."])
        documents.import_pdf(path, symbol, "annual_report", "FY 2025 annual report",
                             "https://issuer.example/" + symbol + ".pdf", "2025-07-01")
        return analysis.begin(symbol, "business")

    def finish(self, index):
        result, job = self.start(index)
        self.assertFalse(result["cached"])
        analysis.run(*job, caller=lambda model, data, lens: response_for(data))

    def count(self):
        with live_store.connection() as db:
            analysis.prepare(db)
            return db.execute("SELECT COUNT(*) FROM public_ai_attempts").fetchone()[0]

    def test_all_public_switches_and_explicit_free_provider_are_required(self):
        self.assertTrue(llm.enabled())
        for key, value in [("FINN_ENABLE_LLM", "0"), ("FINN_PUBLIC_LLM", "0"),
                           ("FINN_INTERACTIVE_DEMO", "0"), ("FINN_LLM_PROVIDER", "openai"),
                           ("FINN_LLM_PROVIDER", "gemini"), ("FINN_LLM_PROVIDER", "auto")]:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                self.assertFalse(llm.enabled())

    def test_anonymous_browser_cannot_start_generation(self):
        workspaces._current.set("public")
        with self.assertRaisesRegex(llm.ProviderError, "Open your own workspace"):
            analysis.begin("INFY", "business")
        self.assertEqual(self.count(), 0)

    def test_public_transport_rejects_paid_provider_and_model_before_network(self):
        with patch("finn.llm.post_json") as post:
            for provider, model in [("openai", llm.OPENAI_MODEL), ("openrouter", "vendor/paid-model")]:
                with self.assertRaises(llm.ProviderError):
                    llm.generate(provider, model, "test", {}, {})
            post.assert_not_called()

    def test_only_one_distinct_public_job_can_be_reserved_concurrently(self):
        owner = workspaces.current()
        def begin(lens):
            token = workspaces._current.set(owner)
            try:
                try:
                    return analysis.begin("INFY", lens)[0]["status"]
                except llm.ProviderError as exc:
                    return exc.code
            finally:
                workspaces._current.reset(token)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(begin, ["business", "guidance"]))
        self.assertCountEqual(results, ["running", "PUBLIC_AI_BUSY"])
        self.assertEqual(self.count(), 1)

    def test_saved_result_is_shared_and_does_not_consume_a_new_attempt(self):
        self.finish(0)
        self.enter_new_workspace()
        # Even a fully consumed global allowance must not hide a saved result.
        with live_store.connection() as db:
            db.executemany("INSERT INTO public_ai_attempts VALUES(?,?)",
                           [("other", analysis.now().timestamp())] * 14)
        with patch("finn.analysis.call_model") as call:
            result, job = analysis.begin("CHECK0", "business")
        self.assertTrue(result["cached"])
        self.assertIsNone(job)
        self.assertEqual(self.count(), 15)
        call.assert_not_called()
        self.assertEqual(analysis.status("CHECK0")["public_limits"], public_ai.LIMITS)

    def test_workspace_hourly_limit_and_failed_attempt_accounting(self):
        for i in range(3):
            _, job = self.start(i)
            def fail(*args):
                raise llm.ProviderError("Controlled provider unavailability")
            analysis.run(*job, caller=fail)
        with self.assertRaises(llm.ProviderError) as caught:
            self.start(3)
        self.assertEqual(caught.exception.code, "PUBLIC_AI_LIMIT")
        self.assertEqual(self.count(), 3)

    def test_global_hourly_limit_survives_workspace_deletion(self):
        for i in range(5):
            self.enter_new_workspace()
            self.finish(i)
            workspaces.delete()
        self.enter_new_workspace()
        with self.assertRaises(llm.ProviderError) as caught:
            self.start(5)
        self.assertEqual(caught.exception.code, "PUBLIC_AI_LIMIT")
        self.assertEqual(self.count(), 5)

    def test_daily_limit_and_window_expiry(self):
        with live_store.connection() as db:
            analysis.prepare(db)
            db.executemany("INSERT INTO public_ai_attempts VALUES(?,?)",
                           [("other", analysis.now().timestamp() - 7200)] * 15)
        with self.assertRaises(llm.ProviderError) as caught:
            self.start(0)
        self.assertEqual(caught.exception.code, "PUBLIC_AI_LIMIT")
        with live_store.connection() as db:
            db.execute("UPDATE public_ai_attempts SET at=at-86400")
        self.finish(0)
        self.assertEqual(self.count(), 1)

    def test_missing_key_does_not_use_the_public_allowance(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            with self.assertRaisesRegex(llm.ProviderError, "OPENROUTER_API_KEY"):
                self.start(0)
        self.assertEqual(self.count(), 0)
