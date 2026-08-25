#!/usr/bin/env python3
"""Run the 2026-08-19 cumulative private ablation serially."""

from __future__ import annotations

import csv
import json
import os
import statistics
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
REPORT_ROOT = REPO / "solver/reports/ablation_20260819"
PYTHON = REPO / "build/python_envs/setp-independent-hgs/bin/python"
RUNNER = REPO / "solver/scripts/run_problem_hgs_private_technical.py"
INSTANCE = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
SEEDS = (1, 2, 3)
RUNTIME_SECONDS = 600
MECHANISMS = ("cross_depot", "multi_trip", "type_exchange", "charge_timing")
ARMS = (
    ("A0", "路线基准", ()),
    ("A1", "+跨场协同", ("cross_depot",)),
    ("A2", "+实体车多趟", ("cross_depot", "multi_trip")),
    ("A3", "+整车换型", ("cross_depot", "multi_trip", "type_exchange")),
    ("A4", "+时变碳充电", MECHANISMS),
)


@dataclass(frozen=True)
class Unit:
    arm: str
    label: str
    enabled: tuple[str, ...]
    seed: int

    @property
    def output(self) -> Path:
        return REPORT_ROOT / "units" / self.arm / f"seed_{self.seed}"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def accepted(output: Path) -> bool:
    try:
        return json.loads((output / "decision.json").read_text())["accepted"] is True
    except (FileNotFoundError, KeyError, json.JSONDecodeError, TypeError):
        return False


def command(unit: Unit) -> list[str]:
    disabled = ",".join(name for name in MECHANISMS if name not in unit.enabled)
    argv = [
        str(PYTHON), str(RUNNER), str(unit.output.relative_to(REPO)),
        "--instance-id", INSTANCE, "--seed", str(unit.seed),
        "--carbon-price", "0.20", "--iterations", "1000000000",
        "--max-runtime-seconds", str(RUNTIME_SECONDS),
        "--stagnation-patience", "500",
        "--fleet-parameter-class", "endogenous", "--population-mode", "copied_hgs_defaults",
        "--trajectory", "off",
        "--charge-timing-policy", "cost_plus_carbon", "--arm", f"ablation_{unit.arm}",
        "--stderr-capture-state", "combined_stdout_stderr_in_unit_log",
    ]
    if disabled:
        argv += ["--mechanism-off", disabled]
    return argv


def environment() -> dict[str, str]:
    env = os.environ.copy()
    required = "solver/src:models/src:third_party/setp_hgs_kernel:."
    env["PYTHONPATH"] = f"{required}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else required
    return env


def failure_package(unit: Unit, returncode: int, reason: str) -> None:
    unit.output.mkdir(parents=True, exist_ok=True)
    payloads = {
        "decision.json": {"accepted": False, "failure_reason": reason},
        "metadata.json": {"status": "FAILED", "arm": unit.arm, "seed": unit.seed, "returncode": returncode},
    }
    for name, payload in payloads.items():
        path = unit.output / name
        if not path.exists():
            path.write_text(json.dumps(payload, indent=2) + "\n")
    raw = unit.output / "raw_runs.csv"
    if not raw.exists():
        raw.write_text(f"arm,seed,accepted,returncode,failure_reason\n{unit.arm},{unit.seed},False,{returncode},{json.dumps(reason)}\n")
    report = unit.output / "report.md"
    if not report.exists():
        report.write_text(f"# Failed unit\n\n- Arm: {unit.arm}\n- Seed: {unit.seed}\n- Reason: {reason}\n")


def run_unit(unit: Unit) -> dict[str, object]:
    if unit.output.exists():
        return {"arm": unit.arm, "seed": unit.seed, "ok": False, "returncode": -3, "reason": "output already exists"}
    log_path = REPORT_ROOT / "unit_logs" / f"{unit.arm}_seed_{unit.seed}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        completed = subprocess.run(command(unit), cwd=REPO, env=environment(), stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, check=False)
    reason = None
    if completed.returncode != 0 or not accepted(unit.output):
        reason = f"runner returncode={completed.returncode}, accepted={accepted(unit.output)}"
    if reason is not None:
        failure_package(unit, completed.returncode, reason)
    return {"arm": unit.arm, "seed": unit.seed, "ok": reason is None,
            "returncode": completed.returncode, "reason": reason}


