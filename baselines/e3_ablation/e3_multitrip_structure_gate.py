#!/usr/bin/env python3
"""Build the two seed-1 E3 structural witnesses; never starts the 70-run batch."""

from __future__ import annotations

from dataclasses import asdict, replace
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    sys.path.insert(0, str(path))

from baselines.e2_alns import e2_final_closure as closure
from setp_solver.check import check_solution
from setp_solver.instance_loader import Instance
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import _build_cv_seed_with_retry
from setp_solver.search.multitrip_schedule import (
    CHARGE_MODE_FULL,
    CHARGE_MODE_PARTIAL,
    build_multitrip_certificate,
    route_timing,
)
from setp_solver.solution import Route, Solution


OUT = ROOT / "baselines/e3_ablation/e3_multitrip_structure_gate_20260712"
INSTANCE = "L-main-threeshift-200c-01"


def _subinstance(instance: Instance, depots: list[str], customers: list[str]) -> Instance:
    keep = set(depots) | set(customers)
    nodes = [node for node in instance.nodes if node.node_id in keep]
    indices = [instance.node_index[node.node_id] for node in nodes]
    matrix = [[instance.distance_matrix[i][j] for j in indices] for i in indices]
    return Instance(nodes, matrix)


def _short_trips(instance: Instance, *, independent: bool, prices: object) -> list[Route]:
    owners = infer_customer_home_depots(instance)
    depots = sorted(node.node_id for node in instance.nodes if node.node_type.lower() == "d")
    customers = [node for node in instance.nodes if node.node_type.lower() == "c"]
    routes: list[Route] = []
    for shift in range(3):
        shift_customers = [node for node in customers if min(2, int(node.ready_time // 28_800)) == shift]
        groups = depots if independent else ["joint"]
        for group in groups:
            selected = [node.node_id for node in shift_customers if not independent or owners[node.node_id] == group]
            active_depots = [group] if independent else depots
            if not selected:
                continue
            sub = _subinstance(instance, active_depots, selected)
            seed = _build_cv_seed_with_retry(
                sub, prices, start_budget=1, max_budget=len(selected), enforce_fleet_count=False
            )
            # Split each depot's simultaneous trips between the two available
            # asset types, but never hand an EV a trip beyond one full battery.
            # This changes no route or constraint; it only assigns legal work.
            by_depot: dict[str, list[Route]] = {}
            for route in seed.routes:
                by_depot.setdefault(route.home_depot_id, []).append(route)
            for depot_id, depot_routes in sorted(by_depot.items()):
                ordered = sorted(depot_routes, key=lambda route: tuple(route.node_sequence))
                target_ev = len(ordered) // 2
                eligible: list[tuple[float, int]] = []
                for index, route in enumerate(ordered):
                    try:
                        timing = route_timing(
                            replace(route, vehicle_type="ev"),
                            instance,
                            prices,
                        )
                    except ValueError:
                        continue
                    eligible.append((timing.drive_energy_kwh, index))
                if len(eligible) < target_ev:
                    raise ValueError(
                        f"HALT_ASSET_ASSIGNMENT: shift {shift} depot {depot_id} needs {target_ev} EV trips "
                        f"but only {len(eligible)} fit one 280 kWh battery"
                    )
                ev_indices = {index for _, index in sorted(eligible)[:target_ev]}
                for index, route in enumerate(ordered):
                    vehicle_type = "ev" if index in ev_indices else "cv"
                    prefix = "EV" if vehicle_type == "ev" else "CV"
                    routes.append(replace(
                        route,
                        vehicle_id=f"{prefix}_{'solo' if independent else 'shared'}_S{shift}_{depot_id}_{index + 1}",
                        vehicle_type=vehicle_type,
                    ))
    return routes


def _run_case(
    instance: Instance,
    label: str,
    independent: bool,
    *,
    recharge_mode: str,
    prices: object,
) -> dict[str, object]:
    started = time.perf_counter()
    routes = _short_trips(instance, independent=independent, prices=prices)
    # Route-level capacity and customer/time-window checks remain useful, but
    # legacy fleet/battery labels are intentionally excluded from this new
    # full-battery-at-first-departure contract.
    route_violations = [
        asdict(item) for item in check_solution(Solution(routes=routes), replace(instance, num_cv=None, num_ev=None), prices)
        if item.type not in {"BATTERY", "FLEET_COUNT"}
    ]
    certificate = build_multitrip_certificate(routes, instance, prices, recharge_mode=recharge_mode)
    counts = certificate.vehicle_counts
    status = (
        "PASS_14_14_WITNESS"
        if not route_violations and counts["cv"] <= 14 and counts["ev"] <= 14
        else "NO_14_14_WITNESS_GREEDY"
    )
    payload = {
        "case": label,
        "recharge_mode": recharge_mode,
        "status": status,
        "route_count": len(routes),
        "customer_count": sum(len(route.node_sequence) - 2 for route in routes),
        "physical_cv": counts["cv"],
        "physical_ev": counts["ev"],
        "depot_charge_power_kw": certificate.depot_charge_power_kw,
        "charge_energy_kwh": sum(float(trip.charge_energy_kwh or 0.0) for trip in certificate.trips),
        "max_trips_per_vehicle": max((trip.trip_index for trip in certificate.trips), default=0),
        "route_violations": route_violations,
        "wall_seconds": time.perf_counter() - started,
        "certificate": certificate.as_dict(),
        "routes": [asdict(route) for route in routes],
    }
    (OUT / f"{label}_{recharge_mode}_certificate.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {key: value for key, value in payload.items() if key not in {"certificate", "routes", "route_violations"}} | {
        "route_violation_count": len(route_violations)
    }


def main() -> int:
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUT))
    parser.add_argument("--recharge-mode", choices=(CHARGE_MODE_FULL, CHARGE_MODE_PARTIAL, "both"), default="both")
    args = parser.parse_args()
    OUT = Path(args.output_dir).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    source = closure._resolve_bundle_dir("threeshift", INSTANCE)
    bundle = load_search_bundle(source)
    metadata = {
        "schema": "setp-e3-multitrip-structure-gate.v2",
        "purpose": "prove seed-1 solo and shared routing can be physically scheduled before formal E3",
        "instance": INSTANCE,
        "source_bundle": str(source.relative_to(ROOT)),
        "asset_caps": {"cv": 14, "ev": 14},
        "battery_kwh": 280,
        "depot_charge_power_kw": float(DEFAULT_PRICES.depot_charge_power_kw),
        "depot_charge_power_source": "PriceParameters.depot_charge_power_kw",
        "certificate_scope": "greedy feasibility witness; not a proof of minimum vehicle count or global infeasibility",
        "formal_recharge_rule": "partial_recharge_decision_within_each_legal_gap",
        "formal_run_count_started": 0,
        "model_changed": False,
        "legacy_e1_e2_rejudged": False,
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, initial_ev_battery_kwh=280.0)
    modes = (CHARGE_MODE_FULL, CHARGE_MODE_PARTIAL) if args.recharge_mode == "both" else (args.recharge_mode,)
    rows = []
    for recharge_mode in modes:
        rows.extend([
            _run_case(bundle.instance, "solo_business", True, recharge_mode=recharge_mode, prices=prices),
            _run_case(bundle.instance, "shared_business", False, recharge_mode=recharge_mode, prices=prices),
        ])
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    partial_rows = [row for row in rows if row["recharge_mode"] == CHARGE_MODE_PARTIAL]
    full_rows = [row for row in rows if row["recharge_mode"] == CHARGE_MODE_FULL]
    partial_witness_passed = bool(partial_rows) and all(row["status"] == "PASS_14_14_WITNESS" for row in partial_rows)
    full_witness_passed = bool(full_rows) and all(row["status"] == "PASS_14_14_WITNESS" for row in full_rows)
    structure_gate_cleared = partial_witness_passed
    decision = {
        "verdict": "E3_STRICT_STRUCTURE_V2_PASS" if structure_gate_cleared else "HALT_E3_STRICT_STRUCTURE_V2",
        "partial_14_14_witness_passed": partial_witness_passed,
        "full_recharge_robustness_witness_passed": full_witness_passed if full_rows else None,
        "structure_gate_cleared": structure_gate_cleared,
        "formal_70_authorized": False,
        "formal_70_started": False,
        "next_required_gate": "200_evaluation_wiring_gate" if structure_gate_cleared else "stop_and_report",
        "rows": rows,
    }
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    report = "# E3真实车辆结构门\n\n" + (
        "通过：按论文已经批准的按需补电规则，独立经营和合作经营都能在14辆油车、14辆电车以内排开。"
        if partial_witness_passed else "停止：当前构造没有在14辆油车、14辆电车以内排开。"
    ) + "\n\n这一步只证明物理上排得开，不证明方案省钱，也没有启动正式70次。若另跑每趟补满，它只作额外对照，不决定正式口径。\n"
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hashes = {}
    for path in sorted(OUT.iterdir()):
        if path.name != "artifact_hashes.json" and not path.name.startswith("._") and path.is_file():
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
