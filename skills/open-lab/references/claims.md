# Claims

## What counts as a claim

A claim is one statement, with its conditions attached, that something in this
repository could show to be wrong. Not a topic, not a plan, not a direction of
work.

Three things are easy to confuse:

- **Observation** — what a run measured. "The check ran on all 40 inputs and
  printed `CHECK_OK` for each." Lives in the run's packet.
- **Inference** — what you concluded from observations. "So the second method
  handles every input we care about." Lives in prose.
- **Claim** — an inference someone has staked a status on, under an ID. Lives
  in the ledger.

Observations are cheap and plentiful. Turn an inference into a claim only when
later work will lean on it.

## The six statuses

| Status | Meaning |
|---|---|
| `proposed` | Stated. Nothing settles it yet. |
| `verified` | Established here, by validation on record: a replay that passed, or a review by someone other than its discoverer. |
| `conditional` | Established *given* something this repository has not itself verified. |
| `externally-established` | Established in the published literature, cited, not re-derived here. |
| `accepted-by-investigator` | Taken as true on the Investigator's recorded decision — not proved here, not read in full. Visibly weaker than either of the above, and listed by catchup so nothing forgets what rests on decree. |
| `refuted` | Shown false under the claim's own stated conditions. Terminal. |
| `superseded` | Replaced by a sharper claim. Terminal. |

## The moves between them

| From | Legal targets |
|---|---|
| `proposed` | `conditional`, `verified`, `externally-established`, `refuted`, `superseded` |
| `conditional` | `verified`, `proposed`, `refuted`, `superseded` |
| `externally-established` | `conditional`, `proposed`, `refuted`, `superseded` |
| `accepted-by-investigator` | `proposed`, `refuted`, `superseded` |
| `verified` | `conditional`, `proposed`, `refuted`, `superseded` |
| `refuted` | none — terminal |
| `superseded` | none — terminal |

A move back to `proposed` is a **demotion**: use it when the evidence stops
holding up but nothing has actually refuted the statement. `verified →
proposed` is the common case — a replay that no longer runs, or a dependency
that turned out to be shakier than it looked. Demoting is cheap and honest.
Leaving a claim at `verified` while you privately doubt it is neither.

`conditional → verified` is legal only once the thing it rested on is itself a
`verified` claim in this repository, cited by ID. The script checks this on
every move to `verified`, from any status. `verified → conditional` is the
honest correction when a verified claim turns out to rest on something not
verified here — it once had to be demoted all the way to `proposed` for want
of that move.

## The hard rules

- **IDs come only from `claims.py`.** Never write a new ID by hand. Workers
  never allocate at all — they propose claims as plain sentences, and the ID is
  allocated when their run is ingested.
- **No self-verification.** Whoever discovered a result never promotes it. A
  different actor, in a different run, has to confirm it. A confirming brief
  pastes the statement to check, never the discovering run's method.
- **`verified` requires validation on record in an ingested run** — a replay
  that passed, or a review by an actor different from the discoverer. Work that
  never went through ingest does not exist for this purpose, however convincing
  it looked at the time. A citation is not validation: it makes a claim
  `externally-established`. The script checks `ingest.json`, not the
  packet: a refused packet still has its files on disk, and a claim was once
  promoted on a check run the gate had rejected.
- **Never chain a status change after an ingest in one command.** If the
  ingest is refused, the `claims.py set` behind it still fires. Run the
  ingest, read its verdict, then change status as a separate command.
- **Verifying names its evidence and its ground.** `claims.py set verified`
  takes `--evidence R-NNN` and `--rests-on` (claim IDs, or `none`). The script
  compares the evidence run's model against the discovering run's and records
  the result on the claim — `full`, `partial (same provider)`, or, only with
  `--accept-same-model`, `none`. Same-model checking is allowed, not
  preferred, and always visible: the reference run promoted a claim on a
  run by the very model that discovered it, and nothing showed it.
- **When a claim falls, its dependents surface.** Refuting, superseding or
  demoting prints every claim resting on it, transitively. State dependencies
  at promotion, when the proof is fresh — the one dependency hunt done by
  hand took four hours and missed one.
- **`refuted` and `superseded` are terminal.** Reviving an idea means a *new*
  claim, with a new ID, citing the old one. The old one stays where it is.
  Otherwise nobody can tell later which version of a claim an argument used.
- **Resting on the literature alone means `conditional`, not `verified`**,
  however solid the source is. `externally-established` is for a result you are
  citing whole and not building on; the moment your own claim depends on it,
  your claim is conditional.

## One ledger each

Each investigator writes their own append-only stream,
`claims/ledger-<tag>.jsonl`, with the stream from before anyone joined read
alongside them. Nobody appends to anybody else's. Two people writing one
file conflict on every push, over lines neither of them wrote.

A claim's current state is its **latest event across every stream**. The
scripts read all of them, fold the statements in before the status changes —
two machines' clocks need not agree — and rebuild the views from the result.
When two streams have left one claim in two different states, that is a
disagreement between people, and it goes on the meeting's agenda rather than
being resolved by whoever ran a script last.

Claim IDs carry their author's tag (`C-<tag>-004`), so two investigators
cannot mint the same one, and a claim from another stream is cited by ID like
any other. What you may not do is set the status of a claim you cannot see
in your own tree: cite it as fetched, and settle it at the meeting.

`independence` records one thing more when the check came from another
investigator's run: "different lab". A second machine, a second person and a
second model reaching the same result is the strongest form on offer here,
and it is worth being able to grep for.

## Who a change is credited to

`--actor` says who is making a change. Once the lab's investigators have
joined, it defaults to the caller's own tag, so nobody retypes their name
into every command; in a lab nobody has joined there is no tag to assume and
`--actor` is required. Credit is never guessed from the run: a claim's
discoverer is the actor the dispatch stamped, and that is what stops a run
confirming itself.

## Stating a claim that only cites a source

`claims.py new` states a claim as `proposed` and prints, with the ID, what
would settle it. Two statuses may be given at birth instead, in one command
and one commit: `--status externally-established --evidence "<citation>"`
and `--status accepted-by-investigator --evidence "<the decision>"`. Neither
rests on work of ours, so there is nothing for a later command to check.
Every other status is refused there and reached with `set`: `verified` needs
an ingested run that checked the claim, and a claim cannot be born already
confirmed.

## Citing claims in prose

Write the ID inline, in the sentence that uses it: `By C-021, the second method
is the faster one.` A load-bearing sentence with no ID is an assertion.

## Generated files

`CLAIMS.md` and the per-claim files are views built from the ledgers. The
ledgers are the only truth about status. Edit neither by hand; change status
with `claims.py` and let the views be rebuilt. After any merge, `run.py
rebuild` (or `claims.py rebuild`) regenerates them from every stream — a
generated page merged by hand is a page that no longer says what the record
says.
