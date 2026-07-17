# ADR-0001: Establish a single-agent baseline before multi-agent orchestration

- **Status:** Historical; superseded for active project direction by ADR-0003 through ADR-0005
- **Date:** 2026-07-14
- **Decision type:** Architecture Decision Record (ADR)

## Context

This decision records the original scientific research scaffold. At the time, adding several roles
before validating the Environment and Verifier would have made failures difficult to attribute. A
successful output could have come from hidden information leakage, and a failure could have come
from the biological Model, Agent, communication protocol, or grader.

The active project is now durable execution for long-horizon Agent workflows. Multi-agent
scientific discovery, skill transfer, and adaptive organization remain possible future research,
not the destination assumed by the current roadmap.

## Decision

M0 implements one deterministic agent with four explicit boundaries:

1. model;
2. environment;
3. agent;
4. verifier.

The original plan deferred multi-agent orchestration until these interfaces and the Episode trace
passed acceptance tests. M0 satisfied that local scaffold, but it did not activate a multi-agent
scientific roadmap.

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

There is no active M2 trigger. Reviving multi-agent scientific orchestration, skill transfer, or
adaptive organization requires a new ADR and separate evidence that the proposed research problem
is real, measurable, and not already addressed by the durable-runtime roadmap.
