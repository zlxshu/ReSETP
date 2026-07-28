from __future__ import annotations

import argparse

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


def test_stage_c_parity_accepts_24d_dr_algorithm() -> None:
    rows = [
        _parity_row("b1", "ppo_block_best_24d", 101.0),
        _parity_row("b1", "alpha_ucb_block", 100.0),
        _parity_row("b1", "best_static_meta", 102.0),
        _parity_row("b1", "official_winner_kernel", 103.0),
    ]

    summary = track23.summarize_stage_c_parity(rows)

    assert summary["status"] == track23.NO_TUNING_PARITY_CLEAN
    assert summary["bundle_rows"][0]["strongest_non_dr_algorithm"] == "alpha_ucb_block"


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


def test_stage_error_does_not_block_later_stages(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(track23.track22, "run_preflight", lambda args, output_dir: {"status": "OK"})

    def boom(*args, **kwargs):
        raise RuntimeError("fake stage c failure")

    monkeypatch.setattr(track23, "run_stage_c_parity", boom)
    monkeypatch.setattr(
        track23,
        "run_stage_d_dynamic",
        lambda *args, **kwargs: {"status": track23.HEURISTIC_FLAT, "reason": "fake flat"},
    )
    args = argparse.Namespace(
        output_dir=str(tmp_path),
        worker_python="C:/fake/python.exe",
        resume=False,
        stages="C,D,E",
    )

    exit_code = track23.run(args)
    state = track23.track22._load_json(tmp_path / "track23_final_report.json")

    assert exit_code == 0
    assert state["stage_c"]["status"] == track23.STAGE_ERROR
    assert state["stage_d"]["status"] == track23.HEURISTIC_FLAT
    assert state["final_status"] == "TRACK23_COMPLETE_WITH_STAGE_ERRORS"


def test_stage_b_existing_summary_can_add_knob_table(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"stage_b": {"status": "CARBON_MECHANISM_WEAK", "reason": "kept"}}
    monkeypatch.setattr(
        track23,
        "build_carbon_knob_table",
        lambda *args, **kwargs: [
            {
                "ev_vehicle_factor": 1.0,
                "carbon_price_factor": 1.0,
                "carbon_intensity_amplitude_factor": 1.0,
                "carbon_cost_share_pct": 2.5,
            }
        ],
    )

    summary = track23.ensure_stage_b_carbon_knobs(
        argparse.Namespace(),
        tmp_path,
        tmp_path / "progress.log",
        state,
    )

    assert summary["status"] == "CARBON_MECHANISM_WEAK"
    assert summary["scenario_knob_rows"] == 1
    assert (tmp_path / "stage_b_carbon_scenario_knobs.csv").is_file()
    assert (tmp_path / "stage_b_carbon_scenario_knobs_summary.json").is_file()


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


def test_pilot16_sidecar_does_not_override_stage_c_pillar() -> None:
    pillars = track23.summarize_pillars(
        {
            "stage_c": {
                "status": track23.NO_TUNING_PARITY_CLEAN,
                "pilot16_reval": {"status": "PILOT16_CLEAN_REVAL_COMPLETE", "min_gap_pct_vs_strongest_non_dr": -99.0},
            }
        }
    )

    assert pillars["DR_PILLAR_QUALITY"] == "站住"


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
