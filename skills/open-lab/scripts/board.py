#!/usr/bin/env python3
"""Build the private static v3 board and an incremental comparison report.

No status writes. No model calls unless an explicit mock fixture is configured.
The authenticating proxy and PostgREST identity bridge are deployment prerequisites.
"""
import argparse
import html
import json
import re
import subprocess
from pathlib import Path

import claims
import rectification
import run


def graph(known):
    """Small deterministic dependency graph, with links to the claim cards."""
    ids = sorted(known)
    if not ids:
        return '<p>No claims on record.</p>'
    height = max(80, len(ids) * 44)
    positions = {cid: (240, 24 + i * 44) for i, cid in enumerate(ids)}
    parts = ['<svg class="graph" viewBox="0 0 600 %s" role="img" aria-label="Claim dependency graph">' % height, '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>']
    for cid in ids:
        x, y = positions[cid]
        for other in known[cid]['rests_on']:
            if other not in positions:
                continue
            _, yy = positions[other]
            parts.append('<path d="M 220 %d C 40 %d 40 %d 220 %d" fill="none" stroke="currentColor" marker-end="url(#arrow)"/>' % (y, y, yy, yy))
    for cid in ids:
        x, y = positions[cid]
        c = known[cid]
        parts.append('<a href="#%s"><circle class="%s" cx="%d" cy="%d" r="7"/><text x="260" y="%d">%s [%s]</text><title>%s</title></a>' %
                     (html.escape(cid, quote=True), html.escape(c['status']), x, y, y + 5,
                      html.escape(cid), html.escape(c['status']), html.escape(c['statement'])))
    return '\n'.join(parts + ['</svg>'])


def recent_runs(problem):
    root = claims.git_root(problem)
    base = str(problem.relative_to(root)) + '/runs'
    rows = {}
    for ref in ['HEAD'] + [r for _, r in claims.branch_refs(root)]:
        for rid in claims.list_branch_dir(root, ref, base):
            if not claims.RUN_ID.match(rid):
                continue
            path = base + '/' + rid + '/'
            d = claims.read_branch_file(root, ref, path + 'dispatch.json')
            ing = claims.read_branch_file(root, ref, path + 'ingest.json')
            if d:
                dispatch = json.loads(d)
                item = {'run': rid, 'dispatch': dispatch,
                        'ingest': json.loads(ing) if ing else None, 'ref': ref}
                previous = rows.get(rid)
                if previous is None or (item['ingest'] and not previous['ingest']):
                    rows[rid] = item
    return sorted(rows.values(), key=lambda r: (r['ingest'] or r['dispatch'])['ts'], reverse=True)[:30]


def issue_spec(problem, pair):
    key = pair['key']
    marker = '<!-- lab-book-pair:%s -->' % key
    a, b = pair['pair']
    kinds = ', '.join(k for k, yes in pair['flags'].items() if yes)
    body = '%s\n\nProblem: `%s`\n\n%s\n\n%s\n\n' % (marker, problem, a['statement'], b['statement'])
    body += 'Flags: %s. Source: %s.\n\nRaw probabilities:\n```json\n%s\n```\n\n' % (
        kinds, pair['source'], json.dumps(pair['probabilities'], indent=2))
    kind = next(k for k in ('contradiction', 'duplicate', 'adjudication') if pair['flags'].get(k))
    body += ('Discuss the ruling here. Closing this issue alone does not dismiss a flag. '
             'Record a false positive with `claims.py dismiss %s --kind %s '
             '--reason "..." --issue "..." --actor <investigator> --problem %s`. '
             'Refutation/supersession remain explicit `claims.py set` operations; '
             'a request for another run leaves the question open.\n' % (key, kind, problem))
    body += '<!-- /lab-book-pair -->\n'
    return {'key': key, 'title': '%s: %s / %s' % (kinds, a['id'], b['id']), 'body': body}


