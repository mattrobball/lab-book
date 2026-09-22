#!/usr/bin/env python3
"""Disposable native two-investigator pilot. Requires Docker, psql, nginx,
PostgREST, and Playwright Chromium. NEVER accepts a production database or host.

The first fixture ingress uses real nginx Basic authentication for synthetic
identities on loopback HTTP. It is NOT a mock of GitHub login and makes no claim
about production OAuth. PostgreSQL uses verify-full TLS. Jev alone is replaced
at the model-call boundary. No paid calls or real issues are created.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

HERE = Path(__file__).resolve()
SCRIPTS = HERE.parents[1] / 'scripts'
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / 'tests')]
from test_federation import FederationCase, git
import claims
import rectification


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


def token(actor, secret):
    def enc(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=')
    msg = enc({'alg': 'HS256', 'typ': 'JWT'}) + b'.' + enc({
        'role': actor, 'sub': actor, 'aud': 'lab-book-fixture', 'iat': int(time.time()), 'exp': int(time.time()) + 900})
    return (msg + b'.' + base64.urlsafe_b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).rstrip(b'=')).decode()


class Pilot(FederationCase):
    def setUp(self):
        super().setUp()
        self.evidence = Path(os.environ['LAB_BOOK_PILOT_EVIDENCE']).resolve()
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.n = 0
        self.container = 'lab-book-pilot-' + secrets.token_hex(6)
        self.addCleanup(self.stop_database)
        self.command(['docker', 'run', '-d', '--name', self.container,
                      '-p', '127.0.0.1::5432', '-e', 'POSTGRES_PASSWORD=disposable-pilot',
                      '-e', 'POSTGRES_DB=labbook_fixture', 'postgres:17'])
        self.dbport = self.command(['docker', 'port', self.container, '5432']).stdout.strip().rsplit(':', 1)[1]
        for _ in range(60):
            p = subprocess.run(['docker', 'exec', self.container, 'pg_isready', '-U', 'postgres'], capture_output=True)
            if p.returncode == 0: break
            time.sleep(1)
        else: self.fail('disposable PostgreSQL never became ready')
        self.trust = self.tmp / 'trust'; self.trust.mkdir()
        cert, key = self.trust / 'server.crt', self.trust / 'server.key'
        self.command(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                      '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1',
                      '-keyout', str(key), '-out', str(cert)])
        for source, target in ((cert, '/tmp/server.crt'), (key, '/tmp/server.key')):
            self.command(['docker', 'cp', str(source), self.container + ':' + target])
        self.command(['docker', 'exec', '-u', '0', self.container, 'chown', 'postgres:postgres', '/tmp/server.key'])
        self.command(['docker', 'exec', '-u', '0', self.container, 'chmod', '600', '/tmp/server.key'])
        for sql in ("ALTER SYSTEM SET ssl='on'", "ALTER SYSTEM SET ssl_cert_file='/tmp/server.crt'",
                    "ALTER SYSTEM SET ssl_key_file='/tmp/server.key'", 'SELECT pg_reload_conf()'):
            self.admin(sql)
        self.admin((HERE.parents[1] / 'assets/v3/reservations.sql').read_text())
        self.admin("CREATE ROLE alice LOGIN PASSWORD 'alice-fixture' IN ROLE lab_book_member;\n"
                   "CREATE ROLE bob LOGIN PASSWORD 'bob-fixture' IN ROLE lab_book_member;\n"
                   "CREATE ROLE fixture_authenticator LOGIN NOINHERIT PASSWORD 'auth-fixture';\n"
                   "GRANT alice, bob TO fixture_authenticator;")
        self.secret = secrets.token_urlsafe(48)
        self.apiport, self.webport = port(), port()
        self.start('postgrest', [os.environ.get('POSTGREST_BIN', 'postgrest')], env=dict(os.environ,
            PGRST_DB_URI='postgresql://fixture_authenticator:auth-fixture@127.0.0.1:' + self.dbport +
                '/labbook_fixture?sslmode=verify-full&sslrootcert=' + str(cert),
            PGRST_DB_SCHEMAS='lab_book', PGRST_JWT_SECRET=self.secret,
            PGRST_JWT_AUD='lab-book-fixture', PGRST_DB_POOL_ACQUISITION_TIMEOUT='3', PGRST_SERVER_HOST='127.0.0.1', PGRST_SERVER_PORT=str(self.apiport)))
        self.site = self.tmp / 'site'
        for clone in (self.alice, self.bob):
            self.join(clone)
            private = self.tmp / ('private-' + clone.name); private.mkdir(mode=0o700)
            (private / 'services').write_text('[pilot]\nhost=127.0.0.1\nport=' + self.dbport +
                '\ndbname=labbook_fixture\nuser=' + clone.name + '\nsslrootcert=' + str(cert) + '\n')
            (private / 'password').write_text('127.0.0.1:' + self.dbport + ':labbook_fixture:' + clone.name + ':' + clone.name + '-fixture\n')
            (private / 'password').chmod(0o600)
            config = {'director': {'model': 'director-model'}, 'reservations': {'service': 'pilot'},
                      'roles': {'manual': {'model': 'worker-' + clone.name}}}
            (clone / 'lab.local.json').write_text(json.dumps(config))
            (self.problem(clone) / 'claims').mkdir(exist_ok=True)
        self.render()
        users = self.tmp / 'users'
        users.write_text(''.join(who + ':' + self.command(['openssl', 'passwd', '-apr1', who + '-fixture']).stdout.strip() + '\n'
                                 for who in ('alice', 'bob')))
        conf = self.tmp / 'nginx.conf'
        conf.write_text('daemon off;\npid ' + str(self.tmp / 'nginx.pid') + ';\n'
            'error_log ' + str(self.evidence / 'nginx-error.log') + ' info;\nevents {}\nhttp {\n'
            'access_log ' + str(self.evidence / 'nginx-access.log') + ';\nmap $remote_user $jwt { default "";\n' +
            ''.join(who + ' "Bearer ' + token(who, self.secret) + '";\n' for who in ('alice', 'bob')) + '}\n'
            'server { listen 127.0.0.1:' + str(self.webport) + '; root ' + str(self.site) + ';\n'
            'auth_basic "Synthetic pilot identities"; auth_basic_user_file ' + str(users) + ';\n'
            'location /api/ { proxy_read_timeout 5s; proxy_set_header Authorization $jwt; proxy_set_header Cookie ""; '
            'proxy_pass http://127.0.0.1:' + str(self.apiport) + '/; }\n'
            'location / { try_files $uri $uri/ =404; } } }\n')
        self.start('nginx', ['nginx', '-p', str(self.tmp), '-c', str(conf)])
        self.url = 'http://127.0.0.1:' + str(self.webport) + '/demo/'
        for _ in range(60):
            try:
                with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:' + str(self.apiport) + '/rpc/list_leases',
                    data=b'{"p":{}}', headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token('alice', self.secret)}), timeout=2) as r:
                    if r.status == 200: break
            except (OSError, urllib.error.HTTPError): time.sleep(.5)
        else: self.fail('PostgREST never became ready')

    def command(self, command, *, cwd=None, env=None, input=None, expected=0):
        self.n += 1; base = self.evidence / ('command-%03d' % self.n)
        # Never record environment values, private service files, or JWTs.
        base.with_suffix('.json').write_text(json.dumps({'argv': list(map(str, command)), 'cwd': str(cwd or Path.cwd())}))
        p = subprocess.run(command, cwd=cwd, env=env, input=input, capture_output=True, text=True, timeout=180)
        base.with_suffix('.stdout').write_text(p.stdout); base.with_suffix('.stderr').write_text(p.stderr)
        base.with_suffix('.exit').write_text(str(p.returncode) + '\n')
        if expected is not None: self.assertEqual(p.returncode, expected, p.stdout + p.stderr)
        return p

    def start(self, name, command, env=None):
        out = (self.evidence / (name + '.stdout')).open('w')
        err = (self.evidence / (name + '.stderr')).open('w')
        p = subprocess.Popen(command, stdout=out, stderr=err, env=env)
        def stop():
            p.terminate()
            try: p.wait(timeout=10)
            except subprocess.TimeoutExpired: p.kill(); p.wait()
            out.close(); err.close()
        self.addCleanup(stop)

    def stop_database(self):
        p = subprocess.run(['docker', 'logs', self.container], capture_output=True, text=True)
        (self.evidence / 'postgres.stdout').write_text(p.stdout)
        (self.evidence / 'postgres.stderr').write_text(p.stderr)
        subprocess.run(['docker', 'rm', '-f', self.container], capture_output=True)

    def admin(self, sql):
        return self.command(['docker', 'exec', '-i', self.container, 'psql', '-XqAt', '-v', 'ON_ERROR_STOP=1',
                             '-U', 'postgres', '-d', 'labbook_fixture'], input=sql).stdout

    def script(self, path, clone, *args, cwd=None):
        private = self.tmp / ('private-' + clone.name)
        env = dict(os.environ, PGSERVICEFILE=str(private / 'services'), PGPASSFILE=str(private / 'password'))
        return self.command([sys.executable, str(path), *args], cwd=cwd or self.problem(clone), env=env, expected=None)

    def render(self):
        self.command([sys.executable, str(SCRIPTS / 'board.py'), '--root', str(self.alice), '--output', str(self.site)])

    def real_packet(self, clone, rid, statement=None):
        self.packet(clone, rid, proposed=[statement] if statement else [])
        p = self.problem(clone) / 'runs' / rid / 'packet/RESULT.md'
        p.write_text(p.read_text().replace("printf '%s\\n' CHECK_OK", "python3 -c \"print('CHECK_OK' if sum(range(4)) == 6 else 'BAD')\""))

    def test_complete_notice_comparison_and_recovery_loop(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            alice = browser.new_context(http_credentials={'username': 'alice', 'password': 'alice-fixture'})
            bob = browser.new_context(http_credentials={'username': 'bob', 'password': 'bob-fixture'})
            pa, pb = alice.new_page(), bob.new_page()
            pa.goto(self.url); pb.goto(self.url)
            expect(pa.locator('#connection')).to_contain_text('Signed in as alice')
            expect(pb.locator('#connection')).to_contain_text('Signed in as bob')
            ba = self.brief(self.alice, 'Compute the pilot invariant.', name='alice.md')
            bb = self.brief(self.bob, 'Compute the pilot invariant.', name='bob.md')
            ra, _ = self.dispatch(self.alice, brief=ba)
            pb.reload(); expect(pb.locator('#flight')).to_contain_text(ra)
            rb, notice = self.dispatch(self.bob, brief=bb)
            self.assertIn('Existing work:', notice.stdout)
            self.assertIn('this run is allowed too', notice.stdout)
            da, db = self.dispatch_json(self.alice, ra), self.dispatch_json(self.bob, rb)
            self.assertTrue(da['lease']); self.assertTrue(db['lease'])
            pa.reload(); expect(pa.locator('#flight')).to_contain_text(rb)
            result = pa.evaluate("async p => await rpc('release_lease',p)", {'lease': db['lease'], 'run': rb})
            self.assertEqual(result['outcome'], 'unsolicited')
            pa.reload(); expect(pa.locator('#flight')).to_contain_text(rb)
            pb.reload()
            own = pb.locator('#flight article').filter(has_text=rb)
            own.get_by_role('button', name='Release my notice').click()
            expect(pb.locator('#flight')).not_to_contain_text(rb)
            expect(pb.locator('#flight')).to_contain_text(ra)
            # Synthetic assertions deliberately disagree. Actual packet replay
            # recomputes arithmetic; this is a policy test, not model accuracy.
            sa, sb = 'The synthetic pilot invariant is six.', 'The synthetic pilot invariant is seven.'
            self.real_packet(self.alice, ra, sa); self.ok(self.alice, 'ingest', ra, '--worker-done')
            self.real_packet(self.bob, rb, sb); self.ok(self.bob, 'ingest', rb, '--worker-done')
            for clone in (self.alice, self.bob): git(clone, 'fetch', '-q', 'origin')
            self.render()
            record = json.loads((self.site / 'demo/record.json').read_text())
            ca, cb = 'C-alice-001', 'C-bob-001'
            key = rectification.pair_key(record['claims'][ca], record['claims'][cb])
            fixture = self.tmp / 'jev.json'
            fixture.write_text(json.dumps({key: {'same_claim': .01, 'contradictory': .99,
                'first_entails_second': .01, 'second_entails_first': .01}}))
            self.claims_ok(self.alice, 'compare', '--new', ca, '--mock-responses', str(fixture))
            git(self.alice, 'push', '-q', 'origin', 'lab/alice')
            git(self.bob, 'fetch', '-q', 'origin')
            self.render(); pa.reload()
            expect(pa.locator('#' + ca)).to_contain_text('contradictions')
            expect(pa.locator('#' + cb)).to_contain_text('contradictions')
            expect(pa.locator('#' + ca)).to_contain_text('mock')
            self.claims_ok(self.alice, 'dismiss', key, '--kind', 'contradiction', '--actor', 'alice',
                           '--reason', 'Synthetic fixture pair, not a mathematical ruling.', '--issue', 'native pilot')
            git(self.alice, 'push', '-q', 'origin', 'lab/alice')
            self.claims_ok(self.alice, 'compare', '--new', ca, '--mock-responses', str(fixture))
            self.render(); pa.reload()
            expect(pa.locator('#' + ca)).not_to_contain_text('contradictions')
            # Late return is kept, not rejected; no worker is preempted.
            late, _ = self.dispatch(self.alice, name='late.md', extra=['--worker-timeout', '1'])
            time.sleep(1.1); pa.reload(); expect(pa.locator('#flight')).to_contain_text('stale')
            self.real_packet(self.alice, late); self.ok(self.alice, 'ingest', late, '--worker-done')
            ing = json.loads((self.problem(self.alice) / 'runs' / late / 'ingest.json').read_text())
            self.assertEqual(ing['reservation_outcome']['outcome'], 'unsolicited')
            self.assertEqual(ing['verdict'], 'PASS'); self.assertTrue(ing['replayed'])
            self.command(['docker', 'stop', self.container])
            absent, _ = self.dispatch(self.alice, name='offline.md')
            self.real_packet(self.alice, absent); self.ok(self.alice, 'ingest', absent, '--worker-done')
            pa.reload(); expect(pa.locator('#connection')).to_contain_text('unavailable', timeout=20000)
            self.assertIsNone(self.dispatch_json(self.alice, absent)['lease'])
            self.render(); pa.reload(); pa.screenshot(path=str(self.evidence / 'board.png'), full_page=True)
            for clone in (self.alice, self.bob):
                self.assertEqual(git(clone, 'status', '--porcelain').stdout.strip(), '')
                p = subprocess.run(['git', 'archive', 'HEAD'], cwd=clone, capture_output=True, check=True)
                (self.evidence / (clone.name + '-record.tar')).write_bytes(p.stdout)
            browser.close()
        (self.evidence / 'result.json').write_text(json.dumps({'result': 'PASS', 'jev': 'mock',
            'database': 'real PostgreSQL verify-full TLS', 'rest': 'real PostgREST', 'browser': 'Chromium',
            'identity': 'synthetic nginx Basic credentials; not production GitHub OAuth',
            'checks': ['peer notice visible', 'concurrent work allowed', 'peer release denied',
                       'two replayed ingests', 'symmetric contradiction', 'persistent dismissal',
                       'late return retained', 'database outage nonblocking', 'clean investigator records']}, indent=2))


if __name__ == '__main__':
    unittest.main()
