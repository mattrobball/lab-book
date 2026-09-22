# V3 review repairs — 2026-09-22

The Investigator authorized the review fixes in this order: publication and replay credential isolation; acknowledgment and database invariants; upgrade/versioning and durable CI coverage. This note records authorization before changes to kit scripts or shared defaults.

Rechecked source heads:
- Foundation (#2): `0a0ac1b3404f731edce6c25ec6280eb36e9c9482`.
- Pilot/CI (#3): `cbb21ef63505c50971edb9ed72cd04b68009c496`.
- Hosting/identity (#4): `844a8fd7f264ac96d6cdcd585f272d584e3b3a4d`.
- Jev (#5): `3cf07169efab5c851627ee6597f0b4fe3da643a5`.

The dedicated repair branch starts at #5, which includes the reviewed pilot code. The unchanged hosting additions may be included here for combined regression verification, with their source identified. Original branches and PRs remain untouched; no PR merge, force push, production deployment, paid calls, or real-credential testing is authorized or performed.

Acceptance requires regression controls for both publication orderings, replay environment AND credential-file isolation, exact acknowledged claim versions, direct SQL invariants, an actual first-pass upgrade, durable workflow triggers, and a real small dispatch/replayed-ingest canary. Missing or interrupted output is not passing evidence. Results and remaining limitations will be recorded after verification.
