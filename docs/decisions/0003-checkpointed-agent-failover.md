# ADR-0003: Checkpoint agent-semantic artifacts before adding adaptive organization

- **Status:** Accepted
- **Date:** 2026-07-16
- **Decision type:** Architecture Decision Record (ADR)

## Context

The long-term direction is reliable execution for heterogeneous, long-horizon agent systems. A
static manager hierarchy does not solve the immediate failure mode: a worker can time out after
producing useful intermediate work, forcing the task to restart.

The first implementation must demonstrate durability without becoming a general workflow engine or
claiming to snapshot an LLM process. It must also leave the validated scientific fixture intact while
the broader direction is tested.

## Decision

Add a parallel, experimental `mechanistgym.runtime` namespace. Its first vertical slice persists:

1. an immutable `Task` with ordered resumable steps;
2. one application-level immutable `Artifact` with a checksummed content field per completed step;
3. a `Checkpoint` containing the next step and committed Artifact identifiers.

Use standard-library SQLite to atomically commit an Artifact and its successor Checkpoint. Expose an
async `AgentAdapter.execute_step` boundary, while keeping v0.1 execution sequential. When an adapter
raises `RecoverableAgentError`, reroute the same uncommitted step to the next adapter. A reopened
runner loads the last committed Checkpoint and never requests earlier steps again.

## Concrete example

The primary adapter completes step 0, then receives an injected failure on step 1. The store retains
Artifact 0 and Checkpoint revision 1. A fallback adapter receives the same task at step 1 and then
completes steps 1 and 2. The observable call trace is:

```text
primary:  [0, 1]
fallback: [1, 2]
```

Step 0 is not repeated.

## Invariants

- an Artifact is frozen through the Python API and its stored SHA-256 checksum must match its content;
- a Checkpoint references exactly the committed Artifact sequence for its task;
- Artifact and Checkpoint advancement occur in one SQLite transaction;
- stale Checkpoint revisions cannot commit;
- reusing a task identifier with a changed definition fails explicitly;
- completed tasks are idempotent when reopened;
- only explicitly recoverable adapter failures are rerouted.

## Consequences

### Positive

- recovery is measurable with deterministic fault injection;
- state survives store and runner object recreation;
- heterogeneous model APIs can later enter through adapters;
- the scientific decay workflow remains a compatible first task pack;
- execution traces support later failure analysis and routing models.

### Negative

- tasks must currently be decomposed into ordered steps before execution;
- there is one Artifact per step and no DAG scheduling;
- SQLite is local and the runner does not provide distributed leases;
- recovery is at-least-once at the step boundary, not exactly-once for external side effects;
- uncommitted hidden context inside a failed model call is not recoverable.

## Explicit non-claims

R0 is not an operating system, a Ray/Temporal/Airflow replacement, a process snapshotter, a learned
router, or an autonomous AI organization. It demonstrates checkpointed, artifact-level handoff in a
controlled local runtime.

## Review trigger

Revisit the one-artifact-per-step and sequential-execution constraints only after R0 passes external
reproduction and a real adapter demonstrates the same recovery contract.
