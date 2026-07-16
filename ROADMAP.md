# Project Roadmap

MechanistGym is organized as gated runtime and validation milestones. The R-series is the current
product-engineering track; the M-series is a separate scientific validation track. Each gate requires
aligned implementation, tests, evidence, and review documentation.

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

R0 is a cross-cutting infrastructure experiment. It does not replace the scientific roadmap or
authorize a repository rename before the planned direction and user validation.

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

**Implementation status:** complete on the R1 development branch. Local acceptance covers the exit
gate; the milestone remains pre-release until review and the remote Python matrix pass.

The **R-series** validates reusable runtime infrastructure. The **M-series** remains the scientific
validation and research track.

## Scientific validation track

### M0 — Platform contracts and analytic fixture

**Objective:** establish explicit Model, Environment, Agent, Verifier, and Episode interfaces before
introducing LLM or multi-agent complexity.

**Artifacts:**

- first-order decay analytic fixture;
- closed-form parameter-estimation baseline;
- independent positive and negative verifier fixtures;
- typed episode trace;
- CI, issue and pull-request templates, ADRs, and an M0 V&V record.

**Exit gate:** local tests pass; remote CI and independent reproduction complete.

### M1 — ODE task environments and noisy observations

**Objective:** move from exact interface validation to nontrivial estimation.

**Systems:**

- first-order decay with observation noise;
- logistic growth;
- two-species feedback;
- a reduced tumor–immune system.

**Methods:**

- closed-form baseline where available;
- regression-based estimation;
- numerical-solver adapter;
- explicit solver and observation-failure handling.

**Exit gate:** reference trajectories reproduce within declared tolerances, and noisy-task baselines include uncertainty.

### M2 — SBML integration and scientific verifiers

**Objective:** add standardized mechanistic models and domain-grounded validation.

**Artifacts:**

- SBML environment adapter;
- schema, topology, trajectory, equilibrium, and robustness validators;
- curated valid and invalid fixtures;
- benchmark and data cards.

**Exit gate:** graders distinguish curated valid and invalid artifacts at the preregistered threshold.

### M3 — Procedural memory and skill lifecycle

**Objective:** compare static, self-generated, self-revised, and externally verified procedures.

**Conditions:**

- no memory;
- human-curated procedure;
- one-shot generated procedure;
- iterative self-feedback;
- verifier-gated revision.

**Exit gate:** pilot study quantifies both improvement and negative transfer on frozen development tasks.

### M4 — Role-specialized multi-agent systems

**Objective:** measure when role specialization and communication justify their overhead.

**Candidate roles:**

- experiment planner;
- mechanistic modeler;
- scientific critic;
- reproducibility verifier.

**Required controls:**

- same underlying model family;
- matched tool access;
- matched token, time, retry, and compute budgets;
- role-removal and communication-topology ablations.

**Exit gate:** results identify where multi-agent coordination helps, hurts, or is cost-inefficient.

### M5 — Held-out transfer and robustness

**Objective:** evaluate selective procedure reuse under systems-biology distribution shifts.

**Shifts:**

- dynamical topology;
- observation noise and sparsity;
- initial conditions and parameter scales;
- solver settings;
- irrelevant or conflicting procedural context.

**Exit gate:** primary outcomes, confidence intervals, failure taxonomy, and frozen manifests are reproducible.

### M6 — Artifact review and release

**Artifacts:**

- technical report;
- reproducibility package;
- tagged release;
- archived benchmark version;
- independent reproduction record;
- poster and short technical demonstration.

**Exit gate:** an external reviewer can reproduce the primary table and figure without private context.
