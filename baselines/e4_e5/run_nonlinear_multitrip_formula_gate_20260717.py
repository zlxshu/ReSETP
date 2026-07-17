#!/usr/bin/env python3
"""Zero-search mathematical gate for nonlinear multi-trip packing."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import csv
import hashlib
import json
import subprocess

from baselines.e4_e5.nonlinear_charging_replay_20260717 import (
    ChargingCurveError,
    scale_normalized_curve,
)
from baselines.e4_e5.nonlinear_multitrip_prototype_20260717 import (
    inverse_cumulative_time_seconds,
    minimum_departure_energies_kwh,
    pack_trip_chain,
    reachable_energy_kwh,
)


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/e4_e5/nonlinear_multitrip_formula_gate_20260717"
PLAN = ROOT / "docs/handoff/nonlinear_charging_core_upgrade_plan_20260717.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(name: str, payload: Any) -> None:
    (OUT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(name: str, rows: list[dict[str, Any]]) -> None:
    with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    linear = scale_normalized_curve(
        capacity_kwh=280.0,
        soc_breakpoints=(0.0, 1.0),
        relative_powers=(1.0,),
        reference_power_kw=22.0,
    )
    nonlinear = scale_normalized_curve(
        capacity_kwh=10.0,
        soc_breakpoints=(0.0, 0.8, 0.9, 1.0),
        relative_powers=(1.0, 0.5, 0.25),
        reference_power_kw=2.0,
    )
    rows: list[dict[str, Any]] = []
    inverse_errors = []
    for energy in (0.0, 1.25, 8.0, 8.5, 9.0, 9.75, 10.0):
        restored = inverse_cumulative_time_seconds(
            nonlinear, nonlinear.cumulative_time_seconds(energy)
        )
        error = abs(restored - energy)
        inverse_errors.append(error)
        rows.append(
            {
                "check": "inverse_round_trip",
                "case": f"energy={energy}",
                "expected": energy,
                "actual": restored,
                "absolute_error": error,
                "pass": error <= 1e-12,
            }
        )

    linear_required = minimum_departure_energies_kwh(linear, (50.0, 50.0), (3600.0,))
    rows.append(
        {
            "check": "constant_power_degeneracy",
            "case": "two_trips_50kWh_gap1h",
            "expected": "78.0|50.0",
            "actual": "|".join(f"{value:.12g}" for value in linear_required),
            "absolute_error": max(abs(linear_required[0] - 78.0), abs(linear_required[1] - 50.0)),
            "pass": max(abs(linear_required[0] - 78.0), abs(linear_required[1] - 50.0))
            <= 1e-12,
        }
    )
    packed = pack_trip_chain(linear, (50.0, 50.0), (3600.0,))
    packing_error = max(
        abs(packed[0].return_energy_kwh - 28.0),
        abs(packed[0].charge_energy_kwh - 22.0),
        abs(packed[0].charge_duration_seconds - 3600.0),
    )
    rows.append(
        {
            "check": "constant_power_materialization",
            "case": "return_charge_duration",
            "expected": "28.0|22.0|3600.0",
            "actual": (
                f"{packed[0].return_energy_kwh:.12g}|{packed[0].charge_energy_kwh:.12g}|"
                f"{packed[0].charge_duration_seconds:.12g}"
            ),
            "absolute_error": packing_error,
            "pass": packing_error <= 1e-12,
        }
    )

    drives = (3.0, 4.0, 3.0)
    gaps = (1800.0, 3600.0)
    exact = minimum_departure_energies_kwh(nonlinear, drives, gaps)[0]
    step = 0.001
    candidate = drives[0]
    dense_best = None
    while candidate <= nonlinear.capacity_kwh + 1e-12:
        battery = candidate
        feasible = True
        for index, drive in enumerate(drives):
            battery -= drive
            if battery < -1e-12:
                feasible = False
                break
            if index < len(gaps):
                battery = reachable_energy_kwh(nonlinear, max(0.0, battery), gaps[index])
        if feasible:
            dense_best = candidate
            break
        candidate += step
    if dense_best is None:
        raise RuntimeError("dense feasibility scan unexpectedly found no solution")
    dense_error = abs(exact - dense_best)
    rows.append(
        {
            "check": "nonlinear_backward_recursion_dense_scan",
            "case": "drives=3|4|3_gaps=1800|3600",
            "expected": dense_best,
            "actual": exact,
            "absolute_error": dense_error,
            "pass": dense_error <= step + 1e-12,
        }
    )

    infeasible_rejected = False
    try:
        minimum_departure_energies_kwh(nonlinear, (8.0, 8.0), (0.0,))
    except ChargingCurveError:
        infeasible_rejected = True
    rows.append(
        {
            "check": "infeasible_chain_rejected",
            "case": "drives=8|8_gap=0",
            "expected": True,
            "actual": infeasible_rejected,
            "absolute_error": 0.0 if infeasible_rejected else 1.0,
            "pass": infeasible_rejected,
        }
    )
    write_csv("raw_runs.csv", rows)
    passed = all(bool(row["pass"]) for row in rows)
    metadata = {
        "schema": "setp.nonlinear_multitrip_formula_gate.v1",
        "execution_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "search_evaluations": 0,
        "dense_scan_step_kwh": step,
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (
                Path(__file__),
                ROOT / "baselines/e4_e5/nonlinear_multitrip_prototype_20260717.py",
                ROOT / "baselines/e4_e5/nonlinear_charging_replay_20260717.py",
                PLAN,
            )
        },
    }
    decision = {
        "verdict": (
            "PASS_NONLINEAR_MULTITRIP_FORMULA_GATE"
            if passed
            else "HALT_NONLINEAR_MULTITRIP_FORMULA_GATE"
        ),
        "all_checks_pass": passed,
        "check_count": len(rows),
        "maximum_inverse_error_kwh": max(inverse_errors),
        "dense_scan_error_kwh": dense_error,
        "search_evaluations": 0,
        "solver_core_modified": False,
    }
    write_json("metadata.json", metadata)
    write_json("decision.json", decision)
    report = (
        "# 非线性多趟排班数学门\n\n"
        f"判决：`{decision['verdict']}`。本门搜索评价数为0，未导入或修改共享求解器。\n\n"
        f"累计时间逆函数往返最大误差为{max(inverse_errors):.3e} kWh；恒功率两趟递推退化为"
        f"{linear_required}；非线性后向递推与0.001 kWh稠密可行性扫描的误差为"
        f"{dense_error:.3e} kWh。容量不足的趟次链被拒绝，未通过提高电池上限修复。\n"
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")
    artifact_paths = tuple(
        OUT / name
        for name in ("raw_runs.csv", "metadata.json", "decision.json", "report.md")
    )
    write_json(
        "artifact_hashes.json",
        {str(path.relative_to(ROOT)): sha256(path) for path in artifact_paths},
    )
    print(decision["verdict"])
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
