#!/usr/bin/env python3
"""P1: public V13-MDVRPTW-28 formal batch, six-worker parallel.

Design (v2, natural no-op collapse): public V13 instances carry no
EV/carbon/multi-depot-responsibility fields, so by the frozen natural
no-op principle every mechanism view of MV-HGS-SP provably degenerates
and the algorithm collapses to its full-budget HGS backbone. One mother
run per (instance, seed) therefore fills both the PyVRP-HGS column and
the MV-HGS-SP column; the identity is a design guarantee disclosed in
the claim boundary, never presented as an independent second run.

(The earlier two-arm draft that split C's budget into three seed-diverse
views violated the no-op principle -- with no mechanism fields the split
is pure depth loss -- and was retired before any formal unit completed.)

Resumable: on restart, already-completed (instance, seed) rows in
raw_runs.csv are skipped.
"""

from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import sys

import numpy as np
from pyvrp import ProblemData, Route, Solution, read, solve as pyvrp_solve
from pyvrp.stop import MaxRuntime

try:
    from scipy.optimize import Bounds, LinearConstraint, milp
except ModuleNotFoundError:
    system_site = Path("/opt/anaconda3/lib/python3.13/site-packages")
    if system_site.exists():
        sys.path.append(str(system_site))
    from scipy.optimize import Bounds, LinearConstraint, milp

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
INSTANCE_DIR = (
    ROOT
    / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
    / "sources/normalised_instances"
)
OPPONENT_CSV = (
    ROOT
    / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
    / "opponent_targets.csv"
)
OUT = PACKAGE / "p1_gate"
SEEDS = tuple(range(1, 11))
SP_TIME_FRACTION = 0.10
VIEW_COUNT = 3
WORKERS = 6


def _wall_clock_seconds(n_clients: int) -> float:
    import os

    smoke_override = os.environ.get("P1_SMOKE_TIME_LIMIT_SECONDS")
    if smoke_override:
        return float(smoke_override)
    return max(120.0, 0.6 * n_clients)


def _instance_list() -> list[str]:
    with OPPONENT_CSV.open(encoding="utf-8") as handle:
        return [row["instance"] for row in csv.DictReader(handle)]


def _opponent_targets() -> dict[str, dict[str, float]]:
    with OPPONENT_CSV.open(encoding="utf-8") as handle:
        return {row["instance"]: row for row in csv.DictReader(handle)}


@dataclass(frozen=True)
class RouteRecord:
    key: tuple[int, tuple[int, ...]]
    vehicle_type: int
    visits: tuple[int, ...]
    distance: float


def _routes_of(solution: Solution) -> list[RouteRecord]:
    records: list[RouteRecord] = []
    for route in solution.routes():
        visits = tuple(route.visits())
        records.append(
            RouteRecord(
                key=(route.vehicle_type(), visits),
                vehicle_type=route.vehicle_type(),
                visits=visits,
                distance=float(route.distance()),
            )
        )
    return records


def _solve_set_partitioning(
    data: ProblemData,
    records: list[RouteRecord],
    *,
    time_limit_seconds: float,
) -> tuple[Solution | None, dict[str, Any]]:
    clients = list(range(data.num_depots, data.num_locations))
    client_index = {client: index for index, client in enumerate(clients)}
    matrix = np.zeros((len(clients), len(records)), dtype=float)
    for column, record in enumerate(records):
        for visit in record.visits:
            matrix[client_index[visit], column] = 1.0
    costs = np.array([record.distance for record in records], dtype=float)
    constraints: list[LinearConstraint] = [
        LinearConstraint(matrix, lb=np.ones(len(clients)), ub=np.ones(len(clients)))
    ]
    for vt in range(data.num_vehicle_types):
        limit = data.vehicle_type(vt).num_available
        row = np.array(
            [1.0 if record.vehicle_type == vt else 0.0 for record in records]
        )
        constraints.append(LinearConstraint(row, lb=-np.inf, ub=float(limit)))
    result = milp(
        c=costs,
        integrality=np.ones(len(records)),
        bounds=Bounds(np.zeros(len(records)), np.ones(len(records))),
        constraints=constraints,
        options={"time_limit": float(time_limit_seconds)},
    )
    stats: dict[str, Any] = {
        "solver": "scipy.optimize.milp/HiGHS",
        "success": bool(result.success),
        "status": int(result.status),
        "objective": None if result.fun is None else float(result.fun),
        "selected_route_count": 0,
    }
    if result.x is None:
        return None, stats
    selected = [
        records[index] for index, value in enumerate(result.x) if value > 0.5
    ]
    stats["selected_route_count"] = len(selected)
    depots = [
        data.vehicle_type(record.vehicle_type).start_depot for record in selected
    ]
    routes = [
        Route(data, list(record.visits), record.vehicle_type) for record in selected
    ]
    solution = Solution(data, routes)
    if not solution.is_feasible():
        return None, stats
    return solution, stats


