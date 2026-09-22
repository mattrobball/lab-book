# v3 — service-owned Git branches

Status: redesign, not implemented. This supersedes both the original multi-writer v3
implementation and the first single-main redesign.

The central decision is:

> **Git remains the durable record and branch structure remains the separation
> mechanism. The lab service is the only Git writer. A single integration runner is
> the only writer to `main`.**

Investigators, Directors, browser clients, CI, and workers do not push lab-record
commits. They submit typed operations to the service. The service writes those
operations to the appropriate service-owned branch. A separate serialized integration
runner advances `main`.

## Why this middle ground

The reviewed v3 failed because investigator processes and automation were independent
Git writers. The fix is not to eliminate branches; branches are useful precisely
because they separate concurrent streams.

The clean boundary is:

- **many logical streams;**
- **one Git-writing service;**
- **one main-integration runner.**

This preserves the federated-notebook model without giving every investigator a Git
credential or making clients solve push races.

## Branch topology

### Investigator branches

Each investigator keeps a durable branch:

```
lab/alice
lab/bob
lab/carol
```

The branch still represents that investigator's notebook and work stream. IDs,
provenance, run ownership and independent conclusions retain investigator identity.

The difference from 2.x is ownership: **Alice does not push `lab/alice`; the service
does, on Alice's authenticated behalf.**

The service serializes mutations to each branch, so two Alice clients cannot race a
Git push. Bob's work proceeds independently on `lab/bob`.

### Automation branch

Service-generated durable advisory events may have their own stream, for example:

```
lab/automation
```

This can contain version-bound comparison results and other machine-authored durable
observations. It contains no human claim-status decisions.

Automation is separated because its provenance and lifecycle differ from an
investigator notebook, not because a second process needs Git write access. The same
service creates these commits.

### Main

`main` is the integrated lab record.

Only the **integration runner** may advance it. No investigator branch, browser client,
CI job, or ordinary service request pushes directly to `main`.

The runner reads the current heads of all active service-owned branches and integrates
them in a deterministic, serialized operation. Straightforward independent additions
can be integrated automatically. Semantic conflicts remain explicit agenda items and
require the existing human ruling/meeting mechanism before the runner records the
resolution on `main`.

The integration runner may be a mode of the same service deployment, but it has a
distinct Git capability: ordinary service workers can advance stream branches; only
the runner can advance `main`.

## Ownership

### The service owns every Git commit

The service is the only holder of Git write credentials for active lab branches. It
creates commits for:

- run preregistration / dispatch;
- ingest and void;
- retained run artifacts and transcripts;
- claim creation and claim-status events;
- contradiction acknowledgments and dismissals;
- notes and meeting decisions;
- automated comparison/check events;
- generated branch-local views;
- explicit shared configuration or upgrade operations.

The authenticated person or agent remains the **actor** recorded in the event.
The service is the Git committer. Git identity is not used as proof of who made a
mathematical decision.

### Clients own computation, not Git mutation

Clients may read/fetch the repository, prepare work, launch workers, collect packets,
and submit typed operations. They do not need Git write credentials.

A local clone may contain arbitrary scratch edits or local commits, but those have no
lab-record status until represented by an accepted service operation.

### CI is read-only

CI tests the software and may render disposable artifacts. It does not mutate lab Git.
There is no CI publication branch written by GitHub Actions.

## Operation protocol

Every mutation request carries:

- a unique request ID / idempotency key;
- authenticated actor identity;
- operation type and typed payload;
- the branch/stream implied by that actor or operation;
- the branch revision observed by the client when relevant.

For an accepted investigator operation the service:

1. authenticates the caller;
2. maps the operation to the caller's `lab/<tag>` stream;
3. reads that branch's current head plus any required integrated/reference state;
4. checks whether the request ID was already accepted;
5. validates the operation against current state;
6. performs any required confined validation;
7. writes the authoritative event/artifact transaction;
8. regenerates affected branch-local derived views;
9. creates one service commit;
10. fast-forward pushes only that stream branch;
11. returns its commit SHA as the durable receipt.

Machine-authored comparisons follow the same process on the automation stream.

No force push and no automatic history rewrite.

Retries are idempotent. If the push succeeded but the response was lost, the same
request ID returns the already-recorded result.

## Integration protocol

The integration runner is the sole writer to `main`.

An integration cycle:

1. snapshots `main` and all active stream heads;
2. verifies that every candidate head descends from the last integrated point for that
   stream, or explicitly identifies a migration/divergence;
3. folds the append-only records across the selected stream heads;
4. regenerates the integrated views;
5. detects semantic conflicts requiring a human ruling;
6. if no unresolved ruling blocks integration, creates the integration commit;
7. fast-forward pushes `main`;
8. records the exact source stream heads integrated.

The runner does **not** require investigators to stop working. New commits can land on
their branches while an integration is in progress; those simply belong to the next
cycle because the current cycle is pinned to exact head SHAs.

A human meeting/ruling can itself be submitted as a typed service operation to a
meeting stream or designated investigator stream and then integrated by the runner.
The runner records decisions; it does not invent them.

## Concurrency

Concurrency is separated at two levels.

**Within a branch:** the service serializes mutations, eliminating client push races.

**Across branches:** Git branches permit Alice and Bob to progress independently. The
integration runner later combines their exact heads into `main`.

This is preferable to serializing every durable mutation globally: unrelated work need
not wait merely because it belongs to a different investigator.

