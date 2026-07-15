"""Executable example for the MechanistGym M0 milestone."""

from __future__ import annotations

from typing import Any

from .agents import AnalyticDecayAgent
from .environment import DecayTask, LinearDecayEnvironment
from .experiment import run_episode
from .models import LinearDecayModel
from .verification import AbsoluteToleranceVerifier


def run_decay_demo() -> dict[str, Any]:
    """Run one complete first-order biological-decay episode."""

    environment = LinearDecayEnvironment(
        model=LinearDecayModel(),
        initial_value=100.0,
        rate_constant=0.25,
        task=DecayTask(
            observation_times=(0.0, 2.0, 4.0),
            target_time=6.0,
        ),
    )
    result = run_episode(
        environment,
        AnalyticDecayAgent(),
        AbsoluteToleranceVerifier(tolerance=1e-10),
    )
    return {
        "episode_type": "first_order_decay_parameter_estimation",
        "model": "dx/dt = -k*x",
        "observations": [
            {"time": point.time, "value": point.value} for point in result.observations
        ],
        "estimated_rate_constant": result.prediction.estimated_rate_constant,
        "target_time": result.prediction.target_time,
        "predicted_value": result.prediction.predicted_value,
        "expected_value": result.expected_value,
        "absolute_error": result.verification.absolute_error,
        "verification_passed": result.verification.passed,
    }
