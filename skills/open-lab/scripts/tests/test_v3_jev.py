"""Paid calls forbidden: async provider doubles test caps and policy integration."""
import asyncio
import importlib.util
import json
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import rectification as rx
ASSET = Path(__file__).resolve().parents[2] / 'assets/v3/jev.py'
spec=importlib.util.spec_from_file_location('jev',ASSET); jev=importlib.util.module_from_spec(spec); spec.loader.exec_module(jev)


def pair(n):
    return ({'id':'C-a-001','hash':'a','statement':'X equals six.','conditions':''},
            {'id':'C-b-%03d'%n,'hash':str(n),'statement':'Y equals seven.','conditions':''})


class Provider:
    def __init__(self, delay=.001, error=None):
        self.delay=delay; self.error=error; self.calls=[]; self.active=0; self.peak=0; self.closed=False
    async def __aenter__(self): return self
    async def __aexit__(self,*_): self.closed=True
    async def system_one(self, **kw):
        self.calls.append(kw); self.active+=1; self.peak=max(self.peak,self.active)
        try:
            await asyncio.sleep(self.delay)
            if self.error: raise self.error
            return SimpleNamespace(answers={k:{} for k in jev.QUESTIONS},
                nouls={k:SimpleNamespace(noul=.03 if k=='same_claim' else .98) for k in jev.QUESTIONS},
                usage=SimpleNamespace(model_dump=lambda:{'input_tokens':100,'output_tokens':4}),
                model='jev-fixture',request_id='fixture-request',
                raw_http_response=SimpleNamespace(json=lambda:{'answers':{k:{'type':'noul','noul':.03 if k=='same_claim' else .98} for k in jev.QUESTIONS}}))
        finally: self.active-=1


class JevTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict('os.environ',{'LAB_BOOK_ALLOW_PAID_JEV':'1','TYPESAFE_API_KEY':'not-a-real-key'});self.env.start();self.addCleanup(self.env.stop)
        self.config={'enabled':True,'model':'jev-fixture','max_calls':5,'budget_seconds':2,'concurrency':2,'max_retries':0}

    def judge(self, provider=None, **limits):
        provider=provider or Provider()
        return jev.JevJudge(dict(self.config,**limits),client_factory=lambda:provider),provider

    def test_both_optins_required_before_a_client_is_constructed(self):
        with patch.dict('os.environ',{'LAB_BOOK_ALLOW_PAID_JEV':'0'}):
            with self.assertRaises(ValueError): self.judge()
        with self.assertRaises(ValueError): self.judge(enabled=False)
        with patch.dict('os.environ',{'TYPESAFE_API_KEY':''}):
            with self.assertRaises(ValueError): self.judge()

    def test_no_implicit_model_or_unbounded_budget(self):
        for limits in ({'model':'jev-latest'},{'max_calls':0},{'concurrency':11},{'max_calls':1.5},{'budget_seconds':float('inf')}):
            with self.subTest(limits=limits):
                with self.assertRaises(ValueError): self.judge(**limits)

    def test_concurrency_call_cap_and_closed_client(self):
        judge,p=self.judge(); pairs=[pair(n) for n in range(10)];judge.prepare(pairs)
        self.assertEqual(len(p.calls),5);self.assertLessEqual(p.peak,2);self.assertEqual(p.active,0);self.assertTrue(p.closed)
        successes=sum(not isinstance(judge.results[rx.pair_key(*x)],Exception) for x in pairs)
        self.assertEqual(successes,5)
        with self.assertRaises(jev.DeferredJev):judge(*pairs[-1])

    def test_deadline_cancels_and_drains_requests(self):
        judge,p=self.judge(Provider(delay=10),budget_seconds=.02)
        start=time.monotonic();judge.prepare([pair(n) for n in range(10)])
        self.assertLess(time.monotonic()-start,1);self.assertEqual(p.active,0);self.assertTrue(p.closed)
        with self.assertRaises(jev.DeferredJev):judge(*pair(1))

    def test_retry_attempts_share_the_same_cap(self):
        error=type('TypeSafeRateLimitError',(Exception,),{})('secret message')
        judge,p=self.judge(Provider(error=error),max_calls=3,max_retries=2)
        judge.prepare([pair(1),pair(2)]);self.assertEqual(len(p.calls),3)
        self.assertNotIn('secret',repr(judge.results))

    def test_raw_scores_and_request_provenance(self):
        judge,p=self.judge();judge.prepare([pair(1)]);scores=judge(*pair(1))
        self.assertEqual(scores['same_claim'],.03);self.assertEqual(scores.provenance['template_sha256'],jev.TEMPLATE)
        self.assertEqual(scores.provenance['request_id'],'fixture-request')
        self.assertNotEqual(judge.source,'mock');self.assertIn('jev-fixture',judge.source)
        self.assertEqual(set(p.calls[0]['questions']),set(rx.FIELDS))
        self.assertEqual(p.calls[0]['state']['FIRST']['id'],'C-a-001')

    def test_oversized_claim_never_calls_the_provider(self):
        judge,p=self.judge(); a,b=pair(1);a['statement']='x'*17000;judge.prepare([(a,b)])
        self.assertEqual(p.calls,[])
        with self.assertRaises(jev.DeferredJev):judge(a,b)

    def test_missing_sdk_or_transport_keeps_pairs_deferred(self):
        judge,_=self.judge();judge.factory=lambda:(_ for _ in ()).throw(ImportError('not installed'))
        judge.prepare([pair(1)])
        with self.assertRaises(jev.DeferredJev):judge(*pair(1))

    def test_configured_judge_shares_budget_across_checks(self):
        import tempfile
        import claims
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'lab.local.json').write_text(json.dumps({'rectification':{'live':self.config}}))
            a=rx.configured_judge(root); b=rx.configured_judge(root)
            self.assertIs(a,b)
            with patch.dict('os.environ',{'LAB_BOOK_ALLOW_PAID_JEV':'0'}):
                with self.assertRaises(ValueError):rx.configured_judge(root)
            (root/'lab.local.json').write_text(json.dumps({'rectification':{'live':self.config,'mock_responses':'fixture.json'}}))
            with self.assertRaises(ValueError):rx.configured_judge(root)


