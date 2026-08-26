# Design queue

Two requests from the Investigator (2026-08-25), kept here so they survived the monitoring work. Each names the failure it prevents, per the README principle. **Both were built on 2026-08-26 (kit 1.2.0).** The original notes stay below as the record of the decisions; the "Built" paragraph at the top of each says what landed and where it is documented.

## 1. Session transcripts in git

**Built 2026-08-26.** `run.py ingest` (and `ingest --record-broken`) discovers the worker's native transcript by a per-role rule in `lab.json` (`roles.<name>.transcript = {"glob": ..., "match": "path" | "first-line-cwd"}`, with `{cwd}`, `{cwd_dashed}`, `{cwd_urlencoded}` placeholders — no vendor patterns in code), gzips it to `runs/R-…/session.jsonl.gz`, commits it with the ingest, and records source, sha256 and sizes in `ingest.json`; above `transcripts.max_mb` (default 20) only the sha and sizes are kept. `--transcript <path>` overrides discovery for in-process workers. `director_session` is stamped in `dispatch.json` and `ingest.json`. Documented in `references/runs.md`, "Transcripts". Not done: moving Director memory into the repo — superseded by the `## This Investigator` block in `AGENTS.md` and role notes in `lab.json`.

### Original note (2026-08-25)

**Failure prevented.** `worker.log` is only the worker's stdout. The reasoning and tool calls behind a claim live in each CLI's private session store on one machine and are pruned or lost; a second investigator cannot audit how a result was produced. The Director's own session is the same: nothing in the repo says which session dispatched or ingested a run.

**What exists today** (audited 2026-08-25 against `reference/run.py` and the combo lab):
- `run.py` writes `worker.log` (stdout+stderr) and nothing else about the session. `dispatch.json` / `ingest.json` carry no session id or transcript path.
- Native transcripts, all recoverable per run:
  - Codex: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, first line has `cwd`.
  - Grok: `~/.grok/sessions/<url-encoded cwd>/`.
  - opencode: `~/.local/share/opencode/opencode.db` (SQLite), by project directory.
  - Claude Code: `~/.claude/projects/<escaped cwd>/<session>.jsonl` for the Director; Agent-tool subagents are separate files under `<session>/subagents/`.
- `CLAUDE_CODE_SESSION_ID` is in the environment when the Director runs `run.py`, so the Director's session id is free to record.

**Proposed minimal design.**
- `run.py new` stamps `director_session` (from `CLAUDE_CODE_SESSION_ID`, else `unknown`) into `dispatch.json`; `ingest` stamps it again.
- `run.py ingest` locates the worker's native transcript by cwd match (Codex, Grok, opencode) and copies it to `runs/R-NNN/session.jsonl`, recording source path + sha256 in `ingest.json`. Agent-tool subagents: `--worker-done --transcript <path>` — the Director knows which subagent file it used.
- Size policy: transcripts over N MB (say 5) are gitignored by pattern and kept on the originating machine, exactly as the combo lab already does for large CSVs; the sha in `ingest.json` still pins them. Decide: this, or git LFS.

**Recommendation (2026-08-25).** Commit worker transcripts, gzipped, at ingest — measured: codex transcripts for this lab are 0.3–2.4 MB raw, 3–4× smaller gzipped, so ~0.2–0.8 MB per run; no LFS. Cap at 20 MB compressed; above that keep local and commit only the sha + size. Copy on `--record-broken` too — that is where the evidence matters most (F-008/F-009). Director session: record the id only; the notebook is the Director's record by design. Move dispatch-governing Director memory (role quirks, quota state) from `~/.claude/projects/<lab>/memory/` into the repo — a second investigator's Director must inherit it.

## 2. Several investigators on one experiment — the federated-notebook model

