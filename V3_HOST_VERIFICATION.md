# Hosting/identity verification — 2026-09-22

The Investigator authorized hosting/identity as an independent continuation after the integration/CI foundation. This branch is based on tested integration commit `f6c022ca84126712c11ef185769e284972b9a836`. It does not merge the separate Jev adapter or deploy a production host.

## Implemented

A private Unix-socket bridge verifies a browser's cookie at a fixed loopback OAuth2 Proxy endpoint, maps the returned GitHub login to a provisioned investigator tag, and forwards a server-only 30-second PostgREST role token. PostgreSQL row-level permissions remain authoritative. Browser-supplied bearer/identity headers cannot choose a role. Exact Origin, bounded JSON, duplicate-header/key rejection, and an explicit four-operation allowlist protect requests. Unknown mappings, invalid sessions, auth outages, and malformed requests fail closed. Mapping removal applies on the next request.

The hosting templates cover nginx HTTPS/private static files, OAuth2 Proxy organization access, PostgREST, the identity mapping, and a restricted systemd service. No preemption or claim-status endpoint is added. Configuration, credentials, TLS certificates, and artifact deployment must still be provisioned deliberately.

## Completed tests

Tested code commit: `4c644f35b6984cc46f8f278823449f97041dd92c`.
Tested tree: `9e5a3d023067bb256d0ef1b79d6975df863b644e`.
This report is a subsequent documentation-only change.

**233 native kit tests passed, zero failures/errors/skips**, in 176.757 seconds. This includes the 224-test integration baseline plus nine new identity tests. Those tests exercise identity selection, signed token role/lifetime/audience, browser-header spoofing, mapping removal, missing/invalid sessions, auth outages, Origin controls, payload limits, invalid configuration, and the actual Unix HTTP server. Auth-provider and PostgREST responses are controlled boundaries in these identity tests.

Run: https://github.com/mattrobball/lab-book/actions/runs/35770445602
Artifact: `10713737604`, `kit-evidence-4c644f35b6984cc46f8f278823449f97041dd92c`.
ZIP SHA-256: `826f78cd15f70e2b6a8c283f742ea427490037ee4d9db8d1869d2995d3f44784`.

The artifact was downloaded through the GitHub connector. ZIP and source-archive checksums, source SHA, zero exit, complete per-test output, and reviewed source bytes were verified. Retention is 14 days.

The existing assembled native pilot also completed successfully on this branch in run `35770445585`. That fixture still uses synthetic nginx identities. It is evidence for the underlying PostgreSQL/PostgREST/browser workflow, **not** for a full GitHub-login-to-bridge-to-browser deployment.

Locally, all nine focused identity tests passed, including the real Unix HTTP test. An instantiated nginx template with disposable local certificate paths passed `nginx -t`; that is syntax validation, not production HTTPS or OAuth verification.

## Deployment boundaries

No real GitHub OAuth callback, organization removal, public HTTPS endpoint, firewall, or CI-to-host artifact transfer was exercised. These remain required before exposing browser writes. Keep OAuth2 Proxy and PostgREST loopback-only, and the bridge on its restricted Unix socket.

The identity mapping uses exact GitHub logins, not immutable numeric account IDs. Administrators must review/remove mappings when usernames change or users leave. Mapping revocation is immediate; organization membership removal is bounded by the configured five-minute session lifetime. Use identical private ASCII JWT-secret files for bridge and PostgREST (for example a freshly generated 64-character random hexadecimal value), without whitespace; never commit or log them.

No paid model calls, production writes, merges, rebases, or force pushes were performed. Setup and trust boundaries are documented in `skills/open-lab/assets/v3/hosting/README.md`.
