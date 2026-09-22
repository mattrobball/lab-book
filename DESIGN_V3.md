# v3 — single-writer lab service

Status: redesign, not implemented. This supersedes the multi-writer v3 design and
the repair architecture in which investigators wrote research branches while CI
wrote a publication branch. Those implementations remain useful evidence, but they
are not the target architecture.

The central decision is simple:

> **Git is the permanent record, but Git is not the client write protocol. The lab
> service is the only writer to the canonical Git repository.**

Investigators, Directors, browser clients, CI, and workers do not push lab-record
commits. They submit typed operations to the service. The service validates each
operation against the current record, commits the accepted mutation, and returns the
resulting record revision.

## Why change the architecture

The previous v3 split Git mutation between investigators and automation. That made
correctness depend on coordinating independent Git writers. The review found the
fundamental failure: a successful CI commit could advance an investigator branch and
make the investigator's next normal push diverge.

Moving CI metadata to a separate branch repaired that specific race, but it left Git
branch topology doing work that the service is better placed to do. Once a trusted
service already authenticates actors, validates operations, owns shared state, and
writes some durable events, partial Git ownership adds complexity without adding a
useful trust boundary.

The redesign removes that split.

## Ownership

### The service owns every durable mutation

The service is the sole remote Git writer for the lab record. It owns:

- run preregistration / dispatch records;
- ingest and void records;
- run artifacts and retained transcripts;
- claim creation and every claim-status event;
- contradiction acknowledgments and dismissals;
- investigator notes and meeting decisions;
- automated comparison/check events;
- generated human-readable views;
- shared configuration and explicit kit upgrades.

The authenticated human or agent remains the **actor** of the operation. The service
is the Git writer/committer. Actor identity is recorded in the event itself and in the
operation receipt; Git credentials are never used as proof of who made a mathematical
decision.

### Clients own computation, not the record

A Director or human client may:

- read/fetch the canonical record;
- prepare a brief;
- run workers locally;
- collect a returned packet;
- submit typed operations to the service;
- keep arbitrary local scratch state.

A client does not need write credentials for the Git remote and does not make a
canonical commit. Local scratch commits, if someone uses them, have no lab-record
meaning.

### CI is read-only

CI verifies releases, exercises the service, and may render disposable artifacts.
It does not commit lab state, comparison results, generated views, or checkpoints.
There is no CI publication branch in the target architecture.

## The permanent record

The service writes one canonical branch, initially **main**. Branch topology is no
longer the model of disagreement.

The canonical branch contains the whole durable lab record, including conflicting
claims, open contradictions, failed runs, and human rulings. Consensus is represented
by claim status and meeting/ruling events, not by whether a fact has been merged into
a special branch.

Per-investigator branches from the 2.x design become legacy read-only history. The
investigator tag remains useful in IDs and provenance, but no longer exists to prevent
Git writer collisions.

Each accepted mutation is one atomic record transaction: all authoritative event
changes, retained artifacts, and derived Markdown that belong to that operation land
in one service-created commit. A cascade of claim-status changes is one operation and
one commit.

## Operation protocol

Every mutation request carries:

- a globally unique client request ID / idempotency key;
- the authenticated actor;
- the operation type and typed payload;
- the record revision the client observed when that matters.

For an accepted operation the service:

1. authenticates the caller and maps it to an investigator identity;
2. reads the current canonical Git HEAD;
3. checks whether the request ID is already present;
4. validates the operation against current state;
5. performs any required sandboxed validation;
6. writes the authoritative event/artifact transaction;
7. regenerates affected derived views;
8. creates a service commit;
9. fast-forward pushes the canonical branch;
10. returns the commit SHA as the durable receipt.

There is no force push and no automatic rebase of record history.

A retry with the same request ID is idempotent. If the push succeeded but the response
was lost, the service finds the already-recorded request and returns the same durable
result rather than repeating the operation.

The service does not acknowledge a durable mutation as complete until the canonical
Git remote contains the commit. PostgreSQL caches may accelerate idempotency lookup,
but Git is sufficient to reconstruct the answer after those caches are lost.

## Concurrency

The service serializes Git mutation. There is one logical commit queue for the
canonical record.

Serialization does not mean every request blindly succeeds on the newest HEAD.
Operations that depend on a particular observed state use optimistic validation:

- claim status changes must still apply to the exact claim version the caller saw;
- contradiction acknowledgment must name the current pair versions;
- closing a run must match its current owner and state;
- a stale operation that is no longer valid is refused with the current revision.

Append-like operations may be accepted after revalidation even if another commit
landed first.

This moves concurrency control from Git push races into a typed application boundary,
where the lab's actual invariants are visible.

## Runs

### Dispatch

A normal run begins with a service operation. The service:

- allocates/validates the run ID;
- records the brief hash, question, method, model, expected claim shape and budget;
- commits that preregistration;
- announces soft in-flight state in PostgreSQL;
- returns the durable commit revision and run information.

Only then does the client launch the worker.

This makes preregistration genuinely prior to the experiment instead of a local commit
that may or may not reach the remote.

### Worker execution

Workers may run on investigator machines or other execution hosts. They receive only
the inputs and environment intended for the worker. They do not receive Git, database,
model-provider, or service-writer credentials.

### Ingest

The client uploads the returned packet to the service. The service, not the Director
process, performs the authoritative ingest validation and replay in a confined
environment. It then commits the verdict, replay evidence, retained packet/transcript,
and any proposed claims as one durable transaction.

A late result is still real evidence. Expired/missing notice state may mark it
unsolicited but does not invalidate an otherwise valid packet.

