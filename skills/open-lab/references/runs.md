# Runs

## Starting a lab

Ask the Investigator these six questions, one at a time, waiting for each
answer.

1. State the problem. (Becomes the problem's README.) Every term the
   Investigator uses gets an entry under "Objects and definitions" before
   you go on: the definition, one small worked example, and its source —
   the paper or book it comes from, or "Investigator, intake". Read them
   back and have them confirmed. Those are the words every later message
   and brief uses. The lab's own terms are in `GLOSSARY.md`, each with an
   example and the file that owns the rule.
2. What counts as evidence — what must someone run, and what must they see,
   before a result is believed here?
3. Same repository or a new one? (Will this work cite claims or objects already
   here?)
4. Anything known or already tried? (The first claims, and "do not retry
   unless" notes.)
5. What are the constraints — budgets, cadence?
6. How should I talk to you? Asked as short sub-questions, one at a time:
   how much have you used coding agents (none, some, daily); where do you
   read — a phone, a laptop — and how long may a message be; do you want
   each step explained before it happens, or done and reported; words or
   notation; what should I always ask you before doing, and what may I
   decide alone. The answers go, in the Investigator's own words, into
   `## This Investigator` at the end of the lab's `AGENTS.md`, one block per
   person, and bind every later session. When the Investigator says "talk to
   me differently", ask again, replace the block, and file the change as a
   note.

Then discover the environment rather than assuming it: probe for agent
command-line tools, for the subject-specific tools this problem needs, and for
the language libraries. Report a short table — tool, version, how it is
launched, and what it is for and not for. The Investigator adds what you
missed, strikes what should not be used, and says what each worker should
and should not be sent. Store the confirmed list in `lab.json`; the "for /
not for" column becomes each role's `note`, and `run.py new` prints it at
every dispatch. `lab.json` is the worker registry — the one place that says
which workers exist, how they launch, what they are for, and whether they
are on hold. One lab kept "stalls on reading-heavy tasks" in a memory
instead, and sent that worker three more reading-heavy tasks.

Every key the scripts read, in one example:

```json
{
  "roles": {
    "technician": {
      "model": "<your-model>",
      "command": "<your-cli> --model <your-model> --prompt-file {prompt}",
      "note": "for: small generation jobs. not for: reading-heavy tasks",
      "unavailable_until": "2026-09-01",
      "worker_timeout": 14400,
      "memory_gb": 10,
      "usage_pattern": "(?P<tokens>[\\d,]+) tokens",
      "transcript": {"glob": "~/<store>/**/*.jsonl", "match": "first-line-cwd"}
    }
  },
  "tools": ["<confirmed-tool>", "<confirmed-tool>"],
  "machine": {"max_heavy_runs": 2, "rotate_after_ingests": 12},
  "transcripts": {"max_mb": 20},
  "sources": {"refetch_days": 30},
  "investigators": {}
}
```

Only `roles.<role>.model` and, for a role that launches itself, `command`
are needed. `note` is printed at every dispatch; `unavailable_until` is a
date, and lifts itself. `worker_timeout` and `memory_gb` are the default
budgets a run is watched against. `usage_pattern` is a regex with named
groups read over the worker's log when the built-in token shapes do not fit.
`transcript` says where that worker's session file lives ("Transcripts").
`machine.max_heavy_runs` is the Director's ceiling on compute-heavy workers
at once; `machine.rotate_after_ingests` is when a session is told it has run
long. `transcripts.max_mb` caps what is copied into the record;
`sources.refetch_days` is when a baseline is called stale. `investigators`
is written by `run.py join` — never by hand.

The skill ships no models or commands. `run.py new` refuses a dispatch to a role on hold, printing the
note, and dispatches normally once the date has passed, so nobody has to
remember to lift the hold; catchup lists the roles currently held. A hold is
a date, never a bare flag — a flag goes stale the day the quota resets. The
one lab once wrote a brief and allocated a run for a role with no quota
left, because that fact lived in a Director's memory.

Then search the literature the same way: what is published on this exact
question — known values, bounds, constructions, attempts that failed. Report a
short list — result, source, what it settles. The Investigator adds what you
missed and strikes what does not apply. What survives enters the ledger as
`externally-established` claims with their citations, so later briefs paste
facts, not folklore.

Then, for a problem with a numeric objective, the data. Papers are not the
only prior art: inventory the public tables, archives and leaderboards that
already hold values for this objective, fetch what can be fetched (a fetch
script and the file's SHA-256 in `sources/MANIFEST.md`, on a line marked
`baseline` with `fetched YYYY-MM-DD`), score every entry with the lab's own
scorer, and file the best known value at each size as an
`externally-established` claim with its source. "Record" in any later brief
then means beating that baseline, and a worker's "new best" below it is
caught at adjudication. One lab seeded a search from one paper while a
2004 table and a 2018 archive sat public; the search "certified" values at
53 sizes those tables already beat. A baseline also goes stale as public
boards update: catchup flags any baseline line fetched more than
`sources.refetch_days` ago (`lab.json`, default 30) for a re-fetch.

## Joining a lab

Every investigator runs `run.py join` once per clone, before their first
write; in a fresh lab it makes the first commit itself. It makes a **tag** from git's `user.name` (lowercase, letters and
digits, at most twelve), registers the person in `lab.json` under
`investigators`, creates the branch `lab/<tag>`, and checks it out. Run it
again and it only checks the branch out; it refuses when the tag is already
somebody else's, because two people sharing a tag share their IDs.

From then on that clone allocates in its own namespace — `R-<tag>-001`,
`C-<tag>-001` — writes claim events to its own `claims/ledger-<tag>.jsonl`,
and refuses `new`, `ingest`, `void`, `note`, `waive-review` and every
`claims.py` write on any other branch, printing the command that fixes it.
Read-only commands work anywhere. IDs allocated before the first join keep
the short form for good and stay readable everywhere: nobody renumbers
evidence.

The failures this prevents: two people minting the same ID on two machines
and someone renumbering a run by hand afterwards; a day of pushes to one
shared branch rejected, merged, and conflicting on generated files, in the
hands of people who have never resolved a merge; and "whose run is this, and
is it still alive" being a question the record cannot answer. `run.py
whoami` answers the last one for you: tag, branch, and how many commits have
not left this laptop.

A run belongs to whoever dispatched it. Others cite it by ID; only its owner
ingests, voids or waives it, and the commit guard refuses to stage a file
under somebody else's run at all. A run dispatched before anyone joined
belongs to nobody, and any registered investigator may close it — the script
says so when it does. When you deliberately repeat somebody's work, say so
at dispatch with `--duplicates <run>`: catchup names the pair until the
original is closed, so two people doing one job is visible on the day, not
at the meeting.

## Seeing the others

`run.py catchup` fetches and then reads every other `lab/<tag>` branch
straight out of git — their runs, verdicts, and claim events — without
merging anything into your tree. It reports, per investigator, what they
have recorded since the last meeting, their runs still open past a day, and
how many of your own commits origin has not got. Every write pushes your
branch afterwards, best effort: a failure is one line, never a lost commit,
and the count shows up here.

Nothing you run merges their record. A brief may paste another investigator's
claim by ID with the status as fetched, exactly as it pastes a claim of your
own; what it must not do is edit their stream. Two labs holding two truths
about one claim until the paper is written is what the meeting exists to
prevent, and reading each other daily is what keeps that meeting short.

## The meeting

`run.py reconcile`, with everyone on a call and one person at the keyboard.
It is in two halves.

**Prepare.** It refuses on a dirty tree or unpushed work, fetches, checks out
`main`, and merges every investigator's branch in turn. Namespaced files
never collide. What can conflict is generated pages, which it rebuilds from
the record; the ledgers, whose union is the answer because they are
append-only; the registry of investigators, which is a list of people; and
hand-written pages, where two people have written two bottom lines. Those
last are not merged: the incoming version is left beside the page as
`STATUS.md.<tag>`, the page keeps its pre-merge text, and the disagreement
goes on the agenda. Nothing is ever left half-merged for somebody to find.

Then it prints and files the agenda — `notebook/meetings/<date>-agenda.md` —
one numbered line per thing two records disagree about or one record has left
open, each with the command that settles it: pages rewritten twice, the same
statement proposed in two streams, one claim two streams left in different
states, a verified claim resting on something another stream demoted, runs
open since before the last meeting, duplicate pairs, reviews owed. The
Director leads the room through it and never settles a disagreement itself.

**Record.** Decisions are ordinary commands, made on `main` while the agenda
is open, with `--actor "meeting <date> (<tags>)"` so the ledger says who
decided. Then `run.py reconcile --close --present alice,bob` refuses while
any copy of a page is still in the tree, files the minutes as
`notebook/meetings/<date>.md`, commits `meeting: <date> (<tags>)`, pushes
`main`, fast-forwards every branch onto it, and puts the keyboard-holder back
on their own. Everyone starts the next day from the same record, and the
meeting is where the group agrees — never a merge somebody did alone.

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

**While a worker runs, commit every edit you make, naming its path.** The
fence at ingest counts every uncommitted file outside the run's own paths
against that run, and the refusal names the worker — so a note you left
open in the editor is filed as the worker writing where it should not.
Commit your own work as you go and the fence only ever sees the worker's.

Briefs live in the problem's `briefs/`, one file per brief, named
`B-NNN-<short-slug>.md` — the number ties it to the run that carries it, the
slug says what it asks. `run.py new` commits the brief itself along with the
run, so what a worker was asked is in the history beside what it returned.

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
`run.py new` refuses without one. A referee dispatch also names the run it
checks, `--checks R-NNN`: ingest fills `reviewed` from it if the packet
leaves it out, and `new` refuses when the referee would run on the same
model as the run it checks, unless `--accept-same-model` — the ledger would
refuse the promotion anyway, but only after the run was paid for. `new` allocates the run ID, records
`dispatch.json` (brief fingerprint, model, launch command, replay timeout, the
claim IDs the brief pasted, the run checked, git position, timestamp), and assembles `PROMPT.md`
from the worker charter, the brief, and the return contract. It refuses when
an open run already carries the same brief fingerprint — usually a Director
who lost the thread, or a retry that fired twice — unless `--force` says the
repeat is meant. `--no-launch` is only for roles with no launch command; on a
role that launches through `lab.json` it leaves a run open with no worker,
and is refused.

The worker runs with its run directory as its working directory, where `run.py
new` has written an `AGENTS.md` holding worker rules only — so the Director
charter at the repository root is unreachable. Workers that marinate in lab
governance start editing it.

Several workers at once is the normal mode, and the machinery is built for
it: the fence judges each worker only by what it could itself have written,
ingest takes a lock, and a run whose worker is still alive is not ingested.
`run.py new` waits for its worker; pass `--detach` to leave a watcher behind
and return at once, or every dispatch queues behind the last one's whole
lifetime — that is how three "parallel" dispatches once ran one at a time.
While it waits it watches: every ten seconds it checks wall time and the
process tree's resident memory against `--worker-timeout` and `--memory-gb`
(or the role's `worker_timeout` and `memory_gb` in `lab.json`), records a
breach in `execution.json` and reports it in every later `new`, `ingest`
and catchup. It never kills. Whether a run over budget dies or runs on is
the Investigator's decision, so the Director surfaces the breach and waits
for it. Set budgets with headroom: a worker once went thirty times over its
stated memory on a shared machine before anyone looked.
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
brief), `claims_proposed` — **plain statements, never IDs** — and, for a
check of another run, `reviewed`: the IDs refereed. That last field is what
clears "review owed" on the run checked; one lab went weeks without a
worker being told it existed, and cleared every review by hand. Workers do
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
strings it prints, and what it prints when it fails. The command block runs
whole, as one shell script in which every line must succeed — the gate once
ran only the first line of a three-line block and passed on nothing. The timeout is set at
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
run whose worker process is still alive is refused until it exits — the
refusal prints the kill command — because a live worker writing into a filed
packet is a mutation nobody can audit. `--worker-done` covers a worker that
has exited without `execution.json` saying so; it never overrides a live
process, which is how an orphan once kept writing into a filed run while its
duplicate was dispatched.

Every refusal saves its reason to the run's `refusal.txt`. Filing the failure
is then one command with two honest verdicts: `ingest R-NNN --record-broken`
files `UNINGESTABLE` when a packet exists and failed a named gate, and
`HARNESS-FAILURE` when the worker never produced one — the recorded reason
and `execution.json`'s exit code go in the entry either way, `--reason` adds
yours and is required when nothing is on record, and whatever the
packet proposed is quoted there as untrusted text, so a refusal never
silently destroys a lead. A pure format failure may be bounced once: re-run
the same worker with the refusal text as its prompt (the launch command is in
`execution.json`) — the same actor repairing its own return launders nothing.
Fence and content failures are never bounced. Packets are never hand-edited —
a Director who repairs a worker's return has laundered its provenance. The
one field the Director may set at ingest is `reviewed`, with `--reviewed
R-NNN`, recorded as an override in the entry: a passing packet was once
thrown away because its referee named the wrong run.
Recovery is a fresh dispatch. A run that produced nothing at all is closed
with `run.py void R-NNN --reason`, so the open list never carries ghosts.

Ingest never promotes a claim. It files proposals as `proposed` and stops.
Promotion is your separate act, under `references/claims.md`, never on the strength of
the run that made the discovery.

## Transcripts

`worker.log` holds what a worker printed. What it was thinking and which
tools it called live in its command's own session store — one directory, on
one machine, pruned on that command's schedule. So ingest copies that
session file into the run as `session.jsonl.gz` and commits it with
everything else, and `--record-broken` does the same: the runs that most
need explaining a month later are the ones that were filed broken.

Discovery is configured, never compiled in — every command stores its
sessions somewhere different, and a pattern in the script goes stale the
first time one of them moves. A role in `lab.json` may carry
`"transcript": {"glob": "<pattern>", "match": "<rule>"}`. The glob takes `~`
and three spellings of the run directory — `{cwd}`, `{cwd_dashed}` (every
`/` replaced by `-`), `{cwd_urlencoded}` — because the stores that name a
folder after the working directory each mangle it differently. `match` is
`path`, which takes the newest match inside the run's own start-to-end
window, or `first-line-cwd`, which keeps only files whose first line is JSON naming
this run directory as its `cwd` — checked both at the top level of that
record and one level down inside it, because commands differ on where they
put it. As shapes: a command that writes one
JSONL per session under a date tree and puts the working directory in the
first line wants `first-line-cwd`; one that names the session folder after
the working directory wants `path` with `{cwd_urlencoded}` or
`{cwd_dashed}`. The window is what stops one worker's reasoning being filed
under another worker's verdict.

`ingest.json` records the source path, the sha256 of the file as it stood,
its size, its gzipped size, and whether the copy was kept. Over
`transcripts.max_mb` in `lab.json` (default 20) it is described but not
copied — the hash and the path are on record, so a large session can still
be fetched by hand while that machine exists. Nothing found means
`transcript: null` and one line saying so; a thin record is never a refusal.
`ingest --transcript <path>` names the file yourself, for a worker the
Director drove in its own session, where no role rule looks. `run.py lint`
says whether a run has one, and catchup names every ingested run whose role
says where to look and that has nothing stored. `run.py transcript <run>`
attaches one afterwards — by the role's rule, or `--path` — for the run
whose rule was wrong on the day, or whose store was still writing;
`--replace` swaps one already on record, and the swap is in the history.

## The commit guard

`run.py new` installs a pre-commit hook in the clone, once. It refuses any
commit that stages a file under a run still open, unless `run.py` or
`claims.py` made the commit. A refusal names the runs and the files; the
remedy is to name the paths meant, or to ingest or void the run. Catchup
says when the hook is missing. The failure it prevents: a Director, hours
into a session, committing a `lab.json` edit with `-A` and sweeping a live
worker's directory in with it — seven times in one day in one lab.

## Director notes

`run.py note` files a notebook entry you wrote yourself — headline and body,
your actor recorded, no packet and no claims. Use it for a decision, an
approach abandoned and why, a result reached in conversation with the
Investigator. Without it the only thinking on record is a worker's.

## Catchup

`run.py catchup` lists the runs, verdicts, and claim changes since a commit
or a date — with none given, since the last meeting, or the last seven days
when there has not been one, saying which it used — then the standing lints: runs needing attention, reviews owed
(aggregated, cleared by a referee or `run.py waive-review`), unresolved
duplicate-claim warnings, verified claims resting on unverified ones, claims
accepted on the Investigator's word, promotions with no model independence,
and per-model totals of runs, ingests, refusals and wall time. Every line is
closable — a flag nobody can clear teaches its reader to skim, which is how
an owed referee stayed flagged for three days and was never dispatched. You
tell the Investigator what it means, in plain sentences, without pasting the
listing. `new` and `ingest` also end by naming any run that needs attention,
so a stalled run cannot hide behind a report nobody asks for.

Every `dispatch.json` and `ingest.json` records the Director session that
wrote it (from `LAB_SESSION`, else `CLAUDE_CODE_SESSION_ID`, else `unknown`).
When the ingests under the current session reach
`machine.rotate_after_ingests` in `lab.json` (default 12), ingest says so,
with the reason: judgment degrades with context, and one lab's worst
hour was its longest session. Rotation is proposed to the Investigator and
done on their word; the charter has the steps.

## Resource accounting

`execution.json` in each run directory records the launch command, start and
end, exit code, wall time, the limits it was watched against, its peak
resident memory, any budget breach with when and what was seen, and — best
effort, via an optional `usage_pattern` regex per role in `lab.json` —
tokens and cost from the worker's log. Missing numbers stay missing, never
guessed. Beside it, `session.jsonl.gz` holds the worker's own transcript
when the role's rule found one (above). Each notebook entry ends with the run's
resource line, and catchup's per-model totals answer "is this model earning
its place" at a glance. What a theorem cost is a grep away: its claims name
their evidence runs, and the entries carry the footers.

## The honest stop

A worker that returns `UNDECIDED` naming its blocker precisely has succeeded,
and is graded as one. A manufactured verdict is the expensive failure. `run.py new` puts this in every assembled prompt, so the brief does
not repeat it.
