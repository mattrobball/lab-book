# Opt-in Jev adapter verification — 2026-09-22

The Investigator authorized an opt-in Jev adapter as an independent continuation after the integration/CI foundation. This branch is based on `f6c022ca84126712c11ef185769e284972b9a836` and does not merge hosting/identity. **No paid request was made.**

## Implemented

The optional TypeSafe SDK 0.7.1 adapter requires explicit private local enablement, a separate process opt-in, an API key, an explicit model, and bounded calls/time. Existing credentials alone do not enable calls. Mock and live configuration are mutually exclusive. The model, exact question-template hash, and SDK version distinguish cache identity; old mock judgments cannot suppress live comparisons.

Four raw probabilities remain policy inputs, never status changes. The adapter records requested/returned model, template identity, request ID, usage and elapsed time. It validates wire values rather than allowing numeric strings or booleans to become probabilities through coercion. Attempts, including retries, share a process-wide per-lab/configuration cap across problem checks. Concurrency, request time, batch time and input bytes are bounded. Cancellation drains in-flight tasks and closes the client. Remaining or failed pairs remain deferred; valid experiment packets are not rejected for model unavailability.

The production client uses the fixed official HTTPS endpoint, ignores environment proxy/base-URL overrides, disables redirects and nested SDK retries, and suppresses SDK body-level debug logging. This is opt-in code, not enabled deployment.

## Completed verification

Tested implementation/contract commit: `e18dbfbc2ebd2c36fe694e80b388e01a2388d0f5`.
Tested tree: `ee7ce37c6caa5d3271e76b7f966ce8b99351763a`.
This report is a subsequent documentation-only change.

**234 native kit tests passed, zero failures/errors/skips**, in 180.205 seconds: the 224-test integration baseline plus ten adapter tests. The adapter tests include a real claim-ledger transaction with controlled provider responses, asserting that a mock cache is replaced by separately identified adapter evidence, provenance survives the commit, and claim statuses remain unchanged.

**Three additional actual-SDK contract tests passed**, in 0.007 seconds, with `typesafe-sdk==0.7.1` and `httpx2==2.13.0`. The tests exercise the SDK's real serialization and response parser through MockTransport, with socket connections forbidden. They verify exact request format, all four raw scores, provider request-ID provenance, boolean-wire rejection, and the default adapter's actual client construction, fixed endpoint/proxy isolation, and client closure. No genuine API credential or paid response was used.

### Retained evidence

| Job | Run | Artifact | ZIP SHA-256 |
|---|---|---|---|
| Full kit | 35771472628 | 10714371791 | `67143eb521038c667c5c045e8d3063fc3f3ec377fc3334b33362ddf956ed0349` |
| Actual SDK contract | 35771472664 | 10713998404 | `862e5cdd32b9e0722327a9de24417a2fbdb492e895ebe3d1839e41fa4412f68c` |

- https://github.com/mattrobball/lab-book/actions/runs/35771472628
- https://github.com/mattrobball/lab-book/actions/runs/35771472664

Both artifacts were downloaded through the GitHub connector. ZIP checksums, retained source-archive checksums, source SHA, zero exits, complete test output, and the reviewed code bytes were checked. The kit artifact retains 14 days and the SDK contract 30 days.

### Earlier failed SDK contract retained

Run `35770834905` at `c6807cf76bdbc423ea185b0436661b119ac5bb4c` installed the actual SDK but failed its positive contract test. The fixture supplied `x-request-id`, while this SDK reads `x-typesafe-request-id` and raises when request identity is absent. The corrected fixture supplies and asserts the real header. A separate default-client construction/closure test was added. The earlier failed artifact `10713439878` is retained; it was not counted as passing evidence.

## Remaining boundaries

These tests validate transport contracts, limits and policy behavior, not Jev's mathematical accuracy, latency, throughput, or cost. No live API evaluation was performed. The configured limits bound calls, time and input size, **not dollar expenditure**. Paid use still requires separate approval and an account-supported versioned model; placeholder fixture model names are not production recommendations.

No live settings or keys were installed in CI, no production deployment was made, and no merge, rebase, or force push was performed. Installation and explicit enablement are documented in `skills/open-lab/assets/v3/JEV.md`.
