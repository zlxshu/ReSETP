#!/usr/bin/env python3
"""D6 full corrected China81 E2 rerun.

Each (instance, seed) executes the three frozen HGS views once under the
corrected authorities and finite fleet. The three single-view results are
read from those exact archives, and the same routes feed the time-limited MIP
recombination. This avoids duplicate search while preserving all four private
table algorithms.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from importlib.metadata import version
import json
import multiprocessing as mp
import os
import platform
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from route_pool_sp import run_hgs_route_pool_recombination  # noqa: E402
import scipy  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.cost import route_departure_second  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402


OUT = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v2_20260723/full_gate"
)
FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
SETTLEMENT = (
    REPO
    / "data/ChinaInstances/"
    "china81_spatiotemporal_settlement_authority_v1_20260723"
)
CATALOG = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723/"
    "instance_catalog.csv"
)
CONTRACT = (
    REPO
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v4_20260723.json"
)
SEEDS = (1, 2, 3, 4, 5)
VIEWS = {
    "HGS-F": "cv_only",
    "HGS-E": "naive_ev",
    "HGS-M": "mechanism_ev",
}
MAX_HGS_ITERATIONS_PER_VIEW = 5_000
ARCHIVE_CANDIDATES_PER_VIEW = 24
EXACT_ELITES_PER_VIEW = 8
COMPLETE_CANDIDATE_BUDGET = 80
MIP_TIME_LIMIT_SECONDS = 5.0
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _instance_ids() -> list[str]:
    with CATALOG.open(newline="", encoding="utf-8-sig") as handle:
        return sorted(row["instance_id"] for row in csv.DictReader(handle))


def _load_initial(instance_id: str) -> Solution:
    payload = json.loads(
        (FLEET / "witnesses" / f"{instance_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return Solution(
        routes=[
            Route(
                vehicle_id=row["vehicle_id"],
                vehicle_type=row["vehicle_type"],
                home_depot_id=row["home_depot_id"],
                node_sequence=list(row["node_sequence"]),
            )
            for row in payload["routes"]
        ]
    )


def _solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [
            {
                "vehicle_id": route.vehicle_id,
                "vehicle_type": route.vehicle_type,
                "home_depot_id": route.home_depot_id,
                "node_sequence": list(route.node_sequence),
            }
            for route in solution.routes
        ],
        "charging_actions": [
            {
                "vehicle_id": action.vehicle_id,
                "station_id": action.station_id,
                "energy_kwh": float(action.energy_kwh),
                "occupancy_minutes": float(action.occupancy_minutes),
                "charge_start_second": float(
                    action.charge_start_second
                ),
                "start_energy_kwh": action.start_energy_kwh,
                "end_energy_kwh": action.end_energy_kwh,
                "charging_curve_id": action.charging_curve_id,
                "charge_day_offset": int(action.charge_day_offset),
            }
            for action in solution.charging_actions
        ],
        "cross_site_services": [
            {
                "customer_id": item.customer_id,
                "served_by_depot_id": item.served_by_depot_id,
            }
            for item in solution.cross_site_services
        ],
    }


def _require_same_day_charging(
    solution: Solution,
    bundle: Any,
) -> None:
    routes = {
        route.vehicle_id: route
        for route in solution.routes
    }
    for action in solution.charging_actions:
        start = float(action.charge_start_second)
        end = start + float(action.occupancy_minutes) * 60.0
        if (
            int(action.charge_day_offset) != 0
            or start < -1.0e-9
            or end > 86_400.0 + 1.0e-9
        ):
            raise RuntimeError(
                "HALT_D6_CHARGING_DATE_BOUNDARY:"
                f"{action.vehicle_id}:{start}:{end}:"
                f"{action.charge_day_offset}"
            )
        node = bundle.instance.nodes[
            bundle.instance.node_index[action.station_id]
        ]
        if node.node_type.lower() != "d":
            continue
        route = routes[action.vehicle_id]
        departure = route_departure_second(
            route,
            bundle.instance,
            bundle.prices,
        )
        if end > departure + 1.0e-9:
            raise RuntimeError(
                "HALT_D6_DEPOT_CHARGE_AFTER_DEPARTURE:"
                f"{action.vehicle_id}:{end}>{departure}"
            )


def _source_hashes() -> dict[str, str]:
    paths = (
        CONTRACT,
        FLEET / "artifact_hashes.json",
        SETTLEMENT / "artifact_hashes.json",
        PROTOTYPE / "pyvrp_adapter.py",
        PROTOTYPE / "epochal_hgs.py",
        PROTOTYPE / "route_pool_sp.py",
        REPO / "solver/src/setp_solver/china81.py",
        REPO / "solver/src/setp_solver/china81_completion.py",
        REPO / (
            "solver/src/setp_solver/algorithms/resetp_alns/"
            "support/charging.py"
        ),
        REPO / "solver/src/setp_solver/prices.py",
        REPO / "solver/src/setp_solver/charging_curve.py",
        REPO / "solver/src/setp_solver/instance_loader.py",
        REPO / "solver/src/setp_solver/solution.py",
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/check.py",
        Path(__file__).resolve(),
    )
    return {
        str(path.relative_to(REPO)): file_sha256(path)
        for path in paths
    }


def _run_unit(args: tuple[str, int]) -> dict[str, Any]:
    instance_id, seed = args
    task_id = f"D6-E2__{instance_id}__seed{seed}"
    task_dir = OUT / "tasks" / task_id
    decision_path = task_dir / "decision.json"
    if decision_path.is_file():
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        if decision.get("verdict") == "PASS_D6_E2_TASK":
            return decision["raw_row"]
        raise RuntimeError(f"existing task is not PASS: {task_id}")

    bundle = load_china81_bundle(REPO, instance_id)
    initial = _load_initial(instance_id)
    customer_count = sum(
        node.node_type.lower() == "c"
        for node in bundle.instance.nodes
    )
    safety_seconds = max(180.0, 2.0 * customer_count)
    run = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=int(seed),
        hgs_seconds_per_view=None,
        exact_elites_per_view=EXACT_ELITES_PER_VIEW,
        max_archive_candidates_per_view=(
            ARCHIVE_CANDIDATES_PER_VIEW
        ),
        sp_time_limit_seconds=MIP_TIME_LIMIT_SECONDS,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=(
            MAX_HGS_ITERATIONS_PER_VIEW
        ),
        wallclock_safety_seconds_per_view=safety_seconds,
    )
    if run.stats["wallclock_safety_triggered"]:
        raise RuntimeError(f"HALT_SAFETY_WALLCLOCK:{task_id}")
    if (
        run.stats["complete_candidate_evaluation_attempts"]
        != COMPLETE_CANDIDATE_BUDGET
        or not run.stats[
            "complete_candidate_budget_exactly_consumed"
        ]
    ):
        raise RuntimeError(f"HALT_COMPLETE_BUDGET:{task_id}")

    solutions: dict[str, Solution] = {}
    costs: dict[str, float] = {}
    elapsed_by_arm: dict[str, float] = {}
    for label, mode in VIEWS.items():
        epoch = run.view_epochs[mode]
        best = min(
            (*epoch.elite_completions, epoch.proxy_best_completion),
            key=lambda item: item.objective,
        )
        solutions[label] = annotate_cross_site_services(
            best.solution,
            bundle.customer_home_depot,
        )
        costs[label] = float(best.objective)
        elapsed_by_arm[label] = float(epoch.elapsed_seconds)
    solutions["MV-HGS-SP"] = annotate_cross_site_services(
        run.solution,
        bundle.customer_home_depot,
    )
    costs["MV-HGS-SP"] = float(run.completion.objective)
    elapsed_by_arm["MV-HGS-SP"] = float(run.elapsed_seconds)
    breakdowns: dict[str, dict[str, float]] = {}
    for label, solution in solutions.items():
        _require_same_day_charging(solution, bundle)
        objective, breakdown, violations = exact_china81_score(
            solution,
            bundle,
        )
        if violations or abs(objective - costs[label]) > 1e-9:
            raise RuntimeError(
                f"HALT_D6_E2_RECHECK:{task_id}:{label}"
            )
        breakdowns[label] = breakdown

    witnesses = {
        label: _solution_payload(solution)
        for label, solution in solutions.items()
    }
    witness_path = task_dir / "solution_witnesses.json"
    write_json(witness_path, witnesses)
    mip = run.stats["route_pool_mip"]
    raw_row = {
        "task_id": task_id,
        "instance_id": instance_id,
        "region": bundle.region,
        "tier": customer_count,
        "seed": int(seed),
        "HGS-F_cost": costs["HGS-F"],
        "HGS-F_cpu_seconds": elapsed_by_arm["HGS-F"],
        "HGS-E_cost": costs["HGS-E"],
        "HGS-E_cpu_seconds": elapsed_by_arm["HGS-E"],
        "HGS-M_cost": costs["HGS-M"],
        "HGS-M_cpu_seconds": elapsed_by_arm["HGS-M"],
        "MV-HGS-SP_cost": costs["MV-HGS-SP"],
        "MV-HGS-SP_cpu_seconds": elapsed_by_arm["MV-HGS-SP"],
        "HGS-F_emissions_kg": breakdowns["HGS-F"]["E_total"],
        "HGS-E_emissions_kg": breakdowns["HGS-E"]["E_total"],
        "HGS-M_emissions_kg": breakdowns["HGS-M"]["E_total"],
        "MV-HGS-SP_emissions_kg": (
            breakdowns["MV-HGS-SP"]["E_total"]
        ),
        "complete_candidate_attempts": run.stats[
            "complete_candidate_evaluation_attempts"
        ],
        "wallclock_safety_triggered": False,
        "all_charging_on_registered_date": True,
        "all_depot_charging_finishes_before_departure": True,
        "mip_status": mip["status"],
        "mip_status_class": mip["status_class"],
        "mip_message": mip["message"],
        "mip_incumbent_available": mip["incumbent_available"],
        "mip_objective": mip["objective"],
        "mip_dual_bound": mip["dual_bound"],
        "mip_gap": mip["mip_gap"],
        "mip_node_count": mip["mip_node_count"],
        "mip_time_limit_seconds": mip["time_limit_seconds"],
        "mip_optimality_proven": mip["optimality_proven"],
        "selected_source": run.stats["selected_source"],
        "witness_sha256": file_sha256(witness_path),
        "input_manifest_sha256": payload_sha256(
            dict(bundle.source_paths)
        ),
        "responsibility_map_sha256": payload_sha256(
            dict(bundle.customer_home_depot)
        ),
        "status": "PASS",
    }
    write_csv(task_dir / "raw_runs.csv", [raw_row])
    write_json(
        task_dir / "metadata.json",
        {
            "schema": "resetp.d6-e2-corrected-task.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "task_id": task_id,
            "python": sys.version,
            "platform": platform.platform(),
            "pyvrp_version": version("pyvrp"),
            "scipy_version": scipy.__version__,
            "thread_environment": {
                key: os.environ.get(key)
                for key in REQUIRED_THREAD_ENV
            },
            "source_hashes": _source_hashes(),
        },
    )
    write_json(
        decision_path,
        {
            "schema": "resetp.d6-e2-corrected-task.decision.v1",
            "verdict": "PASS_D6_E2_TASK",
            "raw_row": raw_row,
        },
    )
    (task_dir / "report.md").write_text(
        f"# D6 corrected E2 task {task_id}\n\n"
        "Three single-view algorithms and MV-HGS-SP share the corrected "
        "China81 bundle, finite fleet, common seed, common initial witness "
        "and complete evaluator. All four returned solutions pass the full "
        "checker. This private comparison is descriptive and makes no "
        "equal-compute claim between a single view and the three-view fusion.\n",
        encoding="utf-8",
    )
    hashes = {
        path.name: file_sha256(path)
        for path in sorted(task_dir.iterdir())
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        task_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": hashes,
        },
    )
    return raw_row


def _finalize() -> dict[str, Any]:
    rows = []
    for path in sorted((OUT / "tasks").glob("*/raw_runs.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows.extend(csv.DictReader(handle))
    expected = len(_instance_ids()) * len(SEEDS)
    if len(rows) != expected:
        raise RuntimeError(
            f"D6 E2 incomplete: expected {expected}, found {len(rows)}"
        )
    if any(row["status"] != "PASS" for row in rows):
        raise RuntimeError("D6 E2 contains non-PASS tasks")
    write_csv(OUT / "raw_runs.csv", rows)
    decision = {
        "schema": "resetp.d6-e2-corrected.decision.v1",
        "verdict": "PASS_D6_CORRECTED_CHINA81_E2_RAW",
        "instance_count": len(_instance_ids()),
        "seed_count": len(SEEDS),
        "task_count": len(rows),
        "returned_solution_count": len(rows) * 4,
        "full_model_feasible_solution_count": len(rows) * 4,
        "protected_historical_e2_artifacts_overwritten": False,
        "public_p1_reused_as_search": False,
        "claim_boundary": (
            "descriptive private comparison; no equal-compute claim between "
            "single-view and three-view algorithms"
        ),
        "next_gate": "S3 representative seeds 6-10 and S4-S5 rebuild",
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.d6-e2-corrected.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": _source_hashes(),
            "thread_environment": REQUIRED_THREAD_ENV,
        },
    )
    (OUT / "report.md").write_text(
        "# D6 corrected China81 private E2 rerun\n\n"
        "All 81 instances x 5 seeds completed under the corrected geography,"
        " road, date/city/slot energy, city diesel, finite fleet and charger "
        "scenario authorities. Each task emits four independently rechecked "
        "solutions and complete MIP status/bound/gap fields. Historical E2 "
        "raw artifacts remain untouched.\n",
        encoding="utf-8",
    )
    hashes = {
        str(path.relative_to(OUT)): file_sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "artifacts": hashes,
        },
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--finalize-only", action="store_true")
    args = parser.parse_args()
    if args.finalize_only:
        print(json.dumps(_finalize(), ensure_ascii=False, sort_keys=True))
        return 0
    if any(
        os.environ.get(key) != value
        for key, value in REQUIRED_THREAD_ENV.items()
    ):
        raise RuntimeError("single-thread environment is not fully locked")
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = [
        (instance_id, seed)
        for instance_id in _instance_ids()
        for seed in SEEDS
    ]
    with mp.get_context("spawn").Pool(processes=args.workers) as pool:
        for row in pool.imap_unordered(_run_unit, tasks):
            print(
                f"[D6-E2] {row['instance_id']} seed={row['seed']} PASS "
                f"full={float(row['MV-HGS-SP_cost']):.6f}",
                flush=True,
            )
    print(json.dumps(_finalize(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
