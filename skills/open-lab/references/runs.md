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

Several workers at once is fine as long as each has its own write fence and
each brief names the others' directories off-limits.

## The return packet

The worker writes two files into its run's `packet/`.

`RESULT.md` — first line `# VERDICT: PASS|FAIL|UNDECIDED`, a headline sentence,
then `## What was done`, `## Not claimed`, `## Leads`, `## Validation`.
`## Not claimed` is graded: a narrow honest boundary beats a loud headline.
`## Leads` is the worker's strategy, with reasons — what it dropped and why,
what looked promising, what it would try next. Dead ends die here or get
retried forever.

`RETURN.json` — `headline`, `exits` (the states reached), `validation`
(`replay` or `review`), `machine_markers`, `honesty_tier` (`machine-verified`,
`hand-checked`, `asserted`), `claims_used` (IDs copied from the brief), and
`claims_proposed` — **plain statements, never IDs**. Workers do not mint claim
IDs, and do not name themselves: ingest stamps the actor from `dispatch.json`.

## Replay or review

Every return declares which of the two validated it.

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
checks the write fence, renders the notebook entry, warns when a proposed claim
looks like one already on file, and commits the run with the verdict in the
message.

What lands on record follows: a replay that passed is machine-verified, a
review by a different actor is hand-checked, neither is asserted. A review
lifts asserted to hand-checked; it never overwrites a tier a replay earned.

A packet that cannot be ingested is committed as it stands under the verdict
`UNINGESTABLE`, allocating no claims. Packets are never hand-edited — a
Director who repairs a worker's return has laundered its provenance. Recovery
is a fresh dispatch.

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
a date. It gives you the raw change; you tell the Investigator what it means,
in plain sentences, without pasting the listing.

## The honest stop

A worker that returns `UNDECIDED` naming its blocker precisely has succeeded,
and is graded as one. A manufactured verdict is the expensive failure. `run.py new` puts this in every assembled prompt, so the brief does
not repeat it.
