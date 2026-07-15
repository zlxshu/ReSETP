from __future__ import annotations

from copy import deepcopy
import json

import pytest

from baselines.e7_dynamic import e7_formal_resumable_runner_20260715 as runner


def _task(condition: str, stream: int, arm: str, evaluations: int = 4, network: str = "N114"):
    return {
        "task_id": runner.task_id(network, condition, stream, arm),
        "network": network,
        "condition": condition,
        "stream": stream,
        "arm": arm,
        "evaluations": evaluations,
        "max_stages": runner.ALL_STAGES_SENTINEL,
    }


def _payload(condition: str, stream: int, arm: str, evaluations: int = 4, network: str = "N114"):
    rows = []
    for stage in (1, 2):
        rows.append(
            {
                "arm": arm,
                "network": network,
                "responsibility_condition": condition,
                "stream_seed": stream,
                "stage": stage,
                "main_evaluations": 1 if arm == "simple_insertion" else evaluations,
                "shadow_evaluations": evaluations,
                "main_search_seed": stream * 100 + stage * 2,
                "shadow_search_seed": stream * 100 + stage * 2 - 1,
                "second_start_sha256": f"start-{stage}",
                "baseline_output_sha256": f"start-{stage}",
                "customer_accounting_pass": True,
                "predicted_charging_saving_kg": 0.25,
                "minimum_profit_margin": 0.0,
                "minimum_profit_ratio": 1.0,
                "cross_site_customer_count": 0 if arm == "no_cooperation" else stage,
                "feasible_cross_candidate_count": 0 if arm == "no_cooperation" else 2,
            }
        )
    return {
        "network": network,
        "arm": arm,
        "responsibility_condition": condition,
        "stream_seed": stream,
        "available_stages": 2,
        "stages": 2,
        "rows": rows,
        "initial_timing": {
            "route_sha256": f"routes-{network}-{condition}-{stream}",
            "energy_sha256": f"energy-{network}-{condition}-{stream}",
            "predicted_charging_saving_kg": 0.1,
        },
        "event_sha256": f"event-{network}-{stream}",
        "owner_sha256": f"owner-{network}-{condition}-{stream}",
        "final_running": {
            "total_revenue": 200.0 + stream,
            "total_cost": 100.0 + stream,
            "total_profit": 100.0,
            "direct_emissions_kg": 40.0,
            "predicted_charging_emissions_kg": 9.0 + stream,
            "actual_charging_emissions_kg": 10.0 + stream,
            "total_actual_emissions_kg": 50.0 + stream,
            "depot_profit": {"D0": 50.0, "D1": 50.0},
        },
        "full_day_execution": {
            "completed_customer_ids": ["C1", "C2"],
            "completed_customer_count": 2,
            "completed_demand": 20.0,
            "cross_site_customer_ids": []
            if arm == "no_cooperation"
            else ["C2"],
            "cross_site_customer_count": 0 if arm == "no_cooperation" else 1,
            "solution_sha256": f"full-day-{network}-{condition}-{stream}-{arm}",
        },
    }


def _matrix(evaluations: int = 4):
    return [
        _payload(condition, stream, arm, evaluations, network)
        for network in runner.NETWORKS
        for condition in runner.CONDITIONS
        for stream in runner.STREAMS
        for arm in runner.ARMS
    ]


def test_contract_resume_accepts_same_scientific_contract_and_rejects_change(
    tmp_path,
) -> None:
    contract = {
        "contract_id": "test",
        "contract_sha256": "abc",
        "evaluations": 4,
    }
    stored = runner.ensure_contract(
        tmp_path, contract, source_commit_at_start="commit-one"
    )
    resumed = runner.ensure_contract(
        tmp_path, contract, source_commit_at_start="commit-two"
    )

    assert stored == resumed
    assert resumed["source_commit_at_start"] == "commit-one"
    with pytest.raises(runner.ContractMismatchError, match="differs"):
        runner.ensure_contract(
            tmp_path,
            {**contract, "evaluations": 8},
            source_commit_at_start="commit-two",
        )


