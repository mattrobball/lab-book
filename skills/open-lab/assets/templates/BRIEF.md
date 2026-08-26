# Brief: <short title>

## Kind

<construct | check | refute | measure | survey>

## Goal

<The precise question, in one or two sentences. A worker with no context should
be able to tell whether it has been answered.

For a check of prior work, use this framing verbatim, filled in: "A claims X;
review the claim adversarially but fairly — your job is to prove or refute
it. A refutation with an explicit witness is full success. A PASS must name
what you attacked and could not break." If the claim rests on computation,
add: "Write your own verifier from the statement; do not run or trust the
original's." If the checker's method will differ from the original's, name
a control: "First reproduce <a case the original's method got right>; only
then attack the claim" — a referee once switched engines, never calibrated,
and returned a wrong answer. Name the run under check — "This is a check of
R-NNN" — and dispatch with `--checks R-NNN`, so the record shows which run
was refereed.>

## Context carried

<What the worker may rely on, pasted in here — not referenced. The minimum it
needs, not everything you have: more context measurably hurts a worker. Paste
each claim with its status attached — `C-NNN [verified] — statement` — and mark
anything not verified as "not settled here". The file contents it needs, or
leave to read `tools/`. Anything a previous run got wrong and how it was
corrected. Mark each item "do not re-derive".>

## Allowed writes

<The exact paths this worker may create or modify. If other workers are running
in parallel, name their directories here as off-limits.>

## Bans

- No `git` commands of any kind.
- Never invent a claim ID. Copy into `claims_used` exactly the IDs given in
  Context carried, and propose new claims as plain sentences.
- Nothing written outside Allowed writes.
- No backgrounded jobs. Run long computations in the foreground and wait. If
  one will not finish inside your session, checkpoint to disk, say where in
  `## What was done`, and return UNDECIDED — a session once exited with its
  calculation still running and the result in limbo.
- <Anything specific to this task: a method known not to work, an input known
  to be degenerate.>

## Machine budget

<Memory the whole run may hold resident, and per process; wall time. State
them as numbers: "≤ 10 GB resident, ≤ 3 GB per process; ≤ 4 h". Heavy runs
stream to disk and checkpoint. The Director passes the same numbers to
`run.py new --memory-gb --worker-timeout`; a breach is reported to the
Investigator, who decides whether the run dies or continues.>

## Metrics

<What makes this PASS. The values to report, and the exact marker strings the
replay must print. The replay is one code block, run as one shell script: a
single command, or several lines joined with `&&`; every line must succeed. If
nothing here is executable, say so and say what a referee would have to check
instead.>
