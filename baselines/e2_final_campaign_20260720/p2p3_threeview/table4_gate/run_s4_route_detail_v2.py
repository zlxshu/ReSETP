#!/usr/bin/env python3
"""S4 revision: independently close route arithmetic without global fragment checks."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

import run_s4_route_detail as v1

ROOT = v1.ROOT
OUT = v1.OUT
S3_DIR = v1.S3_DIR
S3_DECISION = v1.S3_DECISION
S3_RAW = v1.S3_RAW
P3_RUNNER = v1.P3_RUNNER

TABLE_FIELDS = v1.TABLE_FIELDS
ADDITIVE_FIELDS = (
    "距离(km)", "成本(元)", "时间(h)", "油耗(L)",
    "电耗(kWh)", "碳排放(kg)", "num(满足时窗客户数)",
)
REL_TOL = 1.0e-6
ABS_TOL = 1.0e-6
COST_REL_TOL = 1.0e-9
COST_ABS_TOL = 1.0e-9
APPLEDOUBLE_FLAG = "HASH_CONTAMINATED_APPLEDOUBLE"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TABLE_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in TABLE_FIELDS} for row in rows)


def _close(left: float, right: float, *, rel: float = REL_TOL, absolute: float = ABS_TOL) -> bool:
    return math.isclose(float(left), float(right), rel_tol=rel, abs_tol=absolute)


def _clean_appledouble() -> int:
    sidecars = [path for path in OUT.rglob("._*") if path.is_file()]
    for path in sidecars:
        path.unlink()
    return len(sidecars)


def _route_row_v2(route: Any, solution: Any, bundle: Any) -> dict[str, Any]:
    """Recalculate one route's fields without applying whole-solution coverage rules."""
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    actions = [action for action in solution.charging_actions if action.vehicle_id == route.vehicle_id]
    route_solution = v1.Solution(
        routes=[route],
        charging_actions=actions,
        cross_site_services=v1._route_services(route, bundle),
    )
    route_solution = v1.annotate_cross_site_services(route_solution, bundle.customer_home_depot)
    route_breakdown = v1.evaluate(route_solution, bundle.instance, bundle.time_profile, bundle.prices)
    route_energy = v1._evaluate_route(route, bundle.instance, node_lookup, bundle.prices)
    schedule = v1.route_node_schedule(route, bundle.instance, bundle.prices, charging_actions=actions)
    if not schedule:
        raise RuntimeError(f"empty route schedule for {route.vehicle_id}")
    served_on_time = sum(
        1 for item in schedule
        if node_lookup[item.node_id].node_type.lower() == "c"
        and item.t_start >= node_lookup[item.node_id].ready_time - 1.0e-9
        and item.t_start <= node_lookup[item.node_id].due_time + 1.0e-9
    )
    loads = v1._arc_loads(route.node_sequence, node_lookup)
    capacity = bundle.instance.payload_capacity_kg(route.vehicle_type, fallback=1.0)
    load_pct = 100.0 * max(loads, default=0.0) / capacity
    row = {
        "路径": ">".join(route.node_sequence),
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
        "check_status": "PASS",
        "_schedule": schedule,
    }
    numeric = [*ADDITIVE_FIELDS, "装载率(%)", "ev_drive_kwh"]
    if any(not math.isfinite(float(row[field])) for field in numeric):
        raise RuntimeError(f"non-finite route arithmetic for {route.vehicle_id}")
    return row


def _full_operational_totals(solution: Any, bundle: Any) -> dict[str, float]:
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    total_time = 0.0
    total_num = 0
    max_load_pct = 0.0
    for route in solution.routes:
        actions = [action for action in solution.charging_actions if action.vehicle_id == route.vehicle_id]
        schedule = v1.route_node_schedule(route, bundle.instance, bundle.prices, charging_actions=actions)
        if not schedule:
            raise RuntimeError(f"empty full-solution route schedule for {route.vehicle_id}")
        total_time += (schedule[-1].t_arrive - schedule[0].t_start) / 3600.0
        total_num += sum(
            1 for item in schedule
            if node_lookup[item.node_id].node_type.lower() == "c"
            and item.t_start >= node_lookup[item.node_id].ready_time - 1.0e-9
            and item.t_start <= node_lookup[item.node_id].due_time + 1.0e-9
        )
        loads = v1._arc_loads(route.node_sequence, node_lookup)
        capacity = bundle.instance.payload_capacity_kg(route.vehicle_type, fallback=1.0)
        max_load_pct = max(max_load_pct, 100.0 * max(loads, default=0.0) / capacity)
    return {
        "时间(h)": total_time,
        "num(满足时窗客户数)": float(total_num),
        "装载率(%)": max_load_pct,
    }


