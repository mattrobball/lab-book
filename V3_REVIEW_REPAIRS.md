# V3 review repairs — 2026-09-22

## Status

**Linux repair candidate verified; macOS replay remains blocked at shell startup.** The new macOS workflow remains failing, not skipped or relabeled as passing. This is not a fully verified cross-platform release or deployment approval.

The Investigator authorized these changes in order: publication and replay credential isolation; acknowledgment/database invariants; upgrade/versioning and durable CI coverage. Authorization was recorded on this branch before modifying the kit. No paid calls, real-credential tests, production changes, PR merges, rebases, or force pushes were performed.

The repair branch is `repair/v3-review-fixes-20260922`, based on #5 at `3cf07169efab5c851627ee6597f0b4fe3da643a5`. It contains the prior foundation/pilot lineage and the unchanged hosting implementation/tests from `4c644f35b6984cc46f8f278823449f97041dd92c`, for combined verification. Original heads remain unchanged:

- #2: `0a0ac1b3404f731edce6c25ec6280eb36e9c9482`.
- #3: `cbb21ef63505c50971edb9ed72cd04b68009c496`.
- #4: `844a8fd7f264ac96d6cdcd585f272d584e3b3a4d`.
- #5: `3cf07169efab5c851627ee6597f0b4fe3da643a5`.

## Repairs and regression evidence

### 1. Publication does not make CI a second writer of research

`v3/ci.py` computes against pinned source refs in a disposable worktree and publishes only advisory metadata/checkpoints on `lab-book/publication`. It does not commit onto an investigator branch, main, or master. The claim tools read comparison/check events from a fetched publication ref without merging executable code or status ledgers. Normal fast-forward publication preserves competing writers; a losing publisher must retry from a fresh checkout. The workflow still serializes issue publication repository-wide.

Twelve CI tests cover both investigator-first and CI-first orderings, including two real investigator dispatch/ingest cycles with intervening CI publication. The second ingest reaches origin without manual history repair. Competing publication and fetched symmetric-flag controls also pass. Existing historical divergence is not automatically rebased or rewritten.

### 2. Replay no longer inherits Director credentials

Replay uses a constructed environment and a bounded, link-free private copy of its run. Linux Bubblewrap confines filesystem, process and network access and drops capabilities; only selected read-only system/interpreter runtimes and private replay inputs are exposed. Credential files in the host home/checkout, host process environments and host network endpoints are not replay inputs. Symlinks, hard links and special entries are rejected before copying. Replay outputs stay in the disposable copy. A missing or blocked backend cannot fall back to unrestricted execution; a non-replayed worker PASS is recorded UNDECIDED under the existing gate rules.

Native Linux tests exercise dummy environment credentials, credential files outside the packet, host process access, networking, input-link rejection, timeouts, and an actual recomputed ingest. This confines replay, not every interactive coding-agent launcher. Selected runtime directories are trusted and must not contain credentials. See `skills/open-lab/assets/v3/REPLAY.md`.

**Outstanding: macOS.** Its deny-default Seatbelt path exits the shell with signal 6 before the native positive replay and timeout controls complete. Seven replay tests run: five pass and two fail; the separate upgraded canary also fails because it is recorded UNDECIDED, not replayed PASS. The diagnostic workflow retains the failure and sandbox logs. No unrestricted fallback or unverified policy relaxation was applied. Successful macOS replay is not claimed.

### 3. Acknowledgment is bound to the promoted text

`claims.py set ... verified` now refuses a simultaneous statement/condition revision, or a visible version that differs from this branch. It cannot save new text under an old contradiction acknowledgment. The real CLI regression changes both statement and conditions separately, checks refusal before any ledger write, and verifies that unchanged text remains promotable with its exact current acknowledgment. A revision should enter as a new proposed claim, or the committed wording should be restored.

### 4. Direct SQL obeys notice invariants

Table constraints enforce the authenticated run namespace, payload/run/actor agreement, typed nonempty prerequisite fields, integer budget bounds and the exact budget-derived deadline. These checks apply to direct INSERT as well as the four existing RPC functions. Row-level ownership rules and nonexclusive notices remain unchanged. No preemption, heartbeat or renewal is introduced.

