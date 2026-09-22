"""Offline v3 behavioral tests. Model judgments are explicit mocks throughout."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import claims
import rectification as rx
import reservations
import board
from test_run import LabCase, git, CLAIMS


def scores(same=.1, contradiction=.1, forward=.1, backward=.1):
    return dict(zip(rx.FIELDS, (same, contradiction, forward, backward)))


class PolicyTests(unittest.TestCase):
    def test_threshold_boundaries(self):
        self.assertFalse(rx.policy(scores(same=.9))['duplicate'])
        self.assertTrue(rx.policy(scores(same=.9))['adjudication'])
        self.assertTrue(rx.policy(scores(same=.5))['adjudication'])
        self.assertFalse(rx.policy(scores(same=.4999))['adjudication'])
        self.assertTrue(rx.policy(scores(same=.9001))['duplicate'])
        self.assertFalse(rx.policy(scores(contradiction=.7))['contradiction'])
        self.assertTrue(rx.policy(scores(contradiction=.7001))['contradiction'])

    def test_malformed_probabilities_are_not_negative_judgments(self):
        for value in [True, '0.5', -1, 2, math.nan, math.inf, None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                rx.probabilities(scores(same=value))
        with self.assertRaises(ValueError):
            rx.probabilities({'same_claim': .99})

    def test_missing_mock_pair_fails_closed_as_coverage_not_truth(self):
        a = {'id':'C-001','hash':'a'}
        b = {'id':'C-002','hash':'b'}
        self.assertEqual(rx.pair_key(a,b), rx.pair_key(b,a))
        with self.assertRaises(LookupError):
            rx.MockJev({})(a,b)


class RectificationTests(LabCase):
    def setUp(self):
        super().setUp()
        claims.forget_committed()
        self.addCleanup(claims.forget_committed)

    def new(self, text, actor='discoverer'):
        return self.claims_py('new', '--statement', text, '--actor', actor)

    def known(self):
        claims.forget_committed()
        return claims.load(self.problem)[0]

    def compare(self, first, second, raw):
        known=self.known()
        key=rx.pair_key(known[first], known[second])
        fixture=self.root/'responses.json'
        fixture.write_text(json.dumps({key:raw}))
        self.claims_py('compare','--new',second,'--mock-responses',str(fixture))
        return key

    def test_quantity_change_is_not_a_duplicate_and_flags_are_symmetric(self):
        a=self.new('The ring has two generators.')
        b=self.new('The ring has three generators.')
        key=self.compare(a,b,scores(same=.02,contradiction=.99,forward=.03,backward=.04))
        k=self.known()
        self.assertFalse(k[a]['duplicate-candidate-of'])
        self.assertEqual(k[a]['contradictions'][0]['other'],b)
        self.assertEqual(k[b]['contradictions'][0]['other'],a)
        self.assertEqual(k[a]['contradictions'][0]['key'],key)
        self.assertEqual(k[a]['status'],'proposed')
        self.assertEqual(k[b]['status'],'proposed')
        self.assertEqual(k[a]['contradictions'][0]['probabilities'],scores(.02,.99,.03,.04))

    def test_dismissal_survives_rechecks_and_is_specific_to_kind_and_version(self):
        a=self.new('The invariant is two.')
        b=self.new('The invariant is three.')
        key=self.compare(a,b,scores(.95,.99))
        self.claims_py('dismiss',key,'--kind','contradiction','--reason','Different objects.',
                       '--actor','reviewer','--issue','meeting 2026-09-22')
        self.compare(a,b,scores(.95,.99))
        k=self.known()
        self.assertFalse(k[a]['contradictions'])
        self.assertTrue(k[a]['duplicate-candidate-of'])
        self.claims_py('set',b,'conditional','--conditions','Only for object B.','--actor','reviewer')
        self.assertFalse(self.known()[a]['duplicate-candidate-of'])
        new_key=self.compare(a,b,scores(.05,.99))
        self.assertNotEqual(key,new_key)
        self.assertTrue(self.known()[a]['contradictions'])

    def test_terminal_claims_are_excluded_before_calls(self):
        a=self.new('The value is two.')
        b=self.new('The value is three.')
        self.claims_py('set',a,'refuted','--evidence','Explicit counterexample.', '--actor','reviewer')
        judge=Mock(side_effect=AssertionError('must not call for terminal claim'))
        judge.source='mock'
        report=rx.check_new(self.problem,[a,b],judge=judge)
        self.assertEqual(report['compared'],0)
        judge.assert_not_called()

    def test_missing_and_failed_responses_are_visible_deferred_coverage(self):
        a=self.new('The first object is rigid.')
        b=self.new('The second object is rigid.')
        c=self.new('The third object is rigid.')
        k=self.known()
        judge=rx.MockJev({rx.pair_key(k[a],k[c]):scores(.97,.01)})
        report=rx.check_new(self.problem,[c],judge=judge)
        self.assertEqual(report['compared'],1)
        self.assertEqual(report['deferred'],1)
        claims.regenerate(self.problem); claims.commit(self.problem,'mock partial coverage')
        known=self.known()
        self.assertTrue(known[c]['duplicate-candidate-of'])
        self.assertEqual(known[c]['comparison_check']['state'],'deferred')
        self.assertEqual(known[c]['comparison_check']['error'],'LookupError')

    def test_promotion_requires_exact_current_acknowledgment(self):
        a=self.new('The invariant is two.')
        b=self.new('The invariant is three.')
        key=self.compare(a,b,scores(.01,.99))
        rid,_=self.dispatch()
        self.packet(rid, command="python3 -c \"print('CHECK_OK' if 1+2 == 3 else 'BAD')\"")
        self.ok('ingest',rid,'--worker-done')
        args=['set',a,'verified','--actor','reviewer','--evidence',rid,'--rests-on','none']
        rejected=self.script(CLAIMS,*args)
        self.assertEqual(rejected.returncode,2,rejected.stdout+rejected.stderr)
        self.assertIn('--acknowledge-contradictions',rejected.stderr)
        self.assertEqual(self.known()[a]['status'],'proposed')
        self.claims_py(*args,'--acknowledge-contradictions',key)
        k=self.known()
        self.assertEqual(k[a]['status'],'verified')
        self.assertEqual(k[a]['history'][-1]['acknowledged_contradictions'][0]['key'],key)
        self.assertEqual(k[b]['status'],'proposed')

    def test_promotion_rejects_old_acknowledgment_after_statement_or_condition_edit(self):
        a=self.new('The invariant is two.')
        b=self.new('The invariant is three.')
        key=self.compare(a,b,scores(.01,.99))
        rid,_=self.dispatch()
        self.packet(rid,command="python3 -c \"print('CHECK_OK' if 1+2 == 3 else 'BAD')\"")
        self.ok('ingest',rid,'--worker-done')
        page=self.problem/'claims'/(a+'.md')
        original=page.read_text()
        ledger_before=(self.problem/'claims/ledger.jsonl').read_bytes()
        args=['set',a,'verified','--actor','reviewer','--evidence',rid,'--rests-on','none',
              '--acknowledge-contradictions',key]
        page.write_text(original.replace('The invariant is two.','The invariant is four.'))
        response=self.script(CLAIMS,*args)
        self.assertEqual(response.returncode,2,response.stdout+response.stderr)
        self.assertIn('claim version',response.stderr)
        self.assertEqual((self.problem/'claims/ledger.jsonl').read_bytes(),ledger_before)
        page.write_text(original)
        response=self.script(CLAIMS,*args,'--conditions','Only for a different object.')
        self.assertEqual(response.returncode,2,response.stdout+response.stderr)
        self.assertEqual((self.problem/'claims/ledger.jsonl').read_bytes(),ledger_before)
        # Unchanged text remains promotable with its exact current acknowledgment.
        self.claims_py(*args)
        self.assertEqual(self.known()[a]['history'][-1]['acknowledged_contradictions'][0]['key'],key)

    def test_real_canary_dispatch_ingest_with_mock_jev_at_ingest(self):
        a=self.new('The sum of zero through three is six.')
        k=self.known()
        second={'id':'C-002','hash':claims.text_hash('Zero plus one plus two plus three equals six.','')}
        key=rx.pair_key(k[a],second)
        # Fixture outside the worker's fence and credentials outside shared config.
        with tempfile.TemporaryDirectory() as tmp:
            fixture=Path(tmp)/'jev.json'; fixture.write_text(json.dumps({key:scores(.99,.01)}))
            cfg=self.local(); cfg['rectification']={'mock_responses':str(fixture)}; self.write_local(cfg)
            brief=self.brief('Compute sum(range(4)).\n\n## Method\n\nInteger addition.\n\n## Expected claim shape\n\nThe sum is six.')
            rid,_=self.dispatch(brief=brief)
            d=self.dispatch_json(rid)
            self.assertEqual(d['preregistration']['method'],'Integer addition.')
            self.assertIsNone(d['lease'])
            self.packet(rid,command="python3 -c \"print('CHECK_OK' if sum(range(4)) == 6 else 'BAD')\"",
                        ret={'claims_proposed':['Zero plus one plus two plus three equals six.']})
            self.ok('ingest',rid,'--worker-done')
        ing=self.ingest_json(rid)
        self.assertEqual(ing['verdict'],'PASS')
        self.assertTrue(ing['replayed'])
        self.assertEqual(ing['comparison']['source'],'mock')
        self.assertEqual(ing['reservation_outcome']['outcome'],'unreserved')
        self.assertEqual(self.known()[a]['duplicate-candidate-of'][0]['other'],'C-002')
        self.assertEqual(git(self.root,'status','--porcelain').stdout.strip(),'')

    def test_board_escapes_record_and_labels_mock(self):
        a=self.new('<script>alert("x")</script> The invariant is two.')
        b=self.new('The invariant is three.')
        self.compare(a,b,scores(.01,.99))
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            claims.forget_committed()  # Match a fresh board CLI process after the comparison commit.
            specs=board.render_problem(self.problem,out,api=False)
            page=(out/'index.html').read_text()
            self.assertNotIn('<script>alert',page)
            self.assertIn('&lt;script&gt;',page)
            self.assertIn('MOCK',page)
            self.assertIn('In flight',page)
            self.assertEqual(specs,[])  # Mocks never open real issues.


class ReservationBoundaryTests(unittest.TestCase):
    def test_database_error_is_nonblocking_and_does_not_leak_secrets(self):
        with patch('claims.local_config',return_value={'reservations':{'service':'test'}}), \
             patch('subprocess.run',side_effect=OSError('password=secret')):
            result=reservations.rpc(Path('.'),'list_leases',{})
        self.assertFalse(result['available'])
        self.assertNotIn('secret',json.dumps(result))

    def test_libpq_tls_is_forced_and_payload_is_not_sql(self):
        completed=Mock(returncode=0,stdout='{"actor":"alice","reservations":[]}')
        with patch('claims.local_config',return_value={'reservations':{'service':'lab'}}), \
             patch('subprocess.run',return_value=completed) as process:
            reservations.rpc(Path('.'),'list_leases',{'problem':"x'); DROP TABLE t; --"})
        args=process.call_args
        self.assertIn('sslmode=verify-full',args.args[0][args.args[0].index('--dbname')+1])
        self.assertIn(":'payload'",args.kwargs['input'])
        self.assertNotIn('DROP TABLE',args.kwargs['input'])
        self.assertEqual(args.kwargs['timeout'],5)

    def test_late_and_missing_leases_never_reject_results(self):
        with patch('reservations.rpc',return_value={'available':True,'outcome':'unsolicited'}):
            self.assertEqual(reservations.release(Path('.'),{'lease':'id','run':'R-alice-001'})['outcome'],'unsolicited')
        with patch('reservations.rpc',return_value={'available':False,'reason':'offline'}):
            self.assertEqual(reservations.release(Path('.'),{'lease':'id','run':'R-alice-001'})['outcome'],'unavailable')

    def test_worker_does_not_inherit_database_or_judge_credentials(self):
        import run
        source={'PATH':'/bin','PGPASSWORD':'secret','PGSERVICEFILE':'/private/services',
                'JEV_API_KEY':'secret','GITHUB_TOKEN':'secret'}
        self.assertEqual(run.worker_environment({},source),{'PATH':'/bin'})


class IssueTests(unittest.TestCase):
    def test_repeated_pair_updates_do_not_create_duplicate_issues(self):
        key='a'*64
        spec={'key':key,'title':'conflict','body':'<!-- lab-book-pair:%s -->'%key}
        store=[]
        def request(method,path,body=None):
            if method=='GET': return list(store)
            if method=='POST':
                item=dict(body,number=1,state='open'); store.append(item); return item
            raise AssertionError((method,path,body))
        board.sync_issues('owner/repo',[spec,spec],request)
        board.sync_issues('owner/repo',[spec],request)
        self.assertEqual(len(store),1)

    def test_issue_refresh_preserves_human_text_outside_bot_summary(self):
        key='b'*64
        old='<!-- lab-book-pair:'+key+' -->old<!-- /lab-book-pair -->\n'
        fresh='<!-- lab-book-pair:'+key+' -->new<!-- /lab-book-pair -->\n'
        item={'number':7,'title':'old','body':old+'Human ruling in progress.','state':'closed'}
        updates=[]
        def request(method,path,body=None):
            if method=='GET': return [item]
            self.assertEqual(method,'PATCH'); updates.append(body); return dict(item,**body)
        board.sync_issues('owner/repo',[{'key':key,'title':'new','body':fresh}],request)
        self.assertEqual(updates,[{'title':'new','body':fresh+'Human ruling in progress.','state':'open'}])


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.known = {cid: {'id': cid, 'hash': cid, 'status': 'proposed'}
                      for cid in ('C-001', 'C-002')}
        self.pair = list(self.known.values())
        self.event = {'event': 'comparison', 'key': rx.pair_key(*self.pair),
                      'pair': [dict(c) for c in self.pair],
                      'probabilities': scores(), 'source': 'mock'}

    def test_current_coverage_not_historical_attempt_counts(self):
        attempt = {'event': 'check', 'id': 'C-001', 'state': 'complete', 'compared': 0}
        coverage = rx.current_coverage(self.known, [attempt])
        self.assertEqual(coverage['C-001']['deferred'], 1)
        self.assertEqual(attempt['state'], 'complete')
        self.known['C-002']['status'] = 'superseded'
        coverage = rx.current_coverage(self.known, [attempt])
        self.assertEqual(coverage['C-001']['deferred'], 0)
        self.assertEqual(coverage['C-002']['state'], 'excluded')

    def test_negative_and_dismissed_judgments_still_cover_pair(self):
        dismissal = {'event': 'dismiss', 'key': self.event['key'], 'kind': 'contradiction'}
        coverage = rx.current_coverage(self.known, [self.event, self.event, dismissal])
        for c in coverage.values():
            self.assertEqual((c['peers'], c['compared'], c['deferred'], c['mock']), (1, 1, 0, 1))

    def test_changed_version_and_new_peer_need_fresh_coverage(self):
        self.known['C-003'] = {'id': 'C-003', 'hash': 'fresh', 'status': 'proposed'}
        coverage = rx.current_coverage(self.known, [self.event])
        self.assertEqual(coverage['C-001']['deferred'], 1)
        self.assertEqual(coverage['C-003']['deferred'], 2)
        self.known['C-002']['hash'] = 'changed'
        self.assertEqual(rx.current_coverage(self.known, [self.event])['C-001']['deferred'], 2)

    def test_unknown_peer_cannot_fill_current_coverage(self):
        other = {'id': 'C-unseen-001', 'hash': 'unseen', 'status': 'proposed'}
        event = dict(self.event, pair=[self.pair[0], other], key=rx.pair_key(self.pair[0], other))
        self.assertEqual(rx.current_coverage(self.known, [event])['C-001']['compared'], 0)

    def test_corrupt_comparison_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            rx.current_coverage(self.known, [dict(self.event, key='forged')])
