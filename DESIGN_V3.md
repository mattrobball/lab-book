# v3 — a lab several people and agents work in at once

Status: design, not built. The decisions behind it are in `DESIGN_QUEUE.md` §3,
with the date each was taken. This page is the specification.

## What is different

2.x assumes people work apart and meet later. Everyone has their own branch, their
own numbers and their own ledger; `main` is written only at a meeting, where the
Director reads out what the records disagree about and the room decides.

That is the right design for a group that meets weekly. It is the wrong one for half
a dozen people and agents working the same problem in the same hour, because nothing
is visible until a run is ingested — by which time the work is already spent.

v3 adds three things and changes nothing else: a reservation taken before a run
starts, a check that compares every new claim against the record, and a page that
shows the lab as it stands.

## The failures it prevents

- Two agents spend an hour each on the same question because neither could see the
  other start.
- A claim is shaped after the data is seen, and nothing on record says what the run
  set out to test.
- A run goes quiet and nobody notices until the next morning's catchup.
- The same statement arrives twice and the only warning is a line printed to one
  person's terminal at ingest.
- Two claims assert different values for the same quantity, both stand at `verified`,
  and the record shows nothing. This is not hypothetical: the check found such a pair
  on its first pass over an existing record, where the later claim's own text said the
  earlier one was false.
- The lab's state is readable only by running scripts in a clone, so a colleague who
  wants to see where things stand has to become an operator first.

## Three substrates, by job

Facts, coordination and human decisions have different lifetimes. Keeping them in one
store is the mistake that makes each of them worse.

| | Lives in | Why there |
|---|---|---|
| Claims, runs, ledgers, transcripts | git, as now | The record is what is committed. Unchanged. |
| Reservations, presence | Postgres, on the group's host | High churn, worthless after a crash, must never pollute the record. |
| Duplicate and contradiction rulings | GitHub Issues | A decision that needs discussion and an author. |
| Derived files, the checks | CI on push | Impartial, on nobody's laptop, cannot be skipped. |

Postgres is installed on the host, not managed. The lease table is soft state: losing
it costs nothing, because agents re-announce. The durability a managed service sells
is durability this design deliberately does not need, and everything that must survive
is already in git.

**If the host is unreachable, agents work anyway and reconcile later.** A reservation
is an optimisation, never a gate. The lab must not stop because a machine is asleep.

## Reservations

A reservation is a preregistration. It is taken before the run starts and names the
question, the method, the actor, the model, the expected claim shape, and the budget.

It earns its keep with one person working alone — it is the record of what a run set
out to test, which is what makes a claim shaped after the fact visible — so it is not
only a device for avoiding collisions.

- Taken at dispatch. Deadline is the brief's budget.
- Released at ingest or void.
- Past its deadline with no packet: shown as stale.
- No heartbeat, no renewal, no checkpoints. Every in-flight signal considered was
  either uninformative or a change to the brief template that workers would have to be
  asked to honour. A dead agent's lease sits until its deadline rather than being
  reaped early; at six participants that is someone glancing at the board.
- Every dispatch and ingest carries its lease number. An agent can pause inside a long
  model call, lose its lease, and return with a real packet. That packet is not
  rejected — it files as unsolicited, and if a successor covered the same ground the
  pair goes to rectification.

Built as a schema and four SQL functions — take, release, reap, list. No API server.
Agents connect to Postgres directly, one role per person, over TLS, with row-level
security confining a person to their own rows. Postgres authentication is the
authentication, and it revokes cleanly.

## Rectification

**Duplicates are not waste.** Two agents that independently reach the same claim,
neither aware of the other, are the second actor the promotion rule already demands.
Rectification promotes the pair as independent corroboration; it discards nothing.

The old test compared normalised word sets at 0.6 overlap and warned at ingest. It
cannot be repaired by moving the threshold: pairs differing only in a stated quantity
score from 0.85 to 1.00, and some score exactly 1.00, because changing a number can
leave the word set unchanged.

The replacement asks four yes/no judgments in one call — is this the same claim, can
both be true, does the first force the second, does the second force the first. Raw
probabilities are recorded; the policy stays in code.

- `same_claim` above 0.9 — CI sets `duplicate-candidate-of`. It is a flag, not a
  status: it promotes nothing and demotes nothing. Merging is a status move and stays
  a person's, through `claims.py`.
