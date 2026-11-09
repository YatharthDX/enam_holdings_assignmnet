import json
import os
import tempfile
import unittest
from datetime import datetime, time, timedelta, timezone
from unittest.mock import patch

from finn import desk, live, live_store as store, providers

NOW = datetime(2026, 11, 9, 13, 0, tzinfo=timezone.utc)


def bar_series(symbol="INFY", close=105, volume=300):
    first = NOW.astimezone(providers.IST).date() - timedelta(days=20)
    return [{"symbol": symbol, "day": (first + timedelta(days=i)).isoformat(),
             "close": close if i == 20 else 100.0, "volume": volume if i == 20 else 100.0,
             "split": False} for i in range(21)]


def filing_payload():
    return [{
        "symbol": "INFY", "desc": "Financial Results",
        "attchmntText": "Integration test fixture for financial results",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/fixture.pdf",
        "an_dt": "09-Nov-2026 12:00:00", "seq_id": "fixture"
    }]


class LiveTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": folder.name, "FINN_AUTO_REFRESH": "0"})
        env.start()
        self.addCleanup(env.stop)

    def fetch_filings(self, companies, start, end):
        rows, skipped = providers.parse_announcements(filing_payload(), companies)
        return {"rows": rows, "skipped": skipped, "warning": "", "coverage": "range",
                "url": providers.NSE_PAGE}

    def test_signal_boundaries_exclude_current_volume_from_baseline(self):
        value = live.signal(bar_series())
        self.assertAlmostEqual(value["price_change"], 5.0)
        self.assertEqual(value["volume_ratio"], 3.0)
        self.assertEqual(value["baseline_sessions"], 20)
        self.assertIsNone(live.signal(bar_series()[:10])["volume_ratio"])
        self.assertTrue(live.price_due(providers.iso(NOW), NOW, "2026-11-06"))
        self.assertFalse(live.price_due(providers.iso(NOW), NOW, "2026-11-09"))

    def test_splits_and_missing_data_cannot_raise_false_volume_signals(self):
        rows = bar_series()
        rows[-1]["split"] = True
        result = live.signal(rows)
        self.assertIsNone(result["price_change"])
        self.assertIsNone(result["volume_ratio"])
        rows[-1]["split"] = False
        rows[5]["volume"] = None
        self.assertIsNone(live.signal(rows)["volume_ratio"])
        rows[-1]["close"] = None
        self.assertIsNone(live.signal(rows)["price_change"])

    def test_refresh_retry_keeps_one_alert_per_event_and_seen_state(self):
        holdings = {s: {**c, "holding": s == "INFY"} for s, c in desk.COMPANIES.items()}
        with patch.dict(desk.COMPANIES, holdings, clear=True):
            for _ in range(2):
                result = live.refresh(NOW, self.fetch_filings, lambda symbol, now: bar_series(symbol),
                                      force_prices=True)
                self.assertEqual(result["status"], "complete")
            with store.connection() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM live_filings").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM live_alerts").fetchone()[0], 3)
                db.execute("UPDATE live_alerts SET seen=1")
            live.refresh(NOW, self.fetch_filings, lambda symbol, now: bar_series(symbol), force_prices=True)
            with store.connection() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM live_alerts WHERE seen=0").fetchone()[0], 0)
                alert = db.execute("SELECT event_at FROM live_alerts WHERE id LIKE 'price-%'").fetchone()
                self.assertTrue(alert[0].startswith("2026-11-09T"))

    def test_exact_price_threshold_alerts_but_exact_volume_threshold_does_not(self):
        preferences = {**store.DEFAULT_SETTINGS, "categories": [], "price_pct": 5.0, "volume_multiple": 3.0}
        with store.connection() as db:
            store.put_bars(db, bar_series(), providers.iso(NOW))
            db.execute("UPDATE alert_settings SET body=? WHERE id=1", (json.dumps(preferences),))
            live.evaluate(db, NOW)
            kinds = [a["kind"] for a in store.alerts(db)]
        self.assertEqual(kinds, ["price"])

    def test_disabled_rules_produce_no_new_alerts(self):
        with store.connection() as db:
            store.put_bars(db, bar_series(), providers.iso(NOW))
        live.update_settings({**store.DEFAULT_SETTINGS, "enabled": False}, NOW)
        with store.connection() as db:
            self.assertFalse(store.alerts(db))

    def test_failed_refresh_preserves_cache_and_exposes_source_errors(self):
        def fail(*args):
            raise providers.SourceError("Connection unavailable")
        with patch.dict(desk.COMPANIES, {s: {**c, "holding": s == "INFY"} for s, c in desk.COMPANIES.items()}, clear=True):
            live.refresh(NOW, self.fetch_filings, lambda symbol, now: bar_series(symbol))
            result = live.refresh(NOW, fail, fail, force_prices=True)
            self.assertEqual(result["status"], "partial")
            snapshot = live.snapshot("24h", now=NOW)
            self.assertEqual(len(snapshot["rows"]), 1)
            self.assertEqual(snapshot["quotes"][0]["close"], 105)
            self.assertTrue(all(s["status"] == "error" for s in snapshot["sources"]))
            self.assertTrue(all(s["success"] for s in snapshot["sources"]))
            self.assertIsNone(snapshot["comparison"])

    def test_rolling_window_uses_source_time_in_ist(self):
        rows, _ = providers.parse_announcements(filing_payload(), desk.COMPANIES)
        with store.connection() as db:
            store.put_filings(db, rows)
        self.assertEqual(providers.timestamp("09-Nov-2026 12:00:00").hour, 6)
        self.assertTrue(live.snapshot("24h", now=NOW)["rows"])
        self.assertFalse(live.snapshot("24h", now=NOW + timedelta(days=2))["rows"])

    def test_running_refresh_prevents_a_second_fetch(self):
        with store.connection() as db:
            db.execute("INSERT INTO refresh_job VALUES(1,'owner','running',?,NULL,?,'')",
                       (providers.iso(NOW), providers.iso(NOW + timedelta(minutes=5))))
        result = live.refresh(NOW, lambda *a: self.fail("Must not fetch while locked"))
        self.assertEqual(result["status"], "running")

    def test_classification_places_notices_below_substantive_results(self):
        self.assertEqual(live.classify("Board Meeting Intimation", "Financial results")[0], "notice")
        self.assertEqual(live.classify("Appointment of statutory auditor")[0], "compliance")
        self.assertEqual(live.classify("Financial results")[2], "Material")

    def test_partial_feed_never_reports_complete_coverage(self):
        def partial(companies, start, end):
            data = self.fetch_filings(companies, start, end)
            return {**data, "coverage": "partial", "warning": "Only the latest RSS items are available."}
        with patch.dict(desk.COMPANIES, {s: {**c, "holding": s == "INFY"} for s, c in desk.COMPANIES.items()}, clear=True):
            self.assertEqual(live.refresh(NOW, partial, lambda s, n: bar_series(s))["status"], "partial")


