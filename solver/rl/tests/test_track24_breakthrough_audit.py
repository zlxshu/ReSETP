from __future__ import annotations

import pytest

from dr_alns_ppo import track24_breakthrough_audit as track24
from setp_solver.instance_loader import Instance, Node
from setp_solver.search.dynamic import DynamicEvent, RollingParameters, RollingPolicyContext


def _baseline(bundle: str = "b1", seed: int = 1, pct: float = 40.0) -> dict[str, object]:
    return {
        "bundle": bundle,
        "bundle_dir": "models/data_bundle/generated_instances/E-UK25_02__curric_d2_s3_seed2_24h",
        "seed": seed,
        "scale": "25",
        "information_cost_pct": pct,
        "information_cost": 400.0,
        "dynamic_cost": 1400.0,
        "static_revealed_cost": 1000.0,
    }


def _oracle_row(bundle: str, seed: int, action: str, reduction_pp: float) -> dict[str, object]:
    base_pct = 40.0
    return {
        "bundle": bundle,
        "seed": seed,
        "action_id": action,
        "health_status": "HEALTHY",
        "action_real_effect": True,
        "oracle_information_cost_pct": base_pct - reduction_pp,
        "information_cost_reduction_pp": reduction_pp,
    }


def test_stage3_thresholds_use_percentage_points() -> None:
    actions = [{"action_id": "a1"}, {"action_id": "a2"}]
    baselines = [_baseline("b1", 1), _baseline("b2", 2)]
    rows = [
        _oracle_row("b1", 1, "a1", 5.0),
        _oracle_row("b1", 1, "a2", 1.0),
        _oracle_row("b2", 2, "a1", 6.0),
        _oracle_row("b2", 2, "a2", 0.5),
    ]

    summary = track24.summarize_stage3_oracle(baselines, rows, actions, partial=False, reason="")

    assert summary["status"] == track24.STRONG_DYNAMIC_ACTION_SPACE
    assert summary["mean_information_cost_reduction_pp"] == pytest.approx(5.5)


def test_stage3_ignores_metadata_only_actions() -> None:
    actions = [{"action_id": "a1"}]
    baselines = [_baseline("b1", 1)]
    rows = [
        {
            "bundle": "b1",
            "seed": 1,
            "action_id": "a1",
            "health_status": "HEALTHY",
            "action_real_effect": False,
            "information_cost_reduction_pp": 10.0,
        }
    ]

    summary = track24.summarize_stage3_oracle(baselines, rows, actions, partial=False, reason="")

    assert summary["status"] == track24.HALT_DYNAMIC_ACTION_SPACE_FLAT
    assert summary["selected_count"] == 0


def test_stage3_summary_groups_health_failures() -> None:
    actions = [{"action_id": "a1"}, {"action_id": "a2"}]
    baselines = [_baseline("b1", 1)]
    rows = [
        {"bundle": "b1", "seed": 1, "action_id": "a1", "health_status": "HALT_E7_FINAL_CHUNK_CHECK", "payload_path": "p1.json"},
        {"bundle": "b1", "seed": 1, "action_id": "a2", "health_status": "HALT_E7_COMMIT_CHUNK_CHECK", "payload_path": "p2.json"},
    ]

    summary = track24.summarize_stage3_oracle(baselines, rows, actions, partial=False, reason="")

    assert summary["status"] == "HALT_DYNAMIC_ORACLE_HEALTH"
    assert summary["health_failure_groups"] == [
        {"health_status": "HALT_E7_COMMIT_CHUNK_CHECK", "count": 1},
        {"health_status": "HALT_E7_FINAL_CHUNK_CHECK", "count": 1},
    ]
    assert summary["first_health_failure_sample"]["payload_path"] == "p1.json"


def test_stage3_failure_only_mixed_rows_do_not_pass_oracle_gate() -> None:
    actions = [{"action_id": "a1"}]
    baselines = [_baseline("b1", 1)]
    rows = [
        _oracle_row("b1", 1, "a1", 6.0) | {"row_source": "carried_forward_pre_fix", "mixed_code": True},
    ]

    summary = track24.summarize_stage3_oracle(baselines, rows, actions, partial=False, reason="")

    assert summary["status"] == track24.TRACK24R_FAILURE_ONLY_HEALTHY_MIXED_REFERENCE
    assert summary["mixed_code_result"] is True


def test_track24_policy_changes_active_ids_for_capacity_reserve() -> None:
    nodes = [
        Node("D1", "d", 0.0, 0.0),
        Node("C1", "c", 1.0, 0.0, due_time=10_000.0),
        Node("C2", "c", 2.0, 0.0, due_time=20_000.0),
        Node("C3", "c", 3.0, 0.0, due_time=30_000.0),
    ]
    instance = Instance(nodes=nodes, distance_matrix=[[0.0] * len(nodes) for _ in nodes], num_cv=2, num_ev=0)
    context = RollingPolicyContext(
        stage_index=0,
        trigger_time=0.0,
        stage_events=[],
        all_events=[],
        settings=RollingParameters(),
        base_instance=instance,
        effective_instance=instance,
        active_ids={"C1", "C2", "C3"},
        served_customers=set(),
        previous_plan=None,
        previous_instance=None,
    )
    policy = track24.build_track24_dynamic_policy(
        {"action_id": "capacity_reserve_high", "action_class": "depot_capacity_reserve", "level": "high", "fraction": 0.34}
    )

    decision = policy(context)

    assert decision.active_ids is not None
    assert len(decision.active_ids) == 1
    assert decision.metadata["action_effect"] == "active_ids_changed"
    assert decision.metadata["semantic_status"] == "proxy_time_slack_defer_not_real_depot_capacity"


