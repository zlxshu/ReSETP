from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest

import dr_alns_ppo.pilot24_data_generalization as p24
from dr_alns_ppo.pilot21_learned_destroy_big import PASS_STATUS, WEAK_STATUS
from dr_alns_ppo.pilot24_data_generalization import (
    HALT_INSUFFICIENT_DATA,
    HALT_NO_GENERALIZATION,
    HALT_POLICY_UNSTABLE,
    PASS_STAGE0,
    PASS_STAGE1,
    Pilot24Halt,
    build_data_manifest,
    make_split_specs,
    run_stage0,
    summarize_stage0,
    summarize_stage1,
    summarize_stage2,
    validate_data_manifest,
    validate_pilot24_bundle,
    _enforce_resume_guard,
)


def test_make_split_specs_uses_disjoint_seed_ranges_and_excludes_old_base() -> None:
    specs = make_split_specs(
        scale_customers=25,
        train_count=4,
        val_count=3,
        test_count=2,
        train_seed_start=24000,
        val_seed_start=25000,
        test_seed_start=26000,
    )

    train_seeds = {spec.seed for spec in specs["train"]}
    val_seeds = {spec.seed for spec in specs["val"]}
    test_seeds = {spec.seed for spec in specs["test"]}

    assert train_seeds == {24000, 24001, 24002, 24003}
    assert not (train_seeds & val_seeds)
    assert not (train_seeds & test_seeds)
    assert all(spec.base_id != "E-UK25_01" for rows in specs.values() for spec in rows)


def test_data_manifest_requires_complete_non_overlapping_bundles(tmp_path: Path) -> None:
    rows = {
        "train": [_bundle_row(tmp_path, "train_a", "train", seed=1)],
        "val": [_bundle_row(tmp_path, "val_a", "val", seed=2)],
        "test": [_bundle_row(tmp_path, "test_a", "test", seed=3)],
    }

    manifest = build_data_manifest(rows, scale_customers=25)
    validation = validate_data_manifest(manifest)
    stage0 = summarize_stage0(manifest, min_train_count=1)

    assert validation["complete"] is True
    assert validation["overlap"] is False
    assert stage0["gate_status"] == PASS_STAGE0


def test_stage0_halts_on_seed_or_path_overlap(tmp_path: Path) -> None:
    shared = _bundle_row(tmp_path, "shared", "train", seed=7)
    rows = {
        "train": [shared],
        "val": [{**shared, "split": "val"}],
        "test": [_bundle_row(tmp_path, "test_a", "test", seed=8)],
    }
    manifest = build_data_manifest(rows, scale_customers=25)

    summary = summarize_stage0(manifest, min_train_count=1)

    assert summary["gate_status"] == HALT_INSUFFICIENT_DATA
    assert summary["overlap"] is True


