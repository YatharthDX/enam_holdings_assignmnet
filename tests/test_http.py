"""Exercise the real app, its static client and its JSON routes over loopback."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch

import uvicorn

from finn.app import app


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = tempfile.TemporaryDirectory()
        cls.addClassCleanup(data.cleanup)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": data.name, "FINN_AUTO_REFRESH": "0"})
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
        for file in ["app.js", "views.js", "ui.js", "desk.css", "icon.svg"]:
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
