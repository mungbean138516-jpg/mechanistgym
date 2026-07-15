"""Task environments that expose observations while hiding ground truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .models import Model


@dataclass(frozen=True)
class Observation:
    """One value observed from a model at a known time."""

    time: float
    value: float


@dataclass(frozen=True)
class DecayTask:
    """Times shown to an agent and the later time it must predict."""

    observation_times: tuple[float, ...]
    target_time: float

    def __post_init__(self) -> None:
        if len(self.observation_times) < 2:
            raise ValueError("at least two observations are required")
        if any(time < 0 for time in self.observation_times):
            raise ValueError("observation times must be non-negative")
        if any(
            later <= earlier
            for earlier, later in zip(
                self.observation_times,
                self.observation_times[1:],
                strict=False,
            )
        ):
            raise ValueError("observation times must be strictly increasing")
        if self.target_time <= self.observation_times[-1]:
            raise ValueError("target_time must follow all observation times")


@runtime_checkable
class Environment(Protocol):
    """An interface through which an agent interacts with a dry lab."""

    @property
    def target_time(self) -> float:
        """Return the time the agent is asked to predict."""

    def observe(self) -> tuple[Observation, ...]:
        """Return the evidence available to the agent."""

    def expected_value(self) -> float:
        """Return hidden ground truth for evaluation only."""


@dataclass(frozen=True)
class LinearDecayEnvironment:
    """Deterministic dry lab for a first-order decay parameter task."""

    model: Model
    initial_value: float
    rate_constant: float
    task: DecayTask

    def __post_init__(self) -> None:
        if self.initial_value <= 0:
            raise ValueError("initial_value must be positive")
        if self.rate_constant < 0:
            raise ValueError("rate_constant must be non-negative")

    @property
    def target_time(self) -> float:
        return self.task.target_time

    def observe(self) -> tuple[Observation, ...]:
        return tuple(
            Observation(
                time=time,
                value=self.model.simulate(
                    initial_value=self.initial_value,
                    rate_constant=self.rate_constant,
                    time=time,
                ),
            )
            for time in self.task.observation_times
        )

    def expected_value(self) -> float:
        return self.model.simulate(
            initial_value=self.initial_value,
            rate_constant=self.rate_constant,
            time=self.target_time,
        )
