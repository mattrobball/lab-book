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
        self.publish(before=last_parent)
        path = self.alice / 'v3/ci-state' / (ci.publisher('lab/alice') + '.json')
        pending = json.loads(path.read_text())['problems']['problems/demo']['pending']
        self.assertEqual(set(pending), {first, second, peer})
        self.assertEqual(ledger.read_bytes(), before_bytes)
        self.assertEqual(git(self.alice, 'status', '--porcelain').stdout, '')
        self.assertTrue((self.output / 'demo/record.json').exists())
        manifest = json.loads((self.output / 'publication.json').read_text())
        self.assertIn('origin/lab/bob', manifest['visible_refs'])
        self.assertEqual(manifest['published'], git(self.alice, 'rev-parse', 'HEAD').stdout.strip())

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
            with self.assertRaises(ci.PublicationError): self.publish()
        remote = git(self.remote, 'rev-parse', 'lab/alice').stdout.strip()
        self.assertEqual(remote, advanced[0])
        fresh = self.clone('retry', 'CI')
        git(fresh, 'checkout', '-q', 'lab/alice')
        self.publish(fresh)
        self.assertEqual((fresh / 'human.txt').read_text(), 'Concurrent investigator work')
        self.assertTrue(git(fresh, 'show', 'HEAD:problems/demo/claims/ledger-alice.jsonl').stdout.find(cid) >= 0)
        self.assertEqual(git(fresh, 'status', '--porcelain').stdout, '')


if __name__ == '__main__':
    unittest.main()
