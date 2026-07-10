from __future__ import annotations

import unittest

from baselines.e2_alns import m1_e2_submission_runner as runner


class E2SubmissionLivenessAdjudicationTest(unittest.TestCase):
    def test_independent_algorithms_converging_to_same_solution_is_information(self) -> None:
        rows = [
            {
                "algorithm": "LNS",
                "best_signature": "same-output",
                "route_structure_signature": "route-a",
                "algorithm_specific_update_count": 4,
            },
            {
                "algorithm": "VNS",
                "best_signature": "same-output",
                "route_structure_signature": "route-b",
                "algorithm_specific_update_count": 7,
            },
        ]
        liveness = [
            {
                "scope": "cross_algorithm",
                "algorithm": "LNS|VNS",
                "verdict": "CROSS_ALGO_IDENTITY_SUSPECT",
                "flags": "shared_signature=same-output",
            }
        ]

        result = runner.adjudicate_submission_liveness(rows, liveness)

        self.assertEqual(result[0]["decision"], "INFO")
        self.assertEqual(result[0]["adjudicated_verdict"], "INDEPENDENT_CONVERGENCE_INFO")
        self.assertEqual(result[0]["algorithm_specific_active_runs"], 2)
        self.assertEqual(result[0]["route_structure_signature_count"], 2)

    def test_shared_output_without_algorithm_specific_activity_halts(self) -> None:
        rows = [
            {
                "algorithm": "LNS",
                "best_signature": "same-output",
                "route_structure_signature": "route-a",
                "algorithm_specific_update_count": 3,
            },
            {
                "algorithm": "VNS",
                "best_signature": "same-output",
                "route_structure_signature": "route-a",
                "algorithm_specific_update_count": 0,
                "history_json": "[]",
            },
        ]
        liveness = [
            {
                "scope": "cross_algorithm",
                "algorithm": "LNS|VNS",
                "verdict": "CROSS_ALGO_IDENTITY_SUSPECT",
                "flags": "shared_signature=same-output",
            }
        ]

        result = runner.adjudicate_submission_liveness(rows, liveness)

        self.assertEqual(result[0]["decision"], "HALT")

    def test_seed_invariance_remains_a_hard_stop(self) -> None:
        result = runner.adjudicate_submission_liveness(
            [],
            [
                {
                    "scope": "algorithm_seed_group",
                    "algorithm": "GA",
                    "verdict": "SEED_INVARIANCE_SUSPECT",
                    "flags": "exact_cost_and_signature_repeated_across_seeds",
                }
            ],
        )

        self.assertEqual(result[0]["decision"], "HALT")

    def test_legacy_liveness_failure_is_cleared_by_algorithm_specific_activity(self) -> None:
        rows = [
            {
                "run_id": "ga-active",
                "algorithm": "GA",
                "algorithm_specific_update_count": 12,
            }
        ]
        liveness = [
            {
                "scope": "run",
                "run_id": "ga-active",
                "algorithm": "GA",
                "verdict": "BASELINE_LIVENESS_FAIL",
                "flags": "NO_NATIVE_BEST_UPDATE|LOW_ROUTE_COUNT_DIVERSITY",
            }
        ]

        result = runner.adjudicate_submission_liveness(rows, liveness)

        self.assertEqual(result[0]["decision"], "INFO")
        self.assertEqual(result[0]["adjudicated_verdict"], "ALGORITHM_SPECIFIC_ACTIVITY_CONFIRMED")

    def test_legacy_liveness_failure_without_any_activity_still_halts(self) -> None:
        rows = [
            {
                "run_id": "pso-inactive",
                "algorithm": "PSO",
                "algorithm_specific_update_count": 0,
                "history_json": "[]",
            }
        ]
        liveness = [
            {
                "scope": "run",
                "run_id": "pso-inactive",
                "algorithm": "PSO",
                "verdict": "BASELINE_LIVENESS_FAIL",
                "flags": "NO_NATIVE_BEST_UPDATE",
            }
        ]

        result = runner.adjudicate_submission_liveness(rows, liveness)

        self.assertEqual(result[0]["decision"], "HALT")


if __name__ == "__main__":
    unittest.main()