- `same_claim` between 0.5 and 0.9 — the adjudication queue.
- `contradictory` above 0.7 — attached to both claims.
- Claims at a terminal status are excluded before comparing. A refuted claim is
  supposed to contradict its replacement.

Runs at ingest, comparing the new claim against every claim on file — a few thousand
calls in a large lab, about a minute. Director-side, not in the worker: the worker
environment allowlist deliberately withholds keys, and this is the gate's job.

## Contradictions

The higher-priority output, and free in the same call. Two runs reaching opposite
conclusions is more urgent than two reaching the same one, and word overlap scores
those two cases identically. The lab has no mechanism for this today.

**An open contradiction does not block promotion.** Blocking assumed a ruling is always
available, but "we do not know yet, dispatch a run" is a legitimate ruling and can take
a week. Instead it is attached to both claims, shows in catchup and on the board, and
`claims.py set verified` prints it and requires the promoter to acknowledge it
explicitly. The promotion is then recorded as having been made over an open
contradiction — honest, and findable later.

Ruling on one is one of four, and three are moves the lab already has: dismiss it as a
false positive; refute one claim, letting the cascade carry its dependents; supersede
with a sharper claim stating the conditions under which both held; or write a brief and
dispatch a run to settle it. Only dismissal is new, and it must land as a ledger event
or the flag fires again at every ingest.

## The board

A static site rendered by CI on push, served from the host behind an authenticating
proxy with the forge as the identity provider — organisation membership is the access
list. Three bands:

- **Believed** — claims and statuses from the ledger fold. The dependency graph,
  coloured by status, with the cone that fell when something was demoted. The
  conditional list and what each is waiting on. This is the band that is unreadable as
  text today.
- **In flight** — from Postgres, joined to the graph on claim or question ID, so a node
  can be lit as under attack by two agents. Who, which method, which model, elapsed
  against budget. What the reservation promised, beside what came back.
- **Just landed** — recent ingests, verdicts, status moves.

The board writes reservations — take, release, preempt — and marks a pair adjudicated.
It never writes claim status.

**One identity, two paths.** An agent authenticates as a Postgres role; a person in the
browser authenticates through the proxy. They must map to the same investigator tag,
the one already in `R-<tag>-NNN`. Otherwise a person's browser actions and their own
agent's actions appear on the record as two different actors, and the lab's discipline
is that an experiment belongs to whoever ran it.

## What it depends on

- PostgreSQL on a host the group can reach.
- A forge with issues, CI and an identity provider.
- A typed-decision model API for the check, reached over the network at ingest. This
  is the first paid dependency in the ingest path; its cost should be known before it
  is load-bearing, and an ingest must degrade gracefully when it is unreachable.

## What was measured

Against 2003 claim statements from two existing records, and 113 pairs built by editing
45 of those statements one word at a time, with the variants written by a different
model from the one judging them.

- Pairs differing by one stated quantity — different claims by construction: the word
  overlap test called all 120 duplicates; the replacement called 4.
- Of the pairs word overlap flags in those records, fewer than half are duplicates.
- Real contradictions: all 30 caught at 0.7. No weakening mistaken for one, and 93% of
  weakenings correctly returned as a one-way entailment.
- The cost at 0.7 is that about one in six pairs about a *different object* reads as
  contradictory. Raising the bar to 0.9 clears those but loses a quarter of the real
  contradictions, which is the wrong trade: a false one costs a reader a minute and the
  dismissal is recorded so it never fires again.
- Roughly 700 input tokens per pair; hundreds of pairs in seconds.

One method that failed, worth not repeating: building the labelled set by regular
expression. It could not tell an asserted value from a quantifier bound or a subject
qualifier — which is the exact judgment under test — so it mislabelled most of the set
in both directions and made a working check look broken.

## Build order

1. **The check.** Useful alone, needs no server, no board, no reservations. `claims.py`
   gains `duplicate-candidate-of`, a contradiction attached to both claims, dismissal
   as a ledger event, and an acknowledgment on `set verified`. Tests alongside.
2. **CI.** Regenerate derived files, run the check across all branches, open or update
   one issue per pair.
3. **Reservations.** Postgres, the schema, the four functions, and the `run.py` calls
   at dispatch and ingest.
4. **The board.**

This changes the scripts and the shared settings, which the kit's own rule says needs
the Investigator's explicit agreement and one small test task afterwards.

## Not settled

Nothing in the design. One thing in an existing record: contradictions the check found
have not been ruled on by anyone who knows the mathematics, so the measured
false-positive rate is the only estimate of how many are real.
