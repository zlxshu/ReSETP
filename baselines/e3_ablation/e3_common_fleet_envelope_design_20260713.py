#!/usr/bin/env python3
"""Build one outcome-blind fleet envelope per E3 network.

This design step performs no route search.  It constructs a deterministic
stand-alone witness for each of the two preregistered ownership classes, then
uses the componentwise maximum physical fleet as the common non-binding cap
for both classes and both later comparison arms.  The envelope is a mechanism
experiment input, not a claim about the minimum fleet.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from baselines.e3_ablation.e3_multitrip_structure_gate import _subinstance
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import _build_cv_seed_with_retry
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.search.fairness import _subinstance_for_depot
from setp_solver.search.instance_registry import instance_abs_dir
from setp_solver.search.multitrip_schedule import build_multitrip_certificate, route_timing
from setp_solver.solution import Route, Solution


OWNERSHIP_ROOT = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713"
OUT = ROOT / "baselines/e3_ablation/e3_common_fleet_envelope_design_v3_20260713"
PREDECESSOR = ROOT / "baselines/e3_ablation/e3_common_fleet_envelope_design_v2_20260713/decision.json"
CONDITIONS = ("geographic", "mixed")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_owners(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}


def deterministic_routes(instance: Any, owners: dict[str, str], prices: Any) -> list[Route]:
    """Build owner-restricted routes and assign a feasible mix without caps."""

    routes: list[Route] = []
    for depot in sorted(set(owners.values())):
        owned = _subinstance_for_depot(instance, depot, owners)
        customers = [node for node in owned.nodes if node.node_type.lower() == "c"]
        for shift in range(3):
            customer_ids = [
                node.node_id
                for node in customers
                if min(2, int(float(node.ready_time) // 28_800)) == shift
            ]
            if not customer_ids:
                continue
            shift_instance = _subinstance(owned, [depot], customer_ids)
            seed = _build_cv_seed_with_retry(
                shift_instance,
                prices,
                start_budget=1,
                max_budget=len(customer_ids),
                enforce_fleet_count=False,
            )
            ordered = sorted(seed.routes, key=lambda route: tuple(route.node_sequence))
            for index, route in enumerate(ordered):
                routes.append(
                    replace(
                        route,
                        vehicle_type="cv",
                        vehicle_id=f"CV_{depot}_S{shift}_{index + 1}",
                    )
                )
    assigned: list[Route] = []
    for depot in sorted(set(route.home_depot_id for route in routes)):
        depot_routes = [route for route in routes if route.home_depot_id == depot]
        eligible: list[tuple[float, tuple[str, ...], str]] = []
        for route in depot_routes:
            try:
                timing = route_timing(replace(route, vehicle_type="ev"), instance, prices)
            except ValueError:
                continue
            eligible.append((float(timing.drive_energy_kwh), tuple(route.node_sequence), route.vehicle_id))
        target_ev = min(len(eligible), max(1, len(depot_routes) // 2))
        ev_ids = {vehicle_id for _, _, vehicle_id in sorted(eligible)[:target_ev]}
        for route in depot_routes:
            vehicle_type = "ev" if route.vehicle_id in ev_ids else "cv"
            assigned.append(
                replace(
                    route,
                    vehicle_type=vehicle_type,
                    vehicle_id=route.vehicle_id.replace("CV_", "EV_", 1) if vehicle_type == "ev" else route.vehicle_id,
                )
            )
    return assigned


def depot_counts(certificate: Any) -> dict[str, dict[str, int]]:
    return legacy._depot_counts(certificate)


def prepared_witness(
    routes: list[Route], bundle: Any, prices: Any, global_caps: dict[str, int], depot_caps: dict[str, dict[str, int]]
) -> tuple[Solution, Any, list[Any]]:
    instance = replace(bundle.instance, num_cv=global_caps["cv"], num_ev=global_caps["ev"])
    context = EvaluationContext(
        instance,
        bundle.carbon_profile,
        prices=prices,
        carbon_weight=0.0,
        fairness_enabled=False,
        allow_cross_depot=False,
    )
    with legacy.strict_mode(depot_caps):
        solution, certificate = prepare_solution(Solution(routes=routes), context)
        violations = hard_violations(solution, context)
    return solution, certificate, violations


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ownership_rows = [
        row
        for row in csv.DictReader((OWNERSHIP_ROOT / "raw_runs.csv").open(newline="", encoding="utf-8"))
    ]
    prices = legacy.prices_for("M1", 0.0)
    summary_rows: list[dict[str, Any]] = []
    envelope_rows: list[dict[str, Any]] = []
    all_pass = True

    for ownership_row in ownership_rows:
        instance_id = ownership_row["instance"]
        bundle_dir = instance_abs_dir(ROOT, instance_id)
        bundle = load_search_bundle(bundle_dir)
        condition_routes: dict[str, list[Route]] = {}
        condition_counts: dict[str, dict[str, dict[str, int]]] = {}
        condition_map_hashes: dict[str, str] = {}

        for condition in CONDITIONS:
            map_path = OWNERSHIP_ROOT / "ownership_maps" / f"{instance_id}__{condition}.csv"
            owners = load_owners(map_path)
            routes = deterministic_routes(bundle.instance, owners, prices)
            certificate = build_multitrip_certificate(routes, bundle.instance, prices)
            condition_routes[condition] = routes
            condition_counts[condition] = depot_counts(certificate)
            condition_map_hashes[condition] = sha256(map_path)

        depots = sorted({depot for item in condition_counts.values() for depot in item})
        per_depot_envelope = {
            depot: {
                kind: max(condition_counts[condition].get(depot, {}).get(kind, 0) for condition in CONDITIONS)
                for kind in ("cv", "ev")
            }
            for depot in depots
        }
        global_caps = {
            kind: sum(per_depot_envelope[depot][kind] for depot in depots)
            for kind in ("cv", "ev")
        }

        instance_pass = True
        for condition in CONDITIONS:
            solution, certificate, violations = prepared_witness(
                condition_routes[condition], bundle, prices, global_caps, per_depot_envelope
            )
            condition_pass = (
                certificate is not None
                and not violations
                and int(certificate.vehicle_counts["cv"]) > 0
                and int(certificate.vehicle_counts["ev"]) > 0
            )
            instance_pass = instance_pass and condition_pass
            all_pass = all_pass and condition_pass
            write_json(
                OUT / "witnesses" / f"{instance_id}__{condition}__solution.json",
                legacy.solution_to_dict(solution),
            )
            if certificate is not None:
                write_json(
                    OUT / "witnesses" / f"{instance_id}__{condition}__certificate.json",
                    certificate.as_dict(),
                )
            summary_rows.append(
                {
                    "instance": instance_id,
                    "source_scale": int(ownership_row["source_scale"]),
                    "condition": condition,
                    "ownership_map_sha256": condition_map_hashes[condition],
                    "source_num_cv": int(bundle.instance.num_cv or 0),
                    "source_num_ev": int(bundle.instance.num_ev or 0),
                    "common_cap_cv": global_caps["cv"],
                    "common_cap_ev": global_caps["ev"],
                    "witness_cv": int(certificate.vehicle_counts["cv"]) if certificate else "",
                    "witness_ev": int(certificate.vehicle_counts["ev"]) if certificate else "",
                    "trip_count": len(certificate.trips) if certificate else "",
                    "depot_counts_json": json.dumps(
                        depot_counts(certificate) if certificate else {}, sort_keys=True
                    ),
                    "violation_count": len(violations),
                    "status": "PASS" if condition_pass else "HALT",
                }
            )

        envelope_rows.append(
            {
                "instance": instance_id,
                "source_scale": int(ownership_row["source_scale"]),
                "source_num_cv": int(bundle.instance.num_cv or 0),
                "source_num_ev": int(bundle.instance.num_ev or 0),
                "common_cap_cv": global_caps["cv"],
                "common_cap_ev": global_caps["ev"],
                "common_depot_caps_json": json.dumps(per_depot_envelope, sort_keys=True),
                "geographic_counts_json": json.dumps(condition_counts["geographic"], sort_keys=True),
                "mixed_counts_json": json.dumps(condition_counts["mixed"], sort_keys=True),
                "status": "PASS" if instance_pass else "HALT",
            }
        )

    for name, rows in (("raw_runs.csv", summary_rows), ("fleet_envelopes.csv", envelope_rows)):
        with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    metadata = {
        "schema": "setp.e3.common_fleet_envelope.v2",
        "purpose": "outcome-blind non-binding fleet caps for the E3 cost mechanism comparison",
        "search_evaluations": 0,
        "predecessor_decision": str(PREDECESSOR.relative_to(ROOT)),
        "predecessor_change_reason": "include the ninth formal network rather than excluding it for source-fleet powertrain composition; the common envelope is already the outcome-blind fleet input for this mechanism experiment",
        "ownership_design_sha256": sha256(OWNERSHIP_ROOT / "decision.json"),
        "battery_kwh": 280.0,
        "depot_charge_power_kw": 22.0,
        "fixed_cost_semantics": "per dispatched trip; unused cap carries no cost",
        "envelope_rule": (
            "for each network, take the componentwise maximum physical CV/EV witness counts "
            "across the two preregistered ownership classes before any cooperation search"
        ),
        "source_commit": source_commit,
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (
                Path(__file__).resolve(),
                ROOT / "baselines/e3_ablation/e3_v3_runner.py",
                ROOT / "solver/src/setp_solver/cost.py",
                ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
            )
        },
    }
    write_json(OUT / "metadata.json", metadata)
    decision = {
        "status": "PASS" if all_pass and len(envelope_rows) == 9 else "HALT",
        "instance_count": len(envelope_rows),
        "all_two_condition_witnesses_pass": all_pass,
        "all_witnesses_use_both_vehicle_types": all(
            int(row["witness_cv"] or 0) > 0 and int(row["witness_ev"] or 0) > 0
            for row in summary_rows
        ),
        "search_evaluations": 0,
        "result_based_retries": 0,
        "paper_boundary": (
            "these caps isolate the routing-cost mechanism and are not estimates of minimum fleet size; "
            "source-fleet scarcity must be reported separately"
        ),
        "next_step": (
            "rerun one same-start 200-evaluation wiring probe"
            if all_pass
            else "stop before search and diagnose the failed deterministic witness"
        ),
    }
    write_json(OUT / "decision.json", decision)

    if decision["status"] == "PASS":
        report = (
            "# 共同车队上限零搜索审计\n\n"
            "判决：通过。9张地图的两类客户组合都已有严格排班见证。\n\n"
            "本步骤没有运行路线搜索。每张地图先分别为地理聚集与空间混合客户组合构造一个合法的各自经营排班，"
            "再把两者实际需要的油车、电车数量逐项取大，作为后续两类情境共同使用的车队上限。"
            "因此，车队上限不会因为合作结果而调整，两类客户组合也不会使用不同资产。\n\n"
            "这组上限只用于把车辆短缺从合作成本比较中拿开，不代表最少车辆数。"
            "当前模型按实际派出的每一趟计固定费，未使用的上限不会产生费用。正式车队紧张时的可服务性必须另行报告，"
            "不能与本实验的成本变化混成一个百分比。\n"
        )
    else:
        report = (
            "# 共同车队上限零搜索审计\n\n"
            "判决：停止。至少一个预注册客户组合没有通过严格排班见证，未启动任何合作搜索。\n"
        )
    (OUT / "report.md").write_text(report, encoding="utf-8")

    hashes = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
