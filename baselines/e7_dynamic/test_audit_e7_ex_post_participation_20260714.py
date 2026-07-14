from __future__ import annotations

from pathlib import Path
import sys
import unittest


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
import audit_e7_ex_post_participation_20260714 as MODULE


class ParticipationProbeTests(unittest.TestCase):
    def test_stream_one_closes_mechanically(self) -> None:
        result = MODULE.audit_stream(1)
        for arm in ("cooperative", "independent"):
            row = result[arm]
            self.assertLess(abs(row["cost_closure_error"]), 1e-6)
            self.assertAlmostEqual(
                sum(row["profit_by_depot"].values()),
                sum(row["revenue_by_depot"].values()) - sum(row["cost_by_depot"].values()),
                places=6,
            )
        self.assertTrue(all(value > 0 for value in result["independent"]["profit_by_depot"].values()))

    def test_zero_fee_and_zero_carbon_are_required(self) -> None:
        validator = MODULE._validator()
        prices = validator.formal_prices()
        self.assertEqual(float(prices.cross_site_cost), 0.0)
        self.assertEqual(float(prices.carbon_price), 0.0)


if __name__ == "__main__":
    unittest.main()
