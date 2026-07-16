# Project Roadmap

MechanistGym is organized around gated reliable-execution milestones. The R-series is the active
product-engineering roadmap. Scientific discovery, skill transfer, and adaptive organization are
non-committed Future Research and require separate validation before entering this roadmap. Each gate
requires aligned implementation, tests, evidence, and review documentation.

## R0 — Durable agent execution vertical slice

**Objective:** preserve committed Agent work and resume a Task at its first uncommitted step after a
recoverable worker failure.

**Scope:**

- Task and committed Artifact contracts;
- revisioned Checkpoint as runtime-managed recovery metadata exposed for inspection;
- persistent RuntimeStore abstraction with a local SQLite backend and atomic Artifact–Checkpoint
  commits;
- asynchronous AgentAdapter boundary with sequential per-Task execution;
- deterministic failure injection, ordered failover, and close/reopen Recovery;
- abrupt OS-process termination followed by Recovery in a new process.

**Non-goals:** in-flight step or model-context recovery, process-memory snapshots, exactly-once
external side effects, distributed scheduling or leases, learned routing, or autonomous team
formation.

**Exit gate:** failover, reopen, cancellation, abrupt process-exit, idempotent completion,
stale-checkpoint, definition-mismatch, and corruption tests pass; the failure demo shows
`primary=[0, 1]`, `fallback=[1, 2]`.

R0 established durable Agent execution as the active project direction. The older decay fixture
remains a regression fixture and possible future scientific Task pack; it is not the product roadmap.

## R1 — Bounded asynchronous Task execution

**Objective:** execute independent durable Tasks concurrently without allowing one terminal Agent
failure to cancel or corrupt its siblings.

**Scope:**

- concurrency across distinct Tasks; ordered steps inside each Task remain sequential;
- a positive, per-`run_many` `max_concurrency` bound enforced in one Python event loop;
- input-order result stability and per-Task status, Artifact, Checkpoint, and event isolation;
- terminal Agent failure returned as that Task's failed result while sibling Tasks continue;
- batch cancellation that preserves only committed work for later Recovery;
- infrastructure or integrity failure stops queued Tasks, lets already-active siblings settle, and
  remains visible to the caller without discarding additional batch exceptions.

**Non-goals:** parallel DAG steps, threads or subprocess workers, distributed scheduling, fairness,
priorities, per-provider rate limiting, duplicate concurrent execution of one Task, or retrying
infrastructure and integrity failures. The bound is not global across separate `run_many` calls.

**Exit gate:** deterministic tests prove real overlap, enforce the concurrency bound, isolate one
Task's failure, preserve checkpointed failover under concurrency, and recover committed work after
batch cancellation. Invalid adapter chains fail before persistence, queued Tasks stop after an
infrastructure error, and multiple active exceptions remain visible.

**Implementation status:** complete on the R1 development branch. Local acceptance and the remote
Python 3.11–3.13 matrix cover the exit gate; the milestone remains pre-release while its stacked pull
request is in draft review.

## R2 — Visible provider execution and matched recovery baselines

**Objective:** connect the runtime to one real hosted-model interface and measure what checkpoint
recovery preserves relative to clean sequential execution and restart from scratch.

**Scope:**

- one optional, non-streaming OpenAI-compatible Chat Completions adapter, initially configured for
  Qwen through Alibaba Cloud Model Studio;
- API keys read only from a named environment variable and no raw prompt, response, header, or
  secret in telemetry;
- one visible SDK request per step with SDK retries disabled;
- sanitized request outcome, token usage, model, latency, finish reason, provider error code, and
  prompt hash;
- four matched conditions using the same Task, provider, model, prompt template, temperature, seed,
  thinking mode, output limit, endpoint-bound region, and shared live SDK client;
- explicit post-response/pre-commit failure injection and user-supplied dated pricing snapshots.

**Non-goals:** streaming, tool calls, automatic retry or backoff, provider rate-limit scheduling,
dynamic pricing lookup, persistent or distributed telemetry, cross-provider comparison, exact
billing reconciliation, semantic quality claims, or production-outage simulation.

**Exit gate:** deterministic fake-client and real-SDK mock-transport tests prove success, unknown
usage, timeout/cancellation, Qwen rate-limit versus billing classification, protocol rejection,
HTTPS credential transport, and secret-safe records. For a three-step Task failing at step 1, the
matched protocol accounts for 3 sequential, 3 clean-checkpoint, 4 resume, and 5 restart calls;
observed traces prove resume recomputes zero committed steps while restart recomputes one. A
real-provider run remains an explicit empirical gate and is never required in CI.

**Implementation status:** adapter, telemetry, benchmark harness, and deterministic acceptance tests
are implemented on the R2 development branch. The opt-in Qwen smoke run is pending user-owned API
credentials and will be reported separately from deterministic verification.

The **R-series is the project**: reusable infrastructure for reliable long-horizon Agent execution.

## Next runtime and product validation

- persist sanitized provider telemetry incrementally so interrupted experiment blocks remain
  auditable;
- define explicit provider retry, backoff, rate-limit, and budget policies without hiding attempts;
- improve recovery inspection and operator ergonomics;
- repeat matched live-provider blocks with rotated condition order and task-specific verifiers;
- reconcile estimates against user-owned invoices before making economic claims.

## Future research directions

The following ideas are deliberately subordinate to the working runtime and require separate
problem validation before implementation:

- learned failure prediction and adaptive routing after enough traces exist;
- procedural skill transfer and reusable Agent memory under held-out evaluation;
- heterogeneous team formation and dynamic organization;
- verifier-gated scientific Task packs, beginning with the existing systems-biology fixture;
- held-out transfer, robustness, and multi-agent ablations only when preregistered controls exist.

The detailed earlier hypotheses remain in [the research charter](docs/research_charter.md); they are
not claims about what the repository can do today.
