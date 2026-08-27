# Glossary

The words this lab uses. Each entry gives the meaning, one small example, and
the source — the file that owns the rule, so a reader can go and check. Every
message to the Investigator defines a term from here on first use, in these
words. The mathematics has its own glossary: each problem's `README.md`,
"Objects and definitions", written at intake — every term with an example and
a source (the paper or book, or "Investigator, intake").

## People and roles

- **Investigator** — the human. Sets the questions, decides what matters and
  when a line of work is done.
  *Example:* "Settle dimension 4 exactly, then stop" is an Investigator's
  instruction; the Director does not choose to go on to dimension 5.
  *Source:* `AGENTS.md`, "Who's who".
- **Director** — the model in the session. Writes briefs, dispatches workers,
  files what they return, keeps the record, talks to the Investigator. Never
  does the evidence-bearing work itself.
  *Example:* the Director may sketch a proof in conversation; it becomes
  evidence only when a worker checks it in a run.
  *Source:* `AGENTS.md`, "Who's who" and "The loop", step 5.
- **Worker** (Technician) — a fresh model session sent to do one stated task.
  It sees nothing but its brief.
  *Example:* "technician-a, dispatched as R-012 to check C-005" — it never sees
  STATUS.md or the other runs.
  *Source:* `AGENTS.md`, "Who's who"; `references/runs.md`, "Dispatching".
- **Librarian** — the ingest code. Renders entries, rebuilds indexes, decides
  nothing.
  *Source:* `AGENTS.md`, "Who's who".
- **Investigator tag** — the short name an investigator's IDs and branch are
  written with, made from their git `user.name` and unique in the lab.
  *Example:* a person whose git name is two words joins as `<tag>`, and
  their runs are numbered `R-<tag>-001`.
  *Source:* `references/runs.md`, "Joining a lab".
- **Role** — a named worker configuration in `lab.json`: which model, how it
  is launched, what it is for and not for, its default budgets, whether it
  is on hold.
  *Example:* `"technician-b": {"model": "<model>", "command": "...",
  "note": "for: enumeration; not for: reading-heavy tasks"}`.
  *Source:* `references/runs.md`, "Starting a lab" (the `lab.json` shape).

## The work

- **Problem** — one question with its own directory under `problems/`: its
  README, STATUS, open questions, claims, runs, notebook, sources, tools.
  *Example:* `problems/cap-ag3/` — "how large can a cap in AG(n,3) be?"
  *Source:* `AGENTS.md`, "New problems".
- **Brief** — the task written for a worker: kind, goal, what it may rely on
  (pasted in), where it may write, bans, machine budget, what counts as
  success.
  *Example:* "Kind: check. Goal: A claims the largest cap in dimension 4 has
  20 points; prove or refute it. Allowed writes: this run directory."
  *Source:* `templates/BRIEF.md`; `references/runs.md`, "Dispatching".
- **Kind** — what sort of task a brief is: construct, check, refute, measure,
  or survey.
  *Source:* `templates/BRIEF.md`.
- **Run** — one dispatch of one worker on one brief, numbered `R-NNN`. Its
  directory holds the brief, the assembled prompt, the worker's output log,
  execution record, and packet.
  *Example:* `problems/cap-ag3/runs/R-012/` — the twelfth worker sent at
  that problem.
  *Source:* `references/runs.md`, "Dispatching".
- **Dispatch** — `run.py new`: allocating a run, recording who and what, and
  launching the worker.
  *Example:* `run.py new --brief briefs/check-c005.md --role technician-b
  --checks R-012`.
  *Source:* `references/runs.md`, "Dispatching".
- **Packet** — what a worker returns, in its run's `packet/`: `RESULT.md`
  (verdict line, what was done, not claimed, leads, validation) and
  `RETURN.json` (the same in fields).
  *Source:* `references/runs.md`, "The return packet"; `templates/RESULT.md`,
  `templates/RETURN.json`.
