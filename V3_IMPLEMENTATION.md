# Minimal v3 implementation

## Investigator authorization — 2026-09-22

The Investigator requested a first implementation of `DESIGN_V3.md` on the
`v3-live-collaboration` lineage and explicitly authorized GitHub connector pushes.
After the scope questions, the Investigator chose:

- A minimal end-to-end first pass.
- **No preemption.** Reservations only announce existing work. Concurrent work
  remains allowed; nobody's worker is stopped, replaced, or denied a result.
- No paid model calls in this pass: mock the Jev responses to exercise proper
  policy behavior. Mock results must never be presented as live model evidence.

This authorizes the necessary changes to the kit scripts and shared defaults.
The implementation preserves human-only claim status changes, append-only
records, existing ingest fences, and graceful operation without a reservation
host or model service. No production deployment is authorized or attempted.

Base inspected: `3325395c6dfc72d4e5d8dadac23f04a8fabf90de`.
Implementation branch: `implementation/v3-minimal-20260922`.
The design branch is left unchanged.

## Delivered — 3.0.0-alpha.1

**Claim comparison.** `rectification.py` provides an explicitly mocked Jev call
boundary and validates all four raw probabilities. It compares each new claim
with every visible nonterminal claim in its problem, including fetched peer
branches, without a word-overlap prefilter. Version-bound comparison and dismissal
events are committed in per-investigator append-only rectification streams.
Duplicate candidates, contradictions, and adjudication notices are attached to
both claims, shown in claim pages and catchup, and never change claim status.
Verifying over an open contradiction requires explicit acknowledgment of every
current pair; the promotion event retains those acknowledgments. Dismissal is
specific to the pair's text/condition hashes and flag kind.

Missing, malformed, or unavailable model responses leave deferred coverage, not
an assertion that no conflict exists. Current coverage is derived from current
visible peers: a merge can reveal an unassessed pair, and terminal peers do not
leave stale warnings. Historical attempt records remain unchanged. Negative and
dismissed judgments still count as assessed. Mock provenance remains visible,
and mock cache entries cannot suppress a future live comparison.

**Work notices.** `reservations.py` and `assets/v3/reservations.sql` provide four
PostgreSQL operations: take, release, list, and reap. All participants can read
notices; only their owner can write or close them. Concurrent work is allowed.
No preemption, renewal, or heartbeat exists. Reannouncement cannot rewrite the
promise or extend its deadline. Expired unreturned work is stale; a late packet
is unsolicited, not rejected. Dispatch retains its preregistration in git even
without a database, and ingest/void release the notice. The client forces verified
TLS, bounds connection/request time, and keeps credentials outside shared files.

**Board and CI.** `board.py` renders believed claims, their dependency graph and
conditions, in-flight notices, and recent ingests/decisions, including promised
versus returned work. It provides own-notice browser controls through PostgREST,
not worker or claim-status controls. The lab CI template checks changed claim
versions against visible branches, regenerates views, commits only advisory
metadata/derived files, and produces a static board artifact. Issue synchronization
is idempotent by pair and preserves human text outside its delimited summary.
Mock comparisons are excluded from real GitHub issue publishing.

**Packaging.** Fresh installation and upgrade include the new modules and v3
assets. Skill/plugin versions agree on `3.0.0-alpha.1`. The design documents record
the no-preemption correction. Setup, commands, mock fixtures, security prerequisites,
and deployment boundaries are in `skills/open-lab/assets/v3/README.md`.

## Completed verification

Tested implementation commit:
`7ce97758a66ba52d83baf4355d384659f163a157`.

Tested tree: `a3c7dddb659f8c06449bdc4ec667565c3e5ec6ed`.
This report was added afterward as a documentation-only change.

**215 tests passed, zero failures/errors/skips**, in 172.853 seconds, on the
native GitHub runner with Python 3.12.14 and a disposable PostgreSQL 17 service.
The suite includes 21 v3 behavior tests and six actual PostgreSQL tests, alongside
the existing claim, cascade, committed-record, federation, identity, worker
isolation, ingest, transcript, and upgrade regressions.

```sh
PYTHONPATH=skills/open-lab/scripts python -m unittest discover -s skills/open-lab/scripts/tests -v
```

The native database tests use separate investigator connections and exercise
concurrent notices, shared visibility, own-row writes, peer-release denial,
actor/run-ID forgery, owner/deadline update denial, original preregistration on
reannouncement, stale expiry, late return, own-only reaping, and no public access
or preemption/renewal operations.

The canary uses the real dispatch and ingest commands and replays an actual
calculation, `sum(range(4)) == 6`; only the Jev response is mocked. It verifies
preregistration, the filed PASS/replay result, mock comparison provenance, the
unreserved outcome without a host, persisted symmetric flags, and a clean final
git working tree. Promotion acknowledgment, dismissal persistence, partial model
failure, malformed scores, HTML escaping, issue idempotency, and credential
isolation are also covered. Python compilation and JavaScript syntax checks
passed locally; the 21 focused v3 tests also passed locally after correction.

### Retained native evidence

- Run: https://github.com/mattrobball/lab-book/actions/runs/35759286166
- Job: `106852939892` — completed successfully.
- Artifact: `10709622102`, named
  `kit-evidence-7ce97758a66ba52d83baf4355d384659f163a157`.
- ZIP SHA-256:
  `f5d923e077b3ecc90d82eaf6313bba0388e115baf97629976b06721e8a6303f8`.

The artifact contains stdout, stderr with every test result, command, exit status,
source commit, source archive/checksum, and tool versions. The downloaded ZIP and
source-archive checksums were verified, its source SHA and zero exit confirmed,
and its code/test/SQL bytes checked against the reviewed local files. The native
artifact retention is 14 days; retain it separately for longer-term audit.

### Earlier results are not passes

Initial CI run `35752543599` had an incorrect import environment; `PYTHONPATH`
was fixed rather than treating that run as a baseline pass. Integrated-source run
`35757537623` at `7d31f716d5c19487fd3227198f7228bdfe73fbd5` completed 210 tests with
three failures. Its output remains retained. Those failures exposed stale/current
coverage handling and old heuristic test expectations. The corrected meeting test
also now uses the actual dated meeting actor and asserts the ruling in the minutes,
not merely a claim ID mentioned in an agenda. Five current-coverage controls were
added. The complete 215-test run above supersedes those failures. Interrupted local
runs were not used as passing verification.

## Deliberate first-pass limits

No live Jev adapter or paid calls, no production host deployment, and no implemented
GitHub-login-to-PostgREST-role token bridge. The board must remain private and its
write endpoints inaccessible until authenticated hosting, identity mapping, and
CSRF controls are installed and validated. The database tests exercise real RLS
locally, not production TLS/HTTPS; forced client TLS options are separately tested.
Browser adjudication is an issue/CLI handoff, not a new ledger-writing service.
The graph layout is basic. No browser end-to-end or large-lab performance claim is
made. Mock tests establish policy behavior, not a model's mathematical accuracy.

PR: https://github.com/mattrobball/lab-book/pull/2

All implementation commits are on the dedicated branch. No merge, rebase, or force
push was performed. Temporary exact-object publication helpers were removed from
the final tree; branch publication used the GitHub connector.
