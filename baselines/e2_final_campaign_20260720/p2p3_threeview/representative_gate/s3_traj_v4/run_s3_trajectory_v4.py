#!/usr/bin/env python3
"""S3-TRAJ-V4: observation-only trajectory replay for the sealed S3 batch.

The sealed S3 ledger is never rewritten.  This runner repeats the registered
representative four-arm protocol with the same PyVRP 0.12.2 engine, seeds,
stopping criteria, and continuation logic.  It adds one read-only hook to a
local copy of PyVRP's Python genetic-algorithm loop: when the proxy global best
changes, the current route skeleton is copied.  The hook does not score,
repair, mutate, or draw from the random-number generator.  Snapshots are
completed and scored only after the HGS run has ended.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import multiprocessing as mp
import platform
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[5]
REPRESENTATIVE_DIR = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
PACKAGE = ROOT / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final"
P3_RAW = PACKAGE / "p3_china81_gate/raw_runs.csv"
SEALED_S3_RAW = REPRESENTATIVE_DIR / "raw_runs.csv"
OBS_RAW = OUT / "raw_runs.csv"
S3_DECISION = REPRESENTATIVE_DIR / "decision.json"
REGISTRATION = REPRESENTATIVE_DIR / "representative_registration.json"
TARGET_INSTANCE = "cn-prd-50c-01-V2-LOCATIONS"
ARMS = ("cv_only", "naive_ev", "mechanism_ev", "MV-HGS-SP")
SEEDS = tuple(range(1, 11))
ROTATION = ("cv_only", "naive_ev", "mechanism_ev")
MAX_EPOCHS = 4
STALL_EPOCHS = 2
SP_TIME = 10.0
EPS = 1.0e-6
DEFAULT_WORKERS = 6
APPLEDOUBLE_FLAG = "HASH_CONTAMINATED_APPLEDOUBLE"

for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_p3_china81_formal as p3  # noqa: E402
from epochal_hgs import HgsExactEpoch  # noqa: E402
from pyvrp.GeneticAlgorithm import GeneticAlgorithm  # noqa: E402
from pyvrp.PenaltyManager import PenaltyManager  # noqa: E402
from pyvrp.Population import Population  # noqa: E402
from pyvrp.ProgressPrinter import ProgressPrinter  # noqa: E402
from pyvrp.Result import Result  # noqa: E402
from pyvrp.Statistics import Statistics  # noqa: E402
from pyvrp._pyvrp import RandomNumberGenerator  # noqa: E402
from pyvrp._pyvrp import Solution as NativeSolution  # noqa: E402
from pyvrp.crossover import ordered_crossover, selective_route_exchange  # noqa: E402
from pyvrp.diversity import broken_pairs_distance  # noqa: E402
from pyvrp.search import LocalSearch, compute_neighbours  # noqa: E402
from pyvrp.solve import SolveParams  # noqa: E402
from pyvrp.stop import MultipleCriteria  # noqa: E402
from pyvrp_adapter import (  # noqa: E402
    _native_solution_key,
    _project_initial_solution,
    _translate_solution,
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
from setp_solver.solution import Route, Solution  # noqa: E402


OBS_FIELDS = [
    "instance_id",
    "n",
    "seed",
    "arm",
    "status",
    "sealed_cost",
    "rerun_cost",
    "cost_equal",
    "cost_delta",
    "cpu_seconds",
    "violation_count",
    "violations",
    "epochs_run",
    "hgs_iterations",
    "snapshot_count",
    "snapshot_file",
    "error_type",
    "error",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _skeleton_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [
            {
                "vehicle_id": route.vehicle_id,
                "vehicle_type": route.vehicle_type,
                "home_depot_id": route.home_depot_id,
                "node_sequence": list(route.node_sequence),
            }
            for route in solution.routes
        ]
    }


def _solution_from_payload(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(route["vehicle_id"]),
                vehicle_type=str(route["vehicle_type"]),
                home_depot_id=str(route["home_depot_id"]),
                node_sequence=[str(item) for item in route["node_sequence"]],
            )
            for route in payload.get("routes", [])
        ]
    )


def _sealed_costs() -> dict[tuple[str, int], float]:
    rows = list(csv.DictReader(SEALED_S3_RAW.open(encoding="utf-8", newline="")))
    # The sealed S3 raw has four paper arms; this checks the registered
    # representative ledger without touching it.
    values: dict[tuple[str, int], float] = {}
    for row in rows:
        if row["instance_id"] != TARGET_INSTANCE:
            continue
        arm = row["arm"]
        if arm not in ARMS:
            continue
        if row["status"] != "OK":
            raise RuntimeError(f"sealed S3 row is not OK: {arm}/seed{row['seed']}")
        key = (arm, int(row["seed"]))
        values[key] = float(row["cost"])
    expected = {(arm, seed) for arm in ARMS for seed in SEEDS}
    if set(values) != expected:
        raise RuntimeError(
            f"sealed S3 representative rows are incomplete: {len(values)} / {len(expected)}"
        )
    return values


def _protected_hashes() -> dict[str, str]:
    paths = [
        ROOT / "solver/src/setp_solver/cost.py",
        ROOT / "solver/src/setp_solver/check.py",
        ROOT / "solver/src/setp_solver/search/evaluation.py",
        ROOT / "solver/src/setp_solver/prices.py",
        ROOT / "docs/paper_submission_final/RETIRED_paper_main.tex",
        PACKAGE / "run_p3_china81_formal.py",
        P3_RAW,
        SEALED_S3_RAW,
        REPRESENTATIVE_DIR / "run_s3_representative.py",
    ]
    return {
        str(path.relative_to(ROOT)): _sha256(path)
        for path in paths
        if path.is_file()
    }


class ObservableGeneticAlgorithm(GeneticAlgorithm):
    """PyVRP 0.12.2 GeneticAlgorithm with a non-invasive best hook."""

    def __init__(self, *args: Any, on_new_best: Callable[..., None], **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._on_new_best = on_new_best

    def run(
        self,
        stop,
        collect_stats: bool = True,
        display: bool = False,
        display_interval: float = 5.0,
    ) -> Result:
        # This is the PyVRP 0.12.2 run loop, with the hook placed after the
        # existing _improve_offspring call.  No random or solver state is
        # changed by the hook.
        print_progress = ProgressPrinter(display, display_interval)
        print_progress.start(self._data)

        start = time.perf_counter()
        stats = Statistics(collect_stats=collect_stats)
        iters = 0
        iters_no_improvement = 1

        for sol in self._initial_solutions:
            self._pop.add(sol, self._cost_evaluator)

        while not stop(self._cost_evaluator.cost(self._best)):
            iters += 1

            if iters_no_improvement == self._params.num_iters_no_improvement:
                print_progress.restart()

                iters_no_improvement = 1
                self._pop.clear()

                for sol in self._initial_solutions:
                    self._pop.add(sol, self._cost_evaluator)

            curr_best = self._cost_evaluator.cost(self._best)

            parents = self._pop.select(self._rng, self._cost_evaluator)
            offspring = self._crossover(
                parents, self._data, self._cost_evaluator, self._rng
            )
            self._improve_offspring(offspring)

            new_best = self._cost_evaluator.cost(self._best)

            if new_best < curr_best:
                iters_no_improvement = 1
                self._on_new_best(self._best, new_best, iters)
            else:
                iters_no_improvement += 1

            stats.collect_from(self._pop, self._cost_evaluator)
            print_progress.iteration(stats)

        end = time.perf_counter() - start
        res = Result(self._best, stats, iters, end)
        print_progress.end(res)
        return res


def _run_epoch_observed(
    bundle: Any,
    problem: Any,
    common_initial_solution: Solution,
    *,
    seed: int,
    stop: Any,
    warm_elites: tuple[Solution, ...],
    timeline_started: float,
    arm: str,
    epoch_label: str,
) -> tuple[HgsExactEpoch, list[dict[str, Any]]]:
    """Run the sealed epoch logic and collect only native-best skeletons."""
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
    snapshots: list[dict[str, Any]] = []

    def on_new_best(native: NativeSolution, proxy_cost: int, iteration: int) -> None:
        skeleton = _translate_solution(native, problem)
        snapshots.append(
            {
                "elapsed_seconds": float(perf_counter() - timeline_started),
                "proxy_cost": int(proxy_cost),
                "iteration": int(iteration),
                "arm": arm,
                "epoch": epoch_label,
                "source": "hgs_new_population_best",
                "skeleton": _skeleton_payload(skeleton),
            }
        )

    algorithm = ObservableGeneticAlgorithm(
        data,
        penalty_manager,
        rng,
        population,
        local_search,
        crossover,
        initial_solutions,
        params.genetic,
        on_new_best=on_new_best,
    )
    result = algorithm.run(stop, collect_stats=False, display=False)
    cost_evaluator = penalty_manager.cost_evaluator()
    feasible = [item for item in population if item.is_feasible()]
    feasible.append(result.best)
    unique: dict[tuple[Any, ...], Any] = {}
    for native in feasible:
        unique.setdefault(_native_solution_key(native), native)
    proxy_ranked = sorted(unique.values(), key=cost_evaluator.cost)[:24]
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
    selected = exact_ranked[:8]
    proxy_best_completion = complete_china81_route_skeleton(
        _translate_solution(result.best, problem), bundle
    )
    epoch = HgsExactEpoch(
        elite_skeletons=tuple(item[0] for item in selected),
        elite_completions=tuple(item[1] for item in selected),
        proxy_best_completion=proxy_best_completion,
        elapsed_seconds=perf_counter() - started,
        stats={"seed": int(seed), "hgs_iterations": int(result.num_iterations)},
    )
    return epoch, snapshots


def _common(bundle: Any) -> Any:
    return complete_china81_route_skeleton(
        build_initial_solution(
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
            introduce_ev=False,
            require_charging_signal=False,
        ),
        bundle,
    )


def _single_arm(
    bundle: Any,
    instance_id: str,
    seed: int,
    mode: str,
) -> tuple[float, float, list[dict[str, Any]], Solution, dict[str, Any], int, float]:
    caps = p3.TIER_CAPS[p3._tier_of(instance_id)]
    common = _common(bundle)
    started = perf_counter()
    problem = p3.build_pyvrp_problem(bundle, route_proxy_mode=mode)
    stop = MultipleCriteria(
        [p3.NoImprovement(int(caps["K_M"])), p3.MaxRuntime(caps["CAP_M"])]
    )
    epoch, snapshots = _run_epoch_observed(
        bundle,
        problem,
        common.solution,
        seed=seed,
        stop=stop,
        warm_elites=(),
        timeline_started=started,
        arm=mode,
        epoch_label="single_view",
    )
    completion = min((*epoch.elite_completions, common), key=lambda item: item.objective)
    objective, breakdown, violations = exact_china81_score(completion.solution, bundle)
    return (
        float(objective),
        perf_counter() - started,
        snapshots,
        completion.solution,
        breakdown,
        int(epoch.stats.get("hgs_iterations", -1)),
        float(common.objective),
    )


def _full_arm(
    bundle: Any,
    instance_id: str,
    seed: int,
) -> tuple[float, float, list[dict[str, Any]], Solution, dict[str, Any], int, int, float]:
    caps = p3.TIER_CAPS[p3._tier_of(instance_id)]
    common = _common(bundle)
    started = perf_counter()
    mother_problem = p3.build_pyvrp_problem(bundle, route_proxy_mode="mechanism_ev")
    mother_stop = MultipleCriteria(
        [p3.NoImprovement(int(caps["K_M"])), p3.MaxRuntime(caps["CAP_M"])]
    )
    mother_epoch, snapshots = _run_epoch_observed(
        bundle,
        mother_problem,
        common.solution,
        seed=seed,
        stop=mother_stop,
        warm_elites=(),
        timeline_started=started,
        arm="MV-HGS-SP",
        epoch_label="mechanism_ev_mother",
    )
    mother_completion = min(
        (*mother_epoch.elite_completions, common), key=lambda item: item.objective
    )
    best_completion = mother_completion
    global_best = float(mother_completion.objective)
    view_epochs = {"mechanism_ev": mother_epoch}
    elites = mother_epoch.elite_skeletons
    stall = 0
    epochs_run = 0
    total_iterations = int(mother_epoch.stats.get("hgs_iterations", -1))
    for epoch_index in range(MAX_EPOCHS):
        improved = False
        pool = _route_pool_records(bundle, view_epochs)
        sp_solution, _sp_stats = _solve_set_partitioning(
            bundle,
            pool,
            time_limit_seconds=SP_TIME,
        )
        if sp_solution is not None:
            sp_completion = complete_china81_route_skeleton(sp_solution, bundle)
            snapshots.append(
                {
                    "elapsed_seconds": float(perf_counter() - started),
                    "proxy_cost": None,
                    "iteration": None,
                    "arm": "MV-HGS-SP",
                    "epoch": f"sp_round_{epoch_index + 1}",
                    "source": "set_partitioning_candidate",
                    "skeleton": _skeleton_payload(sp_solution),
                }
            )
            if sp_completion.objective < global_best - EPS:
                global_best = float(sp_completion.objective)
                best_completion = sp_completion
                improved = True
        mode = ROTATION[epoch_index % len(ROTATION)]
        problem = p3.build_pyvrp_problem(bundle, route_proxy_mode=mode)
        epoch_stop = MultipleCriteria(
            [p3.NoImprovement(int(caps["K_E"])), p3.MaxRuntime(caps["CAP_E"])]
        )
        epoch_seed = int(seed) + 1009 * (epoch_index + 1)
        epoch, epoch_snapshots = _run_epoch_observed(
            bundle,
            problem,
            best_completion.solution,
            seed=epoch_seed,
            stop=epoch_stop,
            warm_elites=(best_completion.solution, *elites),
            timeline_started=started,
            arm="MV-HGS-SP",
            epoch_label=f"{mode}_continuation_{epoch_index + 1}",
        )
        snapshots.extend(epoch_snapshots)
        total_iterations += int(epoch.stats.get("hgs_iterations", -1))
        epoch_best = min(epoch.elite_completions, key=lambda item: item.objective)
        if epoch_best.objective < global_best - EPS:
            global_best = float(epoch_best.objective)
            best_completion = epoch_best
            improved = True
        view_epochs[mode] = epoch
        elites = epoch.elite_skeletons
        epochs_run += 1
        stall = 0 if improved else stall + 1
        if stall >= STALL_EPOCHS:
            break
    objective, breakdown, _violations = exact_china81_score(
        best_completion.solution,
        bundle,
    )
    return (
        float(objective),
        perf_counter() - started,
        snapshots,
        best_completion.solution,
        breakdown,
        epochs_run,
        total_iterations,
        float(common.objective),
    )


_WORKER_SEALED: dict[tuple[str, int], float] = {}


def _init_worker(sealed: dict[tuple[str, int], float]) -> None:
    global _WORKER_SEALED
    _WORKER_SEALED = sealed


def _worker_unit(task: tuple[str, int, str]) -> dict[str, Any]:
    return _run_unit(task, _WORKER_SEALED)


def _run_unit(args: tuple[str, int, str], sealed: dict[tuple[str, int], float]) -> dict[str, Any]:
    instance_id, seed, arm = args
    sealed_cost = sealed[(arm, seed)]
    row: dict[str, Any] = {
        "instance_id": instance_id,
        "n": p3._tier_of(instance_id),
        "seed": seed,
        "arm": arm,
        "status": "ERROR",
        "sealed_cost": sealed_cost,
        "rerun_cost": None,
        "cost_equal": False,
        "cost_delta": None,
        "cpu_seconds": None,
        "violation_count": None,
        "violations": "",
        "epochs_run": None,
        "hgs_iterations": None,
        "snapshot_count": 0,
        "snapshot_file": "",
        "error_type": "",
        "error": "",
        "_snapshots": [],
        "_final_skeleton": None,
        "_common_cost": None,
    }
    try:
        bundle = p3.load_china81_bundle(ROOT, instance_id)
        if arm == "MV-HGS-SP":
            (
                objective,
                cpu,
                snapshots,
                solution,
                _breakdown,
                epochs,
                iterations,
                common_cost,
            ) = _full_arm(bundle, instance_id, seed)
        else:
            (
                objective,
                cpu,
                snapshots,
                solution,
                _breakdown,
                iterations,
                common_cost,
            ) = _single_arm(bundle, instance_id, seed, arm)
            epochs = 1
        _, _, violations = exact_china81_score(solution, bundle)
        equal = float(objective) == float(sealed_cost)
        row.update(
            {
                "status": "OK" if not violations and equal else "HALT_COST_MISMATCH" if not violations else "INFEASIBLE",
                "rerun_cost": float(objective),
                "cost_equal": equal,
                "cost_delta": float(objective) - float(sealed_cost),
                "cpu_seconds": float(cpu),
                "violation_count": len(violations),
                "violations": json.dumps([str(item) for item in violations], ensure_ascii=False),
                "epochs_run": int(epochs),
                "hgs_iterations": int(iterations),
                "snapshot_count": len(snapshots) + 2,
                "_snapshots": snapshots,
                "_final_skeleton": _skeleton_payload(solution),
                "_common_cost": common_cost,
            }
        )
        if not equal and not violations:
            row["error_type"] = "SEALED_FINAL_COST_MISMATCH"
            row["error"] = (
                f"sealed={sealed_cost!r}; rerun={objective!r}; "
                "observation-only rerun is not admissible"
            )
        elif violations:
            row["error_type"] = "EXACT_SCORE_VIOLATION"
            row["error"] = "rerun final solution has exact-score violations"
    except Exception as exc:  # preserve the scene in the row; parent stops the batch
        row.update({"error_type": type(exc).__name__, "error": str(exc)})
    return row


def _existing_rows(path: Path) -> dict[tuple[str, int, str], dict[str, str]]:
    if not path.exists():
        return {}
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    output: dict[tuple[str, int, str], dict[str, str]] = {}
    for row in rows:
        key = (row["instance_id"], int(row["seed"]), row["arm"])
        if key in output:
            raise RuntimeError(f"duplicate observation row: {key}")
        output[key] = row
    return output


def _append_raw(path: Path, row: dict[str, Any], first: bool) -> None:
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OBS_FIELDS)
        if first:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in OBS_FIELDS})
        handle.flush()


def _snapshot_path(arm: str, seed: int) -> Path:
    return OUT / "snapshots" / f"{arm}_seed{seed}.json"


def _write_snapshot_file(row: dict[str, Any]) -> None:
    path = _snapshot_path(row["arm"], int(row["seed"]))
    snapshots = [
        {
            "elapsed_seconds": 0.0,
            "proxy_cost": None,
            "iteration": 0,
            "arm": row["arm"],
            "epoch": "initial",
            "source": "common_initial",
            "skeleton": row["_common_skeleton"],
            "exact_cost_at_initialization": row["_common_cost"],
        },
        *row.get("_snapshots", []),
        {
            "elapsed_seconds": float(row["cpu_seconds"] or 0.0),
            "proxy_cost": None,
            "iteration": None,
            "arm": row["arm"],
            "epoch": "final",
            "source": "final_rerun_solution",
            "skeleton": row["_final_skeleton"],
        },
    ]
    _write_json(
        path,
        {
            "schema_version": "resetp.e2-final-campaign.s3-trajectory-snapshots.v1",
            "instance_id": row["instance_id"],
            "seed": int(row["seed"]),
            "arm": row["arm"],
            "observation_only": True,
            "callback_contract": "new proxy global best only; no scoring, repair, mutation, or RNG draw",
            "points": snapshots,
        },
    )
    row["snapshot_file"] = str(path.relative_to(OUT))


def _status(completed: int, total: int, last: dict[str, Any] | None = None) -> None:
    _write_json(
        OUT / "status.json",
        {
            "completed": int(completed),
            "total": int(total),
            "last": {
                key: value
                for key, value in (last or {}).items()
                if not key.startswith("_")
            },
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )


def _offline_score_snapshot(
    bundle: Any,
    point: dict[str, Any],
    order: int,
) -> dict[str, Any]:
    try:
        skeleton = _solution_from_payload(point["skeleton"])
        completion = complete_china81_route_skeleton(skeleton, bundle)
        objective, _breakdown, violations = exact_china81_score(completion.solution, bundle)
        return {
            "order": int(order),
            "elapsed_seconds": float(point["elapsed_seconds"]),
            "source": point["source"],
            "iteration": point.get("iteration"),
            "proxy_cost": point.get("proxy_cost"),
            "status": "OK" if not violations else "INFEASIBLE",
            "exact_cost": float(objective),
            "violation_count": len(violations),
            "violations": [str(item) for item in violations],
        }
    except Exception as exc:
        return {
            "order": int(order),
            "elapsed_seconds": float(point["elapsed_seconds"]),
            "source": point["source"],
            "iteration": point.get("iteration"),
            "proxy_cost": point.get("proxy_cost"),
            "status": "ERROR",
            "exact_cost": None,
            "violation_count": None,
            "violations": [],
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _materialize_curve(
    row: dict[str, str],
    sealed: dict[tuple[str, int], float],
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = p3.load_china81_bundle(ROOT, row["instance_id"])
    path = OUT / row["snapshot_file"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    scored = [
        _offline_score_snapshot(bundle, point, order)
        for order, point in enumerate(payload["points"])
    ]
    valid = [item for item in scored if item["status"] == "OK"]
    valid.sort(key=lambda item: (item["elapsed_seconds"], item["order"]))
    best = math.inf
    curve: list[dict[str, Any]] = []
    for item in valid:
        cost = float(item["exact_cost"])
        if cost < best - EPS:
            best = cost
            curve.append(
                {
                    "elapsed_seconds": float(item["elapsed_seconds"]),
                    "cost": cost,
                    "source": item["source"],
                }
            )
    sealed_cost = sealed[(row["arm"], int(row["seed"]))]
    final_cost = float(row["rerun_cost"])
    if not math.isfinite(best) or best != final_cost or final_cost != sealed_cost:
        raise RuntimeError(
            f"offline curve final mismatch for {row['arm']}/seed{row['seed']}: "
            f"curve={best!r}, rerun={final_cost!r}, sealed={sealed_cost!r}"
        )
    if not curve or curve[-1]["cost"] != sealed_cost:
        curve.append(
            {
                "elapsed_seconds": float(row["cpu_seconds"]),
                "cost": sealed_cost,
                "source": "final_rerun_solution",
            }
        )
    result = {
        "schema_version": "resetp.e2-final-campaign.s3-materialized-trajectory.v1",
        "instance_id": row["instance_id"],
        "seed": int(row["seed"]),
        "arm": row["arm"],
        "cost_definition": "exact_china81_score objective",
        "time_definition": "elapsed wall seconds from the arm runner start",
        "curve_rule": "monotone running minimum over offline-completed snapshots",
        "points": curve,
        "offline_snapshot_audit": {
            "total": len(scored),
            "valid": len(valid),
            "errors": sum(item["status"] == "ERROR" for item in scored),
            "infeasible": sum(item["status"] == "INFEASIBLE" for item in scored),
        },
    }
    audit = {
        "instance_id": row["instance_id"],
        "seed": int(row["seed"]),
        "arm": row["arm"],
        "sealed_cost": sealed_cost,
        "rerun_cost": final_cost,
        "curve_final_cost": best,
        "exact_equal": final_cost == sealed_cost == best,
        "snapshot_audit": result["offline_snapshot_audit"],
    }
    return result, audit


def _select_avg_nearest(rows: list[dict[str, str]]) -> dict[str, int]:
    selected: dict[str, int] = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        average = statistics.fmean(float(row["rerun_cost"]) for row in arm_rows)
        winner = min(
            arm_rows,
            key=lambda row: (
                abs(float(row["rerun_cost"]) - average),
                int(row["seed"]),
            ),
        )
        selected[arm] = int(winner["seed"])
    return selected


def _clean_appledouble() -> bool:
    removed = False
    for path in OUT.rglob("._*"):
        if path.is_file():
            path.unlink()
            removed = True
    return removed


def _archive_prior_failure_artifacts() -> None:
    """Keep a failed v1 materialization scene before a narrow resume."""
    decision_path = OUT / "decision.json"
    if not decision_path.is_file():
        return
    try:
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if str(decision.get("decision", "")).startswith("PASS_"):
        return
    for name in (
        "decision.json",
        "metadata.json",
        "report.md",
        "artifact_hashes.json",
        "offline_recheck.json",
    ):
        source = OUT / name
        if not source.is_file():
            continue
        suffix = source.suffix
        target = OUT / f"{source.stem}_halt_v1{suffix}"
        if not target.exists():
            shutil.copy2(source, target)


def _normalise_snapshot_paths(
    path: Path,
    rows: dict[tuple[str, int, str], dict[str, str]],
) -> None:
    """Backfill paths for rows emitted before the v1 writer fix."""
    changed = False
    for row in rows.values():
        if row.get("snapshot_file", "").strip():
            continue
        row["snapshot_file"] = str(
            _snapshot_path(row["arm"], int(row["seed"])).relative_to(OUT)
        )
        changed = True
    if not changed:
        return
    temporary = path.with_name(f".{path.name}.normalising")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OBS_FIELDS)
        writer.writeheader()
        writer.writerows(
            {field: row.get(field, "") for field in OBS_FIELDS}
            for row in rows.values()
        )
        handle.flush()
    temporary.replace(path)


def _hash_inputs() -> list[Path]:
    paths = [
        OUT / "task_card_s3_traj_v4.md",
        OUT / "monitor_s3_traj_v4.json",
        OUT / "run_s3_trajectory_v4.py",
        P3_RAW,
        SEALED_S3_RAW,
        REPRESENTATIVE_DIR / "decision.json",
        REPRESENTATIVE_DIR / "representative_registration.json",
        OBS_RAW,
        OUT / "offline_recheck.json",
        OUT / "decision.json",
        OUT / "metadata.json",
        OUT / "report.md",
    ]
    paths.extend(path for path in (OUT / "snapshots").rglob("*") if path.is_file())
    paths.extend(path for path in (OUT / "materialized_trajectories").rglob("*") if path.is_file())
    paths.extend(path for path in OUT.glob("*_halt_v1.*") if path.is_file())
    return [
        path
        for path in paths
        if path.is_file()
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    ]


def _write_report(decision: str, rows: list[dict[str, str]], audit: list[dict[str, Any]], selected: dict[str, int] | None, error: str | None = None) -> None:
    lines = [
        "# S3-TRAJ-V4 observation-only trajectory rerun",
        "",
        f"Decision: `{decision}`.",
        "",
        "The sealed S3 `raw_runs.csv` was read-only. The rerun used the registered "
        "representative instance, the same four arms, seeds 1--10, PyVRP 0.12.2, "
        "stopping criteria, continuation seeds, and SP time limit.",
        "",
        "The only code addition was a local observer around the PyVRP 0.12.2 "
        "Python loop. It copied the translated route skeleton when the proxy global "
        "best improved. The observer did not call the exact scorer, completioner, "
        "repair code, RNG, or solver mutation. Completion and exact scoring were "
        "performed offline after each HGS unit ended.",
        "",
        f"Completed rows: {len(rows)}/40.",
    ]
    if error:
        lines.extend(["", f"HALT detail: {error}"])
    if rows:
        exact = sum(str(row.get("cost_equal", "")).lower() == "true" for row in rows)
        lines.extend(["", f"Final-cost exact equality: {exact}/{len(rows)} completed rows."])
    if audit:
        offline_errors = sum(item["snapshot_audit"]["errors"] for item in audit)
        offline_infeasible = sum(item["snapshot_audit"]["infeasible"] for item in audit)
        lines.extend([
            "",
            f"Offline snapshot audit: {len(audit)} units; "
            f"{offline_errors} completion errors and {offline_infeasible} infeasible snapshots "
            f"were retained rather than filtered from the audit.",
        ])
    if selected:
        lines.extend([
            "",
            "Pre-registered Figure 4 selection rule: per arm, choose the seed whose "
            "sealed final cost is closest to that arm's ten-seed average; ties use "
            "the smaller seed.",
            "",
            "Selected seeds: " + ", ".join(f"{arm}=seed{selected[arm]}" for arm in ARMS) + ".",
        ])
    lines.extend([
        "",
        "No algorithm, evaluator, protected raw ledger, or sealed S3 value is changed "
        "by this lane. The observation rerun authorizes only a presentation-level "
        "trajectory artifact if all 40 final costs are exactly equal to sealed S3.",
    ])
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _finalize(decision: dict[str, Any], metadata: dict[str, Any]) -> None:
    _write_json(OUT / "decision.json", decision)
    _write_json(OUT / "metadata.json", metadata)
    _clean_appledouble()
    paths = _hash_inputs()
    _write_json(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.s3-trajectory-v4",
            "algorithm": "sha256",
            "appledouble_excluded": True,
            "integrity_flags": [APPLEDOUBLE_FLAG],
            "files": {
                str(path.relative_to(ROOT)): _sha256(path)
                for path in paths
                if not path.name.startswith("._")
            },
        },
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--unit",
        help="probe one unit as instance_id:seed:arm; does not write the formal decision",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "snapshots").mkdir(exist_ok=True)
    (OUT / "materialized_trajectories").mkdir(exist_ok=True)
    _archive_prior_failure_artifacts()
    if not S3_DECISION.is_file() or json.loads(S3_DECISION.read_text(encoding="utf-8")).get("decision") != "PASS_S3_REPRESENTATIVE":
        raise SystemExit("sealed S3 decision is not PASS_S3_REPRESENTATIVE")
    registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
    if registration.get("selected_instance_id") != TARGET_INSTANCE:
        raise SystemExit("registered representative differs from the authorized trajectory target")
    sealed = _sealed_costs()

    if args.unit:
        instance_id, seed_text, arm = args.unit.split(":", 2)
        row = _run_unit((instance_id, int(seed_text), arm), sealed)
        probe_bundle = p3.load_china81_bundle(ROOT, instance_id)
        probe_common = _common(probe_bundle)
        row["_common_skeleton"] = _skeleton_payload(probe_common.solution)
        probe_dir = OUT / "probe"
        probe_dir.mkdir(exist_ok=True)
        row["snapshot_file"] = "probe_snapshot.json"
        _write_json(probe_dir / "probe_snapshot.json", {
            "row": {key: value for key, value in row.items() if not key.startswith("_")},
            "snapshots": row.get("_snapshots", []),
        })
        _write_json(probe_dir / "probe_result.json", {key: value for key, value in row.items() if not key.startswith("_")})
        print(f"[S3-TRAJ probe] {row['arm']} seed={row['seed']} status={row['status']} cost={row['rerun_cost']}", flush=True)
        return 0 if row["status"] == "OK" else 2

    existing = _existing_rows(OBS_RAW)
    _normalise_snapshot_paths(OBS_RAW, existing)
    for key, row in existing.items():
        if row.get("status") != "OK" or row.get("cost_equal", "").lower() != "true":
            raise SystemExit(f"existing S3-TRAJ row is not a passing exact replay: {key}")
    tasks = [
        (TARGET_INSTANCE, seed, arm)
        for seed in SEEDS
        for arm in ARMS
        if (TARGET_INSTANCE, seed, arm) not in existing
    ]
    rows = list(existing.values())
    total = len(SEEDS) * len(ARMS)
    _status(len(rows), total)
    print(f"[S3-TRAJ] {len(rows)} complete; {len(tasks)} remaining", flush=True)
    first = not OBS_RAW.exists()
    if tasks:
        pool = mp.Pool(
            processes=max(1, int(args.workers)),
            initializer=_init_worker,
            initargs=(sealed,),
        )
        terminated = False
        try:
            for row in pool.imap_unordered(_worker_unit, tasks):
                if row["status"] != "OK":
                    pool.terminate()
                    terminated = True
                    _append_raw(OBS_RAW, row, first)
                    first = False
                    rows.append({field: row.get(field, "") for field in OBS_FIELDS})
                    _write_json(OUT / "decision.json", {
                        "schema_version": "resetp.e2-final-campaign.s3-trajectory-v4",
                        "decision": "HALT_S3_TRAJ_FINAL_COST_OR_QUALITY_GATE",
                        "failed_row": {field: row.get(field, "") for field in OBS_FIELDS},
                    })
                    _write_report(
                        "HALT_S3_TRAJ_FINAL_COST_OR_QUALITY_GATE",
                        rows,
                        [],
                        None,
                        error=row.get("error") or row.get("error_type"),
                    )
                    _finalize(
                        json.loads((OUT / "decision.json").read_text(encoding="utf-8")),
                        {"schema_version": "resetp.e2-final-campaign.s3-trajectory-metadata.v1", "protected_hashes": _protected_hashes()},
                    )
                    return 2
                row["_common_skeleton"] = _skeleton_payload(
                    _common(p3.load_china81_bundle(ROOT, row["instance_id"])).solution
                )
                _write_snapshot_file(row)
                _append_raw(OBS_RAW, row, first)
                first = False
                rows.append({field: row.get(field, "") for field in OBS_FIELDS})
                _status(len(rows), total, row)
                print(f"[S3-TRAJ] seed={row['seed']} arm={row['arm']} exact={row['cost_equal']} cost={row['rerun_cost']}", flush=True)
        except BaseException:
            if not terminated:
                pool.terminate()
                terminated = True
            raise
        finally:
            if not terminated:
                pool.close()
            pool.join()

    if len(rows) != total:
        raise SystemExit(f"S3-TRAJ raw row count is {len(rows)}, expected {total}")
    rows = list(csv.DictReader(OBS_RAW.open(encoding="utf-8", newline="")))
    audit: list[dict[str, Any]] = []
    materialized: list[dict[str, Any]] = []
    try:
        for row in rows:
            result, item_audit = _materialize_curve(row, sealed)
            _write_json(OUT / "materialized_trajectories" / f"{row['arm']}_seed{row['seed']}.json", result)
            audit.append(item_audit)
            materialized.append(result)
        _write_json(OUT / "offline_recheck.json", {"units": audit, "all_exact": all(item["exact_equal"] for item in audit)})
        selected = _select_avg_nearest(rows)
        curve_rows: list[dict[str, Any]] = []
        for result in materialized:
            if selected[result["arm"]] != int(result["seed"]):
                continue
            for point in result["points"]:
                curve_rows.append({
                    "algorithm": result["arm"],
                    "seed": result["seed"],
                    "elapsed_minutes": float(point["elapsed_seconds"]) / 60.0,
                    "elapsed_seconds": point["elapsed_seconds"],
                    "cost_cny": point["cost"],
                    "source": point["source"],
                })
        with (OUT / "curve_data_v4.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["algorithm", "seed", "elapsed_minutes", "elapsed_seconds", "cost_cny", "source"])
            writer.writeheader()
            writer.writerows(curve_rows)
        decision = {
            "schema_version": "resetp.e2-final-campaign.s3-trajectory-v4",
            "decision": "PASS_S3_TRAJ_OBSERVATION_ONLY",
            "instance_id": TARGET_INSTANCE,
            "units": total,
            "final_cost_exact_matches": total,
            "algorithm_or_score_changed": False,
            "random_stream_changed": False,
            "offline_scoring_after_solver_end": True,
            "figure4_selection": "per-arm final-cost average-nearest seed; seed lexicographic tie-break",
            "selected_seeds": selected,
            "curve_data": "curve_data_v4.csv",
            "sealed_s3_raw_unchanged": True,
            "integrity_flags": [APPLEDOUBLE_FLAG],
        }
        metadata = {
            "schema_version": "resetp.e2-final-campaign.s3-trajectory-metadata.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "command": " ".join([sys.executable, *sys.argv]),
            "git_head": "UNAVAILABLE",
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "workers": int(args.workers),
            "protected_hashes": _protected_hashes(),
            "source_sha256": {"p3_raw": _sha256(P3_RAW), "s3_raw": _sha256(SEALED_S3_RAW)},
            "observation_contract": {
                "callback": "new proxy global best",
                "callback_side_effects": "copy translated skeleton and wall-clock timestamp only",
                "exact_score_timing": "offline after each solver unit",
                "same_seeds": list(SEEDS),
                "arms": list(ARMS),
            },
        }
        _write_report("PASS_S3_TRAJ_OBSERVATION_ONLY", rows, audit, selected)
        _finalize(decision, metadata)
        _write_json(OUT / "done.json", {"decision": decision["decision"], "completed_at_utc": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        _write_json(OUT / "offline_recheck.json", {"all_exact": False, "error_type": type(exc).__name__, "error": str(exc), "units": audit})
        decision = {
            "schema_version": "resetp.e2-final-campaign.s3-trajectory-v4",
            "decision": "HALT_S3_TRAJ_OFFLINE_CURVE_GATE",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "sealed_s3_raw_unchanged": True,
        }
        metadata = {"schema_version": "resetp.e2-final-campaign.s3-trajectory-metadata.v1", "protected_hashes": _protected_hashes()}
        _write_report("HALT_S3_TRAJ_OFFLINE_CURVE_GATE", rows, audit, None, error=str(exc))
        _finalize(decision, metadata)
        return 2
    _status(total, total, {"decision": "PASS_S3_TRAJ_OBSERVATION_ONLY"})
    print("[S3-TRAJ] PASS_S3_TRAJ_OBSERVATION_ONLY", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