- **Verdict** — the packet's first line: PASS, FAIL, or UNDECIDED. An honest
  UNDECIDED naming its blocker is graded a success; a manufactured PASS is
  the expensive failure.
  *Example:* "# VERDICT: UNDECIDED — the search reached dimension 5 prefix
  10 and ran out of time; checkpoint in `state.pkl`."
  *Source:* `references/runs.md`, "The honest stop".
- **Not claimed** — the packet section stating what the work does not
  establish. Graded: a narrow honest boundary beats a loud headline.
  *Example:* "Not claimed: anything for n > 4; the n = 4 count assumes the
  symmetry reduction in C-003."
  *Source:* `templates/RESULT.md`.
- **Leads** — the packet section for strategy: what was dropped and why,
  what looked promising, what to try next. The next brief is written from
  it.
  *Source:* `templates/RESULT.md`.
- **Ingest** — `run.py ingest`: the gate. Checks the packet, replays its
  evidence, checks the fence, files the notebook entry, allocates proposed
  claims, commits. A run exists in the record only after ingest.
  *Example:* `run.py ingest R-012` → "R-012 PASS (replayed: yes)".
  *Source:* `references/runs.md`, "Ingest".
- **Refusal** — the gate saying no, with the reason saved to the run's
  `refusal.txt`. Information, not an obstacle; never worked around.
  *Source:* `AGENTS.md`, "The four refusals"; `references/runs.md`, "Ingest".
- **UNINGESTABLE / HARNESS-FAILURE** — the two verdicts for a run filed
  broken: a packet exists but failed a gate; or no packet was ever produced.
  Filed with `ingest --record-broken --reason`.
  *Source:* `references/runs.md`, "Ingest".
- **Void** — closing a run that produced nothing, reason on record, so the
  open list never carries ghosts.
  *Example:* `run.py void R-019 --reason "launched with --no-launch by
  mistake; never started"`.
  *Source:* `references/runs.md`, "Ingest".

## Evidence

- **Replay** — a machine re-running the packet's command block, as one shell
  script, and checking that the exact strings it promised appear. Proves the
  command ran and printed them — not that anything was recomputed; the
  referee checks that.
  *Example:* command `python3 cap_check.py --n 4`; must print `CAP_20_OK`.
  *Source:* `references/runs.md`, "Replay or review".
- **Marker** — one of those exact strings. Matched character for character,
  never by pattern.
  *Source:* `references/runs.md`, "Replay or review".
- **Review** — a different actor checking work by hand, on record: who, when,
  what they checked. A proof is validated by review; a review nobody has
  done validates nothing.
  *Source:* `references/runs.md`, "Replay or review".
- **Referee** — the worker dispatched to do a review, told to attack the
  claim: prove or refute it, and name what it attacked and could not break.
  *Example:* "R-015 (model B) refereed R-012 (model A): PASS — attacked the
  symmetry reduction and the count; neither broke."
  *Source:* `templates/BRIEF.md`, Goal; `references/runs.md`, "Dispatching".
- **Control** — a case the original method got right, which a referee using
  a different method reproduces before attacking the claim.
  *Example:* "Before enumerating n = 5, reproduce the n = 4 count of 20."
  *Source:* `templates/BRIEF.md`, Goal.
- **Fence** — the paths a worker may write. Ingest refuses a packet whose
  worker wrote elsewhere, judged only by what that worker could have written.
  *Source:* `references/runs.md`, "Ingest".
- **Transcript** — the worker's own session file — its reasoning and tool
  calls — copied into the run at ingest as `session.jsonl.gz`, with its
  hash and size on record. Found by the rule the role carries in
  `lab.json`, or named with `ingest --transcript`.
  *Example:* a run filed broken still has the session that produced it,
  after that machine's own store has pruned it.
  *Source:* `references/runs.md`, "Transcripts".
