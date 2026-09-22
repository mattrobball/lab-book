# Design queue

Two requests from the Investigator (2026-08-25), kept here so they survived the monitoring work. Each names the failure it prevents, per the README principle. **Both were built on 2026-08-26 (kit 1.2.0).** The original notes stay below as the record of the decisions; the "Built" paragraph at the top of each says what landed and where it is documented.

## 1. Session transcripts in git

**Built 2026-08-26.** `run.py ingest` (and `ingest --record-broken`) discovers the worker's native transcript by a per-role rule in `lab.json` (`roles.<name>.transcript = {"glob": ..., "match": "path" | "first-line-cwd"}`, with `{cwd}`, `{cwd_dashed}`, `{cwd_urlencoded}` placeholders — no vendor patterns in code), gzips it to `runs/R-…/session.jsonl.gz`, commits it with the ingest, and records source, sha256 and sizes in `ingest.json`; above `transcripts.max_mb` (default 20) only the sha and sizes are kept. `--transcript <path>` overrides discovery for in-process workers. `director_session` is stamped in `dispatch.json` and `ingest.json`. Documented in `references/runs.md`, "Transcripts". Not done: moving Director memory into the repo — superseded by the `## This Investigator` block in `AGENTS.md` and role notes in `lab.json`.

### Original note (2026-08-25)

**Failure prevented.** `worker.log` is only the worker's stdout. The reasoning and tool calls behind a claim live in each CLI's private session store on one machine and are pruned or lost; a second investigator cannot audit how a result was produced. The Director's own session is the same: nothing in the repo says which session dispatched or ingested a run.

**What exists today** (audited 2026-08-25 against `reference/run.py` and the combo lab):
- `run.py` writes `worker.log` (stdout+stderr) and nothing else about the session. `dispatch.json` / `ingest.json` carry no session id or transcript path.
- Native transcripts, all recoverable per run:
  - Codex: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, first line has `cwd`.
  - Grok: `~/.grok/sessions/<url-encoded cwd>/`.
  - opencode: `~/.local/share/opencode/opencode.db` (SQLite), by project directory.
  - Claude Code: `~/.claude/projects/<escaped cwd>/<session>.jsonl` for the Director; Agent-tool subagents are separate files under `<session>/subagents/`.
- `CLAUDE_CODE_SESSION_ID` is in the environment when the Director runs `run.py`, so the Director's session id is free to record.

**Proposed minimal design.**
- `run.py new` stamps `director_session` (from `CLAUDE_CODE_SESSION_ID`, else `unknown`) into `dispatch.json`; `ingest` stamps it again.
- `run.py ingest` locates the worker's native transcript by cwd match (Codex, Grok, opencode) and copies it to `runs/R-NNN/session.jsonl`, recording source path + sha256 in `ingest.json`. Agent-tool subagents: `--worker-done --transcript <path>` — the Director knows which subagent file it used.
- Size policy: transcripts over N MB (say 5) are gitignored by pattern and kept on the originating machine, exactly as the combo lab already does for large CSVs; the sha in `ingest.json` still pins them. Decide: this, or git LFS.

**Recommendation (2026-08-25).** Commit worker transcripts, gzipped, at ingest — measured: codex transcripts for this lab are 0.3–2.4 MB raw, 3–4× smaller gzipped, so ~0.2–0.8 MB per run; no LFS. Cap at 20 MB compressed; above that keep local and commit only the sha + size. Copy on `--record-broken` too — that is where the evidence matters most (F-008/F-009). Director session: record the id only; the notebook is the Director's record by design. Move dispatch-governing Director memory (role quirks, quota state) from `~/.claude/projects/<lab>/memory/` into the repo — a second investigator's Director must inherit it.

## 2. Several investigators on one experiment — the federated-notebook model

