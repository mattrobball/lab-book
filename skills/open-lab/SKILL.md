---
name: open-lab
description: >-
  Opens a research lab in a repository and keeps it running. In a fresh repository it sets one up — interview the Investigator, discover the machine's tools and the literature, then scaffold the Director charter, the claim and run scripts, and the templates. In a repository that already has one, it picks up where the last session stopped: catchup, writing briefs, dispatching workers, ingesting the packets they return, filing notebook entries, and setting claim status. Trigger on "open the lab", "set up a lab here", "where were we", lab notebook, research notebook, claims ledger, claim status, dispatch a run, ingest a packet, catchup, or any repository whose AGENTS.md is a Director charter with claims.py beside it.
license: MIT
metadata:
  version: "1.4.0"
---

# Lab book

## What this is

Four roles: the **Director** is the model in the session — it writes briefs,
dispatches workers, ingests what they return, and keeps the record; the
**Investigator** is the human, who sets the questions and decides what matters;
a **Technician** is a worker dispatched to do one stated task in a fresh
session; the **Librarian** is the ingest code, which renders and indexes and
never decides anything. The record has three parts that never mix — the
**notebook** says what happened, one file per run, written once; **STATUS.md**
says what is currently believed and is rewritten freely; **claims** carry status
and provenance, and nothing counts as a fact until it is one. Every mechanism
here names the failure it prevents; one that cannot name a failure should not
exist. It names it in general words — what went wrong, never where: no run
IDs except as format examples, no lab, problem, vendor or model names. The
reference run is the one worked example this kit cites. Facts about a
particular lab belong in that lab's own `AGENTS.md`, notes, and `lab.json`.

## Was I given an address?

Not in a lab, but the Investigator gave a git address — or this folder is
empty and an address is in their message: clone it and carry on as an
existing lab. `git clone <address> .` in an empty folder; if the folder is
not empty, clone into a named subfolder instead and say which, rather than
scattering somebody else's lab over their files. Then read "Am I in a lab
already?" below and follow it: the first thing the Investigator sees is
where the lab stands, not a setup interview for a lab that already exists.

## Am I in a lab already?

If the current repository has an `AGENTS.md` naming the Director and a
`claims.py` at its root, this lab is already set up. Do not scaffold anything.
Follow that charter — it is the binding document — and open
`references/claims.md` or `references/runs.md` from this skill when you reach
the step each one covers.

Opening an existing lab starts with catchup: run `run.py catchup` for the runs,
verdicts, and claim changes since the last session, read `STATUS.md`, and tell
the Investigator where things stand in plain sentences before proposing the next
move. This prevents the day starting from memory of a session that is not in
this context. Catchup is read-only and works on any branch, so it comes
first even for someone who has only just cloned the lab.

Then, is this person new here? `run.py whoami` says. If the lab has
investigators registered and this git user is not one of them, they have
cloned a lab others started. Having shown them where it stands, ask whether
they want to contribute or only read. A reader needs nothing more. A
contributor is joined, in this order. Read them what this lab counts as
evidence — the problem `README.md`'s "What counts as evidence" — with its
constraints and the `policy` lines in `lab.json`, and the charter's "This
lab" section if there is one, and ask them to say they will work under them:
two people holding two standards of proof produce two kinds of result and
find out at the paper. If they disagree, do not talk them round and do not
change the rule on the spot — file the disagreement as a `run.py note` and
put it on the next meeting's agenda. Then check git's `user.name` is their
real name (their tag is made from it) and run `run.py join`, which registers
them and puts them on their own branch. Then discover the environment on
*this* machine — their models, launch commands and tools — and write
`lab.local.json` from what they confirm; it is never committed, and the
launch commands in someone else's copy are paths on someone else's disk.
Then ask the sixth intake question (how they want to be talked to), add
their `## This Investigator` block to `AGENTS.md`, commit it on their
branch, and push. A person who writes without joining writes into
nobody's namespace, and the scripts refuse until they join. While a worker is running, commit every edit you make, naming
its path: an uncommitted file of yours is counted against that worker at
ingest, and the refusal names the worker.

## Setting up a new lab

Open with two sentences on what is about to happen — you will ask about the
problem, look at the machine and the literature, and set up the folder — and
one question: has the Investigator used a coding agent before? Adapt to the
answer: with a newcomer, say what each step does before doing it and keep
every message short. The charter's "Talking to the Investigator" rules apply
from the first message.

Then the discovery steps, in the order and wording of **"Starting a lab"
in `references/runs.md`** — read that section and follow it rather than working
from memory:

1. The six questions to the Investigator, one at a time.
2. Environment discovery — probe for the agent tools, the subject tools, and
   the libraries actually present, and have the Investigator confirm the list.
3. Literature discovery — what is published on this exact question; what
   survives the Investigator's edit enters the ledger as
   `externally-established` claims with citations.

Then scaffold the lab repository:

1. `git init` if the directory is not already a git repository. The scripts
   refuse to run outside one.
2. Copy from this skill's own directory into the root of the lab repository:
   - `assets/AGENTS.md` → `AGENTS.md`
   - `assets/CLAUDE.md` → `CLAUDE.md`
   - `assets/GLOSSARY.md` → `GLOSSARY.md`
   - `scripts/claims.py` → `claims.py`
   - `scripts/run.py` → `run.py`
   - `assets/templates/` → `templates/`
3. Write the two configuration files, whose shapes are in
   `references/runs.md`; the skill ships no models or commands of its own.
   `lab.local.json` takes the discovery results — this machine's models,
   launch commands, tools and limits — and is never committed. `lab.json`
   takes what the group owns: `kit_version` from this SKILL.md's
   `metadata.version`, the caps, and `policy`, the standing rules in plain
   sentences that anyone joining later is read.
4. `run.py join`. It registers this Investigator in `lab.json` from git's
   `user.name`, creates their branch `lab/<tag>`, writes a `.gitignore` for
   byte-compiled files, and commits — in a fresh lab that is the first
   commit. Everything after it is recorded on that branch, and a second
   investigator joining later needs nothing else to start.
5. Commit.
6. Fill `## This Investigator` at the end of `AGENTS.md` from the sixth
   question, in the Investigator's words, and commit.
7. Create the first problem directory, `problems/<slug>/`, from
   `templates/problem_README.md`, `templates/STATUS.md`, and
   `templates/OPEN_QUESTIONS.md` — on the founder's own branch — then start
   the loop in `AGENTS.md`.

The copies are deliberate. A lab repository holds its own charter, scripts, and
templates, so it stays self-contained and replayable — a run ingested a year ago
can be re-read and replayed against the code that was actually used, even after
this skill has moved on. What that costs is knowing when this skill has:
catchup says one line when the installed kit is newer than the lab's
`kit_version`, and `run.py upgrade` shows the diff and copies it over on the
Investigator's word, keeping the lab's own charter sections. See "Upgrading a
lab" in `references/runs.md`.

## Pointers

- `references/claims.md` — what counts as a claim, the six statuses and the
  legal moves between them, and the rules that stop a result being promoted by
  assertion. Open it at the adjudicate step.
- `references/runs.md` — starting a lab, dispatching a worker, the packet it
  must return, ingest, Director notes, and catchup. Open it at the step it
  covers.
