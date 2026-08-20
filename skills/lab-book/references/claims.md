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
| `refuted` | Shown false under the claim's own stated conditions. Terminal. |
| `superseded` | Replaced by a sharper claim. Terminal. |

## The moves between them

| From | Legal targets |
|---|---|
| `proposed` | `conditional`, `verified`, `externally-established`, `refuted`, `superseded` |
| `conditional` | `verified`, `proposed`, `refuted`, `superseded` |
| `externally-established` | `conditional`, `proposed`, `refuted`, `superseded` |
| `verified` | `proposed`, `refuted`, `superseded` |
| `refuted` | none — terminal |
| `superseded` | none — terminal |

A move back to `proposed` is a **demotion**: use it when the evidence stops
holding up but nothing has actually refuted the statement. `verified →
proposed` is the common case — a replay that no longer runs, or a dependency
that turned out to be shakier than it looked. Demoting is cheap and honest.
Leaving a claim at `verified` while you privately doubt it is neither.

`conditional → verified` is legal only once the thing it rested on is itself a
`verified` claim in this repository, cited by ID.

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
  `externally-established`.
- **`refuted` and `superseded` are terminal.** Reviving an idea means a *new*
  claim, with a new ID, citing the old one. The old one stays where it is.
  Otherwise nobody can tell later which version of a claim an argument used.
- **Resting on the literature alone means `conditional`, not `verified`**,
  however solid the source is. `externally-established` is for a result you are
  citing whole and not building on; the moment your own claim depends on it,
  your claim is conditional.

## Citing claims in prose

Write the ID inline, in the sentence that uses it: `By C-021, the second method
is the faster one.` A load-bearing sentence with no ID is an assertion.

## Generated files

`CLAIMS.md` and the per-claim files are views built from the ledger. The ledger
is the only truth about status. Edit neither by hand; change status with
`claims.py` and let the views be rebuilt.
