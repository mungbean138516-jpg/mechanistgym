# ADR-0005: Make provider attempts visible and compare recovery against matched baselines

- **Status:** Accepted
- **Date:** 2026-07-16
- **Decision type:** Architecture Decision Record (ADR)

## Context

R0 proves local Artifact-level recovery and R1 bounds concurrent independent Tasks, but both use
deterministic adapters. Neither milestone shows what a hosted model request costs, how long it takes,
or how much work restart from scratch repeats. Adding several providers or a learned router now would
increase surface area without answering that validation question.

Provider SDKs can also retry requests invisibly. Hidden retries would make request counts, latency,
failure handoff, and token accounting misleading. Credentials, prompts, and raw responses create a
separate privacy boundary and must not enter default runtime traces.

## Decision

R2 adds one optional `OpenAICompatibleAdapter` for non-streaming Chat Completions. The included live
configuration targets Qwen through Alibaba Cloud Model Studio, but the boundary is not coupled to a
Qwen-specific response class. The official OpenAI Python SDK is optional and lazily loaded.

The adapter:

1. reads an API key only from the configured environment-variable name;
2. requires an explicit base URL and model;
3. requires explicit Qwen thinking mode, sets an explicit timeout, and uses `max_retries=0`;
4. sends one text-only request for one ordered Task step;
5. supplies committed Artifact content as the durable prefix context;
6. accepts only non-empty text with the terminal `stop` finish reason;
7. returns a canonical Artifact only after a valid response;
8. records sanitized call metadata in an event-loop-local sink.

Telemetry includes condition/run ID, Task and step, adapter, provider, requested and returned model,
outcome, local latency, prompt-template version and SHA-256 hash, a hash binding every non-secret
request setting, token usage when returned, finish reason, hashed request ID, HTTP status when known,
and sanitized error type. It excludes raw prompts, responses, endpoint text, headers, environment
values, and API keys. Unknown usage remains `None`; it is never reported as zero.

Status 408, 409, 5xx, timeouts, and transport failures are recoverable. Generic HTTP 429 remains
recoverable. For Qwen, documented `Throttling` rate/burst/allocation codes are recoverable, while
documented purchase/billing codes and ambiguous 429 codes fail closed as permanent. A valid HTTP
response with an invalid output contract is a recoverable protocol failure. Cancellation is
recorded and re-raised. R2 does not add automatic retries; the existing explicit fallback chain owns
recovery.

## Matched evaluation

Run four conditions with the same Task, provider, pinned model snapshot, prompt template,
temperature, seed, thinking mode, output limit, endpoint-bound region, and—during the live CLI
block—shared SDK client:

1. **Sequential/no checkpoint:** direct ordered calls without checkpoint persistence.
2. **Checkpoint/no failure:** clean `DurableRunner` execution to expose checkpoint overhead.
3. **Checkpoint resume:** a controlled failure after the selected provider response but before its
   Artifact commits, followed by closing and reopening the same SQLite store.
4. **Restart from scratch:** the same controlled failure, followed by executing every step in a fresh
   store.

Both failure conditions repeat the uncommitted failure step. Checkpoint resume preserves all earlier
committed steps; restart recomputes them. For three steps and failure at step 1, expected provider
calls are 3, 3, 4, and 5 respectively. The benchmark derives preservation and recomputation from
call records plus pre-failure and final Artifact checksums. A completed condition is rejected unless
its exact call pattern and each call's configuration hash match the manifest. It exports sanitized
call-level evidence, a hashed configuration/Task manifest, tokens, provider and wall time, structural
verification, and optional simple estimated cost with a dated model, public region enum, and token
tier. Experiment IDs are restricted before they can enter SQLite paths.

## Consequences

### Positive

- the first real provider uses the same AgentAdapter boundary as deterministic workers;
- SDK retries cannot hide provider attempts from the experiment;
- restart overhead and uncommitted-step replay are reported separately;
- mutable prices are not embedded in source code;
- fake-client and real-SDK mock-transport CI cover the boundary without credentials or billable
  calls;
- users must explicitly acknowledge live calls.

### Negative

- provider telemetry is not committed incrementally and can be lost if evaluation aborts before the
  final JSON report;
- the generic compatibility claim covers only the tested Chat Completions subset;
- one provider response can be billed even when its Artifact never commits;
- model stochasticity prevents exact text equivalence from serving as a quality metric;
- no retry/backoff means transient failures can end a chain sooner than a production policy would.

## Scope boundary

R2 does not implement streaming, tool calls, structured-output negotiation, context compression,
automatic retries, rate-limit queues, incremental provider telemetry, price lookup, multi-provider
normalization, distributed workers, or learned routing. The provider fault and graceful store reopen
occur in one Python process; R0 separately tests abrupt process loss with a deterministic adapter.
This experiment cannot establish real
outage frequency, exactly-once execution, exact billed cost, semantic quality equivalence, or a
general advantage of multi-agent systems. A one-block CLI smoke run is not a performance study;
empirical comparison requires repeated and order-counterbalanced blocks.

Scientific discovery, skill transfer, and adaptive organization are explicitly outside this
milestone and remain Future Research.

## Review trigger

Revisit persistence and retry policy after opt-in live traces exist. Add a second provider only when
one concrete cross-provider use case requires it; do not add adapters merely to lengthen a support
matrix.