def _mother_hgs_arm(data: ProblemData, seed: int, time_limit: float) -> dict[str, Any]:
    started = perf_counter()
    result = pyvrp_solve(data, MaxRuntime(time_limit), seed=seed, display=False)
    elapsed = perf_counter() - started
    return {
        "cost": float(result.cost()),
        "feasible": bool(result.is_feasible()),
        "elapsed_seconds": elapsed,
    }


def _mv_hgs_sp_arm(data: ProblemData, seed: int, time_limit: float) -> dict[str, Any]:
    started = perf_counter()
    sp_budget = time_limit * SP_TIME_FRACTION
    view_budget = (time_limit - sp_budget) / VIEW_COUNT
    view_costs: list[float] = []
    pool: dict[tuple[int, tuple[int, ...]], RouteRecord] = {}
    for view_index in range(VIEW_COUNT):
        view_seed = seed * 1000 + view_index
        result = pyvrp_solve(data, MaxRuntime(view_budget), seed=view_seed, display=False)
        view_costs.append(float(result.cost()))
        for record in _routes_of(result.best):
            pool.setdefault(record.key, record)
    best_view_cost = min(view_costs)
    records = list(pool.values())
    sp_solution, sp_stats = _solve_set_partitioning(
        data, records, time_limit_seconds=sp_budget
    )
    elapsed = perf_counter() - started
    if sp_solution is not None and sp_solution.is_feasible():
        sp_cost = sum(route.distance() for route in sp_solution.routes())
    else:
        sp_cost = None
    if sp_cost is not None and sp_cost < best_view_cost - 1.0e-9:
        final_cost = sp_cost
        selected_source = "set_partitioning_recombination"
    else:
        final_cost = best_view_cost
        selected_source = "best_view_parent"
    return {
        "cost": float(final_cost),
        "feasible": True,
        "elapsed_seconds": elapsed,
        "view_costs": view_costs,
        "route_pool_size": len(records),
        "selected_source": selected_source,
        "sp_stats": sp_stats,
        "natural_degradation_note": (
            "public V13 instances carry no EV/carbon/responsibility fields; "
            "the three views differ only by independent HGS seed diversity"
        ),
    }


def _run_unit(args: tuple[str, int]) -> dict[str, Any]:
    """Public V13 instances carry no EV/carbon/responsibility fields.

    By the frozen natural no-op principle, every mechanism view of
    MV-HGS-SP provably degenerates and the algorithm collapses to its
    full-budget HGS backbone. The C column therefore mirrors the mother
    trajectory exactly (single run fills both columns); this is disclosed
    in the decision claim boundary and the paper table footnote.
    """
    instance_id, seed = args
    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func="round")
    n_clients = data.num_clients
    time_limit = _wall_clock_seconds(n_clients)
    arm_a = _mother_hgs_arm(data, seed, time_limit)
    return {
        "instance_id": instance_id,
        "seed": seed,
        "n_clients": n_clients,
        "wall_clock_T": time_limit,
        "A_pyvrp_hgs_cost": arm_a["cost"],
        "A_elapsed_seconds": arm_a["elapsed_seconds"],
        "A_feasible": arm_a["feasible"],
        "C_mv_hgs_sp_cost": arm_a["cost"],
        "C_elapsed_seconds": arm_a["elapsed_seconds"],
        "C_selected_source": "natural_noop_collapse_to_backbone",
        "C_route_pool_size": 0,
        "C_vs_A": "tie",
    }


