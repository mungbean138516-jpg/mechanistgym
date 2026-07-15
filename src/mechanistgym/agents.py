"""Scientific agents for MechanistGym tasks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import exp, log
from typing import Protocol, runtime_checkable

from .environment import Observation


@dataclass(frozen=True)
class Prediction:
    """An agent's answer plus the fitted parameters that produced it."""

    target_time: float
    predicted_value: float
    estimated_rate_constant: float
    estimated_initial_value: float


@runtime_checkable
class Agent(Protocol):
    """An entity that turns observations into an action or prediction."""

    def predict(
        self,
        observations: Sequence[Observation],
        *,
        target_time: float,
    ) -> Prediction:
        """Infer parameters and predict the state at ``target_time``."""


@dataclass(frozen=True)
class AnalyticDecayAgent:
    """Deterministic agent that solves first-order decay analytically.

    The agent observes the first and last data points, estimates k from
    their log ratio, reconstructs x(0), and extrapolates to the requested
    time. It never reads the environment's hidden parameters.
    """

    name: str = "analytic-decay-agent"

    def estimate_parameters(
        self,
        observations: Sequence[Observation],
    ) -> tuple[float, float]:
        if len(observations) < 2:
            raise ValueError("at least two observations are required")

        first = observations[0]
        last = observations[-1]
        elapsed = last.time - first.time
        if elapsed <= 0:
            raise ValueError("observations must be ordered at distinct times")
        if first.value <= 0 or last.value <= 0:
            raise ValueError("first-order decay observations must be positive")

        rate_constant = log(first.value / last.value) / elapsed
        initial_value = first.value * exp(rate_constant * first.time)
        return initial_value, rate_constant

    def predict(
        self,
        observations: Sequence[Observation],
        *,
        target_time: float,
    ) -> Prediction:
        if target_time < 0:
            raise ValueError("target_time must be non-negative")
        initial_value, rate_constant = self.estimate_parameters(observations)
        predicted_value = initial_value * exp(-rate_constant * target_time)
        return Prediction(
            target_time=target_time,
            predicted_value=predicted_value,
            estimated_rate_constant=rate_constant,
            estimated_initial_value=initial_value,
        )
