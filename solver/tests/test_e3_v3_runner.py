from __future__ import annotations

import json

from baselines.e3_ablation.e3_v3_runner import (
    _cooperation_mobility_row_ok,
    default_budget,
    fairness_rejection_count,
    phase_plans,
    prices_for,
    score_counts,
    summarize_phase,
)
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerOperatorSet,
    _forced_cross_depot_pair,
    _selector_coupling_contract,
)
from setp_solver.algorithms.resetp_alns.operators.feasible_repair import repair_removed_customers
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Route, Solution


def test_formal_matrix_is_seed_first_and_has_exactly_seventy_rows() -> None:
    plans = phase_plans("formal70", 4000)
    assert len(plans) == 5
    assert sum(len(plan["specs"]) for plan in plans) == 70
    for seed, plan in enumerate(plans, start=1):
        assert plan["seed"] == seed
        assert plan["specs"][0]["layer"] == "M0"
        assert plan["specs"][0]["size"] == "200c"
        assert sum(spec["size"] == "100c" for spec in plan["specs"]) == 4
        assert sum(spec["fee"] > 0 for spec in plan["specs"]) == 4


def test_preflight_separates_plain_cooperation_from_fair_cooperation() -> None:
    specs = phase_plans("preflight", 200)[0]["specs"]
    assert [spec["layer"] for spec in specs] == ["M0", "M1", "M5", "M5"]
    assert [spec["fee"] for spec in specs] == [0.0, 0.0, 0.0, 95.0]


def test_promotion_matrix_is_exactly_thirty_rows() -> None:
    plans = phase_plans("promote100", 4000)
    assert [plan["seed"] for plan in plans] == [6, 7, 8, 9, 10]
    assert sum(len(plan["specs"]) for plan in plans) == 30


def test_short_gate_budgets_are_intentionally_small() -> None:
    assert default_budget("smoke") == 8
    assert default_budget("preflight") == 200
    assert default_budget("rehearsal") == 400
    assert default_budget("model_gate") == 4000


def test_fee_is_an_in_memory_override_only() -> None:
    prices = prices_for("M5", 95.0)
    assert prices.cross_site_cost == 95.0
    assert DEFAULT_PRICES.cross_site_cost == 0.0
    assert prices.B_battery_kwh == 280.0
    assert prices.initial_ev_battery_kwh == 0.0


def test_score_count_aggregation_does_not_double_count_best_phase() -> None:
    result = {
        "operator_counts": {
            "score_counts": {"candidate": 9},
            "staged_chain": {
                "phase_operator_counts": [
                    {"score_counts": {"candidate": 3, "cross_site_complete_candidates": 1}},
                    {"score_counts": {"candidate": 5, "cross_site_complete_candidates": 2}},
                ]
            },
        }
    }
    assert score_counts(result) == {"candidate": 8, "cross_site_complete_candidates": 3}


def test_fairness_rejection_ledger_reads_the_current_precise_key() -> None:
    assert fairness_rejection_count({"strict_reject_profit_fairness": 73}) == 73
    assert fairness_rejection_count({"strict_reject_fairness": 2}) == 2


def test_cross_depot_repair_forces_one_alternate_depot_when_feasible() -> None:
    nodes = [
        Node("D0", "d", 0, 0, due_time=100_000),
        Node("D1", "d", 10, 0, due_time=100_000),
        Node("C1", "c", 1, 0, demand=10, due_time=100_000),
        Node("C2", "c", 9, 0, demand=10, due_time=100_000),
        Node("C3", "c", 2, 0, demand=10, due_time=100_000),
    ]
    matrix = [[0.0 if i == j else 1_000.0 for j in range(len(nodes))] for i in range(len(nodes))]
    instance = Instance(nodes, matrix)
    partial = Solution(routes=[
        Route("CV0", "cv", "D0", ["D0", "C1", "D0"]),
        Route("CV1", "cv", "D1", ["D1", "C2", "D1"]),
    ])
    context = EvaluationContext(
        instance,
        [],
        customer_home_depot={"C1": "D0", "C2": "D1", "C3": "D0"},
    )
    repaired = repair_removed_customers(
        partial,
        ["C3"],
        context,
        SearchPolicy(),
        mode="cross_depot",
    )
    assert repaired is not None
    assert any(route.home_depot_id == "D1" and "C3" in route.node_sequence for route in repaired.routes)
    assert context.score_counts["cross_depot_forced_insertions"] == 1


