from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path("solver/tools/e2_route_compression_probe.py")


def _load_probe_module():
    spec = importlib.util.spec_from_file_location("e2_route_compression_probe", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_annotate_vs_winner_reports_route_and_cost_deltas() -> None:
    probe = _load_probe_module()
    rows = [
        {
            "bundle": "case",
            "seed": 1,
            "algorithm": "winner_kernel",
            "best_cost": 100.0,
            "route_count": 4,
            "fixed_cost": 40.0,
            "route_count_delta_vs_winner": "",
            "fixed_cost_delta_vs_winner": "",
            "objective_delta_vs_winner": "",
            "gap_vs_lns_delta_pp": "",
        },
        {
            "bundle": "case",
            "seed": 1,
            "algorithm": "winner_kernel_plus_route_elimination",
            "best_cost": 95.0,
            "route_count": 3,
            "fixed_cost": 30.0,
            "route_count_delta_vs_winner": "",
            "fixed_cost_delta_vs_winner": "",
            "objective_delta_vs_winner": "",
            "gap_vs_lns_delta_pp": "",
        },
    ]

    annotated = probe.annotate_vs_winner(rows)

    assert annotated[1]["route_count_delta_vs_winner"] == -1
    assert annotated[1]["fixed_cost_delta_vs_winner"] == -10.0
    assert annotated[1]["objective_delta_vs_winner"] == -5.0
    assert annotated[1]["gap_vs_lns_delta_pp"] == ""


def test_decision_from_rows_marks_missing_short_budget_signal_as_fix_required() -> None:
    probe = _load_probe_module()
    rows = [
        {
            "bundle": "case",
            "seed": 1,
            "algorithm": "winner_kernel",
            "best_cost": 100.0,
            "route_count": 4,
            "fixed_cost": 40.0,
            "feasible": True,
            "route_count_delta_vs_winner": "",
            "fixed_cost_delta_vs_winner": "",
            "objective_delta_vs_winner": "",
        },
        {
            "bundle": "case",
            "seed": 1,
            "algorithm": "winner_kernel_plus_route_elimination",
            "best_cost": 100.0,
            "route_count": 4,
            "fixed_cost": 40.0,
            "feasible": True,
            "route_count_delta_vs_winner": 0,
            "fixed_cost_delta_vs_winner": 0.0,
            "objective_delta_vs_winner": 0.0,
        },
    ]

    decision = probe.decision_from_rows(rows)

    assert decision["status"] == "ROUTE_COMPRESSION_NO_SHORT_BUDGET_SIGNAL"
    assert decision["requires_code_fix"] is True


def test_decision_from_rows_marks_objective_regression_as_fix_required() -> None:
    probe = _load_probe_module()
    rows = [
        {
            "bundle": "case",
            "seed": 1,
            "algorithm": "winner_kernel",
            "best_cost": 100.0,
            "route_count": 4,
            "fixed_cost": 40.0,
            "feasible": True,
            "route_count_delta_vs_winner": "",
            "fixed_cost_delta_vs_winner": "",
            "objective_delta_vs_winner": "",
        },
        {
            "bundle": "case",
            "seed": 1,
            "algorithm": "winner_kernel_plus_route_elimination",
            "best_cost": 101.0,
            "route_count": 3,
            "fixed_cost": 30.0,
            "feasible": True,
            "route_count_delta_vs_winner": -1,
            "fixed_cost_delta_vs_winner": -10.0,
            "objective_delta_vs_winner": 1.0,
        },
    ]

    decision = probe.decision_from_rows(rows)

    assert decision["status"] == "ROUTE_COMPRESSION_INTEGRATION_REGRESSED"
    assert decision["regression_rows_over_0_5pct"] == 1
    assert decision["requires_code_fix"] is True
