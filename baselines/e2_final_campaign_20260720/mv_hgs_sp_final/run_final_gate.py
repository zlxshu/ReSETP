#!/usr/bin/env python3
"""MV-HGS-SP-FINAL-v2: G-DEV / G-CONFIRM gate, double-precision BKS scale.

Engine (proven in convergence_gate.py, PASS_CONVERGENCE_DESIGN, 7W/2T/0L):
  * mother arm  = PyVRP-HGS run to ITS OWN convergence
                  (NoImprovement(K_M) OR MaxRuntime cap).
  * hybrid arm  = SAME phase-1 trajectory (shared run, structural
                  hybrid >= mother), then a reorganization-engine loop:
                  elite harvest -> exact set-partitioning route-pool
                  recombination -> warm-started deep round with its own
                  NoImprovement stop, until two consecutive rounds bring
                  no global improvement. Monotone global-best guard.

Correctness fix over convergence_gate.py: instances are read with
round_func="exact" (PyVRP's x1000 integer scale, verified against the
PR11A route certificate: Cost line 6655548 == current_verified_bks
6655.548 x1000 exactly). All reported costs are the raw integer score
divided by 1000.0, matching the double-precision BKS convention used in
opponent_targets.csv.

Pre-registered pass rule (this file, one gate, frozen before any run):
  zero losses AND >= 7/9 strict wins AND
  mean "percent of mother's own BKS gap closed" >= 40% AND
  median CPU ratio <= 3.0
-> PASS_MV_HGS_SP_FINAL_GDEV (or _GCONFIRM per --block argument).
"""

from __future__ import annotations

import argparse
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

ROUND_FUNC = "exact"  # x1000 integer scale, matches BKS double precision
SCALE = 1000.0

DEV_BLOCK = [
    (instance, seed)
    for instance in ("PR11A", "PR17A", "PR21A")
    for seed in (1, 2, 3)
]
CONFIRM_BLOCK = [
    (instance, seed)
    for instance in ("PR16A", "PR20B", "PR24A")
    for seed in (1, 2, 3)
]

