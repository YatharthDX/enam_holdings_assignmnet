"""Exercise the real app, its static client and its JSON routes over loopback."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener
from unittest.mock import patch

import uvicorn

from finn.app import app


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = tempfile.TemporaryDirectory()
        cls.addClassCleanup(data.cleanup)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": data.name})
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
