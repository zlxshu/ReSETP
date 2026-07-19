#!/usr/bin/env python3
"""Independent replay audit for the frozen SEG-GEN-01 warning gate."""

from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import solution_signature_hash  # noqa: E402
from prototype import independent_cost  # noqa: E402
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


OUT = HERE / "segment_generation_fresh_warning_gate"
BUNDLES = HERE / "fresh_donor03_segment_bundles"
TASKS = (
    "DEV-seggen-donor03-25c",
    "DEV-seggen-donor03-50c",
)
ARMS = ("control", "mechanism", "distance")
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
TOL = 1.0e-7
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO
    / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
)


def main() -> int:
    rows = list(csv.DictReader((OUT / "raw_runs.csv").open()))
    decision = _read_json(OUT / "decision.json")
    comparisons = _read_json(OUT / "comparisons.json")
    witnesses = _read_json(OUT / "solution_witnesses.json")
    metadata = _read_json(OUT / "metadata.json")

    checks: dict[str, bool] = {
        "six_rows": len(rows) == 6,
        "task_arm_matrix_exact": {
            (row["task"], row["arm"]) for row in rows
        }
        == {(task, arm) for task in TASKS for arm in ARMS},
        "machine_verdict_is_stop": (
            decision["verdict"] == "STOP_SEGMENT_GENERATOR_NO_RESCUE"
            and not decision["passed"]
        ),
        "cost_gate_passed": (
            int(decision["nonloss_count_vs_control"]) == 2
            and int(decision["strict_win_count_vs_control"]) == 1
            and int(decision["strict_win_count_vs_distance"]) == 1
        ),
        "wall_gate_failed": (
            not decision["checks"]["median_wall_ratio_at_most_1_25"]
            and not decision["checks"]["maximum_wall_ratio_at_most_1_50"]
        ),
        "no_execution_failures": not decision["execution_failures"],
        "source_drift_recorded_false": all(
            decision["drift_checks"].values()
        ),
    }
    replays: list[dict[str, Any]] = []
    signatures_by_task: dict[str, set[str]] = {
        task: set() for task in TASKS
    }
    for row in rows:
        task = row["task"]
        arm = row["arm"]
        solution = _solution(
            witnesses[task]["arms"][arm]["solution"]
        )
        bundle_dir = BUNDLES / task
        bundle = load_search_bundle(bundle_dir)
        cost = independent_cost(bundle_dir, solution, PRICES)
        violations = check_solution(solution, bundle.instance, PRICES)
        signature = solution_signature_hash(solution)
        signatures_by_task[task].add(row["start_signature"])
        replay = {
            "task": task,
            "arm": arm,
            "cost": cost,
            "reported_cost": float(row["parent_recomputed_cost"]),
            "cost_match": (
                abs(cost - float(row["parent_recomputed_cost"])) <= TOL
            ),
            "feasible": not violations,
            "signature_match": signature == row["final_signature"],
            "ledger_closed": row["ledger_closed"] == "True",
            "objective_match": row["objective_match"] == "True",
        }
        replays.append(replay)
    checks["all_costs_replayed"] = all(
        item["cost_match"] for item in replays
    )
    checks["all_solutions_feasible"] = all(
        item["feasible"] for item in replays
    )
    checks["all_signatures_match"] = all(
        item["signature_match"] for item in replays
    )
    checks["all_ledgers_closed"] = all(
        item["ledger_closed"] and item["objective_match"]
        for item in replays
    )
    checks["same_start_within_each_task"] = all(
        len(values) == 1 for values in signatures_by_task.values()
    )
    checks["comparison_costs_reproduce"] = _check_comparisons(
        rows, comparisons
    )
    checks["protected_hashes_match"] = {
        str(path.relative_to(REPO)): _sha(path)
        for path in PROTECTED
    } == metadata["protected_hashes"]

    result = {
        "schema_version": "resetp.seg-gen-01.independent-audit.v1",
        "passed": all(checks.values()),
        "checks": checks,
        "replays": replays,
        "claim_boundary": (
            "Independent saved-solution replay only; no search was rerun. "
            "The locked STOP verdict remains authoritative."
        ),
    }
    _write_json(OUT / "independent_audit.json", result)
    _write_artifact_hashes()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


def _check_comparisons(
    rows: list[dict[str, str]],
    comparisons: list[dict[str, Any]],
) -> bool:
    by_key = {
        (row["task"], row["arm"]): float(
            row["parent_recomputed_cost"]
        )
        for row in rows
    }
    for item in comparisons:
        task = item["task"]
        control = by_key[(task, "control")]
        mechanism = by_key[(task, "mechanism")]
        distance = by_key[(task, "distance")]
        if abs(item["control_cost"] - control) > TOL:
            return False
        if abs(item["mechanism_cost"] - mechanism) > TOL:
            return False
        if abs(item["distance_cost"] - distance) > TOL:
            return False
        if abs(
            item["mechanism_minus_control"] - (mechanism - control)
        ) > TOL:
            return False
        if abs(
            item["mechanism_minus_distance"] - (mechanism - distance)
        ) > TOL:
            return False
    return True


def _solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=list(row["node_sequence"]),
            )
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row["vehicle_id"]),
                station_id=str(row["station_id"]),
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(row["charge_start_second"]),
                charge_day_offset=int(row.get("charge_day_offset", 0)),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def _read_json(path: Path) -> Any:
    with path.open() as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")


def _write_artifact_hashes() -> None:
    payload = {
        path.name: _sha(path)
        for path in sorted(OUT.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _write_json(OUT / "artifact_hashes.json", payload)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
