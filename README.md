# MechanistGym

**Never restart a long-running Agent workflow from scratch when committed work can be recovered.**

[![CI](https://github.com/mungbean138516-jpg/mechanistgym/actions/workflows/ci.yml/badge.svg)](https://github.com/mungbean138516-jpg/mechanistgym/actions/workflows/ci.yml)

MechanistGym is an experimental runtime for durable, long-horizon Agent execution. Each successful
Task step becomes a committed Artifact; after an interruption or explicitly recoverable worker
failure, execution can resume from the first uncommitted step instead of restarting the whole Task.

> **Status:** pre-alpha. The current runtime supports local **Task → Artifact → Recovery** and
> bounded asynchronous execution across independent Tasks within a submitted batch. R2 adds one
> optional OpenAI-compatible provider adapter and a matched recovery benchmark. SQLite remains the
> reference backend; distributed workers and learned routing are not implemented.

## What works today

- ✅ artifact-level recovery from the first uncommitted Task step;
- ✅ a persistent `RuntimeStore` contract with a local SQLite reference backend;
- ✅ asynchronous `AgentAdapter` interfaces with ordered execution inside each Task;
- ✅ deterministic failure injection, fallback handoff, integrity checks, and event traces;
- ✅ recovery after closing the store or abruptly terminating the local execution process;
- ✅ per-batch bounded concurrency across independent Tasks in one event loop;
- ✅ per-Task Agent-failure isolation and stable input-order results;
- ✅ preservation of committed checkpoints during batch cancellation;
- ✅ a non-streaming OpenAI-compatible adapter implementing the documented Qwen Model Studio
  contract, with deterministic contract tests and a separate opt-in live gate;
- ✅ sanitized per-call token, latency, outcome, model, and prompt-hash telemetry;
- ✅ a four-condition engineering block separating checkpoint overhead, recovery, and restart;
- ✅ automated tests and CI on Python 3.11, 3.12, and 3.13.

Not implemented yet:

- 🚧 streaming, tool calling, automatic provider retries, or a global rate-limit scheduler;
- 🚧 parallel DAG steps, distributed workers, persistent provider telemetry, and production retry
  or rate-limit policy.

## Run it

MechanistGym has no runtime dependencies beyond Python 3.11 or newer.

~~~bash
git clone https://github.com/mungbean138516-jpg/mechanistgym.git
cd mechanistgym
python -m pip install -e ".[dev]"
make runtime-demo
make runtime-async-demo
~~~

The recovery demo deliberately fails the primary adapter at step 1. The important output is:

~~~text
status: succeeded
primary_calls:  [0, 1]
fallback_calls: [1, 2]
~~~

Step 0 was already committed, so the fallback does not repeat it. Run the complete verification
suite with `make test` or all compilation, test, lint, and formatting gates with `make check`.

The async demo runs three independent Tasks with `max_concurrency=2`. One Task recovers through a
fallback while its siblings continue:

~~~text
observed_max_active: 2
result_order: [batch-a, batch-b, batch-c]
statuses: all succeeded
recovered: batch-b only
fallback_calls: [(batch-b, 1)]
~~~

## Evaluate a real Qwen-compatible provider

The first hosted-provider boundary uses the official OpenAI-compatible Chat Completions shape. The
adapter is generic, while the included live configuration targets Alibaba Cloud Model Studio. It
uses non-streaming text responses, makes exactly one SDK request per `execute_step`, and disables
the SDK's hidden retries so request, token, and latency accounting stay visible.

Install the optional SDK and configure the API host shown for the same region as your key:

~~~bash
python -m pip install -e ".[provider-openai]"
export DASHSCOPE_API_KEY="..."
export DASHSCOPE_BASE_URL="https://dashscope-us.aliyuncs.com/compatible-mode/v1"
export DASHSCOPE_MODEL="qwen3.6-flash-2026-04-16"
export DASHSCOPE_REGION="us-virginia"
~~~

Do not paste the key into a config file or command-line argument. The adapter reads only the named
environment variable. Model Studio API keys and hosts are region-specific; copy the current API host
from the provider console rather than guessing it. `DASHSCOPE_MODEL` is deliberately required so an
experiment never drifts to a silent default. `DASHSCOPE_REGION` must be one of `beijing`,
`hong-kong`, `singapore`, `tokyo`, `frankfurt`, or `us-virginia`; it is public metadata included in
the report and must match the endpoint host. The included live CLI explicitly disables Qwen thinking
mode and records that setting in its configuration manifest, rather than relying on the model's
default. The dated example is listed as a US (Virginia) Model ID in Alibaba's
[official pricing table](https://www.alibabacloud.com/help/en/model-studio/model-pricing) as of
2026-07-16; account access still requires a live smoke check. Verify current regional availability in
Alibaba's
[current model list](https://www.alibabacloud.com/help/en/model-studio/models). See also the
[OpenAI-compatible API reference](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)
and [API-key guide](https://www.alibabacloud.com/help/en/model-studio/get-api-key).

The live benchmark is deliberately opt-in because it sends billable requests. With the default
three-step Task and failure at step 1, it sends 15 requests across four conditions:

~~~bash
PYTHONPATH=src python -m mechanistgym.evaluation \
  --confirm-live-calls \
  --failure-step 1
~~~

To add an estimated cost, supply an explicitly dated price snapshot; the project does not hardcode
mutable provider prices:

~~~bash
PYTHONPATH=src python -m mechanistgym.evaluation \
  --confirm-live-calls \
  --price-snapshot "model-pricing-YYYY-MM-DD" \
  --price-token-tier "up-to-32k" \
  --input-price INPUT_USD_PER_MILLION \
  --output-price OUTPUT_USD_PER_MILLION
~~~

R2 compares:

- **sequential/no checkpoint:** three normal provider calls, establishing direct-loop behavior;
- **checkpoint/no failure:** three calls through `DurableRunner`, exposing local checkpoint overhead;
- **checkpoint resume:** four calls, because the injected failure loses step 1 after the provider
  responds but before its Artifact commits; the store closes and reopens, then repeats step 1 while
  preserving step 0;
- **restart from scratch:** five calls, because it repeats both the uncommitted step 1 and the already
  completed step 0 in a fresh store before finishing.

The counts above are protocol invariants for the default Task, not empirical performance results.
Tokens, simple estimated cost, and latency come from the actual run. The JSON report includes a
sanitized configuration manifest and call records; endpoint text is hashed, region is a constrained
public enum, and every call carries the same non-secret request-configuration hash. The injected fault is
controlled and uses a graceful SQLite close/reopen in one Python process. It does not establish real
outage frequency, abrupt-process provider recovery, production durability, exactly-once model
execution, or answer-quality equivalence. Raw prompts, responses, authorization headers, and API
keys are excluded from telemetry. Any empirical comparison needs repeated, order-counterbalanced
runs with deterministic task-specific verifiers and incrementally persistent telemetry; one CLI
report is an engineering smoke test, not a performance claim. R2 keeps telemetry in memory, so an
interrupted benchmark block can lose its call evidence and must not be used as a repeated empirical
study.

## How recovery works

Long-horizon agent tasks can fail after earlier steps have already produced valid outputs. The
current runtime tests two bounded claims:

> Another adapter can resume a Task at the first uncommitted step without recomputing completed
> Artifacts.

> Independent Tasks can overlap up to a per-batch concurrency limit without sharing recovery state
> or allowing one terminal Agent failure to cancel its siblings.

The public execution model is deliberately small:

- **Task:** the goal and ordered resumable steps;
- **Artifact:** a committed, content-checked output from a completed step;
- **Recovery:** resumption at the first uncommitted step after interruption or recoverable failure.

A revisioned **Checkpoint** is runtime-managed recovery metadata exposed for inspection rather than
a primary user-authored concept. It connects Recovery to the exact committed Artifacts. A persistent
`RuntimeStore` atomically commits each Artifact with its successor Checkpoint; R0 ships SQLite as the
reference backend.

~~~mermaid
sequenceDiagram
    participant R as DurableRunner
    participant A as Primary Agent
    participant S as Persistent Store
    participant B as Fallback Agent
    R->>A: Execute step 0
    A-->>R: Artifact 0
    R->>S: Atomically commit Artifact 0 + recovery cursor
    R->>A: Execute step 1
    A--xR: Recoverable failure
    R->>B: Recover at first uncommitted step
    B-->>R: Artifact 1
    R->>S: Atomically commit Artifact 1 + recovery cursor
~~~

Inside each Task, steps remain ordered and sequential. Across Tasks, `DurableRunner.run_many` uses a
positive `max_concurrency` limit within that call and returns results in input order. A terminal Agent
failure becomes that Task's failed result. After an infrastructure or integrity error becomes known,
already-active siblings settle, queued Tasks do not start, and every observed batch exception remains
visible if the batch is allowed to settle—multiple child exceptions are raised as a Python exception
group. Explicit caller cancellation propagates immediately and may supersede pending child errors.

**Scope boundary.** The runtime provides application-level recovery at committed step boundaries in
one local Python event loop. It does not recover an in-flight step or hidden model context, snapshot
process memory, guarantee exactly-once external side effects, schedule parallel DAG steps, provide
distributed workers or leases, or implement learned routing or autonomous team formation. The
concurrency bound is not global across simultaneous `run_many` calls and is not a provider rate
limit. Shared adapter instances must be safe for re-entrant async use. Concurrent execution of the
same Task ID across separate calls is unsupported until the runtime has claims or leases.

## Roadmap

- **R0 — Durable execution:** committed Artifact recovery and deterministic failover;
- **R1 — Bounded async execution:** concurrent independent Tasks with Agent-failure isolation and
  preservation of committed work during cancellation;
- **R2 — Provider evaluation:** one Qwen-compatible adapter, visible call telemetry, and a matched
  sequential/checkpoint/resume/restart engineering block;
- **Next runtime milestones:** persistent traces, provider retry/rate-limit policy, recovery
  ergonomics, and repeated evaluation with task-specific verifiers.

See the gated [roadmap](ROADMAP.md) and [architecture decisions](docs/decisions/) for exact scope and
non-goals. The README describes working code; longer-term hypotheses live in the documentation.

## Future research directions

The current project is reliable execution for long-horizon Agent systems. It is not a scientific
discovery platform. **Scientific discovery, skill transfer, and adaptive organization are future
research hypotheses, not product commitments.** They require separate problem validation and may
later use the runtime to study learned failure prediction, budget-aware routing, heterogeneous teams,
procedural memory, and verifier-gated scientific Task packs.

The repository's original systems-biology fixture remains a regression test and possible future
Task pack; run it with `make demo`. Its hypotheses and controls are archived in the
[research charter](docs/research_charter.md), separate from the current product claim.

## Repository structure

- **src/mechanistgym/** — runtime contracts, provider adapters, evaluation utilities, and package APIs
- **src/mechanistgym/runtime/** — experimental Task and Artifact types, recovery behavior, and
  persistent-store contracts with a SQLite reference backend
- **src/mechanistgym/providers/** — optional provider adapters and privacy-conscious call telemetry
- **src/mechanistgym/evaluation/** — matched baseline protocols and report types
- **tests/** — unit, negative-fixture, and end-to-end acceptance tests
- **docs/decisions/** — architecture decision records
- **docs/reviews/** — milestone verification and validation records
- **.github/** — CI, issue forms, and pull-request review controls

## License and citation

MechanistGym code is released under the MIT License. The adapter calls an external metered Model
Studio service and does not bundle or redistribute Qwen weights. If you self-host a Qwen checkpoint,
verify that model repository's license separately; do not infer a hosted model's terms from this
repository's license. Citation metadata is available in [CITATION.cff](CITATION.cff).
