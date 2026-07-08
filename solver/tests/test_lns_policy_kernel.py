from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

SOLVER_SRC = Path(__file__).resolve().parents[1] / "src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))


class LnsPolicyKernelTests(unittest.TestCase):
    def test_macro_actions_cover_lns_policy_package(self) -> None:
        from setp_solver.search import lns_policy_kernel as kernel

        self.assertIn("vehicle_type_mutation", kernel.LNS_POLICY_MACRO_ACTIONS)
        self.assertIn("fallback_order_relocate", kernel.LNS_POLICY_MACRO_ACTIONS)
        self.assertIn("strong_bridge_random_customer_removal_greedy_insert_repair", kernel.LNS_POLICY_MACRO_ACTIONS)
        self.assertIn("strong_bridge_worst_customer_removal_regret3_insert_repair", kernel.LNS_POLICY_MACRO_ACTIONS)

    def test_reheated_temperature_uses_current_objective(self) -> None:
        from setp_solver.search import lns_policy_kernel as kernel

        temperature = kernel.reheated_temperature(current_objective=1200.0, phi=0.05)

        self.assertTrue(math.isfinite(temperature))
        self.assertGreater(temperature, 0.0)
        self.assertAlmostEqual(temperature, -0.05 * 1200.0 / math.log(0.5))


if __name__ == "__main__":
    unittest.main()
