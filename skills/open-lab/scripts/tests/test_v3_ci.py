"""Native two-clone publication tests; no network model calls or fake Git."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_federation import FederationCase, git
import claims
import rectification

ASSETS = Path(__file__).resolve().parents[2] / 'assets' / 'v3'
spec = importlib.util.spec_from_file_location('lab_ci', ASSETS / 'ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.current = {cid: {'hash': cid, 'status': 'proposed'} for cid in ('C-001', 'C-002')}

    def test_first_install_is_not_all_pairs_backfill(self):
        self.assertEqual(ci.plan(self.current, None), [])
        self.assertEqual(ci.plan(self.current, None, ['C-002']), ['C-002'])

    def test_interrupted_and_deferred_work_is_retried(self):
        saved = {'versions': {'C-001': 'C-001'}, 'pending': {'C-001': 'C-001'}}
        self.assertEqual(ci.plan(self.current, saved), ['C-001', 'C-002'])
        self.current['C-001']['status'] = 'refuted'
        self.assertEqual(ci.plan(self.current, saved), ['C-002'])

    def test_explicit_retry_does_not_require_a_text_edit(self):
        saved = {'versions': {cid: c['hash'] for cid, c in self.current.items()}}
        self.assertEqual(ci.plan(self.current, saved, retry=['C-002']), ['C-002'])

    def test_publication_allowlist_excludes_status_and_other_streams(self):
        tag = ci.publisher('lab/alice'); path = 'v3/ci-state/' + tag + '.json'
        for p in (path, 'problems/demo/CLAIMS.md', 'problems/demo/claims/rectification-' + tag + '.jsonl'):
            self.assertTrue(ci.allowed_path(p, tag, path), p)
        for p in ('lab.json', 'problems/demo/claims/ledger-alice.jsonl', 'problems/demo/STATUS.md',
                  'problems/demo/claims/rectification-bob.jsonl', '.github/workflows/untrusted.yml'):
            self.assertFalse(ci.allowed_path(p, tag, path), p)
        self.assertNotEqual(ci.publisher('lab/alice'), ci.publisher('lab/bob'))

    def test_workflow_serializes_all_branches_and_retains_failure_evidence(self):
        text = (ASSETS / 'lab-ci.yml').read_text()
        self.assertIn('group: lab-v3-publication', text)
        self.assertNotIn('group: lab-v3-${{ github.ref }}', text)
        self.assertIn('queue: max', text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('if: always()', text)
        self.assertIn('if: success()', text)
        self.assertNotIn('pull_request_target', text)


class PublicationTests(FederationCase):
    def setUp(self):
        super().setUp()
        self.join(self.alice); self.join(self.bob)
        self.output = self.tmp / 'published'

    def publish(self, clone=None, **kw):
        claims.forget_committed()
        return ci.publish(clone or self.alice, self.output, **kw)

    def claim(self, clone, text):
        r = self.claims_ok(clone, 'new', '--statement', text, '--actor', clone.name)
        return next(line for line in r.stdout.splitlines() if line.startswith('C-') and ' ' not in line)

    def test_checkpoint_catches_skipped_event_and_peer_branch(self):
        self.publish()
        first = self.claim(self.alice, 'The invariant of X is two.')
        git(self.alice, 'push', '-q', 'origin', 'lab/alice')
        last_parent = git(self.alice, 'rev-parse', 'HEAD').stdout.strip()
        second = self.claim(self.alice, 'The invariant of Y is three.')
        peer = self.claim(self.bob, 'The invariant of Z is four.')
        git(self.bob, 'push', '-q', 'origin', 'lab/bob')
        git(self.alice, 'push', '-q', 'origin', 'lab/alice')
        git(self.alice, 'fetch', '-q', 'origin')
        ledger = self.problem(self.alice) / 'claims' / 'ledger-alice.jsonl'
        before_bytes = ledger.read_bytes()
        # A colleague's newer/equal clock must not hide this invocation's deferral.
        with patch.object(claims, 'now', return_value='2000-01-01T00:00:00Z'):
            self.publish(before=last_parent)
        path = 'v3/ci-state/' + ci.publisher('lab/alice') + '.json'
        pending = json.loads(git(self.remote, 'show', ci.PUBLICATION_BRANCH + ':' + path).stdout)['problems']['problems/demo']['pending']
        self.assertFalse((self.alice / path).exists())
        self.assertEqual(set(pending), {first, second, peer})
        self.assertEqual(ledger.read_bytes(), before_bytes)
        self.assertEqual(git(self.alice, 'status', '--porcelain').stdout, '')
        self.assertTrue((self.output / 'demo/record.json').exists())
        manifest = json.loads((self.output / 'publication.json').read_text())
        self.assertIn('origin/lab/bob', manifest['visible_refs'])
        self.assertEqual(manifest['source'], git(self.alice, 'rev-parse', 'HEAD').stdout.strip())
        self.assertEqual(manifest['published'], git(self.remote, 'rev-parse', ci.PUBLICATION_BRANCH).stdout.strip())

    def test_refuses_dirty_source_before_any_publication(self):
        head = git(self.alice, 'rev-parse', 'HEAD').stdout
        (self.alice / 'human.txt').write_text('Uncommitted work')
        with self.assertRaises(ci.PublicationError): self.publish()
        self.assertEqual(git(self.alice, 'rev-parse', 'HEAD').stdout, head)
        self.assertFalse(self.output.exists())

    def test_unknown_retry_is_not_a_successful_empty_check(self):
        with self.assertRaises(ci.PublicationError): self.publish(retry=['C-missing-001'])
        self.assertFalse(self.output.exists())

    def test_concurrent_source_push_is_preserved_and_fresh_retry_completes(self):
        self.publish()
        cid = self.claim(self.alice, 'Two plus two equals four.')
        git(self.alice, 'push', '-q', 'origin', 'lab/alice')
        real = ci.git
        advanced = []
        def race(root, *args, **kw):
            if args[0] == 'push' and not advanced:
                other = self.clone('parallel', 'Alice')
                git(other, 'checkout', '-q', 'lab/alice')
                (other / 'human.txt').write_text('Concurrent investigator work')
                git(other, 'add', '--', 'human.txt'); git(other, 'commit', '-qm', 'concurrent work')
                git(other, 'push', '-q', 'origin', 'lab/alice')
                advanced.append(git(other, 'rev-parse', 'HEAD').stdout.strip())
            return real(root, *args, **kw)
        with patch.object(ci, 'git', side_effect=race):
            manifest = self.publish()
        self.assertEqual(manifest['publication'], 'pushed')
        self.assertEqual(manifest['published'], git(self.remote, 'rev-parse', ci.PUBLICATION_BRANCH).stdout.strip())
        remote = git(self.remote, 'rev-parse', 'lab/alice').stdout.strip()
        self.assertEqual(remote, advanced[0])
        fresh = self.clone('retry', 'CI')
        git(fresh, 'checkout', '-q', 'lab/alice')
        self.publish(fresh)
        self.assertEqual((fresh / 'human.txt').read_text(), 'Concurrent investigator work')
        self.assertTrue(git(fresh, 'show', 'HEAD:problems/demo/claims/ledger-alice.jsonl').stdout.find(cid) >= 0)
        self.assertEqual(git(fresh, 'status', '--porcelain').stdout, '')

    def test_ci_wins_between_two_real_investigator_cycles_without_divergence(self):
        first = self.work(self.alice, name='first.md')
        source = git(self.alice, 'rev-parse', 'HEAD').stdout.strip()
        publisher = self.clone('publisher', 'CI')
        git(publisher, 'checkout', '-q', 'lab/alice')
        manifest = self.publish(publisher)
        self.assertEqual(git(self.remote, 'rev-parse', 'lab/alice').stdout.strip(), source)
        self.assertEqual(git(publisher, 'rev-parse', 'HEAD').stdout.strip(), source)
        self.assertEqual(git(publisher, 'status', '--porcelain').stdout, '')
        rid, _ = self.dispatch(self.alice, name='second.md')
        self.packet(self.alice, rid)
        response = self.ok(self.alice, 'ingest', rid)
        self.assertNotIn('Not pushed to origin', response.stdout)
        record = json.loads(git(self.remote, 'show', 'lab/alice:problems/demo/runs/' + rid + '/ingest.json').stdout)
        self.assertEqual(record['verdict'], 'PASS')
        self.assertTrue(record['replayed'])
        self.assertEqual(git(self.alice, 'rev-parse', 'HEAD').stdout.strip(),
                         git(self.remote, 'rev-parse', 'lab/alice').stdout.strip())
        paths = git(self.remote, 'ls-tree', '-r', '--name-only', ci.PUBLICATION_BRANCH).stdout.splitlines()
        self.assertTrue(paths)
        self.assertFalse(any('/runs/' in p or '/ledger' in p or p.endswith('.py') for p in paths))
        print('CI_WINS: two real cycles reached origin; source unchanged by publisher')

    def test_competing_automation_push_fails_without_overwriting_either_writer(self):
        self.publish()
        source = git(self.alice, 'rev-parse', 'HEAD').stdout.strip()
        real = ci.git
        advanced = []
        def race(root, *args, **kw):
            if args[0] == 'push' and not advanced:
                other = self.clone('other-publisher', 'CI')
                git(other, 'checkout', '-q', ci.PUBLICATION_BRANCH)
                path = other / 'v3/ci-state' / (ci.publisher('lab/bob') + '.json')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'version':1, 'branch':'lab/bob', 'problems':{}}))
                git(other, 'add', '--', str(path)); git(other, 'commit', '-qm', 'other publisher')
                git(other, 'push', '-q', 'origin', ci.PUBLICATION_BRANCH)
                advanced.append(git(other, 'rev-parse', 'HEAD').stdout.strip())
            return real(root, *args, **kw)
        with patch.object(ci, 'git', side_effect=race):
            with self.assertRaises(ci.PublicationError):
                self.publish(retry=[self.claim_for_retry()])
        self.assertEqual(git(self.remote, 'rev-parse', ci.PUBLICATION_BRANCH).stdout.strip(), advanced[0])
        self.assertEqual(git(self.alice, 'status', '--porcelain').stdout, '')
        result = self.publish()
        self.assertEqual(git(self.remote, 'merge-base', advanced[0], result['published']).stdout.strip(), advanced[0])

    def claim_for_retry(self):
        cid = self.claim(self.alice, 'The sum of one and one is two.')
        git(self.alice, 'push', '-q', 'origin', 'lab/alice')
        return cid

    def test_fetched_advisory_flags_are_visible_without_merging_or_status_writes(self):
        a = self.claim(self.alice, 'The invariant is two.')
        b = self.claim(self.bob, 'The invariant is three.')
        for clone, branch in ((self.alice,'lab/alice'), (self.bob,'lab/bob')):
            git(clone,'push','-q','origin',branch)
        publisher = self.clone('publisher','CI')
        git(publisher,'checkout','-q','lab/alice')
        claims.forget_committed()
        known = claims.load(self.problem(publisher), include_remote=True)[0]
        key = rectification.pair_key(known[a],known[b])
        judge = rectification.MockJev({key: {'same_claim':.01,'contradictory':.99,
                  'first_entails_second':.01,'second_entails_first':.01}})
        with patch.object(rectification,'configured_judge',return_value=judge):
            result=self.publish(publisher,retry=[a])
        git(self.alice,'fetch','-q','origin')
        claims.forget_committed()
        known=claims.load(self.problem(self.alice), include_remote=True)[0]
        self.assertEqual(known[a]['contradictions'][0]['key'],key)
        self.assertEqual(known[b]['contradictions'][0]['key'],key)
        self.assertEqual(known[a]['status'],'proposed')
        self.assertFalse(list((self.problem(self.alice)/'claims').glob('rectification-automation-ci-*')))


if __name__ == '__main__':
    unittest.main()
