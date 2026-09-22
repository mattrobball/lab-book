"""Optional PostgreSQL notices. Failure never refuses dispatch or ingest."""
import hashlib
import json
import re
import subprocess
from pathlib import Path


def rpc(root, operation, payload):
    import claims
    if operation not in {'take_lease', 'release_lease', 'reap_leases', 'list_leases'}:
        raise ValueError('unknown reservation operation')
    config = claims.local_config(root).get('reservations') or {}
    service = config.get('service')
    if not service:
        return {'available': False, 'reason': 'not configured'}
    if not isinstance(service, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', service):
        return {'available': False, 'reason': 'invalid service name'}
    # A libpq service holds the password and trust material outside git.
    # Explicit parameters override service defaults: no sslmode=prefer fallback.
    conn = 'service=%s sslmode=verify-full connect_timeout=3' % service
    try:
        p = subprocess.run(['psql', '-X', '-qAt', '--no-password', '--dbname', conn,
                            '--set', 'ON_ERROR_STOP=1', '--set',
                            'payload=' + json.dumps(payload, allow_nan=False)],
                           input="SELECT lab_book.%s(:'payload'::jsonb)::text;\n" % operation,
                           capture_output=True, text=True, timeout=5)
        if p.returncode:
            return {'available': False, 'reason': 'database request failed'}
        result = json.loads(p.stdout)
        if not isinstance(result, dict):
            raise ValueError('invalid database response')
        return dict(result, available=True)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        # Never copy libpq stderr/connection details into the committed record.
        return {'available': False, 'reason': 'database unavailable or invalid response'}


def preregister(root, problem, dispatch, text):
    import run
    sections = run.split_sections(text)
    question = sections.get('goal', '').strip() or text.strip()
    carried = dispatch.get('claims_pasted') or []
    question_id = carried[0] if len(carried) == 1 else 'Q-' + hashlib.sha256(question.encode()).hexdigest()[:24]
    promise = {'actor': dispatch.get('investigator'), 'run': dispatch['run'],
               'problem': str(Path(problem).relative_to(root)),
               'question_id': question_id, 'question': question,
               'method': sections.get('method', '').strip() or dispatch.get('kind') or 'not stated',
               'model': dispatch['model'],
               'expected_claim_shape': sections.get('expected claim shape', '').strip()
                   or sections.get('metrics', '').strip() or 'not stated',
               'budget_seconds': dispatch['limits']['worker_timeout'],
               'brief_sha': dispatch['brief_sha']}
    dispatch['preregistration'] = promise
    dispatch['lease'] = None
    if not promise['actor']:
        result = {'available': False, 'reason': 'join the lab before announcing a database reservation'}
    else:
        result = rpc(root, 'take_lease', promise)
    dispatch['reservation'] = result
    if result.get('available'):
        row = result.get('reservation') or {}
        if row.get('actor') != promise['actor'] or row.get('run_id') != dispatch['run'] or not row.get('lease'):
            dispatch['reservation'] = {'available': False, 'reason': 'database identity mismatch'}
            return
        dispatch['lease'] = row['lease']
    # Printing stays with run.py, after its existing first line containing the ID.


def notices(dispatch):
    result = dispatch.get('reservation') or {}
    if not result.get('available'):
        return ['Reservation unavailable: %s; work continues.' % result.get('reason', 'unknown')]
    return ['Existing work: %s by %s on %s; this run is allowed too.' %
            (r['run_id'], r['actor'], r['payload']['question_id'])
            for r in result.get('notices', [])]


def release(root, dispatch):
    lease = dispatch.get('lease')
    if not lease:
        return {'lease': None, 'outcome': 'unreserved'}
    result = rpc(root, 'release_lease', {'lease': lease, 'run': dispatch['run']})
    if not result.get('available'):
        return {'lease': lease, 'outcome': 'unavailable', 'reason': result.get('reason')}
    outcome = result.get('outcome')
    return {'lease': lease, 'outcome': outcome if outcome in ('released', 'unsolicited') else 'unavailable'}
