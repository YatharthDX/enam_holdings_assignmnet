"""Grounding, cost control and error handling without external model calls."""
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from finn import analysis, documents, live_store
from test_import import make_pdf


def response_for(data, text=None):
    p = data["passages"][0]
    finding = {"label": "Guidance", "kind": "fact", "text": text or p["text"],
               "evidence": [{"passage_id": p["id"], "quote": p["text"][:480]}]}
    return response_with({"findings": [finding], "gaps": []})


def response_with(output):
    return {"id": "resp_test", "status": "completed", "usage": {"input_tokens": 1000,
            "output_tokens": 100, "input_tokens_details": {"cached_tokens": 200}},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(output)}]}]}


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {"FINN_ENABLE_LLM": "1", "FINN_DATA_DIR": str(self.root / "db"),
                                    "OPENAI_API_KEY": "test-key-never-real",
                                    "FINN_RESEARCH_MODEL": analysis.DEFAULT_MODEL,
                                    "FINN_LLM_PROVIDER": "openai", "FINN_OPENAI_MODEL": ""})
        env.start()
        self.addCleanup(env.stop)

    def add_document(self, text="Revenue grew 12% in FY 2025 on a consolidated basis.", url="one"):
        path = self.root / "doc.pdf"
        make_pdf(path, [text])
        return documents.import_pdf(path, "NEWCO", "annual_report", "FY 2025 annual report",
                                    "https://issuer.example/" + url + ".pdf", "2025-07-01")

    def test_unseeded_company_uses_imported_original_with_exact_page(self):
        self.add_document()
        data = analysis.retrieve("NEWCO", "business")
        checked = analysis.verify(response_for(data), data)
        source = checked["findings"][0]["sources"][0]
        self.assertEqual(source["url"], "https://issuer.example/one.pdf")
        self.assertEqual(source["page"], 1)
        self.assertEqual(data["coverage"]["corpus"], "indexed_originals")
        self.assertNotIn("digest", source)

    def test_unsupported_number_quote_or_reference_withholds_finding(self):
        self.add_document()
        data = analysis.retrieve("NEWCO", "business")
        for field, value in [("number", "Revenue grew 99% in FY 2025."),
                             ("quote", "This quote is not in the original document."),
                             ("reference", "P99")]:
            reply = response_for(data)
            output = json.loads(reply["output"][0]["content"][0]["text"])
            finding = output["findings"][0]
            if field == "number": finding["text"] = value
            if field == "quote": finding["evidence"][0]["quote"] = value
            if field == "reference": finding["evidence"][0]["passage_id"] = value
            checked = analysis.verify(response_with(output), data)
            self.assertEqual(checked["withheld"], 1, field)
            self.assertFalse(checked["findings"], field)

    def test_whitespace_normalization_preserves_real_quotes(self):
        self.add_document()
        data = analysis.retrieve("NEWCO", "cash")
        reply = response_for(data)
        output = json.loads(reply["output"][0]["content"][0]["text"])
        output["findings"][0]["evidence"][0]["quote"] = data["passages"][0]["text"].replace(" ", "\n ")
        self.assertEqual(len(analysis.verify(response_with(output), data)["findings"]), 1)

    def test_refusal_truncation_and_invalid_schema_never_publish(self):
        data = analysis.retrieve("INFY", "guidance")
        replies = [{"status": "incomplete"}, {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "refusal"}]}]}, response_with({"unexpected": "field"})]
        for reply in replies:
            with self.assertRaises(analysis.AnalysisError):
                analysis.verify(reply, data)

    def test_successful_cache_avoids_second_call_even_without_key(self):
        calls = []
        def caller(model, data, mode):
            calls.append(mode)
            return response_for(data)
        result, work = analysis.begin("INFY", "guidance")
        self.assertFalse(result["cached"])
        analysis.run(*work, caller=caller)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            result, work = analysis.begin("INFY", "guidance")
            self.assertTrue(result["cached"])
            self.assertIsNone(work)
            current = analysis.status("INFY", "guidance")
        self.assertEqual(calls, ["guidance"])
        self.assertEqual(current["job"]["status"], "complete")
        self.assertAlmostEqual(current["job"]["usage"]["estimated_usd"], .001065)
        self.assertFalse(current["configured"])

    def test_duplicate_concurrent_requests_acquire_one_job(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: analysis.begin("INFY", "guidance"), range(2)))
        self.assertEqual(sum(work is not None for _, work in results), 1)

    def test_global_concurrency_limit(self):
        analysis.begin("INFY", "business")
        analysis.begin("INFY", "guidance")
        with self.assertRaisesRegex(analysis.AnalysisError, "Two research jobs"):
            analysis.begin("INFY", "cash")

    def test_document_revision_lens_and_model_invalidate_cache(self):
        self.add_document()
        _, _, first = analysis.context("NEWCO", "business")
        _, _, other_lens = analysis.context("NEWCO", "cash")
        self.add_document(text="Revenue grew 13% in FY 2025 on a consolidated basis.")
        _, _, replacement = analysis.context("NEWCO", "business")
        with patch.dict(os.environ, {"FINN_RESEARCH_MODEL": "another-model"}):
            _, _, other_model = analysis.context("NEWCO", "business")
        self.assertEqual(len({first, other_lens, replacement, other_model}), 4)

    def test_imported_originals_replace_historical_evidence(self):
        path = self.root / "original.pdf"
        make_pdf(path, ["Business overview: new evidence from an imported original report."])
        documents.import_pdf(path, "INFY", "annual_report", "New original", "https://issuer.example/new.pdf", "")
        data = analysis.retrieve("INFY", "business")
        self.assertEqual(data["coverage"]["corpus"], "indexed_originals")
        self.assertEqual(len(data["passages"]), 1)
        self.assertEqual(data["passages"][0]["source"]["date"], "Publication date unverified")

    def test_retrieval_budget_and_document_diversity(self):
        for i in range(6):
            self.add_document(text=("Cash flows operating activities and business revenue growth. " * 500), url=str(i))
        data = analysis.retrieve("NEWCO", "cash")
        self.assertLessEqual(data["coverage"]["characters"], analysis.MAX_CONTEXT_CHARS)
        self.assertLessEqual(len(data["passages"]), analysis.MAX_PASSAGES)
        self.assertEqual(len({p["source"]["id"] for p in data["passages"]}), 5)

    def test_missing_key_empty_corpus_and_bad_lens_make_no_job(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaisesRegex(analysis.AnalysisError, "OPENAI_API_KEY"):
                analysis.begin("INFY", "guidance")
        with self.assertRaisesRegex(analysis.AnalysisError, "Find primary documents"):
            analysis.begin("UNCOVERED", "business")
        with self.assertRaises(analysis.AnalysisError):
            analysis.begin("INFY", "unknown")

    def test_failed_job_has_usage_and_requires_explicit_retry(self):
        _, work = analysis.begin("INFY", "guidance")
        reply = response_for(work[-1])
        reply["status"] = "incomplete"
        analysis.run(*work, caller=lambda *args: reply)
        job = analysis.status("INFY", "guidance")["job"]
        self.assertEqual(job["status"], "error")
        self.assertIsNone(job["result"])
        self.assertEqual(job["usage"]["input_tokens"], 1000)
        _, next_work = analysis.begin("INFY", "guidance")
        self.assertNotEqual(work[1], next_work[1])

    def test_expired_job_does_not_hide_interruption_or_accept_stale_writer(self):
        _, old = analysis.begin("INFY", "guidance")
        with live_store.connection() as db:
            db.execute("UPDATE research_runs SET expires='2000-01-01'")
        self.assertEqual(analysis.status("INFY", "guidance")["job"]["status"], "interrupted")
        _, new = analysis.begin("INFY", "guidance")
        analysis.run(*old, caller=lambda model, data, mode: response_for(data))
        self.assertEqual(analysis.status("INFY", "guidance")["job"]["status"], "running")
        analysis.run(*new, caller=lambda model, data, mode: response_for(data))
        self.assertEqual(analysis.status("INFY", "guidance")["job"]["status"], "complete")

    def test_api_payload_is_bounded_structured_and_excludes_network(self):
        data = analysis.retrieve("INFY", "guidance")
        opener = unittest.mock.MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(response_for(data)).encode()
        with patch("finn.llm.build_opener", return_value=opener):
            analysis.call_model(analysis.DEFAULT_MODEL, data, "guidance")
        request = opener.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertFalse(payload["store"])
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(payload["max_output_tokens"], 3500)
        self.assertEqual(set(json.loads(payload["input"])), {"task", "coverage", "passages"})
        self.assertNotIn("Mira Shah", payload["input"])

    def test_provider_errors_are_redacted_and_not_retried(self):
        data = analysis.retrieve("INFY", "guidance")
        for error in [HTTPError(analysis.ENDPOINT, 401, "secret", {}, BytesIO(b"secret")),
                      HTTPError(analysis.ENDPOINT, 429, "secret", {}, BytesIO(b"secret")), URLError("secret")]:
            opener = unittest.mock.Mock()
            opener.open.side_effect = error
            with patch("finn.llm.build_opener", return_value=opener):
                with self.assertRaises(analysis.AnalysisError) as exc:
                    analysis.call_model(analysis.DEFAULT_MODEL, data, "guidance")
            self.assertNotIn("secret", str(exc.exception))
            self.assertEqual(opener.open.call_count, 1)
