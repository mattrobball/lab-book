#!/usr/bin/env python3
"""Serialized lab publication. Run from a clean, disposable CI checkout.

The workflow owns serialization across ALL branches. Checkpoints and notices use
one stream per publisher branch, so later investigator meetings do not merge two
writers into the same append-only file. A checkpoint remembers changed/deferred
targets, never claims that historical all-pairs comparison has been performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

# Installed at <lab>/v3/ci.py. The kit's tests import it by explicit file path.
if (Path(__file__).resolve().parents[1] / 'claims.py').exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import board
import claims
import rectification
import run


class PublicationError(RuntimeError):
    pass


def git(root, *args, check=True):
    p = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=90)
    if check and p.returncode:
        # Git stderr can contain credential-bearing remote URLs. The runner's
        # raw command wrapper retains exit status; the record contains no secrets.
        raise PublicationError('git %s failed (exit %s)' % (args[0], p.returncode))
    return p.stdout.strip()


def publisher(branch):
    if branch not in ('main', 'master') and not re.fullmatch(r'lab/[a-z0-9][a-z0-9-]*', branch):
        raise PublicationError('publication requires main, master, or a lab/<tag> branch')
    return 'automation-ci-' + hashlib.sha256(branch.encode()).hexdigest()[:16]


def snapshot(root):
    refs = {'HEAD': git(root, 'rev-parse', 'HEAD')}
    refs.update({ref: git(root, 'rev-parse', ref) for _, ref in claims.branch_refs(root)})
    return refs


def plan(current, saved, initial_ids=(), retry=()):
    """Select only newly observed versions, prior deferred targets, or explicit IDs."""
    live = {cid: c['hash'] for cid, c in current.items() if c['status'] not in rectification.TERMINAL}
    if saved is None:
        targets = set(initial_ids)  # No one-time historical all-pairs backfill.
    else:
        targets = {cid for cid, h in live.items() if saved['versions'].get(cid) != h}
        targets.update(cid for cid, h in saved.get('pending', {}).items() if live.get(cid) == h)
    targets.update(retry)
    return sorted(targets & live.keys())


def initial_targets(root, problem, before):
    if not before or set(before) == {'0'}:
        # Installation/manual first run establishes a baseline. Explicit retry
        # IDs can request older claims. Never silently start a paid backfill.
        return []
    if not re.fullmatch(r'[0-9a-f]{40}', before):
        raise PublicationError('initial comparison base must be a full commit SHA')
    return board.incremental(root, problem, before)


def changed_paths(root):
    tracked = git(root, 'diff', '--name-only', '-z').split('\0')
    fresh = git(root, 'ls-files', '--others', '--exclude-standard', '-z').split('\0')
    return sorted(set(filter(None, tracked + fresh)))


def allowed_path(path, tag, state_path):
    prefix = r'(?:problems/[^/]+/)?'
    views = r'(?:CLAIMS\.md|notebook/INDEX\.md|claims/C-[a-z0-9-]+\.md)'
    stream = r'claims/rectification-' + re.escape(tag) + r'\.jsonl'
    return path == state_path or bool(re.fullmatch(prefix + '(?:' + views + '|' + stream + ')', path))


def pending_after_check(problem, ids, current, tag):
    """Read THIS publisher's just-appended attempts, in append order.

    A peer's clock may be ahead or equal. A timestamp-sorted global last check
    must not erase the work this invocation actually left deferred.
    """
    if not ids:
        return {}
    attempts = {}
    for line in rectification.ledger_path(problem, tag).read_text().splitlines():
        event = json.loads(line)
        if event['event'] == 'check':
            attempts[event['id']] = event
    pending = {}
    for cid in ids:
        event = attempts.get(cid)
        if not event or event['hash'] != current[cid]['hash']:
            raise PublicationError('missing current publisher attempt')
        if event['state'] == 'deferred':
            pending[cid] = current[cid]['hash']
    return pending


def publish(root, output, before=None, retry=(), push=True, sync_issues=False):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output == root or root in output.parents:
        raise PublicationError('render outside the checkout; artifacts must not enter the record')
    if git(root, 'status', '--porcelain'):
        raise PublicationError('publication requires a clean disposable checkout')
    branch = git(root, 'symbolic-ref', '--short', 'HEAD')
    tag = publisher(branch)
    source = git(root, 'rev-parse', 'HEAD')
    remote = git(root, 'ls-remote', '--heads', 'origin', 'refs/heads/' + branch).split()
    if push and (not remote or remote[0] != source):
        raise PublicationError('branch advanced: restart from its current head, do not force or rebase')
    refs = snapshot(root)
    state_path = 'v3/ci-state/' + tag + '.json'
    checkpoint = root / state_path
    saved = json.loads(checkpoint.read_text()) if checkpoint.exists() else None
    if saved and (saved.get('version') != 1 or saved.get('branch') != branch):
        raise PublicationError('invalid publication checkpoint')
    problems = run.all_problems(root)
    loaded = {}
    for problem in problems:
        claims.forget_committed()
        loaded[problem] = claims.load(problem, include_remote=True)[0]
    visible = {cid for known in loaded.values() for cid in known}
    if set(retry) - visible:
        raise PublicationError('unknown retry claim IDs: ' + ', '.join(sorted(set(retry) - visible)))
    next_state = {'version': 1, 'branch': branch, 'problems': {}}
    reports = {}
    for problem, known in loaded.items():
        rel = str(problem.relative_to(root))
        old = saved.get('problems', {}).get(rel, {'versions': {}, 'pending': {}}) if saved else None
        ids = plan(known, old, initial_targets(root, problem, before) if old is None else (), retry)
        if ids:
            reports[rel] = rectification.check_new(problem, ids, tag=tag)
        # read own appends BEFORE forgetting committed caches
        current = claims.load(problem, include_remote=True)[0]
        next_state['problems'][rel] = {
            'versions': {cid: c['hash'] for cid, c in current.items()},
            'pending': pending_after_check(problem, ids, current, tag)}
        claims.regenerate(problem)
        (problem / "notebook").mkdir(exist_ok=True)
        run.regenerate_index(problem)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps(next_state, indent=2, sort_keys=True) + '\n')
    paths = changed_paths(root)
    if any(not allowed_path(path, tag, state_path) for path in paths):
        raise PublicationError('unexpected write: refusing publication')
    if paths:
        git(root, 'add', '--', *paths)
        git(root, 'commit', '-m', 'CI: comparison metadata and derived views')
    if push:
        # Normal fast-forward is the final compare-and-swap. No force, pull,
        # stash, conflict resolution, or overwrite of a newer source.
        git(root, 'push', 'origin', 'HEAD:refs/heads/' + branch)
    published = git(root, 'rev-parse', 'HEAD')
    claims.forget_committed()
    board.main(['--root', str(root), '--output', str(output)] + (['--sync-issues'] if sync_issues else []))
    manifest = {'source': source, 'published': published, 'branch': branch,
                'visible_refs': refs, 'checks': reports,
                'publication': 'pushed' if push else 'local-only',
                'issue_sync': bool(sync_issues)}
    (output / 'publication.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    parser.add_argument('--output', required=True)
    parser.add_argument('--before')
    parser.add_argument('--retry', action='append', default=[])
    parser.add_argument('--local-only', action='store_true')
    parser.add_argument('--sync-issues', action='store_true')
    args = parser.parse_args(argv)
    # This is an operational guard, not an authorization boundary. All issue
    # writers MUST use the repository-wide concurrency group in lab-ci.yml.
    if args.sync_issues and os.environ.get('LAB_BOOK_SERIALIZED_PUBLICATION') != '1':
        parser.error('issue publication requires the serialized lab CI workflow')
    try:
        result = publish(args.root, args.output, args.before, args.retry,
                         push=not args.local_only, sync_issues=args.sync_issues)
    except (PublicationError, OSError, ValueError) as e:
        print('Publication incomplete: ' + str(e), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