def sync_issues(repository, specs, request):
    """One issue per version-bound pair; pagination and retry-safe lookup.

    request(method, path, body=None) is the network boundary. Tests mock it.
    Real publishing is opt-in and refuses mock comparisons before this call.
    """
    existing, page = {}, 1
    while True:
        items = request('GET', '/repos/%s/issues?state=all&per_page=100&page=%d' % (repository, page))
        for item in items:
            if 'pull_request' in item:
                continue
            match = re.search(r'<!-- lab-book-pair:([0-9a-f]{64}) -->', item.get('body') or '')
            if match:
                existing.setdefault(match.group(1), item)
        if len(items) < 100:
            break
        page += 1
    for spec in specs:
        payload = {'title': spec['title'], 'body': spec['body']}
        old = existing.get(spec['key'])
        if old:
            old_body = old.get('body') or ''
            block = r'<!-- lab-book-pair:' + spec['key'] + r' -->.*?<!-- /lab-book-pair -->\n?'
            # Refresh only the delimited bot-owned summary. Discussion, comments,
            # and text outside that block remain the person's own record.
            match = re.search(block, old_body, re.S)
            updates = {}
            if match:
                new_body = old_body[:match.start()] + payload['body'] + old_body[match.end():]
                if new_body != old_body:
                    updates['body'] = new_body
                if old.get('title') != payload['title']:
                    updates['title'] = payload['title']
            if old.get('state') == 'closed':
                updates['state'] = 'open'
            if updates:
                request('PATCH', '/repos/%s/issues/%s' % (repository, old['number']), updates)
                old.update(updates)
        else:
            created = request('POST', '/repos/%s/issues' % repository, payload)
            existing[spec['key']] = created


JS = r'''
const flight = document.getElementById('flight');
const message = document.getElementById('connection');
const problem = document.body.dataset.problem;
let actor = null;
function text(tag, value, parent) { const e=document.createElement(tag); e.textContent=value; parent.append(e); return e; }
async function rpc(name,p) {
  const r=await fetch('/api/rpc/'+name,{method:'POST',credentials:'same-origin',
    headers:{'Content-Type':'application/json','X-Lab-Board':'1'},body:JSON.stringify({p})});
  if(!r.ok) throw new Error('Reservation service returned '+r.status);
  return r.json();
}
async function refresh() {
  try {
    const data=await rpc('list_leases',{problem});
    if(!Array.isArray(data.reservations) || typeof data.actor !== 'string') throw new Error('Invalid reservation response');
    actor=data.actor; flight.replaceChildren();
    message.textContent='Live reservations as of '+new Date().toLocaleTimeString()+'. Signed in as '+actor+'.';
    if(!data.reservations.length) text('p','No announced work.',flight);
    for(const r of data.reservations) {
      const box=text('article','',flight), p=r.payload;
      const elapsed=Math.max(0,Math.round((Date.now()-Date.parse(r.started_at))/60000));
      text('h3',r.run_id+' — '+r.actor+' — '+r.state,box);
      text('p',p.question,box);
      text('p',p.method+' · '+p.model+' · '+elapsed+' / '+Math.round(p.budget_seconds/60)+' minutes',box);
      text('p','Expected: '+p.expected_claim_shape,box);
      if(document.getElementById(p.question_id)) { const link=text('a',p.question_id,box); link.href='#'+p.question_id; }
      if(r.actor===actor) { const b=text('button','Release my notice',box); b.type='button';
        b.onclick=async()=>{try {await rpc('release_lease',{lease:r.lease,run:r.run_id}); await refresh();}
          catch(e){message.textContent=e.message+'; no claim or worker was changed.';}}; }
    }
  } catch(e) { message.textContent='Reservations unavailable. Displayed notices may be stale; work may continue. '+e.message; }
}
document.getElementById('reserve').onsubmit=async e=>{
  e.preventDefault(); const data=Object.fromEntries(new FormData(e.target));
  data.budget_seconds=Number(data.budget_seconds); data.problem=problem;
  try {const result=await rpc('take_lease',data); await refresh();
    if(result.notices?.length) message.textContent+=' Existing work on this question: '+result.notices.map(x=>x.run_id+' by '+x.actor).join(', ')+'. This work is allowed too.';
  } catch(error){message.textContent=error.message+'; work may continue.';}
};
refresh(); setInterval(refresh,15000);
'''


