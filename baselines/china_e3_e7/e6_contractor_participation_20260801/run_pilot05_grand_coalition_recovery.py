#!/usr/bin/env python3
"""Recover the E6 grand coalition with the successful E3-02 search budget."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from route_pool_sp import _route_pool_records, run_hgs_route_pool_recombination
from setp_solver.china81_completion import exact_china81_score

from baselines.china_e3_e7.e3_scattered_ownership_20260801 import (
    run_e3_capacity_rank_aligned as e3,
)

INSTANCE = e3.INSTANCE
SEED = 1
ITERATIONS = 100
ARCHIVE = 8
OUTPUT = HERE / "pilot05_grand_coalition_recovery_20260801"
E3_METADATA = e3.OUTPUT / "metadata.json"
E3_RAW = e3.OUTPUT / "raw_runs.csv"
PILOT04 = HERE / "pilot04_rank_aligned_direct_screen_20260801"
PILOT04_RAW = PILOT04 / "raw_runs.csv"
ROUTE_POOL_SOURCE = PROTOTYPE / "route_pool_sp.py"
PROTECTED = tuple(e3.base.PROTECTED)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, row: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def load_context() -> tuple[Any, Any, dict[str, Any], dict[str, Any]]:
    bundle, info = e3.prepare(INSTANCE)
    bundle = replace(bundle, prices=replace(bundle.prices, cross_site_cost=0.0))
    initial, route_counts = e3.base.build_common_initial(bundle)
    with E3_RAW.open(encoding="utf-8", newline="") as handle:
        e3_rows = list(csv.DictReader(handle))
    expected_mapping = {row["mapping_sha256"] for row in e3_rows}
    expected_initial = {row["initial_sha256"] for row in e3_rows}
    observed_initial = e3.base.solution_sha256(initial)
    if expected_mapping != {info["mapping_sha256"]}:
        raise RuntimeError("mapping hash differs from E3-02")
    if expected_initial != {observed_initial}:
        raise RuntimeError("common initial solution differs from E3-02")

    original = e3.base.load_bundle(INSTANCE)
    fleet = {depot: dict(row) for depot, row in bundle.fleet_caps_by_depot.items()}
    original_fleet = {
        depot: dict(row) for depot, row in original.fleet_caps_by_depot.items()
    }
    if fleet != original_fleet:
        raise RuntimeError("fleet differs from the original China81 caps")
    return bundle, initial, info, {
        "initial_sha256": observed_initial,
        "initial_route_counts": route_counts,
        "fleet_caps_by_depot": fleet,
    }


def source_audit() -> dict[str, Any]:
    expected = json.loads(E3_METADATA.read_text(encoding="utf-8"))["source_hashes"]
    observed = {name: sha256(REPO / name) for name in expected}
    matches = {name: observed[name] == value for name, value in expected.items()}
    if not all(matches.values()):
        raise RuntimeError("E3-02 source or protected hash changed")
    pilot04_hashes = json.loads(
        (PILOT04 / "artifact_hashes.json").read_text(encoding="utf-8")
    )
    pilot04_matches = {
        name: sha256(PILOT04 / name) == value
        for name, value in pilot04_hashes.items()
    }
    if not all(pilot04_matches.values()):
        raise RuntimeError("pilot04 artifact hash changed")
    return {
        "e3_expected": expected,
        "e3_observed": observed,
        "e3_all_match": True,
        "pilot04_artifacts_all_match": True,
        "runner_sha256": sha256(Path(__file__)),
        "route_pool_source_sha256": sha256(ROUTE_POOL_SOURCE),
    }


def pilot04_singleton_cost() -> float:
    with PILOT04_RAW.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    singletons = [
        float(row["cost_cny"])
        for row in rows
        if row["record_type"] == "COALITION"
        and int(row["coalition_member_count"]) == 1
        and row["status"] == "PASS"
    ]
    if len(singletons) != 4:
        raise RuntimeError("pilot04 does not contain four legal singleton costs")
    return sum(singletons)


def transfer_metrics(bundle: Any, solution: Any) -> tuple[int, float]:
    customers = {item.customer_id for item in solution.cross_site_services}
    demand = {
        node.node_id: float(node.demand)
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    return len(customers), sum(demand[customer] for customer in customers)


def mechanism_triggered(
    technical_valid: bool,
    final_cost: float,
    singleton_cost: float,
    cross_customers: int,
) -> bool:
    return technical_valid and final_cost < singleton_cost and cross_customers > 0


def route_pool_payload(bundle: Any, run: Any) -> dict[str, Any]:
    records = _route_pool_records(bundle, run.view_epochs)
    views = Counter(record.source_view for record in records)
    return {
        "schema": "resetp.e6-grand-coalition-route-pool.v1",
        "summary": {
            "record_count": len(records),
            "records_by_view": dict(sorted(views.items())),
            "minimum_route_cost_cny": min(record.route_cost for record in records),
            "maximum_route_cost_cny": max(record.route_cost for record in records),
        },
        "records": [
            {
                "source_view": record.source_view,
                "source_rank": record.source_rank,
                "route_cost_cny": record.route_cost,
                "customers": list(record.customers),
                "route": asdict(record.route),
                "charging_actions": [asdict(action) for action in record.actions],
            }
            for record in records
        ],
    }


def report_text(decision: dict[str, Any]) -> str:
    return (
        "# E6 grand-coalition recovery\n\n"
        f"状态：{decision['status']}。\n\n"
        f"共同初始解成本 {decision['initial_cost_cny']:.3f} 元，"
        f"最终成本 {decision['final_cost_cny']:.3f} 元。"
        f"pilot04 四家单干成本合计 {decision['pilot04_singleton_cost_cny']:.3f} 元，"
        f"最终大联盟相对少 {decision['saving_vs_pilot04_singletons_cny']:.3f} 元"
        f"（{decision['saving_vs_pilot04_singletons_percent']:.3f}%）。\n\n"
        f"最终方案有 {decision['cross_contractor_customers']} 个跨承包商客户，"
        f"对应 {decision['cross_contractor_quantity_kg']:.3f} kg。"
        f"技术合法={'是' if decision['technical_valid'] else '否'}，"
        f"机制触发={'是' if decision['mechanism_triggered'] else '否'}。\n"
    )


def run(output: Path = OUTPUT) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    audit = source_audit()
    bundle, initial, info, context = load_context()
    initial_cost, _, initial_violations = exact_china81_score(initial, bundle)
    if initial_violations:
        raise RuntimeError("E3-02 common initial solution is not legal")

    run_result = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=SEED,
        hgs_seconds_per_view=None,
        exact_elites_per_view=ARCHIVE,
        max_archive_candidates_per_view=ARCHIVE,
        sp_time_limit_seconds=5.0,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=ITERATIONS,
        wallclock_safety_seconds_per_view=180.0,
        exact_checkpoint_interval_iterations=None,
    )
    final_cost, breakdown, violations = exact_china81_score(
        run_result.solution, bundle
    )
    technical_valid = not violations and math.isclose(
        final_cost, run_result.completion.objective, abs_tol=1e-6
    )
    singleton_cost = pilot04_singleton_cost()
    cross_customers, cross_quantity = transfer_metrics(bundle, run_result.solution)
    triggered = mechanism_triggered(
        technical_valid, final_cost, singleton_cost, cross_customers
    )
    status = (
        "PASS_GRAND_COALITION_MECHANISM_TRIGGERED"
        if triggered
        else "HALT_GRAND_COALITION_RECOVERY_CRITERIA_NOT_MET"
    )
    pool = route_pool_payload(bundle, run_result)
    solution_payload = {
        "schema": "resetp.e6-grand-coalition-solution.v1",
        "instance_id": INSTANCE,
        "seed": SEED,
        "mapping_sha256": info["mapping_sha256"],
        "initial_sha256": context["initial_sha256"],
        "solution_sha256": e3.base.solution_sha256(run_result.solution),
        "objective_cny": final_cost,
        "breakdown": breakdown,
        "violations": [asdict(item) for item in violations],
        "solution": asdict(run_result.solution),
    }
    decision = {
        "status": status,
        "mechanism_triggered": triggered,
        "technical_valid": technical_valid,
        "instance_id": INSTANCE,
        "seed": SEED,
        "mapping_sha256": info["mapping_sha256"],
        "initial_sha256": context["initial_sha256"],
        "solution_sha256": solution_payload["solution_sha256"],
        "initial_cost_cny": initial_cost,
        "final_cost_cny": final_cost,
        "pilot04_singleton_cost_cny": singleton_cost,
        "saving_vs_pilot04_singletons_cny": singleton_cost - final_cost,
        "saving_vs_pilot04_singletons_percent": 100.0
        * (singleton_cost - final_cost)
        / singleton_cost,
        "cross_contractor_customers": cross_customers,
        "cross_contractor_quantity_kg": cross_quantity,
        "route_pool_records": pool["summary"]["record_count"],
        "complete_candidate_evaluations": run_result.stats[
            "complete_candidate_evaluation_attempts"
        ],
        "elapsed_seconds": run_result.elapsed_seconds,
        "violation_count": len(violations),
    }
    row = {
        **decision,
        "iterations_per_view": ITERATIONS,
        "archive_candidates_per_view": ARCHIVE,
        "cross_site_system_cost_cny": bundle.prices.cross_site_cost,
        "route_count": len(run_result.solution.routes),
        "used_cv": int(breakdown["n_veh_cv"]),
        "used_ev": int(breakdown["n_veh_ev"]),
        "distance_km": float(breakdown["distance_total"]) / 1000.0,
        "emissions_kg": float(breakdown["E_total"]),
    }
    metadata = {
        "schema": "resetp.e6-grand-coalition-recovery.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": "one four-contractor grand coalition only",
        "instance_id": INSTANCE,
        "seed": SEED,
        "iterations_per_view": ITERATIONS,
        "archive_candidates_per_view": ARCHIVE,
        "cross_site_system_cost_cny": bundle.prices.cross_site_cost,
        "mapping_sha256": info["mapping_sha256"],
        "initial_sha256": context["initial_sha256"],
        "initial_route_counts": context["initial_route_counts"],
        "fleet_caps_by_depot": context["fleet_caps_by_depot"],
        "hash_audit": audit,
        "protected_hashes": {
            str(path.relative_to(REPO)): sha256(path) for path in PROTECTED
        },
    }
    write_json(output / "solution.json", solution_payload)
    write_json(output / "route_pool_records.json", pool)
    write_json(output / "metadata.json", metadata)
    write_csv(output / "raw_runs.csv", row)
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(report_text(decision), encoding="utf-8")
    artifacts = {
        name: sha256(output / name)
        for name in (
            "metadata.json",
            "raw_runs.csv",
            "decision.json",
            "report.md",
            "solution.json",
            "route_pool_records.json",
        )
    }
    write_json(output / "artifact_hashes.json", artifacts)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