Native PostgreSQL tests execute the previously untested direct-SQL counterexamples and positive controls. The explicit `migrate-alpha1-alpha2.sql` migration is tested against the actual alpha.1 schema. It refuses transactionally while rows remain and does not rewrite or discard promises. Owners must close/reap their notices before the database owner applies it. File upgrade does not silently migrate a database.

### 5. The actual first-pass updater installs alpha.2

Skill/plugin metadata agree on `3.0.0-alpha.2`. The replay helper lives in `v3/`, which the original updater already copies; adding only a new top-level helper would not have worked with its fixed installation list. The separate upgrade fixture installs the exact alpha.1 kit from commit `0a0ac1b3404f731edce6c25ec6280eb36e9c9482`, invokes that old command, checks installed CI/Jev/identity/replay/migration bytes and disabled live configuration, and completes a real sum(range(4)) replayed canary on Linux.

### 6. Native checks have durable triggers

The kit, browser pilot, actual-SDK contract and macOS replay workflows now run on ordinary pushes and pull requests, not temporary branch names alone. They use read-only repository permissions and no paid credentials. Release tests assert coordinated versions, durable triggers and old-updater-compatible packaging. The macOS failure remains visible on those triggers.

## Exact completed verification

Runtime/test candidate: `b419155e784946cfe2ce70a0f32d6c616093273e`.
Tree: `3b3e738848d69d9b7c42b4543600f05b85e5ceeb`.
The next commit, `b79969eba7a8ec8512fb6b1f46fbca384c4f3e09`, changes only the macOS workflow's failure diagnostics. This report and installation notes are subsequent documentation-only changes.

| Check | Completed result | Run | Artifact |
|---|---|---|---|
| Full native Linux kit, including real PostgreSQL | 260 tests passed; no failures/errors/skips; 146.174s | 35779349479 | 10717227027 |
| Actual alpha.1 updater and confined Linux canary | 1 test passed; 0.642s | 35779349479 | 10717227027 |
| Two-investigator native browser/service pilot | 1 complete scenario passed; 20.588s | 35779349457 | 10717261703 |
| Actual pinned SDK contract, sockets forbidden | 3 tests passed; 0.010s | 35779348966 | 10717276384 |
| Native macOS replay and upgraded canary | FAIL: 2 of 7 replay tests; separate canary failed | 35779642826 | 10717508248 |

The separate fixture counts are not additions to an alleged all-platform passing suite. The pilot uses real PostgreSQL TLS, PostgREST, nginx and Chromium, synthetic browser identities, and mocked Jev judgments. It is not a live GitHub OAuth deployment.

Artifacts were downloaded through the GitHub connector. ZIP checksums, source SHA, embedded source-archive checksums, complete per-command output and exit status were inspected. All passing jobs above identify the same runtime/test commit. ZIP SHA-256:

- Linux kit/upgrade: `0edcce3f96f574366571da04cb88049a5b4d9e1832d4e5a1fdb2d8940364741d`.
- Native pilot: `4db66572449c1f90020fb454aa6fd44777ea414c844919f42737307d9ade0da1`.
- SDK contract: `25d924ab6dafbcb9c9a0d8d7ad6f706bd5c0b5dc20a4417ea48670cadc8eb7a0`.
- macOS diagnostics: `c5a82e562520fa83ab4eed081552a20d75718e1aa1d3cb854d0b9a81b73226bf`.

Run links:
- https://github.com/mattrobball/lab-book/actions/runs/35779349479
- https://github.com/mattrobball/lab-book/actions/runs/35779349457
- https://github.com/mattrobball/lab-book/actions/runs/35779348966
- https://github.com/mattrobball/lab-book/actions/runs/35779642826

Evidence retention is 30 days. Earlier 244- and 257-test passing milestones are superseded by the 260-test candidate, not counted again. Initial patch-transport and namespace-provisioning failures were not counted as passes. Linux CI now provisions a scoped Bubblewrap AppArmor permission in disposable runners; runtime replay never changes host security settings. The initial macOS failure and subsequent diagnostic failure remain retained.

Temporary exact-object publication helpers were removed from the final tree; GitHub connector calls published branch refs incrementally. Original review branches were not changed. Before adoption, resolve native macOS startup for macOS users and complete site-specific authentication/TLS/port and production runtime validation. No live Jev accuracy, throughput, cost, production OAuth callback, or host deployment is claimed.