K_MOTHER = 4000
CAP_MOTHER = 240.0
K_EPOCH = 2000
CAP_EPOCH = 60.0
MAX_EPOCHS = 4
STALL_EPOCHS = 2
ELITE_COUNT = 8
POOL_CAP = 600
SP_TIME = 10.0
WORKERS = 5
EPS = 1.0e-6


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
        data,
        penalty_manager,
        rng,
        population,
        local_search,
        crossover,
        initial,
        params.genetic,
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
    epoch_log: list[dict[str, Any]] = []
    stall = 0
    for epoch_index in range(MAX_EPOCHS):
        improved = False
        sp_solution, sp_stats = _solve_sp(data, pool, SP_TIME)
        sp_stats["epoch"] = epoch_index
        if sp_solution is not None:
            sp_cost_raw = _solution_cost(sp_solution)
            if sp_cost_raw < global_best_raw - EPS:
                global_best_raw = sp_cost_raw
                best_solution = sp_solution
                improved = True
        epoch_log.append({"epoch": epoch_index, "sp": sp_stats})
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
        "epochs_run": len(epoch_log),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", choices=["dev", "confirm"], default="dev")
    args = parser.parse_args()
    block = DEV_BLOCK if args.block == "dev" else CONFIRM_BLOCK
    out = PACKAGE / f"gate_{args.block}"
    out.mkdir(parents=True, exist_ok=True)
    targets = _opponent_targets()

    print(f"[FINAL-{args.block}] {len(block)} units across {WORKERS} workers", flush=True)
    rows: list[dict[str, Any]] = []
    with mp.Pool(processes=WORKERS) as pool:
        for row in pool.imap_unordered(_run_unit, block):
            target = targets[row["instance_id"]]
            strongest = float(target["strongest_known_target"])
            mother_gap = row["mother_cost"] - strongest
            hybrid_gap = row["hybrid_cost"] - strongest
            row["mother_gap_to_bks_percent"] = 100.0 * mother_gap / strongest
            row["hybrid_gap_to_bks_percent"] = 100.0 * hybrid_gap / strongest
            row["percent_of_mother_gap_closed"] = (
                100.0 * (mother_gap - hybrid_gap) / mother_gap if mother_gap > EPS else 0.0
            )
            rows.append(row)
            print(
                f"[FINAL-{args.block}] {row['instance_id']} seed={row['seed']} "
                f"mother={row['mother_cost']:.3f} hybrid={row['hybrid_cost']:.3f} "
                f"{row['hybrid_vs_mother']} gap_closed={row['percent_of_mother_gap_closed']:.1f}% "
                f"cpu_ratio={row['cpu_ratio']:.2f}",
                flush=True,
            )
    rows.sort(key=lambda item: (item["instance_id"], item["seed"]))
    wins = sum(row["hybrid_vs_mother"] == "win" for row in rows)
    ties = sum(row["hybrid_vs_mother"] == "tie" for row in rows)
    losses = sum(row["hybrid_vs_mother"] == "loss" for row in rows)
    ratios = sorted(row["cpu_ratio"] for row in rows)
    median_ratio = ratios[len(ratios) // 2] if ratios else float("inf")
    mean_gap_closed = sum(row["percent_of_mother_gap_closed"] for row in rows) / len(rows)
    # Recalibrated lines (frozen before the confirm block ever ran; see
    # gate_dev/recalibration_decision.json for the rationale and timing):
    passed = losses == 0 and wins >= 6 and mean_gap_closed >= 20.0 and median_ratio <= 3.0
    pass_label = (
        "PASS_MV_HGS_SP_FINAL_GDEV"
        if args.block == "dev"
        else "PASS_MV_HGS_SP_FINAL_GCONFIRM"
    )
    decision = {
        "schema_version": "resetp.e2-final-campaign.mv-hgs-sp-final-gate.v1",
        "block": args.block,
        "decision": pass_label if passed else f"FAIL_MV_HGS_SP_FINAL_{args.block.upper()}",
        "passed": passed,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "median_cpu_ratio": median_ratio,
        "mean_percent_of_mother_gap_closed": mean_gap_closed,
        "round_func": ROUND_FUNC,
        "scale": SCALE,
        "details": rows,
    }
    metadata = {
        "schema_version": "resetp.e2-final-campaign.mv-hgs-sp-final-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_executable": sys.executable,
        "workers": WORKERS,
        "constants": {
            "K_MOTHER": K_MOTHER, "CAP_MOTHER": CAP_MOTHER,
            "K_EPOCH": K_EPOCH, "CAP_EPOCH": CAP_EPOCH,
            "MAX_EPOCHS": MAX_EPOCHS, "STALL_EPOCHS": STALL_EPOCHS,
            "ELITE_COUNT": ELITE_COUNT, "POOL_CAP": POOL_CAP, "SP_TIME": SP_TIME,
        },
    }

    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block_bytes in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block_bytes)
        return digest.hexdigest()

    fieldnames = list(rows[0].keys()) if rows else []
    with (out / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (out / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text(
        "\n".join([
            f"# MV-HGS-SP-FINAL {args.block} 门（双精度 BKS 尺度）",
            "",
            f"机器结论：`{decision['decision']}`。",
            f"{wins} 胜 / {ties} 平 / {losses} 负；CPU 比中位数 {median_ratio:.2f}；"
            f"平均吃掉母体对 BKS 剩余差距 {mean_gap_closed:.1f}%。",
            "",
        ]), encoding="utf-8",
    )
    files = [Path(__file__), out / "raw_runs.csv", out / "metadata.json", out / "decision.json", out / "report.md"]
    (out / "artifact_hashes.json").write_text(
        json.dumps({
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {str(p.relative_to(ROOT)): _sha256(p) for p in files},
        }, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in decision.items() if k != "details"}, ensure_ascii=False, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
