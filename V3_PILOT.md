# v3 pilot continuation

## Investigator authorization — 2026-09-22

The Investigator approved: integration fixture and CI hardening first; hosting/identity and an opt-in Jev adapter as separate parallel workstreams afterward. This authorizes the necessary kit and CI changes on dedicated branches, with incremental GitHub connector pushes. No merge, force push, production deployment, or paid model calls are authorized here.

Base rechecked: `0a0ac1b3404f731edce6c25ec6280eb36e9c9482` on `implementation/v3-minimal-20260922`. The design branch and first-pass branch remain untouched.

The integration fixture exercises two independent investigator clones and real services. Notices are nonexclusive announcements; there is no preemption. Hosting/identity and the live adapter remain separately reviewable, branched from the tested integration commit below.

## Implemented

`skills/open-lab/assets/v3/ci.py` supplies a clean-checkout publication command. It tracks observed claim versions and deferred targets in branch-scoped checkpoints, with a separate append-only comparison stream per publisher. A skipped event or a deferred model call remains retryable without editing claim text. First installation establishes a baseline, not an automatic historical all-pairs backfill. Explicit unknown retry IDs refuse rather than silently succeed.

The lab workflow serializes publication across all investigator branches, queues pending work, and checks the current branch head. Publication uses ordinary fast-forward pushes only. A concurrent investigator push is preserved; retry starts from a fresh checkout, never from a force push or automatic rebase. The staging allowlist excludes status ledgers, investigator notes, and shared settings. Source archives, ref identities, commands, output, and exit status are retained on failures; only successful publication produces a board artifact. The board records both source and published identities.

The native pilot uses two clones, two investigator roles, actual PostgreSQL with verified database TLS, actual PostgREST, actual nginx, and two Chromium browser contexts. Jev judgments are explicit fixtures. Synthetic nginx Basic credentials provide the fixture's browser identities; this is deliberately **not** a simulation or verification of a real GitHub OAuth callback.

The completed scenario verifies: Bob sees Alice's notice and may still start work; neither may release the other's notice; own notice release does not stop a worker; both valid packets are ingested with actual recomputation; a mocked contradiction appears symmetrically and a human dismissal persists; a stale notice's late packet remains accepted; database outage does not block dispatch or ingest; both investigator records finish clean. The artifact contains the board screenshot and both synthetic committed records.

## Completed verification

Tested code commit: `f6c022ca84126712c11ef185769e284972b9a836`.
Tested tree: `7855fa6ccfdd1cbece0f3d7cac2df91fc5b9d476`.
This report is a subsequent documentation-only change.

- Full native kit suite: **224 tests, zero failures/errors/skips**, 175.837 seconds. Includes the original 215 tests, nine new CI tests, and six real PostgreSQL tests within the suite.
- Separate assembled pilot: **one complete end-to-end scenario passed**, 19.137 seconds.
- The focused nine CI tests also passed locally, including deterministic peer-clock skew and a real concurrent Git push followed by a fresh successful retry.

Commands:

```sh
PYTHONPATH=skills/open-lab/scripts python -m unittest discover -s skills/open-lab/scripts/tests -v
python skills/open-lab/integration/pilot.py -v
```

The pilot requires its disposable native dependencies and `LAB_BOOK_PILOT_EVIDENCE`, provisioned by `.github/workflows/v3-pilot.yml`. It cannot be pointed at a production database.

### Retained evidence

| Job | Run | Artifact | ZIP SHA-256 |
|---|---|---|---|
| Kit | 35769397079 | 10713686913 | `46b619c36e2978ae834dd06b671c66980ca0c2e36c5a8726b31a4f2c09a47939` |
| Native pilot | 35769397135 | 10713497597 | `0a18f911bb67981ef010c12ed57863ff54867adece21a41dd754f6a1b7d7a462` |

Run links:
- https://github.com/mattrobball/lab-book/actions/runs/35769397079
- https://github.com/mattrobball/lab-book/actions/runs/35769397135

Both artifacts were downloaded through the GitHub connector. ZIP and retained source-archive checksums, source commit, zero exit, and complete test output were checked. The reviewed local code/configuration bytes match the retained source archives. Kit artifacts currently expire after 14 days; the native pilot retains evidence for 30 days.

### Earlier failure is retained

The first 224-test run, `35768597947` at `8ec402a4db3405405606f79dd8b93ff4c57fe130`, had one failure. A same-second peer check could hide this publisher's newly deferred check when global wall-clock order selected the apparent latest event. The fix reads this publisher's own append order; the regression now deliberately skews the publisher clock. The red artifact `10713600883` remains available. The first native browser pilot passed independently, but that pass was not treated as a passing full suite.

## Installation and remaining boundaries

Install the updated `v3/` assets into a lab and copy `v3/lab-ci.yml` to that lab's `.github/workflows/lab-ci.yml`. Keep all issue writers in its repository-wide serialization group. Manual retries use the workflow's `retry_claims` input, or repeated `--retry` arguments to `v3/ci.py`. A publication interrupted by a concurrent push must be restarted from the current head. Queue overflow or manual cancellation needs an explicit rerun; no claim of infinite durable Actions queueing is made.

The tests exercise the real publication code with local bare Git origins. They do **not** create real GitHub adjudication issues or prove race freedom against arbitrary publishers outside the workflow lock. They do not deploy a board artifact to a host. The native pilot's browser ingress is loopback HTTP with synthetic identities; PostgreSQL TLS is verified, but production HTTPS, GitHub OAuth, host firewalls, and real organization revocation are outside this fixture.

No real mathematical claim was promoted, no paid model request was made, and no production state was touched. The hosting/identity and Jev branches are separate continuations, not merged into this branch.
