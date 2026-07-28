from __future__ import annotations

from pathlib import Path

from dr_alns_ppo.pilot12_acceptance_stop_tools import (
    acceptance_row_gate,
    classify_acceptance_observability,
    classify_static_headroom,
    IMPLEMENTED_POLICIES,
    load_top_level_eval_bundles,
    paired_relative_percent,
    render_pilot12_report,
    threeshift_probe_bundles,
    unimplemented_policy_rows,
)


def test_paired_relative_percent_positive_means_policy_better() -> None:
    assert paired_relative_percent(policy_cost=90.0, baseline_cost=100.0) == 10.0


def test_acceptance_row_gate_rejects_worker_drift() -> None:
    row = {
        "worker_python_executable": "C:/bad/python.exe",
        "worker_numpy_version": "2.3.5",
        "violation_count": 0,
        "best_obj": 100.0,
        "actual_evals": 600,
        "eval_budget": 600,
        "elapsed_seconds": 1.0,
    }
    ok, reason = acceptance_row_gate(row)
    assert not ok
    assert "worker" in reason


def test_acceptance_row_gate_accepts_valid_budget_row() -> None:
    row = {
        "worker_python_executable": r"C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe",
        "worker_numpy_version": "2.3.5",
        "violation_count": 0,
        "best_obj": 100.0,
        "actual_evals": 600,
        "eval_budget": 600,
        "elapsed_seconds": 1.0,
    }
    assert acceptance_row_gate(row) == (True, "")


def test_observability_gate_passes_when_acceptance_has_variance_and_cost_signal() -> None:
    rows = [
        {
            "bundle_role": "held_out",
            "accepted_rate": 0.10,
            "accepted_worse_rate": 0.01,
            "best_obj": 100.0,
            "policy_label": "best_static_meta",
        },
        {
            "bundle_role": "held_out",
            "accepted_rate": 0.45,
            "accepted_worse_rate": 0.12,
            "best_obj": 96.0,
            "policy_label": "moderate",
        },
        {
            "bundle_role": "held_out",
            "accepted_rate": 0.80,
            "accepted_worse_rate": 0.30,
            "best_obj": 103.0,
            "policy_label": "loose",
        },
    ]
    gate = classify_acceptance_observability(rows)
    assert gate["status"] == "PASS_ACCEPTANCE_OBSERVABLE"


def test_observability_gate_halts_without_acceptance_spread() -> None:
    rows = [
        {
            "bundle_role": "held_out",
            "accepted_rate": 0.20,
            "accepted_worse_rate": 0.01,
            "best_obj": 100.0,
            "policy_label": "best_static_meta",
        },
        {
            "bundle_role": "held_out",
            "accepted_rate": 0.25,
            "accepted_worse_rate": 0.02,
            "best_obj": 99.9,
            "policy_label": "strict",
        },
    ]
    gate = classify_acceptance_observability(rows)
    assert gate["status"] == "HALT_NO_ACCEPTANCE_SIGNAL"


def test_load_top_level_eval_bundles_uses_train_and_held_out_only(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        """
{
  "train": ["train_bundle"],
  "held_out": ["held_bundle"],
  "formal_eval": ["formal_bundle"]
}
""".strip(),
        encoding="utf-8",
    )
    bundles = load_top_level_eval_bundles(manifest)
    assert bundles == [
        {"bundle_role": "train", "bundle_name": "train_bundle", "bundle_path": "train_bundle"},
        {"bundle_role": "held_out", "bundle_name": "held_bundle", "bundle_path": "held_bundle"},
    ]


def test_threeshift_probe_uses_50c_train_and_75c_held_only() -> None:
    bundles = threeshift_probe_bundles()
    names = [row["bundle_name"] for row in bundles]
    assert names == [
        "e2-threeshift-50c-01",
        "e2-threeshift-50c-02",
        "e2-threeshift-50c-03",
        "e2-threeshift-75c-01",
        "e2-threeshift-75c-02",
        "e2-threeshift-75c-03",
    ]
    assert {row["bundle_role"] for row in bundles[:3]} == {"train_probe"}
    assert {row["bundle_role"] for row in bundles[3:]} == {"held_probe"}
    assert not any("100c" in row["bundle_name"] for row in bundles)


def test_unimplemented_stop_policies_are_not_silently_approximated() -> None:
    rows = unimplemented_policy_rows()
    labels = {row["policy_label"] for row in rows}
    assert {"early_stop", "adaptive_stop", "restart_on_stagnation"} <= labels
    assert all(row["status"] == "UNIMPLEMENTABLE_STATIC_POLICY" for row in rows)


def test_implemented_policies_are_threshold_variants_not_stop_approximations() -> None:
    assert set(IMPLEMENTED_POLICIES) == {
        "best_static_meta",
        "strict_accept",
        "loose_accept",
        "very_loose_accept",
    }
    assert "adaptive_stop" not in IMPLEMENTED_POLICIES


def test_static_headroom_gate_passes_on_held_gain_and_train_not_worse() -> None:
    rows = []
    for role, baseline, candidate in (
        ("train_probe", [100.0, 100.0, 100.0, 100.0, 100.0], [100.1, 99.8, 100.0, 99.9, 99.95]),
        ("held_probe", [100.0, 100.0, 100.0, 100.0, 100.0], [99.0, 99.1, 99.2, 100.2, 99.3]),
    ):
        for idx, (base_cost, candidate_cost) in enumerate(zip(baseline, candidate), start=1):
            common = {
                "bundle_role": role,
                "bundle_name": f"{role}-{idx}",
                "seed": idx,
                "worker_python_executable": r"C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe",
                "worker_numpy_version": "2.3.5",
                "violation_count": 0,
                "actual_evals": 600,
                "eval_budget": 600,
                "elapsed_seconds": 1.0,
                "accepted_rate": 0.5,
                "accepted_worse_rate": 0.1,
            }
            rows.append({**common, "policy_label": "best_static_meta", "best_obj": base_cost})
            rows.append({**common, "policy_label": "loose_accept", "best_obj": candidate_cost})
    gate = classify_static_headroom(rows)
    assert gate["status"] == "PASS_ACCEPTANCE_HEADROOM"
    assert gate["best_policy"] == "loose_accept"


def test_render_report_mentions_gate_and_baseline_rule() -> None:
    report = render_pilot12_report(
        rows=[],
        gate={"status": "HALT_NO_ACCEPTANCE_SIGNAL", "reason": "no signal"},
        evidence_items=[
            {
                "source": "example.md",
                "claim": "claim",
                "resetp_implication": "implication",
                "phase": "Phase A",
            }
        ],
    )
    assert "HALT_NO_ACCEPTANCE_SIGNAL" in report
    assert "best static/tuned meta" in report
    assert "three-shift 50c/75c" in report
