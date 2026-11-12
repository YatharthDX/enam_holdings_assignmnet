"""XBRL results cards, filing classification, appointee profiles and network ties."""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from finn import guidance, live, live_store as store, network, people_filings, results, snapshot, workspaces


def instance(end, values, start=None, extra_context=True):
    """A minimal Ind-AS XBRL instance with one quarterly whole-entity context."""
    start = start or {3: "01-01", 6: "04-01", 9: "07-01", 12: "10-01"}[int(end[5:7])]
    start = end[:4] + "-" + start if len(start) == 5 else start
    facts = "".join(f'<in-capmkt:{tag} contextRef="OneD" unitRef="INR" decimals="-5">{value}</in-capmkt:{tag}>'
                    for tag, value in values.items())
    segment = ('<xbrli:context id="OneSeg"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
               '<xbrli:segment><x>m</x></xbrli:segment></xbrli:entity><xbrli:period>'
               f'<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>'
               '<in-capmkt:RevenueFromOperations contextRef="OneSeg">1</in-capmkt:RevenueFromOperations>') if extra_context else ""
    return (f'<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
            f'xmlns:in-capmkt="urn:capmkt"><xbrli:context id="OneD"><xbrli:entity><xbrli:identifier scheme="x">1'
            f'</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate>'
            f'<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>{segment}{facts}</xbrli:xbrl>').encode()


