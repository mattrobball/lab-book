#!/usr/bin/env python3
"""Advisory, version-bound claim comparisons; never a claim status writer.

The first pass deliberately has no live Jev transport. MockJev is an explicit
fixture boundary, not a heuristic replacement or a source of mathematical truth.
"""
import hashlib
import json
import math
import os
from pathlib import Path

FIELDS = ('same_claim', 'contradictory', 'first_entails_second',
          'second_entails_first')
TERMINAL = {'refuted', 'superseded'}


def pair_key(first, second):
    pair = sorted((first, second), key=lambda c: c['id'])
    identity = [[c['id'], c['hash']] for c in pair]
    return hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()


def probabilities(raw):
    if not isinstance(raw, dict) or set(raw) != set(FIELDS):
        raise ValueError('expected exactly four Jev probability fields')
    for key, value in raw.items():
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError('invalid probability for ' + key)
    return dict(raw)


def policy(raw):
    p = probabilities(raw)
    return {'duplicate': p['same_claim'] > .9,
            'adjudication': .5 <= p['same_claim'] <= .9,
            'contradiction': p['contradictory'] > .7}


class MockJev:
    """Exact, ordered, version-bound responses. Missing pairs fail, never default."""
    source = 'mock'

    def __init__(self, responses):
        if not isinstance(responses, dict):
            raise ValueError('mock responses must be a dictionary keyed by pair hash')
        self.responses = responses

    def __call__(self, first, second):
        key = pair_key(first, second)
        if key not in self.responses:
            raise LookupError('no mock response for ' + key)
        return probabilities(self.responses[key])


def configured_judge(root):
    import claims
    config = claims.local_config(root).get('rectification') or {}
    path = config.get('mock_responses')
    if not path:
        return None
    path = Path(path)
    if not path.is_absolute():
        path = Path(root) / path
    return MockJev(json.loads(path.read_text()))


def ledger_path(problem, tag=None):
    return Path(problem) / 'claims' / ('rectification%s.jsonl' % ('-' + tag if tag else ''))


def records(problem, include_remote=False):
    import claims
    root = claims.cached_root(problem)
    base = None
    if root:
        base = str(Path(problem).resolve().relative_to(root.resolve()))
        base = ('' if base == '.' else base + '/') + 'claims/'
    refs = [('HEAD', None)]
    if include_remote and root:
        refs += [(ref, tag) for tag, ref in claims.branch_refs(root)]
    result, seen = [], set()
    for ref, _ in refs:
        names = set()
        if ref == 'HEAD':
            names.update(p.name for p in (Path(problem) / 'claims').glob('rectification*.jsonl'))
        if root:
            names.update(n for n in claims.list_branch_dir(root, ref, base.rstrip('/'))
                         if n.startswith('rectification') and n.endswith('.jsonl'))
        for name in sorted(names):
            text = (claims.committed_text(problem, Path(problem) / 'claims' / name)
                    if ref == 'HEAD' else claims.read_branch_file(root, ref, base + name)) or ''
            for line in text.splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                key = json.dumps(rec, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    result.append(rec)
    return sorted(result, key=lambda r: r['ts'])


def append(problem, rec, tag=None):
    import claims
    path = ledger_path(problem, tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    claims.own_write(path)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644), 'a') as f:
        f.write(json.dumps(rec, sort_keys=True, allow_nan=False) + '\n')


def active_pairs(known, events):
    comparisons, dismissed = {}, set()
    for rec in events:
        if rec['event'] == 'comparison':
            probabilities(rec['probabilities'])
            comparisons[rec['key']] = rec
        elif rec['event'] == 'dismiss':
            dismissed.add((rec['key'], rec['kind']))
    result = []
    for key, rec in sorted(comparisons.items()):
        pair = rec['pair']
        if len(pair) != 2 or pair[0]['id'] == pair[1]['id']:
            raise ValueError('invalid comparison identity')
        if pair_key(*pair) != key:
            raise ValueError('comparison identity does not match its key')
        # An unseen colleague is not a refuted claim. Keep that notice until
        # their current record is available, rather than clearing it silently.
        if any(c['id'] in known and (known[c['id']]['hash'] != c['hash']
                                    or known[c['id']]['status'] in TERMINAL) for c in pair):
            continue
        flags = {k: v and (key, k) not in dismissed
                 for k, v in policy(rec['probabilities']).items()}
        if any(flags.values()):
            result.append(dict(rec, flags=flags))
    return result


