#!/usr/bin/env python3
"""Aggregate the three frozen E4 formal members without rerunning search."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PANEL = HERE / "formal_panel_20260801"
MODES = ("COST_ONLY", "COST_PLUS_CARBON", "PURE_CARBON")
COMMAND = (
    "python3 baselines/china_e3_e7/e4_joint_routing_20260801/"
    "aggregate_formal_panel.py --panel "
    "baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def verify_member(directory: Path) -> str:
    manifest_path = directory / "artifact_hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected in manifest.items():
        observed = sha256(directory / name)
        if observed != expected:
            raise RuntimeError(f"source artifact hash differs: {directory.name}/{name}")
    return sha256(manifest_path)


def read_members(panel: Path) -> tuple[list[dict[str, str]], list[str], dict[str, str]]:
    members = sorted(
        path
        for path in panel.iterdir()
        if path.is_dir() and (path / "artifact_hashes.json").exists()
    )
    if len(members) != 3:
        raise RuntimeError(f"expected three formal members, found {len(members)}")

    rows: list[dict[str, str]] = []
    fields: list[str] | None = None
    manifests: dict[str, str] = {}
    for member in members:
        manifests[member.name] = verify_member(member)
        with (member / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if fields is None:
                fields = list(reader.fieldnames or ())
            elif list(reader.fieldnames or ()) != fields:
                raise RuntimeError("source raw schemas differ")
            rows.extend(reader)
    return rows, fields or [], manifests


def comparison(rows: list[dict[str, str]], mode: str) -> dict[str, Any]:
    paired: dict[tuple[str, int], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        paired[(row["instance_id"], int(row["seed"]))][row["objective_mode"]] = row

    def mean_change(field: str) -> float:
        changes = []
        for unit in paired.values():
            base = float(unit["COST_ONLY"][field])
            value = float(unit[mode][field])
            changes.append(100.0 * (value - base) / base)
        return sum(changes) / len(changes)

    return {
        "pair_count": len(paired),
        "mean_system_emissions_change_pct": mean_change("system_emissions_kg"),
        "mean_charging_emissions_change_pct": mean_change("charging_emissions_kg"),
        "mean_operating_cost_change_pct": mean_change("operating_cost_cny"),
        "mean_electricity_cost_change_pct": mean_change("electricity_cost_cny"),
        "route_path_changed_pairs": sum(
            unit[mode]["path_hash"] != unit["COST_ONLY"]["path_hash"]
            for unit in paired.values()
        ),
        "typed_path_changed_pairs": sum(
            unit[mode]["typed_path_hash"] != unit["COST_ONLY"]["typed_path_hash"]
            for unit in paired.values()
        ),
    }


def report_text(decision: dict[str, Any]) -> str:
    cost_carbon = decision["comparisons"]["COST_PLUS_CARBON_vs_COST_ONLY"]
    pure = decision["comparisons"]["PURE_CARBON_vs_COST_ONLY"]
    return (
        "# E4 路线—车型—充电联合优化正式总面板\n\n"
        "状态：PASS_E4_FORMAL_PANEL_AGGREGATED。\n\n"
        "本面板原样汇总三个已封存正式单题包，没有重新搜索或修改单题结果。"
        "共保留90行，即30个算例—种子配对下的纯运营成本、运营成本加碳成本和系统总排放三个目标。\n\n"
        "| 比较 | 配对 | 系统排放变化 | 运营成本变化 | 电费变化 | 路线/车型变化 |\n"
        "|---|---:|---:|---:|---:|---:|\n"
        f"| 成本加碳/纯成本 | {cost_carbon['pair_count']} | "
        f"{cost_carbon['mean_system_emissions_change_pct']:.6f}% | "
        f"{cost_carbon['mean_operating_cost_change_pct']:+.7f}% | "
        f"{cost_carbon['mean_electricity_cost_change_pct']:.6f}% | "
        f"{cost_carbon['typed_path_changed_pairs']}/30 |\n"
        f"| 纯排放/纯成本 | {pure['pair_count']} | "
        f"{pure['mean_system_emissions_change_pct']:.6f}% | "
        f"{pure['mean_operating_cost_change_pct']:+.6f}% | "
        f"{pure['mean_electricity_cost_change_pct']:+.6f}% | "
        f"{pure['typed_path_changed_pairs']}/30 |\n\n"
        "百分比为30个同算例—同种子配对变化率的简单平均。\n"
    )


def run(panel: Path = PANEL) -> dict[str, Any]:
    outputs = tuple(panel / name for name in (
        "metadata.json", "raw_runs.csv", "decision.json", "report.md", "artifact_hashes.json"
    ))
    if any(path.exists() for path in outputs):
        raise RuntimeError("formal panel aggregate already exists")

    rows, fields, source_manifests = read_members(panel)
    rows.sort(key=lambda row: (row["instance_id"], int(row["seed"]), MODES.index(row["objective_mode"])))
    paired = defaultdict(set)
    for row in rows:
        paired[(row["instance_id"], int(row["seed"]))].add(row["objective_mode"])
    if len(rows) != 90 or len(paired) != 30 or any(modes != set(MODES) for modes in paired.values()):
        raise RuntimeError("formal panel is not 90 rows with 30 complete three-objective pairs")
    if any(row["status"] != "PASS" for row in rows):
        raise RuntimeError("formal panel contains a non-PASS row")

    with (panel / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    comparisons = {
        "COST_PLUS_CARBON_vs_COST_ONLY": comparison(rows, "COST_PLUS_CARBON"),
        "PURE_CARBON_vs_COST_ONLY": comparison(rows, "PURE_CARBON"),
    }
    decision = {
        "schema": "resetp.e4-formal-panel-decision.v1",
        "status": "PASS_E4_FORMAL_PANEL_AGGREGATED",
        "row_count": len(rows),
        "paired_unit_count": len(paired),
        "objective_modes": list(MODES),
        "all_source_rows_retained": True,
        "all_rows_pass": True,
        "comparisons": comparisons,
        "route_search_executed": False,
        "solver_reruns": 0,
        "source_members_modified": False,
    }
    metadata = {
        "schema": "resetp.e4-formal-panel-metadata.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "aggregation_command": COMMAND,
        "aggregation_script_sha256": sha256(Path(__file__)),
        "source_member_manifest_sha256": source_manifests,
        "source_artifacts_all_match": True,
        "aggregation_rule": "concatenate all source rows and pair by instance_id plus seed",
        "percentage_rule": "simple mean of 30 paired percentage changes",
        "route_change_rule": "typed_path_hash differs from paired COST_ONLY",
        "route_search_executed": False,
        "solver_reruns": 0,
        "source_members_modified": False,
    }
    write_json(panel / "decision.json", decision)
    write_json(panel / "metadata.json", metadata)
    (panel / "report.md").write_text(report_text(decision), encoding="utf-8")
    artifacts = {
        name: sha256(panel / name)
        for name in ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
    }
    write_json(
        panel / "artifact_hashes.json",
        {"schema": "resetp.artifact-hashes.v1", "artifacts": artifacts},
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, default=PANEL)
    args = parser.parse_args()
    print(json.dumps(run(args.panel), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