class ProviderTests(unittest.TestCase):
    def test_daily_chart_rejects_open_session_and_wrong_currency(self):
        def stamp(day):
            return int(datetime.combine(day, time(9, 15), providers.IST).timestamp())
        today = NOW.astimezone(providers.IST).date()
        payload = {"chart": {"result": [{
            "meta": {"symbol": "INFY.NS", "currency": "INR"},
            "timestamp": [stamp(today - timedelta(days=1)), stamp(today)],
            "indicators": {"quote": [{"close": [100, 105], "volume": [100, 300]}]}
        }], "error": None}}
        before_close = datetime.combine(today, time(14), providers.IST)
        self.assertEqual(len(providers.parse_chart(payload, "INFY", before_close)), 1)
        self.assertEqual(len(providers.parse_chart(payload, "INFY", NOW)), 2)
        evening_close = datetime.combine(today, time(19), providers.IST)
        payload["chart"]["result"][0]["meta"]["currentTradingPeriod"] = {
            "regular": {"end": evening_close.timestamp()}
        }
        self.assertEqual(len(providers.parse_chart(payload, "INFY", NOW)), 1)
        payload["chart"]["result"][0]["meta"]["currency"] = "USD"
        with self.assertRaises(providers.SourceError):
            providers.parse_chart(payload, "INFY", NOW)

    def test_rss_preserves_time_and_matches_issuer(self):
        feed = b"""<rss><channel><item><title>Infosys Limited</title>
        <description>Financial results</description><link>https://nsearchives.nseindia.com/corporate/x.pdf</link>
        <pubDate>Mon, 09 Nov 2026 12:00:00 +0530</pubDate></item></channel></rss>"""
        rows, skipped = providers.parse_rss(feed, desk.COMPANIES)
        self.assertEqual(rows[0]["symbol"], "INFY")
        self.assertEqual(skipped, 0)
        with self.assertRaises(providers.SourceError):
            providers.parse_rss(b"<!DOCTYPE rss><rss><channel/></rss>", desk.COMPANIES)

    def test_bad_portfolio_record_is_flagged_and_unknown_issuer_is_ignored(self):
        bad = {**filing_payload()[0], "an_dt": ""}
        foreign = {**filing_payload()[0], "symbol": "OTHER"}
        rows, skipped = providers.parse_announcements([bad, foreign], desk.COMPANIES)
        self.assertFalse(rows)
        self.assertEqual(skipped, 1)

    def test_official_csv_import_uses_same_event_identity(self):
        payload = filing_payload()[0]
        csv = ("SYMBOL,SUBJECT,DETAILS,ATTACHMENT,BROADCAST DATE/TIME\n"
               "INFY,Financial Results,Fixture,https://nsearchives.nseindia.com/corporate/fixture.pdf,"
               "09-Nov-2026 12:00:00\n")
        rows, skipped = providers.parse_csv(csv.encode(), desk.COMPANIES)
        expected, _ = providers.parse_announcements([payload], desk.COMPANIES)
        self.assertEqual(rows[0]["id"], expected[0]["id"])
        self.assertEqual(skipped, 0)


if __name__ == "__main__":
    unittest.main()
