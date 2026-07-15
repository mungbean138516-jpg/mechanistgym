# Research Charter

## Motivation

Scientific agents can execute increasingly complex analysis workflows, yet successful task completion does not guarantee valid scientific reasoning. Procedural memory may improve repeated-task performance while also introducing negative transfer, stale assumptions, and recursive self-revision errors.

Mechanistic biological systems provide a useful testbed because they support executable interventions, deterministic and numerical checks, and controlled distribution shifts.

## Research question

Can scientific agents transfer experimental-design and model-auditing procedures across biological dynamical systems without negative transfer or recursive drift?

## Working hypotheses

1. Procedural memory will improve in-distribution performance but may increase errors under topology, noise, or observation shifts.
2. External verifier-gated updates will reduce recursive drift relative to self-feedback-only updates.
3. Applicability conditions and abstention will reduce harmful procedure reuse.
4. Role-specialized multi-agent systems will provide conditional rather than universal benefit under matched budgets.
5. Structure-aware curricula will improve held-out transfer relative to random task ordering.

## Planned contribution

The intended contribution is a reproducible environment and evaluation protocol for:

- versioned procedural artifacts with explicit applicability and failure conditions;
- executable scientific verification;
- held-out transfer under mechanistic distribution shifts;
- negative-transfer and abstention measurement;
- cost-matched single- and multi-agent comparison.

## Experimental controls

- frozen train, development, and held-out task families;
- isolated Agent and Verifier information boundaries;
- fixed model, tool, token, time, retry, and compute budgets;
- multiple independent runs for stochastic systems;
- paired task-level comparisons and uncertainty intervals;
- negative and null result retention.

## M0 scope

M0 validates platform contracts with a first-order decay analytic fixture. It does not test the working hypotheses or claim methodological novelty.

## Exclusions

- private clinical data;
- wet-lab automation;
- foundation-model training;
- unrestricted autonomous execution;
- GPU or distributed infrastructure without profiling evidence;
- claims based only on LLM judging.
