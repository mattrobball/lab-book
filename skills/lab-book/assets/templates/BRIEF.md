# Brief: <short title>

## Kind

<construct | check | refute | measure | survey>

## Goal

<The precise question, in one or two sentences. A worker with no context should
be able to tell whether it has been answered.>

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
- <Anything specific to this task: a method known not to work, an input known
  to be degenerate.>

## Metrics

<What makes this PASS. The values to report, and the exact marker strings the
replay must print. If nothing here is executable, say so and say what a referee
would have to check instead.>
