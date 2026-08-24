# Runs

## Starting a lab

Ask the Investigator these five questions, one at a time, waiting for each
answer.

1. State the problem. (Becomes the problem's README.)
2. What counts as evidence — what must someone run, and what must they see,
   before a result is believed here?
3. Same repository or a new one? (Will this work cite claims or objects already
   here?)
4. Anything known or already tried? (The first claims, and "do not retry
   unless" notes.)
5. What are the constraints — budgets, cadence?

Then discover the environment rather than assuming it: probe for agent
command-line tools, for the subject-specific tools this problem needs, and for
the language libraries. Report a short table — tool, version, how it is
launched. The Investigator adds what you missed and strikes what should not be
used. Store the confirmed list in `lab.json`:

```json
{
  "roles": {"technician": {"model": "<your-model>",
    "command": "<your-cli> --model <your-model> --prompt-file {prompt}"}},
  "tools": ["<confirmed-tool>", "<confirmed-tool>"]
}
```

The skill ships no models or commands.

Then search the literature the same way: what is published on this exact
question — known values, bounds, constructions, attempts that failed. Report a
short list — result, source, what it settles. The Investigator adds what you
missed and strikes what does not apply. What survives enters the ledger as
`externally-established` claims with their citations, so later briefs paste
facts, not folklore.

## Sources

The problem's `sources/` directory is to literature what `tools/` is to code:
where reusable retrieval work is promoted so it is done once. Cache what can
lawfully be cached, record each file's SHA-256 in `sources/MANIFEST.md`, and
index the lot in STATUS.md under "Sources held here". `sources/QUERIES.md` is
the append-only log of searches: what was asked, where, what came back, what
was kept — literature runs append to it, briefs paste from it. A source that
cannot be obtained gets a manifest line, not a claim: what it is, what was
tried, and "do not retry unless ..." — the reference run re-litigated one
embargoed thesis across four runs for want of that line. A not-found result
("no published proof of X exists") lives in QUERIES.md with its trail, and
becomes a claim only if the trail would convince a skeptic — mathematical
impossibility results are ordinary claims and untouched by this rule.

## Dispatching

Dispatch when you can state the goal and a worker with no context could tell
whether it succeeded. Do not dispatch to save yourself reading, or a question
you have not decided how to grade.

Write the brief from `templates/BRIEF.md`. Everything the worker needs goes in
it — paste the claims and file contents it may rely on rather than pointing at
them. Reread `STATUS.md` first: results it must not re-derive, scripts it
should reuse, approaches it must not retry. A worker sees nothing but its
brief, so work it redoes is your omission, not its mistake.

Move anything reusable a run builds into the problem's `tools/` directory at
the Update step, headed by one line: what it does, which run built it. "Tools
built here" in `STATUS.md` indexes that directory, and a brief may allow
reading `tools/` instead of pasting scripts in.

A check is dispatched as an attack, in the brief's own words: "A claims X;
review the claim adversarially but fairly — your job is to prove or refute
it. A refutation with an explicit witness is full success. A PASS must name
what you attacked and could not break." If the claim rests on computation,
the checker writes its own verifier and never runs or trusts A's. This
framing is what makes a second opinion evidence: the checks in the reference
run that read the discoverer's proof passed its false step; the ones that
attacked the statement caught it.

**Every dispatch names a model**, from `lab.json` or stated explicitly.
`run.py new` refuses without one. It allocates the run ID, records
`dispatch.json` (brief fingerprint, model, launch command, replay timeout, the
claim IDs the brief pasted, git position, timestamp), and assembles `PROMPT.md`
from the worker charter, the brief, and the return contract. It warns when an
open run already carries the same brief fingerprint — usually a Director who
lost the thread and dispatched the same question twice.

The worker runs with its run directory as its working directory, where `run.py
new` has written an `AGENTS.md` holding worker rules only — so the Director
charter at the repository root is unreachable. Workers that marinate in lab
governance start editing it.

Several workers at once is the normal mode, and the machinery is built for
it: the fence judges each worker only by what it could itself have written,
ingest takes a lock, and a run whose worker is still alive is not ingested.
Each brief still names the other runs' directories off-limits. Launch
commands should invoke the tool directly by absolute path — login shells
(`bash -lc`) read profile files and have broken under sandboxes; `run.py new`
refuses a command whose binary is not on PATH, because a launch that cannot
start is a harness failure, not a run.

## The return packet

The worker writes two files into its run's `packet/`.

`RESULT.md` — created first with `# VERDICT: PENDING` and filled in as the
worker goes, so a death mid-task leaves partial findings instead of nothing;
finished, its first line is `# VERDICT: PASS|FAIL|UNDECIDED`, a headline sentence,
then `## What was done`, `## Not claimed`, `## Leads`, `## Validation`.
`## Not claimed` is graded: a narrow honest boundary beats a loud headline.
`## Leads` is the worker's strategy, with reasons — what it dropped and why,
what looked promising, what it would try next. Dead ends die here or get
retried forever.

`RETURN.json` — `headline`, `exits` (the states reached), `validation`
(`replay` or `review`), `machine_markers`, `claims_used` (IDs copied from the
brief), and `claims_proposed` — **plain statements, never IDs**. Workers do
not mint claim IDs, do not grade themselves, and do not name themselves:
ingest stamps the actor from `dispatch.json`. Before finishing, a worker runs
`run.py lint R-NNN` — read-only — and does not stop until the packet passes.

## Replay or review

Every return declares which of the two validated it. They are separate facts,
never a ladder: `replayed` says a machine re-ran it clean, `reviewed_by` says
who checked it, and a refereed proof is not below a passing script. And be
precise about what a replay proves: a marker is a print statement — its
presence proves the command ran, not that anything was recomputed. The
reference run's worst moment was a replay that validated shapes and its own
checksum while recomputing nothing; the referee that caught it was checking
what the replay actually recomputes, which is now the standing instruction
for every referee of computational work.

**Replay** — a machine re-runs the work: the exact command, the exact marker
strings it prints, and what it prints when it fails. The timeout is set at
dispatch and recorded in `dispatch.json`.

**Review** — an actor other than the discoverer checks the work by hand, and
the record keeps who, when, and what they checked. A result with no executable
check — a proof, say — declares review and names what a referee must check. You
then dispatch that referee: a review nobody has done validates nothing.

## Ingest

`run.py ingest` checks the packet is complete and well-formed. For a replay it
runs the command under the dispatched timeout: a nonzero exit fails whatever
was printed, and every marker must appear exactly as written, not paraphrased
and not matched by pattern. Ingest stamps the actor from `dispatch.json`,
checks the write fence — judging only uncommitted files this worker could
have written, never committed history or another run's directory — renders
the notebook entry, warns when a proposed claim looks like one already on
file, and commits the run under a lock, with the verdict in the message. A
run whose worker process is still alive is refused until it exits (or
`--worker-done` overrides), because a live worker writing into a filed packet
is a mutation nobody can audit.

Every refusal saves its reason to the run's `refusal.txt`. Filing the failure
is then one command with two honest verdicts: `ingest R-NNN --record-broken`
files `UNINGESTABLE` when a packet exists and failed a named gate, and
`HARNESS-FAILURE` when the worker never produced one — the recorded reason
and `execution.json`'s exit code go in the entry either way, and whatever the
packet proposed is quoted there as untrusted text, so a refusal never
silently destroys a lead. A pure format failure may be bounced once: re-run
the same worker with the refusal text as its prompt (the launch command is in
`execution.json`) — the same actor repairing its own return launders nothing.
Fence and content failures are never bounced. Packets are never hand-edited —
a Director who repairs a worker's return has laundered its provenance.
Recovery is a fresh dispatch. A run that produced nothing at all is closed
with `run.py void R-NNN --reason`, so the open list never carries ghosts.

Ingest never promotes a claim. It files proposals as `proposed` and stops.
Promotion is your separate act, under `references/claims.md`, never on the strength of
the run that made the discovery.

## Director notes

`run.py note` files a notebook entry you wrote yourself — headline and body,
your actor recorded, no packet and no claims. Use it for a decision, an
approach abandoned and why, a result reached in conversation with the
Investigator. Without it the only thinking on record is a worker's.

## Catchup

`run.py catchup` lists the runs, verdicts, and claim changes since a commit or
a date, then the standing lints: runs needing attention, reviews owed
(aggregated, cleared by a referee or `run.py waive-review`), unresolved
duplicate-claim warnings, verified claims resting on unverified ones, claims
accepted on the Investigator's word, promotions with no model independence,
and per-model totals of runs, ingests, refusals and wall time. Every line is
closable — a flag nobody can clear teaches its reader to skim, which is how
an owed referee stayed flagged for three days and was never dispatched. You
tell the Investigator what it means, in plain sentences, without pasting the
listing. `new` and `ingest` also end by naming any run that needs attention,
so a stalled run cannot hide behind a report nobody asks for.

## Resource accounting

`execution.json` in each run directory records the launch command, start and
end, exit code, wall time, and — best effort, via an optional `usage_pattern`
regex per role in `lab.json` — tokens and cost from the worker's log. Missing
numbers stay missing, never guessed. Each notebook entry ends with the run's
resource line, and catchup's per-model totals answer "is this model earning
its place" at a glance. What a theorem cost is a grep away: its claims name
their evidence runs, and the entries carry the footers.

## The honest stop

A worker that returns `UNDECIDED` naming its blocker precisely has succeeded,
and is graded as one. A manufactured verdict is the expensive failure. `run.py new` puts this in every assembled prompt, so the brief does
not repeat it.