def test_stage0_skips_invalid_generated_bundle_and_keeps_sampling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    progress_path = output_dir / "pilot24_progress.log"
    generated_root = tmp_path / "generated"
    args = SimpleNamespace(
        resume=False,
        generated_root=str(generated_root),
        template_manifest=str(tmp_path / "template.json"),
        scale_customers=25,
        train_bundle_count=1,
        val_bundle_count=1,
        test_bundle_count=1,
        train_seed_start=24000,
        val_seed_start=25000,
        test_seed_start=26000,
        stage0_max_attempt_multiplier=3,
    )

    monkeypatch.setattr(p24, "_load_template_config", lambda _path: {})
    monkeypatch.setattr(p24, "build_config_for_spec", lambda _root, _template, _spec: ({}, {}))
    monkeypatch.setattr(p24, "generate_scenario", lambda _config: object())
    monkeypatch.setattr(p24, "write_scenario_bundle", lambda _scenario, bundle_dir, config: Path(bundle_dir).mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(p24, "_missing_bundle_files", lambda _bundle: [])

    def fake_validate(bundle_dir: Path, *, expected_n: int) -> dict[str, object]:
        if "seed24000" in str(bundle_dir):
            raise ValueError("validation did not pass")
        return {"validation": {"customer_count": expected_n, "passed": True}}

    monkeypatch.setattr(p24, "validate_pilot24_bundle", fake_validate)

    manifest = run_stage0(args, output_dir, progress_path)

    assert len(manifest["splits"]["train"]) == 1
    assert manifest["splits"]["train"][0]["seed"] == 24001
    assert manifest["rejected_bundles"][0]["seed"] == 24000


def test_validate_pilot24_bundle_checks_required_files_and_generator_validation(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "bundle", validation_passed=True)

    result = validate_pilot24_bundle(bundle, expected_n=25)

    assert result["validation"]["passed"] is True
    assert result["validation"]["customer_count"] == 25


def test_stage1_gate_requires_fresh_schedule_and_stable_kl(tmp_path: Path) -> None:
    update_rows = [{"policy_loss": 0.1, "value_loss": 1.0, "approx_kl": 0.02, "entropy": 2.0}]
    validation_rows = [
        {"tag": "initial", "validation_gain_pct_vs_initial": 0.0, "validation_zero_violations": True},
        {"tag": "update_0025", "validation_gain_pct_vs_initial": 4.0, "validation_zero_violations": True},
        {"tag": "final", "validation_gain_pct_vs_initial": 4.5, "validation_zero_violations": True},
    ]

    passed = summarize_stage1(
        update_rows,
        validation_rows,
        tmp_path / "best.pt",
        threshold_pct=3.0,
        rollback_tolerance_pct=3.0,
        kl_ok_threshold=0.30,
        recent_count=2,
        train_schedule=["a", "b"],
    )
    reused = summarize_stage1(
        update_rows,
        validation_rows,
        tmp_path / "best.pt",
        threshold_pct=3.0,
        rollback_tolerance_pct=3.0,
        kl_ok_threshold=0.30,
        recent_count=2,
        train_schedule=["a", "a"],
    )
    bad_kl = summarize_stage1(
        [{"policy_loss": 0.1, "value_loss": 1.0, "approx_kl": 0.40, "entropy": 2.0}],
        validation_rows,
        tmp_path / "best.pt",
        threshold_pct=3.0,
        rollback_tolerance_pct=3.0,
        kl_ok_threshold=0.30,
        recent_count=2,
        train_schedule=["a", "b"],
    )

    assert passed["gate_status"] == PASS_STAGE1
    assert reused["gate_status"] != PASS_STAGE1
    assert reused["fresh_no_reuse"] is False
    assert bad_kl["gate_status"] == HALT_POLICY_UNSTABLE


def test_stage2_pass_weak_and_halt_thresholds() -> None:
    passed = summarize_stage2(_comparison_rows(learned=97.0, operator=100.0, random_obj=101.0, worst=102.0), pass_threshold=2.0)
    weak = summarize_stage2(_comparison_rows(learned=99.0, operator=100.0, random_obj=101.0, worst=102.0), pass_threshold=2.0)
    halt = summarize_stage2(_comparison_rows(learned=101.0, operator=100.0, random_obj=102.0, worst=103.0), pass_threshold=2.0)

    assert passed["status"] == PASS_STATUS
    assert weak["status"] == WEAK_STATUS
    assert halt["status"] == HALT_NO_GENERALIZATION


def test_resume_guard_blocks_conclusive_state_but_allows_wall_clock_resume() -> None:
    with pytest.raises(Pilot24Halt, match="HALT_RESUME_GUARD"):
        _enforce_resume_guard({"final_status": HALT_NO_GENERALIZATION}, resume=True)

    _enforce_resume_guard({"final_status": "HALT_WALL_CLOCK"}, resume=True)
    _enforce_resume_guard({"final_status": HALT_NO_GENERALIZATION}, resume=False)


def _bundle_row(tmp_path: Path, name: str, split: str, *, seed: int) -> dict[str, object]:
    bundle = _make_bundle(tmp_path / name, validation_passed=True)
    return {
        "split": split,
        "path": str(bundle),
        "scenario_id": name,
        "base_id": "E-UK25_02",
        "seed": seed,
        "n_customers": 25,
        "validation_passed": True,
    }


def _make_bundle(path: Path, *, validation_passed: bool) -> Path:
    path.mkdir(parents=True)
    for name in ("instance.json", "distance_matrix.npy", "carbon_profile.csv", "nodes.csv"):
        (path / name).write_text("placeholder\n", encoding="utf-8")
    manifest = {
        "schema_version": "setp-scenario-bundle.v1",
        "validation": {
            "passed": validation_passed,
            "customer_count": 25,
            "checks": [],
        },
    }
    (path / "scenario_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _comparison_rows(*, learned: float, operator: float, random_obj: float, worst: float) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for algorithm, value in (
        ("learned_destroy", learned),
        ("operator_select", operator),
        ("random_operator", random_obj),
        ("worst_removal_fixed", worst),
    ):
        rows.append(
            {
                "algorithm": algorithm,
                "bundle": "bundle25",
                "scale": "25c",
                "seed": 901,
                "best_obj": value,
                "violation_count": 0,
                "worker_integrity_ok": True,
            }
        )
    return rows
