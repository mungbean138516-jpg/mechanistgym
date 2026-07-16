# ADR-0004: Bound asynchronous execution across independent Tasks

- **Status:** Accepted
- **Date:** 2026-07-16
- **Decision type:** Architecture Decision Record (ADR)

## Context

R0 executes one durable Task at a time. Real Agent applications need multiple independent Tasks to
make progress without admitting an unconstrained number of active Task workflows inside one batch.
The runtime must add useful concurrency without weakening the per-Task checkpoint and recovery
invariants already established by R0.

This milestone is not a DAG scheduler or a distributed worker system. It needs one precise unit of
concurrency and explicit failure and cancellation semantics that can be tested deterministically.

## Decision

Add an immutable `ExecutionSpec` containing one Task and an immutable snapshot of its ordered Agent
failover chain. Validate the Task, adapters, names, chain uniqueness, and batch Task IDs before
persisted execution. Add `DurableRunner.run_many`, which executes distinct `ExecutionSpec` values in
one Python event loop.

Use a batch-local `asyncio.Semaphore` around each complete Task workflow. A positive
`max_concurrency` therefore bounds active Tasks within one `run_many` call, not individual steps,
raw coroutines, simultaneous batches, or provider calls. Steps within each Task remain sequential and
continue to use the R0 Artifact and Checkpoint contract.

The batch contract is:

1. validate the whole batch before creating any persisted Task state;
2. reject duplicate Task identifiers within one call;
3. preserve input order in the returned results;
4. convert terminal Agent exhaustion into that Task's `FAILED` result so siblings continue;
5. after an infrastructure or integrity exception becomes known, allow already-active siblings to
   settle but prevent queued Tasks from entering persisted execution;
6. when the batch is allowed to settle, preserve every child exceptional outcome: re-raise one error
   unchanged or group multiple errors in a Python `BaseExceptionGroup`;
7. propagate caller cancellation to active executions, leaving only atomically committed work for a
   later Recovery; immediate caller cancellation may supersede pending child errors.

## Concrete example

Given Tasks A, B, and C with `max_concurrency=2`, A and B enter the runtime while C waits. B's primary
Agent commits step 0 and fails on step 1; B's fallback resumes at step 1. A continues independently.
When either active Task releases its slot, C starts. Results are returned in A, B, C input order even
if completion order differs.

## Invariants

- active Task workflows within one `run_many` call never exceed `max_concurrency`;
- one Task's Artifacts, Checkpoint, status, and events never satisfy another Task's recovery state;
- a Task executes only one ordered step at a time;
- a failed Task cannot cancel a healthy sibling merely because they share a batch;
- queued Tasks do not create store state before acquiring a slot and entering `run`;
- queued Tasks do not enter `run` after an infrastructure or integrity error is observed;
- multiple active failures are not collapsed into a single reported exception;
- cancellation does not convert an interrupted Task into a false success or terminal Agent failure.

## Consequences

### Positive

- independent Tasks can overlap while preserving R0 durability semantics;
- the explicit per-batch bound prevents unbounded active Task workflows within one call;
- callers receive stable result ordering and isolated terminal Agent failures;
- deterministic tests can control overlap with events instead of timing-sensitive sleeps.

### Negative

- a long Task holds one slot for its entire workflow, so short Tasks behind it can wait;
- fairness and priority scheduling are unspecified;
- adapter instances shared across Tasks must be safe for re-entrant async use;
- synchronous persistent-store operations still run on the event-loop thread;
- infrastructure failure is reported only after already-started siblings settle;
- separate simultaneous `run_many` calls have separate bounds and can exceed either bound in
  aggregate.

## Scope boundary

R1 does not add parallel steps within a Task, dependency graphs, threads, process pools, provider
rate limits, distributed leases, priorities, budgets, or learned scheduling. The semaphore is a
per-call execution bound, not a global limit or general scheduler. Concurrent execution of the same
Task ID across separate calls is unsupported until claims or leases exist.

## Review trigger

Revisit whole-Task slot ownership only after real provider traces show head-of-line blocking or a
need for provider-specific limits. Do not introduce a scheduler abstraction before that evidence
exists.
