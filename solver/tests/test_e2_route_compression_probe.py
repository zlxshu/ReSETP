from __future__ import annotations

import importlib.util
from pathlib import Path

from setp_solver.instance_loader import Instance, Node
from setp_solver.solution import Route, Solution


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
            "algorithm": "lns_reference",
            "best_cost": 90.0,
            "route_count": 3,
            "fixed_cost": 30.0,
            "route_count_delta_vs_winner": "",
            "fixed_cost_delta_vs_winner": "",
            "objective_delta_vs_winner": "",
            "gap_vs_lns_delta_pp": "",
        },
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

    assert annotated[2]["route_count_delta_vs_winner"] == -1
    assert annotated[2]["fixed_cost_delta_vs_winner"] == -10.0
    assert annotated[2]["objective_delta_vs_winner"] == -5.0
    assert annotated[2]["gap_vs_lns_delta_pp"] == 5.555555555555555


def test_solution_row_reports_auditable_route_metrics() -> None:
    probe = _load_probe_module()
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
            Node("C1", "c", 1.0, 0.0, demand=1.0, due_time=100_000.0),
        ],
        distance_matrix=[[0.0, 1.0], [1.0, 0.0]],
    )
    solution = Solution(routes=[Route("CV1", "cv", "D0", ["D0", "C1", "D0"])])

    row = probe.solution_row(
        bundle_id="case",
        algorithm="winner_kernel",
        seed=1,
        solution=solution,
        carbon_profile=[],
        instance=instance,
        eval_budget=10,
        best_update_count=2,
        unique_solution_count=3,
    )

    assert row["ev_routes"] == 0
    assert row["cv_routes"] == 1
    assert row["cv_route_share"] == 1.0
    assert row["zero_violations"] is True
    assert row["best_update_count"] == 2
    assert row["unique_solution_count"] == 3


def test_history_stats_counts_best_updates_and_unique_solutions() -> None:
    probe = _load_probe_module()
    solution = Solution(routes=[Route("CV1", "cv", "D0", ["D0", "C1", "D0"])])
    result = {
        "history": [
            {"solution_signature_hash": "warm"},
            {"solution_signature_hash": "best1"},
            {"solution_signature_hash": "best1"},
        ]
    }

    stats = probe._history_stats(result, solution)

    assert stats["best_update_count"] == 2
    assert stats["unique_solution_count"] == 3