def render_problem(problem, output, api=True):
    known, order = claims.load(problem, include_remote=True)
    pairs = rectification.active_pairs(known, rectification.records(problem, True))
    runs = recent_runs(problem)
    root = claims.git_root(problem)
    identity = claims.git_out(root, 'rev-parse', 'HEAD')
    body = ['<h1>Lab book · %s</h1>' % html.escape(problem.name),
            '<p>Committed record at <code>%s</code>. Comparison flags are advisory; mock judgments are labeled.</p>' % identity,
            '<h2>Believed</h2>', graph(known)]
    for cid in order:
        c = known[cid]
        body += ['<article id="%s"><h3>%s · %s</h3><p>%s</p>' %
                 (html.escape(cid), html.escape(cid), html.escape(c['status']), html.escape(c['statement'])),
                 '<p>Conditions: %s</p><p>Rests on: %s</p>' %
                 (html.escape(c['conditions'] or 'None stated.'), html.escape(', '.join(c['rests_on']) or 'Nothing.'))]
        for notice in rectification.summary({cid: c}):
            body.append('<p class="notice">%s</p>' % html.escape(notice))
        coverage = c['comparison_coverage']
        if coverage['state'] == 'excluded':
            body.append('<p>Terminal claim: excluded from current comparison coverage.</p>')
        else:
            body.append('<p>Current comparison coverage: %d / %d visible peers assessed.</p>' %
                        (coverage['compared'], coverage['peers']))
            if coverage['mock']:
                body.append('<p class="notice">MOCK comparison coverage — %d pair(s), not live Jev judgments.</p>' % coverage['mock'])
        for event in c['history']:
            if event.get('cascade_from') or event.get('acknowledged_contradictions'):
                body.append('<p>Recorded change: %s</p>' % html.escape(json.dumps(event, sort_keys=True)))
        body.append('</article>')
    body += ['<h2>In flight</h2><p id="connection">Live reservation service not yet contacted. No inference of inactivity.</p><div id="flight"></div>',
             '<details><summary>Announce existing work</summary><p>This notice does not dispatch, stop, or reserve exclusive access to a worker.</p><form id="reserve">']
    for name, label in [('run','Allocated run ID'),('question_id','Claim or question ID'),('question','Question'),
                        ('method','Method'),('model','Model'),('expected_claim_shape','Expected claim shape')]:
        body.append('<label>%s<input required name="%s"></label>' % (label, name))
    body += ['<label>Budget (seconds)<input required type="number" min="1" max="604800" name="budget_seconds"></label><button>Announce</button></form></details>',
             '<h2>Just landed</h2>']
    for item in runs:
        ing, d = item['ingest'], item['dispatch']
        body.append('<article><h3>%s · %s</h3>' % (html.escape(item['run']), html.escape((ing or d).get('verdict', d['status']))))
        body.append('<p>Promised: %s</p>' % html.escape(json.dumps(d.get('preregistration') or {}, sort_keys=True)))
        body.append('<p>Returned: %s</p></article>' % html.escape(json.dumps(ing or {'state':'not ingested'}, sort_keys=True)))
    body.append('<h3>Recent claim decisions</h3>')
    events = claims.stream_events(problem) + claims.remote_events(problem)
    seen = set()
    for event, ref in sorted(events, key=lambda row: row[0]['ts'], reverse=True):
        identity_key = json.dumps(event, sort_keys=True)
        if identity_key in seen:
            continue
        seen.add(identity_key)
        if len(seen) > 30:
            break
        body.append('<p>%s</p>' % html.escape(run.describe_event(event)))
    body += ['<h3>Adjudication</h3><p>Discuss pairs in GitHub Issues. Apply a dismissal through <code>claims.py dismiss</code>; an issue closure alone is not a ledger ruling.</p>']
    for pair in pairs:
        body.append('<details><summary>%s / %s [%s]</summary><pre>%s</pre></details>' %
                    (html.escape(pair['pair'][0]['id']), html.escape(pair['pair'][1]['id']), html.escape(pair['source']),
                     html.escape(issue_spec(problem.name, pair)['body'])))
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lab book</title><style>
body{font:16px/1.5 system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#18212b;background:#f5f7fa}
article,details{background:white;border:1px solid #d5dce3;padding:1rem;margin:1rem 0;border-radius:6px}
h2{border-top:2px solid #b8c5cf;padding-top:1rem}label{display:block;margin:.5rem 0}input{display:block;width:95%%;padding:.5rem}
button{padding:.6rem 1rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}.notice{border-left:4px solid #a45a0c;padding-left:.75rem}
.graph{max-height:500px;width:100%%;overflow:auto}.graph text{font:14px system-ui;fill:currentColor}
circle{fill:#80909d}.verified{fill:#15803d}.conditional{fill:#b7791f}.refuted,.superseded{fill:#b91c1c}
</style><body data-problem="%s">%s<script src="board.js"></script></body></html>'''
    output.mkdir(parents=True, exist_ok=True)
    (output / 'index.html').write_text(page % (html.escape(str(problem.relative_to(root)), quote=True), '\n'.join(body)))
    (output / 'board.js').write_text(JS if api else '// Live service disabled for this rendering.\n')
    (output / 'record.json').write_text(json.dumps({'source': identity, 'claims': known, 'pairs': pairs, 'runs': runs}, indent=2) + '\n')
    return [issue_spec(problem.name, pair) for pair in pairs if pair['source'] != 'mock']


def incremental(root, problem, before):
    """Only changed local claim versions, against all visible investigator refs."""
    if not before or set(before) == {'0'}:
        before = claims.git_out(root, 'rev-parse', 'HEAD^')
    if not before:
        return []  # No silent one-time all-pairs backfill.
    resolved = claims.git(root, 'rev-parse', '--verify', before + '^{commit}')
    if resolved.returncode:
        raise ValueError('comparison base is not an available commit')
    path = str(problem.relative_to(root)) + '/claims'
    events = []
    for name in claims.list_branch_dir(root, before, path):
        if name.startswith('ledger') and name.endswith('.jsonl'):
            text = claims.read_branch_file(root, before, path + '/' + name) or ''
            events += [(json.loads(line), before) for line in text.splitlines() if line.strip()]
    previous, _ = claims.fold(events)
    current, _ = claims.load(problem)
    return [cid for cid, c in current.items() if c['status'] not in rectification.TERMINAL
            and (cid not in previous or previous[cid]['hash'] != c['hash'])]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    parser.add_argument('--output', required=True)
    parser.add_argument('--before')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--sync-issues', action='store_true')
    args = parser.parse_args(argv)
    root = claims.lab_root(args.root)
    out = Path(args.output).resolve()
    reports, specs, links = {}, [], []
    for problem in run.all_problems(root):
        ids = incremental(root, problem, args.before) if args.check else []
        if ids:
            reports[problem.name] = rectification.check_new(problem, ids, tag='automation-ci')
            claims.regenerate(problem)
        specs += render_problem(problem, out / problem.name)
        links.append('<p><a href="%s/index.html">%s</a></p>' % (html.escape(problem.name, quote=True), html.escape(problem.name)))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Lab book</title><h1>Lab book</h1>' + (''.join(links) or '<p>No lab problems in this repository.</p>'))
    (out / 'comparison-report.json').write_text(json.dumps(reports, indent=2) + '\n')
    (out / 'issue-candidates.json').write_text(json.dumps(specs, indent=2) + '\n')
    if args.sync_issues:
        import os
        import urllib.request
        repo, token = os.environ.get('GITHUB_REPOSITORY', ''), os.environ.get('GITHUB_TOKEN')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) or not token:
            parser.error('issue publishing needs GITHUB_REPOSITORY and GITHUB_TOKEN')
        def request(method, path, body=None):
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request('https://api.github.com' + path, data=data, method=method,
                headers={'Authorization':'Bearer ' + token, 'Accept':'application/vnd.github+json',
                         'Content-Type':'application/json', 'X-GitHub-Api-Version':'2022-11-28'})
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)
        sync_issues(repo, specs, request)
    print(json.dumps(reports, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
