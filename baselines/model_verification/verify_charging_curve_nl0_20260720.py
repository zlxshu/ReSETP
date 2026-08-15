#!/usr/bin/env python3
"""Verify the production charging kernel against all frozen replay actions."""

from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "solver/src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.charging_curve import (  # noqa: E402
    CURVE_SPECS,
    L100_CONTROL,
    curve_from_id,
    half_hour_boundaries,
    slot_energy_kwh,
)


INPUT = (
    ROOT
    / "baselines/e4_e5/nonlinear_charging_robustness_replay_20260717"
    / "action_replay.csv"
)
OUT = (
    ROOT
    / "baselines/model_verification"
    / "china81_nonlinear_core_nl0_20260720"
)
PROTECTED = (
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
    ROOT / "solver/src/setp_solver/prices.py",
    ROOT / "docs/paper_submission_final/RETIRED_paper_main.tex",
)
TOL = 1e-7


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_command(command: list[str], *, env: dict[str, str] | None = None) -> dict[str, object]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    curves = {
        curve_id: curve_from_id(
            curve_id,
            capacity_kwh=280.0,
            reference_power_kw=22.0,
        )
        for curve_id in ("NL90_mild", "NL80_stress")
    }
    boundaries = half_hour_boundaries()
    checked = 0
    feasible = 0
    duration_mismatches = 0
    energy_mismatches = 0
    max_duration_error = 0.0
    max_energy_error = 0.0
    first_failures: list[dict[str, object]] = []

    with INPUT.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            checked += 1
            curve = curves[row["curve"]]
            start_energy = float(row["start_energy_kwh"])
            end_energy = float(row["end_energy_kwh"])
            expected_duration = float(row["nonlinear_duration_second"])
            actual_duration = curve.duration_seconds(start_energy, end_energy)
            duration_error = abs(actual_duration - expected_duration)
            max_duration_error = max(max_duration_error, duration_error)
            if duration_error > TOL:
                duration_mismatches += 1
                if len(first_failures) < 20:
                    first_failures.append(
                        {
                            "kind": "duration",
                            "row": checked,
                            "expected": expected_duration,
                            "actual": actual_duration,
                        }
                    )

            if row["feasible"] != "True":
                continue
            feasible += 1
            start_second = float(row["charge_start_second"])
            expected_energy = float(row["slot_energy_sum_kwh"])
            actual_energy = sum(
                slot_energy_kwh(
                    curve,
                    start_energy_kwh=start_energy,
                    end_energy_kwh=end_energy,
                    charging_start_seconds=start_second,
                    slot_boundaries_seconds=boundaries,
                )
            )
            energy_error = abs(actual_energy - expected_energy)
            max_energy_error = max(max_energy_error, energy_error)
            if energy_error > TOL:
                energy_mismatches += 1
                if len(first_failures) < 20:
                    first_failures.append(
                        {
                            "kind": "energy",
                            "row": checked,
                            "expected": expected_energy,
                            "actual": actual_energy,
                        }
                    )

    linear = L100_CONTROL.scale(
        capacity_kwh=280.0, reference_power_kw=22.0
    )
    linear_grid_failures = 0
    max_linear_error = 0.0
    for start_index in range(0, 28):
        start = start_index * 10.0
        for end_index in range(start_index + 1, 29):
            end = end_index * 10.0
            expected = (end - start) / 22.0 * 3600.0
            error = abs(linear.duration_seconds(start, end) - expected)
            max_linear_error = max(max_linear_error, error)
            linear_grid_failures += error > TOL

    python_env = dict(**__import__("os").environ)
    python_env["PYTHONPATH"] = f"{ROOT / 'solver/src'}:{ROOT}"
    pytest_result = run_command(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "solver/tests/test_charging_curve.py",
            "solver/tests/test_nonlinear_multitrip_prototype_20260717.py",
            "solver/tests/test_nonlinear_charging_replay_20260717.py",
            "solver/tests/test_nonlinear_charging_robustness_runner_20260717.py",
        ],
        env=python_env,
    )
    ruff_result = run_command(
        [
            "/opt/anaconda3/bin/ruff",
            "check",
            "solver/src/setp_solver/charging_curve.py",
            "solver/tests/test_charging_curve.py",
            str(Path(__file__).relative_to(ROOT)),
        ]
    )
    protected_diff = run_command(
        [
            "git",
            "diff",
            "--exit-code",
            "--",
            *(str(path.relative_to(ROOT)) for path in PROTECTED),
        ]
    )

    passed = all(
        (
            checked == 264_600,
            duration_mismatches == 0,
            energy_mismatches == 0,
            linear_grid_failures == 0,
            pytest_result["returncode"] == 0,
            ruff_result["returncode"] == 0,
            protected_diff["returncode"] == 0,
        )
    )
    verdict = (
        "PASS_NL0_PRODUCTION_CHARGING_CURVE_CORE"
        if passed
        else "HALT_NL0_PRODUCTION_CHARGING_CURVE_CORE"
    )
    now = datetime.now(timezone.utc).isoformat()
    summary = {
        "checked_action_rows": checked,
        "feasible_action_rows": feasible,
        "duration_mismatches": duration_mismatches,
        "energy_mismatches": energy_mismatches,
        "max_duration_error_seconds": max_duration_error,
        "max_energy_error_kwh": max_energy_error,
        "linear_grid_failures": linear_grid_failures,
        "max_linear_duration_error_seconds": max_linear_error,
    }
    metadata = {
        "schema": "resetp.charging-curve-nl0-verification.v1",
        "created_at_utc": now,
        "scope": "pure production nonlinear charging curve kernel only",
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "input": str(INPUT.relative_to(ROOT)),
        "input_sha256": file_sha256(INPUT),
        "curve_specs": {
            key: asdict(value) for key, value in CURVE_SPECS.items()
        },
        "protected_hashes": {
            str(path.relative_to(ROOT)): file_sha256(path)
            for path in PROTECTED
        },
    }
    decision = {
        "verdict": verdict,
        "passed": passed,
        **summary,
        "formal_search_allowed": False,
        "next_gate": "NL1_SOLUTION_AND_MULTITRIP_WIRING" if passed else "STOP",
        "honest_boundary": (
            "NL0 proves the pure shared mathematical kernel matches the sealed "
            "replay and constant-power control. It does not yet change solver "
            "physics, authorize China81 search, or prove algorithm performance."
        ),
    }
    raw_rows = [
        {
            "check": "frozen_action_matrix",
            "status": "PASS"
            if duration_mismatches == energy_mismatches == 0
            and checked == 264_600
            else "FAIL",
            "observed": checked,
            "expected": 264_600,
            "detail": json.dumps(summary, sort_keys=True),
        },
        {
            "check": "linear_degeneracy_grid",
            "status": "PASS" if linear_grid_failures == 0 else "FAIL",
            "observed": linear_grid_failures,
            "expected": 0,
            "detail": f"max_error={max_linear_error:.12g}",
        },
        {
            "check": "target_tests",
            "status": "PASS" if pytest_result["returncode"] == 0 else "FAIL",
            "observed": pytest_result["returncode"],
            "expected": 0,
            "detail": str(pytest_result["stdout_tail"]),
        },
        {
            "check": "ruff",
            "status": "PASS" if ruff_result["returncode"] == 0 else "FAIL",
            "observed": ruff_result["returncode"],
            "expected": 0,
            "detail": str(ruff_result["stdout_tail"]),
        },
        {
            "check": "protected_diff",
            "status": "PASS"
            if protected_diff["returncode"] == 0
            else "FAIL",
            "observed": protected_diff["returncode"],
            "expected": 0,
            "detail": str(protected_diff["stdout_tail"]),
        },
    ]

    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=raw_rows[0].keys())
        writer.writeheader()
        writer.writerows(raw_rows)
    (OUT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / "first_failures.json").write_text(
        json.dumps(first_failures, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = (
        "# China81 非线性充电核心 NL0 验证\n\n"
        f"判定：`{verdict}`。\n\n"
        f"逐项读取冻结动作 {checked:,} 行，其中可行动作 {feasible:,} 行。"
        f"持续时间不一致 {duration_mismatches}，分时电量不一致 {energy_mismatches}；"
        f"最大误差分别为 {max_duration_error:.12g} 秒和 "
        f"{max_energy_error:.12g} kWh。恒功率退化网格失败 "
        f"{linear_grid_failures}。\n\n"
        "本门只证明生产级纯数学内核可进入下一批接线；没有修改正式成本、检查、"
        "价格或评价器，没有运行搜索，也不代表 China81 已可验收。\n"
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")

    hash_paths = (
        Path(__file__),
        ROOT / "solver/src/setp_solver/charging_curve.py",
        ROOT / "solver/tests/test_charging_curve.py",
        ROOT / "docs/handoff/china81_nonlinear_core_g1_contract_20260720.md",
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "first_failures.json",
        OUT / "development_incidents.md",
        OUT / "report.md",
    )
    artifact_hashes = {
        str(path.relative_to(ROOT)): file_sha256(path) for path in hash_paths
    }
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(artifact_hashes, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
