# ADR-0001: Establish a single-agent baseline before multi-agent orchestration

- **Status:** Accepted
- **Date:** 2026-07-14
- **Decision type:** Architecture Decision Record (ADR)

## Context

MechanistGym is ultimately a multi-agent research program. However, adding several roles before validating the environment and verifier would make failures difficult to attribute. A successful output could come from hidden information leakage, and a failure could come from the biological model, agent, communication protocol, or grader.

## Decision

M0 implements one deterministic agent with four explicit boundaries:

1. model;
2. environment;
3. agent;
4. verifier.

Multi-agent orchestration begins only after these interfaces and the episode trace pass acceptance tests.

## Concrete example

AnalyticDecayAgent observes protein concentrations, estimates a hidden degradation rate, and predicts a later concentration. AbsoluteToleranceVerifier grades the artifact independently.

## Consequences

### Positive

- failures have a small attribution surface;
- the single-agent system becomes the required baseline;
- later multi-agent claims can be cost-matched against a working control;
- terminology maps directly to code and tests.

### Negative

- v0.1 does not yet demonstrate agent communication or role specialization;
- the initial agent is deliberately simpler than an LLM-based scientific agent.

## Review trigger

Revisit this decision after the ODE environment and scientific validators pass M2.
