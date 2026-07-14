from __future__ import annotations

import json

import pytest

from baselines.e6_fairness.e6_profit_guarantee_frontier_20260715 import (
    guarantee_levels,
    frontier_rows,
    lock_level_contract,
    raw_frontier_rows,
    reuse_alpha0,
    select_specs,
)


def _candidate(
    task_id: str,
    alpha: float,
    cost: float,
    ratio_d0: float,
    ratio_d1: float,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "source_alpha": alpha,
        "alpha": alpha,
        "executed_search": True,
        "reused_from_alpha0": False,
        "evaluations": 4000,
        "total_cost": cost,
        "minimum_profit_ratio": min(ratio_d0, ratio_d1),
        "depot_profit_json": json.dumps({"D0": 100.0 * ratio_d0, "D1": 100.0 * ratio_d1}),
        "profit_ratio_json": json.dumps({"D0": ratio_d0, "D1": ratio_d1}),
        "solution_path": f"solutions/{task_id}.json",
        "solution_sha256": f"solution-{task_id}",
        "certificate_path": f"certificates/{task_id}.json",
        "certificate_sha256": f"certificate-{task_id}",
        "cross_site_customer_count": 1,
        "cost_fix": 10.0,
        "cost_km": 20.0,
        "cost_fuel": 30.0,
        "cost_elec": 40.0,
        "cost_occ": 0.0,
        "cost_transship": 0.0,
        "cost_carbon": 0.0,
    }


def test_guarantee_levels_interpolate_from_mu_to_one() -> None:
    levels = guarantee_levels(0.8)
    assert [row["alpha"] for row in levels] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert [row["formula_theta"] for row in levels] == pytest.approx(
        [0.8, 0.85, 0.9, 0.95, 1.0]
    )
    assert levels[0]["fairness_enabled"] is False
    assert all(row["fairness_enabled"] for row in levels[1:])
    assert all(row["execution_rule"] == "run_constrained" for row in levels[1:])


def test_natural_satisfaction_reuses_alpha_zero_without_search() -> None:
    levels = guarantee_levels(1.03)
    assert all(row["natural_satisfaction"] for row in levels)
    assert levels[0]["execution_rule"] == "run_unrestricted"
    assert all(row["execution_rule"] == "reuse_alpha0" for row in levels[1:])
    assert all(row["effective_theta"] == 1.0 for row in levels[1:])
    assert not any(row["fairness_enabled"] for row in levels)


def test_frontier_selection_is_nested_and_uses_all_computed_candidates() -> None:
    levels = guarantee_levels(0.8)
    raw = [
        _candidate("a0", 0.0, 80.0, 0.8, 1.2),
        _candidate("a25", 0.25, 82.0, 0.86, 1.15),
        _candidate("a50", 0.5, 84.0, 0.91, 1.1),
        _candidate("a75", 0.75, 88.0, 0.96, 1.05),
        _candidate("a100", 1.0, 91.0, 1.01, 1.02),
    ]
    for row, level in zip(raw, levels):
        row.update(
            {
                "formula_theta": level["formula_theta"],
                "effective_theta": level["effective_theta"],
                "natural_satisfaction": False,
            }
        )
    independent = _candidate("independent", -1.0, 100.0, 1.0, 1.0)
    independent["candidate_id"] = "frozen_independent_start"
    independent.pop("task_id")
    group = {
        "spec_id": "N__geographic__seed1",
        "instance": "N",
        "condition": "geographic",
        "seed": 1,
        "status": "PASS",
        "unrestricted_mu": 0.8,
        "natural_satisfaction": False,
        "independent_reference": independent,
        "rows": raw,
    }
    rows = frontier_rows(group)
    assert [row["selected_total_cost"] for row in rows] == [80.0, 82.0, 84.0, 88.0, 91.0]
    assert [row["cost_increment_pct"] for row in rows] == pytest.approx(
        [0.0, 2.5, 5.0, 10.0, 13.75]
    )
    assert all(row["minimum_lower_bound_slack"] >= -1e-9 for row in rows)
    assert [row["selected_source_alpha"] for row in rows] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert [row["selected_source_kind"] for row in rows] == ["level_search"] * 5
    assert [row["candidate_pool_size"] for row in rows] == [6] * 5
    assert [row["total_search_evaluations_exposed"] for row in rows] == [20_000] * 5

    raw_curve = raw_frontier_rows(group)
    assert [row["raw_total_cost"] for row in raw_curve] == [80.0, 82.0, 84.0, 88.0, 91.0]
    assert [row["raw_cost_increment_pct"] for row in raw_curve] == pytest.approx(
        [0.0, 2.5, 5.0, 10.0, 13.75]
    )


