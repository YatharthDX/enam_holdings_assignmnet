import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from finn import desk, documents


def make_pdf(path, texts):
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    for line in texts:
        page = writer.add_blank_page(width=360, height=400)
        if line:
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            stream = DecodedStreamObject()
            stream.set_data(("BT /F1 12 Tf 20 340 Td (" + line + ") Tj ET").encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)


class ImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": str(self.root / "db")})
        env.start()
        self.addCleanup(env.stop)
        self.pdf = self.root / "primary.pdf"
        self.args = dict(file=self.pdf, symbol="NEWCO", kind="annual_report",
                         title="Test annual report", url="https://issuer.example/report.pdf",
                         published="2024-07-01")

    def test_unseen_ticker_search_retains_page_and_origin(self):
        make_pdf(self.pdf, ["Business overview", "Copper utilisation rose during the year."])
        documents.import_pdf(**self.args)
        result = desk.research("NEWCO", "copper")
        self.assertEqual(result["matches"][0]["page"], 2)
        self.assertEqual(result["matches"][0]["url"], self.args["url"])
        self.assertIn("Copper utilisation", result["matches"][0]["excerpt"])
        self.assertTrue(any(c["symbol"] == "NEWCO" for c in desk.all_companies()))

    def test_retries_and_replacements_preserve_one_document(self):
        make_pdf(self.pdf, ["Packaging volumes grew."])
        first = documents.import_pdf(**self.args)
        self.assertEqual(documents.import_pdf(**self.args)[2], "already indexed")
        make_pdf(self.pdf, ["A replacement page on fluorochemicals."])
        self.assertEqual(documents.import_pdf(**self.args)[0], first[0])
        self.assertEqual(len(desk.research("NEWCO")["sources"]), 1)
        self.assertFalse(desk.research("NEWCO", "packaging")["matches"])
        self.assertTrue(desk.research("NEWCO", "fluorochemicals")["matches"])

    def test_unreadable_replacement_keeps_last_verified_pages(self):
        make_pdf(self.pdf, ["Dealer inventory normalised."])
        documents.import_pdf(**self.args)
        make_pdf(self.pdf, [""])
        with self.assertRaisesRegex(ValueError, "no selectable text"):
            documents.import_pdf(**self.args)
        self.assertTrue(desk.research("NEWCO", "inventory")["matches"])

    def test_new_index_may_be_read_while_schema_is_being_created(self):
        path = documents.database_path()
        path.parent.mkdir()
        with sqlite3.connect(path) as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("CREATE TABLE scratch (x TEXT)")
            self.assertFalse(documents.symbols())
            self.assertEqual(documents.for_symbol("NEWCO", True), ([], []))

    def test_invalid_url_and_future_dates(self):
        for url in ("file:///tmp/x", "https://a:b@example.com"):
            with self.assertRaises(ValueError):
                documents.source_url(url)
        with self.assertRaises(ValueError):
            documents.import_pdf(**{**self.args, "published": "2099-01-01"})

    def test_public_index_accepts_a_677_page_report_and_preserves_last_page(self):
        make_pdf(self.pdf, ["Business operations continue."] * 676 + ["Finalpage evidence on funding."])
        with patch.dict(os.environ, {"FINN_PUBLIC_DEMO": "1"}):
            _, pages, state = documents.import_pdf(**self.args)
            self.assertEqual((pages, state), (677, "indexed"))
            results = desk.research("NEWCO", "finalpage")["matches"]
            self.assertEqual(results[0]["page"], 677)

    def test_report_above_800_pages_is_rejected_in_both_modes_without_replacing_evidence(self):
        make_pdf(self.pdf, ["Verified previous evidence remains available."])
        documents.import_pdf(**self.args)
        make_pdf(self.pdf, ["Replacement evidence."] * 801)
        for public in ("0", "1"):
            with self.subTest(public=public), patch.dict(os.environ, {"FINN_PUBLIC_DEMO": public}):
                with self.assertRaisesRegex(ValueError, "801 pages.*800"):
                    documents.import_pdf(**self.args)
                self.assertTrue(desk.research("NEWCO", "previous")["matches"])

    def test_encrypted_pdf_error_is_separate_from_page_count_error(self):
        writer = PdfWriter()
        writer.add_blank_page(width=360, height=400)
        writer.encrypt("fixture-password")
        writer.write(self.pdf)
        with patch.dict(os.environ, {"FINN_PUBLIC_DEMO": "1"}):
            with self.assertRaisesRegex(ValueError, "PDF is encrypted") as caught:
                documents.import_pdf(**self.args)
        self.assertNotIn("pages", str(caught.exception))

    def test_public_download_size_bound_remains_in_effect(self):
        with self.pdf.open("wb") as file:
            file.write(b"%PDF-")
            file.truncate(20 * 1024 * 1024 + 1)
        with patch.dict(os.environ, {"FINN_PUBLIC_DEMO": "1"}):
            with self.assertRaisesRegex(ValueError, "20 MiB"):
                documents.import_pdf(**self.args)


if __name__ == "__main__":
    unittest.main()
