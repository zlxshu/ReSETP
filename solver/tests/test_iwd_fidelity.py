from __future__ import annotations

import unittest

from setp_solver.search.metaheuristic_baselines import _iwd_transition_weight, _iwd_update_global_soil


class IwdFidelityHelperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.params = {
            "soil0": 10000.0,
            "epsilon_s": 1e-9,
            "rho_global": 0.9,
        }

    def test_transition_probability_uses_savings_and_shifted_soil(self) -> None:
        soil = {("a", "b"): 10.0, ("a", "c"): 20.0}
        savings = {("a", "b"): 5.0, ("a", "c"): 5.0}
        weight_b = _iwd_transition_weight("a", "b", soil, savings, {"b", "c"}, self.params)
        weight_c = _iwd_transition_weight("a", "c", soil, savings, {"b", "c"}, self.params)
        self.assertGreater(weight_b, weight_c)

    def test_global_update_uses_carried_soil_and_does_not_depend_on_objective(self) -> None:
        soil = {("a", "b"): 100.0, ("b", "c"): 200.0}
        _iwd_update_global_soil(["a", "b", "c"], soil, carried_soil=300.0, params=self.params)
        expected_deposit = 2.0 * 300.0 / (3.0 * 2.0)
        self.assertAlmostEqual(soil[("a", "b")], 0.1 * 100.0 + 0.9 * expected_deposit)
        self.assertAlmostEqual(soil[("b", "c")], 0.1 * 200.0 + 0.9 * expected_deposit)


if __name__ == "__main__":
    unittest.main()
