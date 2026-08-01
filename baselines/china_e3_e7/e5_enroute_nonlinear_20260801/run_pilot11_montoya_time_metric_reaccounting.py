#!/usr/bin/env python3
"""Reaccount sealed pilot10 solutions by drive time plus en-route charge time."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801 import (
    run_montoya_approximations as source,
)

SOURCE = HERE / "pilot10_montoya_l1_l2_pl_20260801"
OUTPUT = HERE / "pilot11_montoya_time_metric_reaccounting_20260801"
METRIC = "DRIVE_TIME_PLUS_ENROUTE_CHARGE_TIME"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[
            ChargingAction(**row) for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row)
            for row in payload.get("cross_site_services", [])
        ],
    )


def verify_source() -> dict[str, Any]:
    manifest_path = SOURCE / "artifact_hashes.json"
    manifest = read_json(manifest_path)
    mismatches = {
        name: {"expected": expected, "observed": sha256(SOURCE / name)}
        for name, expected in manifest.items()
        if sha256(SOURCE / name) != expected
    }
    if mismatches:
        raise RuntimeError("pilot10 artifact manifest mismatch")
    metadata = read_json(SOURCE / "metadata.json")
    source_paths = {
        "runtime_overlay.py": HERE / "runtime_overlay.py",
        "charging_curve.py": REPO / "solver/src/setp_solver/charging_curve.py",
        "cost.py": REPO / "solver/src/setp_solver/cost.py",
        "check.py": REPO / "solver/src/setp_solver/check.py",
        "search/evaluation.py": REPO / "solver/src/setp_solver/search/evaluation.py",
    }
    observed = {name: sha256(path) for name, path in source_paths.items()}
    if observed != metadata["source_sha256"]:
        raise RuntimeError("pilot10 protected source hash changed")
    runner_hash = sha256(Path(source.__file__))
    if runner_hash != metadata["runner_sha256"]:
        raise RuntimeError("pilot10 runner hash changed")
    return {
        "manifest_sha256": sha256(manifest_path),
        "manifest_entries": len(manifest),
        "all_artifacts_match": True,
        "pilot10_runner_sha256": runner_hash,
        "protected_source_sha256": observed,
    }


def time_metric(solution: Solution, bundle: Any) -> tuple[float, float, float]:
    drive_seconds = sum(
        bundle.instance.arc_metrics(
            left,
            right,
            route.vehicle_type,
            fallback_speed_mps=float(bundle.prices.v_speed_ms),
        )[1]
        for route in solution.routes
        for left, right in zip(route.node_sequence, route.node_sequence[1:])
    )
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    enroute_charge_minutes = sum(
        float(action.occupancy_minutes)
        for action in solution.charging_actions
        if nodes[action.station_id].node_type.lower() == "f"
    )
    drive_minutes = drive_seconds / 60.0
    return drive_minutes, enroute_charge_minutes, drive_minutes + enroute_charge_minutes


def derive() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    audit = verify_source()
    unit_paths = sorted(
        path for path in (SOURCE / "units").glob("*.json") if not path.name.startswith("._")
    )
    if len(unit_paths) != 90:
        raise RuntimeError(f"expected 90 sealed units, found {len(unit_paths)}")
    base_bundles: dict[str, Any] = {}
    units: list[dict[str, Any]] = []
    for path in unit_paths:
        payload = read_json(path)
        row = payload["row"]
        if row["optimization_status"] != "SUCCESS" or not row["optimization_legal"]:
            raise RuntimeError(f"source unit is not a legal success: {path.name}")
        key = str(row["instance_id"])
        base_bundles.setdefault(key, load_china81_bundle(REPO, key))
        bundle = source._bundle_for(
            base_bundles[key],
            capacity_kwh=float(row["capacity_kwh"]),
            approximation=str(row["approximation"]),
        )
        solution = load_solution(payload["solution"])
        violations = check_solution(solution, bundle.instance, bundle.prices)
        if violations:
            raise RuntimeError(f"source solution failed recheck: {path.name}")
        drive, charge, metric = time_metric(solution, bundle)
        if not math.isclose(
            charge, float(row["public_charging_minutes_total"]), abs_tol=1e-7
        ):
            raise RuntimeError(f"public charging duration differs: {path.name}")
        units.append(
            {
                "instance_id": key,
                "seed": int(row["seed"]),
                "capacity_kwh": float(row["capacity_kwh"]),
                "approximation": str(row["approximation"]),
                "curve_id": str(row["curve_id"]),
                "source_unit": path.name,
                "source_unit_sha256": sha256(path),
                "route_hash": str(row["route_hash"]),
                "action_hash": str(row["action_hash"]),
                "drive_time_minutes": drive,
                "enroute_charge_time_minutes": charge,
                "montoya_time_metric_minutes": metric,
            }
        )

    keyed = {
        (
            row["instance_id"],
            row["seed"],
            row["capacity_kwh"],
            row["approximation"],
        ): row
        for row in units
    }
    if len(keyed) != 90:
        raise RuntimeError("source unit keys are not unique")
    rows: list[dict[str, Any]] = []
    for row in units:
        pl = keyed[
            (
                row["instance_id"],
                row["seed"],
                row["capacity_kwh"],
                "PL",
            )
        ]
        delta = row["montoya_time_metric_minutes"] - pl["montoya_time_metric_minutes"]
        rows.append(
            {
                **row,
                "pl_montoya_time_metric_minutes": pl["montoya_time_metric_minutes"],
                "own_minus_pl_minutes": delta,
                "own_minus_pl_percent": 100.0
                * delta
                / pl["montoya_time_metric_minutes"],
                "comparison_to_pl": (
                    "BETTER" if delta < -1e-7 else "WORSE" if delta > 1e-7 else "TIE"
                ),
            }
        )

    summaries: list[dict[str, Any]] = []
    for scope, capacity in (("ALL_CAPACITIES", None), ("CAPACITY_16_KWH", 16.0)):
        for approximation in ("L1", "L2"):
            selected = [
                row
                for row in rows
                if row["approximation"] == approximation
                and (capacity is None or row["capacity_kwh"] == capacity)
            ]
            summaries.append(
                {
                    "scope": scope,
                    "approximation": approximation,
                    "paired_units": len(selected),
                    "better_than_pl": sum(row["comparison_to_pl"] == "BETTER" for row in selected),
                    "ties_pl": sum(row["comparison_to_pl"] == "TIE" for row in selected),
                    "worse_than_pl": sum(row["comparison_to_pl"] == "WORSE" for row in selected),
                    "mean_metric_minutes": fmean(row["montoya_time_metric_minutes"] for row in selected),
                    "mean_pl_metric_minutes": fmean(row["pl_montoya_time_metric_minutes"] for row in selected),
                    "mean_own_minus_pl_minutes": fmean(row["own_minus_pl_minutes"] for row in selected),
                    "pooled_own_minus_pl_percent": 100.0
                    * sum(row["own_minus_pl_minutes"] for row in selected)
                    / sum(row["pl_montoya_time_metric_minutes"] for row in selected),
                }
            )
    audit["runner_sha256"] = sha256(Path(__file__))
    return rows, summaries, audit


def report_text(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# E5 Montoya 时间指标换口径复算",
        "",
        "指标只包含车辆行驶时间和途中充电时间；不包含客户服务时间、等待时间、车场充电时间或人民币成本。",
        "",
        "| 范围 | 近似 | 配对数 | 优于PL | 持平 | 劣于PL | 平均指标/分钟 | PL平均/分钟 | 平均差/分钟 | 合计差/% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            f"| {row['scope']} | {row['approximation']} | {row['paired_units']} | "
            f"{row['better_than_pl']} | {row['ties_pl']} | {row['worse_than_pl']} | "
            f"{row['mean_metric_minutes']:.3f} | {row['mean_pl_metric_minutes']:.3f} | "
            f"{row['mean_own_minus_pl_minutes']:+.3f} | {row['pooled_own_minus_pl_percent']:+.3f}% |"
        )
    lines.extend(
        [
            "",
            "`raw_runs.csv` 完整保留 90 行：每个 L1、L2 和 PL 封存解各占一行，并与同算例、同 seed、同容量的 PL 配对。",
            "",
            "这只是对已封存解换口径复算，不代表当前人民币目标下的实验成功，也不选择正文故事。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(output: Path = OUTPUT) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    rows, summaries, audit = derive()
    decision = {
        "status": "PASS_MECHANICAL_TIME_METRIC_REACCOUNTING",
        "formal_result": False,
        "manuscript_story": "AWAITING_USER_DECISION",
        "metric": METRIC,
        "source_units": 90,
        "rows_written": len(rows),
        "paired_l1_l2_comparisons": 60,
        "summaries": summaries,
        "rmb_objective_success_claimed": False,
    }
    metadata = {
        "schema": "resetp.e5-montoya-time-reaccounting.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "derivation_only": True,
        "formal_result": False,
        "metric": {
            "formula": "drive_time_minutes + enroute_charge_time_minutes",
            "included": ["road-profile arc travel time", "public-station charging occupancy"],
            "excluded": ["customer service time", "waiting time", "depot charging time", "RMB cost"],
            "literature": "Montoya et al. (2017), PDF page 4",
        },
        "source": str(SOURCE.relative_to(REPO)),
        "audit": audit,
    }
    write_csv(output / "raw_runs.csv", rows)
    write_json(output / "decision.json", decision)
    write_json(output / "metadata.json", metadata)
    (output / "report.md").write_text(report_text(summaries), encoding="utf-8")
    artifacts = {
        path.name: sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    write_json(
        output / "artifact_hashes.json",
        {"schema": "resetp.artifact-hashes.v1", "artifacts": artifacts},
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
