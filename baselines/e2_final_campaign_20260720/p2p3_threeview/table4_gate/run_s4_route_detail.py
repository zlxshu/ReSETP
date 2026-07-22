#!/usr/bin/env python3
"""S4: independently recalculate the best representative MV-HGS-SP routes."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final"
OUT = Path(__file__).resolve().parent
S3_DIR = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate"
S3_DECISION = S3_DIR / "decision.json"
S3_RAW = S3_DIR / "raw_runs.csv"
P3_RUNNER = PACKAGE / "run_p3_china81_formal.py"

for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_p3_china81_formal as p3  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import (  # noqa: E402
    _arc_loads,
    _evaluate_route,
    evaluate,
    route_node_schedule,
)
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)

TABLE_FIELDS = [
    "路径", "距离(km)", "成本(元)", "时间(h)", "油耗(L)",
    "电耗(kWh)", "碳排放(kg)", "num(满足时窗客户数)", "装载率(%)",
    "vehicle_id", "vehicle_type", "ev_drive_kwh", "check_status",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_solution(payload: dict[str, Any]) -> Solution:
    routes = [
        Route(
            vehicle_id=str(row["vehicle_id"]),
            vehicle_type=str(row["vehicle_type"]),
            home_depot_id=str(row["home_depot_id"]),
            node_sequence=[str(item) for item in row["node_sequence"]],
        )
        for row in payload["routes"]
    ]
    actions = [
        ChargingAction(
            vehicle_id=str(row["vehicle_id"]),
            station_id=str(row["station_id"]),
            energy_kwh=float(row["energy_kwh"]),
            occupancy_minutes=float(row["occupancy_minutes"]),
            charge_start_second=float(row["charge_start_second"]),
            charge_day_offset=int(row.get("charge_day_offset", 0)),
            start_energy_kwh=None if row.get("start_energy_kwh") is None else float(row["start_energy_kwh"]),
            end_energy_kwh=None if row.get("end_energy_kwh") is None else float(row["end_energy_kwh"]),
            charging_curve_id=row.get("charging_curve_id"),
        )
        for row in payload.get("charging_actions", [])
    ]
    services = [
        CrossSiteService(
            customer_id=str(row["customer_id"]),
            served_by_depot_id=str(row["served_by_depot_id"]),
        )
        for row in payload.get("cross_site_services", [])
    ]
    return Solution(routes=routes, charging_actions=actions, cross_site_services=services)


def _load_best() -> tuple[str, int, float, Path, Solution, Any]:
    decision = json.loads(S3_DECISION.read_text(encoding="utf-8"))
    if decision.get("decision") != "PASS_S3_REPRESENTATIVE":
        raise RuntimeError(f"S3 is not PASS: {decision.get('decision')!r}")
    representative = str(decision["representative_instance_id"])
    rows = [
        row for row in csv.DictReader(S3_RAW.open(encoding="utf-8"))
        if row["instance_id"] == representative
        and row["arm"] == "MV-HGS-SP"
        and row["status"] == "OK"
    ]
    if len(rows) != 10:
        raise RuntimeError(f"expected 10 usable MV-HGS-SP rows, got {len(rows)}")
    row = min(rows, key=lambda item: (float(item["cost"]), int(item["seed"])))
    witness = S3_DIR / row["witness_file"]
    if not witness.is_file():
        raise RuntimeError(f"missing best-run witness: {witness}")
    payload = json.loads(witness.read_text(encoding="utf-8"))
    bundle = p3.load_china81_bundle(ROOT, representative)
    return representative, int(row["seed"]), float(row["cost"]), witness, _load_solution(payload), bundle


def _route_services(route: Route, bundle: Any) -> list[CrossSiteService]:
    return [
        CrossSiteService(customer_id=node_id, served_by_depot_id=route.home_depot_id)
        for node_id in route.node_sequence[1:-1]
        if bundle.customer_home_depot.get(node_id) is not None
        and bundle.customer_home_depot[node_id] != route.home_depot_id
    ]


def _route_row(route: Route, solution: Solution, bundle: Any) -> dict[str, Any]:
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    actions = [action for action in solution.charging_actions if action.vehicle_id == route.vehicle_id]
    route_solution = Solution(routes=[route], charging_actions=actions, cross_site_services=_route_services(route, bundle))
    route_solution = annotate_cross_site_services(route_solution, bundle.customer_home_depot)
    route_violations = check_solution(route_solution, bundle.instance, bundle.prices)
    route_breakdown = evaluate(route_solution, bundle.instance, bundle.time_profile, bundle.prices)
    route_energy = _evaluate_route(route, bundle.instance, node_lookup, bundle.prices)
    schedule = route_node_schedule(route, bundle.instance, bundle.prices, charging_actions=actions)
    if not schedule:
        raise RuntimeError(f"empty route schedule for {route.vehicle_id}")
    customers = [node_lookup[node_id] for node_id in route.node_sequence if node_lookup[node_id].node_type.lower() == "c"]
    served_on_time = sum(
        1 for item in schedule
        if node_lookup[item.node_id].node_type.lower() == "c"
        and item.t_start >= node_lookup[item.node_id].ready_time - 1.0e-9
        and item.t_start <= node_lookup[item.node_id].due_time + 1.0e-9
    )
    loads = _arc_loads(route.node_sequence, node_lookup)
    capacity = bundle.instance.payload_capacity_kg(route.vehicle_type, fallback=1.0)
    load_pct = 100.0 * max(loads, default=0.0) / capacity
    path = ">".join(route.node_sequence)
    return {
        "路径": path,
        "距离(km)": route_energy.distance_m / 1000.0,
        "成本(元)": route_breakdown["total_cost"],
        "时间(h)": (schedule[-1].t_arrive - schedule[0].t_start) / 3600.0,
        "油耗(L)": route_energy.fuel_liters,
        "电耗(kWh)": route_breakdown["electricity_kwh"],
        "碳排放(kg)": route_breakdown["E_total"],
        "num(满足时窗客户数)": served_on_time,
        "装载率(%)": load_pct,
        "vehicle_id": route.vehicle_id,
        "vehicle_type": route.vehicle_type,
        "ev_drive_kwh": route_energy.ev_drive_kwh,
        "check_status": "PASS" if not route_violations else "FAIL",
        "_route_violation_count": len(route_violations),
        "_customers": len(customers),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TABLE_FIELDS)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in TABLE_FIELDS} for row in rows])


def _hash_paths() -> list[Path]:
    paths = [
        P3_RUNNER, S3_DECISION, S3_RAW, OUT / "task_card.md",
        OUT / "run_s4_route_detail.py", OUT / "best_solution_witness.json",
        OUT / "route_details.csv", OUT / "metadata.json", OUT / "decision.json",
        OUT / "report.md",
    ]
    return [path for path in paths if path.exists() and not path.name.startswith("._")]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    representative, seed, recorded_cost, witness_path, solution, bundle = _load_best()
    checked_solution = annotate_cross_site_services(solution, bundle.customer_home_depot)
    direct_violations = check_solution(checked_solution, bundle.instance, bundle.prices)
    direct_breakdown = evaluate(checked_solution, bundle.instance, bundle.time_profile, bundle.prices)
    exact_cost, exact_breakdown, exact_violations = exact_china81_score(solution, bundle)
    cost_delta = abs(float(direct_breakdown["total_cost"]) - float(exact_cost))
    full_delta = abs(float(exact_cost) - float(recorded_cost))
    route_rows = [_route_row(route, checked_solution, bundle) for route in checked_solution.routes]
    route_failures = sum(int(row["_route_violation_count"]) for row in route_rows)
    numeric = ["距离(km)", "成本(元)", "时间(h)", "油耗(L)", "电耗(kWh)", "碳排放(kg)", "num(满足时窗客户数)"]
    mean_row = {field: fmean(float(row[field]) for row in route_rows) for field in numeric}
    mean_row.update({"路径": "均值", "装载率(%)": fmean(float(row["装载率(%)"]) for row in route_rows), "vehicle_id": "", "vehicle_type": "", "ev_drive_kwh": fmean(float(row["ev_drive_kwh"]) for row in route_rows), "check_status": "PASS"})
    total_row = {field: sum(float(row[field]) for row in route_rows) for field in numeric}
    total_row.update({"路径": "合计", "装载率(%)": max(float(row["装载率(%)"]) for row in route_rows), "vehicle_id": "", "vehicle_type": "", "ev_drive_kwh": sum(float(row["ev_drive_kwh"]) for row in route_rows), "check_status": "PASS"})
    rows = route_rows + [mean_row, total_row]
    _write_csv(OUT / "route_details.csv", rows)
    best_witness = json.loads(witness_path.read_text(encoding="utf-8"))
    best_witness.update({
        "s4_representative": representative, "s4_best_seed": seed,
        "s3_recorded_cost": recorded_cost, "s4_exact_cost": exact_cost,
        "s4_direct_cost": direct_breakdown["total_cost"],
        "s4_cost_delta_direct_vs_exact": cost_delta,
    })
    _write_json(OUT / "best_solution_witness.json", best_witness)
    passed = not direct_violations and not exact_violations and route_failures == 0 and cost_delta <= 1.0e-7 and full_delta <= 1.0e-5
    verdict = "PASS_S4_ROUTE_DETAIL" if passed else "HALT_S4_INDEPENDENT_RECHECK"
    decision = {
        "schema_version": "resetp.e2-final-campaign.s4-route-detail.v1",
        "decision": verdict,
        "representative_instance_id": representative, "best_seed": seed,
        "recorded_s3_cost": recorded_cost, "direct_cost": direct_breakdown["total_cost"],
        "exact_cost": exact_cost, "direct_vs_exact_abs_delta": cost_delta,
        "s3_vs_s4_abs_delta": full_delta,
        "full_solution_violation_count": len(exact_violations),
        "route_violation_count": route_failures,
        "route_rows": len(route_rows),
        "claim_boundary": "S4 is an independently checked route-detail witness; it does not change the S3 arm comparison or authorize a superiority claim.",
    }
    _write_json(OUT / "decision.json", decision)
    metadata = {
        "schema_version": "resetp.e2-final-campaign.s4-route-detail-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join([sys.executable, *sys.argv]),
        "git_head": _git_head(), "branch": "codex/reporting-pipeline",
        "python": sys.version, "python_executable": sys.executable,
        "platform": platform.platform(), "numpy_version": __import__("numpy").__version__,
        "representative_instance_id": representative, "best_seed": seed,
        "source_witness": str(witness_path.relative_to(ROOT)),
        "s3_decision_sha256": _sha256(S3_DECISION), "s3_raw_sha256": _sha256(S3_RAW),
        "protected_file_sha256": {str(path.relative_to(ROOT)): _sha256(path) for path in [P3_RUNNER] if path.exists()},
        "recalculation_sources": ["setp_solver.check.check_solution", "setp_solver.cost.evaluate", "setp_solver.cost.route_node_schedule", "setp_solver.china81_completion.exact_china81_score"],
        "integrity_flags": [],
    }
    _write_json(OUT / "metadata.json", metadata)
    report = [
        "# S4 Route detail independent recheck", "",
        f"Decision: `{verdict}`.", f"Representative `{representative}`, best seed `{seed}`.",
        f"Recorded S3 cost={recorded_cost:.9f}; direct cost={float(direct_breakdown['total_cost']):.9f}; exact cost={float(exact_cost):.9f}.",
        f"Direct/exact delta={cost_delta:.3g}; S3/S4 delta={full_delta:.3g}; full violations={len(exact_violations)}; route violations={route_failures}.",
        "", "`电耗(kWh)` is electricity supplied by charging actions; `ev_drive_kwh` is retained as an audit column. `装载率(%)` is the maximum arc load divided by the vehicle payload capacity; the total-row value is the maximum route load rate, not a sum.",
    ]
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    hash_paths = _hash_paths() + [OUT / "metadata.json", OUT / "decision.json", OUT / "report.md"]
    _write_json(OUT / "artifact_hashes.json", {
        "schema_version": "resetp.artifact-hashes.v1", "algorithm": "sha256",
        "appledouble_excluded": True,
        "files": {str(path.relative_to(ROOT)): _sha256(path) for path in hash_paths if path.exists() and not path.name.startswith("._")},
    })
    _write_json(OUT / "done.json", {"decision": verdict, "route_rows": len(route_rows), "artifact_hashes": "artifact_hashes.json", "completed_at_utc": datetime.now(timezone.utc).isoformat()})
    print(f"[S4] {verdict}", flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