def test_cross_depot_operator_is_isolated_to_strict_e3(monkeypatch) -> None:
    monkeypatch.delenv("SETP_E3_STRICT_MULTITRIP", raising=False)
    assert "cross_depot_insert_repair" not in {name for name, _ in WinnerOperatorSet.create().repair_ops}
    assert "cross_depot_boundary_removal" not in {name for name, _ in WinnerOperatorSet.create().destroy_ops}
    monkeypatch.setenv("SETP_E3_STRICT_MULTITRIP", "1")
    assert "cross_depot_insert_repair" in {name for name, _ in WinnerOperatorSet.create().repair_ops}
    assert "cross_depot_boundary_removal" in {name for name, _ in WinnerOperatorSet.create().destroy_ops}
    operators = WinnerOperatorSet.create()
    coupling = _selector_coupling_contract(operators)
    destroy_names = [name for name, _ in operators.destroy_ops]
    repair_names = [name for name, _ in operators.repair_ops]
    destroy_idx = destroy_names.index("cross_depot_boundary_removal")
    repair_idx = repair_names.index("cross_depot_insert_repair")
    assert coupling[destroy_idx, repair_idx]
    assert coupling[:, repair_idx].sum() == 1
    assert coupling[destroy_idx, :].sum() == 1
    context = EvaluationContext(
        Instance(
            [Node("D0", "d", 0, 0), Node("D1", "d", 1, 0), Node("C1", "c", 0, 0)],
            [[0.0, 1.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 0.0]],
        ),
        [],
        budget=EvalBudget(limit=200, target=200),
        customer_home_depot={"C1": "D0"},
    )
    assert _forced_cross_depot_pair(operators, context) == (destroy_idx, repair_idx)
    context.score_counts["cross_depot_forced_operator_calls"] = 1
    assert _forced_cross_depot_pair(operators, context) is None
    context.budget.count = 100
    assert _forced_cross_depot_pair(operators, context) == (destroy_idx, repair_idx)


def test_preflight_cannot_pass_when_cooperation_never_makes_a_legal_move(tmp_path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    plans = [{
        "seed": 1,
        "sizes": ["200c"],
        "specs": [
            {"run_id": "independent", "layer": "M0", "budget": 2},
            {"run_id": "cooperative", "layer": "M1", "budget": 2},
        ],
    }]
    common = {
        "status": "OK",
        "actual_evals": 2,
        "budget": 2,
        "violation_count": 0,
        "cost_component_error": 0.0,
        "fee_override_verified": True,
        "search_cross_site_fee_error": 0.0,
    }
    (runs / "independent.json").write_text(
        json.dumps({**common, "run_id": "independent", "layer": "M0"}),
        encoding="utf-8",
    )
    cooperative = {
        **common,
        "run_id": "cooperative",
        "layer": "M1",
        "cross_site_attempted_candidates": 1,
        "cross_site_legal_candidates": 0,
    }
    cooperative_path = runs / "cooperative.json"
    cooperative_path.write_text(json.dumps(cooperative), encoding="utf-8")
    assert summarize_phase(tmp_path, "preflight", plans)["verdict"] == "HALT_E3_PREFLIGHT"
    cooperative["cross_site_legal_candidates"] = 1
    cooperative_path.write_text(json.dumps(cooperative), encoding="utf-8")
    assert summarize_phase(tmp_path, "preflight", plans)["verdict"] == "E3_PREFLIGHT_PASS"


def test_fair_cooperation_may_reject_unfair_moves_but_must_record_why() -> None:
    row = {
        "cross_site_attempted_candidates": 3,
        "cross_site_legal_candidates": 0,
        "fairness_enabled": True,
        "fairness_search_active_evidence": json.dumps({"rejected_candidates": 3}),
    }
    assert _cooperation_mobility_row_ok(row)
    row["fairness_search_active_evidence"] = json.dumps({"rejected_candidates": 0})
    assert not _cooperation_mobility_row_ok(row)