**Built 2026-08-26, with one change from the note below.** Every investigator works on their own branch `lab/<tag>` from day one, even alone (`run.py join`); `main` is written only by `run.py reconcile`, the investigators' meeting: everyone on a call, one at the keyboard, the Director reads the agenda (duplicate statements, a claim moved differently in two streams, a verified claim resting on one another stream refuted, open runs older than the last meeting, duplicated runs, pages rewritten two ways), the room decides, decisions land as ledger events under actor `meeting <date> (tags)`, the minutes go in `notebook/meetings/`, and every branch is fast-forwarded to `main`. Namespaced IDs `R-<tag>-NNN` / `C-<tag>-NNN`, one ledger per person, legacy untagged IDs still valid; `catchup` reads the others' branches without merging. "Everyone on main between meetings" was considered on 2026-08-26 and rejected by the Investigator: daily pushes to a shared branch are where git bites people new to it; per-person branches became viable once namespacing removed the ID collision that had ruled them out. Documented in `references/runs.md` ("Joining a lab", "Seeing the others", "The meeting"), `references/claims.md` ("One ledger each"), `AGENTS.md` ("Investigators' meeting"), README ("Working as a group").

### Original note (2026-08-25)

**Chosen 2026-08-25 (Investigator).** Replaces the earlier serial push/pull plan, kept at the end as the rejected alternative.

**The analogy.** Collaborating physical labs do not share a notebook. Each keeps its own, append-only, in its own voice. What they share is the results — a claims table and a manuscript — and they reconcile at meetings: compare findings, surface discrepancies, decide who re-runs what, write minutes. An experiment belongs to the group that ran it; others cite it, never edit it.

**Failures prevented.**
- Two investigators mint the same `R-NNN`/`C-NNN` and someone renumbers evidence by hand (IDs are max+1 scans of the local tree, `run.py:228`, `claims.py:127`).
- Two labs quietly hold two truths about a claim until the paper is written.
- "Whose run is this, and is it still alive?" unanswerable from the record.
- A second investigator's Director starting without the operational facts that live in the first one's machine-local memory.

**Design.**
1. *Notebooks are per investigator.* Everything an investigator writes carries their tag: `runs/R-<inv>-NNN`, notes `N-<date>-<inv>-NN`, and an append-only `claims/ledger-<inv>.jsonl`. Files with one writer never merge-conflict; the ID race and any pull-first rule disappear. A run directory is owned by its investigator and immutable to others, exactly as notebook entries already are. Transcripts (§1) follow the run. `dispatch.json`/`ingest.json` carry `investigator` (git `user.name`), `host`, and the Director session id, so an open run says whose machine it lives on.
2. *Claims are the shared object.* `CLAIMS.md` is generated from all ledgers; a claim's current status is the latest event across them. Any investigator's Director may referee another's claim. Independence gains a second axis: "checked by a different model" becomes "checked by a different model and a different lab" — the software form of inter-lab reproducibility. `claims.py` records both.
3. *STATUS.md is the meeting minutes.* It is the only genuinely contended file, so it is rewritten only at reconciliation. Between meetings, investigators write notes in their own stream.
4. *Reconciliation is a script plus a meeting.* `claims.py reconcile` prepares the agenda: duplicate statements across ledgers, conflicting status events on one claim, a claim one lab verified that rests on something the other lab moved, open runs older than the last meeting. People decide; decisions land as ledger events under an actor like `meeting 2026-08-30`, and the meeting note is filed in the notebook. `catchup` reads all streams.
5. *Generated files are derived, never merged.* `CLAIMS.md`, `INDEX.md` are regenerated after every pull; the lint refuses a commit where they disagree with the ledgers.
6. *Director memory.* Per-investigator habits stay local; anything that governs dispatch (role availability, quirks, quota state) lives in `lab.json` so every Director inherits it.

Serial turns are the special case of one active investigator and need no extra rules.

**Decisions (Investigator, 2026-08-25).**
1. The investigator tag is the git `user.name` (normalized to a short slug for file names).
2. A claim proposed and verified within the same lab counts as `verified`; the cross-lab axis is recorded as independence, not required for status.
3. Only the owner may close (ingest or void) a run. Another lab may *duplicate* it: dispatch the same brief in its own namespace, with `dispatch.json` carrying `duplicates: R-<inv>-NNN` so `reconcile` lists the pair and the stale original stays visible until its owner closes it.

