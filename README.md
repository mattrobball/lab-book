# Lab Book

A coding agent is a program that runs a language model in your terminal and
lets it read files, write files, and run commands. This package turns one into
a research lab. The model in your session becomes the **Director**: it writes
tasks for other model sessions, sends them off, checks what they bring back,
and keeps a notebook you can trust. You are the **Investigator**: you set the
questions and decide what matters. Nothing in the lab counts as a fact until
it is a claim with a status and evidence on record.

## What you actually do

- Say **open the lab**. The first time, you answer a few questions about the
  problem and confirm what the Director found on your machine and in the
  literature. Every time after, the Director tells you what changed since you
  were last there and proposes the next move.
- Read **`STATUS.md`** for a problem: one page, plain words, what the lab
  currently believes and what it has ruled out.
- Say what matters: which question next, what counts as evidence, when to
  stop.

That is the whole job. The Director runs the scripts; you never have to.

## Your first hour

1. **Install a coding agent.** Any of these works; pick the one whose vendor
   you have an account with.
   - Claude Code: `npm install -g @anthropic-ai/claude-code`, then type
     `claude` in a terminal.
   - Codex: `npm install -g @openai/codex`, then `codex`.

   Open a terminal, make an empty folder for the lab, `cd` into it, and start
   the agent there.
2. **Install this skill.** Inside the agent, say:

       install the skill from mattrobball/lab-book

   or, from a shell, `npx skills add mattrobball/lab-book`. (By hand: copy
   `skills/open-lab/` into your agent's skill folder — see the table at the
   end.)
3. **Say "open the lab".** The Director asks its questions one at a time —
   what the problem is, what would convince you a result is true, what is
   already known, what the limits are. Answer in plain sentences. It then
   looks for the tools on your machine, the papers, and the public data on
   your exact question, and shows you each list to confirm or strike. Then
   it sets up the folder and proposes the first task.
4. **Watch the first task go round.** The Director writes a **brief** (the
   task, in full), sends a **worker** to do it, and when the worker returns
   the result is checked by machine, filed, and summarised for you in a few
   sentences. Anything the worker claims appears as a numbered **claim**
   (`C-001`, `C-002`, …) marked *proposed* — not yet believed. A second
   worker, on a different model, is sent to attack it before it is believed.

## Every day after

Say **open the lab**. The Director reads what happened since you last
looked, tells you where things stand in plain sentences, and proposes the
next move. You say yes, no, or something else. When you want the whole
picture, read the problem's `STATUS.md`.

## The words

The Director defines each of these the first time it uses one in a message,
and `GLOSSARY.md` in your lab has the full list, each with an example and the
file that owns the rule.

- **Brief** — a task written for a worker: the goal, what it may rely on,
  what counts as success. *"Prove or refute: the largest cap in dimension 4
  has 20 points."*
- **Run** — one worker sent on one brief, numbered `R-001`, `R-002`, …
- **Packet** — what the worker brings back: a verdict (PASS, FAIL, or
  UNDECIDED), what it did, what it does *not* claim, and how to check it.
- **Ingest** — the gate: the packet is checked, its evidence is re-run by
  machine, and only then is the run filed. An unfiled run does not exist.
- **Claim** — one statement with an ID and a status. *Proposed* means stated;
  *verified* means checked here, on record, by someone other than whoever
  found it; *refuted* means shown false.
- **Replay / review** — the two ways a result is validated: a machine
  re-runs the exact command and checks the exact output, or a different
  worker checks the argument by hand and the record says who and what.
- **Catchup** — the report at the start of every session: runs, verdicts,
  claim changes, and anything that needs a decision.

## When it refuses

Four things are enforced by the scripts. The Director will not work around
them, and neither should you; each refusal tells you what to do.

1. **A claim's status changes only through the script.** You will see the
   Director decline to write "verified" into a page by hand. It is right;
   ask it to set the status with the evidence run named.
2. **A run enters the record only through ingest.** A worker's result that
   was never filed is not evidence, however good it looked. Ask for it to be
   ingested, or closed with a reason.
3. **No task goes out without a named model.** The Director must say which
   model does the work; a default is fine, silence is not.
4. **The scripts and the lab's settings change only with your explicit
   agreement.** The Director will ask you before changing a rule, record your
   answer, and run one small test task afterwards.

Two more things come to you as decisions, never taken alone: a worker that
has gone over its time or memory budget (kill it, or let it run), and a
session that has run long enough to degrade (start a fresh one, or carry
on).

## Working as a group

Several people can share one lab, each with their own copy of it.

- Everyone starts by saying **join the lab**, once, on their own machine.
  From then on their work is written to their own line of the record and
  numbered with their own initials, so two people can never label two
  different things the same way.
- Every morning the Director tells you what the others recorded since you
  last looked — their tasks, their results, their claims — without mixing
  their record into yours. An experiment belongs to whoever ran it: you cite
  someone else's, you never edit it.
- What the group has agreed lives in one place, and it changes only at a
  **meeting**. You get on a call, one person shares their screen, and the
  Director reads out the list of things the records disagree about: the same
  result claimed twice, one page rewritten two different ways, a task left
  open for a week. The room decides each one and the decision is written
  down before the next.
- Afterwards everyone is back on the same page, literally, and the minutes
  of the meeting are in the notebook.

This prevents the two failures that end shared work: two people quietly
believing different things until it matters, and a day spent untangling
whose copy of a file is right.

## The design principle

Every mechanism here names the failure it prevents. If it cannot name one,
it should not exist.

- **One notebook file per entry, plus a generated index** — prevents the
  single notebook file that grows until nobody reads it and two versions of
  the bottom line drift apart inside it.
- **Claim status only through a script** — prevents a status that was
  hand-edited into a file, believed for weeks, and traceable to nothing.
- **The script commits its own writes** — prevents evidence that exists on
  someone's disk but not in the history, which is a rumour.
- **Replay with exact marker strings** — prevents a worker's report of
  success standing in for success.
- **The discoverer never promotes its own result** — prevents a run grading
  its own homework.
- **Catchup** — prevents "what happened last week?" being answered by
  grepping a hundred run directories.
- **A commit guard on open runs** — prevents a tired Director sweeping a
  live worker's half-written files into the history.
- **A watched wait on every worker** — prevents a run running for hours, or
  thirty times over its memory budget, with nobody told.
- **One branch and one set of numbers per person** — prevents two people
  labelling different results the same way, and a day of untangling whose
  copy of a file is right.

## Install, in full

Claude Code can also install it as a plugin:

    /plugin marketplace add mattrobball/lab-book
    /plugin install lab-book@lab-book

By hand, copy the `skills/open-lab/` directory into your agent's skill path:

| CLI | Path |
|---|---|
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.codex/skills/` |
| Cursor | `~/.cursor/skills/` |
| Gemini | `~/.gemini/skills/` |
| Copilot | `~/.copilot/skills/` |
| pi | `~/.pi/agent/skills/` |
| shared, where supported | `~/.agents/skills/` |

New skills load without a restart in Claude Code, Copilot (`/skills reload`),
and pi (`/reload`); Codex and Gemini sessions need a restart to see them.

## Status

Complete and in daily use. The charter, the two
references, the templates, the glossary, and both scripts with their test
suite (`python3 -m unittest` from `skills/open-lab/scripts/tests/`).

## Contributing

Issues welcome. For proposed mechanisms, the kit's own rule applies: name the
failure it prevents, or it should not exist. Name it in general words — what
went wrong, never where: no run IDs, no lab, problem, vendor or model names.
The kit's reference run is the one worked example it may cite. Facts about a
particular lab live in that lab.
