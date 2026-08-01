#!/usr/bin/env python3
"""Zero-search route-mileage audit against Wang et al.'s 95 km reference."""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[3]
for entry in (REPO, REPO / "solver/src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from setp_solver.china81 import load_china81_bundle
from setp_solver.prices import PriceParameters


E5_DIR = Path(__file__).resolve().parent
WITNESS_DIR = (
    REPO
    / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723/witnesses"
)
OUTPUT_DIR = E5_DIR / "b2_wang95_range_opportunity_20260801"
REFERENCE_RANGE_KM = 95.0
EXPECTED_INSTANCE_COUNT = 81
EXPECTED_ROUTE_COUNT = 1040
FORMAL_SIX = {
    f"cn-prd-{customers}c-0{replicate}-V2-LOCATIONS"
    for customers in (150, 200)
    for replicate in (1, 2, 3)
}
SOURCE_NOTE = (
    "Wang et al. (2026), Computers & Operations Research, PDF pp. 24, "
    "26-27; repository review: docs/handoff/"
    "e5b_literature_and_infrastructure_diagnosis_20260801.md:84-92"
)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _witness_files() -> list[Path]:
    return sorted(WITNESS_DIR.glob("cn-*.json"))


def _ev_route_distance_m(
    node_sequence: list[str],
    instance: Any,
    prices: PriceParameters,
) -> float:
    return sum(
        instance.arc_metrics(
            left,
            right,
            "ev",
            fallback_speed_mps=prices.v_speed_ms,
        )[0]
        for left, right in zip(node_sequence, node_sequence[1:])
    )


def _compute_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for witness_path in _witness_files():
        instance_id = witness_path.stem
        match = re.fullmatch(
            r"cn-([a-z]+)-(\d+)c-(\d+)-V2-LOCATIONS",
            instance_id,
        )
        if match is None:
            raise ValueError(f"unexpected China81 instance id: {instance_id}")
        payload = json.loads(witness_path.read_text(encoding="utf-8"))
        bundle = load_china81_bundle(REPO, instance_id)
        for route_index, route in enumerate(payload["routes"]):
            sequence = [str(node_id) for node_id in route["node_sequence"]]
            distance_m = _ev_route_distance_m(
                sequence,
                bundle.instance,
                bundle.prices,
            )
            distance_km = distance_m / 1000.0
            rows.append(
                {
                    "instance_id": instance_id,
                    "region": match.group(1),
                    "customer_count": int(match.group(2)),
                    "replicate": int(match.group(3)),
                    "route_index": route_index,
                    "source_vehicle_id": str(route["vehicle_id"]),
                    "arc_count": len(sequence) - 1,
                    "ev_road_distance_m": float(distance_m),
                    "ev_road_distance_km": float(distance_km),
                    "reference_range_km": REFERENCE_RANGE_KM,
                    "exceeds_reference_range": (
                        distance_km > REFERENCE_RANGE_KM + 1e-9
                    ),
                    "excess_km": max(0.0, distance_km - REFERENCE_RANGE_KM),
                    "formal_six_instance": instance_id in FORMAL_SIX,
                }
            )
    return rows


def _summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for instance_id in sorted({str(row["instance_id"]) for row in rows}):
        local = [row for row in rows if row["instance_id"] == instance_id]
        summaries.append(
            {
                "instance_id": instance_id,
                "route_count": len(local),
                "routes_over_95_km": sum(
                    bool(row["exceeds_reference_range"]) for row in local
                ),
                "share_over_95_km": sum(
                    bool(row["exceeds_reference_range"]) for row in local
                )
                / len(local),
                "maximum_ev_road_distance_km": max(
                    float(row["ev_road_distance_km"]) for row in local
                ),
            }
        )
    return summaries


def _report(
    rows: list[dict[str, Any]],
    formal_six: list[dict[str, Any]],
) -> str:
    over = sum(bool(row["exceeds_reference_range"]) for row in rows)
    lines = [
        "# E5-B2：Wang 95 km 续航参照下的零搜索机会审计",
        "",
        f"81 个权威见证算例共有 {len(rows)} 条既定路线。按电动车路网距离复算，其中 {over} 条超过 Wang 等（2026）北京业务案例的 95 km 续航参照，占 {over / len(rows):.2%}。",
        "",
        "这里没有把 95 km 或该文献车辆写入 China81 求解器，也没有替换原 77.28 kWh 车型。它只回答一个问题：若把文献车辆作为敏感性参照，现成路线中有多少条在物理上可能需要途中补电。",
        "",
        "| 正式算例 | 路线数 | 超过95 km | 比例 | 最长路线(km) |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in formal_six:
        lines.append(
            f"| {item['instance_id']} | {item['route_count']} | "
            f"{item['routes_over_95_km']} | "
            f"{item['share_over_95_km']:.2%} | "
            f"{item['maximum_ev_road_distance_km']:.3f} |"
        )
    lines.extend(
        [
            "",
            "这不是非线性充电效应，也不能替代 E5-B2 的车型、路径、充电站、充电次数和充电量联合优化。即使一条路线超过 95 km，也仍需联合优化判断能否补电、在哪里补、补多少以及成本是否改善。",
            "",
            f"文献依据：{SOURCE_NOTE}。本产物 formal_result=false。",
        ]
    )
    return "\n".join(lines) + "\n"


def generate(output_dir: Path) -> None:
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    rows = _compute_rows()
    if len(_witness_files()) != EXPECTED_INSTANCE_COUNT or len(rows) != EXPECTED_ROUTE_COUNT:
        raise ValueError("China81 witness count is not 81 instances / 1040 routes")
    summaries = _summaries(rows)
    formal_six = [
        item for item in summaries if item["instance_id"] in FORMAL_SIX
    ]
    output_dir.mkdir(parents=True)
    with (output_dir / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    over = sum(bool(row["exceeds_reference_range"]) for row in rows)
    metadata = {
        "task_id": "E5-B2-DIAG-02",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "formal_result": False,
        "method": "zero-search EV-road-distance replay of authoritative witnesses",
        "witness_authority": str(WITNESS_DIR.relative_to(REPO)),
        "instance_count": EXPECTED_INSTANCE_COUNT,
        "route_count": len(rows),
        "reference_range_km": REFERENCE_RANGE_KM,
        "reference_role": "literature sensitivity only; not a solver or vehicle parameter",
        "reference_source": SOURCE_NOTE,
        "original_china81_vehicle_unchanged": True,
        "search_executed": False,
    }
    decision = {
        "status": "FACT_ZERO_SEARCH_RANGE_OPPORTUNITY_AUDIT_COMPLETE",
        "formal_result": False,
        "route_count": len(rows),
        "routes_over_95_km": over,
        "share_over_95_km": over / len(rows),
        "formal_six": formal_six,
        "interpretation": (
            "physical opportunity screen only; not nonlinear-effect evidence "
            "and not a substitute for E5-B2 joint optimization"
        ),
    }
    _write_json(output_dir / "metadata.json", metadata)
    _write_json(output_dir / "decision.json", decision)
    (output_dir / "report.md").write_text(
        _report(rows, formal_six), encoding="utf-8"
    )
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _write_json(output_dir / "artifact_hashes.json", hashes)


def check(output_dir: Path) -> dict[str, Any]:
    required = {
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    }
    present = {
        path.name
        for path in output_dir.iterdir()
        if path.is_file() and not path.name.startswith("._")
    }
    if present != required:
        raise ValueError(f"unexpected artifact files: {sorted(present ^ required)}")
    with (output_dir / "raw_runs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        saved = list(csv.DictReader(handle))
    expected = _compute_rows()
    if len(saved) != EXPECTED_ROUTE_COUNT or len(expected) != EXPECTED_ROUTE_COUNT:
        raise ValueError("raw_runs.csv does not contain exactly 1040 routes")
    for stored, current in zip(saved, expected, strict=True):
        identity = (current["instance_id"], str(current["route_index"]))
        if (stored["instance_id"], stored["route_index"]) != identity:
            raise ValueError(f"route identity mismatch at {identity}")
        distance_m = float(stored["ev_road_distance_m"])
        distance_km = float(stored["ev_road_distance_km"])
        if abs(distance_m / 1000.0 - distance_km) > 1e-9:
            raise ValueError(f"metre/kilometre arithmetic mismatch at {identity}")
        if abs(distance_m - float(current["ev_road_distance_m"])) > 1e-6:
            raise ValueError(f"EV road distance mismatch at {identity}")
        stored_over = stored["exceeds_reference_range"].lower() == "true"
        if stored_over != (distance_km > REFERENCE_RANGE_KM + 1e-9):
            raise ValueError(f"95 km classification mismatch at {identity}")
    manifest = json.loads(
        (output_dir / "artifact_hashes.json").read_text(encoding="utf-8")
    )
    expected_hash_files = required - {"artifact_hashes.json"}
    if set(manifest) != expected_hash_files:
        raise ValueError("artifact hash manifest has the wrong file set")
    for name, digest in manifest.items():
        actual = hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError(f"artifact hash mismatch: {name}")
    return {
        "status": "PASS",
        "instance_count": EXPECTED_INSTANCE_COUNT,
        "route_count": EXPECTED_ROUTE_COUNT,
        "distance_arithmetic": "PASS",
        "artifact_hashes": "PASS",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(check(args.output_dir), ensure_ascii=False))
    else:
        generate(args.output_dir)
        print(json.dumps({"output_dir": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
