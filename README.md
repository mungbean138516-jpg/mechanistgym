# MechanistGym

**Preserve completed agent work when a worker fails.**

[![CI](https://github.com/mungbean138516-jpg/mechanistgym/actions/workflows/ci.yml/badge.svg)](https://github.com/mungbean138516-jpg/mechanistgym/actions/workflows/ci.yml)

MechanistGym is an experimental runtime for durable, long-horizon Agent execution. Each successful
Task step becomes a committed Artifact; after an interruption or explicitly recoverable worker
failure, execution can resume from the first uncommitted step instead of restarting the whole Task.

> **Status:** pre-alpha. The current runtime supports local **Task → Artifact → Recovery** and
> bounded asynchronous execution across independent Tasks within a submitted batch. It uses
> deterministic adapters and a SQLite reference backend; it does not yet include real model-provider
> adapters, distributed workers, or learned routing.

## What works today

- ✅ artifact-level recovery from the first uncommitted Task step;
- ✅ a persistent `RuntimeStore` contract with a local SQLite reference backend;
- ✅ asynchronous `AgentAdapter` interfaces with ordered execution inside each Task;
- ✅ deterministic failure injection, fallback handoff, integrity checks, and event traces;
- ✅ recovery after closing the store or abruptly terminating the local execution process;
- ✅ per-batch bounded concurrency across independent Tasks in one event loop;
- ✅ per-Task Agent-failure isolation and stable input-order results;
- ✅ preservation of committed checkpoints during batch cancellation;
- ✅ automated tests and CI on Python 3.11, 3.12, and 3.13.

Not implemented yet:

- 🚧 production adapters for hosted or local model providers;
- 🚧 parallel DAG steps, distributed workers, budgets, learned routing, and adaptive organization.

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
- **Later milestones:** provider adapters, budget-aware routing, failure prediction, adaptive teams,
  and scientific Task packs—added only after their prerequisites and evaluation data exist.

See the gated [roadmap](ROADMAP.md) and [architecture decisions](docs/decisions/) for exact scope and
non-goals. The README describes working code; longer-term hypotheses live in the documentation.

## Scientific validation track

The repository began with a systems-biology analytic fixture. It remains a concrete test domain for
Agent–Environment boundaries, independent verification, and structured traces; it is not presented
as the current runtime product or as a completed scientific contribution.

Run that fixture with `make demo`. Its detailed hypotheses, matched-budget controls, planned task
families, and related work are maintained in the [research charter](docs/research_charter.md) and
[research-engineering lifecycle](docs/lifecycle.md).

## Repository structure

- **src/mechanistgym/** — platform contracts and reference implementations
- **src/mechanistgym/runtime/** — experimental Task and Artifact types, recovery behavior, and
  persistent-store contracts with a SQLite reference backend
- **tests/** — unit, negative-fixture, and end-to-end acceptance tests
- **docs/decisions/** — architecture decision records
- **docs/reviews/** — milestone verification and validation records
- **.github/** — CI, issue forms, and pull-request review controls

## License and citation

Code is released under the MIT License. Citation metadata is available in [CITATION.cff](CITATION.cff).
