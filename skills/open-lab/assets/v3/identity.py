#!/usr/bin/env python3
"""Private cookie-to-PostgREST bridge. Serve ONLY through the supplied Unix socket.

Authenticate each request at a fixed loopback oauth2-proxy endpoint. Browser
identity headers and bearer tokens are never trusted. No claim-status writes.
"""
import argparse
import base64
import hashlib
import hmac
import http.client
import http.server
import json
import os
from pathlib import Path
import re
import socketserver
import stat
import time
from urllib.parse import urlsplit

RPCS = {'take_lease', 'release_lease', 'list_leases', 'reap_leases'}
LIMIT = 65536


class Denied(Exception):
    def __init__(self, status=403):
        self.status = status


def one(headers, name):
    values = headers.get_all(name, [])
    if len(values) > 1:
        raise Denied(400)
    return values[0] if values else ''


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Denied(400)
        result[key] = value
    return result


def private_json(path):
    path = Path(path)
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o022:
        raise ValueError('identity configuration must not be writable by group or others')
    if path.stat().st_size > LIMIT:
        raise ValueError('identity configuration is too large')
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def endpoint(url):
    value = urlsplit(url)
    if (value.scheme != 'http' or value.hostname != '127.0.0.1' or
            not value.port or value.username or value.password or value.query or value.fragment):
        raise ValueError('internal services must use fixed loopback HTTP endpoints')
    return value


def call(url, method, headers, data=None):
    value = endpoint(url)
    conn = http.client.HTTPConnection(value.hostname, value.port, timeout=3)
    try:
        conn.request(method, value.path or '/', body=data, headers=headers)
        response = conn.getresponse()
        body = response.read(LIMIT + 1)
        if len(body) > LIMIT:
            raise Denied(502)
        return response.status, response.headers, body
    finally:
        conn.close()


class Bridge:
    def __init__(self, config_path, request=call):
        self.config_path = Path(config_path)
        self.request = request
        self.config()  # refuse a broken installation before opening its socket

    def config(self):
        c = private_json(self.config_path)
        origin = urlsplit(c['origin'])
        if (origin.scheme != 'https' or not origin.netloc or origin.path or
                origin.query or origin.fragment or origin.username or origin.password):
            raise ValueError('origin must be an exact HTTPS origin without a path')
        if endpoint(c['auth_url']).path != '/oauth2/auth':
            raise ValueError('auth endpoint must be /oauth2/auth')
        if endpoint(c['postgrest_url']).path not in ('', '/'):
            raise ValueError('PostgREST endpoint must be its root')
        mappings = c['investigators']
        if not isinstance(mappings, dict) or not mappings:
            raise ValueError('explicit investigator mapping is required')
        if any(not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,38}', login) or
               not isinstance(tag, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,30}', tag)
               for login, tag in mappings.items()):
            raise ValueError('invalid login or investigator tag')
        if len(set(mappings.values())) != len(mappings):
            raise ValueError('investigator mappings must be one-to-one')
        secret = Path(c['jwt_secret_file'])
        if secret.stat().st_mode & 0o077 or not secret.is_file():
            raise ValueError('JWT secret must be a private regular file (0600)')
        key = secret.read_bytes().strip()
        if not 32 <= len(key) <= 4096:
            raise ValueError('JWT secret needs 32 or more bytes')
        return c, key

    def authorize(self, headers, config):
        cookie = one(headers, 'Cookie')
        if not cookie or len(cookie) > 8192:
            raise Denied(401)
        # Only a cookie crosses this boundary. No forwarded client identity,
        # bearer token, routing header, or caller-selected auth URL is used.
        status, result, _ = self.request(config['auth_url'], 'GET', {'Cookie': cookie})
        if status != 202:
            raise Denied(401 if status in (401, 403) else 502)
        login = one(result, 'X-Auth-Request-User').lower()
        tag = config['investigators'].get(login)
        if tag is None:
            raise Denied(403)
        return login, tag

    def jwt(self, login, tag, key, origin):
        def enc(value):
            return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=')
        now = int(time.time())
        value = enc({'alg': 'HS256', 'typ': 'JWT'}) + b'.' + enc({
            'role': tag, 'sub': 'github:' + login, 'iss': origin,
            'aud': 'lab-book', 'iat': now, 'nbf': now, 'exp': now + 30})
        return (value + b'.' + base64.urlsafe_b64encode(hmac.new(key, value, hashlib.sha256).digest()).rstrip(b'=')).decode()

    def handle(self, method, path, headers, body=b''):
        config, key = self.config()  # mapping removal takes effect on the next request
        if method == 'GET' and path == '/auth':
            self.authorize(headers, config)
            return 204, b''
        operation = path.removeprefix('/api/rpc/')
        if method != 'POST' or path != '/api/rpc/' + operation or operation not in RPCS:
            raise Denied(404)
        if (one(headers, 'Origin') != config['origin'] or one(headers, 'X-Lab-Board') != '1' or
                one(headers, 'Sec-Fetch-Site') not in ('', 'same-origin')):
            raise Denied(403)
        if one(headers, 'Content-Type').split(';')[0].strip().lower() != 'application/json':
            raise Denied(415)
        if len(body) > LIMIT:
            raise Denied(413)
        login, tag = self.authorize(headers, config)
        try:
            obj = json.loads(body, object_pairs_hook=unique_object)
        except (ValueError, UnicodeError):
            raise Denied(400)
        if not isinstance(obj, dict) or set(obj) != {'p'} or not isinstance(obj['p'], dict):
            raise Denied(400)
        status, _, result = self.request(config['postgrest_url'].rstrip('/') + '/rpc/' + operation, 'POST',
            {'Authorization': 'Bearer ' + self.jwt(login, tag, key, config['origin']),
             'Content-Type': 'application/json'}, body)
        # Database failures may contain SQL/schema/connection details. Do not
        # expose those; preserve HTTP failure, never convert failure to success.
        if not 200 <= status < 300:
            raise Denied(status if status in (400, 401, 403, 404, 409) else 502)
        return status, result


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *_):
        pass  # nginx access log owns request metadata, never cookies/JWT/body

    def do_GET(self):
        self.process()

    def do_POST(self):
        self.process()

    def process(self):
        try:
            self.connection.settimeout(5)
            if one(self.headers, 'Transfer-Encoding'):
                raise Denied(400)
            length = one(self.headers, 'Content-Length') or '0'
            if not length.isdigit() or len(length) > 8:
                raise Denied(400)
            size = int(length)
            if size > LIMIT:
                raise Denied(413)
            body = self.rfile.read(size)
            if len(body) != size:
                raise Denied(400)
            status, result = self.server.bridge.handle(self.command, self.path, self.headers, body)
        except Denied as error:
            status, result = error.status, b'{"error":"request refused"}'
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            status, result = 503, b'{"error":"identity service unavailable"}'
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(result)))
        self.end_headers()
        self.wfile.write(result)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True)
    p.add_argument('--socket', required=True)
    args = p.parse_args()
    bridge = Bridge(args.config)
    path = Path(args.socket)
    if path.exists():
        p.error('socket already exists; let the service manager clean its private runtime directory')
    with Server(str(path), Handler) as server:
        os.chmod(path, 0o660)
        server.bridge = bridge
        try:
            server.serve_forever()
        finally:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
