#!/usr/bin/env python3
"""G-CHINA-REP: convergence-style MV-HGS-SP vs mother on 3 representative
China81 instances, 5 seeds each. Must flip the P0-era 150c 0/5 result.

Design mirrors run_final_gate.py's proven public-instance engine, wired
into the China81 mechanism-completion scoring space:

  * mother arm  = single mechanism_ev view HGS run to ITS OWN convergence
                  (NoImprovement(K_M) | MaxRuntime cap), scored by the
                  full nonlinear ReSETP completion (exact_china81_score).
  * hybrid arm  = SAME phase-1 trajectory (shared, structural
                  hybrid >= mother), then continuation epochs ROTATE
                  across the three mechanism views (cv_only, naive_ev,
                  mechanism_ev), harvesting each epoch's elites into a
                  shared route pool (reusing route_pool_sp._route_pool_
                  records / _solve_set_partitioning, already China81-
                  aware: vehicle-type limits, charging actions, exact
                  completion cost). Warm-started next epoch from the
                  best completion found so far. Stop after 2 consecutive
                  stalled epochs. Monotone global-best guard.

Pre-registered pass rule: zero losses AND 150c stratum >= 3/5 strict
wins -> PASS_G_CHINA_REP.
"""

from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
PROTO = ROOT / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
OUT = PACKAGE / "gate_china_rep"

for path in (ROOT / "solver/src", PROTO, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from epochal_hgs import HgsExactEpoch  # noqa: E402
from pyvrp._pyvrp import RandomNumberGenerator  # noqa: E402
from pyvrp._pyvrp import Solution as NativeSolution  # noqa: E402
from pyvrp.crossover import ordered_crossover, selective_route_exchange  # noqa: E402
from pyvrp.diversity import broken_pairs_distance  # noqa: E402
from pyvrp.GeneticAlgorithm import GeneticAlgorithm  # noqa: E402
from pyvrp.PenaltyManager import PenaltyManager  # noqa: E402
from pyvrp.Population import Population  # noqa: E402
from pyvrp.search import LocalSearch, compute_neighbours  # noqa: E402
from pyvrp.solve import SolveParams  # noqa: E402
from pyvrp.stop import MaxRuntime, MultipleCriteria, NoImprovement  # noqa: E402

from pyvrp_adapter import (  # noqa: E402
    _native_solution_key,
    _project_initial_solution,
    _translate_solution,
    build_pyvrp_problem,
)
from route_pool_sp import _route_pool_records, _solve_set_partitioning  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import Solution  # noqa: E402

INSTANCES = {
    "cn-jjj-25c-03-V2-LOCATIONS": "jjj-25",
    "cn-prd-75c-03-V2-LOCATIONS": "prd-75",
    "cn-cy-150c-03-V2-LOCATIONS": "cy-150",
}
SEEDS = (1, 2, 3, 4, 5)
CAPS = {
    "cn-jjj-25c-03-V2-LOCATIONS": {"K_M": 3000, "CAP_M": 90.0, "K_E": 1500, "CAP_E": 30.0},
    "cn-prd-75c-03-V2-LOCATIONS": {"K_M": 3000, "CAP_M": 180.0, "K_E": 1500, "CAP_E": 45.0},
    "cn-cy-150c-03-V2-LOCATIONS": {"K_M": 3000, "CAP_M": 300.0, "K_E": 1500, "CAP_E": 75.0},
}
MAX_EPOCHS = 4
STALL_EPOCHS = 2
ELITE_COUNT = 8
MAX_ARCHIVE = 24
SP_TIME = 10.0
ROTATION = ("cv_only", "naive_ev", "mechanism_ev")
WORKERS = 5
EPS = 1.0e-6


def _run_epoch(
    bundle,
    problem,
    common_initial_solution: Solution,
    *,
    seed: int,
    stop,
    warm_elites: tuple[Solution, ...],
) -> HgsExactEpoch:
    started = perf_counter()
    data = problem.model.data()
    params = SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))
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
    warm_native = [
        _project_initial_solution(item, data, problem) for item in warm_elites
    ]
    random_count = max(0, int(params.population.min_pop_size) - len(warm_native))
    initial_solutions = [
        *warm_native,
        *[NativeSolution.make_random(data, rng) for _ in range(random_count)],
    ]
    crossover = (
        selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
    )
    algorithm = GeneticAlgorithm(
        data, penalty_manager, rng, population, local_search, crossover,
        initial_solutions, params.genetic,
    )
    result = algorithm.run(stop, collect_stats=False, display=False)
    cost_evaluator = penalty_manager.cost_evaluator()
    feasible = [item for item in population if item.is_feasible()]
    feasible.append(result.best)
    unique: dict[tuple[Any, ...], Any] = {}
    for native in feasible:
        unique.setdefault(_native_solution_key(native), native)
    proxy_ranked = sorted(unique.values(), key=cost_evaluator.cost)[:MAX_ARCHIVE]
    exact_candidates: list[tuple[Solution, Any, int]] = []
    for native in proxy_ranked:
        try:
            skeleton = _translate_solution(native, problem)
            completion = complete_china81_route_skeleton(skeleton, bundle)
            exact_candidates.append((skeleton, completion, int(cost_evaluator.cost(native))))
        except (IndexError, KeyError, TypeError, ValueError):
            continue
    common_completion = complete_china81_route_skeleton(common_initial_solution, bundle)
    exact_candidates.append((common_initial_solution, common_completion, -1))
    exact_ranked = sorted(exact_candidates, key=lambda item: (item[1].objective, item[2]))
    selected = exact_ranked[:ELITE_COUNT]
    proxy_best_completion = complete_china81_route_skeleton(
        _translate_solution(result.best, problem), bundle
    )
    return HgsExactEpoch(
        elite_skeletons=tuple(item[0] for item in selected),
        elite_completions=tuple(item[1] for item in selected),
        proxy_best_completion=proxy_best_completion,
        elapsed_seconds=perf_counter() - started,
        stats={"seed": int(seed), "hgs_iterations": int(result.num_iterations)},
    )


