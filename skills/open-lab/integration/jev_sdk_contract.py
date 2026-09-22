#!/usr/bin/env python3
"""Actual pinned SDK with HTTPX MockTransport; sockets are explicitly forbidden."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx2
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy
from importlib.metadata import version
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path[:0]=[str(SCRIPTS),str(SCRIPTS/'tests')]
from test_v3_jev import jev, pair


class SDKContract(unittest.TestCase):
    def test_real_sdk_wire_contract_and_raw_scores(self):
        self.assertEqual(version('typesafe-sdk'),jev.SDK_VERSION)
        observed=[]
        async def handler(request):
            observed.append(request)
            body=json.loads(request.content)
            self.assertEqual(str(request.url),'https://api.typesafe.ai/v1/systemone')
            self.assertEqual(body['model'],'jev-fixture')
            self.assertEqual(set(body['questions']),set(jev.QUESTIONS))
            self.assertEqual(body['state']['FIRST']['id'],'C-a-001')
            return httpx2.Response(200,json={'model':'jev-fixture','usage':{'input_tokens':100,'output_tokens':4},
                'answers':{k:{'type':'noul','noul':.03 if k=='same_claim' else .98} for k in jev.QUESTIONS}},
                headers={'x-request-id':'wire-fixture'})
        factory=lambda:AsyncTypeSafeClient(api_key='not-real',model='jev-fixture',base_url='https://api.typesafe.ai',
            transport=httpx2.MockTransport(handler),retry=RetryPolicy(max_retries=0))
        with patch.dict(os.environ,{'LAB_BOOK_ALLOW_PAID_JEV':'1','TYPESAFE_API_KEY':'not-real'}), \
             patch('socket.socket.connect',side_effect=AssertionError('network forbidden')):
            judge=jev.JevJudge({'enabled':True,'model':'jev-fixture','max_calls':1,'budget_seconds':2},client_factory=factory)
            judge.prepare([pair(1)])
            result=judge(*pair(1))
        self.assertEqual(len(observed),1);self.assertEqual(result['same_claim'],.03)
        self.assertEqual(result.provenance['usage']['input_tokens'],100)
        print(json.dumps({'SDK':version('typesafe-sdk'),'httpx2':version('httpx2'),
                          'calls':len(observed),'transport':'MockTransport','paid_requests':0,'provenance':result.provenance}))

    def test_real_sdk_cannot_turn_wire_boolean_into_probability(self):
        async def handler(request):
            return httpx2.Response(200,json={'model':'jev-fixture','usage':{'input_tokens':1,'output_tokens':1},
                'answers':{k:{'type':'noul','noul':True} for k in jev.QUESTIONS}})
        factory=lambda:AsyncTypeSafeClient(api_key='not-real',transport=httpx2.MockTransport(handler),retry=RetryPolicy(max_retries=0))
        with patch.dict(os.environ,{'LAB_BOOK_ALLOW_PAID_JEV':'1','TYPESAFE_API_KEY':'not-real'}), \
             patch('socket.socket.connect',side_effect=AssertionError('network forbidden')):
            judge=jev.JevJudge({'enabled':True,'model':'jev-fixture','max_calls':1,'budget_seconds':2},client_factory=factory)
            judge.prepare([pair(1)])
            with self.assertRaises(jev.DeferredJev):judge(*pair(1))


if __name__=='__main__':unittest.main(verbosity=2)
