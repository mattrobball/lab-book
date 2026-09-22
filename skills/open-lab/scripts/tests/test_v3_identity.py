"""Identity bridge authorization contracts. No live GitHub login is asserted."""
from email.message import Message
import importlib.util
import json
import base64
import hashlib
import hmac
from pathlib import Path
import tempfile
import threading
import time
import unittest
import http.client
import socket

ASSETS = Path(__file__).resolve().parents[2] / 'assets/v3'
spec = importlib.util.spec_from_file_location('identity', ASSETS / 'identity.py')
identity = importlib.util.module_from_spec(spec); spec.loader.exec_module(identity)


def headers(**values):
    h = Message()
    for key, value in values.items(): h[key.replace('_', '-')] = value
    return h


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secret = self.root / 'secret'; self.secret.write_bytes(b'k' * 48); self.secret.chmod(0o600)
        self.config = self.root / 'config.json'
        self.c = {'origin': 'https://lab.example', 'auth_url': 'http://127.0.0.1:4180/oauth2/auth',
                  'postgrest_url': 'http://127.0.0.1:3000', 'jwt_secret_file': str(self.secret),
                  'investigators': {'github-alice': 'alice', 'github-bob': 'bob'}}
        self.write_config()
        self.calls = []
        self.login = 'github-alice'
        self.auth_status = 202
        def request(url, method, h, data=None):
            self.calls.append((url, method, h, data))
            if url.endswith('/oauth2/auth'):
                return self.auth_status, headers(X_Auth_Request_User=self.login), b''
            return 200, headers(), b'{"actor":"alice","reservations":[]}'
        self.bridge = identity.Bridge(self.config, request)
        self.h = headers(Cookie='session=opaque', Origin=self.c['origin'], X_Lab_Board='1', Content_Type='application/json')

    def write_config(self):
        self.config.write_text(json.dumps(self.c))

    def invoke(self, h=None, body=b'{"p":{}}', method='POST', path='/api/rpc/list_leases'):
        return self.bridge.handle(method, path, h or self.h, body)

    def denied(self, code, **kw):
        with self.assertRaises(identity.Denied) as ctx: self.invoke(**kw)
        self.assertEqual(ctx.exception.status, code)

    def test_verified_identity_maps_to_the_same_database_actor(self):
        status, _ = self.invoke(); self.assertEqual(status, 200)
        self.assertEqual(self.calls[0][2], {'Cookie': 'session=opaque'})
        jwt = self.calls[1][2]['Authorization'].removeprefix('Bearer ')
        a,b,c = jwt.split('.')
        decode = lambda s: base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
        payload = json.loads(decode(b))
        self.assertEqual(payload['role'], 'alice'); self.assertEqual(payload['sub'], 'github:github-alice')
        self.assertEqual(payload['aud'], 'lab-book'); self.assertEqual(payload['exp']-payload['iat'], 30)
        self.assertEqual(decode(c), hmac.new(b'k'*48, (a+'.'+b).encode(), hashlib.sha256).digest())
        self.assertNotIn('Cookie', self.calls[1][2])

    def test_browser_identity_and_bearer_headers_are_ignored(self):
        self.h['X-Auth-Request-User'] = 'github-bob'; self.h['Authorization'] = 'Bearer stolen'
        self.invoke()
        payload = self.calls[1][2]['Authorization'].split('.')[1]
        self.assertEqual(json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload)%4)))['role'], 'alice')

    def test_unknown_and_removed_mapping_are_denied_immediately(self):
        self.login = 'outsider'; self.denied(403)
        self.login = 'github-alice'; self.c['investigators'].pop('github-alice'); self.write_config()
        self.denied(403)

    def test_anonymous_invalid_session_and_auth_outage_are_closed(self):
        del self.h['Cookie']; self.denied(401); self.assertFalse(self.calls)
        self.h['Cookie'] = 'session=bad'; self.auth_status=401; self.denied(401)
        self.auth_status=302; self.denied(502)
        self.assertFalse(any('/rpc/' in c[0] for c in self.calls))

    def test_cross_origin_missing_origin_and_header_duplication_are_refused(self):
        del self.h['Origin']; self.denied(403)
        self.h['Origin']='https://evil.example'; self.denied(403)
        self.h['Origin']='https://lab.example'; self.denied(400)
        self.assertFalse(self.calls)

    def test_body_limits_duplicate_keys_and_extra_role_are_refused(self):
        self.denied(413, body=b'x'*65537)
        self.denied(400, body=b'{"p":{},"p":{}}')
        self.denied(400, body=b'{"p":{},"role":"bob"}')
        self.denied(400, body=b'null')
        self.assertFalse(any('/rpc/' in c[0] for c in self.calls))

    def test_private_board_auth_and_no_arbitrary_endpoint(self):
        self.assertEqual(self.invoke(method='GET', path='/auth', body=b'')[0], 204)
        for path in ('/api/rpc/preempt', '/api/rpc/list_leases?role=bob', '/api/claims/set', '/api/rpc/../auth'):
            self.denied(404, path=path)

    def test_config_refuses_insecure_origin_remote_endpoint_or_role_alias(self):
        for key, value in [('origin','http://lab.example'),('auth_url','http://evil.example/oauth2/auth'),
                           ('investigators', {'a':'alice','b':'alice'})]:
            original = self.c[key]; self.c[key]=value; self.write_config()
            with self.assertRaises(ValueError): self.bridge.config()
            self.c[key]=original
        self.write_config(); self.secret.chmod(0o644)
        with self.assertRaises(ValueError): self.bridge.config()

    def test_real_unix_http_server_enforces_the_boundary(self):
        path = str(self.root / 'bridge.sock')
        server = identity.Server(path, identity.Handler); server.bridge = self.bridge
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection('localhost')
        conn.sock = socket.socket(socket.AF_UNIX); conn.sock.connect(path)
        conn.request('POST', '/api/rpc/list_leases', b'{"p":{}}', dict(self.h.items()))
        response = conn.getresponse(); self.assertEqual(response.status,200)
        self.assertEqual(json.loads(response.read())['actor'], 'alice'); conn.close()
        conn = http.client.HTTPConnection('localhost'); conn.sock=socket.socket(socket.AF_UNIX); conn.sock.connect(path)
        conn.request('GET','/auth'); response=conn.getresponse(); self.assertEqual(response.status,401); response.read(); conn.close()


if __name__ == '__main__': unittest.main()