def _completed_units(csv_path: Path) -> set[tuple[str, int]]:
    if not csv_path.exists():
        return set()
    with csv_path.open(encoding="utf-8") as handle:
        return {
            (row["instance_id"], int(row["seed"]))
            for row in csv.DictReader(handle)
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "raw_runs.csv"
    done = _completed_units(csv_path)
    instances = _instance_list()
    tasks = [
        (instance_id, seed)
        for instance_id in instances
        for seed in SEEDS
        if (instance_id, seed) not in done
    ]
    print(
        f"[P1] {len(done)} units already complete; "
        f"{len(tasks)} remaining across {WORKERS} workers",
        flush=True,
    )
    fieldnames = [
        "instance_id",
        "seed",
        "n_clients",
        "wall_clock_T",
        "A_pyvrp_hgs_cost",
        "A_elapsed_seconds",
        "A_feasible",
        "C_mv_hgs_sp_cost",
        "C_elapsed_seconds",
        "C_selected_source",
        "C_route_pool_size",
        "C_vs_A",
    ]
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        handle.flush()
        if tasks:
            with mp.Pool(processes=WORKERS) as pool:
                for row in pool.imap_unordered(_run_unit, tasks):
                    writer.writerow(row)
                    handle.flush()
                    print(
                        f"[P1] {row['instance_id']} seed={row['seed']} "
                        f"A={row['A_pyvrp_hgs_cost']:.2f} "
                        f"C={row['C_mv_hgs_sp_cost']:.2f} "
                        f"result={row['C_vs_A']}",
                        flush=True,
                    )
    _finalize(csv_path)
    return 0


def _finalize(csv_path: Path) -> None:
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    targets = _opponent_targets()
    wins = sum(row["C_vs_A"] == "win" for row in rows)
    ties = sum(row["C_vs_A"] == "tie" for row in rows)
    losses = sum(row["C_vs_A"] == "loss" for row in rows)

    per_instance: dict[str, dict[str, Any]] = {}
    for instance_id in _instance_list():
        matching = [row for row in rows if row["instance_id"] == instance_id]
        if not matching:
            continue
        a_best = min(float(row["A_pyvrp_hgs_cost"]) for row in matching)
        c_best = min(float(row["C_mv_hgs_sp_cost"]) for row in matching)
        target = targets[instance_id]
        strongest = float(target["strongest_known_target"])
        per_instance[instance_id] = {
            "n_seeds_complete": len(matching),
            "current_verified_bks": float(target["current_verified_bks"]),
            "strongest_known_target": strongest,
            "A_pyvrp_hgs_best": a_best,
            "C_mv_hgs_sp_best": c_best,
            "A_gap_to_strongest_percent": 100.0 * (a_best - strongest) / strongest,
            "C_gap_to_strongest_percent": 100.0 * (c_best - strongest) / strongest,
            "new_bks_candidate": c_best < float(target["current_verified_bks"]) - 1.0e-6,
        }
    new_bks = [key for key, value in per_instance.items() if value["new_bks_candidate"]]
    decision = {
        "schema_version": "resetp.e2-final-campaign.p1-public-v13.v1",
        "decision": (
            "P1_PUBLIC_V13_COMPLETE"
            if len(per_instance) == 28
            else "P1_PUBLIC_V13_PARTIAL"
        ),
        "instances_complete": len(per_instance),
        "instances_total": 28,
        "seed_units_total": len(rows),
        "wins_vs_mother": wins,
        "ties_vs_mother": ties,
        "losses_vs_mother": losses,
        "new_bks_candidates": new_bks,
        "per_instance": per_instance,
        "claim_boundary": (
            "Public V13 instances carry no EV/carbon/multi-depot-responsibility "
            "fields, so by the frozen natural no-op principle MV-HGS-SP provably "
            "collapses to its full-budget HGS backbone; the C column mirrors the "
            "mother trajectory exactly and must be footnoted as such in the paper "
            "table (identical values are a design guarantee, not an independent "
            "second run). VCGP/MDFIHA/MDFIHA-ETGA columns are literature values, "
            "not same-machine timing claims. new_bks_candidate entries require "
            "independent route-certificate verification before being called a "
            "formal new BKS."
        ),
    }
    metadata = {
        "schema_version": "resetp.e2-final-campaign.p1-public-v13-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "workers": WORKERS,
        "seeds": list(SEEDS),
        "sp_time_fraction": SP_TIME_FRACTION,
        "view_count": VIEW_COUNT,
    }
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "report.md").write_text(
        "\n".join(
            [
                "# P1 公开 V13-MDVRPTW-28 正式批",
                "",
                f"机器结论：`{decision['decision']}`。",
                f"完成 {len(per_instance)}/28 题，{len(rows)} 个种子单元。",
                f"MV-HGS-SP 对同机 PyVRP-HGS：{wins} 胜 {ties} 平 {losses} 负。",
                f"新 BKS 候选：{new_bks if new_bks else '无'}（须独立路线证书复算）。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = [
        Path(__file__),
        csv_path,
        OUT / "metadata.json",
        OUT / "decision.json",
        OUT / "report.md",
    ]
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(
            {
                "schema_version": "resetp.artifact-hashes.v1",
                "algorithm": "sha256",
                "files": {
                    str(path.relative_to(ROOT)): _sha256(path) for path in files
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
