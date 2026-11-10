"""Privacy, expiry, consent and independent alert state without external services."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from finn import live, live_store as store, network, workspaces


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": folder.name, "FINN_PUBLIC_DEMO": "0", "FINN_SESSION_SECRET": ""})
        env.start()
        self.addCleanup(env.stop)
        context = workspaces._current.set(None)
        self.addCleanup(workspaces._current.reset, context)

    def open(self, **kwargs):
        token, session = workspaces.create(**kwargs)
        return token, session["workspace"]

    def enter(self, wid):
        workspaces._current.set(wid)

    def test_signed_cookie_rejects_tampering_and_expiry(self):
        token, wid = self.open(now=1000)
        self.assertEqual(workspaces.identify(token, now=1001)["workspace"], wid)
        self.assertIsNone(workspaces.identify(token[:-1] + ("0" if token[-1] != "0" else "1"), now=1001))
        self.assertIsNone(workspaces.identify(token, now=1000 + workspaces.TTL))
        self.assertIsNone(workspaces.identify("../../unsafe", now=1001))

    def test_first_local_workspace_adopts_legacy_settings_and_seen_alerts_once(self):
        with store.connection() as db:
            settings = store.settings(db)
            settings["price_pct"] = 8.5
            db.execute("UPDATE alert_settings SET body=?", (json.dumps(settings),))
            db.execute("INSERT INTO live_alerts VALUES('legacy','2026-01-01','2026-01-01',?,1)", (json.dumps({"title":"Legacy signal"}),))
        _, first = self.open()
        _, second = self.open()
        self.enter(first)
        with store.connection() as db:
            self.assertEqual(workspaces.settings(db)["price_pct"], 8.5)
            self.assertTrue(workspaces.alerts(db)[0]["seen"])
        self.enter(second)
        with store.connection() as db:
            self.assertEqual(workspaces.settings(db)["price_pct"], 5.0)
            self.assertFalse(workspaces.alerts(db))

    def test_private_notes_profiles_and_deletions_do_not_cross_workspaces(self):
        _, first = self.open()
        _, second = self.open()
        self.enter(first)
        network.save_note("mira", "Private first-workspace note", "2025-01-01")
        self.assertIn("Private first-workspace", json.dumps(network.people("Mira")))
        self.enter(second)
        self.assertNotIn("Private first-workspace", json.dumps(network.people("Mira")))
        network.delete_person("mira")
        self.assertFalse(network.people("Mira"))
        self.enter(first)
        self.assertTrue(network.people("Mira"))

    def test_per_workspace_thresholds_and_seen_state_are_independent(self):
        _, first = self.open()
        _, second = self.open()
        now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        with store.connection() as db:
            store.put_bars(db, [{"symbol":"INFY","day":"2026-11-09","close":100,"volume":100,"split":False},
                                {"symbol":"INFY","day":"2026-11-10","close":105,"volume":100,"split":False}], "2026-11-10")
        for wid, threshold in [(first, 5), (second, 10)]:
            self.enter(wid)
            live.update_settings({"enabled":True,"price_pct":threshold,"volume_multiple":100,"categories":[]}, now)
        self.enter(first)
        with store.connection() as db:
            self.assertEqual(len(workspaces.alerts(db)), 1)
            workspaces.mark_read(db)
            live.evaluate(db, now)
            self.assertTrue(workspaces.alerts(db)[0]["seen"])
        self.enter(second)
        with store.connection() as db:
            self.assertEqual(workspaces.alerts(db), [])

    def test_ambiguous_name_never_produces_an_introduction(self):
        _, wid = self.open()
        self.enter(wid)
        profile = {"id":"mira-namesake","name":"Mira Shah","role":"Delivery lead","employer":"INFY",
                   "tenure":"2019–2023","topics":["IT delivery"]}
        network.import_bundle({"synthetic":True,"people":[profile],"edges":[["investor","mira-namesake"]]})
        result = network.resolve("Mira Shah", "INFY", "Delivery lead", "2022-01-01")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["person"])
        self.assertEqual(network.resolve("Mira Shah", "", "", "")["status"], "unresolved")

    def test_real_profiles_require_consent_and_expired_consent_is_purged(self):
        now = datetime(2030, 1, 1, 8, tzinfo=timezone.utc).timestamp()
        _, wid = self.open(now=now)
        self.enter(wid)
        p = {"id":"permissioned","name":"Permissioned example","role":"Lead","employer":"NEWCO",
             "tenure":"2020–2030","topics":["Operations"]}
        with self.assertRaisesRegex(ValueError, "consent"):
            network.import_bundle({"people":[p]})
        p["consent"] = {"granted":True,"purpose":"investment research","expires":"2030-01-01","source":"Explicit opt-in fixture"}
        network.import_bundle({"people":[p],"edges":[["investor","permissioned"]]})
        with store.connection() as db:
            workspaces.expire(db, now + 17 * 3600)
            self.assertIsNotNone(db.execute("SELECT id FROM workspaces WHERE id=?", (wid,)).fetchone())
            self.assertIsNone(db.execute("SELECT id FROM workspace_people WHERE workspace=? AND id='permissioned'", (wid,)).fetchone())

    def test_public_import_rejects_real_profiles_and_source_work_is_capped(self):
        _, wid = self.open()
        self.enter(wid)
        with patch.dict(os.environ, {"FINN_PUBLIC_DEMO":"1"}):
            with self.assertRaisesRegex(ValueError, "fictional"):
                network.import_bundle({"people":[{"id":"not-fictional"}]})
            workspaces.consume("refresh", public_limit=1)
            with self.assertRaisesRegex(ValueError, "limit"):
                workspaces.consume("refresh", public_limit=1)

    def test_workspace_export_excludes_credentials_and_delete_cascades(self):
        token, wid = self.open()
        self.enter(wid)
        network.save_note("mira", "An owned note", "2025-01-01")
        exported = json.dumps(workspaces.export_data())
        self.assertIn("An owned note", exported)
        self.assertNotIn(token, exported)
        self.assertNotIn("csrf", exported)
        workspaces.delete()
        self.assertIsNone(workspaces.identify(token))
        with store.connection() as db:
            for table in ["workspace_people","workspace_edges","workspace_notes","workspace_alerts","reviewed_facts"]:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM " + table + " WHERE workspace=?", (wid,)).fetchone()[0], 0)

    def test_expiry_removes_private_rows_but_keeps_public_sources(self):
        token, wid = self.open(now=1000)
        with store.connection() as db:
            db.execute("INSERT INTO source_state VALUES('nse','now','now','ok','Public data','https://example.com','range')")
            workspaces.expire(db, now=1000 + workspaces.TTL + 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM workspace_sessions").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM source_state").fetchone()[0], 1)
