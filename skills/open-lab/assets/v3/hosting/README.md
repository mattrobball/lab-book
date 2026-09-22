# Private hosting and identity — opt-in installation

This branch adds a real cookie-to-role bridge, not a second authorization model.
It changes no worker or claim-status operation. Nothing here deploys or enables a
host automatically. Keep service ports private until the complete deployment is
validated. The Investigator authorized this implementation on 2026-09-22.

## Connection and trust

nginx terminates HTTPS and protects every board file, including `record.json`.
Its internal auth subrequest goes through `identity.py` on a restricted Unix
socket. For each request the bridge calls the fixed loopback oauth2-proxy
`/oauth2/auth` endpoint with **only the cookie**. It ignores browser bearer and
identity headers. Only the successful auth response's GitHub login selects an
explicitly provisioned investigator tag. The bridge signs a 30-second, audience-
bound role token and forwards it to loopback PostgREST; that token never reaches
the browser. PostgreSQL's existing row policies remain the write authority.

For GitHub, OAuth2 Proxy 7.15.0 sets session.User to user.Login. Configure the exact
lowercase GitHub login in `investigators`, mapped to the existing database role
and `R-<tag>-NNN` tag. The mapping is one-to-one and reread on every request.
Example: `{"github-alice":"alice","github-bob":"bob"}`. **This is a login
mapping, not an immutable numeric GitHub-account-ID binding.** Administrators
must remove/review mappings when a login changes or an investigator leaves.
Mapping removal is immediate; organization-membership removal is bounded by the
five-minute OAuth session lifetime in the supplied configuration.

POSTs require the exact configured HTTPS Origin, JSON, `X-Lab-Board: 1`, and
same-origin fetch metadata when present. Duplicate headers/JSON keys, large
bodies, unknown operations, missing sessions, failed auth, and unknown logins are
refused. Cookies and client identity headers are not forwarded to the database.
Errors and logs omit tokens, cookie contents, request bodies, and database errors.
No CORS or anonymous database role is enabled. There is no preemption endpoint.

## Install deliberately

Provision PostgreSQL as described in the parent README. Create a separate LOGIN
NOINHERIT authenticator, with membership in exactly the registered investigator
roles; those roles keep only `lab_book_member`. Do not grant superuser, BYPASSRLS,
table ownership, or peer memberships to investigators.

Copy the templates, replace their explicit placeholders, and install the bridge
as `/opt/lab-book/v3/identity.py`. Use `identity.json` with a nonempty registered
mapping; the empty example deliberately refuses startup. Create a random JWT
secret of at least 32 bytes, with matching private 0600 copies owned by the bridge
and PostgREST service users. Keep OAuth application and cookie secrets in private
files as well; never place any secret in git, arguments, board artifacts, or logs.
The OAuth application callback must exactly match the configured HTTPS callback.
OAuth cookie-secret-file expects raw random bytes of an accepted AES key length.

Serve a **successfully published private** CI board artifact from
`/srv/lab-book/board`, owned by the deployer and read-only to nginx. Retain
`publication.json` with the source and visible-ref identities. Do not deploy a
partial artifact or a private lab to public Pages. This first hosting pass does
not transfer artifacts or select a cloud host for you.

Keep nginx as the only publicly reachable service. Bind OAuth2 Proxy and
PostgREST to loopback. The bridge's Unix socket directory must be writable only
by its service user and accessible only to nginx's group; the unit assumes the
Debian/Ubuntu `www-data` group. Use verified PostgreSQL TLS and real HTTPS
certificates. Validate edited configuration with `nginx -t` and
`oauth2-proxy --config-test --config=...` before enabling services. Do not add
OAuth user allowlists that bypass organization restrictions or skip-auth options.

## Verification and limits

The contract tests run the real bridge and a real Unix HTTP server; auth and
PostgREST responses are controlled network boundaries. They establish identity
selection, token signature/lifetime/audience, revocation, spoofing rejection,
CSRF checks, input limits, and fail-closed behavior, **not a live GitHub login**.
The independent native pilot establishes the actual PostgreSQL/PostgREST/browser
notice loop with synthetic nginx identities. A production OAuth callback, public
TLS certificate, organization revocation, and host firewall still require
site-specific validation. Do not equate either test with a deployed secure host.

Primary references inspected 2026-09-22:
- https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/
- https://github.com/oauth2-proxy/oauth2-proxy/blob/v7.15.0/providers/github.go
- https://postgrest.org/en/stable/references/auth.html
