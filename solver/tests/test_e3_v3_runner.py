from __future__ import annotations

from baselines.e3_ablation.e3_v3_runner import (
    default_budget,
    phase_plans,
    prices_for,
    score_counts,
)
from setp_solver.prices import DEFAULT_PRICES


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
