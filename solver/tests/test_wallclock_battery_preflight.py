from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from setp_solver.solution import ChargingAction, Route, Solution


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "baselines/e2_alns/wallclock_battery_preflight.py"
SPEC = importlib.util.spec_from_file_location("wallclock_battery_preflight", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _task() -> dict[str, object]:
    return {
        "commit_hash": "test",
        "scenario": "wc150",
        "scenario_label": "150kWh same wall-clock",
        "comparison_mode": "wallclock",
        "battery_kwh": 150.0,
        "category": "vanilla",
        "instance": "e2-vanilla-75c-01",
        "size": 75,
        "replicate": 1,
        "algorithm": "alns_e2_throughput",
        "seed": 1,
        "runtime_cap_seconds": 900.0,
        "eval_budget": 16000,
        "checkpoint_path": "dummy.json",
    }


def _row(scenario: str, instance: str, algorithm: str, cost: float, *, ev_routes: int, charging: int, seed: int = 1) -> dict[str, object]:
    route_count = 20
    return {
        "commit_hash": "test",
        "scenario": scenario,
        "scenario_label": scenario,
        "comparison_mode": "wallclock",
        "battery_kwh": runner.SCENARIOS[scenario]["battery_kwh"],
        "category": "vanilla",
        "instance": instance,
        "size": 100,
        "replicate": 1,
        "algorithm": algorithm,
        "seed": seed,
        "runtime_cap_seconds": 900.0,
        "eval_budget_backstop": 16000,
        "checkpoint_path": "dummy.json",
        "python": runner.GOLD_PYTHON,
        "numpy": runner.GOLD_NUMPY,
        "elapsed_seconds": 1.0,
        "actual_evals": 16000,
        "evals_per_second": 16000.0,
        "best_cost": cost,
        "route_count": route_count,
        "cv_route_count": route_count - ev_routes,
        "ev_route_count": ev_routes,
        "charging_action_count": charging,
        "winner_ev_route_share": ev_routes / route_count,
        "winner_all_cv": ev_routes == 0,
        "winner_all_ev": ev_routes == route_count,
        "cv_physical_vehicle_count": route_count - ev_routes,
        "ev_physical_vehicle_count": ev_routes,
        "max_trips_per_physical_vehicle": 1,
        "violation_count": 0,
        "feasible": True,
        "status": "OK",
        "gate_status": "OK",
        "checkpoint_readable": True,
    }


class WallclockBatteryPreflightTests(unittest.TestCase):
    def test_parse_scenarios_accepts_high_tension_tiers(self) -> None:
        self.assertEqual(runner.parse_scenarios("wc80,wc100,wc150,wc280"), ["wc80", "wc100", "wc150", "wc280"])

    def test_gradient01_75_200_selects_only_large_replicate_one_instances(self) -> None:
        selected = runner.select_instances("gradient01_75_200")

        self.assertEqual(len(selected), 12)
        self.assertTrue(all(size >= 75 for _, _, size, _ in selected))
        self.assertTrue(all(replicate == 1 for *_, replicate in selected))

    def test_row_from_solution_records_charging_action_count(self) -> None:
        solution = Solution(
            routes=[
                Route("CV1", "cv", "D0", ["D0", "C1", "D0"]),
                Route("EV1", "ev", "D0", ["D0", "C2", "D0"]),
            ],
            charging_actions=[
                ChargingAction("EV1", "D0", 10.0, 10.0, 0.0),
                ChargingAction("EV1", "F1", 5.0, 5.0, 100.0),
            ],
        )

        row = runner.row_from_solution(_task(), solution, 100.0, 10, 0, "OK", "OK", 1.0, {}, {})

        self.assertEqual(row["charging_action_count"], 2)
        self.assertEqual(row["winner_ev_route_share"], 0.5)

    def test_sign_test_less_counts_negative_diffs_as_alns_wins(self) -> None:
        self.assertAlmostEqual(runner.sign_test_less([-1.0, -2.0, 3.0, 4.0]), 0.6875)

    def test_high_tension_decision_recommends_stage_b_on_preregistered_signal(self) -> None:
        rows = [
            _row("wc80", "a", "alns_e2_throughput", 100.0, ev_routes=1, charging=0),
            _row("wc80", "a", "LNS", 100.0, ev_routes=1, charging=0),
            _row("wc80", "b", "alns_e2_throughput", 100.0, ev_routes=1, charging=0),
            _row("wc80", "b", "LNS", 100.0, ev_routes=1, charging=0),
            _row("wc150", "a", "alns_e2_throughput", 90.0, ev_routes=6, charging=4),
            _row("wc150", "a", "LNS", 100.0, ev_routes=6, charging=4),
            _row("wc150", "b", "alns_e2_throughput", 100.0, ev_routes=6, charging=4),
            _row("wc150", "b", "LNS", 100.0, ev_routes=6, charging=4),
        ]

        decision = runner.high_tension_decision(rows, expected_count=len(rows), instances_mode="gradient01")

        self.assertEqual(decision["verdict"], "INCONCLUSIVE_FAIL_NO_SEPARATION")
        self.assertTrue(decision["stage_b_recommended"])
        self.assertEqual(decision["stage_b_candidate_scenarios"], ["wc150"])


if __name__ == "__main__":
    unittest.main()