def test_winner_profile_flags_make_local_search_and_route_elimination_explicit() -> None:
    probe = _load_probe_module()

    base = probe.winner_profile_flags(include_route_elimination=False, local_search=False)
    local = probe.winner_profile_flags(include_route_elimination=False, local_search=True)
    route = probe.winner_profile_flags(include_route_elimination=True, local_search=False)
    combined = probe.winner_profile_flags(include_route_elimination=True, local_search=True)

    assert base["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] == "0"
    assert base["SETP_ALNS_CRUSH_LOCAL_SEARCH"] == "0"
    assert local["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] == "0"
    assert local["SETP_ALNS_CRUSH_LOCAL_SEARCH"] == "1"
    assert route["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] == "1"
    assert route["SETP_ALNS_CRUSH_LOCAL_SEARCH"] == "0"
    assert combined["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] == "1"
    assert combined["SETP_ALNS_CRUSH_LOCAL_SEARCH"] == "1"


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


def test_decision_from_rows_reports_first_gate_pass() -> None:
    probe = _load_probe_module()
    rows = [
        {
            "bundle": "e2-threeshift-100c-01",
            "seed": 1,
            "algorithm": "winner_kernel",
            "best_cost": 100.0,
            "route_count": 4,
            "fixed_cost": 40.0,
            "feasible": True,
            "zero_violations": True,
        },
        {
            "bundle": "e2-threeshift-100c-01",
            "seed": 1,
            "algorithm": "winner_kernel_plus_route_elimination",
            "best_cost": 95.0,
            "route_count": 3,
            "fixed_cost": 30.0,
            "feasible": True,
            "zero_violations": True,
            "route_count_delta_vs_winner": -1,
            "fixed_cost_delta_vs_winner": -10.0,
            "objective_delta_vs_winner": -5.0,
        },
        {
            "bundle": "e2-threeshift-200c-01",
            "seed": 1,
            "algorithm": "winner_kernel",
            "best_cost": 200.0,
            "route_count": 8,
            "fixed_cost": 80.0,
            "feasible": True,
            "zero_violations": True,
        },
        {
            "bundle": "e2-threeshift-200c-01",
            "seed": 1,
            "algorithm": "winner_kernel_plus_route_elimination",
            "best_cost": 200.5,
            "route_count": 8,
            "fixed_cost": 80.0,
            "feasible": True,
            "zero_violations": "True",
            "route_count_delta_vs_winner": 0,
            "fixed_cost_delta_vs_winner": 0.0,
            "objective_delta_vs_winner": 0.5,
        },
    ]

    decision = probe.decision_from_rows(rows)

    assert decision["first_gate_pass"] is True
    assert decision["first_gate_100c_improved_count"] == 1
    assert decision["first_gate_sanity_regression_count"] == 0


def test_decision_from_rows_requires_fix_when_route_signal_misses_100c_gate() -> None:
    probe = _load_probe_module()
    rows = [
        {
            "bundle": "e2-threeshift-75c-02",
            "seed": 1,
            "algorithm": "winner_kernel",
            "best_cost": 100.0,
            "route_count": 4,
            "fixed_cost": 40.0,
            "feasible": True,
            "zero_violations": True,
        },
        {
            "bundle": "e2-threeshift-75c-02",
            "seed": 1,
            "algorithm": "winner_kernel_plus_route_elimination",
            "best_cost": 95.0,
            "route_count": 4,
            "fixed_cost": 40.0,
            "feasible": True,
            "zero_violations": True,
            "route_count_delta_vs_winner": 0,
            "fixed_cost_delta_vs_winner": 0.0,
            "objective_delta_vs_winner": -5.0,
        },
        {
            "bundle": "e2-threeshift-100c-01",
            "seed": 1,
            "algorithm": "winner_kernel",
            "best_cost": 200.0,
            "route_count": 8,
            "fixed_cost": 80.0,
            "feasible": True,
            "zero_violations": True,
        },
        {
            "bundle": "e2-threeshift-100c-01",
            "seed": 1,
            "algorithm": "winner_kernel_plus_route_elimination",
            "best_cost": 200.0,
            "route_count": 8,
            "fixed_cost": 80.0,
            "feasible": True,
            "zero_violations": True,
            "route_count_delta_vs_winner": 0,
            "fixed_cost_delta_vs_winner": 0.0,
            "objective_delta_vs_winner": 0.0,
        },
    ]

    decision = probe.decision_from_rows(rows)

    assert decision["status"] == "ROUTE_COMPRESSION_SIGNAL_FOUND"
    assert decision["first_gate_pass"] is False
    assert decision["requires_code_fix"] is True


def test_decision_from_rows_reports_lns_reference_availability() -> None:
    probe = _load_probe_module()
    rows = [
        {
            "bundle": "case",
            "seed": 1,
            "algorithm": "lns_reference",
            "best_cost": 90.0,
            "route_count": 3,
            "fixed_cost": 30.0,
            "feasible": True,
            "zero_violations": True,
        },
        {
            "bundle": "case",
            "seed": 1,
            "algorithm": "winner_kernel",
            "best_cost": 100.0,
            "route_count": 4,
            "fixed_cost": 40.0,
            "feasible": True,
            "zero_violations": True,
            "route_count_delta_vs_winner": "",
            "fixed_cost_delta_vs_winner": "",
            "objective_delta_vs_winner": "",
        },
        {
            "bundle": "case",
            "seed": 1,
            "algorithm": "winner_kernel_plus_route_elimination",
            "best_cost": 95.0,
            "route_count": 3,
            "fixed_cost": 30.0,
            "feasible": True,
            "zero_violations": True,
            "route_count_delta_vs_winner": -1,
            "fixed_cost_delta_vs_winner": -10.0,
            "objective_delta_vs_winner": -5.0,
        },
    ]

    decision = probe.decision_from_rows(rows)

    assert decision["lns_reference_available"] is True


def test_decision_from_rows_counts_matrix_route_elimination_profiles() -> None:
    probe = _load_probe_module()
    rows = [
        {
            "bundle": "e2-threeshift-100c-01",
            "seed": 1,
            "algorithm": "winner_kernel",
            "best_cost": 100.0,
            "route_count": 4,
            "fixed_cost": 40.0,
            "feasible": True,
            "zero_violations": True,
        },
        {
            "bundle": "e2-threeshift-100c-01",
            "seed": 1,
            "algorithm": "winner_kernel_route_elimination",
            "best_cost": 95.0,
            "route_count": 3,
            "fixed_cost": 30.0,
            "feasible": True,
            "zero_violations": True,
            "route_count_delta_vs_winner": -1,
            "fixed_cost_delta_vs_winner": -10.0,
            "objective_delta_vs_winner": -5.0,
        },
        {
            "bundle": "e2-threeshift-100c-01",
            "seed": 1,
            "algorithm": "winner_kernel_route_elimination_local_search",
            "best_cost": 94.0,
            "route_count": 3,
            "fixed_cost": 30.0,
            "feasible": True,
            "zero_violations": True,
            "route_count_delta_vs_winner": -1,
            "fixed_cost_delta_vs_winner": -10.0,
            "objective_delta_vs_winner": -6.0,
        },
    ]

    decision = probe.decision_from_rows(rows)

    assert decision["route_elimination_rows"] == 2
    assert decision["improved_rows"] == 2