def current_coverage(known, events):
    """Derive coverage against today's visible peers, without making any calls.

    Historical attempt counts stay on record, but cannot describe a later merge
    or a terminal peer. Work is linear in claims plus retained comparisons, not
    an all-pairs scan. A dismissal does not erase the fact a pair was assessed.
    """
    live = {cid: c for cid, c in known.items() if c['status'] not in TERMINAL}
    latest = {r['key']: r for r in events if r['event'] == 'comparison'}
    covered = {cid: {} for cid in live}
    for key, rec in latest.items():
        pair = rec['pair']
        if len(pair) != 2 or pair[0]['id'] == pair[1]['id'] or pair_key(*pair) != key:
            raise ValueError('invalid comparison identity')
        probabilities(rec['probabilities'])
        if any(c['id'] not in live or live[c['id']]['hash'] != c['hash'] for c in pair):
            continue
        a, b = [c['id'] for c in pair]
        covered[a][b] = rec['source']
        covered[b][a] = rec['source']
    result = {}
    for cid in known:
        sources = list(covered.get(cid, {}).values())
        peers = max(0, len(live) - 1) if cid in live else 0
        missing = peers - len(sources)
        result[cid] = {'state': ('excluded' if cid not in live else
                                 'deferred' if missing else 'complete'),
                       'peers': peers, 'compared': len(sources), 'deferred': missing,
                       'mock': sources.count('mock'), 'sources': sorted(set(sources))}
    return result


def attach(problem, known, include_remote=False):
    events = records(problem, include_remote)
    coverage = current_coverage(known, events)
    for cid, c in known.items():
        c['comparison_coverage'] = coverage[cid]
        c['duplicate-candidate-of'] = []
        c['contradictions'] = []
        c['adjudication'] = []
        c['comparison_check'] = None
    for rec in events:
        if rec['event'] == 'check' and rec['id'] in known:
            c = known[rec['id']]
            if rec['hash'] == c['hash']:
                c['comparison_check'] = rec
    for rec in active_pairs(known, events):
        a, b = [c['id'] for c in rec['pair']]
        for cid, other in ((a, b), (b, a)):
            if cid not in known:
                continue
            notice = {'other': other, 'key': rec['key'], 'source': rec['source'],
                      'probabilities': rec['probabilities']}
            for flag, field in [('duplicate', 'duplicate-candidate-of'),
                                ('contradiction', 'contradictions'),
                                ('adjudication', 'adjudication')]:
                if rec['flags'][flag]:
                    known[cid][field].append(notice)
    return known