def industrial(revenue, pbt, finance=10, dep=20, other=5, pat=None):
    crore = 10_000_000
    return {"RevenueFromOperations": revenue * crore, "ProfitBeforeTax": pbt * crore, "FinanceCosts": finance * crore,
            "DepreciationDepletionAndAmortisationExpense": dep * crore, "OtherIncome": other * crore,
            "ProfitLossForPeriod": (pat or pbt * 3 // 4) * crore}


class ResultsCardTests(unittest.TestCase):
    def quarters(self, values_by_end):
        parsed = {}
        for end, values in values_by_end.items():
            period_end, values, _ = results.parse_instance(instance(end, values))
            parsed[period_end] = {"values": values, "meta": {"scope": "Consolidated", "published": end + "T12:00:00+00:00",
                                                             "url": "https://nsearchives.nseindia.com/x.html"}}
        return parsed

    def test_fiscal_labels_follow_the_indian_year(self):
        self.assertEqual(results.fiscal_label(date(2026, 9, 30)), "Q2 FY27")
        self.assertEqual(results.fiscal_label(date(2026, 3, 31)), "Q4 FY26")
        self.assertEqual(results.shift_quarter(date(2026, 9, 30), 4), date(2025, 9, 30))
        self.assertEqual(results.shift_quarter(date(2026, 3, 31), 1), date(2025, 12, 31))

    def test_segment_contexts_are_ignored_and_ebitda_is_computed(self):
        end, values, _ = results.parse_instance(instance("2026-09-30", industrial(1000, 200)))
        self.assertEqual(end, date(2026, 9, 30))
        self.assertEqual(values["RevenueFromOperations"], Decimal(1000 * 10_000_000))
        line = results.headline(values, "industrial")
        self.assertEqual(line["core"], Decimal((200 + 10 + 20 - 5) * 10_000_000))

    def test_card_reports_qoq_yoy_and_margin_pp(self):
        card = results.build_card("TEST", self.quarters({
            "2025-09-30": industrial(800, 150), "2026-06-30": industrial(950, 190), "2026-09-30": industrial(1000, 200)}))
        rows = {r["key"]: r for r in card["rows"]}
        self.assertEqual(card["quarter"], "Q2 FY27")
        self.assertEqual(rows["revenue"]["value_cr"], 1000.0)
        self.assertEqual(rows["revenue"]["yoy"], 25.0)
        self.assertEqual(rows["revenue"]["qoq"], 5.26)
        self.assertEqual(card["compared"], {"qoq": "Q1 FY27", "yoy": "Q2 FY26"})
        self.assertEqual(card["margin"]["value"], 22.5)
        self.assertIsNotNone(card["margin"]["yoy_pp"])

    def test_missing_baseline_gives_no_change_rather_than_a_guess(self):
        card = results.build_card("TEST", self.quarters({"2026-09-30": industrial(1000, 200)}))
        self.assertTrue(all(r["qoq"] is None and r["yoy"] is None for r in card["rows"]))
        self.assertEqual(card["compared"], {"qoq": None, "yoy": None})

    def test_banks_show_net_interest_income_instead_of_ebitda(self):
        crore = 10_000_000
        bank = {"Income": 500 * crore, "InterestEarned": 400 * crore, "InterestExpended": 250 * crore,
                "ProfitLossFromOrdinaryActivitiesBeforeTax": 90 * crore, "ProfitLossForThePeriod": 70 * crore}
        card = results.build_card("BANK", self.quarters({"2026-09-30": bank}))
        self.assertEqual(card["kind"], "bank")
        self.assertEqual(card["rows"][1]["label"], "Net interest income")
        self.assertEqual(card["rows"][1]["value_cr"], 150.0)
        self.assertIsNone(card["margin"])

    def test_negative_base_does_not_produce_growth(self):
        self.assertIsNone(results.change(Decimal(10), Decimal(-5)))

    def test_entity_declarations_are_rejected(self):
        with self.assertRaises(Exception):
            results.parse_instance(b'<!DOCTYPE x [<!ENTITY a "b">]><x/>')


class ClassifierTests(unittest.TestCase):
    CASES = [
        ("Outcome of Board Meeting", "Infosys Limited has submitted to the Exchange, Financial Results for the quarter ended September 30, 2026", "results", "Material"),
        ("Analysts/Institutional Investor Meet/Con. Call Updates", "Havells India Limited has informed the Exchange about Schedule of meet", "investor_meetings", "Routine"),
        ("General Updates", "HDFC Bank Limited has informed the Exchange regarding disclosure under Regulation 30 - Change in Managing Director and Chief Executive Officer of the Bank", "management_change", "Material"),
        ("Appointment", "Tata Power Company Limited has informed the Exchange regarding Appointment of Mr X as additional Executive Director", "management_change", "Material"),
        ("Appointment", "The Federal Bank Limited has informed the Exchange regarding Appointment of Mr X as Independent Director", "management_change", "Other"),
        ("Other Restructuring", "Blue Star Limited has informed the Exchange about Voluntary strike off of a step down subsidiary", "M&A", "Other"),
        ("Corporate Insolvency Resolution Process", "Polycab India Limited has informed the Exchange about the order passed by NCLAT", "litigation", "Material"),
        ("Strikes/Lockouts/Disturbances", "Havells India Limited has informed the Exchange about strikes/lockouts/disturbances", "disruption", "Material"),
        ("News Verification", "The Exchange has sought clarification with respect to a news item on an acquisition", "press_release", "Other"),
        ("General Updates", "The Federal Bank Limited has informed the Exchange about Allotment of Equity Shares on exercise of Stock options", "compliance", "Routine"),
        ("Capacity addition", "SRF Limited has informed the Exchange about Capacity addition", "capex", "Material"),
        ("Disclosure of encumbrance", "Promoter has created a pledge on shares", "pledging", "Material"),
        ("Record Date", "Bonus issue of equity shares in the ratio 1:1", "bonus_split", "Other"),
        ("Credit Rating", "CARE has revised the outlook to negative", "credit_rating", "Material"),
    ]

    def test_real_exchange_subjects_map_to_the_reference_taxonomy(self):
        for title, details, category, priority in self.CASES:
            with self.subTest(title=title, details=details[:50]):
                got = live.classify(title, details)
                self.assertEqual((got[0], got[2]), (category, priority))


FILING_TEXT = """Sub: Disclosure under Regulation 30. The Board approved the appointment of Mr. Ravi Kumar Iyer
(DIN: 01234567) as the Chief Financial Officer of the Company with effect from November 1, 2026, in place of
Mr. Suresh Menon who has resigned. Particulars 1. Reason for change: Appointment 3. Brief profile (in case of appointment)
Mr. Ravi Kumar Iyer is a finance leader with 25 years of experience. He joined Infosys Limited in 2012 and later served as
Finance Controller at Acme Widgets Limited. He holds an MBA from Indian Institute of Management, Ahmedabad and is a
Chartered Accountant. 4. Disclosure of relationships between directors: Not applicable. Yours faithfully,
For Example Limited Ms. Priya Rao Company Secretary"""


class AppointmentTests(unittest.TestCase):
    def test_brief_profile_yields_career_education_and_direction(self):
        people = {p["name"]: p for p in people_filings.extract({"details": ""}, FILING_TEXT)}
        incoming = people["Ravi Kumar Iyer"]
        self.assertEqual(incoming["change"], "appointment")
        self.assertEqual(incoming["role"], "Chief Financial Officer")
        self.assertIn(("Infosys Limited", "2012"), [(o["name"], o["since"]) for o in incoming["organisations"]])
        self.assertIn("Acme Widgets Limited", [o["name"] for o in incoming["organisations"]])
        self.assertIn("Indian Institute of Management, Ahmedabad", incoming["education"])
        self.assertIn("Chartered Accountant", incoming["degrees"])
        self.assertEqual(people["Suresh Menon"]["change"], "cessation")
        self.assertNotIn("Priya Rao", people)

    def test_name_variants_merge_and_pointer_sentences_are_not_profiles(self):
        text = ("Appointment of Mr. Sanjay Banga as Additional Director. Mr. Sanjay Kumar Banga is appointed w.e.f. today. "
                "Brief profile (in case of appointment) is enclosed herewith as Annexure A.")
        people = people_filings.extract({"details": ""}, text)
        self.assertEqual([p["name"] for p in people], ["Sanjay Kumar Banga"])
        self.assertEqual(people[0]["profile"], "")

    def test_role_words_are_trimmed_from_organisations(self):
        orgs = people_filings.organisations("He is Chief Executive Officer of Tata Power Renewable Energy Limited and earlier "
                                            "worked with Reliance Energy since 1996.")
        self.assertEqual([(o["name"], o["since"]) for o in orgs],
                         [("Tata Power Renewable Energy Limited", None), ("Reliance Energy", "1996")])


class TiesTests(unittest.TestCase):
    def setUp(self):
        token = workspaces._current.set("public")
        self.addCleanup(workspaces._current.reset, token)

    def test_same_org_needs_a_whole_word_prefix_of_two_words(self):
        self.assertTrue(network.same_org("Infosys", "Infosys Limited"))
        self.assertTrue(network.same_org("Tata Power", "Tata Power Delhi Distribution Limited"))
        self.assertFalse(network.same_org("Tata Power", "Tata Motors"))
        self.assertFalse(network.same_org("ICICI", "ICICI Bank"))

    def test_dated_overlap_outranks_an_unconfirmed_shared_employer(self):
        person = {"name": "Ravi Kumar Iyer", "organisations": [{"name": "Infosys Limited", "since": "2012"}], "education": []}
        found = network.ties(person)
        self.assertTrue(found)
        self.assertEqual(found[0]["tie"]["strength"], "strong")
        self.assertIn("overlapped", found[0]["reason"])
        undated = network.ties({**person, "organisations": [{"name": "Infosys Limited", "since": None}]})
        self.assertEqual(undated[0]["tie"]["strength"], "likely")

    def test_group_names_cover_group_companies_and_link_strength_is_reported(self):
        self.assertTrue(network.same_org("ICICI Group", "ICICI Bank"))
        self.assertFalse(network.same_org("ICICI Group", "Kotak Mahindra Bank"))
        person = {"name": "Incoming Banker", "organisations": [{"name": "ICICI Group", "since": "1992"}],
                  "education": ["Indian Institute of Management, Bangalore"]}
        found = network.ties(person)
        names = [p["name"] for p in found]
        self.assertIn("Asha Das", names)
        asha = found[names.index("Asha Das")]
        self.assertEqual(asha["tie"]["strength"], "strong")
        self.assertEqual(asha["link"], "close")
        self.assertIn("You also studied at Indian Institute of Management, Bangalore.", network.own_ties(person))

    def test_two_hop_paths_prefer_the_strongest_weakest_link(self):
        profiles = {"a": {}, "b": {}, "c": {}}
        edges = [["investor", "a", 1], ["investor", "b", 3], ["a", "c", 3], ["b", "c", 2]]
        self.assertEqual(network.paths(profiles, edges)["c"], ["investor", "b", "c"])

    def test_competitors_and_suppliers_are_explained(self):
        reasons = {p["name"]: p["reason"] for p in network.people(symbol="POLYCAB")}
        self.assertEqual(reasons["Ritu Agarwal"], "Worked at KEI Industries, a competitor of Polycab India")

    def test_seeded_last_contact_drives_reconnect_on_a_former_employer(self):
        prompts = network.reconnect("TATAPOWER", "2026-11-11T13:00:00+00:00")
        self.assertIn("Priya Natarajan", [p["person"]["name"] for p in prompts])

    def test_no_shared_history_means_no_tie(self):
        self.assertEqual(network.ties({"name": "Nobody", "organisations": [{"name": "Unrelated Mills Limited", "since": None}],
                                       "education": ["Nowhere College"]}), [])


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": folder.name, "FINN_AUTO_REFRESH": "0"})
        env.start()
        self.addCleanup(env.stop)
        token = workspaces._current.set("public")
        self.addCleanup(workspaces._current.reset, token)

    def test_snapshot_anchors_windows_until_a_newer_live_fetch(self):
        filing = {"id": "nse-x", "provider_id": "1", "symbol": "INFY", "title": "Outcome of Board Meeting",
                  "details": "Infosys Limited has submitted to the Exchange, Financial Results for the quarter",
                  "url": "https://nsearchives.nseindia.com/corporate/x.pdf", "published": "2026-10-23T10:00:00+00:00",
                  "provider": "NSE"}
        path = self.folder / "snap.json"
        path.write_text(json.dumps({"taken_at": "2026-10-24T00:00:00+00:00", "days": 30, "filings": [filing],
                                    "bars": {}, "results": {}, "appointments": []}))
        with store.connection() as db:
            self.assertEqual(snapshot.load(db, path), "2026-10-24T00:00:00+00:00")
        later = datetime(2026, 12, 1, tzinfo=timezone.utc)
        with patch("finn.live.clock", return_value=later):
            brief = live.snapshot("24h")
            self.assertEqual(brief["snapshot_at"], "2026-10-24T00:00:00+00:00")
            self.assertEqual([r["id"] for r in brief["rows"]], ["nse-x"])
            with store.connection() as db:
                store.state(db, "nse", "2026-11-30T00:00:00+00:00", "ok", "", "https://x", "range")
            self.assertIsNone(live.snapshot("24h")["snapshot_at"])
            self.assertEqual(live.snapshot("24h")["rows"], [])

    def test_missing_snapshot_is_harmless(self):
        with store.connection() as db:
            self.assertIsNone(snapshot.load(db, self.folder / "absent.json"))


if __name__ == "__main__":
    unittest.main()


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": folder.name, "FINN_AUTO_REFRESH": "0", "FINN_ENABLE_LLM": "0"})
        env.start()
        self.addCleanup(env.stop)

    def card(self, quarters):
        crore = 10_000_000
        history = [{"quarter": q, "period_end": "", "revenue": r, "core": None, "pbt": pbt, "pat": pbt * 0.75,
                    "ebit": ebit, "tax": pbt * 0.25} for q, r, ebit, pbt in quarters]
        return {"history": history, "kind": "industrial", "scope": "Consolidated"}

    def test_call_dates_resolve_relative_periods(self):
        self.assertEqual(guidance.call_quarter("2026-10"), (2, 27))
        self.assertEqual(guidance.call_quarter("2026-04"), (4, 26))
        self.assertEqual(guidance.normal_period("for the year", "2026-10"), ("FY27", True))
        self.assertEqual(guidance.normal_period("for the year", "2026-04"), ("FY27", True))
        self.assertEqual(guidance.normal_period("financial year '27", "2026-04"), ("FY27", False))
        self.assertEqual(guidance.normal_period("next quarter", "2026-10"), ("Q3 FY27", True))
        self.assertEqual(guidance.normal_period("over the next 5 years", "2026-10"), ("multi-year", True))

    def test_rules_keep_promises_and_drop_questions_results_and_deltas(self):
        text = ("Jayesh, a quick word on your guidance of 0% to 3%. Our revenue growth in 9 months stood at 2.8%, "
                "at the top of guidance. That impacted our guidance by 2%. "
                "Our operating margin guidance remains at 20% to 22% for the year.")
        found = guidance.rule_statements([{"page": 1, "text": text}])
        self.assertEqual([(f["metric"], f["low"], f["high"]) for f in found], [("ebit_margin", 20.0, 22.0)])

    def test_verification_rejects_paraphrase_and_rescaled_numbers(self):
        passage = "We expect EBIT margin of 16% to 17% for FY27."
        statement = {"quote": passage, "low": 16, "high": 17, "speaker": "management", "metric": "ebit_margin",
                     "period_text": "FY27", "unit": "%", "basis": "not_stated", "kind": "guidance"}
        self.assertEqual(guidance.verify(statement, passage, {}, "2026-10", "rules")["period"], "FY27")
        self.assertIsNone(guidance.verify({**statement, "low": 0.16, "high": 0.17}, passage, {}, "2026-10", "rules"))
        self.assertIsNone(guidance.verify({**statement, "quote": "We expect a margin of 16%-17%."}, passage, {}, "2026-10", "rules"))
        self.assertIsNone(guidance.verify({**statement, "speaker": "analyst"}, passage, {}, "2026-10", "rules"))

    def test_verdicts_score_full_years_track_open_years_and_refuse_other_bases(self):
        card = self.card([("Q1 FY26", 100, 15, 16), ("Q2 FY26", 100, 15, 16), ("Q3 FY26", 100, 15, 16), ("Q4 FY26", 100, 15, 16),
                          ("Q1 FY27", 110, 20, 21), ("Q2 FY27", 110, 20, 21)])
        item = {"metric": "ebit_margin", "period": "FY26", "low": "16", "high": "17", "basis": "not_stated", "kind": "guidance"}
        self.assertEqual(guidance.verdict(item, card)["status"], "below")
        self.assertEqual(guidance.verdict({**item, "period": "FY27"}, card)["status"], "tracking_above")
        growth = {**item, "metric": "revenue_growth", "period": "FY27", "low": "8", "high": "12"}
        self.assertEqual(guidance.verdict(growth, card)["status"], "tracking_within")
        self.assertEqual(guidance.verdict({**growth, "basis": "constant_currency"}, card)["status"], "different_basis")
        self.assertEqual(guidance.verdict({**item, "period": "Q4 FY27"}, card)["status"], "due_later")

    def test_repeated_promises_group_and_revisions_chain(self):
        def said(month, low, high):
            return {"metric": "revenue_growth", "label": "Revenue growth", "period": "FY27", "period_inferred": False,
                    "low": low, "high": high, "unit": "%", "basis": "constant_currency", "kind": "guidance",
                    "quote": "guidance " + low + "% to " + high + "%", "call_month": month, "method": "rules",
                    "source": {"id": "x", "title": "call", "url": "https://x"}}
        with store.connection() as db:
            guidance.store_items(db, {"TEST": [said("2026-04", "1.5", "3.5"), said("2026-07", "1.5", "3"),
                                               said("2026-10", "1", "2"), said("2026-10", "1", "2")]})
        tracked = guidance.track("TEST")
        self.assertEqual([(r["item"]["low"], r["item"]["high"]) for r in tracked["rows"]], [("1", "2")])
        chain = tracked["revisions"][0]
        self.assertEqual(chain["direction"], "lowered")
        self.assertEqual([(s["low"], s["high"]) for s in chain["steps"]], [("1.5", "3.5"), ("1.5", "3"), ("1", "2")])
