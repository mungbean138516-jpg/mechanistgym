# MechanistGym

**Durable execution for long-horizon agent tasks**

[![CI](https://github.com/mungbean138516-jpg/mechanistgym/actions/workflows/ci.yml/badge.svg)](https://github.com/mungbean138516-jpg/mechanistgym/actions/workflows/ci.yml)

MechanistGym is an experimental agent-execution runtime that preserves committed work across worker
failures. A Task produces durable Artifacts; after an interruption or explicitly recoverable adapter
failure, execution can resume from the first uncommitted step instead of restarting the whole Task.

> **Status:** pre-alpha. R0 demonstrates local, sequential **Task → Artifact → Recovery** with
> deterministic adapters and a SQLite-backed persistent store. It does not yet include real
> model-provider adapters, distributed execution, or learned routing.

## What works today

- ✅ artifact-level recovery from the first uncommitted Task step;
- ✅ a persistent `RuntimeStore` contract with a local SQLite reference backend;
- ✅ asynchronous `AgentAdapter` interfaces with ordered execution inside each Task;
- ✅ deterministic failure injection, fallback handoff, integrity checks, and event traces;
- ✅ recovery after closing the store or abruptly terminating the local execution process;
- ✅ automated tests and CI on Python 3.11, 3.12, and 3.13.

Not implemented yet:

- 🚧 concurrent execution across independent Tasks (R1);
- 🚧 production adapters for hosted or local model providers;
- 🚧 distributed workers, budgets, learned routing, and adaptive organization.

## Run the recovery demo

MechanistGym has no runtime dependencies beyond Python 3.11 or newer.

~~~bash
git clone https://github.com/mungbean138516-jpg/mechanistgym.git
cd mechanistgym
python -m pip install -e ".[dev]"
make runtime-demo
~~~

The demo deliberately fails the primary adapter at step 1. The important output is:

~~~text
status: succeeded
primary_calls:  [0, 1]
fallback_calls: [1, 2]
~~~

Step 0 was already committed, so the fallback does not repeat it. Run the complete verification
suite with `make test` or all compilation, test, lint, and formatting gates with `make check`.

## How recovery works

Long-horizon agent tasks can fail after earlier steps have already produced valid outputs. R0 tests
one bounded claim:

> Another adapter can resume a Task at the first uncommitted step without recomputing completed
> Artifacts.

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

**Scope boundary.** R0 provides application-level recovery at committed step boundaries in a local,
sequential runner. It does not recover an in-flight step or hidden model context, snapshot process
memory, guarantee exactly-once external side effects, provide distributed scheduling or leases, or
implement learned routing or autonomous team formation.

## Roadmap

- **R0 — Durable execution:** committed Artifact recovery and deterministic failover;
- **R1 — Bounded async execution:** concurrent independent Tasks with failure isolation;
- **Later research:** provider adapters, budget-aware routing, failure prediction, adaptive teams,
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
