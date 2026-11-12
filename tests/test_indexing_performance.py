"""Real parser, cache freshness, progress and bounded worker regression checks."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from finn import desk, discovery, documents, live_store, pdf_text
from test_discovery import PAGE
from test_import import make_pdf


class IndexingPerformanceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": str(self.root / "data"), "FINN_PUBLIC_DEMO": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.original = self.root / "original.pdf"
        make_pdf(self.original, ["Copper business overview and disclosed revenue.", "Finalpage evidence."])
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        return PAGE if "screener.in" in url else self.original.read_bytes()

    def index(self, **kwargs):
        token = discovery.begin("NEWCO")
        discovery.run("NEWCO", token, fetch=self.fetch, **kwargs)
        return discovery.status("NEWCO")

    def test_repeat_discovery_reuses_recent_pages_without_downloading_or_parsing_pdfs(self):
        self.assertEqual(self.index()["status"], "complete")
        self.calls.clear()
        with patch("finn.pdf_text.extract") as extract:
            job = self.index()
        self.assertEqual(job["status"], "complete")
        self.assertTrue(all(source["cached"] for source in job["sources"]))
        self.assertEqual(len(self.calls), 1)
        self.assertIn("screener.in", self.calls[0])
        extract.assert_not_called()

    def test_explicit_refresh_bypasses_cache_and_detects_replaced_content_at_same_url(self):
        self.index()
        make_pdf(self.original, ["Fluorochemicals business replaces the original disclosure."])
        self.index()
        self.assertTrue(desk.research("NEWCO", "copper")["matches"])
        job = self.index(force=True)
        self.assertEqual(job["status"], "complete")
        self.assertFalse(any(source.get("cached") for source in job["sources"]))
        self.assertFalse(desk.research("NEWCO", "copper")["matches"])
        self.assertTrue(desk.research("NEWCO", "fluorochemicals")["matches"])

    def test_expired_cache_rechecks_pdf_bytes_without_forcing(self):
        self.index()
        with live_store.connection() as db:
            db.execute("UPDATE document_checked SET at=at-21601")
        self.calls.clear()
        self.assertEqual(self.index()["status"], "complete")
        self.assertEqual(len([url for url in self.calls if url.endswith(".pdf")]), 2)

    def test_parser_reports_physical_page_progress_and_preserves_page_numbers(self):
        make_pdf(self.original, ["First page of evidence.", "", "Evidence remains on physical page three."])
        updates = []
        doc_id, pages, _ = documents.import_pdf(self.original, "NEWCO", "annual_report", "Report",
            "https://issuer.example/annual.pdf", "", progress=lambda done,total: updates.append((done,total)))
        self.assertEqual(pages, 2)
        self.assertEqual(updates[-1], (3, 3))
        self.assertEqual(desk.research("NEWCO", "physical")["matches"][0]["page"], 3)

    def test_real_stalled_worker_is_terminated_at_deadline(self):
        launch = subprocess.Popen
        processes = []
        def stalled(*args, **kwargs):
            process = launch([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            processes.append(process)
            return process
        with patch("finn.pdf_text.subprocess.Popen", side_effect=stalled):
            with self.assertRaisesRegex(ValueError, "exceeded"):
                pdf_text.extract(self.original, 800, timeout=.1)
        self.assertIsNotNone(processes[0].poll())

    def test_timeout_does_not_replace_previous_index(self):
        self.index()
        make_pdf(self.original, ["Replacement evidence should never be partially visible."])
        with patch("finn.pdf_text.extract", side_effect=ValueError("PDF extraction exceeded its deadline")):
            job = self.index(force=True)
        self.assertEqual(job["status"], "error")
        self.assertTrue(desk.research("NEWCO", "copper")["matches"])
        self.assertFalse(desk.research("NEWCO", "replacement")["matches"])

    def test_native_extractions_are_isolated_across_concurrent_callers(self):
        def index(symbol):
            return documents.import_pdf(self.original, symbol, "annual_report", "Report",
                                        "https://issuer.example/annual.pdf", "")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(index, ["NEWONE", "NEWTWO"]))
        self.assertEqual([r[1] for r in results], [2, 2])
        self.assertTrue(desk.research("NEWONE", "copper")["matches"])
        self.assertTrue(desk.research("NEWTWO", "copper")["matches"])

    def test_operator_file_change_cannot_mismatch_indexed_text_and_retained_original(self):
        original_bytes = self.original.read_bytes()
        launch = subprocess.Popen
        def change_before_launch(*args, **kwargs):
            make_pdf(self.original, ["Different revision must not replace the captured original."])
            return launch(*args, **kwargs)
        with patch("finn.pdf_text.subprocess.Popen", side_effect=change_before_launch):
            doc_id, _, _ = documents.import_pdf(self.original, "NEWCO", "annual_report", "Report",
                                                "https://issuer.example/annual.pdf", "")
        self.assertEqual(documents.cached_original(doc_id)[0].read_bytes(), original_bytes)
        self.assertTrue(desk.research("NEWCO", "copper")["matches"])
        self.assertFalse(desk.research("NEWCO", "different revision")["matches"])

    def test_pdf_worker_does_not_inherit_model_credentials(self):
        launch = subprocess.Popen
        def checked_launch(*args, **kwargs):
            self.assertNotIn("OPENROUTER_API_KEY", kwargs["env"])
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            self.assertNotIn("GEMINI_API_KEY", kwargs["env"])
            return launch(*args, **kwargs)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY":"fixture-not-real"}), patch(
                "finn.pdf_text.subprocess.Popen", side_effect=checked_launch):
            self.assertEqual(len(pdf_text.extract(self.original, 800)), 2)
