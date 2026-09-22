# Minimal v3 implementation

## Investigator authorization — 2026-09-22

The Investigator requested a first implementation of `DESIGN_V3.md` on the
`v3-live-collaboration` lineage and explicitly authorized GitHub connector pushes.
After the scope questions, the Investigator chose:

- A minimal end-to-end first pass.
- **No preemption.** Reservations only announce existing work. Concurrent work
  remains allowed; nobody's worker is stopped, replaced, or denied a result.
- No paid model calls in this pass: mock the Jev responses to exercise proper
  policy behavior. Mock results must never be presented as live model evidence.

This authorizes the necessary changes to the kit scripts and shared defaults.
The implementation preserves human-only claim status changes, append-only
records, existing ingest fences, and graceful operation without a reservation
host or model service. No production deployment is authorized or attempted.

Base inspected: `3325395c6dfc72d4e5d8dadac23f04a8fabf90de`.
Implementation branch: `implementation/v3-minimal-20260922`.
The design branch is left unchanged.

## Verification

Implementation and verification evidence will be added below. A completed small
canary dispatch/ingest and the existing regression suite are required before this
pass is described as verified. Missing or interrupted test output is not a pass.
