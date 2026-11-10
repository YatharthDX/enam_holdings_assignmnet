"""Document provenance, update triggers, revisions and temporal comparisons."""
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from finn import discovery, documents, live, live_store as store, network, providers, research, workspaces
from test_import import make_pdf


class PipelineCompletionTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        env=patch.dict(os.environ,{'FINN_DATA_DIR':str(self.root/'db'),'FINN_PUBLIC_DEMO':'0','FINN_AUTO_REFRESH':'0'})
        env.start();self.addCleanup(env.stop)
        context=workspaces._current.set(None);self.addCleanup(workspaces._current.reset,context)

    def test_cached_pdf_bytes_match_digest_and_old_revision_survives_a_replacement(self):
        p=self.root/'original.pdf';make_pdf(p,['First primary original report.'])
        first=p.read_bytes();first_hash=hashlib.sha256(first).hexdigest()
        doc_id,_,_=documents.import_pdf(p,'NEWCO','annual_report','Original','https://issuer.example/original.pdf','2025-01-01')
        path,_=documents.cached_original(doc_id,first_hash)
        self.assertEqual(path.read_bytes(),first)
        make_pdf(p,['Second primary original report.'])
        documents.import_pdf(p,'NEWCO','annual_report','Original','https://issuer.example/original.pdf','2025-01-01')
        self.assertEqual(documents.cached_original(doc_id,first_hash)[0].read_bytes(),first)
        self.assertIsNone(documents.cached_original(doc_id,'0'*64))
        with self.assertRaises(ValueError):documents.original_path('../escape')

    def test_bad_replacement_retains_previous_text_and_original(self):
        p=self.root/'original.pdf';make_pdf(p,['Retained issuer statement.'])
        doc_id,_,_=documents.import_pdf(p,'NEWCO','annual_report','Original','https://issuer.example/original.pdf','2025-01-01')
        saved=documents.cached_original(doc_id)[0].read_bytes()
        p.write_bytes(b'not a PDF')
        with self.assertRaises(Exception):documents.import_pdf(p,'NEWCO','annual_report','Original','https://issuer.example/original.pdf','2025-01-01')
        self.assertEqual(documents.cached_original(doc_id)[0].read_bytes(),saved)
        self.assertIn('Retained',documents.for_symbol('NEWCO',True)[1][0]['body'])

    def test_same_attachment_preserves_metadata_versions_and_exact_duplicates_keep_all_links(self):
        first=providers.normal_filing('INFY','Financial results','Published results','https://nsearchives.nseindia.com/a.pdf','2026-11-10T10:00:00Z')
        amended={**first,'details':'Amended published results'}
        with store.connection() as db:
            store.put_filings(db,[first]);store.put_filings(db,[amended]);store.put_filings(db,[amended])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM filing_versions').fetchone()[0],2)
        two={**first,'id':'another-attachment','url':'https://nsearchives.nseindia.com/b.pdf'}
        rows=[{**r,'source':live.source_of(r)} for r in [first,two,amended]]
        groups=live.group_filings(rows)
        self.assertEqual(len(groups),2)
        self.assertEqual(groups[0]['other_sources'][0]['url'],two['url'])

    def test_new_material_filings_and_changed_revisions_refresh_tracked_documents_once(self):
        now=datetime(2026,11,10,12,tzinfo=timezone.utc)
        with store.connection() as db:
            db.execute("INSERT INTO document_jobs VALUES('INFY','old','complete','2025','2025','2025','old','[]')")
        filing=providers.normal_filing('INFY','Financial results','Results','https://nsearchives.nseindia.com/result.pdf','2026-11-10T10:00:00Z')
        def upstream(*args):return {'rows':[filing],'warning':'','skipped':0,'url':providers.NSE_PAGE,'coverage':'range'}
        def prices(symbol,now):return [{'symbol':symbol,'day':'2026-11-09','close':100,'volume':100,'split':False}]
        def finish(symbol,token):
            with store.connection() as db:db.execute("UPDATE document_jobs SET status='complete' WHERE symbol=? AND token=?",(symbol,token))
        with patch('finn.discovery.run',side_effect=finish) as run:
            live.refresh(now,filing_fetch=upstream,price_fetch=prices,force_prices=True)
            live.refresh(now,filing_fetch=upstream,price_fetch=prices,force_prices=True)
            self.assertEqual(run.call_count,1)
            filing['details']='Revised results'
            live.refresh(now,filing_fetch=upstream,price_fetch=prices,force_prices=True)
            self.assertEqual(run.call_count,2)

    def test_stale_document_worker_never_contacts_an_upstream(self):
        old=discovery.begin('NEWCO')
        with store.connection() as db:db.execute("UPDATE document_jobs SET token='replacement' WHERE symbol='NEWCO'")
        with patch('finn.discovery.discover_links') as fetch:
            discovery.run('NEWCO',old)
            fetch.assert_not_called()

    def test_disposable_acceptance_workspace_does_not_claim_legacy_preferences(self):
        with store.connection() as db:
            legacy=store.settings(db);legacy['price_pct']=9
            db.execute('UPDATE alert_settings SET body=?',(json.dumps(legacy),))
        _,temporary=workspaces.create(adopt_legacy=False)
        context=workspaces._current.set(temporary['workspace'])
        try:workspaces.delete()
        finally:workspaces._current.reset(context)
        _,owner=workspaces.create()
        context=workspaces._current.set(owner['workspace'])
        try:
            with store.connection() as db:self.assertEqual(workspaces.settings(db)['price_pct'],9)
        finally:workspaces._current.reset(context)

    def test_percentage_metrics_use_points_and_amounts_use_relative_changes(self):
        base={'kind':'actual','metric':'operating_margin','unit':'%','scope':'consolidated','basis':'INR','published':'2025-07-01','source':{}}
        rows=[{**base,'period':'Q4 FY25','low':'3'},{**base,'period':'Q1 FY26','low':'4'}]
        delta=research.financials(rows)[-1]['qoq']
        self.assertEqual(delta['percent'],1);self.assertEqual(delta['unit'],'pp')

    def test_appointment_enrichment_needs_corroborated_role_tenure_and_identity(self):
        _,session=workspaces.create();context=workspaces._current.set(session['workspace'])
        try:
            p={'id':'exec','name':'Nina Rao','role':'Chief Financial Officer','employer':'INFY','tenure':'2020–2026','topics':['Finance']}
            network.import_bundle({'synthetic':True,'people':[p],'edges':[['investor','exec']]})
            filing={'symbol':'INFY','title':'Appointment of Ms. Nina Rao as CFO','details':'','published':'2026-01-01T12:00:00Z'}
            self.assertEqual(network.incoming_person(filing)['status'],'matched')
            p['id']='namesake';network.import_bundle({'synthetic':True,'people':[p],'edges':[['investor','namesake']]})
            self.assertEqual(network.incoming_person(filing)['status'],'ambiguous')
            self.assertIsNone(network.incoming_person({**filing,'title':'Resignation of CFO'})['person'])
        finally:workspaces._current.reset(context)
