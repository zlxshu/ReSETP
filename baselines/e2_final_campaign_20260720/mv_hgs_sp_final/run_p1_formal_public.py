#!/usr/bin/env python3
"""P1: MV-HGS-SP-FINAL formal public batch, all 28 V13-MDVRPTW instances,
10 seeds each, frozen convergence-style engine (unchanged from the engine
that passed G-DEV/G-CONFIRM: PASS_MV_HGS_SP_FINAL_GDEV,
PASS_MV_HGS_SP_FINAL_GCONFIRM). Configuration is frozen -- no re-tuning.

Produces Chen(2025)-style Table 5 raw data:
  instances | n | BKS | VCGP | MDFIHA | MDFIHA-ETGA | HGS mother | MV-HGS-SP
  (error% to current_verified_bks per column; Avg row; bold-best marked at
  report-generation time, not in this raw CSV)

Resumable: on restart, already-completed (instance, seed) rows are skipped.
"""
from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
FOUNDATION = ROOT / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
INSTANCE_DIR = FOUNDATION / "sources/normalised_instances"
OPPONENT_CSV = FOUNDATION / "opponent_targets.csv"
OUT = PACKAGE / "p1_formal_gate"

try:
    from scipy.optimize import Bounds, LinearConstraint, milp
except ModuleNotFoundError:
    system_site = Path("/opt/anaconda3/lib/python3.13/site-packages")
    if system_site.exists():
        sys.path.append(str(system_site))
    from scipy.optimize import Bounds, LinearConstraint, milp

from pyvrp import ProblemData, read  # noqa: E402
from pyvrp._pyvrp import (  # noqa: E402
    RandomNumberGenerator,
    Route as NativeRoute,
    Solution as NativeSolution,
)
from pyvrp.GeneticAlgorithm import GeneticAlgorithm  # noqa: E402
from pyvrp.PenaltyManager import PenaltyManager  # noqa: E402
from pyvrp.Population import Population  # noqa: E402
from pyvrp.crossover import ordered_crossover, selective_route_exchange  # noqa: E402
from pyvrp.diversity import broken_pairs_distance  # noqa: E402
from pyvrp.search import LocalSearch, compute_neighbours  # noqa: E402
from pyvrp.solve import SolveParams  # noqa: E402
from pyvrp.stop import MaxRuntime, MultipleCriteria, NoImprovement  # noqa: E402

ROUND_FUNC = "exact"
SCALE = 1000.0
SEEDS = tuple(range(1, 11))

# Frozen constants (identical to run_final_gate.py; validated on
# 360-972 client instances in G-DEV/G-CONFIRM, no re-tuning for P1).
K_MOTHER = 4000
CAP_MOTHER = 240.0
K_EPOCH = 2000
CAP_EPOCH = 60.0
MAX_EPOCHS = 4
STALL_EPOCHS = 2
ELITE_COUNT = 8
POOL_CAP = 600
SP_TIME = 10.0
WORKERS = 6
EPS = 1.0e-6


def _instance_list() -> list[str]:
    with OPPONENT_CSV.open(encoding="utf-8") as handle:
        return [row["instance"] for row in csv.DictReader(handle)]


def _opponent_targets() -> dict[str, dict[str, str]]:
    with OPPONENT_CSV.open(encoding="utf-8") as handle:
        return {row["instance"]: row for row in csv.DictReader(handle)}


