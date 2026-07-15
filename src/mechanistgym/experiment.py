"""The observe -> predict -> verify scientific-agent loop."""

from __future__ import annotations

from dataclasses import dataclass

from .agents import Agent, Prediction
from .environment import Environment, Observation
from .verification import VerificationResult, Verifier


@dataclass(frozen=True)
class EpisodeResult:
    """Complete trace of one agent attempt in one environment."""

    observations: tuple[Observation, ...]
    prediction: Prediction
    expected_value: float
    verification: VerificationResult


def run_episode(
    environment: Environment,
    agent: Agent,
    verifier: Verifier,
) -> EpisodeResult:
    """Run one deterministic observe -> predict -> verify episode."""

    observations = environment.observe()
    prediction = agent.predict(
        observations,
        target_time=environment.target_time,
    )
    expected_value = environment.expected_value()
    verification = verifier.verify(
        prediction,
        expected_value=expected_value,
    )
    return EpisodeResult(
        observations=observations,
        prediction=prediction,
        expected_value=expected_value,
        verification=verification,
    )
