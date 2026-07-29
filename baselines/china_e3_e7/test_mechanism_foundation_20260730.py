from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "solver/src"))

from baselines.china_e3_e7.mechanism_foundation import (
    CANDIDATE_CASE_PLAN,
    blind_search_convergence,
    search_convergence,
    select_participation_safe_candidate,
    select_result_blind_budget,
)


def test_case_plan_uses_only_three_instances() -> None:
    assert set().union(*map(set, CANDIDATE_CASE_PLAN.values())) == {
        "cn-prd-50c-01-V2-LOCATIONS",
        "cn-prd-100c-02-V2-LOCATIONS",
        "cn-prd-150c-01-V2-LOCATIONS",
    }


def test_search_convergence_excludes_terminal_closure() -> None:
    trace = [
        {"source": "search", "complete_objective": 10.0},
        {"source": "search", "complete_objective": 9.0},
        {"source": "search", "complete_objective": 9.0},
        {"source": "route_pool_candidate_or_parent", "complete_objective": 8.0},
        {"source": "final_independent_certificate", "complete_objective": 8.0},
    ]
    result = search_convergence(trace)
    assert result["search_candidate_evaluations_S"] == 3
    assert result["last_search_improvement_evaluation_L"] == 2
    assert result["terminal_closure_evaluations"] == 2


def test_search_convergence_rejects_unknown_closure() -> None:
    with pytest.raises(ValueError, match="unexpected terminal closure"):
        search_convergence(
            [
                {"source": "search", "complete_objective": 1.0},
                {"source": "other", "complete_objective": 1.0},
                {"source": "final_independent_certificate", "complete_objective": 1.0},
            ]
        )


def test_blind_search_convergence_does_not_read_objectives() -> None:
    result = blind_search_convergence([1, 0, 1, 0, 1])
    assert result["search_candidate_evaluations_S"] == 3
    assert result["last_search_improvement_evaluation_L"] == 3
    assert result["search_starved_L_over_S_gt_0_5"] is True


def test_budget_selection_requires_every_arm_to_pass() -> None:
    rows = [
        {"arm": arm, "budget": 32, "search_starved_L_over_S_gt_0_5": starved}
        for arm in ("A", "B")
        for starved in (False, False, arm == "B")
    ]
    result = select_result_blind_budget(rows, expected_units_by_arm={"A": 3, "B": 3})
    assert result["status"] == "NEEDS_HIGHER_BUDGET"
    assert result["arm_minimum_passing_budget"] == {"A": 32}


def test_participation_selection_keeps_independent_fallback() -> None:
    candidates = [
        {"solution_sha256": "u", "objective": 90.0, "accounting_residual": 0.0, "profit_values": {"D1": 11.0, "D2": 9.0}},
        {"solution_sha256": "i", "objective": 100.0, "accounting_residual": 0.0, "profit_values": {"D1": 10.0, "D2": 10.0}},
    ]
    selected = select_participation_safe_candidate(candidates, independent_profit={"D1": 10.0, "D2": 10.0})
    assert selected["solution_sha256"] == "i"