def _build_algorithm(
    data: ProblemData,
    rng: RandomNumberGenerator,
    params: SolveParams,
    initial: list[NativeSolution],
) -> tuple[GeneticAlgorithm, Population, PenaltyManager]:
    neighbours = compute_neighbours(data, params.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    for node_op in params.node_ops:
        if node_op.supports(data):
            local_search.add_node_operator(node_op(data))
    for route_op in params.route_ops:
        if route_op.supports(data):
            local_search.add_route_operator(route_op(data))
    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    crossover = (
        selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
    )
    algorithm = GeneticAlgorithm(
        data, penalty_manager, rng, population, local_search, crossover,
        initial, params.genetic,
    )
    return algorithm, population, penalty_manager


def _solution_cost(solution: NativeSolution) -> float:
    return float(sum(route.distance() for route in solution.routes()))


def _solution_key(solution: NativeSolution) -> tuple[Any, ...]:
    return tuple(
        sorted(
            (route.vehicle_type(), tuple(route.visits()))
            for route in solution.routes()
        )
    )


def _harvest_elites(
    population: Population,
    penalty_manager: PenaltyManager,
    best: NativeSolution,
) -> list[NativeSolution]:
    cost_evaluator = penalty_manager.cost_evaluator()
    feasible = [item for item in population if item.is_feasible()]
    feasible.append(best)
    unique: dict[tuple[Any, ...], NativeSolution] = {}
    for native in feasible:
        unique.setdefault(_solution_key(native), native)
    ranked = sorted(unique.values(), key=cost_evaluator.cost)
    return ranked[:ELITE_COUNT]


def _pool_add(
    pool: dict[tuple[int, tuple[int, ...]], float],
    solutions: list[NativeSolution],
) -> None:
    for solution in solutions:
        for route in solution.routes():
            key = (route.vehicle_type(), tuple(route.visits()))
            pool.setdefault(key, float(route.distance()))


def _solve_sp(
    data: ProblemData,
    pool: dict[tuple[int, tuple[int, ...]], float],
    time_limit: float,
) -> tuple[NativeSolution | None, dict[str, Any]]:
    records = sorted(pool.items(), key=lambda item: item[1])[:POOL_CAP]
    clients = list(range(data.num_depots, data.num_locations))
    client_index = {client: index for index, client in enumerate(clients)}
    matrix = np.zeros((len(clients), len(records)), dtype=float)
    for column, ((_, visits), _) in enumerate(records):
        for visit in visits:
            matrix[client_index[visit], column] = 1.0
    costs = np.array([cost for _, cost in records], dtype=float)
    constraints = [
        LinearConstraint(matrix, lb=np.ones(len(clients)), ub=np.ones(len(clients)))
    ]
    for vt in range(data.num_vehicle_types):
        limit = data.vehicle_type(vt).num_available
        row = np.array([1.0 if key[0] == vt else 0.0 for key, _ in records])
        constraints.append(LinearConstraint(row, lb=-np.inf, ub=float(limit)))
    result = milp(
        c=costs,
        integrality=np.ones(len(records)),
        bounds=Bounds(np.zeros(len(records)), np.ones(len(records))),
        constraints=constraints,
        options={"time_limit": float(time_limit)},
    )
    stats = {"success": bool(result.success), "pool_size": len(records), "selected": 0}
    if result.x is None:
        return None, stats
    chosen = [records[i] for i, value in enumerate(result.x) if value > 0.5]
    stats["selected"] = len(chosen)
    routes = [NativeRoute(data, list(visits), vt) for (vt, visits), _ in chosen]
    solution = NativeSolution(data, routes)
    if not solution.is_feasible():
        return None, stats
    return solution, stats


def _run_unit(args: tuple[str, int]) -> dict[str, Any]:
    instance_id, seed = args
    data = read(str(INSTANCE_DIR / f"{instance_id}.vrp"), round_func=ROUND_FUNC)
    params = SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))

    started = perf_counter()
    initial = [
        NativeSolution.make_random(data, rng)
        for _ in range(params.population.min_pop_size)
    ]
    algorithm, population, penalty_manager = _build_algorithm(data, rng, params, initial)
    stop = MultipleCriteria([NoImprovement(K_MOTHER), MaxRuntime(CAP_MOTHER)])
    result = algorithm.run(stop, collect_stats=False, display=False)
    mother_cpu = perf_counter() - started
    mother_cost = _solution_cost(result.best) / SCALE
    mother_iterations = int(result.num_iterations)

    global_best_raw = mother_cost * SCALE
    best_solution = result.best
    pool: dict[tuple[int, tuple[int, ...]], float] = {}
    elites = _harvest_elites(population, penalty_manager, result.best)
    _pool_add(pool, elites)
    stall = 0
    epochs_run = 0
    for epoch_index in range(MAX_EPOCHS):
        improved = False
        sp_solution, _sp_stats = _solve_sp(data, pool, SP_TIME)
        if sp_solution is not None:
            sp_cost_raw = _solution_cost(sp_solution)
            if sp_cost_raw < global_best_raw - EPS:
                global_best_raw = sp_cost_raw
                best_solution = sp_solution
                improved = True
        warm = [best_solution, *elites]
        unique_warm: dict[tuple[Any, ...], NativeSolution] = {}
        for native in warm:
            unique_warm.setdefault(_solution_key(native), native)
        warm_list = list(unique_warm.values())
        epoch_rng = RandomNumberGenerator(seed=int(seed) + 1009 * (epoch_index + 1))
        random_fill = [
            NativeSolution.make_random(data, epoch_rng)
            for _ in range(max(0, params.population.min_pop_size - len(warm_list)))
        ]
        algorithm, population, penalty_manager = _build_algorithm(
            data, epoch_rng, params, [*warm_list, *random_fill]
        )
        epoch_stop = MultipleCriteria([NoImprovement(K_EPOCH), MaxRuntime(CAP_EPOCH)])
        epoch_result = algorithm.run(epoch_stop, collect_stats=False, display=False)
        epoch_cost_raw = _solution_cost(epoch_result.best)
        if epoch_cost_raw < global_best_raw - EPS:
            global_best_raw = epoch_cost_raw
            best_solution = epoch_result.best
            improved = True
        elites = _harvest_elites(population, penalty_manager, epoch_result.best)
        _pool_add(pool, elites)
        epochs_run += 1
        stall = 0 if improved else stall + 1
        if stall >= STALL_EPOCHS:
            break
    hybrid_cpu = perf_counter() - started
    hybrid_cost = global_best_raw / SCALE
    delta = hybrid_cost - mother_cost
    outcome = "win" if delta < -EPS else ("loss" if delta > EPS else "tie")
    return {
        "instance_id": instance_id,
        "seed": seed,
        "n_clients": data.num_clients,
        "mother_cost": mother_cost,
        "mother_cpu_seconds": mother_cpu,
        "mother_iterations": mother_iterations,
        "hybrid_cost": hybrid_cost,
        "hybrid_cpu_seconds": hybrid_cpu,
        "cpu_ratio": hybrid_cpu / mother_cpu if mother_cpu > 0 else float("inf"),
        "hybrid_vs_mother": outcome,
        "improvement_percent": 100.0 * (mother_cost - hybrid_cost) / mother_cost,
        "epochs_run": epochs_run,
    }


