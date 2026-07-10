from __future__ import annotations

import unittest

from baselines.e2_alns.m1_e2_submission_closeout import ALGORITHMS, build_closeout


class E2SubmissionCloseoutTest(unittest.TestCase):
    def test_closeout_keeps_aggregate_and_pairwise_claims_separate(self) -> None:
        rows = []
        for size in (10, 15, 20, 25, 50, 75, 100, 150, 200):
            for seed in range(1, 6):
                instance = f"L-main-threeshift-{size}c-01"
                for algorithm in ALGORITHMS:
                    cost = {
                        "staged_hybrid_carbon_aware": 90.0,
                        "staged_hybrid_carbon_naive": 91.0,
                        "LNS": 100.0,
                        "GA": 110.0,
                        "PSO": 120.0,
                        "VNS": 105.0,
                    }[algorithm]
                    rows.append(
                        {
                            "instance": instance,
                            "seed": str(seed),
                            "algorithm": algorithm,
                            "best_cost": str(cost),
                            "elapsed_seconds": "10" if algorithm.startswith("staged_") else "20",
                            "gate_status": "OK",
                            "actual_evals": "4000",
                            "violation_count": "0",
                            "route_structure_signature": f"route-{instance}-{seed}",
                            "electricity_kwh": "50",
                            "E_ev_indirect": "9" if algorithm == "staged_hybrid_carbon_aware" else "10",
                            "charging_actions_moved_from_search_output": "1" if algorithm == "staged_hybrid_carbon_aware" else "0",
                        }
                    )

        _, _, decision = build_closeout(rows)

        self.assertEqual(decision["verdict"], "E2_FULL_BENCHMARK_LEAD_SUPPORTED")
        self.assertTrue(decision["claim_boundaries"]["aggregate_benchmark_lead_over_5pct"])
        self.assertFalse(decision["claim_boundaries"]["uniform_pairwise_5pct_claim"])


if __name__ == "__main__":
    unittest.main()
