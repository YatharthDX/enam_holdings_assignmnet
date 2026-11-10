"""Slow-response handling and ownership safety without real model requests."""
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from finn import analysis, live_store, llm
from test_analysis import response_for


class TimeoutTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"FINN_PUBLIC_DEMO": "0", "FINN_ENABLE_LLM": "1", "FINN_DATA_DIR": folder.name, "FINN_LLM_PROVIDER": "gemini",
                         "GEMINI_API_KEY": "fixture-key", "FINN_GEMINI_MODEL": "", "FINN_LLM_TIMEOUT_SECONDS": ""})
        env.start()
        self.addCleanup(env.stop)
        self.start = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)

    def test_timeout_default_override_and_invalid_settings(self):
        self.assertEqual(llm.timeout_seconds(), 240)
        self.assertEqual(llm.public_config()["timeout_seconds"], 240)
        for raw in ("30", "360", "600"):
            with patch.dict(os.environ, {"FINN_LLM_TIMEOUT_SECONDS": raw}):
                self.assertEqual(llm.timeout_seconds(), int(raw))
        for raw in ("0", "29", "601", "NaN", "2.5"):
            with patch.dict(os.environ, {"FINN_LLM_TIMEOUT_SECONDS": raw}):
                with self.assertRaises(llm.ProviderError): llm.timeout_seconds()

    def test_generation_uses_configured_timeout_but_metadata_keeps_short_timeout(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{}'
        with patch.dict(os.environ, {"FINN_LLM_TIMEOUT_SECONDS": "360"}), patch(
                "finn.llm.build_opener", return_value=opener):
            llm.post_json(llm.GEMINI_ENDPOINT + "fixture:generateContent", {}, {}, "gemini")
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 360)
            llm.get_json(llm.GEMINI_ENDPOINT + "fixture", {}, "gemini")
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)

    def test_request_after_old_110_second_limit_still_owns_its_job(self):
        with patch("finn.analysis.now", return_value=self.start):
            _, work = analysis.begin("INFY", "guidance")
        with patch("finn.analysis.now", return_value=self.start + timedelta(seconds=200)):
            self.assertEqual(analysis.status("INFY", "guidance")["job"]["status"], "running")
            _, duplicate = analysis.begin("INFY", "guidance")
            self.assertIsNone(duplicate)
        analysis.run(*work, caller=lambda model, data, mode: response_for(data))
        self.assertEqual(analysis.status("INFY", "guidance")["job"]["status"], "complete")

    def test_lease_expands_for_a_longer_configured_wait(self):
        with patch.dict(os.environ, {"FINN_LLM_TIMEOUT_SECONDS": "600"}), patch(
                "finn.analysis.now", return_value=self.start):
            _, work = analysis.begin("INFY", "guidance")
        with live_store.connection() as db:
            expires = db.execute("SELECT expires FROM research_runs WHERE cache_key=?", (work[0],)).fetchone()[0]
        self.assertEqual(datetime.fromisoformat(expires), self.start + timedelta(seconds=720))

    def test_heartbeat_extends_ownership_for_a_live_worker(self):
        clock = [self.start]
        with patch("finn.analysis.now", side_effect=lambda: clock[0]):
            _, work = analysis.begin("INFY", "guidance")
            with patch("finn.analysis.HEARTBEAT_SECONDS", .01):
                with analysis.keep_lease(work[0], work[1]) as owned:
                    self.assertTrue(owned)
                    clock[0] = self.start + timedelta(seconds=350)
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        with live_store.connection() as db:
                            expiry = db.execute("SELECT expires FROM research_runs WHERE cache_key=?", (work[0],)).fetchone()[0]
                        if datetime.fromisoformat(expiry) > clock[0] + timedelta(seconds=100): break
                        time.sleep(.01)
                    clock[0] = self.start + timedelta(seconds=400)
                    _, duplicate = analysis.begin("INFY", "guidance")
                    self.assertIsNone(duplicate)
        self.assertFalse(any(t.name == "finn-research-lease" for t in threading.enumerate()))

    def test_replaced_queued_task_does_not_send_another_model_request(self):
        with patch("finn.analysis.now", return_value=self.start):
            _, old = analysis.begin("INFY", "guidance")
        with patch("finn.analysis.now", return_value=self.start + timedelta(seconds=500)):
            _, new = analysis.begin("INFY", "guidance")
        caller = MagicMock()
        analysis.run(*old, caller=caller)
        caller.assert_not_called()
        self.assertNotEqual(old[1], new[1])

    def test_timeout_change_reuses_the_same_answer_cache_identity(self):
        _, _, before = analysis.context("INFY", "guidance")
        with patch.dict(os.environ, {"FINN_LLM_TIMEOUT_SECONDS": "600"}):
            _, _, after = analysis.context("INFY", "guidance")
        self.assertEqual(before, after)
