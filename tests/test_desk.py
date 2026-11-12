import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from finn import desk


class DeskTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": temp.name})
        env.start()
        self.addCleanup(env.stop)

    def test_portfolio_and_off_portfolio_samples(self):
        self.assertEqual(sum(c["holding"] for c in desk.all_companies()), 16)
        for symbol in ["LTTS", "SRF", "HAVELLS"]:
            result = desk.research(symbol)
            self.assertFalse(result["company"]["holding"])
            self.assertIn(result["snapshot"]["source"]["id"], desk.SOURCES)
            self.assertIsNone(result["comparison"])
            self.assertTrue(result["people"])

    def test_default_window_and_priority(self):
        brief = desk.brief()
        self.assertEqual(brief["start"], date(2025, 4, 17))
        self.assertEqual([r["symbol"] for r in brief["rows"]], ["INFY", "TATAPOWER"])
        self.assertEqual([r["priority"] for r in brief["rows"]], ["Material", "Routine"])

    def test_seven_days_and_custom_boundaries(self):
        self.assertEqual(len(desk.brief("7d")["rows"]), 4)
        brief = desk.brief("custom", date(2025, 3, 14), date(2025, 3, 14))
        self.assertEqual([r["source"]["id"] for r in brief["rows"]], ["infy-notice"])
        self.assertFalse(desk.brief("custom", date(2024, 1, 1), date(2024, 1, 2))["rows"])
        with self.assertRaises(ValueError):
            desk.brief("custom", date(2025, 4, 18), date(2025, 4, 18))

    def test_four_guidance_ranges_and_same_basis_actual(self):
        series = desk.comparison("INFY")
        self.assertEqual(series["actual"]["value"], 4.2)
        self.assertEqual([r["position"] for r in series["forecasts"]],
                         ["above", "above", "within", "below"])
        self.assertEqual([r["points"] for r in series["forecasts"]], [1.2, 0.2, 0.0, 0.3])
        self.assertTrue(all(r["source"]["page"] > 0 for r in series["forecasts"]))

    def test_comparison_boundaries(self):
        for actual in [4.5, 5.0]:
            self.assertEqual(desk.distance(actual, 4.5, 5), {"position": "within", "points": 0})
        with self.assertRaises(ValueError):
            desk.distance(4, 5, 3)

    def test_direct_and_recorded_two_hop_connections(self):
        contacts = desk.people(symbol="INFY")
        self.assertEqual(contacts[0]["path"], ["You", "Mira Shah"])
        self.assertEqual(contacts[1]["path"], ["You", "Mira Shah", "Tara Bose"])
        self.assertEqual(contacts[2]["reason"], "Worked at Tata Consultancy Services, a competitor of Infosys")
        self.assertTrue(all(p["fictional"] for p in contacts))

    def test_direct_queries_match_only_relevant_people(self):
        self.assertEqual([p["name"] for p in desk.people("Who in my network worked at SRF?")], ["Leela Nair", "Suresh Pillai"])
        self.assertEqual(len(desk.people("IT delivery")), 3)
        self.assertFalse(desk.people("aviation"))
        self.assertEqual(len(desk.people()), len(desk.NETWORK["people"]))

    def test_search_limits_research_to_primary_documents(self):
        result = desk.research("infy", "constant currency")
        self.assertTrue(result["matches"])
        self.assertEqual({s["kind"] for s in result["sources"]}, {"Earnings call", "Annual report"})
        self.assertTrue(all(m["excerpt"] and m["url"].startswith("https://") for m in result["matches"]))
        self.assertFalse(desk.research("INFY", "unobtainium")["matches"])

    def test_unknown_symbol_is_explicitly_uncovered(self):
        result = desk.research("M&M")
        self.assertEqual(result["company"]["symbol"], "M&M")
        self.assertFalse(result["sources"])
        self.assertIsNone(result["snapshot"])
        self.assertIsNone(result["comparison"])
        with self.assertRaises(ValueError):
            desk.research("../etc")


if __name__ == "__main__":
    unittest.main()
