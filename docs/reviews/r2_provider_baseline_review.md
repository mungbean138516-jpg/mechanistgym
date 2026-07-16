# R2 Provider Adapter and Matched Baseline Acceptance Review

**Review type:** Verification and Validation (V&V) Review
**Review date:** 2026-07-16
**Decision:** Accepted for deterministic local R2 engineering verification. Remote CI remains
pending until this branch is published. Live Qwen validation is a separate opt-in empirical gate
because no user-owned API credential is available in CI.

## Scope reviewed

- optional OpenAI-compatible Chat Completions adapter;
- Qwen Model Studio environment configuration;
- one-request-per-step behavior with SDK retries disabled;
- sanitized call outcome, token, latency, model, finish-reason, request-hash, and prompt-hash data;
- recoverable, permanent, protocol, and cancellation classifications;
- matched sequential, clean-checkpoint, checkpoint-resume, and restart-from-scratch conditions;
- post-response/pre-commit failure injection;
- manifest-to-call configuration binding, exact controlled call counts, and safe experiment IDs;
- structured public-region pricing snapshots and unknown-usage handling.

## Deterministic acceptance requirements

| Requirement | Evidence | Result |
|---|---|---|
| Valid response becomes canonical Artifact | injected async client and response fixture | Pass |
| Request contract is pinned and non-streaming | captured fake request plus real-SDK mock transport | Pass |
| Usage and finish reason are preserved | fake provider metadata | Pass |
| Missing usage stays unknown | `None` token and cost assertions | Pass |
| Qwen rate-limit 429 is recoverable; billing/ambiguous 429 and 401 are permanent | fake errors plus real-SDK 429 bodies | Pass |
| SDK timeout and 500 are recoverable with one wire request | real `AsyncOpenAI` mock transport, retries disabled | Pass |
| Non-`stop`, empty, or missing-choice output is rejected | response protocol fixtures | Pass |
| Cancellation propagates | event-gated async fake | Pass |
| API-key value and raw request/response are absent | sanitized record and representation checks | Pass |
| Manifest and every call share one request-configuration hash | mismatch and missing-telemetry rejection | Pass |
| Unsafe experiment IDs cannot escape the database directory | path-traversal negative fixture | Pass |
| Three-step matched accounting is 3/3/4/5 calls | deterministic fake provider | Pass |
| Resume preserves step 0; restart recomputes it | measured call counts and prefix checksums | Pass |
| Estimated cost requires known usage and structured prices | pricing and missing-usage fixtures | Pass |
| Existing R0/R1 behavior remains compatible | 70-test complete local suite | Pass |
| Python 3.11–3.13 remote matrix | GitHub Actions | Pending |
| Live Qwen request contract | explicit user-owned smoke run | Pending, not a CI blocker |

## Validation boundary

Passing deterministic tests proves adapter and accounting semantics, not hosted-service reliability
or economic benefit. A live run is required before reporting measured Qwen tokens, cost, or latency.
Any empirical report must pin provider region, model snapshot, prompt version, seed, temperature,
thinking mode, timeout, output limit, failure step, and dated price source. It must include all submitted trials and
must not present estimated token cost as an invoice. R2 telemetry is in memory; repeated empirical
claims are blocked until call records are persisted incrementally across interrupted blocks.

The current structural verifier checks complete, non-empty Artifact chains. It is not a semantic or
scientific quality judge. R2 therefore makes no answer-quality, cross-provider, production-outage,
exactly-once, or Multi-Agent-versus-Single-Agent claim.

Scientific discovery, skill transfer, and adaptive organization are outside R2 and remain Future
Research rather than current product claims.
