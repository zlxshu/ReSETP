from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from dr_alns_ppo import pilot07_tools as tools


def test_build_pilot_manifest_has_no_formal_leak() -> None:
    manifest = tools.build_pilot_manifest()

    assert manifest["train"] == [tools.PILOT07_TRAIN]
    assert manifest["held_out"] == [tools.PILOT07_HELD_OUT]
    assert manifest["formal_eval"] == [tools.PILOT07_FORMAL]
    assert "E-UK100_01" not in ",".join(manifest["train"])


def test_calibration_summary_selects_largest_safe_budget(tmp_path: Path) -> None:
    fast_small = _calibration_dir(
        tmp_path / "budget1500_block64",
        eval_budget=1500,
        block_size=64,
        num_actors=8,
        episodes_per_hour=70.0,
        memory_mb=9000.0,
    )
    fast_large = _calibration_dir(
        tmp_path / "budget3000_block64",
        eval_budget=3000,
        block_size=64,
        num_actors=8,
        episodes_per_hour=40.0,
        memory_mb=9500.0,
    )
    unsafe = _calibration_dir(
        tmp_path / "budget3000_block32",
        eval_budget=3000,
        block_size=32,
        num_actors=8,
        episodes_per_hour=60.0,
        memory_mb=13000.0,
    )

    summary = tools.calibration_summary(
        [fast_small, fast_large, unsafe],
        output_dir=tmp_path / "out",
        projection_hours=3.0,
    )

    assert summary["status"] == "CALIBRATION_OK"
    assert summary["selected"]["eval_budget"] == 3000
    assert summary["selected"]["block_size"] == 64


def test_integrity_summary_flags_worker_and_budget() -> None:
    rows = [
        _row(
            "ppo_block",
            tools.PILOT07_TRAIN,
            1,
            eval_budget=3000,
            actual_evals=2999,
            worker="C:/wrong/python.exe",
        )
    ]

    summary = tools.integrity_summary(rows, required_worker=tools.DEFAULT_WORKER)

    assert not summary["ok"]
    assert summary["worker_mismatches"]
    assert summary["budget_mismatches"]


def test_paired_relative_rows_uses_baseline_minus_ppo_percent() -> None:
    rows = [
        _row("ppo_block", tools.PILOT07_TRAIN, 1, best_obj=90.0),
        _row("alpha_ucb_block", tools.PILOT07_TRAIN, 1, best_obj=100.0),
        _row("ppo_block", tools.PILOT07_TRAIN, 2, best_obj=105.0),
        _row("alpha_ucb_block", tools.PILOT07_TRAIN, 2, best_obj=100.0),
    ]

    paired = tools.paired_relative_rows(rows, left="ppo_block")

    alpha = next(row for row in paired if row["baseline_algorithm"] == "alpha_ucb_block")
    assert alpha["paired_n"] == 2
    assert alpha["mean_relative_pct"] == pytest.approx(2.5)


def test_summarize_pilot_writes_verdict_outputs(tmp_path: Path) -> None:
    final_rows = [
        _row("ppo_block", tools.PILOT07_TRAIN, 1, best_obj=90.0),
        _row("alpha_ucb_block", tools.PILOT07_TRAIN, 1, best_obj=100.0),
        _row("random_block", tools.PILOT07_TRAIN, 1, best_obj=120.0),
        _row("ppo_block", tools.PILOT07_FORMAL, 1, best_obj=95.0),
        _row("alpha_ucb_block", tools.PILOT07_FORMAL, 1, best_obj=100.0),
        _row("random_block", tools.PILOT07_FORMAL, 1, best_obj=130.0),
    ]
    sa_rows = [
        _row("scikit-opt-SA", tools.PILOT07_TRAIN, 1, best_obj=115.0),
        _row("scikit-opt-SA", tools.PILOT07_FORMAL, 1, best_obj=125.0),
    ]
    final_csv = tmp_path / "final.csv"
    sa_csv = tmp_path / "sa.csv"
    _write_rows(final_csv, final_rows)
    _write_rows(sa_csv, sa_rows)
    train_log = tmp_path / "async_episode_log.csv"
    _write_episode_log(train_log)

    summary = tools.summarize_pilot(
        final_comparison=final_csv,
        sa_comparison=sa_csv,
        output_dir=tmp_path / "out",
        train_log=train_log,
    )

    assert summary["verdict"] == "PROMISING"
    assert (tmp_path / "out" / "pilot07_report.md").is_file()
    assert (tmp_path / "out" / "pilot07_paired_relative.csv").is_file()


def _calibration_dir(
    path: Path,
    *,
    eval_budget: int,
    block_size: int,
    num_actors: int,
    episodes_per_hour: float,
    memory_mb: float,
) -> Path:
    path.mkdir(parents=True)
    (path / "async_train_summary.json").write_text(json.dumps({"train_wall_time_seconds": 60.0}), encoding="utf-8")
    with (path / "async_episode_log.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "actual_evals",
                "block_steps",
                "violation_count",
                "worker_python_executable",
                "worker_numpy_version",
            ],
        )
        writer.writeheader()
        for _ in range(4):
            writer.writerow(
                {
                    "actual_evals": eval_budget,
                    "block_steps": block_size,
                    "violation_count": 0,
                    "worker_python_executable": tools.DEFAULT_WORKER,
                    "worker_numpy_version": tools.REQUIRED_NUMPY,
                }
            )
    with (path / "worker_throughput.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["num_actors", "episodes_per_hour"])
        writer.writeheader()
        writer.writerow({"num_actors": num_actors, "episodes_per_hour": episodes_per_hour})
    with (path / "cpu_probe.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["system_memory_used_mb", "total_worker_rss_mb"])
        writer.writeheader()
        writer.writerow({"system_memory_used_mb": memory_mb, "total_worker_rss_mb": 500.0})
    return path


def _row(
    algorithm: str,
    bundle: str,
    seed: int,
    *,
    best_obj: float = 100.0,
    eval_budget: int = 3000,
    actual_evals: int = 3000,
    worker: str = tools.DEFAULT_WORKER,
) -> dict:
    return {
        "algorithm": algorithm,
        "bundle": bundle,
        "seed": seed,
        "eval_budget": eval_budget,
        "best_obj": best_obj,
        "actual_evals": actual_evals,
        "candidate_scores": actual_evals,
        "repair_delta_count": 0,
        "operator_base_id": "winner_kernel_v1",
        "control_mode": "test",
        "violation_count": 0,
        "feasible": True,
        "solution_signature_hash": f"sig-{algorithm}-{seed}",
        "operator_counts": {},
        "destroy_counts": {},
        "repair_counts": {},
        "q_ratio_counts": {},
        "worker_python_executable": worker,
        "worker_python_version": "3.13",
        "worker_numpy_version": tools.REQUIRED_NUMPY,
    }


def _write_rows(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tools.RESULT_COLUMNS)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["feasible"] = int(bool(out["feasible"]))
            for key in ("operator_counts", "destroy_counts", "repair_counts", "q_ratio_counts"):
                out[key] = json.dumps(out[key])
            writer.writerow(out)


def _write_episode_log(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["curriculum_phase", "reward_sum", "reward_finite", "violation_count"])
        writer.writeheader()
        writer.writerow({"curriculum_phase": "route", "reward_sum": 1.0, "reward_finite": 1, "violation_count": 0})
        writer.writerow({"curriculum_phase": "energy", "reward_sum": 2.0, "reward_finite": 1, "violation_count": 0})
        writer.writerow({"curriculum_phase": "carbon", "reward_sum": 3.0, "reward_finite": 1, "violation_count": 0})
