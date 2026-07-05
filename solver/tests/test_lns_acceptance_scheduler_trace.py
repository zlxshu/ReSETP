from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from baselines.e2_alns import lns_acceptance_scheduler_audit as audit
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.metaheuristic_baselines import (
    _classify_lns_trace_path,
    _lns_trace_diagnostic_enabled,
    _trace_acceptance_fields,
)
from setp_solver.search.winner_operators import (
    TRACE_DIAGNOSTIC_FLAG,
    WinnerKernelConfig,
    _winner_history_entry,
    run_e2_alns_throughput,
)
from setp_solver.search.evaluation import EvaluationContext


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/verify_20251113"


class LnsAcceptanceSchedulerTraceTests(unittest.TestCase):
    def test_trace_flag_defaults_off_and_plain_history_schema_stays_legacy(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(TRACE_DIAGNOSTIC_FLAG, None)
            result = run_e2_alns_throughput(
                VERIFY_BUNDLE,
                config=WinnerKernelConfig(seed=21, eval_budget=4, max_runtime_seconds=120.0),
            )

        self.assertTrue(result["history"])
        self.assertNotIn("route_count", result["history"][0])
        self.assertNotIn("signature", result["history"][0])
        self.assertNotIn("candidate_trace", result["operator_counts"])
        self.assertFalse(_lns_trace_diagnostic_enabled())

    def test_trace_flag_adds_route_count_signature_to_winner_history(self) -> None:
        bundle = load_search_bundle(VERIFY_BUNDLE)
        solution = make_shared_initial_solution(bundle)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)

        entry = _winner_history_entry(
            context,
            solution,
            objective=123.0,
            eval_count=7,
            started=0.0,
            operator="unit",
            include_trace_fields=True,
        )

        self.assertEqual(entry["route_count"], len(solution.routes))
        self.assertTrue(entry["signature"])

    def test_lns_trace_path_distinguishes_strong_bridge_and_fallback(self) -> None:
        self.assertEqual(_classify_lns_trace_path("lns_scan_initial", fallback_used=False), "scan_initial")
        self.assertEqual(_classify_lns_trace_path("lns_vehicle_type_mutation", fallback_used=False), "vehicle_type_mutation")
        self.assertEqual(_classify_lns_trace_path("lns_random_farthest", fallback_used=False), "strong_bridge")
        self.assertEqual(_classify_lns_trace_path("lns_random_farthest", fallback_used=True), "fallback_relocate")

    def test_trace_acceptance_fields_mark_worse_acceptance_and_best_improvement(self) -> None:
        worse = _trace_acceptance_fields(
            previous_obj=100.0,
            candidate_obj=105.0,
            previous_best_obj=90.0,
            accepted=True,
            hard_violation_count=0,
        )
        better = _trace_acceptance_fields(
            previous_obj=100.0,
            candidate_obj=80.0,
            previous_best_obj=90.0,
            accepted=True,
            hard_violation_count=0,
        )
        infeasible = _trace_acceptance_fields(
            previous_obj=100.0,
            candidate_obj=80.0,
            previous_best_obj=90.0,
            accepted=True,
            hard_violation_count=1,
        )

        self.assertTrue(worse["accepted_worse"])
        self.assertFalse(worse["best_improved"])
        self.assertFalse(better["accepted_worse"])
        self.assertTrue(better["best_improved"])
        self.assertFalse(infeasible["best_improved"])

    def test_summary_preserves_unknown_route_count_without_guessing(self) -> None:
        rows = audit.summarize_alns_revert_reasons(
            [
                {
                    "profile": "A0_TRACE",
                    "destroy_id": "shaw_related_removal",
                    "repair_id": "regret2_insert_repair",
                    "revert_reason": "candidate_usable",
                    "accepted": True,
                    "best_improved": False,
                    "hard_violation_count": 0,
                    "candidate_route_count_delta": "UNKNOWN",
                    "local_search_improved": "UNKNOWN",
                }
            ]
        )

        self.assertEqual(rows[0]["route_count_drop_count"], "UNKNOWN")
        self.assertEqual(rows[0]["local_search_improve_count"], "UNKNOWN")

    def test_diagnostic_task_contract_uses_hard_subset_and_marks_nonformal(self) -> None:
        hard_subset = [{"category": "vanilla", "instance": "e2-vanilla-10c-01"}]
        with tempfile.TemporaryDirectory() as tmp:
            tasks = audit.build_trace_tasks(
                Path(tmp),
                hard_subset,
                seeds=[1, 2],
                eval_budget=4000,
                runtime_cap_seconds=900.0,
            )
            decision = audit.build_decision(
                metadata={"head": "abc"},
                rows=[{"status": "OK"}, {"status": "OK"}],
                expected_rows=4,
                lns_summary=[],
                alns_summary=[],
            )

        self.assertEqual([task["profile"] for task in tasks], ["LNS_TRACE", "A0_TRACE", "LNS_TRACE", "A0_TRACE"])
        self.assertEqual(len(tasks), 4)
        self.assertTrue(decision["diagnostic_only"])
        self.assertFalse(decision["formal_t3"])
        self.assertEqual(decision["expected_rows"], 4)


if __name__ == "__main__":
    unittest.main()
