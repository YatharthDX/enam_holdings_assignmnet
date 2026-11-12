import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finn import desk, discovery, documents, providers
from test_import import make_pdf

PAGE = b"""<!doctype html><html><body><a href="https://www.nseindia.com/get-quotes/equity?symbol=NEWCO">NSE: NEWCO</a>
<h2>Documents</h2><h3>Annual reports</h3><ul>
<li><a href="https://issuer.example/annual.pdf">Annual Report 2026</a><button>AI Summary</button></li>
<li><a href="https://issuer.example/old.pdf">Annual Report 2025</a></li></ul>
<h3>Concalls</h3><ul><li>Oct 2026 <a href="https://issuer.example/call.pdf">Transcript</a>
<a href="https://issuer.example/deck.pdf">PPT</a><button>AI Summary</button></li></ul>
</body></html>"""


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": str(self.root / "db")})
        env.start()
        self.addCleanup(env.stop)

    def test_discovery_selects_primary_documents_and_verifies_ticker(self):
        links = discovery.parse_links(PAGE, "NEWCO", "https://www.screener.in/company/NEWCO/")
        self.assertEqual([r["kind"] for r in links], ["annual_report", "transcript"])
        self.assertEqual([r["url"] for r in links],
                         ["https://issuer.example/annual.pdf", "https://issuer.example/call.pdf"])
        self.assertIsNone(links[0]["published"])
        with self.assertRaises(providers.SourceError):
            discovery.parse_links(PAGE, "DIFFERENT", "https://www.screener.in/company/NEWCO/")

    def test_unseen_company_is_indexed_and_retry_does_not_duplicate(self):
        pdf = self.root / "original.pdf"
        make_pdf(pdf, ["Copper products are supplied to industrial customers."])
        def fetch(url):
            return PAGE if "screener.in" in url else pdf.read_bytes()
        for _ in range(2):
            token = discovery.begin("NEWCO")
            self.assertTrue(token)
            discovery.run("NEWCO", token, fetch=fetch)
        job = discovery.status("NEWCO")
        self.assertEqual(job["status"], "complete")
        result = desk.research("NEWCO", "copper")
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["matches"][0]["page"], 1)
        self.assertEqual(result["matches"][0]["date"], "Publication date unverified")

    def test_failed_update_keeps_previous_documents_and_original_links(self):
        pdf = self.root / "original.pdf"
        make_pdf(pdf, ["Semiconductor engineering is a disclosed business."])
        token = discovery.begin("NEWCO")
        discovery.run("NEWCO", token, fetch=lambda u: PAGE if "screener" in u else pdf.read_bytes())
        token = discovery.begin("NEWCO")
        discovery.run("NEWCO", token, fetch=lambda u: PAGE if "screener" in u else b"<html>Access unavailable</html>")
        self.assertEqual(discovery.status("NEWCO")["status"], "error")
        self.assertEqual(len(discovery.status("NEWCO")["sources"]), 2)
        self.assertTrue(desk.research("NEWCO", "semiconductor")["matches"])

    def test_active_job_and_private_links_are_rejected(self):
        self.assertTrue(discovery.begin("NEWCO"))
        self.assertIsNone(discovery.begin("NEWCO"))
        for url in ["http://issuer.example/a.pdf", "https://127.0.0.1/a.pdf",
                    "https://localhost/a.pdf", "https://user:pass@issuer.example/a.pdf",
                    "https://issuer.example:8080/a.pdf", "https://10.0.0.1/a.pdf"]:
            with self.assertRaises(providers.SourceError):
                discovery.public_url(url)

    def test_public_discovery_indexes_all_677_pages_of_a_large_annual_report(self):
        pdf = self.root / "large-report.pdf"
        make_pdf(pdf, ["Revenue and business overview."] * 676 + ["Finalpage public evidence."])
        annual_only = PAGE.replace(b"<h3>Concalls</h3>", b"<h3>Other</h3>")
        with patch.dict(os.environ, {"FINN_PUBLIC_DEMO": "1", "FINN_INTERACTIVE_DEMO": "1"}):
            token = discovery.begin("NEWCO")
            discovery.run("NEWCO", token, fetch=lambda url: annual_only if "screener.in" in url else pdf.read_bytes())
            job = discovery.status("NEWCO")
            self.assertEqual(job["status"], "complete", job["detail"])
            self.assertEqual(job["sources"][0]["pages"], 677)
            self.assertEqual(desk.research("NEWCO", "finalpage")["matches"][0]["page"], 677)


if __name__ == "__main__":
    unittest.main()
