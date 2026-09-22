# v3 alpha.2: review repairs and private collaboration

The kit version is **3.0.0-alpha.2**. This includes the v3 foundation, repaired CI publication, opt-in identity bridge and Jev adapter, and the review fixes. **Linux verification passes; native macOS replay remains blocked at shell startup.** The macOS job is intentionally still red. Nothing deploys a production host or enables paid calls. Notices remain nonexclusive: no preemption, heartbeat, renewal or automatic promotion.

## Upgrade and migration

After reviewing the changes and obtaining the Investigator's agreement, use the lab's existing command:

```sh
python run.py upgrade --from /path/to/skills/open-lab --agree
```

The actual alpha.1 updater is tested, not replaced with today's updater in the fixture. Replay lives at `v3/replay.py`, inside the assets directory that old updater already copies. Fresh installation copies `claims.py`, `run.py`, `rectification.py`, `reservations.py` and `board.py` from `scripts/` into the lab root and this directory into `v3/`. Run a small dispatch and clean replayed ingest afterward. See [REPLAY.md](REPLAY.md) for Linux prerequisites and the outstanding macOS limitation. There is no unrestricted fallback.

Database migration is separate and explicit. Existing alpha.1 hosts use `migrate-alpha1-alpha2.sql` once, as the database owner, after notice owners close and reap their notices. It locks the table and refuses while any row remains; it never rewrites promises or discards notices. Workers are not stopped and research may continue without the notice host. Fresh hosts use `reservations.sql`; never apply the fresh schema over an existing database.

## Comparisons and decisions

New claims are compared with every visible nonterminal claim in their problem, including fetched investigator branches, without a word-overlap prefilter. Raw probabilities retain exact text/condition hashes and provenance. Policy remains `same_claim > 0.9` for duplicate candidates, 0.5 through 0.9 for adjudication, and `contradictory > 0.7` for symmetric contradiction flags. Terminal claims are excluded. Missing/malformed responses stay deferred, not negative judgments. There is no automatic historical all-pairs backfill and no automatic claim-status change.

```sh
python claims.py compare --problem demo --new C-alice-001
python claims.py dismiss PAIR_HASH --problem demo --kind contradiction \
  --actor alice --reason 'Different objects; both can hold.' --issue 'Issue reference'
python claims.py set C-alice-001 verified --problem demo --actor bob \
  --evidence R-bob-004 --rests-on none --acknowledge-contradictions PAIR_HASH
```

Repeat acknowledgment for every current open pair. Verification cannot revise statement/conditions under an old acknowledgment. Restore committed wording or enter a revised proposed claim and check it first. A conflicting visible version requires reconciliation. Dismissal binds to the pair versions and flag kind; closing a GitHub issue alone is not a ruling.

Tests inject `MockJev` at the call boundary. A private fixture maps `rectification.pair_key(a,b)` to exactly `same_claim`, `contradictory`, `first_entails_second`, `second_entails_first`. Order is by claim ID. Configure `rectification.mock_responses` only in `lab.local.json`, or use `claims.py compare --mock-responses PATH`. Missing pairs defer. Mock provenance is visible and excluded from real issue publishing; it cannot suppress a later live comparison. [JEV.md](JEV.md) documents the optional SDK adapter, which requires explicit private configuration, process opt-in, model, key and budgets. No genuine key or paid response is used by verification.

## Publication without a second research writer

Copy `v3/lab-ci.yml` into the research lab's `.github/workflows/lab-ci.yml`. Its repository-wide concurrency group serializes board/issue publication; all issue writers must use it. Queue cancellation/overflow needs an explicit rerun.

CI computes against pinned source refs in a disposable worktree and writes advisory metadata/checkpoints only on **`lab-book/publication`**. It never commits onto `lab/<investigator>`, main or master. Both race orderings preserve investigator work. Competing publication updates use normal fast-forward pushes; a losing publisher retries from a fresh checkout. Historical divergence is not automatically rewritten.

Fetch the publication ref alongside investigator branches before relying on current notices. Claim tools read its comparison/check events without merging scripts or claim-status ledgers. Changed versions and deferred targets remain retryable through the workflow's `retry_claims` input or repeated `--retry CLAIM_ID` arguments to `v3/ci.py`. Checkpoints never assert historical all-pairs coverage. Only successful publication produces a deployable board artifact. Its manifest retains source, visible refs and publication identity; failure evidence retains output and exits. A board is a pinned snapshot, not evidence about an unfetched future push.

## Database and hosting

Use one database per lab, one login per registered investigator tag, and only `lab_book_member` privileges for investigators. They must not own tables, bypass row-level security or belong to peer roles. All members see notices; only the owner writes/closes them. The four operations remain take, release, list and reap. Table constraints also govern direct SQL: run namespace, complete typed payload, run/actor agreement, integer budget bounds and exact deadline. Reannouncement does not extend or rewrite promises.

Store database credentials and CA material in private libpq service/password files outside the repository. `reservations.service` in `lab.local.json` names that service; the client enforces verified TLS and bounded connection/request time. Configure server authentication and hostssl rules deliberately. Dispatch preregistration persists in git without a host; missing or late notices never invalidate a genuine result. Expired unreturned work remains stale until its owner closes it.

```sh
python board.py --root . --output /private/build/lab-board
```

The static board shows claims/dependencies, notices and recent work. PostgREST failure means unknown, not inactivity. The browser only announces/releases its own notices; it cannot dispatch/terminate workers or set claim status. [hosting/README.md](hosting/README.md) documents private HTTPS, the cookie-to-investigator bridge, server-side role tokens and Origin protection. Actual GitHub callback/revocation, host ports/sockets, HTTPS and artifact delivery still need site-specific validation. Synthetic-identity tests do not prove that production path.

## Verification

Durable push/PR workflows cover the full native Linux kit and actual first-pass upgrade, browser/service pilot, real pinned SDK contract with sockets forbidden, and macOS replay controls. The last remains failing at runtime startup. Exact commits, counts, artifact identities and limitations are in `V3_REVIEW_REPAIRS.md` at the repository root. No skipped, incomplete or failed job is counted as PASS.