- **Machine budget** — the memory and wall time a run is watched against.
  A breach is recorded and reported at every step; whether the run dies is
  the Investigator's decision.
  *Example:* `--memory-gb 10 --worker-timeout 14400`.
  *Source:* `templates/BRIEF.md`, "Machine budget"; `references/runs.md`,
  "Dispatching".

## Claims

- **Claim** — one statement, with its conditions, that something in this
  repository could show to be wrong, under an ID `C-NNN` with a status. Not a
  topic, not a plan.
  *Example:* "C-005: the largest cap in AG(4,3) has exactly 20 points."
  *Source:* `references/claims.md`, "What counts as a claim".
- **Observation / inference / claim** — what a run measured; what you
  concluded; an inference someone has staked a status on.
  *Example:* "printed CAP_20_OK on all inputs" / "so the bound is 20" /
  "C-005 [verified]".
  *Source:* `references/claims.md`, "What counts as a claim".
- **Status** — where a claim stands. `proposed`: stated, nothing settles it.
  `verified`: validated here, on record, by someone other than its
  discoverer. `conditional`: holds given something not verified here.
  `externally-established`: in the literature, cited, not re-derived.
  `accepted-by-investigator`: taken on the Investigator's recorded word.
  `refuted` and `superseded`: final.
  *Example:* C-005 was `proposed` at ingest of R-012, `verified` after R-015
  refereed it.
  *Source:* `references/claims.md`, "The six statuses", "The moves between
  them".
- **Affirm** — recording a decision that leaves a claim's status where it
  is, with the reason. Otherwise a room that considered a claim and kept it
  leaves no trace, and the next meeting argues it again.
  *Example:* `claims.py affirm C-005 --reason "the objection was answered in
  the run"`.
  *Source:* `references/claims.md`, "Deciding to change nothing".
- **Promotion / demotion** — a status change up or down, only through
  `claims.py`, never by editing a file, never by the run that made the
  discovery.
  *Example:* `claims.py set C-005 verified --evidence R-015 --rests-on none`.
  *Source:* `references/claims.md`, "The hard rules".
- **Rests on** — the claims a claim depends on. If any is not verified, the
  claim is at most conditional; when one falls, its dependents surface.
  *Example:* "C-007 rests on C-005" — refute C-005 and C-007 is listed.
  *Source:* `references/claims.md`, "The hard rules".
- **Independence** — whether a claim's checker differed from its discoverer:
  full (different model), partial (same provider), none (same model —
  allowed only with `--accept-same-model`, always visible).
  *Source:* `references/claims.md`, "The hard rules".
- **Ledger** — the append-only file of claim events per problem, one per
  investigator under `claims/`. The only truth about status; `CLAIMS.md` and
  the per-claim pages are views of them all.
  *Source:* `references/claims.md`, "One ledger each", "Generated files".

## The record

- **Notebook** — one file per run or note under `notebook/entries/`, written
  once, never edited. Says what happened. Corrections are new entries.
  *Source:* `AGENTS.md`, "The notebook".
- **Note** — a notebook entry the Director writes itself: a decision, an
  abandoned approach, a result reached in conversation, a handoff.
  *Example:* `run.py note --headline "Dropped the greedy scan" --body "..."`.
  *Source:* `references/runs.md`, "Director notes".
- **STATUS.md** — the hand-written page saying what the Director currently
  believes about a problem. Rewritten freely. Belief, labelled as such: a
  proposed claim appears only as "C-NNN (proposed, unreviewed)".
  *Source:* `AGENTS.md`, "The epistemic rule"; `templates/STATUS.md`.
- **Open questions** — `OPEN_QUESTIONS.md`: questions someone could be
  dispatched to answer, each with why it matters and what an answer would
  look like.
  *Source:* `templates/OPEN_QUESTIONS.md`.
- **Sources** — the problem's `sources/` directory: cached literature with a
  hash manifest, and `QUERIES.md`, the log of searches. Done once.
  *Source:* `references/runs.md`, "Sources".