def _completed_units(csv_path: Path) -> set[tuple[str, int]]:
    if not csv_path.exists():
        return set()
    with csv_path.open(encoding="utf-8") as handle:
        return {(row["instance_id"], int(row["seed"])) for row in csv.DictReader(handle)}


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
        f"[P1-FORMAL] {len(done)} units already complete; "
        f"{len(tasks)} remaining across {WORKERS} workers "
        f"({len(instances)} instances x {len(SEEDS)} seeds = "
        f"{len(instances) * len(SEEDS)} total)",
        flush=True,
    )
    fieldnames = [
        "instance_id", "seed", "n_clients",
        "mother_cost", "mother_cpu_seconds", "mother_iterations",
        "hybrid_cost", "hybrid_cpu_seconds", "cpu_ratio",
        "hybrid_vs_mother", "improvement_percent", "epochs_run",
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
                        f"[P1-FORMAL] {row['instance_id']} seed={row['seed']} "
                        f"mother={row['mother_cost']:.3f} hybrid={row['hybrid_cost']:.3f} "
                        f"{row['hybrid_vs_mother']} (+{row['improvement_percent']:.3f}%) "
                        f"cpu_ratio={row['cpu_ratio']:.2f}",
                        flush=True,
                    )
    _finalize(csv_path)
    return 0


