"""Unit and end-to-end tests for the first MechanistGym dry lab."""

from __future__ import annotations

import math
import unittest

from mechanistgym import (
    AbsoluteToleranceVerifier,
    AnalyticDecayAgent,
    DecayTask,
    LinearDecayEnvironment,
    LinearDecayModel,
    Observation,
    Prediction,
    run_episode,
)


class LinearDecayModelTests(unittest.TestCase):
    def test_analytic_simulator(self) -> None:
        model = LinearDecayModel()

        value = model.simulate(
            initial_value=10.0,
            rate_constant=0.5,
            time=2.0,
        )

        self.assertAlmostEqual(value, 10.0 * math.exp(-1.0))

    def test_simulator_rejects_negative_rate(self) -> None:
        model = LinearDecayModel()

        with self.assertRaises(ValueError):
            model.simulate(
                initial_value=10.0,
                rate_constant=-0.1,
                time=2.0,
            )


class AnalyticDecayAgentTests(unittest.TestCase):
    def test_agent_estimates_rate_and_predicts(self) -> None:
        observations = (
            Observation(time=0.0, value=10.0),
            Observation(time=2.0, value=10.0 * math.exp(-1.0)),
        )

        prediction = AnalyticDecayAgent().predict(
            observations,
            target_time=4.0,
        )

        self.assertAlmostEqual(prediction.estimated_rate_constant, 0.5)
        self.assertAlmostEqual(prediction.estimated_initial_value, 10.0)
        self.assertAlmostEqual(
            prediction.predicted_value,
            10.0 * math.exp(-2.0),
        )


class AbsoluteToleranceVerifierTests(unittest.TestCase):
    @staticmethod
    def _prediction(value: float) -> Prediction:
        return Prediction(
            target_time=4.0,
            predicted_value=value,
            estimated_rate_constant=0.5,
            estimated_initial_value=10.0,
        )

    def test_verifier_passes_accurate_prediction(self) -> None:
        result = AbsoluteToleranceVerifier(tolerance=0.01).verify(
            self._prediction(4.005),
            expected_value=4.0,
        )

        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.absolute_error, 0.005)

    def test_verifier_fails_inaccurate_prediction(self) -> None:
        result = AbsoluteToleranceVerifier(tolerance=0.01).verify(
            self._prediction(4.1),
            expected_value=4.0,
        )

        self.assertFalse(result.passed)
        self.assertAlmostEqual(result.absolute_error, 0.1)


class EpisodeTests(unittest.TestCase):
    def test_end_to_end_observe_predict_verify_loop(self) -> None:
        environment = LinearDecayEnvironment(
            model=LinearDecayModel(),
            initial_value=12.0,
            rate_constant=0.1,
            task=DecayTask(
                observation_times=(0.0, 2.0, 6.0),
                target_time=10.0,
            ),
        )

        result = run_episode(
            environment,
            AnalyticDecayAgent(),
            AbsoluteToleranceVerifier(tolerance=1e-12),
        )

        self.assertEqual(len(result.observations), 3)
        self.assertAlmostEqual(result.prediction.estimated_rate_constant, 0.1)
        self.assertAlmostEqual(
            result.prediction.predicted_value,
            12.0 * math.exp(-1.0),
        )
        self.assertAlmostEqual(result.expected_value, 12.0 * math.exp(-1.0))
        self.assertTrue(result.verification.passed)


if __name__ == "__main__":
    unittest.main()