**Built 2026-08-26, with one change from the note below.** Every investigator works on their own branch `lab/<tag>` from day one, even alone (`run.py join`); `main` is written only by `run.py reconcile`, the investigators' meeting: everyone on a call, one at the keyboard, the Director reads the agenda (duplicate statements, a claim moved differently in two streams, a verified claim resting on one another stream refuted, open runs older than the last meeting, duplicated runs, pages rewritten two ways), the room decides, decisions land as ledger events under actor `meeting <date> (tags)`, the minutes go in `notebook/meetings/`, and every branch is fast-forwarded to `main`. Namespaced IDs `R-<tag>-NNN` / `C-<tag>-NNN`, one ledger per person, legacy untagged IDs still valid; `catchup` reads the others' branches without merging. "Everyone on main between meetings" was considered on 2026-08-26 and rejected by the Investigator: daily pushes to a shared branch are where git bites people new to it; per-person branches became viable once namespacing removed the ID collision that had ruled them out. Documented in `references/runs.md` ("Joining a lab", "Seeing the others", "The meeting"), `references/claims.md` ("One ledger each"), `AGENTS.md` ("Investigators' meeting"), README ("Working as a group").

### Original note (2026-08-25)

**Chosen 2026-08-25 (Investigator).** Replaces the earlier serial push/pull plan, kept at the end as the rejected alternative.

**The analogy.** Collaborating physical labs do not share a notebook. Each keeps its own, append-only, in its own voice. What they share is the results — a claims table and a manuscript — and they reconcile at meetings: compare findings, surface discrepancies, decide who re-runs what, write minutes. An experiment belongs to the group that ran it; others cite it, never edit it.

**Failures prevented.**
- Two investigators mint the same `R-NNN`/`C-NNN` and someone renumbers evidence by hand (IDs are max+1 scans of the local tree, `run.py:228`, `claims.py:127`).
- Two labs quietly hold two truths about a claim until the paper is written.
- "Whose run is this, and is it still alive?" unanswerable from the record.
- A second investigator's Director starting without the operational facts that live in the first one's machine-local memory.

**Design.**
1. *Notebooks are per investigator.* Everything an investigator writes carries their tag: `runs/R-<inv>-NNN`, notes `N-<date>-<inv>-NN`, and an append-only `claims/ledger-<inv>.jsonl`. Files with one writer never merge-conflict; the ID race and any pull-first rule disappear. A run directory is owned by its investigator and immutable to others, exactly as notebook entries already are. Transcripts (§1) follow the run. `dispatch.json`/`ingest.json` carry `investigator` (git `user.name`), `host`, and the Director session id, so an open run says whose machine it lives on.
2. *Claims are the shared object.* `CLAIMS.md` is generated from all ledgers; a claim's current status is the latest event across them. Any investigator's Director may referee another's claim. Independence gains a second axis: "checked by a different model" becomes "checked by a different model and a different lab" — the software form of inter-lab reproducibility. `claims.py` records both.
3. *STATUS.md is the meeting minutes.* It is the only genuinely contended file, so it is rewritten only at reconciliation. Between meetings, investigators write notes in their own stream.
4. *Reconciliation is a script plus a meeting.* `claims.py reconcile` prepares the agenda: duplicate statements across ledgers, conflicting status events on one claim, a claim one lab verified that rests on something the other lab moved, open runs older than the last meeting. People decide; decisions land as ledger events under an actor like `meeting 2026-08-30`, and the meeting note is filed in the notebook. `catchup` reads all streams.
5. *Generated files are derived, never merged.* `CLAIMS.md`, `INDEX.md` are regenerated after every pull; the lint refuses a commit where they disagree with the ledgers.
6. *Director memory.* Per-investigator habits stay local; anything that governs dispatch (role availability, quirks, quota state) lives in `lab.json` so every Director inherits it.

Serial turns are the special case of one active investigator and need no extra rules.

**Decisions (Investigator, 2026-08-25).**
1. The investigator tag is the git `user.name` (normalized to a short slug for file names).
2. A claim proposed and verified within the same lab counts as `verified`; the cross-lab axis is recorded as independence, not required for status.
3. Only the owner may close (ingest or void) a run. Another lab may *duplicate* it: dispatch the same brief in its own namespace, with `dispatch.json` carrying `duplicates: R-<inv>-NNN` so `reconcile` lists the pair and the stale original stays visible until its owner closes it.

**Rejected alternative — one notebook, serial turns.** `run.py new` fetches and refuses if behind `origin/main` or with unpushed ingests; ingest pushes, and a push failure blocks the next `new` rather than the ingest. Workable, but it is "take turns writing in one notebook": it needs enforcement to stay consistent, blocks the second investigator entirely, and gives disagreement no place to be recorded. Per-investigator branches were also rejected — they move the ID collision to merge time.
