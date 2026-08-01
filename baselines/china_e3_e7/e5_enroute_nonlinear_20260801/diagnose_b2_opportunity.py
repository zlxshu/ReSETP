#!/usr/bin/env python3
"""Zero-search audit of whether original China81 routes expose E5-B2."""

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

from setp_solver.algorithms.resetp_alns.support.charging import (
    _direct_route_energy_need,
    repair_route_charging,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.solution import Route, Solution

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.runtime_overlay import (
    M17_22KW_NORMAL_PWL,
    apply_b2_sensitivity_foundation,
)


FLEET = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"
FORMAL_SIX = {
    f"cn-prd-{size}c-0{rep}-V2-LOCATIONS"
    for size in (150, 200)
    for rep in (1, 2, 3)
}


def _json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                str(row["vehicle_id"]),
                str(row["vehicle_type"]),
                str(row["home_depot_id"]),
                [str(value) for value in row["node_sequence"]],
            )
            for row in payload["routes"]
        ]
    )


def _public_count(actions: list[Any], nodes: dict[str, Any]) -> int:
    return sum(nodes[action.station_id].node_type.lower() == "f" for action in actions)


def audit(output_dir: Path) -> list[dict[str, Any]]:
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    instance_summary: list[dict[str, Any]] = []
    for witness in sorted((FLEET / "witnesses").glob("cn-*.json")):
        instance_id = witness.stem
        match = re.fullmatch(r"cn-([a-z]+)-(\d+)c-(\d+)-V2-LOCATIONS", instance_id)
        if match is None:
            raise ValueError(f"unexpected China81 id: {instance_id}")
        payload = json.loads(witness.read_text(encoding="utf-8"))
        base = load_china81_bundle(REPO, instance_id)
        bundle = apply_b2_sensitivity_foundation(
            base,
            curve_id=M17_22KW_NORMAL_PWL.curve_id,
        )
        skeleton = _solution(payload)
        completed = complete_china81_route_skeleton(skeleton, bundle)
        selected_sequences = {
            tuple(route.node_sequence)
            for route in completed.solution.routes
            if route.vehicle_type.lower() == "ev"
        }
        nodes = {node.node_id: node for node in bundle.instance.nodes}
        capacity = bundle.instance.battery_capacity_kwh(
            fallback=bundle.prices.B_battery_kwh
        )
        local_rows: list[dict[str, Any]] = []
        for route_index, source in enumerate(skeleton.routes):
            route = Route(
                source.vehicle_id,
                "ev",
                source.home_depot_id,
                list(source.node_sequence),
            )
            targets = [
                node_id
                for node_id in route.node_sequence[1:]
                if nodes[node_id].node_type.lower() != "f"
            ]
            energy = _direct_route_energy_need(
                route.node_sequence[0],
                targets,
                nodes,
                bundle.instance,
                bundle.prices,
            )
            result: dict[str, Any] = {}
            for amount in ("just_enough", "max_coverage"):
                repaired, actions = repair_route_charging(
                    route,
                    bundle.instance,
                    bundle.time_profile,
                    bundle.prices,
                    strategy="integrated",
                    carbon_weight=0.0,
                    depot_charge_window_mode="same_day_predeparture",
                    charge_amount_strategy=amount,
                )
                result[f"{amount}_public_stops"] = _public_count(actions, nodes)
                result[f"{amount}_action_count"] = len(actions)
                result[f"{amount}_route"] = "|".join(repaired.node_sequence)
            row = {
                "instance_id": instance_id,
                "region": match.group(1),
                "customer_count": int(match.group(2)),
                "replicate": int(match.group(3)),
                "route_index": route_index,
                "source_vehicle_id": source.vehicle_id,
                "route_energy_kwh": float(energy),
                "route_soc_pct": float(100.0 * energy / capacity),
                "route_exceeds_85_pct": energy > 0.85 * capacity + 1e-9,
                "selected_as_ev_by_default_completion": tuple(source.node_sequence)
                in selected_sequences,
                **result,
                "max_coverage_reduces_public_stop": (
                    result["max_coverage_public_stops"]
                    < result["just_enough_public_stops"]
                ),
            }
            rows.append(row)
            local_rows.append(row)
        instance_summary.append(
            {
                "instance_id": instance_id,
                "route_count": len(local_rows),
                "max_route_soc_pct": max(row["route_soc_pct"] for row in local_rows),
                "selected_ev_route_count": sum(
                    row["selected_as_ev_by_default_completion"] for row in local_rows
                ),
                "selected_ev_max_soc_pct": max(
                    (
                        row["route_soc_pct"]
                        for row in local_rows
                        if row["selected_as_ev_by_default_completion"]
                    ),
                    default=None,
                ),
                "just_enough_public_stops": sum(
                    row["just_enough_public_stops"] for row in local_rows
                ),
                "max_coverage_stop_saving_routes": sum(
                    row["max_coverage_reduces_public_stop"] for row in local_rows
                ),
            }
        )
    with (output_dir / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "task_id": "E5-B2-OPPORTUNITY-AUDIT-20260801",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "formal_result": False,
        "method": "zero-search replay of all 81 frozen witness route skeletons",
        "curve_id": M17_22KW_NORMAL_PWL.curve_id,
        "battery_capacity_kwh": 77.28,
        "initial_ev_battery_kwh": 0.0,
        "route_count": len(rows),
        "instance_count": len(instance_summary),
        "instance_summary": instance_summary,
    }
    decision = {
        "status": "FACT_ZERO_SEARCH_OPPORTUNITY_AUDIT_COMPLETE",
        "formal_result": False,
        "route_count": len(rows),
        "routes_over_85_pct": sum(row["route_exceeds_85_pct"] for row in rows),
        "just_enough_public_stops": sum(row["just_enough_public_stops"] for row in rows),
        "max_coverage_stop_saving_routes": sum(
            row["max_coverage_reduces_public_stop"] for row in rows
        ),
        "formal_six": [
            row for row in instance_summary if row["instance_id"] in FORMAL_SIX
        ],
    }
    _json(output_dir / "metadata.json", metadata)
    _json(output_dir / "decision.json", decision)
    (output_dir / "report.md").write_text(
        "\n".join(
            [
                "# E5-B2 机会审计（零搜索）",
                "",
                f"81 个冻结算例共 {len(rows)} 条见证路线；保持原车型、77.28 kWh 电池和初始 0 kWh。",
                f"超过 85% 电量的路线 {decision['routes_over_85_pct']} 条；原充电量规则产生公共站停靠 {decision['just_enough_public_stops']} 次。",
                f"改为 max_coverage 后可少停一次公共站的路线 {decision['max_coverage_stop_saving_routes']} 条。",
                "",
                "本文件只说明现成路线有没有让非线性充电发挥的物理机会；没有启动路线搜索，不是正式实验结果。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _json(output_dir / "artifact_hashes.json", hashes)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "b2_opportunity_audit_20260801",
    )
    args = parser.parse_args()
    print(json.dumps({"rows": len(audit(args.output_dir))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