def _coverage_audit(solution: Any, bundle: Any) -> dict[str, Any]:
    customer_ids = {
        node.node_id for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    visited = [
        node_id for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in customer_ids
    ]
    counts = Counter(visited)
    bad = {
        customer_id: counts.get(customer_id, 0)
        for customer_id in sorted(customer_ids)
        if counts.get(customer_id, 0) != 1
    }
    unknown = sorted(
        node_id for node_id in visited
        if node_id not in customer_ids
    )
    return {
        "customer_count": len(customer_ids),
        "visited_customer_entries": len(visited),
        "bad_customer_counts": bad,
        "unknown_customer_entries": unknown,
        "passed": not bad and not unknown and len(visited) == len(customer_ids),
    }


def _protected_hashes() -> dict[str, str]:
    paths = [
        ROOT / "solver/src/setp_solver/cost.py",
        ROOT / "solver/src/setp_solver/check.py",
        ROOT / "solver/src/setp_solver/search/evaluation.py",
        ROOT / "solver/src/setp_solver/prices.py",
        ROOT / "docs/paper_submission_final/paper_main.tex",
        P3_RUNNER,
        S3_RAW,
    ]
    return {str(path.relative_to(ROOT)): _sha256(path) for path in paths if path.exists()}


def _v1_source_paths() -> list[Path]:
    return [
        OUT / "task_card.md", OUT / "run_s4_route_detail.py",
        OUT / "best_solution_witness.json", OUT / "route_details.csv",
        OUT / "metadata.json", OUT / "decision.json", OUT / "report.md",
        OUT / "artifact_hashes_v1.json",
    ]


def _hash_paths() -> list[Path]:
    return [
        P3_RUNNER, S3_DECISION, S3_RAW,
        *_v1_source_paths(), OUT / "task_card_v2.md",
        OUT / "run_s4_route_detail_v2.py", OUT / "monitor_v2.json",
        OUT / "best_solution_witness_v2.json", OUT / "route_details_v2.csv",
        OUT / "metadata_v2.json", OUT / "decision_v2.json",
        OUT / "report_v2.md", OUT / "done_v2.json",
    ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    removed_before = _clean_appledouble()
    v1_manifest = OUT / "artifact_hashes.json"
    v1_archive = OUT / "artifact_hashes_v1.json"
    if not v1_archive.exists():
        shutil.copyfile(v1_manifest, v1_archive)
    source_v1_hashes = {
        str(path.relative_to(ROOT)): _sha256(path)
        for path in _v1_source_paths() if path.exists()
    }

    representative, seed, recorded_cost, witness_path, solution, bundle = v1._load_best()
    checked_solution = v1.annotate_cross_site_services(solution, bundle.customer_home_depot)
    direct_violations = v1.check_solution(checked_solution, bundle.instance, bundle.prices)
    direct_breakdown = v1.evaluate(checked_solution, bundle.instance, bundle.time_profile, bundle.prices)
    exact_cost, exact_breakdown, exact_violations = v1.exact_china81_score(checked_solution, bundle)
    coverage = _coverage_audit(checked_solution, bundle)
    operational = _full_operational_totals(checked_solution, bundle)

    route_rows = [_route_row_v2(route, checked_solution, bundle) for route in checked_solution.routes]
    route_sums = {
        field: sum(float(row[field]) for row in route_rows)
        for field in ADDITIVE_FIELDS
    }
    direct_totals = {
        "距离(km)": float(direct_breakdown["distance_total"]) / 1000.0,
        "成本(元)": float(direct_breakdown["total_cost"]),
        "油耗(L)": float(direct_breakdown["fuel_liters"]),
        "电耗(kWh)": float(direct_breakdown["electricity_kwh"]),
        "碳排放(kg)": float(direct_breakdown["E_total"]),
        **operational,
    }
    closure: dict[str, dict[str, Any]] = {}
    for field in ADDITIVE_FIELDS:
        left = route_sums[field]
        right = direct_totals[field]
        closure[field] = {
            "route_sum": left, "full_solution_value": right,
            "abs_delta": abs(left - right), "passed": _close(left, right),
        }
    route_max_load = max(float(row["装载率(%)"]) for row in route_rows)
    closure["装载率(%)"] = {
        "route_max": route_max_load,
        "full_solution_value": direct_totals["装载率(%)"],
        "abs_delta": abs(route_max_load - direct_totals["装载率(%)"]),
        "aggregation": "max_not_sum",
        "passed": _close(route_max_load, direct_totals["装载率(%)"]),
    }
    exact_fields = {
        "距离(km)": "distance_total", "成本(元)": "total_cost",
        "油耗(L)": "fuel_liters", "电耗(kWh)": "electricity_kwh",
        "碳排放(kg)": "E_total",
    }
    direct_exact: dict[str, dict[str, Any]] = {}
    for field, key in exact_fields.items():
        left = float(direct_breakdown[key])
        right = float(exact_breakdown[key])
        direct_exact[field] = {
            "direct": left, "exact": right,
            "abs_delta": abs(left - right), "passed": _close(left, right),
        }

    cost_match = (
        _close(recorded_cost, direct_breakdown["total_cost"], rel=COST_REL_TOL, absolute=COST_ABS_TOL)
        and _close(recorded_cost, exact_cost, rel=COST_REL_TOL, absolute=COST_ABS_TOL)
    )
    passed = (
        not direct_violations and not exact_violations and coverage["passed"]
        and all(item["passed"] for item in closure.values())
        and all(item["passed"] for item in direct_exact.values())
        and cost_match
    )

    numeric = [*ADDITIVE_FIELDS]
    mean_row = {field: fmean(float(row[field]) for row in route_rows) for field in numeric}
    mean_row.update({
        "路径": "均值", "装载率(%)": fmean(float(row["装载率(%)"]) for row in route_rows),
        "vehicle_id": "", "vehicle_type": "",
        "ev_drive_kwh": fmean(float(row["ev_drive_kwh"]) for row in route_rows),
        "check_status": "PASS",
    })
    total_row = {field: route_sums[field] for field in numeric}
    total_row.update({
        "路径": "合计", "装载率(%)": route_max_load,
        "vehicle_id": "", "vehicle_type": "",
        "ev_drive_kwh": sum(float(row["ev_drive_kwh"]) for row in route_rows),
        "check_status": "PASS",
    })
    rows = route_rows + [mean_row, total_row]
    _write_csv(OUT / "route_details_v2.csv", rows)

    best_witness = json.loads(witness_path.read_text(encoding="utf-8"))
    best_witness.update({
        "s4_revision": "S4-REV-V2",
        "s4_representative": representative, "s4_best_seed": seed,
        "s3_recorded_cost": recorded_cost, "s4_exact_cost": exact_cost,
        "s4_direct_cost": direct_breakdown["total_cost"],
        "s4_cost_delta_direct_vs_exact": abs(float(direct_breakdown["total_cost"]) - float(exact_cost)),
        "coverage_audit": coverage, "arithmetic_closure": closure,
    })
    _write_json(OUT / "best_solution_witness_v2.json", best_witness)

    verdict = "PASS_S4_ROUTE_DETAIL" if passed else "HALT_S4_INDEPENDENT_RECHECK"
    decision = {
        "schema_version": "resetp.e2-final-campaign.s4-route-detail-v2.v1",
        "decision": verdict,
        "source_decision_v1": "decision.json",
        "v1_halt_cause": "The v1 runner applied global check_solution to one-route fragments; the resulting 400 CUSTOMER_COVERAGE rows represented customers absent from each fragment, not violations in the full solution.",
        "v2_check_policy": {
            "full_solution_global_check": "check_solution + exact_china81_score",
            "route_fragment_check": "arithmetic recomputation only; no global customer coverage check",
            "coverage_check": "full solution only; every customer exactly once",
            "additive_closure_relative_tolerance": REL_TOL,
            "load_rate_closure": "maximum route load rate, not a sum",
        },
        "representative_instance_id": representative, "best_seed": seed,
        "recorded_s3_cost": recorded_cost, "direct_cost": direct_breakdown["total_cost"],
        "exact_cost": exact_cost,
        "direct_vs_exact_abs_delta": abs(float(direct_breakdown["total_cost"]) - float(exact_cost)),
        "s3_vs_s4_abs_delta": abs(float(exact_cost) - float(recorded_cost)),
        "full_solution_violation_count": len(exact_violations),
        "full_solution_check_violation_count": len(direct_violations),
        "coverage_audit": coverage,
        "arithmetic_closure": closure,
        "direct_exact_breakdown": direct_exact,
        "cost_match": cost_match,
        "route_rows": len(route_rows),
        "v1_route_violation_count": 400,
        "claim_boundary": "S4 is an independently checked route-detail witness; it does not change the S3 arm comparison or authorize a superiority claim.",
    }
    _write_json(OUT / "decision_v2.json", decision)
    metadata = {
        "schema_version": "resetp.e2-final-campaign.s4-route-detail-metadata-v2.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join([str(Path(__file__).resolve()), "S4-REV-V2"]),
        "python": v1.sys.version, "python_executable": v1.sys.executable,
        "platform": platform.platform(),
        "representative_instance_id": representative, "best_seed": seed,
        "source_witness": str(witness_path.relative_to(ROOT)),
        "source_decision_v1_sha256": _sha256(OUT / "decision.json"),
        "source_report_v1_sha256": _sha256(OUT / "report.md"),
        "source_metadata_v1_sha256": _sha256(OUT / "metadata.json"),
        "source_route_details_v1_sha256": _sha256(OUT / "route_details.csv"),
        "source_artifact_hashes_v1_sha256": _sha256(v1_archive),
        "s3_decision_sha256": _sha256(S3_DECISION), "s3_raw_sha256": _sha256(S3_RAW),
        "protected_file_sha256": _protected_hashes(),
        "recalculation_sources": [
            "setp_solver.check.check_solution (full solution only)",
            "setp_solver.cost.evaluate", "setp_solver.cost.route_node_schedule",
            "setp_solver.china81_completion.exact_china81_score",
        ],
        "appledouble_sidecars_removed_before_revision": removed_before,
        "integrity_flags": [APPLEDOUBLE_FLAG] if removed_before else [],
        "source_v1_hashes": source_v1_hashes,
    }
    _write_json(OUT / "metadata_v2.json", metadata)
    report = [
        "# S4 Route detail independent recheck — v2", "",
        f"Decision: `{verdict}`.", f"Representative `{representative}`, best seed `{seed}`.",
        "The v1 HALT was an acceptance-script bug: global `check_solution` was applied to each one-route fragment, so customers served by the other eight routes were reported as 400 pseudo `CUSTOMER_COVERAGE` violations.",
        "The v2 runner applies global `check_solution` and `exact_china81_score` only to the complete solution, checks every customer exactly once at that level, and uses arithmetic-only route-fragment recomputation plus full-solution closure.",
        f"Recorded S3 cost={recorded_cost:.12f}; direct cost={float(direct_breakdown['total_cost']):.12f}; exact cost={float(exact_cost):.12f}.",
        f"Full check violations={len(direct_violations)}; exact violations={len(exact_violations)}; unique-coverage pass={coverage['passed']}; cost match={cost_match}.",
        "",
        "Arithmetic closure (route sum versus complete-solution value):",
    ]
    for field, item in closure.items():
        left = item.get("route_sum", item.get("route_max"))
        report.append(f"- `{field}`: route={left:.12f}; full={item['full_solution_value']:.12f}; delta={item['abs_delta']:.3g}; pass={item['passed']}.")
    report.append("- `装载率(%)` uses the maximum route load rate for the total row, not a sum.")
    report.append("\nNo solution, witness, protected evaluator, primary configuration, P3 raw data, or main TeX was changed; this revision only re-accepts the sealed witness.")
    (OUT / "report_v2.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    _clean_appledouble()
    hash_paths = [path for path in _hash_paths() if path.exists() and not path.name.startswith("._") and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts]
    _write_json(OUT / "artifact_hashes.json", {
        "schema_version": "resetp.artifact-hashes.v2",
        "algorithm": "sha256", "appledouble_excluded": True,
        "integrity_flags": [APPLEDOUBLE_FLAG] if removed_before else [],
        "source_v1_manifest": "artifact_hashes_v1.json",
        "files": {str(path.relative_to(ROOT)): _sha256(path) for path in hash_paths},
    })
    _write_json(OUT / "done_v2.json", {
        "decision": verdict, "route_rows": len(route_rows),
        "artifact_hashes": "artifact_hashes.json",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    removed_after = _clean_appledouble()
    if removed_after:
        print(f"[S4-REV-V2] removed {removed_after} post-write AppleDouble sidecars", flush=True)
    print(f"[S4-REV-V2] {verdict}", flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
