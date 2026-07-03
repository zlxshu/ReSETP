from __future__ import annotations

import pytest

from dr_alns_ppo import final_track20
from dr_alns_ppo import track23_standing as track23
from setp_solver.instance_loader import Instance, Node
from setp_solver.search.dynamic import DynamicEvent, RollingParameters, RollingPolicyContext


def _stage_a_row(
    algorithm: str,
    *,
    bundle: str = "models/data_bundle/generated_instances/E-UK25_11",
    seed: int = 1201,
    best_obj: float = 100.0,
    budget_steps: int = 250,
) -> dict[str, object]:
    return track23.annotate_stage_a_budget(
        {
            "algorithm": algorithm,
            "bundle": bundle,
            "scale": "25c",
            "seed": seed,
            "best_obj": best_obj,
            "actual_evals": budget_steps,
            "wall_time_seconds": 2.0,
            "worker_integrity_ok": True,
            "violation_count": 0,
            "budget_steps": budget_steps,
            "budget_label": f"25c_{budget_steps}",
            "evidence_role": "DESTROY_LEVERAGE_GATE",
        }
    )


def _parity_row(bundle: str, algorithm: str, best_obj: float, *, seed: int = 1) -> dict[str, object]:
    return {
        "bundle": bundle,
        "algorithm": algorithm,
        "seed": seed,
        "best_obj": best_obj,
        "actual_evals": 3000,
        "eval_budget": 3000,
        "violation_count": 0,
    }


def test_stage_a_budget_uses_or_gate() -> None:
    row = track23.annotate_stage_a_budget(
        {
            "scale": "25c",
            "budget_steps": 250,
            "actual_evals": 250,
            "wall_time_seconds": 1.0,
        }
    )

    assert row["budget_status"] == "OK"
    assert row["eval_floor"] == 250
    assert float(row["wall_floor_ratio"]) < 1.0


def test_stage_a_ladder_verdict_uses_max_budget_cell() -> None:
    rows = [
        _stage_a_row("operator_select", seed=1, best_obj=100.0),
        _stage_a_row("best_of_k_destroy", seed=1, best_obj=96.0),
        _stage_a_row("worst_removal_fixed", seed=1, best_obj=101.0),
        _stage_a_row("operator_select", seed=2, best_obj=100.0),
        _stage_a_row("best_of_k_destroy", seed=2, best_obj=97.0),
        _stage_a_row("worst_removal_fixed", seed=2, best_obj=101.0),
    ]

    summary = track23.summarize_stage_a_destroy(rows)

    assert summary["status"] == track23.DESTROY_LEVERAGE_AT_BUDGET
    assert summary["max_headroom_pct"] == pytest.approx(3.5)
    assert track23.should_run_stage_a2(summary)


def test_stage_a_no_leverage_skips_a2() -> None:
    rows = [
        _stage_a_row("operator_select", seed=1, best_obj=100.0),
        _stage_a_row("best_of_k_destroy", seed=1, best_obj=99.5),
        _stage_a_row("worst_removal_fixed", seed=1, best_obj=101.0),
    ]

    summary = track23.summarize_stage_a_destroy(rows)

    assert summary["status"] == track23.NO_DESTROY_LEVERAGE_ANY_BUDGET
    assert not track23.should_run_stage_a2(summary)


def test_stage_c_parity_rule_allows_two_percent_floor() -> None:
    rows = [
        _parity_row("b1", "ppo_block_best", 101.0),
        _parity_row("b1", "alpha_ucb_block", 100.0),
        _parity_row("b1", "best_static_meta", 102.0),
        _parity_row("b1", "official_winner_kernel", 103.0),
    ]

    summary = track23.summarize_stage_c_parity(rows)

    assert summary["status"] == track23.NO_TUNING_PARITY_CLEAN
    assert summary["min_gap_pct_vs_strongest_non_dr"] == pytest.approx(-1.0)


def test_stage_c_parity_lost_below_two_percent_floor() -> None:
    rows = [
        _parity_row("b1", "ppo_block_best", 103.0),
        _parity_row("b1", "alpha_ucb_block", 100.0),
        _parity_row("b1", "best_static_meta", 102.0),
        _parity_row("b1", "official_winner_kernel", 104.0),
    ]

    summary = track23.summarize_stage_c_parity(rows)

    assert summary["status"] == track23.PARITY_LOST_CLEAN
    assert summary["min_gap_pct_vs_strongest_non_dr"] == pytest.approx(-3.0)


def test_stage_d_summary_headroom_and_heuristic_rules() -> None:
    no_headroom = track23.summarize_stage_d_dynamic({"mean_information_cost_pct": 4.9}, [])
    assert no_headroom["status"] == track23.NO_ANTICIPATION_HEADROOM_CLEAN

    moved = track23.summarize_stage_d_dynamic(
        {"mean_information_cost_pct": 10.0},
        [{"rows": [{"myopic_information_cost_pct": 10.0, "heuristic_information_cost_pct": 7.5}]}],
    )
    assert moved["status"] == track23.HEURISTIC_MOVES_HEADROOM

    partial = track23.summarize_stage_d_dynamic(
        {"mean_information_cost_pct": 10.0},
        [{"verdict": "HALT_MYOPIC_CALLBACK_REGRESSION", "rows": []}],
    )
    assert partial["status"] == track23.DYNAMIC_INTERFACE_PARTIAL


def test_pillar_triple_uses_only_required_labels() -> None:
    pillars = track23.summarize_pillars(
        {
            "stage_a": {"status": track23.NO_DESTROY_LEVERAGE_ANY_BUDGET},
            "stage_c": {"status": track23.NO_TUNING_PARITY_CLEAN},
            "stage_d": {"status": track23.HEURISTIC_FLAT},
        }
    )

    assert pillars == {
        "DR_PILLAR_QUALITY": "站住",
        "DR_PILLAR_EFFICIENCY": "没站住",
        "DR_PILLAR_DYNAMIC": "没站住",
    }


def test_preposition_policy_returns_real_initial_plan() -> None:
    nodes = [
        Node("D1", "d", 0.0, 0.0),
        Node("D2", "d", 100.0, 100.0),
        Node("C1", "c", 10.0, 0.0, due_time=10_000.0),
        Node("C2", "c", 20.0, 0.0, due_time=10_000.0),
    ]
    instance = Instance(nodes=nodes, distance_matrix=[[0.0] * len(nodes) for _ in nodes], num_cv=2, num_ev=0)
    future_add = DynamicEvent(
        event_id="e1",
        event_type="add",
        t_appear=100.0,
        customer_id="C3",
        old_demand=0.0,
        new_demand=1.0,
        x=95.0,
        y=95.0,
    )
    context = RollingPolicyContext(
        stage_index=1,
        trigger_time=0.0,
        stage_events=[],
        all_events=[future_add],
        settings=RollingParameters(),
        base_instance=instance,
        effective_instance=instance,
        active_ids={"C1", "C2"},
        served_customers=set(),
        previous_plan=None,
        previous_instance=None,
    )

    policy = final_track20.build_reserve_defer_policy(mode="preposition", reserve_fraction=0.2, min_slack_seconds=0.0)
    decision = policy(context)

    assert decision.initial_plan is not None
    assert decision.metadata["action"] == "preposition_initial_plan"
    assert decision.metadata["preposition_depot_id"] == "D2"
    assert decision.initial_plan.routes