def read_unit_row(unit: Unit) -> dict[str, object]:
    with (unit.output / "raw_runs.csv").open(newline="") as handle:
        row = next(csv.DictReader(handle))
    metadata = json.loads((unit.output / "metadata.json").read_text())
    accounting = metadata.get("accounting", {})
    return {**row, "arm": unit.arm, "seed": unit.seed,
            "arm_label": unit.label, "added_component": unit.label,
            "enabled_mechanisms": ";".join(unit.enabled),
            "total_algorithm_wall_seconds": accounting.get(
                "total_algorithm_wall_seconds", row.get("run_wall_seconds", ""))}


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def aggregate(units: list[Unit], results: list[dict[str, object]]) -> None:
    raw_rows = [read_unit_row(unit) for unit in units if (unit.output / "raw_runs.csv").exists()]
    write_csv(REPORT_ROOT / "raw_runs.csv", raw_rows)
    successful = [row for row in raw_rows if accepted(REPORT_ROOT / "units" / str(row["arm"]) / f"seed_{row['seed']}")]
    table = []
    previous_avg = baseline_avg = None
    for arm, label, enabled in ARMS:
        rows = [row for row in successful if row["arm"] == arm]
        costs = [float(row["best_cost"]) for row in rows]
        avg = statistics.mean(costs) if costs else None
        if arm == ARMS[0][0] and avg is not None:
            baseline_avg = avg
        table.append({
            "arm": arm, "added_component": label, "best": min(costs) if costs else "",
            "avg": avg if avg is not None else "", "std": statistics.stdev(costs) if len(costs) > 1 else 0.0 if costs else "",
            "increment_vs_previous_cny": previous_avg - avg if previous_avg is not None and avg is not None else "",
            "increment_vs_previous_pct": (previous_avg - avg) / previous_avg * 100 if previous_avg is not None and avg is not None else "",
            "cumulative_vs_baseline_cny": baseline_avg - avg if baseline_avg is not None and avg is not None else "",
            "cumulative_vs_baseline_pct": (baseline_avg - avg) / baseline_avg * 100 if baseline_avg is not None and avg is not None else "",
            "complete_feasible_runs": len(rows), "completion_success_rate": len(rows) / len(SEEDS),
            "customers_served": ";".join(f"{row['customers_served']}/{row['customers_total']}" for row in rows),
            "demand_served": ";".join(f"{row['demand_served']}/{row['demand_total']}" for row in rows),
            "avg_time_seconds": statistics.mean(float(row["total_algorithm_wall_seconds"]) for row in rows) if rows else "",
        })
        previous_avg = avg
    write_csv(REPORT_ROOT / "table5.csv", table)
    convergence = []
    for unit in units:
        path = unit.output / "convergence.csv"
        if not path.exists():
            continue
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                convergence.append({"arm": unit.arm, "seed": unit.seed, **row})
    write_csv(REPORT_ROOT / "figure3_convergence.csv", convergence)
    ok_count = sum(bool(row["ok"]) for row in results)
    decision = {"accepted": ok_count == len(units),
                "planned_units": len(units), "accepted_units": ok_count,
                "failed_units": len(units) - ok_count}
    metadata = {"status": "COMPLETED" if decision["accepted"] else "FAILED", "instance_id": INSTANCE,
                "arms": [{"arm": a, "label": l, "enabled": e} for a, l, e in ARMS],
                "seeds": SEEDS, "runtime_seconds": RUNTIME_SECONDS, "max_workers": 1,
                "results": results,
                "existing_component_sources": ["run_problem_hgs_private_technical.py", "run_synergy_batch_20260819.py"]}
    (REPORT_ROOT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    (REPORT_ROOT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n")
    report = ["# 表5增量式消融与图3收敛数据", "", "## 表5", "",
              "| 臂 | 新增组件 | Best | Avg | Std | 较上一臂改善(元) | 较基准累计改善(元) | 完成 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in table:
        report.append(f"| {row['arm']} | {row['added_component']} | {row['best']} | {row['avg']} | {row['std']} | {row['increment_vs_previous_cny']} | {row['cumulative_vs_baseline_cny']} | {row['complete_feasible_runs']}/{len(SEEDS)} |")
    report += ["", "图3绘图数据：`figure3_convergence.csv`；横轴为 `actual_full_model_evaluations`。", ""]
    (REPORT_ROOT / "report.md").write_text("\n".join(report))


def main() -> int:
    if REPORT_ROOT.exists():
        raise FileExistsError(f"refusing to overwrite {REPORT_ROOT}")
    REPORT_ROOT.mkdir(parents=True)
    units = [Unit(arm, label, enabled, seed) for arm, label, enabled in ARMS for seed in SEEDS]
    results = [run_unit(unit) for unit in units]
    aggregate(units, results)
    return 0 if json.loads((REPORT_ROOT / "decision.json").read_text())["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
