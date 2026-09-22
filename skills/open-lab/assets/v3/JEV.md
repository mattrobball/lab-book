# Opt-in Jev adapter — no paid calls by default

The Investigator authorized this adapter work on 2026-09-22. No paid calls are
part of implementation or verification. The default judge remains unavailable
unless explicitly mocked or explicitly enabled. No setup installs credentials.

Install the optional pinned dependency `typesafe-sdk==0.7.1` in the Director's
Python environment. The adapter uses its actual asynchronous System One client,
not an invented HTTP protocol or a lexical similarity substitute. The kit's
upgrade copies this adapter with the other `v3/` assets.

Enabling calls requires all three: a private local configuration, the process
opt-in `LAB_BOOK_ALLOW_PAID_JEV=1`, and `TYPESAFE_API_KEY` in the Director's
protected environment. Existing keys alone do nothing. Configure only in
`lab.local.json`, never in a worker's environment:

```json
{"rectification":{"live":{
  "enabled":true,
  "model":"REPLACE_WITH_AN_ACCOUNT_SUPPORTED_VERSIONED_MODEL",
  "max_calls":100,
  "budget_seconds":60,
  "concurrency":4,
  "request_timeout":10,
  "max_retries":1
}}}
```

The example model is a placeholder, not a real model recommendation. Select an
immutable provider model version; `latest` aliases are refused. Existing mock
configuration and live configuration are mutually exclusive. The adapter fixes
the official HTTPS endpoint and ignores environment proxy/base-URL overrides.
It must not be enabled in the lab CI template until paid use is separately
approved and its private configuration and secrets are deliberately provisioned.

Each HTTP attempt, including a retry, consumes the same call cap. Concurrency is
at most ten. A process-wide judge per lab/configuration shares the cap across
problem checks in the same CI invocation. A hard asynchronous batch deadline
cancels and drains in-flight requests. Remaining pairs stay deferred; budget,
provider, malformed-response, SDK, and network failures are not negative model
judgments and never reject a valid experiment. Pairs exceeding 16 KiB are deferred
without sending. This limits calls, elapsed time and input bytes, **not dollars**;
a paid pilot still needs an explicitly approved spending policy.

Four independent raw probabilities return unchanged. The original response is
validated before SDK coercion can turn booleans or numeric strings into numbers.
Policy thresholds remain in `rectification.py`. Records carry the requested and
returned model, exact template hash, SDK version, request ID, usage, and elapsed
time. Cache identity includes model, template and SDK, and never equals `mock`.
Existing mock events cannot suppress a live check. No model keys are recorded.
SDK body-level debug logging is suppressed by this adapter.

## Evidence boundary

The normal tests use controlled asynchronous provider responses. The dedicated
SDK workflow installs the real pinned SDK, exercises its real request/response
serialization through `httpx2.MockTransport`, and forbids socket connections.
It tests the wire contract and raw-probability validation without paid requests.
None of these tests measures Jev's mathematical accuracy, throughput or cost.
A separately authorized live evaluation remains necessary before relying on its
judgments. Failures must retain deferred coverage rather than a clean bill of
health.

Official references inspected 2026-09-22:
- https://docs.typesafe.ai/sdk/python/api/clients/sync
- https://docs.typesafe.ai/sdk/python/usage
- https://github.com/typesafe-ai/typesafe-sdk-python/blob/main/tests/test_clients.py