def check_new(problem, ids, tag=None, judge=None):
    """Compare each requested claim with EVERY nonterminal claim on visible refs.

    Returns coverage, not a truth verdict. Append to the caller's transaction;
    never commit here, so a failed ingest cannot publish orphan claim evidence.
    """
    import claims
    root = claims.git_root(problem)
    known, _ = claims.load(problem, include_remote=True, root=root)
    targets = sorted(set(ids))
    unknown = [cid for cid in targets if cid not in known]
    if unknown:
        raise ValueError('unknown comparison target: ' + ', '.join(unknown))
    problem_events = records(problem, include_remote=True)
    cache = {r['key']: r for r in problem_events if r['event'] == 'comparison'}
    setup_error = None
    if judge is None:
        try:
            judge = configured_judge(root)
        except (OSError, ValueError, TypeError) as e:
            setup_error = type(e).__name__
    source = getattr(judge, 'source', 'unavailable') if judge else 'unavailable'
    counts = {'compared': 0, 'cached': 0, 'deferred': 0, 'source': source}
    attempted = {}
    for cid in targets:
        c = known[cid]
        if c['status'] in TERMINAL:
            continue
        coverage = {'compared': 0, 'cached': 0, 'deferred': 0}
        for other in sorted(known):
            d = known[other]
            if other == cid or d['status'] in TERMINAL:
                continue
            first, second = sorted((c, d), key=lambda x: x['id'])
            key = pair_key(first, second)
            if key in cache:
                # A cached MOCK can exercise mock behavior only. It must not
                # suppress a later live judge's comparison of the same text.
                if cache[key]['source'] == source:
                    coverage['cached'] += 1
                    continue
            if key in attempted:
                state = attempted[key]
                coverage[state] += 1
                continue
            if judge is None:
                attempted[key] = 'deferred'
                coverage['deferred'] += 1
                continue
            try:
                raw = probabilities(judge(first, second))
            except Exception as e:
                # A remote/provider failure is not a failed experiment. Retain
                # the error class only; exception strings may contain secrets.
                setup_error = type(e).__name__
                attempted[key] = 'deferred'
                coverage['deferred'] += 1
                continue
            rec = {'event': 'comparison', 'ts': claims.now(), 'actor': tag or 'director',
                   'key': key, 'pair': [{'id': x['id'], 'hash': x['hash'],
                                        'statement': x['statement'], 'conditions': x['conditions']}
                                       for x in (first, second)],
                   'probabilities': raw, 'source': source}
            append(problem, rec, tag)
            attempted[key] = 'compared'
            coverage['compared'] += 1
        append(problem, dict(coverage, event='check', id=cid, hash=c['hash'],
                             ts=claims.now(), actor=tag or 'director', source=source,
                             state='deferred' if coverage['deferred'] else 'complete',
                             error=setup_error), tag)
        for name in coverage:
            counts[name] += coverage[name]
    return counts


def summary(known):
    lines = []
    for cid in sorted(known):
        c = known[cid]
        if c['status'] in TERMINAL:
            continue
        for field in ('contradictions', 'duplicate-candidate-of', 'adjudication'):
            for flag in c.get(field, []):
                lines.append('%s %s %s [%s; pair %s]' %
                             (cid, field, flag['other'], flag['source'], flag['key']))
        coverage = c.get('comparison_coverage')
        if coverage and coverage['state'] == 'deferred':
            lines.append('%s: comparison deferred (%s current pairs)' % (cid, coverage['deferred']))
    return lines


def cmd_compare(args):
    import claims
    problem = claims.find_problem(args.problem)
    tag = claims.require_own_branch(claims.git_root(problem), 'claim comparison')
    judge = None
    if args.mock_responses:
        judge = MockJev(json.loads(Path(args.mock_responses).read_text()))
    report = check_new(problem, args.new, tag, judge)
    claims.regenerate(problem)
    claims.commit(problem, 'rectification: compare ' + ', '.join(args.new))
    print(json.dumps(report, sort_keys=True))


def cmd_dismiss(args):
    import claims
    problem = claims.find_problem(args.problem)
    tag = claims.require_own_branch(claims.git_root(problem), 'a comparison ruling')
    actor = claims.resolve_actor(args.actor, tag)
    if not args.reason.strip():
        claims.refuse('a dismissal needs a reason')
    known, _ = claims.load(problem, include_remote=True)
    found = [r for r in active_pairs(known, records(problem, True))
             if r['key'] == args.pair and r['flags'].get(args.kind)]
    if not found:
        claims.refuse('no open, current comparison flag matches that pair and kind')
    append(problem, {'event': 'dismiss', 'ts': claims.now(), 'actor': actor,
                     'key': args.pair, 'kind': args.kind, 'reason': args.reason.strip(),
                     'issue': args.issue}, tag)
    claims.regenerate(problem)
    claims.commit(problem, 'rectification: dismiss ' + args.kind + ' ' + args.pair)
    print('Dismissal recorded; claim statuses unchanged.')
