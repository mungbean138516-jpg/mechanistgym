"""Independent checks for scientific-agent outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .agents import Prediction


@dataclass(frozen=True)
class VerificationResult:
    """Machine-readable result returned by a verifier."""

    passed: bool
    absolute_error: float
    tolerance: float
    message: str


@runtime_checkable
class Verifier(Protocol):
    """An independent evaluator of an agent prediction."""

    def verify(
        self,
        prediction: Prediction,
        *,
        expected_value: float,
    ) -> VerificationResult:
        """Compare an agent output with task ground truth."""


@dataclass(frozen=True)
class AbsoluteToleranceVerifier:
    """Accept a prediction when its absolute error is within tolerance."""

    tolerance: float = 1e-9

    def __post_init__(self) -> None:
        if self.tolerance < 0:
            raise ValueError("tolerance must be non-negative")

    def verify(
        self,
        prediction: Prediction,
        *,
        expected_value: float,
    ) -> VerificationResult:
        error = abs(prediction.predicted_value - expected_value)
        passed = error <= self.tolerance
        outcome = "passed" if passed else "failed"
        return VerificationResult(
            passed=passed,
            absolute_error=error,
            tolerance=self.tolerance,
            message=(
                f"Prediction {outcome}: absolute error {error:.6g} "
                f"with tolerance {self.tolerance:.6g}."
            ),
        )
