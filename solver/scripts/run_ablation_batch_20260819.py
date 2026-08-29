#!/usr/bin/env python3
"""Run each private ablation arm once through the current private runner."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
REPORT_ROOT = REPO / "solver/reports/paper_aligned_ablation_20260829"
PYTHON = REPO / "build/python_envs/setp-independent-hgs/bin/python"
RUNNER = REPO / "solver/scripts/run_problem_hgs_private_technical.py"
INSTANCE = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
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

    @property
    def output(self) -> Path:
        return REPORT_ROOT / self.arm


def command(unit: Unit) -> list[str]:
    disabled = ",".join(name for name in MECHANISMS if name not in unit.enabled)
    argv = [
        str(PYTHON),
        str(RUNNER),
        str(unit.output.relative_to(REPO)),
        "--instance-id",
        INSTANCE,
        "--carbon-price",
        "0.20",
        "--fleet-parameter-class",
        "endogenous",
        "--population-mode",
        "copied_hgs_defaults",
        "--charge-timing-policy",
        "cost_plus_carbon",
        "--arm",
        f"ablation_{unit.arm}",
    ]
    if disabled:
        argv += ["--mechanism-off", disabled]
    return argv


def environment() -> dict[str, str]:
    env = os.environ.copy()
    required = "solver/src:models/src:third_party/setp_hgs_kernel:."
    env["PYTHONPATH"] = (
        f"{required}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else required
    )
    return env


def read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_run_row(unit: Unit) -> dict[str, object]:
    path = unit.output / "raw_runs.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return dict(next(csv.DictReader(handle)))


def run_unit(unit: Unit) -> dict[str, object]:
    log_path = REPORT_ROOT / "logs" / f"{unit.arm}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command(unit),
            cwd=REPO,
            env=environment(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )

    decision = read_json(unit.output / "decision.json")
    row: dict[str, object] = {
        "arm": unit.arm,
        "arm_label": unit.label,
        "enabled_mechanisms": ";".join(unit.enabled),
        "returncode": completed.returncode,
        "verdict": decision.get("verdict", "RUN_FAILED"),
        "failure_reasons": "; ".join(
            str(reason) for reason in decision.get("failure_reasons", [])
        ),
    }
    row.update(read_run_row(unit))
    return row


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def completed(row: dict[str, object]) -> bool:
    return row.get("verdict") == "RUN_COMPLETE"


def aggregate(units: list[Unit], rows: list[dict[str, object]]) -> None:
    write_csv(REPORT_ROOT / "raw_runs.csv", rows)
    table = []
    previous_cost: float | None = None
    baseline_cost: float | None = None
    for row in rows:
        cost = float(row["best_cost"]) if completed(row) and row.get("best_cost") else None
        if baseline_cost is None and cost is not None:
            baseline_cost = cost
        table.append(
            {
                "arm": row["arm"],
                "added_component": row["arm_label"],
                "best": "" if cost is None else cost,
                "avg": "" if cost is None else cost,
                "std": "",
                "increment_vs_previous_cny": (
                    "" if cost is None or previous_cost is None else previous_cost - cost
                ),
                "cumulative_vs_baseline_cny": (
                    "" if cost is None or baseline_cost is None else baseline_cost - cost
                ),
                "best_feasible": row.get("best_feasible", ""),
                "customers_served": row.get("customers_served", ""),
                "customers_total": row.get("customers_total", ""),
                "demand_served": row.get("demand_served", ""),
                "demand_total": row.get("demand_total", ""),
                "verdict": row["verdict"],
                "failure_reasons": row["failure_reasons"],
            }
        )
        if cost is not None:
            previous_cost = cost
    write_csv(REPORT_ROOT / "table5.csv", table)

    convergence = []
    for unit in units:
        path = unit.output / "convergence.csv"
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            convergence.extend({"arm": unit.arm, **row} for row in csv.DictReader(handle))
    if convergence:
        write_csv(REPORT_ROOT / "figure3_convergence.csv", convergence)

    complete_count = sum(completed(row) for row in rows)
    decision = {
        "verdict": "RUN_COMPLETE" if complete_count == len(units) else "RUN_FAILED",
        "planned_units": len(units),
        "completed_units": complete_count,
        "failed_units": len(units) - complete_count,
    }
    metadata = {
        "status": decision["verdict"],
        "instance_id": INSTANCE,
        "repeat_count_per_arm": 1,
        "stop_rule": "20,000 consecutive non-improving iterations; no restart",
        "arms": [
            {"arm": arm, "label": label, "enabled": list(enabled)}
            for arm, label, enabled in ARMS
        ],
        "results": rows,
    }
    (REPORT_ROOT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (REPORT_ROOT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = [
        "# 表5增量式消融与图3收敛数据",
        "",
        "每个消融臂运行一次；停止由 private runner 的连续 20,000 次完整迭代无改善且不重启规则统一负责。",
        "",
        "| 臂 | 新增组件 | 成本 | 可行 | 客户服务 | 需求服务 | 结果 |",
        "|---|---|---:|---|---:|---:|---|",
    ]
    for row in table:
        report.append(
            f"| {row['arm']} | {row['added_component']} | {row['best']} | "
            f"{row['best_feasible']} | {row['customers_served']}/{row['customers_total']} | "
            f"{row['demand_served']}/{row['demand_total']} | {row['verdict']} |"
        )
    (REPORT_ROOT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    units = [Unit(arm, label, enabled) for arm, label, enabled in ARMS]
    rows = [run_unit(unit) for unit in units]
    aggregate(units, rows)
    return 0 if all(completed(row) for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
