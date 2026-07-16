# Future Scientific Task-Pack Research Charter

> **Status: Future research.** This document preserves a candidate scientific-validation line and
> its research-integrity requirements. It is not the active product roadmap and does not describe
> current runtime capabilities. MechanistGym's active project is durable execution for
> long-horizon Agent workflows; scientific discovery, skill transfer, and adaptive organization
> require separate problem validation before they become implementation commitments.

## Candidate motivation

Scientific agents may execute increasingly complex analysis workflows, yet successful task completion
would not by itself guarantee valid scientific reasoning. Procedural memory could improve
repeated-task performance while also introducing negative transfer, stale assumptions, and recursive
self-revision errors.

Mechanistic biological systems could provide a useful future testbed because they support executable
interventions, deterministic and numerical checks, and controlled distribution shifts.

## Candidate future research question

Can scientific agents transfer experimental-design and model-auditing procedures across biological dynamical systems without negative transfer or recursive drift?

## Unvalidated future hypotheses

1. Procedural memory will improve in-distribution performance but may increase errors under topology, noise, or observation shifts.
2. External verifier-gated updates will reduce recursive drift relative to self-feedback-only updates.
3. Applicability conditions and abstention will reduce harmful procedure reuse.
4. Role-specialized multi-agent systems will provide conditional rather than universal benefit under matched budgets.
5. Structure-aware curricula will improve held-out transfer relative to random task ordering.

## Potential future contribution

A future scientific Task pack could contribute a reproducible environment and evaluation protocol
for:

- versioned procedural artifacts with explicit applicability and failure conditions;
- executable scientific verification;
- held-out transfer under mechanistic distribution shifts;
- negative-transfer and abstention measurement;
- cost-matched single- and multi-agent comparison.

## Controls required before any future scientific claim

- frozen train, development, and held-out task families;
- isolated Agent and Verifier information boundaries;
- fixed model, tool, token, time, retry, and compute budgets;
- multiple independent runs for stochastic systems;
- paired task-level comparisons and uncertainty intervals;
- negative and null result retention.

## Historical M0 fixture

M0 validated the original Model, Environment, Agent, and Verifier contracts with a first-order decay
analytic fixture. It did not test the hypotheses above or claim methodological novelty. The fixture
now remains a regression test and a possible seed for a future scientific Task pack; it does not
define the active product direction.

## Exclusions for any future scientific track

- private clinical data;
- wet-lab automation;
- foundation-model training;
- unrestricted autonomous execution;
- GPU or distributed infrastructure without profiling evidence;
- claims based only on LLM judging.

## Future scientific-track related work

A future scientific validation track would be informed by:

- [SciGym](https://arxiv.org/abs/2507.02083), an SBML dry lab for evaluating scientific
  experimentation;
- [SkillsBench](https://arxiv.org/abs/2602.12670), which measures both benefit and harm from Agent
  skills;
- [SkillLearnBench](https://arxiv.org/abs/2604.20087), which studies continual skill generation and
  feedback;
- [Process-Reward Tactic Evolution](https://arxiv.org/abs/2606.20839), a related study of
  verifier-backed learning for Galaxy workflows.

These references motivate a possible scientific Task-pack track; they do not establish its novelty,
make it an active roadmap commitment, or validate the durable-execution runtime.

## Research integrity

Reported results must identify task splits, model and tool versions, random seeds, budgets,
evaluation code, uncertainty, and known limitations. AI-assisted contributions remain subject to
author review, testing, and scientific accountability.
