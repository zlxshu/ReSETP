import inspect
import re
from pathlib import Path

import pytest

from dr_alns_ppo import diagnose_pilot_failure as diag


def test_phase_audit_detects_fragmentation_risk() -> None:
    audit = diag.audit_phase_fragmentation(
        {"eval_budget": 16000},
        [
            {"requested_timesteps": "3072", "rollout_timesteps": "3072"},
            {"requested_timesteps": "1600", "rollout_timesteps": "3072"},
        ],
    )

    assert audit["phase_timesteps_lt_eval_budget"] is True
    assert audit["episode_fragmentation_risk"] is True
    assert audit["risky_phase_count"] == 2


def test_monitor_audit_distinguishes_zero_normal_and_missing(tmp_path: Path) -> None:
    missing = diag.audit_monitor(tmp_path / "missing.csv")
    zero_path = tmp_path / "zero.csv"
    zero_path.write_text('#{"t_start": 0.0}\nr,l,t,actual_evals\n', encoding="utf-8")
    normal_path = tmp_path / "normal.csv"
    normal_path.write_text('#{"t_start": 0.0}\nr,l,t,actual_evals\n1.0,32,0.1,32\n', encoding="utf-8")

    assert missing["status"] == "missing"
    assert diag.audit_monitor(zero_path)["status"] == "zero_episodes"
    normal = diag.audit_monitor(normal_path)
    assert normal["status"] == "has_episodes"
    assert normal["episode_count"] == 1


def test_action_collapse_classifier_detects_single_dominant_action() -> None:
    rows = [
        {
            "destroy_counts": {"vehicle_type_swap": 100},
            "repair_counts": {"greedy_insert_repair": 100},
            "q_ratio_counts": {"0.166667": 100},
        },
        {
            "destroy_counts": {"vehicle_type_swap": 50},
            "repair_counts": {"greedy_insert_repair": 50},
            "q_ratio_counts": {"0.166667": 50},
        },
    ]

    result = diag.classify_action_collapse(rows, threshold=0.95)

    assert result["collapsed"] is True
    assert result["top_combined_destroy"] == "vehicle_type_swap"
    assert result["top_combined_repair"] == "greedy_insert_repair"
    assert result["top_combined_share"] == pytest.approx(1.0)


def test_investigation_output_path_guard() -> None:
    allowed = diag.ensure_investigation_path(diag.REPORT_DIR / "probe.csv")
    assert str(allowed).endswith("solver/reports/dr_alns_ppo_v2/ppo_failure_investigation/probe.csv")

    with pytest.raises(ValueError, match="diagnostic output path"):
        diag.ensure_investigation_path("solver/reports/dr_alns_ppo_v2/not_investigation/probe.csv")


def test_diagnostic_runner_has_no_formal_runner_calls() -> None:
    source = inspect.getsource(diag)

    assert "formal_runner" not in source
    assert re.search(r"run_e[1-7]", source) is None
