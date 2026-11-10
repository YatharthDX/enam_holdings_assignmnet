"""Real HTTP evidence workflow, signed sessions and cross-browser isolation."""
import json
import os
import tempfile
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from unittest.mock import patch

import test_http
from finn import documents, live_store as store
from test_import import make_pdf
from test_research import GUIDANCE, ACTUAL
from finn import acceptance


class FeatureHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_http.HttpTests.setUpClass.__func__(cls)

    def new_client(self):
        client=build_opener(ProxyHandler({}),HTTPCookieProcessor(CookieJar()))
        with client.open(Request(self.base+'/api/session',data=b'{}',method='POST')) as response:
            session=json.load(response)
        client.addheaders=[('X-FINN-CSRF',session['csrf'])]
        return client,session

    def call(self,client,path,value=None,method='GET',headers=None):
        request=Request(self.base+path,data=json.dumps(value).encode() if value is not None else None,
                        method=method,headers={'Content-Type':'application/json',**(headers or {})})
        with client.open(request) as response:
            return json.load(response)

    def test_anonymous_writes_and_missing_csrf_are_rejected(self):
        anonymous=build_opener(ProxyHandler({}))
        with self.assertRaises(HTTPError) as error:
            self.call(anonymous,'/api/alerts/read',{},'POST')
        self.assertEqual(error.exception.code,401)
        client,_=self.new_client()
        with self.assertRaises(HTTPError) as error:
            self.call(client,'/api/alerts/read',{},'POST',{'X-FINN-CSRF':'wrong'})
        self.assertEqual(error.exception.code,403)

    def test_private_note_export_and_portfolio_are_isolated_between_browsers(self):
        first,_=self.new_client();second,_=self.new_client()
        self.call(first,'/api/people/mira/note',{'note':'First browser private fixture','last_contact':'2025-01-01'},'PUT')
        a=self.call(first,'/api/people?q=Mira')['people'][0]
        b=self.call(second,'/api/people?q=Mira')['people'][0]
        self.assertIn('First browser',a['note']);self.assertEqual(b['note'],'')
        self.call(first,'/api/portfolio',{'symbols':['INFY','HCLTECH']},'PUT')
        self.assertEqual(sum(c['holding'] for c in self.call(first,'/api/catalog')['companies']),2)
        self.assertEqual(sum(c['holding'] for c in self.call(second,'/api/catalog')['companies']),16)
        exported=self.call(second,'/api/workspace/export?workspace=other-browser')
        self.assertNotIn('First browser',json.dumps(exported))
        self.assertNotIn('csrf',json.dumps(exported))

    def test_unseeded_ticker_to_reviewed_guidance_works_over_http_without_llm(self):
        first,_=self.new_client();second,_=self.new_client()
        ids=[]
        def discover(symbol,token):
            with tempfile.TemporaryDirectory() as folder:
                for name,body,published in [('guide',GUIDANCE,'2024-04-18'),('actual',ACTUAL,'2025-04-17')]:
                    p=Path(folder)/(name+'.pdf');make_pdf(p,[body])
                    ids.append(documents.import_pdf(p,symbol,'transcript',name,'https://issuer.example/'+name+'.pdf',published)[0])
                with store.connection() as db:
                    db.execute("UPDATE document_jobs SET status='complete',detail='Indexed controlled originals' WHERE symbol=? AND token=?",(symbol,token))
        with patch('finn.app.discovery.run',side_effect=discover),patch('finn.llm.generate') as model:
            self.call(first,'/api/research/FRESHCO/discover',{},'POST')
            import time
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                info=self.call(first,'/api/research/FRESHCO')
                if info['discovery']['status']=='complete':break
                time.sleep(.01)
            self.assertEqual(info['structured']['brief']['documents'],2)
            self.assertIn('copper',info['structured']['brief']['groups'][0]['passages'][0]['text'])
            base={'metric':'revenue_growth','period':'FY25','unit':'%','scope':'consolidated','basis':'constant_currency','speaker':'Management',
                  'speaker_kind':'management','page':1,'reviewed':True}
            self.call(first,'/api/research/FRESHCO/facts',{**base,'kind':'guidance','low':'5','high':'7','source_id':ids[0],'quote':GUIDANCE},'POST')
            self.call(first,'/api/research/FRESHCO/facts',{**base,'kind':'actual','low':'6','high':'6','source_id':ids[1],'quote':ACTUAL},'POST')
            comparison=self.call(first,'/api/research/FRESHCO')['structured']['comparisons'][0]
            self.assertEqual(comparison['position'],'within')
            self.assertEqual(self.call(second,'/api/research/FRESHCO')['structured']['facts'],[])
            self.assertEqual(self.call(first,'/api/research/FRESHCO?as_of=2024-07-01')['structured']['comparisons'][0]['position'],'pending')
            model.assert_not_called()

    def test_workspace_delete_revokes_the_cookie_and_does_not_delete_another_workspace(self):
        first,_=self.new_client();second,_=self.new_client()
        self.call(first,'/api/workspace',method='DELETE')
        self.assertFalse(self.call(first,'/api/session')['authenticated'])
        with self.assertRaises(HTTPError) as error:
            self.call(first,'/api/workspace/export')
        self.assertEqual(error.exception.code,401)
        self.assertTrue(self.call(second,'/api/session')['authenticated'])

    def test_interactive_public_demo_allows_owned_controls_but_never_model_calls(self):
        with patch.dict(os.environ,{'FINN_PUBLIC_DEMO':'1','FINN_INTERACTIVE_DEMO':'1','FINN_ENABLE_LLM':'1','GEMINI_API_KEY':'fixture-never-real'}),patch('finn.llm.post_json') as model:
            client,_=self.new_client()
            self.call(client,'/api/people/mira/note',{'note':'Owned synthetic note','last_contact':None},'PUT')
            self.assertFalse(self.call(client,'/api/llm/status')['enabled'])
            self.assertFalse(self.call(client,'/api/catalog')['runtime']['read_only'])
            with self.assertRaises(HTTPError) as error:
                self.call(client,'/api/research/INFY/analyze',{'lens':'business'},'POST')
            self.assertEqual(error.exception.code,422)
            model.assert_not_called()

    def test_large_content_length_and_chunked_request_bodies_are_bounded(self):
        client,_=self.new_client()
        for body in [b' '*300000,iter([b' '*200000,b' '*100000])]:
            with self.subTest(chunked=not isinstance(body,bytes)):
                request=Request(self.base+'/api/network/import',data=body,method='POST',headers={'Content-Type':'application/json'})
                with self.assertRaises(HTTPError) as error:
                    client.open(request)
                self.assertEqual(error.exception.code,413)

    def test_https_proxy_origin_creates_a_secure_signed_cookie_only_when_trusted(self):
        client=build_opener(ProxyHandler({}))
        request=Request(self.base+'/api/session',data=b'{}',method='POST',headers={'Origin':self.base.replace('http:','https:'),'X-Forwarded-Proto':'https'})
        with patch.dict(os.environ,{'FINN_TRUST_PROXY':'0'}),self.assertRaises(HTTPError) as error:
            client.open(request)
        self.assertEqual(error.exception.code,403)
        with patch.dict(os.environ,{'FINN_TRUST_PROXY':'1'}),client.open(request) as response:
            cookie=response.headers['Set-Cookie']
            self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=lax',cookie)

    def test_acceptance_command_uses_disposable_sessions_and_never_a_model(self):
        with patch('finn.llm.generate') as model:
            report=acceptance.run(self.base)
            self.assertEqual(report['status'],'passed')
            self.assertTrue(report['private_isolation'])
            self.assertEqual(report['generation_requests'],0)
            model.assert_not_called()

    def test_cold_ticker_acceptance_exercises_real_indexer_with_controlled_originals(self):
        from finn import discovery
        real_run=discovery.run
        page=b'<a>NSE: COLDCO</a><h3>Annual reports</h3><ul><li><a href="https://issuer.example/cold.pdf">Annual Report FY2025</a></li></ul>'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'cold.pdf';make_pdf(path,[GUIDANCE])
            original=path.read_bytes()
            def index(symbol,token):
                return real_run(symbol,token,fetch=lambda url:page if 'screener.in' in url else original)
            with patch('finn.app.discovery.run',side_effect=index),patch('finn.llm.generate') as model:
                report=acceptance.run(self.base,ticker='COLDCO',wait_seconds=3)
                self.assertEqual(report['status'],'passed')
                self.assertTrue(report['ticker']['cold_cache'])
                self.assertEqual(report['ticker']['indexed_documents'],1)
                self.assertGreater(report['ticker']['search_matches'],0)
                self.assertEqual(report['ticker']['example']['page'],1)
                with self.assertRaisesRegex(acceptance.AcceptanceError,'already has evidence'):
                    acceptance.run(self.base,ticker='COLDCO',wait_seconds=3)
                model.assert_not_called()

    def test_cached_original_http_is_exact_and_not_a_filesystem_gateway(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'source.pdf';make_pdf(p,['Retained original source document.'])
            doc,_,_=documents.import_pdf(p,'CACHECO','annual_report','Original','https://issuer.example/cache.pdf','2025-01-01')
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            with self.client.open(self.base+'/api/documents/'+doc+'/original?revision='+digest) as response:
                self.assertEqual(response.read(),p.read_bytes())
                self.assertEqual(response.headers.get_content_type(),'application/pdf')
            with self.assertRaises(HTTPError) as error:
                self.client.open(self.base+'/api/documents/'+doc+'/original?revision=../desk.sqlite3')
            self.assertEqual(error.exception.code,404)