def test_natural_frontier_is_exactly_flat() -> None:
    levels = guarantee_levels(1.02)
    raw = []
    alpha0 = _candidate("a0", 0.0, 80.0, 1.02, 1.1)
    for level in levels:
        row = dict(alpha0)
        row.update(
            {
                "task_id": level["alpha_label"],
                "alpha": level["alpha"],
                "formula_theta": level["formula_theta"],
                "effective_theta": level["effective_theta"],
                "natural_satisfaction": True,
                "executed_search": level["alpha"] == 0.0,
                "reused_from_alpha0": level["alpha"] != 0.0,
            }
        )
        raw.append(row)
    independent = _candidate("independent", -1.0, 100.0, 1.0, 1.0)
    independent["candidate_id"] = "frozen_independent_start"
    independent.pop("task_id")
    group = {
        "spec_id": "N__mixed__seed1",
        "instance": "N",
        "condition": "mixed",
        "seed": 1,
        "status": "PASS",
        "unrestricted_mu": 1.02,
        "natural_satisfaction": True,
        "independent_reference": independent,
        "rows": raw,
    }
    rows = frontier_rows(group)
    assert [row["selected_solution_sha256"] for row in rows] == ["solution-a0"] * 5
    assert [row["cost_increment_pct"] for row in rows] == [0.0] * 5
    assert [row["displayed_theta"] for row in rows[1:]] == [1.0] * 4


def test_select_specs_applies_probe_bound_after_filters() -> None:
    specs = [
        {"instance": "N2", "condition": "mixed", "seed": 2},
        {"instance": "N1", "condition": "geographic", "seed": 1},
        {"instance": "N1", "condition": "mixed", "seed": 1},
    ]
    selected = select_specs(
        specs,
        instances={"N1"},
        conditions=set(),
        seeds={1},
        max_specs=1,
    )
    assert selected == [{"instance": "N1", "condition": "geographic", "seed": 1}]

    scaled = [
        {"instance": "L-main-threeshift-100c-01", "condition": "geographic", "seed": 1},
        {"instance": "L-main-threeshift-10c-01", "condition": "geographic", "seed": 1},
    ]
    assert select_specs(
        scaled,
        instances=set(),
        conditions=set(),
        seeds=set(),
        max_specs=1,
    )[0]["instance"] == "L-main-threeshift-10c-01"


def test_reuse_alpha_zero_preserves_solution_and_certificate_identity(tmp_path) -> None:
    alpha0 = {
        **_candidate("a0", 0.0, 80.0, 1.02, 1.1),
        "spec_id": "N__geographic__seed1",
        "alpha_label": "alpha_000",
        "formula_theta": 1.02,
        "effective_theta": None,
        "fairness_enabled": False,
        "natural_satisfaction": True,
        "execution_rule": "run_unrestricted",
        "source_alpha": 0.0,
        "planned_budget": 4000,
        "budget": 4000,
        "evaluations": 4000,
        "elapsed_seconds": 1.0,
        "status": "PASS",
        "contract_sha256": "contract",
        "solution_canonical_sha256": "canonical-a0",
        "certificate_sha256": "certificate-a0",
        "fairness_satisfied": True,
    }
    level = guarantee_levels(1.02)[1]
    reused = reuse_alpha0(alpha0, level, out_dir=tmp_path, contract_sha="contract")
    assert reused["reused_from_alpha0"] is True
    assert reused["executed_search"] is False
    assert reused["planned_budget"] == 4000
    assert reused["budget"] == reused["evaluations"] == 0
    assert reused["source_alpha"] == 0.0
    for field in (
        "solution_path",
        "solution_sha256",
        "solution_canonical_sha256",
        "certificate_path",
        "certificate_sha256",
        "total_cost",
    ):
        assert reused[field] == alpha0[field]


def test_level_contract_is_locked_before_later_searches(tmp_path) -> None:
    alpha0 = {
        "task_id": "N__geographic__seed1__alpha_000",
        "solution_sha256": "solution-alpha0",
        "minimum_profit_ratio": 0.8,
    }
    spec = {"spec_id": "N__geographic__seed1", "input_fingerprint": "input"}
    levels = guarantee_levels(0.8)
    first = lock_level_contract(
        spec,
        alpha0,
        levels,
        out_dir=tmp_path,
        contract_sha="contract",
    )
    second = lock_level_contract(
        spec,
        alpha0,
        levels,
        out_dir=tmp_path,
        contract_sha="contract",
    )
    assert first == second
    changed = guarantee_levels(0.7)
    with pytest.raises(ValueError, match="level contract drifted"):
        lock_level_contract(
            spec,
            alpha0,
            changed,
            out_dir=tmp_path,
            contract_sha="contract",
        )
