#!/usr/bin/env python3
"""Observation-only trajectories for the corrected D6 S3 comparison.

For each algorithm, the seed whose final cost is closest to its ten-seed mean
is registered before trajectory observation. During HGS, a hook only copies a
new proxy-best route skeleton and timestamp; it performs no exact evaluation,
repair, mutation, or random draw. All copied skeletons are completed and
scored after the run. Official S3 costs are never changed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable


REPO = Path(__file__).resolve().parents[3]
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v2_20260723"
)
S3 = CAMPAIGN / "representative_gate"
OUT = S3 / "trajectories"
FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from epochal_hgs import HgsExactEpoch  # noqa: E402
from pyvrp.GeneticAlgorithm import GeneticAlgorithm  # noqa: E402
from pyvrp.PenaltyManager import PenaltyManager  # noqa: E402
from pyvrp.Population import Population  # noqa: E402
from pyvrp.ProgressPrinter import ProgressPrinter  # noqa: E402
from pyvrp.Result import Result  # noqa: E402
from pyvrp.Statistics import Statistics  # noqa: E402
from pyvrp._pyvrp import RandomNumberGenerator  # noqa: E402
from pyvrp._pyvrp import Solution as NativeSolution  # noqa: E402
from pyvrp.crossover import (  # noqa: E402
    ordered_crossover,
    selective_route_exchange,
)
from pyvrp.diversity import broken_pairs_distance  # noqa: E402
from pyvrp.search import LocalSearch, compute_neighbours  # noqa: E402
from pyvrp.solve import SolveParams  # noqa: E402
from pyvrp.stop import MaxIterations, MaxRuntime, MultipleCriteria  # noqa: E402
from pyvrp_adapter import (  # noqa: E402
    _native_solution_key,
    _project_initial_solution,
    _translate_solution,
    build_pyvrp_problem,
)
from route_pool_sp import (  # noqa: E402
    _route_pool_records,
    _solve_set_partitioning,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import Route, Solution  # noqa: E402


ARMS = ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP")
VIEW_BY_ARM = {
    "HGS-F": "cv_only",
    "HGS-E": "naive_ev",
    "HGS-M": "mechanism_ev",
}
VIEW_ORDER = ("cv_only", "naive_ev", "mechanism_ev")
MAX_HGS_ITERATIONS = 5_000
MAX_ARCHIVE = 24
EXACT_ELITES = 8
MIP_SECONDS = 5.0
EPS = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def skeleton_payload(solution: Solution) -> dict[str, Any]:
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


def solution_from_payload(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(route["vehicle_id"]),
                vehicle_type=str(route["vehicle_type"]),
                home_depot_id=str(route["home_depot_id"]),
                node_sequence=[
                    str(item) for item in route["node_sequence"]
                ],
            )
            for route in payload["routes"]
        ]
    )


def load_initial(instance_id: str) -> Solution:
    payload = json.loads(
        (FLEET / "witnesses" / f"{instance_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return solution_from_payload(payload)


class AuditedWallclockSafety:
    def __init__(self, seconds: float) -> None:
        self._criterion = MaxRuntime(seconds)
        self.triggered = False

    def __call__(self, best_cost: float) -> bool:
        self.triggered = bool(self._criterion(best_cost))
        return self.triggered


class ObservableGeneticAlgorithm(GeneticAlgorithm):
    """PyVRP 0.12.2 loop with one copy-only new-best hook."""

    def __init__(
        self,
        *args: Any,
        on_new_best: Callable[[NativeSolution, int, int], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._on_new_best = on_new_best

    def run(
        self,
        stop: Any,
        collect_stats: bool = True,
        display: bool = False,
        display_interval: float = 5.0,
    ) -> Result:
        printer = ProgressPrinter(display, display_interval)
        printer.start(self._data)
        started = time.perf_counter()
        stats = Statistics(collect_stats=collect_stats)
        iterations = 0
        iterations_without_improvement = 1
        for solution in self._initial_solutions:
            self._pop.add(solution, self._cost_evaluator)
        while not stop(self._cost_evaluator.cost(self._best)):
            iterations += 1
            if (
                iterations_without_improvement
                == self._params.num_iters_no_improvement
            ):
                printer.restart()
                iterations_without_improvement = 1
                self._pop.clear()
                for solution in self._initial_solutions:
                    self._pop.add(solution, self._cost_evaluator)
            current_best = self._cost_evaluator.cost(self._best)
            parents = self._pop.select(
                self._rng,
                self._cost_evaluator,
            )
            offspring = self._crossover(
                parents,
                self._data,
                self._cost_evaluator,
                self._rng,
            )
            self._improve_offspring(offspring)
            new_best = self._cost_evaluator.cost(self._best)
            if new_best < current_best:
                iterations_without_improvement = 1
                self._on_new_best(
                    self._best,
                    int(new_best),
                    int(iterations),
                )
            else:
                iterations_without_improvement += 1
            stats.collect_from(self._pop, self._cost_evaluator)
            printer.iteration(stats)
        elapsed = time.perf_counter() - started
        result = Result(self._best, stats, iterations, elapsed)
        printer.end(result)
        return result


@dataclass(frozen=True)
class ObservedEpoch:
    epoch: HgsExactEpoch
    snapshots: tuple[dict[str, Any], ...]


def run_observed_epoch(
    bundle: Any,
    initial: Solution,
    mode: str,
    seed: int,
) -> ObservedEpoch:
    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode=mode,
        hard_home_depot_lock=False,
    )
    data = problem.model.data()
    params = SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))
    neighbours = compute_neighbours(data, params.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    active_node: list[str] = []
    for node_op in params.node_ops:
        if node_op.supports(data):
            local_search.add_node_operator(node_op(data))
            active_node.append(node_op.__name__)
    active_route: list[str] = []
    for route_op in params.route_ops:
        if route_op.supports(data):
            local_search.add_route_operator(route_op(data))
            active_route.append(route_op.__name__)
    penalties = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    random_count = int(params.population.min_pop_size)
    initial_native = [
        NativeSolution.make_random(data, rng)
        for _ in range(random_count)
    ]
    crossover = (
        selective_route_exchange
        if data.num_vehicles > 1
        else ordered_crossover
    )
    snapshots: list[dict[str, Any]] = []
    started = perf_counter()

    def on_new_best(
        native: NativeSolution,
        proxy_cost: int,
        iteration: int,
    ) -> None:
        snapshots.append(
            {
                "elapsed_seconds": perf_counter() - started,
                "iteration": iteration,
                "proxy_cost": proxy_cost,
                "source": "hgs_new_proxy_population_best",
                "skeleton": skeleton_payload(
                    _translate_solution(native, problem)
                ),
            }
        )

    algorithm = ObservableGeneticAlgorithm(
        data,
        penalties,
        rng,
        population,
        local_search,
        crossover,
        initial_native,
        params.genetic,
        on_new_best=on_new_best,
    )
    safety = AuditedWallclockSafety(
        max(
            180.0,
            2.0
            * sum(
                node.node_type.lower() == "c"
                for node in bundle.instance.nodes
            ),
        )
    )
    result = algorithm.run(
        MultipleCriteria(
            [MaxIterations(MAX_HGS_ITERATIONS), safety]
        ),
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    evaluator = penalties.cost_evaluator()
    population_items = [
        *initial_native,
        *list(population),
        result.best,
    ]
    unique: dict[tuple[Any, ...], NativeSolution] = {}
    for native in population_items:
        unique.setdefault(_native_solution_key(native), native)
    ranked = sorted(
        unique.values(),
        key=evaluator.cost,
    )[:MAX_ARCHIVE]
    candidates: list[tuple[Solution, Any, int]] = []
    failures: list[str] = []
    for native in ranked:
        try:
            skeleton = _translate_solution(native, problem)
            completion = complete_china81_route_skeleton(
                skeleton,
                bundle,
            )
            candidates.append(
                (skeleton, completion, int(evaluator.cost(native)))
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            failures.append(str(exc))
    common = complete_china81_route_skeleton(initial, bundle)
    candidates.append((initial, common, -1))
    exact_ranked = sorted(
        candidates,
        key=lambda item: (item[1].objective, item[2]),
    )
    selected = exact_ranked[:EXACT_ELITES]
    proxy_failure: str | None = None
    try:
        proxy_best = complete_china81_route_skeleton(
            _translate_solution(result.best, problem),
            bundle,
        )
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        proxy_failure = str(exc)
        proxy_best = min(
            (item[1] for item in candidates),
            key=lambda item: item.objective,
        )
    epoch = HgsExactEpoch(
        elite_skeletons=tuple(item[0] for item in selected),
        elite_completions=tuple(item[1] for item in selected),
        proxy_best_completion=proxy_best,
        elapsed_seconds=perf_counter() - started,
        stats={
            "seed": int(seed),
            "hgs_iterations": int(result.num_iterations),
            "wallclock_safety_triggered": safety.triggered,
            "archive_completion_attempts": len(ranked),
            "archive_completion_failures": failures,
            "proxy_best_completion_failure": proxy_failure,
            "active_node_operators": active_node,
            "active_route_operators": active_route,
        },
    )
    return ObservedEpoch(epoch=epoch, snapshots=tuple(snapshots))


def select_registration() -> dict[str, Any]:
    path = OUT / "trajectory_registration.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    with (S3 / "raw_runs.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        rows = list(csv.DictReader(handle))
    selected: dict[str, int] = {}
    averages: dict[str, float] = {}
    for arm in ARMS:
        arm_rows = [
            row
            for row in rows
            if row["arm"] == arm and row["status"] == "PASS"
        ]
        if len(arm_rows) != 10:
            raise RuntimeError(f"{arm}: expected 10 S3 rows")
        average = sum(float(row["cost"]) for row in arm_rows) / 10.0
        winner = min(
            arm_rows,
            key=lambda row: (
                abs(float(row["cost"]) - average),
                int(row["seed"]),
            ),
        )
        averages[arm] = average
        selected[arm] = int(winner["seed"])
    s3_decision = json.loads(
        (S3 / "decision.json").read_text(encoding="utf-8")
    )
    payload = {
        "schema": "resetp.d6-corrected-s3-trajectory-registration.v1",
        "registered_at_utc": datetime.now(UTC).isoformat(),
        "selection_rule": (
            "for each algorithm, choose the seed whose sealed final cost is "
            "closest to its ten-seed arithmetic mean; lower seed breaks ties"
        ),
        "shape_blind": True,
        "curve_data_read_before_registration": False,
        "representative_instance_id": s3_decision[
            "representative_instance_id"
        ],
        "mean_cost_by_arm": averages,
        "selected_seed_by_arm": selected,
        "s3_raw_sha256": sha256(S3 / "raw_runs.csv"),
    }
    write_json(path, payload)
    return payload


def sealed_costs() -> dict[tuple[str, int], float]:
    with (S3 / "raw_runs.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        return {
            (row["arm"], int(row["seed"])): float(row["cost"])
            for row in csv.DictReader(handle)
            if row["status"] == "PASS"
        }


def offline_points(
    snapshots: list[dict[str, Any]],
    bundle: Any,
    initial_cost: float,
    final_time: float,
    sealed_cost: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    scored: list[dict[str, Any]] = [
        {
            "elapsed_seconds": 0.0,
            "cost": initial_cost,
            "source": "common_initial",
        }
    ]
    errors = 0
    infeasible = 0
    for snapshot in snapshots:
        try:
            completion = complete_china81_route_skeleton(
                solution_from_payload(snapshot["skeleton"]),
                bundle,
            )
            objective, _, violations = exact_china81_score(
                completion.solution,
                bundle,
            )
            if violations:
                infeasible += 1
                continue
            scored.append(
                {
                    "elapsed_seconds": float(
                        snapshot["elapsed_seconds"]
                    ),
                    "cost": float(objective),
                    "source": snapshot["source"],
                }
            )
        except (IndexError, KeyError, TypeError, ValueError):
            errors += 1
    scored.append(
        {
            "elapsed_seconds": float(final_time),
            "cost": float(sealed_cost),
            "source": "sealed_final_solution",
        }
    )
    scored.sort(key=lambda row: row["elapsed_seconds"])
    curve: list[dict[str, Any]] = []
    best = math.inf
    for row in scored:
        if float(row["cost"]) < best - EPS:
            best = float(row["cost"])
            curve.append(row)
    return curve, {
        "snapshot_count": len(snapshots),
        "valid_scored_count": len(scored) - 2,
        "infeasible_count": infeasible,
        "error_count": errors,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    registration = select_registration()
    instance_id = str(registration["representative_instance_id"])
    selected = {
        str(key): int(value)
        for key, value in registration["selected_seed_by_arm"].items()
    }
    bundle = load_china81_bundle(REPO, instance_id)
    initial = load_initial(instance_id)
    initial_completion = complete_china81_route_skeleton(initial, bundle)
    sealed = sealed_costs()
    needed = {
        (VIEW_BY_ARM[arm], selected[arm])
        for arm in ARMS[:-1]
    }
    needed.update(
        (mode, selected["MV-HGS-SP"]) for mode in VIEW_ORDER
    )
    observed: dict[tuple[str, int], ObservedEpoch] = {}
    for mode, seed in sorted(needed):
        result = run_observed_epoch(bundle, initial, mode, seed)
        if result.epoch.stats["wallclock_safety_triggered"]:
            raise RuntimeError(f"trajectory safety triggered: {mode}/seed{seed}")
        observed[(mode, seed)] = result
        print(
            f"[D6-S3-TRAJ] observed {mode} seed={seed} "
            f"snapshots={len(result.snapshots)}",
            flush=True,
        )

    raw_rows: list[dict[str, Any]] = []
    curve_rows: list[dict[str, Any]] = []
    for arm in ARMS[:-1]:
        seed = selected[arm]
        mode = VIEW_BY_ARM[arm]
        result = observed[(mode, seed)]
        rerun_best = min(
            (
                *result.epoch.elite_completions,
                result.epoch.proxy_best_completion,
            ),
            key=lambda item: item.objective,
        )
        sealed_cost = sealed[(arm, seed)]
        exact_equal = math.isclose(
            float(rerun_best.objective),
            sealed_cost,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        )
        if not exact_equal:
            raise RuntimeError(
                f"trajectory rerun mismatch: {arm}/seed{seed}: "
                f"{rerun_best.objective} != {sealed_cost}"
            )
        curve, audit = offline_points(
            list(result.snapshots),
            bundle,
            float(initial_completion.objective),
            result.epoch.elapsed_seconds,
            sealed_cost,
        )
        for order, point in enumerate(curve):
            curve_rows.append(
                {
                    "algorithm": arm,
                    "selected_seed": seed,
                    "point_order": order,
                    "elapsed_seconds": point["elapsed_seconds"],
                    "elapsed_minutes": point["elapsed_seconds"] / 60.0,
                    "cost_cny": point["cost"],
                    "source": point["source"],
                }
            )
        raw_rows.append(
            {
                "algorithm": arm,
                "selected_seed": seed,
                "sealed_final_cost": sealed_cost,
                "rerun_final_cost": rerun_best.objective,
                "final_cost_equal": exact_equal,
                "hgs_iterations": result.epoch.stats["hgs_iterations"],
                "curve_point_count": len(curve),
                "offline_snapshot_count": audit["snapshot_count"],
                "offline_valid_count": audit["valid_scored_count"],
                "offline_infeasible_count": audit["infeasible_count"],
                "offline_error_count": audit["error_count"],
            }
        )

    fusion_seed = selected["MV-HGS-SP"]
    offset = 0.0
    fusion_snapshots: list[dict[str, Any]] = []
    view_epochs: dict[str, HgsExactEpoch] = {}
    for mode in VIEW_ORDER:
        item = observed[(mode, fusion_seed)]
        view_epochs[mode] = item.epoch
        fusion_snapshots.extend(
            {
                **snapshot,
                "elapsed_seconds": (
                    float(snapshot["elapsed_seconds"]) + offset
                ),
                "source": f"{mode}:{snapshot['source']}",
            }
            for snapshot in item.snapshots
        )
        offset += float(item.epoch.elapsed_seconds)
    parents = [
        completion
        for epoch in view_epochs.values()
        for completion in epoch.elite_completions
    ]
    parent = min(parents, key=lambda item: item.objective)
    pool = _route_pool_records(bundle, view_epochs)
    mip_started = perf_counter()
    recombined, mip = _solve_set_partitioning(
        bundle,
        pool,
        time_limit_seconds=MIP_SECONDS,
    )
    mip_elapsed = perf_counter() - mip_started
    if recombined is None:
        final = complete_china81_route_skeleton(
            parent.solution,
            bundle,
        )
    else:
        recombined_completion = complete_china81_route_skeleton(
            recombined,
            bundle,
        )
        final = min(
            (parent, recombined_completion),
            key=lambda item: item.objective,
        )
    fusion_elapsed = offset + mip_elapsed
    fusion_sealed = sealed[("MV-HGS-SP", fusion_seed)]
    fusion_equal = math.isclose(
        float(final.objective),
        fusion_sealed,
        rel_tol=0.0,
        abs_tol=1.0e-9,
    )
    if not fusion_equal:
        raise RuntimeError(
            f"fusion trajectory rerun mismatch: {final.objective} "
            f"!= {fusion_sealed}"
        )
    fusion_curve, fusion_audit = offline_points(
        fusion_snapshots,
        bundle,
        float(initial_completion.objective),
        fusion_elapsed,
        fusion_sealed,
    )
    for order, point in enumerate(fusion_curve):
        curve_rows.append(
            {
                "algorithm": "MV-HGS-SP",
                "selected_seed": fusion_seed,
                "point_order": order,
                "elapsed_seconds": point["elapsed_seconds"],
                "elapsed_minutes": point["elapsed_seconds"] / 60.0,
                "cost_cny": point["cost"],
                "source": point["source"],
            }
        )
    raw_rows.append(
        {
            "algorithm": "MV-HGS-SP",
            "selected_seed": fusion_seed,
            "sealed_final_cost": fusion_sealed,
            "rerun_final_cost": final.objective,
            "final_cost_equal": fusion_equal,
            "hgs_iterations": sum(
                int(epoch.stats["hgs_iterations"])
                for epoch in view_epochs.values()
            ),
            "curve_point_count": len(fusion_curve),
            "offline_snapshot_count": fusion_audit["snapshot_count"],
            "offline_valid_count": fusion_audit["valid_scored_count"],
            "offline_infeasible_count": fusion_audit["infeasible_count"],
            "offline_error_count": fusion_audit["error_count"],
        }
    )
    write_csv(OUT / "raw_runs.csv", raw_rows)
    write_csv(OUT / "curve_data.csv", curve_rows)
    decision = {
        "schema": "resetp.d6-corrected-s3-trajectories.decision.v1",
        "verdict": "PASS_D6_CORRECTED_S3_TRAJECTORIES",
        "representative_instance_id": instance_id,
        "selected_seed_by_arm": selected,
        "observation_only": True,
        "all_final_costs_equal": all(
            bool(row["final_cost_equal"]) for row in raw_rows
        ),
        "curve_definition": (
            "monotone running minimum of complete-model scores obtained by "
            "offline completion of copy-only HGS proxy-best snapshots"
        ),
        "official_score_definition": (
            "sealed final exact-elite/MIP output in corrected S3; trajectory "
            "observations never replace table scores"
        ),
        "shape_based_selection": False,
        "algorithm_or_score_changed": False,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.d6-corrected-s3-trajectories.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    S3 / "raw_runs.csv",
                    S3 / "decision.json",
                    PROTOTYPE / "epochal_hgs.py",
                    PROTOTYPE / "pyvrp_adapter.py",
                    PROTOTYPE / "route_pool_sp.py",
                    Path(__file__).resolve(),
                )
            },
            "max_hgs_iterations_per_view": MAX_HGS_ITERATIONS,
            "archive_candidates_per_view": MAX_ARCHIVE,
            "exact_elites_per_view": EXACT_ELITES,
            "mip_time_limit_seconds": MIP_SECONDS,
        },
    )
    (OUT / "report.md").write_text(
        "# D6 corrected S3 observation-only trajectories\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        "Each displayed seed was registered by distance to the algorithm's "
        "ten-seed mean cost before observing its curve. The hook copied only "
        "route skeletons and timestamps. Offline full-model scoring occurred "
        "after search. Every rerun final cost equals the sealed corrected S3 "
        "cost exactly within 1e-9. Curve observations do not replace official "
        "table scores.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
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
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
