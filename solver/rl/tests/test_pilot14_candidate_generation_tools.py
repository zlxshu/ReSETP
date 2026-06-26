from __future__ import annotations

from dr_alns_ppo.pilot14_candidate_generation_tools import (
    REQUIRED_WORKER_NUMPY,
    REQUIRED_WORKER_PYTHON,
    CandidateVariant,
    candidate_row_gate,
    classify_candidate_generator_gate,
    default_candidate_variants,
    render_pilot14_report,
    threeshift_probe_bundles,
)


def _row(
    *,
    bundle_role: str = "train_probe",
    bundle_name: str = "e2-threeshift-50c-01",
    seed: int = 1,
    variant: str = "route_compression_rebuild",
    feasible: bool = True,
    changed: bool = True,
    improving: bool = True,
    relative: float = 1.0,
) -> dict[str, object]:
    return {
        "bundle_role": bundle_role,
        "bundle_name": bundle_name,
        "seed": seed,
        "variant": variant,
        "candidate_count": 1,
        "feasible_candidate_count": 1 if feasible else 0,
        "changed_candidate_count": 1 if changed else 0,
        "improving_candidate_count": 1 if improving else 0,
        "violation_count": 0 if feasible else 1,
        "baseline_obj": 100.0,
        "best_candidate_obj": 100.0 - relative,
        "best_relative_percent": relative,
        "worker_python_executable": REQUIRED_WORKER_PYTHON,
        "worker_numpy_version": REQUIRED_WORKER_NUMPY,
        "actual_evals": 300,
        "eval_budget": 300,
    }


def test_threeshift_probe_bundles_match_goal_instances() -> None:
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
    assert not any("100c" in name for name in names)


def test_default_candidate_variants_cover_literature_backed_families() -> None:
    variants = default_candidate_variants()
    assert variants == [
        CandidateVariant("route_compression_rebuild", "route-compression / route-rebuild"),
        CandidateVariant("stronger_insertion_repair", "criticality / regret-k / wider insertion repair"),
        CandidateVariant("ev_charging_aware_repair", "EV / charging-aware repair"),
    ]


def test_candidate_row_gate_rejects_worker_drift() -> None:
    row = _row()
    row["worker_python_executable"] = "C:/bad/python.exe"
    ok, reason = candidate_row_gate(row)
    assert not ok
    assert "worker" in reason


def test_candidate_row_gate_rejects_numpy_mismatch() -> None:
    row = _row()
    row["worker_numpy_version"] = "1.26.0"
    ok, reason = candidate_row_gate(row)
    assert not ok
    assert "NumPy" in reason


def test_candidate_row_gate_rejects_budget_mismatch() -> None:
    row = _row()
    row["actual_evals"] = 299
    ok, reason = candidate_row_gate(row)
    assert not ok
    assert "actual_evals" in reason


def test_candidate_generator_gate_passes_only_with_train_and_held_headroom() -> None:
    rows: list[dict[str, object]] = []
    bundles = [
        ("train_probe", "e2-threeshift-50c-01"),
        ("train_probe", "e2-threeshift-50c-02"),
        ("train_probe", "e2-threeshift-50c-03"),
        ("held_probe", "e2-threeshift-75c-01"),
        ("held_probe", "e2-threeshift-75c-02"),
        ("held_probe", "e2-threeshift-75c-03"),
    ]
    for role, bundle_name in bundles:
        for seed in (1, 2, 3):
            rows.append(_row(bundle_role=role, bundle_name=bundle_name, seed=seed, relative=0.6))

    gate = classify_candidate_generator_gate(rows)

    assert gate["status"] == "READY_FOR_PPO_INTERFACE"
    assert gate["changed_rate"] == 1.0
    assert gate["improving_rate"] == 1.0
    assert gate["bundle_nonworse_count"] == 6


def test_candidate_generator_gate_halts_when_held_out_mean_is_too_weak() -> None:
    rows: list[dict[str, object]] = []
    for idx in range(3):
        rows.append(_row(bundle_role="train_probe", bundle_name=f"e2-threeshift-50c-0{idx+1}", relative=0.8))
        rows.append(_row(bundle_role="held_probe", bundle_name=f"e2-threeshift-75c-0{idx+1}", relative=0.0))

    gate = classify_candidate_generator_gate(rows)

    assert gate["status"] == "HALT_CANDIDATE_GENERATOR_NO_HEADROOM"
    assert gate["held_mean_relative_percent"] < 0.30


def test_candidate_generator_gate_halts_when_changed_rate_is_too_low() -> None:
    rows = [_row(changed=False, improving=False, relative=0.0) for _ in range(10)]

    gate = classify_candidate_generator_gate(rows)

    assert gate["status"] == "HALT_CANDIDATE_GENERATOR_NO_HEADROOM"
    assert gate["changed_rate"] == 0.0


def test_candidate_generator_gate_rejects_any_infeasible_row() -> None:
    rows = [_row(), _row(feasible=False, changed=True, improving=False, relative=-1.0)]

    gate = classify_candidate_generator_gate(rows)

    assert gate["status"] == "HALT_CANDIDATE_ROW_GATE"
    assert "violation" in gate["failed_row_reasons"][0]


def test_render_pilot14_report_states_ready_or_halt_without_training_claim() -> None:
    report = render_pilot14_report(
        summary={
            "gate": {"status": "HALT_CANDIDATE_GENERATOR_NO_HEADROOM"},
            "rows": [],
            "variant_summary": [],
        }
    )
    assert "Pilot14" in report
    assert "no PPO training" in report
    assert "HALT_CANDIDATE_GENERATOR_NO_HEADROOM" in report

