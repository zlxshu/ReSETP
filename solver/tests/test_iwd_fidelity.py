from __future__ import annotations

import unittest

from setp_solver.search.metaheuristic_baselines import _iwd_transition_weight, _iwd_update_global_soil


class IwdFidelityHelperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.params = {
            "soil0": 10000.0,
            "epsilon_s": 0.01,
            "rho_global": 0.9,
        }

    def test_transition_probability_uses_only_shifted_soil(self) -> None:
        soil = {("a", "b"): 10.0, ("a", "c"): 20.0}
        weight_b = _iwd_transition_weight("a", "b", soil, {"b", "c"}, self.params)
        weight_c = _iwd_transition_weight("a", "c", soil, {"b", "c"}, self.params)
        self.assertGreater(weight_b, weight_c)

    def test_global_update_uses_iteration_best_carried_soil(self) -> None:
        soil = {("a", "b"): 100.0, ("b", "c"): 200.0}
        _iwd_update_global_soil(["a", "b", "c"], soil, carried_soil=300.0, params=self.params)
        self.assertAlmostEqual(soil[("a", "b")], 1.9 * 100.0 - 0.9 * 300.0 / 2.0)
        self.assertAlmostEqual(soil[("b", "c")], 1.9 * 200.0 - 0.9 * 300.0 / 2.0)


if __name__ == "__main__":
    unittest.main()
