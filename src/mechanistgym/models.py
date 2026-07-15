"""Mathematical models used by MechanistGym environments."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Protocol, runtime_checkable


@runtime_checkable
class Model(Protocol):
    """A mathematical system that can generate an observation."""

    def simulate(
        self,
        *,
        initial_value: float,
        rate_constant: float,
        time: float,
    ) -> float:
        """Return the state of the system at ``time``."""


@dataclass(frozen=True)
class LinearDecayModel:
    """Analytic model for the first-order linear ODE dx/dt = -k*x.

    Its solution is x(t) = x(0) * exp(-k*t). The closed-form solution
    supports exact validation of the platform contracts without a numerical
    solver.
    """

    def simulate(
        self,
        *,
        initial_value: float,
        rate_constant: float,
        time: float,
    ) -> float:
        if initial_value <= 0:
            raise ValueError("initial_value must be positive")
        if rate_constant < 0:
            raise ValueError("rate_constant must be non-negative")
        if time < 0:
            raise ValueError("time must be non-negative")
        return initial_value * exp(-rate_constant * time)