def test_formal_runner_stops_before_compute_without_full_day_probe_capability(
    monkeypatch,
) -> None:
    monkeypatch.delattr(runner.probe, "FULL_DAY_EXECUTION_SCHEMA", raising=False)
    with pytest.raises(runner.FormalRunError, match="full-day merged execution"):
        runner.verify_probe_capability()

    monkeypatch.setattr(
        runner.probe,
        "FULL_DAY_EXECUTION_SCHEMA",
        runner.REQUIRED_PROBE_CAPABILITY,
        raising=False,
    )
    runner.verify_probe_capability()


def test_task_checkpoint_is_atomic_hash_checked_and_resumable(tmp_path) -> None:
    task = _task("geographic", 1, "full")
    payload = _payload("geographic", 1, "full")
    path = tmp_path / ".tasks" / "one.json"

    runner._save_task_checkpoint(path, "contract", task, payload)

    assert not list(path.parent.glob("*.tmp-*"))
    assert runner._load_task_checkpoint(path, "contract", task) == payload
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["stages"] = 1
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(runner.TaskCheckpointError, match="hash differs"):
        runner._load_task_checkpoint(path, "contract", task)


def test_complete_matrix_checks_all_conditions_equal_budget_and_shared_starts() -> None:
    payloads = _matrix()

    assert runner.validate_complete_matrix(payloads, 4) == []

    changed = deepcopy(payloads)
    changed[1]["initial_timing"]["route_sha256"] = "different"
    failures = runner.validate_complete_matrix(changed, 4)
    assert any("share route and energy starts" in failure for failure in failures)


def test_formal_summaries_keep_all_streams_and_use_final_running_ledgers() -> None:
    sessions = runner.build_session_summaries(_matrix())
    groups = runner.build_group_summaries(sessions)

    assert len(sessions) == 120
    assert len(groups) == 24
    geographic_full = next(
        row
        for row in groups
        if row["responsibility_condition"] == "geographic"
        and row["network"] == "N114"
        and row["arm"] == "full"
    )
    assert geographic_full["stream_count"] == 5
    assert geographic_full["full_day_net_profit_mean"] == pytest.approx(100.0)
    assert geographic_full["full_day_actual_total_emissions_kg_mean"] == pytest.approx(
        53.0
    )
    assert geographic_full["full_day_cross_site_customer_count_sum"] == 5


def test_policy_comparisons_are_paired_within_condition_and_stream() -> None:
    sessions = runner.build_session_summaries(_matrix())
    comparisons = runner.build_policy_comparisons(sessions)

    assert len(comparisons) == 30
    row = next(
        item
        for item in comparisons
        if item["responsibility_condition"] == "historical_mixed"
        and item["network"] == "N114"
        and item["stream_seed"] == 3
    )
    assert row["full_minus_no_cooperation_net_profit"] == pytest.approx(0.0)
    assert row["simple_insertion_minus_full_actual_total_emissions_kg"] == pytest.approx(
        0.0
    )
    assert row["full_day_participation_floor_met"] is True


def test_final_evidence_writes_complete_inventory_and_is_reopenable(tmp_path) -> None:
    contract = {
        "contract_sha256": "formal-test-contract",
        "source_commit_at_start": "test-commit",
        "physical_rules": {},
        "input_file_hashes": {},
        "source_file_hashes": {},
    }

    decision = runner.write_final_evidence(
        tmp_path,
        contract,
        _matrix(),
        evaluations=4,
        workers=6,
        started_at_utc="2026-07-15T00:00:00+00:00",
        elapsed_seconds=1.0,
    )

    assert decision["verdict"] == "E7_FORMAL_EVIDENCE_COMPLETE"
    assert (tmp_path / "raw_runs.csv").is_file()
    assert (tmp_path / "paired_policy_comparisons.csv").is_file()
    assert (tmp_path / "RUN_FINISHED.json").is_file()
    assert runner.verify_completed_output(
        tmp_path, "formal-test-contract"
    ) == decision


def test_predicted_emissions_worsening_stops_one_task() -> None:
    task = _task("historical_mixed", 2, "full")
    payload = _payload("historical_mixed", 2, "full")
    payload["rows"][0]["predicted_charging_saving_kg"] = -0.01

    failures = runner.validate_task_payload(task, payload)

    assert any("predicted charging emissions worsened" in item for item in failures)
