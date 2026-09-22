# v3 first pass: notices, comparison flags, and a private board

This is a minimal implementation, not a deployed collaboration host. All existing
claim-status and ingest rules remain in force. There is **no preemption, heartbeat,
renewal, exclusive reservation, or automatic promotion**. Notices about existing
work never stop a second person working on the same question.

## Installation

Copy `claims.py`, `run.py`, `rectification.py`, `reservations.py`, and `board.py`
from the kit's `scripts/` into the lab root, and this directory to `v3/`. New labs
and `run.py upgrade` include these files. Upgrading an existing lab still requires
the Investigator's agreement and a small clean dispatch/ingest canary.

No third-party Python package is required. PostgreSQL notices additionally use
`psql`; without a configured host the lab continues normally. The paid Jev adapter
is deliberately not implemented in this pass. No default configuration makes
network model calls.

## Comparisons and human decisions

New claims are compared against every visible nonterminal claim in the same
problem, including investigator branches already fetched into the clone. There
is no lexical prefilter. Fetch colleagues' branches before relying on coverage;
CI checks out all available branch history. A check records the exact claim IDs,
statement/condition hashes, four ordered raw probabilities, and its source.

The policy is: duplicate candidate above 0.9; adjudication queue from 0.5 through
0.9 inclusive; contradiction above 0.7. Flags appear on both claims. Neither
duplicates nor contradictions change status. Both independently discovered
claims can be retained; independence and promotion still use the existing gates.
A refuted/superseded claim is excluded. A changed statement or condition creates
a different pair identity and does not inherit an old dismissal.

Comparison events have their own append-only, per-investigator
`claims/rectification[-tag].jsonl` stream. This keeps non-status events separate
from the existing claim ledger while committing them in the same transaction.
An unavailable service, invalid response, or missing fixture is recorded as
**deferred**, not as absence of a duplicate or contradiction. Retry named claims
explicitly after restoring a judge; there is no automatic all-pairs backfill.

```sh
python claims.py compare --problem demo --new C-alice-001 --new C-alice-002
python claims.py dismiss PAIR_HASH --problem demo --kind contradiction \
  --actor alice --reason 'Different objects; both statements can hold.' \
  --issue 'Issue or meeting reference'
python claims.py set C-alice-001 verified --problem demo --actor bob \
  --evidence R-bob-004 --rests-on none --acknowledge-contradictions PAIR_HASH
```

Repeat the acknowledgment flag for **each current open pair**. Stale or missing
acknowledgments refuse the move before writing status. The promotion event retains
the acknowledged pair identities, raw scores, and provenance. Dismissing a
contradiction does not dismiss a duplicate flag on the same pair, or vice versa.
Closing a GitHub issue is not a ledger ruling.

### Explicit mocked Jev calls

Tests inject `MockJev` at the call boundary, rather than pretending a string
similarity heuristic is a model. A fixture maps `rectification.pair_key(a, b)`
to exactly these fields, where `a` is the lexicographically first claim ID:

```json
{
  "PAIR_SHA256": {
    "same_claim": 0.03,
    "contradictory": 0.97,
    "first_entails_second": 0.01,
    "second_entails_first": 0.02
  }
}
```

Use `claims.load(problem)` to obtain each claim and its exact text hash, then
`pair_key` to compute the fixture key. Configure only in **lab.local.json**:

```json
{"rectification": {"mock_responses": "/absolute/private/path/responses.json"}}
```

Or pass `--mock-responses PATH` to `claims.py compare`. Missing pairs are deferred.
Mock provenance is retained and visibly labeled. Mock comparisons are **never
published as real GitHub issues** and do not establish Jev's accuracy. The future
live adapter must return the same four validated probabilities and a distinct
source name; mock cache entries cannot suppress that live check.

## PostgreSQL notices

Provision PostgreSQL 17 or compatible on the group's own host. Apply
`reservations.sql` **once**, as the database owner, to a dedicated database for
one lab. It creates a schema, member role, row policies, and exactly four functions:
`take_lease`, `release_lease`, `list_leases`, `reap_leases`.