**Rejected alternative — one notebook, serial turns.** `run.py new` fetches and refuses if behind `origin/main` or with unpushed ingests; ingest pushes, and a push failure blocks the next `new` rather than the ingest. Workable, but it is "take turns writing in one notebook": it needs enforcement to stay consistent, blocks the second investigator entirely, and gives disagreement no place to be recorded. Per-investigator branches were also rejected — they move the ID collision to merge time.

## 3. Live collaboration — reservations, and a board that shows the work

**Requested 2026-09-22.** Not built. The 1.2.0 federated model (per-person branches,
reconciled at a meeting) assumes everyone works apart and meets later. This is the
other mode: half a dozen agents and people working the same problem at the same time,
seeing each other.

### Failures prevented

- Two agents spend an hour each on the same question because neither could see the
  other start. Today nothing is visible until ingest.
- A claim is shaped after the data is seen, and nothing on record shows what the run
  set out to test.
- A run goes quiet and nobody notices until catchup the next morning.
- The same statement arrives twice and `near_duplicates` only warns, at ingest, to
  one person's terminal.
- The lab's state is readable only by running scripts in a clone. A collaborator who
  wants to see where things stand has to become an operator first.

### Design

**Three substrates, by job.**

1. *Facts stay in git.* Claims, runs, ledgers, transcripts. Unchanged. The record is
   what is committed.
2. *Reservations live in Postgres* on the group's cloud host. Never truth, only who is
   working on what. If the host is unreachable, agents work anyway and reconcile
   later — a reservation is an optimization, never a gate.
3. *Adjudication lives in GitHub Issues*, opened by CI. A duplicate pair needs
   discussion and a decision with an author; that is what an issue is for.

**A reservation is a preregistration.** Taken before the run starts, it names the
question, the method, the actor, the model, the expected claim shape, and the time
budget. It earns its keep with one person working alone — it is the record of what a
run set out to test — so it is not only a collision-avoidance device.

**What is built, and nothing more.** A schema and four SQL functions: `take_lease`,
`renew`, `release`, `reap`. No API server. Agents connect to Postgres directly, one
role per person, over TLS; Postgres authentication is the authentication, and it
revokes cleanly. Row-level security confines a person to their own rows.

**Renewal requires progress, not a heartbeat.** An agent that pings forever while
stuck is the failure a plain liveness check cannot see.

**Every dispatch and ingest carries its lease number.** An agent pauses inside a long
model call, the lease expires, a successor takes the question. When the first returns,
its packet is not rejected — the work is real. It is filed as unsolicited, and if a
successor covered the same ground, the pair goes to rectification.

**Duplicates are not waste.** Two agents that independently reach the same claim,
neither aware of the other, are the second actor the promotion rule already demands.
Rectification promotes the pair as independent corroboration; it discards nothing.

**The similarity test is replaced.** `similar()` in `run.py` compares normalized word
sets at 0.6 overlap and warns at ingest. Measured 2026-09-22 against 2003 claim
statements drawn from two live labs:

- On 120 pairs built by swapping one number word in a real statement — different
  claims by construction — the word-overlap rule called all 120 duplicates. No
  threshold repairs this: those pairs score 0.85 to 1.00, and some score exactly 1.00,
  because changing a number can leave the word set unchanged.
- Of the 36 pairs it flags across those labs, 16 are not duplicates.
- It misses real duplicates below its threshold, and it has no notion of two claims
  contradicting each other.