## Service availability

This redesign intentionally changes the old failure model.

**The service is required for new canonical mutations.** In particular, a normal new
dispatch cannot be durably preregistered while the service is unavailable.

Already-dispatched workers may continue computing while the service is down, and their
packets can be retained locally and submitted when it returns. Read-only work can
continue from a fetched record. A future offline submission queue may improve this,
but clients do not bypass the service by pushing Git directly.

This is the cost of having one mutation authority instead of several partially
coordinated writers.

## PostgreSQL

PostgreSQL is internal service state, not a client-facing source of truth.

It holds high-churn/rebuildable state such as:

- in-flight notices and deadlines;
- presence/session information;
- operation scheduling and caches;
- materialized lookup indexes.

Losing PostgreSQL must not lose an accepted mathematical fact or accepted experiment.
The service can rebuild durable operation identity and lab state from Git.

Clients do not receive direct database credentials. Browser and agent requests use the
same service authentication boundary. PostgreSQL row policies may remain as
defense-in-depth for service-selected actor roles, but they are not a second public API.

No preemption, heartbeat, or renewal is introduced. Notices remain advisory and
nonexclusive.

## Rectification

Claim comparison remains advisory. The four raw judgments are unchanged:

- `same_claim`;
- `contradictory`;
- `first_entails_second`;
- `second_entails_first`.

The service schedules comparison work after a claim version enters the durable record.
Ingest does not wait on a paid or unavailable model service.

Comparison coverage is derivable: a claim version with visible nonterminal peers and
no comparison event for a pair is pending/deferred. Therefore a lost PostgreSQL queue
can be reconstructed from Git.

When comparison completes, the service writes another canonical commit containing the
version-bound raw scores and provenance. Model output never changes claim status.
Human dismissals, promotions, refutations, and supersessions are separate authenticated
service operations.

GitHub Issues may mirror open adjudications for discussion, but an issue is not
authoritative. A ruling becomes real only when the service commits the corresponding
record event.

## Board

The board is a read view over:

- canonical Git state for durable claims/runs/rulings/comparisons;
- PostgreSQL for current in-flight notices.

Browser writes go to the same service API as CLI/agent writes. There is no separate
PostgREST mutation path and no separate browser-to-database identity bridge.

The board may request: announce/release work, submit rulings, or other explicitly
allowed typed operations. It cannot invent an actor identity, write Git directly, or
circumvent the same service validation used by CLI clients.

## Authentication and authorization

There is one public identity boundary: the service.

- Human browser authentication maps a verified forge identity to an investigator.
- Agent credentials map to the same investigator identity.
- Every operation is authorized in terms of the authenticated actor.
- The Git remote accepts canonical writes only from the service identity.
- PostgreSQL and provider credentials remain service-side.

Branch protection should reject direct writes to the canonical record from humans,
agents, and CI.

## Git as storage, not coordination

Git still earns its place because it gives the lab:

- immutable, content-addressed history;
- cheap complete replication;
- inspectable diffs;
- durable run/claim artifacts;
- a repository that remains readable without the service;
- straightforward backup and archival.

What Git no longer does is arbitrate concurrent writers. That is the service's job.

## Migration from the current v3 branches

Do not rewrite existing history.

1. Preserve all existing investigator, implementation and publication refs read-only.
2. Choose the reconciled/current record as the service's canonical starting revision.
3. Commit a migration event that records every imported legacy head SHA and the
   migration policy.
4. Enable branch protection so only the service may advance the canonical branch.
5. Remove Git write credentials from investigators, agents and lab CI.
6. Configure clients to submit mutations to the service.
7. Keep legacy refs available for audit; they are not active write streams.

Any divergent legacy facts that have not been reconciled are imported or ruled on
explicitly before the old write paths are disabled; migration must not silently choose
between them.

## Build order

1. **Single-writer core.** Authenticated typed operation envelope, idempotency,
   current-HEAD validation, atomic commit construction, fast-forward publication and
   durable receipts.
2. **Claims and notes.** Move permanent `claims.py`/note mutations behind service
   operations while retaining current policy semantics.
3. **Run lifecycle.** Service-owned preregistration, packet upload, confined replay,
   ingest/void and artifact retention.
4. **Coordination.** Move notice access behind the service; Postgres becomes private
   soft state.
5. **Rectification.** Service-owned asynchronous comparison scheduling and commits;
   issue synchronization becomes a derived integration.
6. **Board.** Read/write through the same authenticated API.
7. **Migration.** Import legacy heads, protect the canonical branch, remove direct
   writer credentials, and run a multi-client pilot.

## Acceptance criteria

The redesign is complete only when all of these are true:

- two investigators can mutate the lab concurrently without either having Git write
  credentials;
- every accepted durable operation returns a canonical commit SHA;
- retrying an accepted request cannot create a second commit;
- service restart and PostgreSQL loss cannot erase an accepted record;
- stale-state claim/status operations are rejected rather than applied to new text;
- worker/replay execution cannot access service credentials;
- CI has no Git mutation permission for lab state;
- direct pushes to the canonical branch are rejected for non-service identities;
- the full record remains intelligible from a read-only clone;
- service unavailability never causes a client to silently create an alternate
  canonical Git history.

## Deliberately unchanged mathematical policy

The redesign changes ownership and transport, not the mathematical decision rules:

- no preemption;
- duplicate/contradiction model outputs are advisory;
- raw probabilities and provenance are retained;
- open contradictions may be promoted only with explicit current-version
  acknowledgment;
- models do not make claim-status decisions;
- human rulings remain attributable and durable.