def test_track24_oracle_rows_mark_proxy_semantics() -> None:
    spec = next(item for item in track24.build_stage3_action_specs(100, 10.0) if item["action_id"] == "ev_charging_slack_reserve_low")

    row = track24.oracle_comparison_row(
        _baseline("b1", 1),
        {"status": "completed", "health_status": "HEALTHY", "information_cost_pct": 35.0, "payload_path": "p.json"},
        {"policy_trace": [{"deferred_count": 1, "stage_eval_budget": 100}], "stage_eval_budget": 100},
        spec,
    )

    assert row["action_semantics"] == "proxy_distance_demand_defer_not_soc_slack"
    assert row["proxy_or_true"] == "proxy"


def test_stage4_skips_when_oracle_gate_not_passed(tmp_path) -> None:
    summary = track24.run_stage4(
        object(),
        tmp_path,
        tmp_path / "progress.log",
        {"stage3": {"status": track24.HALT_DYNAMIC_ACTION_SPACE_FLAT}},
    )

    assert summary["status"] == "SKIP_DYNAMIC_IMITATION_ORACLE_GATE"
    assert not summary["trained"]


def test_stage3_summary_reports_proxy_dominant_semantics_block() -> None:
    actions = [
        {"action_id": "capacity_reserve_high", "action_class": "depot_capacity_reserve", "semantic_status": "proxy_time_slack_defer_not_real_depot_capacity"},
    ]
    baselines = [_baseline("b1", 1), _baseline("b2", 2)]
    rows = [
        _oracle_row("b1", 1, "capacity_reserve_high", 7.0)
        | {
            "action_class": "depot_capacity_reserve",
            "action_semantics": "proxy_time_slack_defer_not_real_depot_capacity",
            "proxy_or_true": "proxy",
        },
        _oracle_row("b2", 2, "capacity_reserve_high", 6.0)
        | {
            "action_class": "depot_capacity_reserve",
            "action_semantics": "proxy_time_slack_defer_not_real_depot_capacity",
            "proxy_or_true": "proxy",
        },
    ]

    summary = track24.summarize_stage3_oracle(baselines, rows, actions, partial=False, reason="")

    assert summary["status"] == track24.STRONG_DYNAMIC_ACTION_SPACE
    assert summary["proxy_selected_count"] == 2
    assert summary["ppo_allowed"] is False
    assert summary["decision_status"] == "PPO_BLOCKED_PROXY_DOMINANT"
    assert summary["selected_action_semantics"][0]["proxy_or_true"] == "proxy"


def test_final_decision_blocks_ppo_when_stage3_proxy_dominant() -> None:
    decision = track24.summarize_final_decision(
        {
            "stage3": {
                "status": track24.STRONG_DYNAMIC_ACTION_SPACE,
                "ppo_allowed": False,
                "decision_status": "PPO_BLOCKED_PROXY_DOMINANT",
            }
        }
    )

    assert decision["final_status"] == "PPO_BLOCKED_PROXY_DOMINANT"


def test_stage6_signal_rules() -> None:
    assert (
        track24.summarize_stage6_status(
            [{"feasible": True, "carbon_price_factor": "1", "carbon_cost_share_pct": "8.1", "aware_vs_naive_timing_delta_pct": "2.2"}]
        )
        == track24.CARBON_CHARGING_SIGNAL_REAL
    )
    assert (
        track24.summarize_stage6_status(
            [{"feasible": True, "carbon_price_factor": "10", "carbon_cost_share_pct": "9.0", "aware_vs_naive_timing_delta_pct": "0.0"}]
        )
        == track24.CARBON_CHARGING_SCENARIO_ONLY
    )


def test_final_decision_blocks_old_training_when_oracle_flat() -> None:
    decision = track24.summarize_final_decision(
        {
            "stage3": {"status": track24.HALT_DYNAMIC_ACTION_SPACE_FLAT},
            "stage5": {"status": track24.HALT_FAIRNESS_ACTION_SPACE_FLAT},
            "stage6": {"status": track24.HALT_CARBON_CHARGING_FLAT},
        }
    )

    assert decision["final_status"] == "TRACK24_HALT_NO_MECHANISM_ACTION_HEADROOM"


def test_final_decision_prioritizes_dynamic_oracle_health_halt() -> None:
    decision = track24.summarize_final_decision(
        {
            "stage3": {"status": "HALT_DYNAMIC_ORACLE_HEALTH"},
            "stage5": {"status": "FAIRNESS_SIGNAL_EXPOSED_ORACLE_NOT_RUN"},
            "stage6": {"status": track24.CARBON_CHARGING_SCENARIO_ONLY},
        }
    )

    assert decision["final_status"] == "TRACK24_HALT_DYNAMIC_ORACLE_HEALTH"
