#!/usr/bin/env python3
"""Aggregate the six approved E3 packages without running any search."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import statistics
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PANEL_ROOT = HERE.parent
REPO = HERE.parents[4]
INSTANCES = (
    "cn-prd-150c-01-V2-LOCATIONS",
    "cn-prd-150c-02-V2-LOCATIONS",
    "cn-prd-150c-03-V2-LOCATIONS",
    "cn-prd-200c-01-V2-LOCATIONS",
    "cn-prd-200c-02-V2-LOCATIONS",
    "cn-prd-200c-03-V2-LOCATIONS",
)
SEEDS = tuple(range(1, 11))
ARMS = ("HISTORICAL_STANDALONE", "JOINT_OPTIMIZED")
SOURCE_ARTIFACTS = ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
OUTPUTS = ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
EXPECTED = {
    "paired_units": 60,
    "joint_cost_lower_pairs": 60,
    "mean_cost_reduction_pct": 36.477268811132966,
    "min_cost_reduction_pct": 30.985806486586164,
    "max_cost_reduction_pct": 42.39971081837583,
    "mean_distance_reduction_pct": 57.372322731126395,
    "mean_emissions_reduction_pct": 57.307070334914364,
    "mean_vehicle_count_change": -2.95,
    "mean_joint_cross_contractor_customer_count": 121.58333333333333,
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().replace("\r\n", "\n").encode()


def relative(path: Path) -> str:
    return str(path.relative_to(REPO))


def load_source(instance_id: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    source = PANEL_ROOT / instance_id
    manifest_path = source / "artifact_hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name in SOURCE_ARTIFACTS:
        if sha256(source / name) != manifest["artifacts"][name]:
            raise RuntimeError(f"source hash mismatch: {instance_id}/{name}")

    metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    decision = json.loads((source / "decision.json").read_text(encoding="utf-8"))
    if metadata["schema"] != "resetp.e3-capacity-rank-aligned-formal-panel-member.v1":
        raise RuntimeError(f"non-formal metadata: {instance_id}")
    if metadata["evidence_role"] != "FORMAL_PANEL_MEMBER":
        raise RuntimeError(f"wrong evidence role: {instance_id}")
    if decision["status"] != "PASS_FORMAL_PANEL_MEMBER":
        raise RuntimeError(f"source decision is not PASS: {instance_id}")
    if decision["formal_adoption"] != "USER_APPROVED":
        raise RuntimeError(f"source is not user-approved: {instance_id}")
    if decision["completed_seeds"] != list(SEEDS):
        raise RuntimeError(f"source seeds are incomplete: {instance_id}")

    with (source / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != len(SEEDS) * len(ARMS):
        raise RuntimeError(f"wrong source row count: {instance_id}")
    return rows, {
        "path": relative(source),
        "artifact_hashes_sha256": sha256(manifest_path),
        "raw_runs_sha256": sha256(source / "raw_runs.csv"),
    }


def number(row: dict[str, str], name: str) -> float:
    return float(row[name])


def vehicle_count(row: dict[str, str]) -> int:
    return int(row["used_cv_total"]) + int(row["used_ev_total"])


def pair_row(
    instance_id: str,
    seed: int,
    historical: dict[str, str],
    joint: dict[str, str],
    source_hash: str,
) -> dict[str, Any]:
    if historical["status"] != "PASS" or joint["status"] != "PASS":
        raise RuntimeError(f"non-PASS source row: {instance_id} seed {seed}")
    if historical["mapping_sha256"] != joint["mapping_sha256"]:
        raise RuntimeError(f"mapping differs within pair: {instance_id} seed {seed}")
    if historical["initial_sha256"] != joint["initial_sha256"]:
        raise RuntimeError(f"initial solution differs within pair: {instance_id} seed {seed}")

    historical_cost = number(historical, "total_cost_cny")
    joint_cost = number(joint, "total_cost_cny")
    historical_distance = number(historical, "total_distance_km")
    joint_distance = number(joint, "total_distance_km")
    historical_emissions = number(historical, "total_emissions_kg")
    joint_emissions = number(joint, "total_emissions_kg")
    cost_reduction = 100.0 * (historical_cost - joint_cost) / historical_cost
    stored_change = -number(joint, "joint_relative_cost_change_pct")
    if abs(cost_reduction - stored_change) > 1e-12:
        raise RuntimeError(f"stored pair effect differs: {instance_id} seed {seed}")

    return {
        "instance_id": instance_id,
        "seed": seed,
        "historical_cost_cny": historical_cost,
        "joint_cost_cny": joint_cost,
        "cost_reduction_pct": cost_reduction,
        "historical_distance_km": historical_distance,
        "joint_distance_km": joint_distance,
        "distance_reduction_pct": 100.0
        * (historical_distance - joint_distance)
        / historical_distance,
        "historical_emissions_kg": historical_emissions,
        "joint_emissions_kg": joint_emissions,
        "emissions_reduction_pct": 100.0
        * (historical_emissions - joint_emissions)
        / historical_emissions,
        "historical_vehicle_count": vehicle_count(historical),
        "joint_vehicle_count": vehicle_count(joint),
        "vehicle_count_change": vehicle_count(joint) - vehicle_count(historical),
        "joint_cross_contractor_customer_count": int(
            joint["cross_contractor_customer_count"]
        ),
        "mapping_sha256": historical["mapping_sha256"],
        "initial_sha256": historical["initial_sha256"],
        "historical_solution_sha256": historical["solution_sha256"],
        "joint_solution_sha256": joint["solution_sha256"],
        "source_artifact_hashes_sha256": source_hash,
        "status": "PASS_PAIRED_SOURCE_RECORDS",
    }


def mean(rows: list[dict[str, Any]], field: str) -> float:
    return statistics.fmean(float(row[field]) for row in rows)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reductions = [float(row["cost_reduction_pct"]) for row in rows]
    by_instance: dict[str, Any] = {}
    for instance_id in INSTANCES:
        subset = [row for row in rows if row["instance_id"] == instance_id]
        by_instance[instance_id] = {
            "paired_units": len(subset),
            "mean_historical_cost_cny": mean(subset, "historical_cost_cny"),
            "mean_joint_cost_cny": mean(subset, "joint_cost_cny"),
            "mean_cost_reduction_pct": mean(subset, "cost_reduction_pct"),
            "mean_distance_reduction_pct": mean(subset, "distance_reduction_pct"),
            "mean_emissions_reduction_pct": mean(subset, "emissions_reduction_pct"),
            "mean_vehicle_count_change": mean(subset, "vehicle_count_change"),
            "mean_joint_cross_contractor_customer_count": mean(
                subset, "joint_cross_contractor_customer_count"
            ),
        }
    return {
        "paired_units": len(rows),
        "source_rows": len(rows) * 2,
        "joint_cost_lower_pairs": sum(value > 0.0 for value in reductions),
        "mean_cost_reduction_pct": statistics.fmean(reductions),
        "min_cost_reduction_pct": min(reductions),
        "max_cost_reduction_pct": max(reductions),
        "mean_distance_reduction_pct": mean(rows, "distance_reduction_pct"),
        "mean_emissions_reduction_pct": mean(rows, "emissions_reduction_pct"),
        "mean_vehicle_count_change": mean(rows, "vehicle_count_change"),
        "mean_joint_cross_contractor_customer_count": mean(
            rows, "joint_cross_contractor_customer_count"
        ),
        "by_instance": by_instance,
    }


def validate_summary(summary: dict[str, Any]) -> None:
    for name, expected in EXPECTED.items():
        if summary[name] != expected:
            raise RuntimeError(
                f"aggregate mismatch for {name}: {summary[name]!r} != {expected!r}"
            )


def report(summary: dict[str, Any]) -> str:
    lines = [
        "# E3 用户批准正式面板汇总",
        "",
        "本包只读聚合六个正式来源包，没有重新运行搜索。",
        "",
        "| 算例 | 历史固定成本/元 | 联合重分成本/元 | 降本/% | 里程降幅/% | 排放降幅/% | 车辆变化 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for instance_id in INSTANCES:
        row = summary["by_instance"][instance_id]
        lines.append(
            f"| {instance_id} | {row['mean_historical_cost_cny']:.3f} | "
            f"{row['mean_joint_cost_cny']:.3f} | {row['mean_cost_reduction_pct']:.3f} | "
            f"{row['mean_distance_reduction_pct']:.3f} | "
            f"{row['mean_emissions_reduction_pct']:.3f} | "
            f"{row['mean_vehicle_count_change']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"配对单元：{summary['paired_units']}；联合重分成本更低："
            f"{summary['joint_cost_lower_pairs']}/{summary['paired_units']}。",
            f"平均降本：{summary['mean_cost_reduction_pct']:.6f}%；"
            f"范围：{summary['min_cost_reduction_pct']:.6f}%--"
            f"{summary['max_cost_reduction_pct']:.6f}%.",
            f"平均里程降幅：{summary['mean_distance_reduction_pct']:.6f}%；"
            f"平均排放降幅：{summary['mean_emissions_reduction_pct']:.6f}%。",
            f"平均车辆变化：{summary['mean_vehicle_count_change']:.2f}；"
            "联合重分后平均跨承包商客户数："
            f"{summary['mean_joint_cross_contractor_customer_count']:.6f}。",
            "",
        ]
    )
    return "\n".join(lines)


def build() -> dict[str, bytes]:
    rows: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}
    for instance_id in INSTANCES:
        source_rows, source = load_source(instance_id)
        sources[instance_id] = source
        indexed = {
            (int(row["seed"]), row["arm"]): row
            for row in source_rows
        }
        if set(indexed) != {(seed, arm) for seed in SEEDS for arm in ARMS}:
            raise RuntimeError(f"source pairs are incomplete: {instance_id}")
        for seed in SEEDS:
            rows.append(
                pair_row(
                    instance_id,
                    seed,
                    indexed[(seed, ARMS[0])],
                    indexed[(seed, ARMS[1])],
                    source["artifact_hashes_sha256"],
                )
            )

    summary = summarize(rows)
    validate_summary(summary)
    metadata = {
        "schema": "resetp.e3-capacity-rank-aligned-formal-panel-aggregate.metadata.v1",
        "evidence_role": "FORMAL_PANEL_AGGREGATE",
        "formal_adoption": "USER_APPROVED",
        "derivation": "read-only aggregation of existing raw_runs.csv files; no search",
        "source_panel": relative(PANEL_ROOT),
        "instances": list(INSTANCES),
        "seeds": list(SEEDS),
        "comparison": list(ARMS),
        "pairing_unit": "instance_id and seed",
        "source_packages": sources,
    }
    decision = {
        "schema": "resetp.e3-capacity-rank-aligned-formal-panel-aggregate.decision.v1",
        "status": "PASS_FORMAL_PANEL_AGGREGATE",
        "formal_adoption": "USER_APPROVED",
        **summary,
    }
    blobs = {
        "metadata.json": json_bytes(metadata),
        "raw_runs.csv": csv_bytes(rows),
        "decision.json": json_bytes(decision),
        "report.md": report(summary).encode(),
    }
    manifest = {
        "schema": "resetp.artifact-hashes.v1",
        "algorithm": "sha256",
        "artifacts": {
            "aggregate_panel.py": sha256(Path(__file__)),
            **{name: sha256_bytes(data) for name, data in blobs.items()},
        },
    }
    blobs["artifact_hashes.json"] = json_bytes(manifest)
    return blobs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    blobs = build()
    if args.check:
        for name, expected in blobs.items():
            if (HERE / name).read_bytes() != expected:
                raise RuntimeError(f"aggregate artifact differs: {name}")
        print("PASS_FORMAL_PANEL_AGGREGATE_CHECK")
        return 0
    for name, data in blobs.items():
        (HERE / name).write_bytes(data)
    print("PASS_FORMAL_PANEL_AGGREGATE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
