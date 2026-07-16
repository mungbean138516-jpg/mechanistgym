# MechanistGym

**Verifier-gated skill transfer for scientific agents in systems biology**

[![CI](https://github.com/mungbean138516-jpg/mechanistgym/actions/workflows/ci.yml/badge.svg)](https://github.com/mungbean138516-jpg/mechanistgym/actions/workflows/ci.yml)

MechanistGym is a research platform and benchmark framework for studying how scientific agents acquire, validate, transfer, and reject procedural knowledge across mechanistic biological systems.

> **Status:** pre-alpha. The repository currently provides the validated M0 platform contracts and an analytic end-to-end fixture. It does not yet report skill-transfer or multi-agent results.

> **Experimental runtime track:** the repository now also contains a bounded vertical slice for
> checkpointed failover between agent adapters. This track is being validated before any project
> rename or broader platform claim.

## Research objective

The central question is:

> Can scientific agents transfer experimental-design and model-auditing procedures across biological dynamical systems without negative transfer or recursive drift?

The planned study will compare single-agent and role-specialized multi-agent systems under matched model, tool, token, time, retry, and compute budgets. Multi-agent benefit is treated as an empirical hypothesis rather than an architectural assumption.

## M0 platform contracts

The initial milestone establishes four independently testable components:

- **Model:** a formal dynamical system;
- **Environment:** a task interface that controls observations and hidden state;
- **Agent:** a policy that maps observations to a task artifact;
- **Verifier:** an evaluator isolated from the Agent's information boundary.

One complete attempt is recorded as an **Episode**, including observations, fitted parameters, prediction, reference value, error, and verification outcome.

## Analytic fixture

M0 uses first-order biological decay:

\[
\frac{dx}{dt}=-kx,
\qquad
x(t)=x_0e^{-kt}.
\]

The Environment hides the rate constant, exposes concentration observations, and requests a later-time prediction. A closed-form baseline estimates the hidden rate and submits a prediction to an independent absolute-tolerance Verifier.

This system is an **analytic fixture for validating interface contracts and information isolation**. It is not the final benchmark or a scientific contribution claim.

~~~mermaid
flowchart LR
    A["Dynamical model"] --> B["Task environment"]
    B --> C["Agent baseline"]
    C --> D["Prediction artifact"]
    D --> E["Independent verifier"]
    E --> F["Structured episode trace"]
~~~

## Checkpointed failover vertical slice

Long-horizon agent work is brittle when an interrupted worker forces valid intermediate work to be
recomputed. The experimental `mechanistgym.runtime` namespace tests one narrower claim:

> A fallback agent can continue from the last committed, artifact-level checkpoint without
> repeating completed task steps.

The current slice persists only three domain objects:

- **Task:** an immutable goal and ordered set of resumable steps;
- **Artifact:** one application-level immutable result with SHA-256 content checking;
- **Checkpoint:** the next step and exact Artifact references needed for handoff.

SQLite atomically commits each Artifact with the Checkpoint that references it. The runner exposes
an asynchronous `AgentAdapter` boundary but deliberately executes one step at a time. A deterministic
failure fixture makes recovery reproducible instead of waiting for a real API outage.

~~~mermaid
sequenceDiagram
    participant R as DurableRunner
    participant A as Primary Agent
    participant S as SQLite Store
    participant B as Fallback Agent
    R->>A: Execute step 0
    A-->>R: Artifact 0
    R->>S: Commit Artifact 0 + Checkpoint 1
    R->>A: Execute step 1
    A--xR: Injected recoverable failure
    R->>B: Execute step 1 from Checkpoint 1
    B-->>R: Artifact 1
    R->>S: Commit Artifact 1 + Checkpoint 2
    R->>B: Execute step 2
~~~

This is **agent-semantic durability**, not a process snapshot. It does not preserve hidden model
reasoning, promise exactly-once side effects, replace Ray/Temporal/Airflow, or yet provide learned
routing and autonomous organization.

## Quick start

MechanistGym M0 has no runtime dependencies beyond Python 3.11 or newer.

~~~bash
make demo
make runtime-demo
make test
~~~

The demo should recover k=0.25 and produce a verified prediction at t=6. The test suite includes positive and negative verifier fixtures.

The runtime demo injects a failure at step 1. Its expected call trace is `primary=[0, 1]` and
`fallback=[1, 2]`: step 0 remains committed and is not repeated.

## Design principles

- external verification before skill promotion;
- explicit Agent–Environment information boundaries;
- frozen task splits and evaluators before full experiments;
- matched budgets for single- and multi-agent comparisons;
- structured traces for failure analysis and reproducibility;
- public or synthetic data only;
- null and negative results retained;
- profiling before parallel, distributed, or GPU optimization.

## Planned evaluation

Future milestones will introduce multiple ODE/SBML families, observation noise, sparse sampling, initial-condition shifts, topology shifts, skill applicability conditions, abstention, and role-specialized orchestration.

Primary outcomes will include:

- held-out task success;
- robust success under perturbation;
- negative-transfer rate;
- skill-reuse precision;
- failure-repair rate;
- abstention calibration;
- cost, latency, and tool calls;
- reproducibility pass rate.

See [research charter](docs/research_charter.md), [roadmap](ROADMAP.md), and [research-engineering lifecycle](docs/lifecycle.md).

## Repository structure

- **src/mechanistgym/** — platform contracts and reference implementations
- **src/mechanistgym/runtime/** — experimental Task, Artifact, Checkpoint, SQLite, and failover contracts
- **tests/** — unit, negative-fixture, and end-to-end acceptance tests
- **docs/decisions/** — architecture decision records
- **docs/reviews/** — milestone verification and validation records
- **.github/** — CI, issue forms, and pull-request review controls

## Related work

The research direction is informed by:

- [SciGym](https://arxiv.org/abs/2507.02083), an SBML dry lab for evaluating scientific experimentation;
- [SkillsBench](https://arxiv.org/abs/2602.12670), which measures both benefit and harm from agent skills;
- [SkillLearnBench](https://arxiv.org/abs/2604.20087), which studies continual skill generation and feedback;
- [Process-Reward Tactic Evolution](https://arxiv.org/abs/2606.20839), a closely related study of verifier-backed learning for Galaxy workflows.

MechanistGym is intended to focus on mechanistic systems, selective skill reuse, negative transfer, and cost-matched agent architecture comparisons.

## Research integrity

Reported results must identify task splits, model and tool versions, random seeds, budgets, evaluation code, uncertainty, and known limitations. AI-assisted contributions remain subject to author review, testing, and scientific accountability.

## License and citation

Code is released under the MIT License. Citation metadata is available in [CITATION.cff](CITATION.cff).