def _run_unit(args: tuple[str, int]) -> dict[str, Any]:
    instance_id, seed = args
    caps = CAPS[instance_id]
    bundle = load_china81_bundle(ROOT, instance_id)
    common = complete_china81_route_skeleton(
        build_initial_solution(
            bundle.instance, bundle.time_profile, bundle.prices,
            introduce_ev=False, require_charging_signal=False,
        ),
        bundle,
    )
    started = perf_counter()

    # ---- phase 1: mother (mechanism_ev, shared trajectory) ----
    mother_problem = build_pyvrp_problem(bundle, route_proxy_mode="mechanism_ev")
    mother_stop = MultipleCriteria(
        [NoImprovement(caps["K_M"]), MaxRuntime(caps["CAP_M"])]
    )
    mother_epoch = _run_epoch(
        bundle, mother_problem, common.solution,
        seed=seed, stop=mother_stop, warm_elites=(),
    )
    mother_cpu = perf_counter() - started
    mother_completion = min(
        (*mother_epoch.elite_completions, common),
        key=lambda item: item.objective,
    )
    mother_cost = mother_completion.objective

    # ---- hybrid: continuation epochs rotating mechanism views ----
    global_best = mother_cost
    best_completion = mother_completion
    view_epochs: dict[str, HgsExactEpoch] = {"mechanism_ev": mother_epoch}
    elites = mother_epoch.elite_skeletons
    stall = 0
    epochs_run = 0
    for epoch_index in range(MAX_EPOCHS):
        improved = False
        pool = _route_pool_records(bundle, view_epochs)
        sp_solution, sp_stats = _solve_set_partitioning(
            bundle, pool, time_limit_seconds=SP_TIME
        )
        if sp_solution is not None:
            sp_completion = complete_china81_route_skeleton(sp_solution, bundle)
            if sp_completion.objective < global_best - EPS:
                global_best = sp_completion.objective
                best_completion = sp_completion
                improved = True
        mode = ROTATION[epoch_index % len(ROTATION)]
        problem = build_pyvrp_problem(bundle, route_proxy_mode=mode)
        epoch_stop = MultipleCriteria(
            [NoImprovement(caps["K_E"]), MaxRuntime(caps["CAP_E"])]
        )
        epoch_seed = int(seed) + 1009 * (epoch_index + 1)
        epoch = _run_epoch(
            bundle, problem, best_completion.solution,
            seed=epoch_seed, stop=epoch_stop,
            warm_elites=(best_completion.solution, *elites),
        )
        epoch_best = min(epoch.elite_completions, key=lambda item: item.objective)
        if epoch_best.objective < global_best - EPS:
            global_best = epoch_best.objective
            best_completion = epoch_best
            improved = True
        view_epochs[mode] = epoch
        elites = epoch.elite_skeletons
        epochs_run += 1
        stall = 0 if improved else stall + 1
        if stall >= STALL_EPOCHS:
            break
    hybrid_cpu = perf_counter() - started
    delta = global_best - mother_cost
    outcome = "win" if delta < -EPS else ("loss" if delta > EPS else "tie")
    _, _, mother_violations = exact_china81_score(mother_completion.solution, bundle)
    _, _, hybrid_violations = exact_china81_score(best_completion.solution, bundle)
    return {
        "instance_id": instance_id,
        "stratum": INSTANCES[instance_id],
        "seed": seed,
        "mother_cost": float(mother_cost),
        "mother_cpu_seconds": mother_cpu,
        "mother_feasible": not mother_violations,
        "hybrid_cost": float(global_best),
        "hybrid_cpu_seconds": hybrid_cpu,
        "hybrid_feasible": not hybrid_violations,
        "cpu_ratio": hybrid_cpu / mother_cpu if mother_cpu > 0 else float("inf"),
        "hybrid_vs_mother": outcome,
        "improvement_percent": 100.0 * (mother_cost - global_best) / mother_cost,
        "epochs_run": epochs_run,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = [(instance_id, seed) for instance_id in INSTANCES for seed in SEEDS]
    print(f"[CHINA-REP] {len(tasks)} units across {WORKERS} workers", flush=True)
    rows: list[dict[str, Any]] = []
    with mp.Pool(processes=WORKERS) as pool:
        for row in pool.imap_unordered(_run_unit, tasks):
            rows.append(row)
            print(
                f"[CHINA-REP] {row['instance_id']} seed={row['seed']} "
                f"mother={row['mother_cost']:.3f} hybrid={row['hybrid_cost']:.3f} "
                f"{row['hybrid_vs_mother']} (+{row['improvement_percent']:.3f}%) "
                f"cpu_ratio={row['cpu_ratio']:.2f} feasible={row['hybrid_feasible']}",
                flush=True,
            )
    rows.sort(key=lambda item: (item["instance_id"], item["seed"]))
    wins = sum(row["hybrid_vs_mother"] == "win" for row in rows)
    ties = sum(row["hybrid_vs_mother"] == "tie" for row in rows)
    losses = sum(row["hybrid_vs_mother"] == "loss" for row in rows)
    by_stratum: dict[str, dict[str, int]] = {}
    for label in ("jjj-25", "prd-75", "cy-150"):
        matching = [row for row in rows if row["stratum"] == label]
        by_stratum[label] = {
            "wins": sum(row["hybrid_vs_mother"] == "win" for row in matching),
            "ties": sum(row["hybrid_vs_mother"] == "tie" for row in matching),
            "losses": sum(row["hybrid_vs_mother"] == "loss" for row in matching),
        }
    all_feasible = all(row["hybrid_feasible"] and row["mother_feasible"] for row in rows)
    passed = losses == 0 and by_stratum["cy-150"]["wins"] >= 3 and all_feasible
    decision = {
        "schema_version": "resetp.e2-final-campaign.g-china-rep.v1",
        "decision": "PASS_G_CHINA_REP" if passed else "FAIL_G_CHINA_REP",
        "passed": passed,
        "wins": wins, "ties": ties, "losses": losses,
        "by_stratum": by_stratum,
        "all_feasible": all_feasible,
        "pass_rule": "zero losses AND cy-150 stratum >= 3/5 strict wins AND all feasible",
        "details": rows,
    }
    metadata = {
        "schema_version": "resetp.e2-final-campaign.g-china-rep-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "workers": WORKERS,
        "caps": CAPS,
    }
    fieldnames = list(rows[0].keys()) if rows else []
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text(
        "\n".join([
            "# G-CHINA-REP: China81 代表题收敛式对母体门",
            "",
            f"机器结论：`{decision['decision']}`。",
            f"{wins} 胜 / {ties} 平 / {losses} 负。",
            f"分层：{json.dumps(by_stratum, ensure_ascii=False)}",
            "",
        ]), encoding="utf-8",
    )
    files = [Path(__file__), OUT / "raw_runs.csv", OUT / "metadata.json", OUT / "decision.json", OUT / "report.md"]
    (OUT / "artifact_hashes.json").write_text(
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
