"""Acceptance test for the user-facing v0.1 demonstration."""

from __future__ import annotations

import unittest

from mechanistgym.demo import run_decay_demo


class DemoTests(unittest.TestCase):
    def test_demo_returns_a_verified_trace(self) -> None:
        trace = run_decay_demo()

        self.assertEqual(
            trace["episode_type"],
            "first_order_decay_parameter_estimation",
        )
        self.assertAlmostEqual(trace["estimated_rate_constant"], 0.25)
        self.assertTrue(trace["verification_passed"])
        self.assertAlmostEqual(trace["absolute_error"], 0.0)


if __name__ == "__main__":
    unittest.main()