from test_run import LabCase
import claims


class LedgerAdapterTests(LabCase):
    def test_prepared_responses_replace_mock_cache_and_retain_provenance(self):
        claims.forget_committed();self.addCleanup(claims.forget_committed)
        a=self.claims_py('new','--statement','X is six.','--actor','a')
        b=self.claims_py('new','--statement','X is seven.','--actor','b')
        claims.forget_committed();known=claims.load(self.problem)[0]
        key=rx.pair_key(known[a],known[b])
        rx.check_new(self.problem,[a],judge=rx.MockJev({key:dict(zip(rx.FIELDS,[.99,.01,.01,.01]))}))
        claims.regenerate(self.problem);claims.commit(self.problem,'fixture mock comparison')
        p=Provider()
        with patch.dict('os.environ',{'LAB_BOOK_ALLOW_PAID_JEV':'1','TYPESAFE_API_KEY':'not-real'}):
            judge=jev.JevJudge({'enabled':True,'model':'jev-fixture','max_calls':1,'budget_seconds':3},client_factory=lambda:p)
            result=rx.check_new(self.problem,[a,b],judge=judge)
            self.assertEqual(len(p.calls),1)
            claims.regenerate(self.problem);claims.commit(self.problem,'fixture adapter transport; no live call')
            claims.forget_committed();current=claims.load(self.problem)[0]
            self.assertEqual(current[a]['status'],'proposed')
            self.assertEqual(current[b]['status'],'proposed')
            self.assertTrue(current[a]['contradictions']);self.assertFalse(current[a]['duplicate-candidate-of'])
            record=[e for e in rx.records(self.problem) if e['event']=='comparison' and e['source']==judge.source][0]
            self.assertEqual(record['provenance']['request_id'],'fixture-request')
            rx.check_new(self.problem,[a],judge=judge)
            self.assertEqual(len(p.calls),1)


if __name__=='__main__':unittest.main()
