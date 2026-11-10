"""Exercise the real app, its static client and its JSON routes over loopback."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch

import uvicorn

from finn.app import app
from finn import smoke


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = tempfile.TemporaryDirectory()
        cls.addClassCleanup(data.cleanup)
        env = patch.dict(os.environ, {"FINN_PUBLIC_DEMO": "0", "FINN_ENABLE_LLM": "1", "FINN_DATA_DIR": data.name, "FINN_AUTO_REFRESH": "0",
                                     "FINN_LLM_PROVIDER": "openai", "GEMINI_API_KEY": ""})
        env.start()
        cls.addClassCleanup(env.stop)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        cls.addClassCleanup(sock.close)
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join, 5)
        cls.addClassCleanup(setattr, cls.server, "should_exit", True)
        deadline = time.monotonic() + 7
        while not cls.server.started:
            if time.monotonic() > deadline or not thread.is_alive():
                raise RuntimeError("Test server failed to start.")
            time.sleep(.02)
        cls.client = build_opener(ProxyHandler({}))

    def read(self, route):
        with self.client.open(self.base + route, timeout=3) as response:
            return response.read()

    def test_app_and_health(self):
        self.assertEqual(json.loads(self.read("/health"))["status"], "ok")
        self.assertIn(b"/assets/app.js", self.read("/"))
        for file in ["app.js", "views.js", "analysis-view.js", "ui.js", "desk.css", "icon.svg"]:
            self.assertTrue(self.read("/assets/" + file))

    def test_normal_entry_points(self):
        self.assertEqual(len(json.loads(self.read("/api/catalog"))["companies"]), 19)
        self.assertEqual(json.loads(self.read("/api/brief"))["focus"], "INFY")
        self.assertTrue(json.loads(self.read("/api/research/INFY?q=currency"))["matches"])
        self.assertEqual(json.loads(self.read("/api/people?q=SRF"))["people"][0]["name"], "Leela Nair")

    def test_invalid_window_and_uncovered_company(self):
        for url in ["/api/brief?window=invalid", "/api/brief?window=custom&start=2027-01-01&end=2027-01-02"]:
            with self.assertRaises(HTTPError) as error:
                self.read(url)
            self.assertEqual(error.exception.code, 422)
        self.assertFalse(json.loads(self.read("/api/research/UNCOVERED"))["sources"])

    def test_live_settings_are_validated_and_preserved(self):
        settings = {"enabled": False, "price_pct": 4.5, "volume_multiple": 2.5, "categories": ["results"]}
        request = Request(self.base + "/api/alert-settings", method="PUT",
                          data=json.dumps(settings).encode(), headers={"Content-Type": "application/json"})
        with self.client.open(request) as response:
            self.assertEqual(json.load(response)["settings"], settings)
        self.assertEqual(json.loads(self.read("/api/alert-settings"))["settings"], settings)
        invalid = Request(self.base + "/api/alert-settings", method="PUT",
                          data=json.dumps({**settings, "price_pct": True}).encode(),
                          headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as error:
            self.client.open(invalid)
        self.assertEqual(error.exception.code, 422)
        cross_origin = Request(self.base + "/api/alerts/read", method="POST", data=b"",
                               headers={"Origin": "https://unrelated.example"})
        with self.assertRaises(HTTPError) as error:
            self.client.open(cross_origin)
        self.assertEqual(error.exception.code, 403)
        self.assertEqual(json.loads(self.read("/api/brief?mode=live"))["mode"], "live")
        self.assertIsNone(json.loads(self.read("/api/brief?mode=live"))["comparison"])

    def test_discovery_route_starts_one_background_job(self):
        request = Request(self.base + "/api/research/UNSEEN/discover", method="POST", data=b"")
        with patch("finn.discovery.run") as run:
            with self.client.open(request) as response:
                self.assertEqual(response.status, 202)
            deadline = time.monotonic() + 2
            while run.call_count < 1 and time.monotonic() < deadline:
                time.sleep(.01)
            with self.client.open(request) as response:
                self.assertEqual(response.status, 202)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(json.loads(self.read("/api/research/UNSEEN/discovery"))["job"]["status"],
                             "running")

    def test_analysis_setup_validation_and_origin(self):
        info = json.loads(self.read("/api/research/INFY/analysis?lens=cash"))
        self.assertEqual(info["lens"], "cash")
        self.assertNotIn("OPENAI_API_KEY", info)
        for body, origin, expected in [({"lens": "cash"}, None, 422),
                                       ({"lens": "unknown"}, None, 422),
                                       ({"lens": "business", "key": "never"}, None, 422),
                                       ({"lens": "cash"}, "https://unrelated.example", 403)]:
            request = Request(self.base + "/api/research/INFY/analyze", method="POST",
                              data=json.dumps(body).encode(), headers={"Content-Type": "application/json",
                              **({"Origin": origin} if origin else {})})
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                with self.assertRaises(HTTPError) as error:
                    self.client.open(request)
            self.assertEqual(error.exception.code, expected)

    def test_analysis_http_flow_citations_and_persistent_cache(self):
        from test_analysis import response_for
        request = Request(self.base + "/api/research/INFY/analyze", method="POST",
                          data=b'{"lens":"guidance"}', headers={"Content-Type": "application/json"})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-never-real"}), patch(
                "finn.analysis.call_model", side_effect=lambda model, data, mode: response_for(data)) as call:
            with self.client.open(request) as response:
                self.assertFalse(json.load(response)["cached"])
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                info = json.loads(self.read("/api/research/INFY/analysis?lens=guidance"))
                if info["job"]["status"] != "running":
                    break
                time.sleep(.01)
            self.assertEqual(info["job"]["status"], "complete")
            self.assertTrue(info["job"]["result"]["findings"][0]["sources"][0]["page"])
            with self.client.open(request) as response:
                self.assertTrue(json.load(response)["cached"])
            self.assertEqual(call.call_count, 1)
            document_view = json.loads(self.read("/api/research/INFY?lens=guidance"))
            self.assertEqual(document_view["analysis"]["job"]["status"], "complete")

    def test_provider_status_is_read_only_and_redacts_both_keys(self):
        with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "auto", "GEMINI_API_KEY": "fixture-google-key",
                                    "OPENAI_API_KEY": "fixture-openai-key"}), patch("finn.llm.post_json") as post:
            raw = self.read("/api/llm/status")
            info = json.loads(raw)
            self.assertEqual(info["provider"], "gemini")
            self.assertTrue(info["configured"])
            self.assertFalse(info["fallback_enabled"])
            self.assertNotIn(b"fixture-google-key", raw)
            self.assertNotIn(b"fixture-openai-key", raw)
            self.assertFalse(post.called)

    def test_gemini_http_flow_checks_citations_and_reuses_cache(self):
        from test_llm import gemini_reply
        def provider_reply(endpoint, payload, headers, provider):
            self.assertEqual(provider, "gemini")
            data = json.loads(payload["contents"][0]["parts"][0]["text"])
            return gemini_reply(data)
        request = Request(self.base + "/api/research/INFY/analyze", method="POST",
                          data=b'{"lens":"guidance"}', headers={"Content-Type": "application/json"})
        with patch.dict(os.environ, {"FINN_LLM_PROVIDER": "auto", "GEMINI_API_KEY": "fixture-g",
                                    "OPENAI_API_KEY": "fixture-o"}), patch(
                "finn.llm.post_json", side_effect=provider_reply) as call:
            with self.client.open(request) as response:
                self.assertFalse(json.load(response)["cached"])
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                info = json.loads(self.read("/api/research/INFY/analysis?lens=guidance"))
                if info["job"]["status"] != "running": break
                time.sleep(.01)
            self.assertEqual(info["job"]["status"], "complete")
            self.assertEqual(info["job"]["provider"], "gemini")
            self.assertTrue(info["job"]["result"]["findings"][0]["sources"][0]["page"])
            self.assertEqual(info["job"]["usage"]["reasoning_tokens"], 300)
            with self.client.open(request) as response:
                self.assertTrue(json.load(response)["cached"])
            self.assertEqual(call.call_count, 1)

    def test_core_workflows_ignore_disabled_ai_even_with_invalid_provider_settings(self):
        with patch.dict(os.environ, {"FINN_ENABLE_LLM": "0", "FINN_LLM_PROVIDER": "invalid-provider",
                                    "GEMINI_API_KEY": "fixture-g", "OPENAI_API_KEY": "fixture-o",
                                    "FINN_GEMINI_MODEL": "invalid/model", "FINN_LLM_TIMEOUT_SECONDS": "invalid"}), patch(
                "finn.llm.generate", side_effect=AssertionError("Core workflows must not call a model")) as call:
            info = json.loads(self.read("/api/research/INFY?q=currency"))
            self.assertFalse(info["analysis"]["enabled"])
            self.assertTrue(info["matches"])
            self.assertEqual(info["comparison"]["actual"]["value"], 4.2)
            self.assertTrue(info["people"])
            self.assertTrue(json.loads(self.read("/api/brief?mode=replay"))["rows"])
            self.assertTrue(json.loads(self.read("/api/people?q=IT%20delivery"))["people"])
            self.assertFalse(json.loads(self.read("/api/llm/status"))["enabled"])
            request = Request(self.base + "/api/research/INFY/analyze", method="POST",
                              data=b'{"lens":"guidance"}', headers={"Content-Type": "application/json"})
            with self.assertRaises(HTTPError) as error:
                self.client.open(request)
            self.assertEqual(error.exception.code, 422)
            self.assertIn(b"disabled", error.exception.read())
            self.assertFalse(call.called)

    def test_invalid_enabled_ai_settings_do_not_block_primary_research(self):
        with patch.dict(os.environ, {"FINN_ENABLE_LLM": "1", "FINN_LLM_PROVIDER": "invalid-provider"}):
            info = json.loads(self.read("/api/research/INFY?q=currency"))
            self.assertTrue(info["matches"])
            self.assertTrue(info["analysis"]["configuration_error"])
            self.assertTrue(info["comparison"])

    def test_ai_status_failure_does_not_block_or_leak_into_primary_research(self):
        with patch("finn.analysis.status", side_effect=RuntimeError("private-secret")), self.assertLogs("finn.app", level="WARNING") as logs:
            raw = self.read("/api/research/INFY?q=currency")
            info = json.loads(raw)
            self.assertTrue(info["matches"])
            self.assertTrue(info["comparison"])
            self.assertNotIn(b"private-secret", raw)
            self.assertNotIn("private-secret", " ".join(logs.output))

    def test_public_demo_blocks_all_mutation_routes_before_any_work_is_queued(self):
        from contextlib import ExitStack
        with patch.dict(os.environ, {"FINN_PUBLIC_DEMO": "1"}), ExitStack() as stack:
            workers = [stack.enter_context(patch(name)) for name in [
                "finn.app.discovery.begin", "finn.app.analysis.begin", "finn.app.live.refresh", "finn.app.live.update_settings"]]
            before = self.read("/api/alert-settings")
            for method, route in [("POST", "/api/research/INFY/discover"), ("POST", "/api/research/INFY/analyze"),
                                  ("POST", "/api/live/refresh"), ("PUT", "/api/alert-settings"), ("POST", "/api/alerts/read")]:
                with self.subTest(route=route):
                    request = Request(self.base + route, data=b'{}', method=method,
                                      headers={"Content-Type": "application/json"})
                    with self.assertRaises(HTTPError) as error:
                        self.client.open(request)
                    self.assertEqual(error.exception.code, 403)
                    self.assertIn(b"read-only", error.exception.read())
            self.assertEqual(before, self.read("/api/alert-settings"))
            for worker in workers:
                worker.assert_not_called()

    def test_public_demo_smoke_over_real_http_with_keys_present(self):
        with patch.dict(os.environ, {"FINN_PUBLIC_DEMO": "1", "FINN_ENABLE_LLM": "1",
                                    "GEMINI_API_KEY": "private-fixture-key"}), patch("finn.llm.post_json") as post:
            checks = smoke.run(self.base, expect_public_demo=True)
            self.assertEqual(len(checks), 9)
            self.assertNotIn(b"private-fixture-key", self.read("/api/catalog"))
            post.assert_not_called()

    def test_local_smoke_cli_and_wrong_public_expectation(self):
        with patch.dict(os.environ, {"FINN_ENABLE_LLM": "0"}):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(smoke.main(["--base-url", self.base]), 0)
            self.assertIn("Read-only checks passed", output.getvalue())
            with self.assertRaisesRegex(smoke.SmokeError, "not configured"):
                smoke.run(self.base, expect_public_demo=True)