Create one login per already registered investigator tag, grant only
`lab_book_member`, and provision its password securely. The application roles must
not own tables or have SUPERUSER/BYPASSRLS privileges, or membership in peers'
roles. All members may see notices; only the owner may create/release/reap its own
rows. Run IDs and any asserted actor must match the authenticated investigator.
No deadline or owner update is granted. Reannouncement preserves the original
payload and deadline; changing the promise is refused. Reaping removes only the
caller's closed rows; expired unreturned work stays visible as **stale**.

Keep credentials and CA material in a private libpq service file and password
file, outside the repository. Example service definition (no password shown):

```ini
[lab-book]
host=your-lab-host.example
dbname=your_lab
user=alice
sslrootcert=/private/path/lab-ca.pem
```

Set `lab.local.json` to `{"reservations":{"service":"lab-book"}}`, alongside
its other settings. The client forces `sslmode=verify-full`, a 3-second connect
limit, and a 5-second subprocess limit. Use hostssl access rules and SCRAM
passwords or certificates on the server; never expose an unauthenticated DB.
The test database is disposable local plaintext; that does not validate a real
host's TLS configuration. Driver tests separately assert the forced TLS options.

Dispatch commits the preregistration even with no database: question, method,
model, actor, expected shape, brief hash, and resolved worker time budget. Explicit
`## Method` and `## Expected claim shape` sections are optional; legacy briefs
fall back to their kind/metrics or say "not stated" rather than inventing content.
Ingest and void release the notice. A late or missing lease gives an unsolicited
return; it does not reject a valid packet. Database errors reveal no credentials
in the committed record. The worker's existing environment allowlist is unchanged.

## Board and CI

```sh
python board.py --root . --output /private/build/lab-board
```

The output is static HTML, JavaScript, and JSON. It includes the committed source
ID, believed claims/dependencies/conditions, recent decisions and ingests, promises
beside returns, and advisory comparison notices. The graph is a basic deterministic
layout, not a large-graph visualization engine. In-flight data polls PostgREST at
`/api/rpc/list_leases`; service failure is shown as unknown, never inactivity.
The browser can announce an already allocated run and release its own notice.
It never launches a worker, changes claim status, or preempts another person's work.
Browser adjudication is an issue/CLI handoff in this first pass, not a second
ledger-writing service. The board includes the current pair and ruling commands.

Copy `lab-ci.yml` to the **lab repository's** `.github/workflows/lab-ci.yml`. On
push it checks only new/changed local claim versions against all visible peers,
regenerates derived files, commits only comparison metadata and derived views,
and publishes a board artifact. A concurrent push fails rather than being forced.
Issue publishing is idempotent by version-bound pair; the bot updates its bounded
summary and preserves discussion outside it. No model keys or mock fixture are
installed in CI by default, so unconfigured checks correctly remain deferred.

### Private hosting and identity are deployment requirements

Serve both the board (including JSON) and `/api` behind the same authenticated
HTTPS origin. Configure GitHub organization membership as the access list. Do not
publish a private lab's board on public Pages or make its artifact publicly
accessible. Configure PostgREST to expose only `lab_book`; do not grant anonymous
access to its schema/functions or publish the database/REST port directly.

An authenticating proxy alone is **not** a GitHub-to-PostgREST identity bridge.
A trusted server-side component must map the verified GitHub login to the existing
investigator tag and issue a short-lived signed PostgREST role token. Its database
authenticator may switch into those provisioned roles; users must not be able to
choose another role, inject trusted identity headers, or obtain signing material.
Use the same tag for direct PostgreSQL logins and browser actions. Protect writes
against CSRF (strict same-origin/Origin checks and SameSite secure cookies), limit
request sizes, and apply an appropriate CSP. This first pass ships no identity
bridge, TLS certificates, live host deployment, or production security validation.

## Verification

`PYTHONPATH=skills/open-lab/scripts python -m unittest discover -s skills/open-lab/scripts/tests -v`

The new tests exercise actual claim CLI transactions and a native dispatch/ingest
canary with recomputed output; mock only the model/network boundaries. Real RLS,
concurrency, ownership, and expiry tests run against a fresh PostgreSQL service
when `LAB_BOOK_TEST_POSTGRES` names localhost's disposable `labbook_test` database.
Never point the test fixture at a production database. CI retains stdout, stderr,
exit status, source identity, source archive, and checksum even after failure.
