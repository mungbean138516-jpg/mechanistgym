# Research Roadmap

MechanistGym is organized as a sequence of gated research milestones. Each gate requires aligned implementation, tests, evaluation evidence, and review documentation.

## M0 — Platform contracts and analytic fixture

**Objective:** establish explicit Model, Environment, Agent, Verifier, and Episode interfaces before introducing LLM or multi-agent complexity.

**Artifacts:**

- first-order decay analytic fixture;
- closed-form parameter-estimation baseline;
- independent positive and negative verifier fixtures;
- typed episode trace;
- CI, issue and pull-request templates, ADRs, and an M0 V&V record.

**Exit gate:** local tests pass; remote CI and independent reproduction complete.

## M1 — ODE task environments and noisy observations

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

## M2 — SBML integration and scientific verifiers

**Objective:** add standardized mechanistic models and domain-grounded validation.

**Artifacts:**

- SBML environment adapter;
- schema, topology, trajectory, equilibrium, and robustness validators;
- curated valid and invalid fixtures;
- benchmark and data cards.

**Exit gate:** graders distinguish curated valid and invalid artifacts at the preregistered threshold.

## M3 — Procedural memory and skill lifecycle

**Objective:** compare static, self-generated, self-revised, and externally verified procedures.

**Conditions:**

- no memory;
- human-curated procedure;
- one-shot generated procedure;
- iterative self-feedback;
- verifier-gated revision.

**Exit gate:** pilot study quantifies both improvement and negative transfer on frozen development tasks.

## M4 — Role-specialized multi-agent systems

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

## M5 — Held-out transfer and robustness

**Objective:** evaluate selective procedure reuse under systems-biology distribution shifts.

**Shifts:**

- dynamical topology;
- observation noise and sparsity;
- initial conditions and parameter scales;
- solver settings;
- irrelevant or conflicting procedural context.

**Exit gate:** primary outcomes, confidence intervals, failure taxonomy, and frozen manifests are reproducible.

## M6 — Artifact review and release

**Artifacts:**

- technical report;
- reproducibility package;
- tagged release;
- archived benchmark version;
- independent reproduction record;
- poster and short technical demonstration.

**Exit gate:** an external reviewer can reproduce the primary table and figure without private context.
