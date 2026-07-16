# ADR-0002: Use first-order exponential decay as the canonical M0 model

- **Status:** Accepted as a historical regression fixture
- **Date:** 2026-07-14

## Context

The first scientific example needed to be biologically recognizable, analytically solvable, and
strict enough to expose the boundaries among Model, Environment, Agent, and Verifier. This ADR
records that historical fixture; it does not define the active durable-execution product direction.

## Decision

Use the first-order linear ODE:

\[
\frac{dx}{dt}=-kx,
\qquad
x(t)=x_0e^{-kt}.
\]

Do not use constant-slope decay dx/dt=-k as the canonical example.

## Concrete biological interpretation

x is a positive protein concentration and k is a non-negative degradation-rate constant. The analytic solution preserves non-negativity and resembles common first-order degradation processes.

## Consequences

- exact ground truth is available without a numerical solver;
- an Agent can estimate k from log concentration ratios;
- a later noisy-observation milestone can expose the fragility of using only two observations;
- the model remains an analytic fixture, not a claim about every biological degradation process.

The decay example remains useful for regression coverage and could seed a future scientific Task
pack. Scientific discovery and skill-transfer experiments based on it are Future Research rather
than current runtime capabilities or roadmap commitments.