- **Tools** — the problem's `tools/` directory: reusable scripts a run built,
  each headed by what it does and which run built it.
  *Source:* `references/runs.md`, "Dispatching".
- **Catchup** — `run.py catchup`: what changed since a date or commit, plus
  the standing warnings, each of which can be cleared. The first thing a
  session runs.
  *Example:* `run.py catchup 2026-08-25`.
  *Source:* `references/runs.md`, "Catchup".
- **Hold** — a role marked unavailable until a date in `lab.json`. Lifts
  itself; catchup lists holds in force.
  *Example:* `"unavailable_until": "2026-09-01", "note": "quota exhausted"`.
  *Source:* `references/runs.md`, "Starting a lab".
- **Commit guard** — the pre-commit hook `run.py new` installs: refuses a
  hand commit that touches an open run's files.
  *Source:* `references/runs.md`, "The commit guard"; `AGENTS.md`,
  "Committing".
- **Branch** — where one investigator's record is written: `lab/<tag>`. The
  scripts refuse a write from anywhere else; `main` holds what the group has
  agreed and is written only by the meeting.
  *Example:* `run.py join` creates and checks out `lab/<tag>`; `run.py
  whoami` says which branch you are on and what is unpushed.
  *Source:* `references/runs.md`, "Joining a lab"; `AGENTS.md`,
  "Committing".
- **Stream** — one investigator's ledger, `claims/ledger-<tag>.jsonl`,
  appended to by them alone. A claim's state is the latest event across all
  the streams.
  *Example:* two streams leave one claim `verified` in one and `refuted` in
  the other; the meeting settles it.
  *Source:* `references/claims.md`, "One ledger each".
- **Meeting** — the call where the investigators agree the record: every
  branch merged into `main`, the agenda taken in order, each decision
  recorded before the next item.
  *Example:* the commit `meeting: <date> (<tags>)` and the minutes beside it
  in `notebook/meetings/`.
  *Source:* `AGENTS.md`, "Investigators' meeting"; `references/runs.md`,
  "The meeting".
- **Reconcile** — `run.py reconcile`: the script that runs a meeting. First
  it merges and prints the agenda; with `--close --present <tags>` it files
  the minutes, commits, and fast-forwards every branch onto `main`.
  *Source:* `references/runs.md`, "The meeting".
- **Agenda** — the numbered list reconcile writes to
  `notebook/meetings/<date>-agenda.md`: one line per thing two records
  disagree about or one has left open, each with the command that settles
  it.
  *Example:* "the same statement proposed in two streams — supersede one".
  *Source:* `references/runs.md`, "The meeting".
- **Unpushed** — commits recorded on this machine that the remote has not
  got. Counted by catchup and `whoami`; a record only one laptop holds is a
  record the group cannot read.
  *Example:* "yours: unpushed 3" — push before the meeting.
  *Source:* `references/runs.md`, "Seeing the others".
- **Duplicate run** — a run that deliberately repeats another, declared with
  `run.py new --duplicates <run>`. Catchup names the pair until the original
  is closed, so two people doing one job is seen the same day.
  *Source:* `references/runs.md`, "Joining a lab".
- **Kit version** — which release of the kit this lab's copies of the
  scripts came from, in `lab.json` as `kit_version`. Catchup says when the
  installed kit is newer; `run.py upgrade` shows the diff and, on the
  Investigator's word, brings the copies over and files a note.
  *Example:* "The installed kit is 1.3.0; this lab's scripts are 1.1.0."
  *Source:* `references/runs.md`, "Upgrading a lab".
- **Session rotation** — starting a fresh Director session because the
  current one has run long. Proposed to the Investigator with the reason;
  done on their word; the next session opens with catchup.
  *Source:* `AGENTS.md`, "Session rotation".
- **Handoff** — the note a rotating Director files: what is open, what was
  decided, what the next session should do first.
  *Source:* `AGENTS.md`, "Session rotation".