Operations that depend on current mathematical state still use optimistic validation.
For example:

- a claim-status change must bind to the exact claim version the actor saw;
- contradiction acknowledgment must name current pair versions;
- closing a run must match its owner/current state;
- a stale operation is refused rather than silently applied to newer text.

## Runs

### Dispatch

Dispatch is a typed service operation on the investigator's branch. The service commits
the preregistration before returning the run information. PostgreSQL then receives the
soft in-flight notice.

Only after the durable branch commit succeeds does the client launch the worker.

### Worker execution

Workers run without Git/database/provider/service-writer credentials.

### Ingest

The returned packet is submitted to the service. Authoritative replay/validation runs
behind the service boundary in confinement. The verdict, packet evidence, transcript
and proposed claims land atomically on the investigator's branch.

A late result remains evidence. Missing/stale notice state may mark it unsolicited but
does not invalidate it.

## PostgreSQL

PostgreSQL is private soft/rebuildable service state:

- in-flight notices and deadlines;
- presence/session data;
- scheduling and queues;
- caches and materialized lookup indexes.

Clients do not connect directly to PostgreSQL. Browser and agent writes use the same
service API.

Losing PostgreSQL must not lose an accepted durable fact. The durable branch histories
allow reconstruction of accepted operations and comparison work.

No preemption, heartbeat or renewal is introduced. Notices remain nonexclusive.

## Rectification

The four raw comparison judgments remain unchanged:

- `same_claim`;
- `contradictory`;
- `first_entails_second`;
- `second_entails_first`.

Comparison work is scheduled by the service after durable claims appear. Results are
committed by the service to the automation stream, version-bound with provenance.

The integration runner brings those advisory events into the integrated view. Model
output never changes claim status. Human dismissals/promotions/refutations/
supersessions remain separately authenticated service operations.

GitHub Issues may mirror adjudications for discussion, but they are not authoritative.

## Board

The board reads:

- `main` for the latest integrated durable state;
- optionally newer stream heads when presenting "since last integration" activity;
- PostgreSQL for live in-flight notices.

Board writes are typed service operations. There is no separate browser-to-Postgres
mutation path.

## Authentication and authorization

There is one public mutation boundary: the service.

- browser identity maps to an investigator;
- agent credentials map to the same investigator;
- ordinary authenticated operations may advance only their authorized stream;
- automation jobs may advance only the automation stream;
- only the integration runner identity may advance `main`;
- humans, agents and CI have no Git write credentials;
- PostgreSQL/provider credentials remain service-side.

Repository protections should enforce these distinctions.

## Git's role

Git now does exactly what it is good at:

- immutable content-addressed history;
- independent append streams through branches;
- cheap replication and audit;
- exact source-head snapshots for integration;
- durable artifacts and provenance;
- a readable record even without the service.

The service handles authenticated mutation. Branches handle separation. The runner
handles integration.

## Availability

The service is required for new **durable** lab mutations. Clients do not bypass an
outage by pushing Git themselves.

Already-dispatched workers may continue computing and retain packets locally for later
submission. Read-only work can continue from fetched branches.

Because branches are separate, service recovery does not require reconstructing one
global mutation queue: each stream resumes from its durable head.

## Migration from current v3

Do not rewrite existing history.

1. Preserve current investigator and publication refs.
2. Establish the service as the only Git credential holder for active lab streams.
3. Retain/create `lab/<tag>` as the active investigator streams.
4. Convert durable automation output to a service-owned automation stream.
5. Record the imported head SHA for every stream.
6. Configure the integration runner as the sole writer to `main`.
7. Remove Git write credentials from humans, agents and CI.
8. Run one pinned integration cycle and record exactly which heads entered `main`.

Existing divergent material is reconciled explicitly; migration must not silently
choose a branch.

## Build order

1. **Service Git writer.** Typed operations, authentication, idempotency and
   fast-forward mutation of service-owned investigator branches.
2. **Integration runner.** Exact-head snapshotting, deterministic folding, semantic
   conflict detection, and sole-writer advancement of `main`.
3. **Claims and notes.** Move permanent local CLI mutations behind service operations.
4. **Run lifecycle.** Service-owned preregistration, confined replay, ingest/void and
   artifact retention.
5. **Coordination.** Put notice access behind the service; keep PostgreSQL private.
6. **Rectification.** Service-owned automation stream and issue mirroring.
7. **Board.** Read integrated plus live state and write through the same API.
8. **Migration/pilot.** Remove direct Git writers and run several concurrent clients.

## Acceptance criteria

The redesign is complete when:

- two investigators can commit durable work concurrently without Git credentials;
- their service-owned branches advance independently;
- every accepted operation returns the exact stream commit SHA;
- retries cannot duplicate an accepted operation;
- only the integration runner can advance `main`;
- an integration commit records the exact stream heads it incorporated;
- a stream may advance during integration without corrupting that integration;
- stale mathematical operations are rejected against newer versions;
- PostgreSQL loss cannot erase accepted durable records;
- worker/replay execution cannot access service credentials;
- CI has no lab-state Git mutation permission;
- the whole record remains understandable from a read-only clone;
- service outage never creates an alternate client-written Git history.

## Deliberately unchanged policy

This redesign changes ownership and Git topology, not mathematical decision rules:

- no preemption;
- model outputs are advisory;
- raw probabilities/provenance are retained;
- open contradictions require explicit current-version acknowledgment for promotion;
- models do not make claim-status decisions;
- human rulings remain attributable and durable.
