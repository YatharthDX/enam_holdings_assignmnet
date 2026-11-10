"""An unseeded ticker produces cited research and reviewed, comparable facts."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finn import documents, live_store as store, research, workspaces
from test_import import make_pdf

GUIDANCE = "Our business manufactures copper components for industrial customers. Management: Revenue growth guidance for FY25 is 5% to 7% in constant currency on a consolidated basis."
ACTUAL = "Company report: We delivered revenue growth of 6% in FY25 in constant currency on a consolidated basis. Operating cash flow improved as working capital declined."


class StructuredResearchTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        env = patch.dict(os.environ, {"FINN_DATA_DIR":str(self.root/'data'),"FINN_PUBLIC_DEMO":"0","FINN_ENABLE_LLM":"0"})
        env.start(); self.addCleanup(env.stop)
        _, session = workspaces.create()
        context = workspaces._current.set(session["workspace"])
        self.addCleanup(workspaces._current.reset, context)
        self.guide = self.add_document("guide", GUIDANCE, "2024-04-18")
        self.actual = self.add_document("actual", ACTUAL, "2025-04-17")

    def add_document(self, name, body, published):
        p=self.root/(name+'.pdf')
        make_pdf(p,[body])
        return documents.import_pdf(p,"NEWCO","transcript",name,"https://issuer.example/"+name+".pdf",published)[0]

    def fact(self, kind="guidance", **updates):
        value={"kind":kind,"metric":"revenue_growth","period":"FY25","unit":"%","scope":"consolidated", "basis":"constant_currency",
               "speaker":"Management" if kind=="guidance" else "Company report", "speaker_kind":"management" if kind=="guidance" else "report",
               "source_id":self.guide if kind=="guidance" else self.actual,"page":1,"quote":GUIDANCE if kind=="guidance" else ACTUAL,
               "published":"2024-04-18" if kind=="guidance" else "2025-04-17","reviewed":True,"low":"5" if kind=="guidance" else "6","high":"7" if kind=="guidance" else "6"}
        return {**value,**updates}

    def test_unseeded_ticker_has_exact_business_passage_and_candidates_without_model(self):
        with patch("finn.llm.generate") as generate:
            result=research.view("NEWCO")
            business=result["brief"]["groups"][0]["passages"][0]
            self.assertIn("copper components",business["text"])
            self.assertEqual(business["source"]["page"],1)
            self.assertTrue(result["candidates"])
            self.assertEqual(result["facts"],[])
            generate.assert_not_called()

    def test_reviewed_non_demo_guidance_and_outcome_compare_correctly(self):
        research.save_fact("NEWCO",self.fact())
        research.save_fact("NEWCO",self.fact("actual"))
        result=research.view("NEWCO")["comparisons"][0]
        self.assertEqual(result["position"],"within")
        self.assertEqual(result["points"],0)
        self.assertEqual(result["actual"]["source"]["url"],"https://issuer.example/actual.pdf")

    def test_asof_excludes_future_outcomes_and_undated_documents(self):
        research.save_fact("NEWCO",self.fact())
        research.save_fact("NEWCO",self.fact("actual"))
        self.add_document("unknown", "Our business provides industrial services.", "")
        result=research.view("NEWCO","2024-07-01")
        self.assertEqual(result["comparisons"][0]["position"],"pending")
        self.assertEqual(result["brief"]["documents"],1)
        self.assertEqual(result["brief"]["excluded_pages"],2)

    def test_bad_quote_value_authority_and_page_never_save(self):
        for updates in [{"quote":"This is not present in the original."},{"low":"99"},{"speaker_kind":"question"},
                        {"speaker_kind":"unidentified"},{"page":2},{"page":True},{"reviewed":False},{"period":"next year"},{"published":"2025-01-01"}]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                research.save_fact("NEWCO",self.fact(**updates))
        self.assertEqual(research.facts("NEWCO"),[])

    def test_scope_currency_unit_or_period_mismatch_never_compares(self):
        research.save_fact("NEWCO",self.fact())
        research.save_fact("NEWCO",self.fact("actual",basis="INR"))
        self.assertEqual(research.view("NEWCO")["comparisons"][0]["position"],"not_comparable")

    def test_source_revision_invalidates_old_reviewed_fact(self):
        research.save_fact("NEWCO",self.fact())
        research.save_fact("NEWCO",self.fact("actual"))
        self.add_document("guide",GUIDANCE.replace("5% to 7%","8% to 9%"),"2024-04-18")
        result=research.view("NEWCO")
        self.assertTrue(next(f for f in result["facts"] if f["kind"]=="guidance")["stale"])
        self.assertEqual(result["comparisons"][0]["position"],"not_comparable")

    def test_duplicate_fact_is_idempotent_and_other_workspace_cannot_read_or_delete_it(self):
        first=research.save_fact("NEWCO",self.fact())
        second=research.save_fact("NEWCO",self.fact())
        self.assertEqual(first["id"],second["id"])
        original=workspaces.current()
        _, other=workspaces.create()
        context=workspaces._current.set(other["workspace"])
        try:
            self.assertEqual(research.facts("NEWCO"),[])
            research.delete_fact(first["id"])
        finally:
            workspaces._current.reset(context)
        self.assertEqual(len(research.facts("NEWCO")),1)

    def test_unchanged_document_uses_parser_version_cache_without_parsing_again(self):
        with patch("pypdf.PdfReader",side_effect=AssertionError("Unexpected reparse")):
            _, _, message=documents.import_pdf(self.root/'guide.pdf',"NEWCO","transcript","guide","https://issuer.example/guide.pdf","2024-04-18")
        self.assertEqual(message,"already indexed")

    def test_qoq_yoy_match_scope_period_and_positive_baselines(self):
        base={"kind":"actual","metric":"revenue","unit":"INR crore","scope":"consolidated","basis":"INR", "published":"2025-07-01","source":{},"low":"100"}
        rows=[{**base,"period":"Q4 FY25","low":"100"},{**base,"period":"Q1 FY25","low":"90"},{**base,"period":"Q1 FY26","low":"110"}]
        current=research.financials(rows)[-1]
        self.assertEqual(current["qoq"]["percent"],10)
        self.assertAlmostEqual(current["yoy"]["percent"],22.2222)
        rows[0]["low"]="0"
        self.assertIsNone(research.financials(rows)[-1]["qoq"])

    def test_outcome_dated_before_guidance_is_not_comparable(self):
        f={**self.fact(),"id":"g","source":{},"stale":False}
        a={**self.fact("actual"),"id":"a","source":{},"published":"2023-01-01","stale":False}
        self.assertEqual(research.compare([f,a])[0]["position"],"not_comparable")

    def test_candidate_fields_are_drafts_and_questions_stay_questions(self):
        drafted=research.suggest_fields(GUIDANCE)
        self.assertEqual(drafted['period'],'FY25')
        self.assertEqual((drafted['low'],drafted['high']),('5','7'))
        self.assertEqual(drafted['basis'],'constant_currency')
        self.add_document('question','Analyst: Do you expect revenue growth of 9% for FY26?','2025-01-01')
        question=next(c for c in research.candidates('NEWCO') if 'Do you expect' in c['quote'])
        self.assertEqual(question['speaker_kind'],'question')
        self.assertEqual(research.facts('NEWCO'),[])

    def test_conflicting_latest_outcomes_do_not_produce_a_verdict_or_headline(self):
        g={**self.fact(),'id':'guide','source':{},'stale':False}
        a={**self.fact('actual'),'id':'one','source':{},'stale':False}
        b={**a,'id':'two','low':'8','high':'8'}
        self.assertEqual(research.compare([g,a,b])[0]['position'],'not_comparable')
        self.assertEqual(research.financials([a,b]),[])