def _finalize(csv_path: Path) -> None:
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    targets = _opponent_targets()
    wins = sum(row["hybrid_vs_mother"] == "win" for row in rows)
    ties = sum(row["hybrid_vs_mother"] == "tie" for row in rows)
    losses = sum(row["hybrid_vs_mother"] == "loss" for row in rows)

    table5: list[dict[str, Any]] = []
    for instance_id in _instance_list():
        matching = [row for row in rows if row["instance_id"] == instance_id]
        if len(matching) < len(SEEDS):
            continue
        mother_best = min(float(row["mother_cost"]) for row in matching)
        hybrid_best = min(float(row["hybrid_cost"]) for row in matching)
        target = targets[instance_id]
        bks = float(target["current_verified_bks"])
        vcgp = float(target["vcgp_best_2013"])
        mdfiha = float(target["mdfiha_best_2026"])
        etga = float(target["mdfiha_etga_best_2026"])
        table5.append({
            "instance": instance_id,
            "n": int(matching[0]["n_clients"]),
            "bks": bks,
            "vcgp_error_pct": 100.0 * (vcgp - bks) / bks,
            "mdfiha_error_pct": 100.0 * (mdfiha - bks) / bks,
            "etga_error_pct": 100.0 * (etga - bks) / bks,
            "mother_best": mother_best,
            "mother_error_pct": 100.0 * (mother_best - bks) / bks,
            "hybrid_best": hybrid_best,
            "hybrid_error_pct": 100.0 * (hybrid_best - bks) / bks,
            "new_bks_candidate": hybrid_best < bks - 1.0e-6,
        })
    complete_instances = len(table5)
    avg_row = {}
    if table5:
        for key in ("vcgp_error_pct", "mdfiha_error_pct", "etga_error_pct",
                     "mother_error_pct", "hybrid_error_pct"):
            avg_row[key] = sum(row[key] for row in table5) / len(table5)
    new_bks = [row["instance"] for row in table5 if row["new_bks_candidate"]]
    decision = {
        "schema_version": "resetp.e2-final-campaign.p1-formal-public.v1",
        "decision": (
            "P1_FORMAL_PUBLIC_COMPLETE"
            if complete_instances == 28
            else "P1_FORMAL_PUBLIC_PARTIAL"
        ),
        "instances_complete": complete_instances,
        "instances_total": 28,
        "seed_units_total": len(rows),
        "wins_vs_mother": wins,
        "ties_vs_mother": ties,
        "losses_vs_mother": losses,
        "avg_row_error_pct": avg_row,
        "new_bks_candidates": new_bks,
        "table5": table5,
        "claim_boundary": (
            "VCGP/MDFIHA/MDFIHA-ETGA columns are literature best values, not "
            "same-machine timing claims. HGS-mother and MV-HGS-SP columns are "
            "same-machine (M1), each run to its own convergence criterion, CPU "
            "disclosed in raw_runs.csv. new_bks_candidate entries require "
            "independent route-certificate verification before being called a "
            "formal new BKS."
        ),
    }
    metadata = {
        "schema_version": "resetp.e2-final-campaign.p1-formal-public-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "workers": WORKERS,
        "seeds": list(SEEDS),
        "frozen_constants": {
            "K_MOTHER": K_MOTHER, "CAP_MOTHER": CAP_MOTHER,
            "K_EPOCH": K_EPOCH, "CAP_EPOCH": CAP_EPOCH,
            "MAX_EPOCHS": MAX_EPOCHS, "STALL_EPOCHS": STALL_EPOCHS,
            "ELITE_COUNT": ELITE_COUNT, "POOL_CAP": POOL_CAP, "SP_TIME": SP_TIME,
        },
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text(
        "\n".join([
            "# P1 公开 28 题正式批（陈式表5数据）",
            "",
            f"机器结论：`{decision['decision']}`。",
            f"完成 {complete_instances}/28 题，{len(rows)} 个种子单元。",
            f"MV-HGS-SP 对同机 HGS 母体：{wins} 胜 {ties} 平 {losses} 负。",
            f"新 BKS 候选：{new_bks if new_bks else '无'}（须独立路线证书复算）。",
            "",
        ]), encoding="utf-8",
    )
    files = [Path(__file__), csv_path, OUT / "metadata.json", OUT / "decision.json", OUT / "report.md"]
    (OUT / "artifact_hashes.json").write_text(
        json.dumps({
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {str(p.relative_to(ROOT)): _sha256(p) for p in files},
        }, ensure_ascii=False, indent=2), encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