The replacement is four independent yes/no judgments asked in one System One call
(TypeSafe's Jev, `typesafe-sdk`): `same_claim`, `contradictory`,
`first_entails_second`, `second_entails_first`. Raw probabilities are recorded; the
policy stays in code. On the same 120 constructed pairs it answered 116 correctly.
Real duplicates return `same_claim` above 0.9 and genuinely ambiguous pairs in the
middle, so: above 0.9 CI acts, 0.5 to 0.9 goes to the adjudication queue, below 0.5 is
dropped. Roughly 700 input tokens per pair, hundreds of pairs in seconds, so it runs
on every pair at every ingest rather than in batches.

**The contradiction threshold is 0.7.** Measured 2026-09-22 against 113 pairs built by
editing 45 real statements one word at a time — a changed asserted value, a weakening,
or a changed subject — with the variants written by a different model from the one
judging them. At 0.7 every one of the 30 real contradictions is caught, no weakening is
mistaken for one, and 93% of weakenings come back correctly as a one-way entailment.
The cost is 15% of different-subject pairs — the same sentence about a different object
— read as contradictory. Raising the bar to 0.9 clears those but loses a quarter of the
real contradictions, which is the wrong trade: a false one costs a reader a minute and
the dismissal is recorded so it never fires again, while a missed one is what the check
exists to prevent. An earlier attempt to build this set by regular expression failed and
is worth remembering — it could not tell an asserted value from a quantifier bound or a
subject qualifier, which is the exact judgment under test, so it labelled 27 weakenings
as contradictions and 74 contradictions as controls.

**Contradiction is the higher-priority output.** It costs nothing extra in the same
call, and a first pass found 18 contradictory pairs already sitting in those two labs'
records — a rough count, since at the measured false-positive rate three or four of
them are likely different-subject pairs rather than genuine conflicts.
Two runs reaching opposite conclusions is more urgent than two reaching the same one,
and the word-overlap test scores those two cases identically. The lab has no mechanism
for this today.

**The board.** A static site rendered by CI on push, served from the cloud host behind
oauth2-proxy with GitHub as the identity provider — org membership is the access list.
Three bands:

- *Believed* — the claims and their statuses, from the ledger fold. The dependency
  graph, coloured by status, with the cone that fell when something was demoted. The
  conditional list and what each is waiting on. This is the band that is unreadable as
  text today.
- *In flight* — from Postgres, joined to the graph on claim or question ID, so a node
  can be lit as under attack by two agents. Who, which method, which model, elapsed
  against budget. What the reservation promised, beside what came back.
- *Just landed* — recent ingests, verdicts, status moves.

Lease expiry surfaces here as a real signal — a run that went quiet — rather than as
plumbing.

### Decisions (Investigator, 2026-09-22)

1. Postgres is self-installed on the group's cloud host, not managed. The lease table
   is soft state; the durability a managed service sells is durability this design
   deliberately does not need, and everything that must survive is in git or GitHub.
2. The board writes reservations — take, release, preempt — and marks a duplicate pair
   adjudicated. It never writes claim status. That stays with `claims.py` and lands as
   a commit, so the record remains what is committed.
3. CI may set `duplicate-candidate-of` itself above 0.9. It is a flag, not a status: it
   promotes nothing and demotes nothing, and a wrong one costs a reader half a minute.
   Requiring a person for it means the flag is missing exactly when someone needs it.
   Merging two claims is a status move and stays a person's, through `claims.py`.
4. The contradiction check runs at ingest, comparing the new claim against every claim
   on file, with no prefilter — about 2000 calls in the larger lab, a minute at ten
   threads. The one-time backfill over all existing pairs is dropped: its word-overlap
   blocking step would have missed contradictions between claims sharing little
   vocabulary, which is the blind spot the check exists to close.
5. An open contradiction does not block promotion. Blocking assumed a ruling is always
   available, but "we do not know yet, dispatch a run" is a legitimate ruling and can
   take a week. Instead the contradiction is attached to both claims, shows on the
   claim, in catchup and on the board, and `claims.py set verified` prints it and
   requires the promoter to acknowledge it explicitly. The promotion is then recorded
   as having been made over an open contradiction, which is the honest outcome and one
   a later reader can find.
6. Ruling on a contradiction is one of four, and three are moves the lab already has:
   dismiss it as a false positive; refute one claim, letting the cascade carry its
   dependents; supersede with a sharper claim that states the conditions under which
   both held; or write a brief and dispatch a run to settle it. Only dismissal is new,
   and it must be recorded as a ledger event or the flag fires again at every ingest.
   Rulings happen in the issue CI opened, or at a meeting; either way the decision
   lands on the ledger as meeting decisions do today.

7. The board's writes reach Postgres through PostgREST. A browser cannot speak the
   Postgres wire protocol, so the alternative needs a proxy anyway, and PostgREST is
   that proxy with the row-level security policies the agents already require —
   rather than a second permission model that can drift from the first. One identity,
   two paths: a GitHub login maps to the investigator tag, which is the Postgres role,
   which is the tag already in `R-<tag>-NNN`. Otherwise a person's browser actions and
   their own agent's actions appear on the record as two different actors.
8. A reservation has a deadline and no heartbeat. It is taken at dispatch with the
   brief's budget as its deadline, released at ingest or void, and shown as stale past
   its deadline with no packet. No renewal, no progress signal, no checkpoints: every
   in-flight signal considered was either uninformative (bytes written) or a change to
   the brief template that workers would have to be asked to honour. A dead agent's
   lease therefore sits until its deadline instead of being reaped early, which at six
   participants is someone glancing at the board, not a correctness problem.

9. The board carries taken and stale, and nothing else in flight. Revisit only if the
   three bands prove thin in use.

### Open decisions

1. The 18 contradictions found in the live labs have not been ruled on by anyone who
   knows the mathematics. Until they are, the measured false-positive rate is the only
   estimate of how many are real.


### Implementation clarification (Investigator, 2026-09-22)

Minimal first pass authorized. There is **no preemption**: coordination only
announces existing work. This supersedes the preempt wording in decision 2.
Jev calls are mocked for behavior tests; no paid API calls are made.
Implementation and evidence are described in `V3_IMPLEMENTATION.md`.


## 4. Single-writer service — Git becomes the durable backend, not the write protocol

**Chosen 2026-09-22 (Investigator).** This supersedes the active-write topology in
§2/§3 for v3. The trigger was the review of the partial-service design: once the
service/CI owned some Git mutation, splitting durable writes between local
investigator processes and automation produced a second-writer race and additional
branch machinery. The simpler boundary is for the service to own all canonical Git
mutation.

### Decisions

1. **The service is the sole writer of the canonical lab Git repository.** Human
   clients, Directors, workers and CI do not push lab-record commits.
2. **One canonical record replaces active per-investigator Git branches.** Actor
   identity and independent viewpoints remain explicit in events; branch topology is
   no longer the representation of disagreement.
3. **Git remains the permanent record.** PostgreSQL holds only soft/rebuildable
   collaboration and service state. GitHub Issues are discussion/mirrors, not
   authoritative rulings.
4. **Every durable action is a typed service operation.** Dispatch, ingest, void,
   notes, claim changes, dismissals, meeting rulings, automated comparison events and
   upgrades all become service-created commits.
5. **The service serializes commits and uses request IDs for idempotency.** A durable
   operation is not acknowledged until its canonical Git commit is present remotely.
   No force push or automatic history rewrite.
6. **The service is now required for new canonical mutations.** Already-dispatched
   workers may continue while it is unavailable and submit later; clients do not
   bypass an outage by pushing an alternate Git history.
7. **One public authentication path.** Browser and agent requests hit the service.
   Git/database/provider write credentials remain service-side. PostgreSQL may retain
   RLS as defense in depth but is not directly exposed to clients.
8. **CI becomes read-only.** It may test and render disposable artifacts, but it does
   not commit advisory state. Automated comparisons are service jobs whose results
   are committed by the same single writer.
9. **Migration preserves old history rather than rewriting it.** Legacy investigator
   and publication refs become read-only audit material; the service records their
   exact heads when establishing the canonical starting revision.

The full target architecture and acceptance criteria are in `DESIGN_V3.md`.


### Topology correction (Investigator, 2026-09-22)

The service remains the sole Git writer, but **branches are retained as the separation
mechanism**. The earlier wording that collapsed active work into one canonical branch
was too strong.

- `lab/<tag>` remains one durable stream per investigator, written only by the service
  on that investigator's authenticated behalf.
- service-generated comparison/advisory events may use a separate automation stream.
- clients, workers and CI still have no Git write credentials.
- one serialized integration runner is the **only writer to `main`**.
- integration pins exact stream heads; streams may continue advancing while an
  integration is in progress, with later commits entering the next cycle.
- `main` is the integrated record, while branches preserve independent provenance
  and avoid unnecessarily serializing unrelated work.

This replaces decision 2 in this section and refines decisions 1, 5 and 8. The full
corrected topology is in `DESIGN_V3.md`.
