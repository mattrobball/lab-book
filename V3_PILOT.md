# v3 pilot continuation

## Investigator authorization — 2026-09-22

The Investigator approved: integration fixture and CI hardening first; hosting/identity and an opt-in Jev adapter as separate parallel workstreams afterward. This authorizes the necessary kit and CI changes on dedicated branches, with incremental GitHub connector pushes. No merge, force push, production deployment, or paid model calls are authorized here.

Base rechecked: `0a0ac1b3404f731edce6c25ec6280eb36e9c9482` on `implementation/v3-minimal-20260922`. The design branch and first-pass branch remain untouched.

The integration fixture must exercise two independent investigator clones and real services, with only Jev responses mocked. Notices are nonexclusive announcements; there is no preemption. CI must preserve investigator records, serialize shared issue publication, retain per-command evidence, and expose interrupted/deferred work honestly.

Hosting/identity and the live adapter remain separately reviewable. Browser writes stay private and require validated identity mapping and CSRF protection. The live adapter must be explicitly enabled, bounded, distinguishable from mocks, and tested without paid calls.

## Evidence

Work and verification results will be recorded below as they complete. Missing, skipped, or interrupted jobs are not passing evidence.
