"""Staged China81 population-search, ALNS, VNS, and mechanism hybrid."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from pyvrp_adapter import PyVRPSkeletonRun, run_pyvrp_hgs_skeleton
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    FLEET_CHARGE_COREPAIR_FLAG,
    WinnerKernelConfig,
    e2_alns_throughput_flags,
    run_winner_kernel_in_memory,
)
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    complete_china81_route_skeleton,
)
from setp_solver.solution import Solution


@dataclass(frozen=True)
class China81AlnsRun:
    raw_solution: Solution
    completion: China81CompletionResult
    elapsed_seconds: float
    evaluations: int
    history: tuple[dict[str, Any], ...]
    operator_counts: dict[str, Any]
    mechanism_mode: bool


@dataclass(frozen=True)
class China81HybridRun:
    solution: Solution
    completion: China81CompletionResult
    elapsed_seconds: float
    hgs_stage: PyVRPSkeletonRun
    alns_stage: China81AlnsRun
    selected_stage: str
    stats: dict[str, Any]


@dataclass(frozen=True)
class China81MultiViewHybridRun:
    solution: Solution
    completion: China81CompletionResult
    elapsed_seconds: float
    view_runs: dict[str, PyVRPSkeletonRun]
    alns_stage: China81AlnsRun
    selected_view: str
    selected_stage: str
    stats: dict[str, Any]


@dataclass(frozen=True)
class China81HomogeneousEnsembleRun:
    solution: Solution
    completion: China81CompletionResult
    elapsed_seconds: float
    population_runs: tuple[PyVRPSkeletonRun, ...]
    alns_stage: China81AlnsRun
    route_proxy_mode: str
    stats: dict[str, Any]


@dataclass(frozen=True)
class China81AdaptiveMultiViewRun:
    solution: Solution
    completion: China81CompletionResult
    elapsed_seconds: float
    scout_runs: dict[str, PyVRPSkeletonRun]
    exploitation_runs: tuple[PyVRPSkeletonRun, ...]
    alns_stage: China81AlnsRun
    selected_view: str
    selected_stage: str
    stats: dict[str, Any]


def run_project_alns(
    bundle: China81Bundle,
    initial_solution: Solution,
    *,
    seed: int,
    runtime_seconds: float,
    mechanism_mode: bool,
    eval_budget: int = 1_000_000,
) -> China81AlnsRun:
    """Run the project ALNS with or without its mechanism-specific experts."""

    if runtime_seconds <= 0.0:
        raise ValueError("runtime_seconds must be positive")
    started = perf_counter()
    config = WinnerKernelConfig(
        seed=int(seed),
        eval_budget=int(eval_budget),
        max_runtime_seconds=float(runtime_seconds),
        require_charging_signal=False,
        include_route_elimination=False,
        carbon_aware_operators=bool(mechanism_mode),
        carbon_operator_bias=1.0 if mechanism_mode else 0.0,
        refined_carbon_operators=bool(mechanism_mode),
        refined_carbon_weight=1.0 if mechanism_mode else 0.0,
        include_sisr_string_removal=False,
        capture_best_solutions=False,
        split_selector_rng=True,
    )
    flags = e2_alns_throughput_flags(
        route_cost_cache=True,
        repair_structure_cache=True,
        timing_ledger=False,
    )
    if mechanism_mode:
        flags[FLEET_CHARGE_COREPAIR_FLAG] = "1"
    run = run_winner_kernel_in_memory(
        initial_solution,
        bundle.instance,
        bundle.time_profile,
        config=config,
        prices=bundle.prices,
        variant_flags=flags,
        customer_home_depot=dict(bundle.customer_home_depot),
    )
    completion = complete_china81_route_skeleton(
        run.best_solution,
        bundle,
    )
    return China81AlnsRun(
        raw_solution=run.best_solution,
        completion=completion,
        elapsed_seconds=perf_counter() - started,
        evaluations=int(run.evaluations),
        history=tuple(run.history),
        operator_counts=dict(run.operator_counts),
        mechanism_mode=bool(mechanism_mode),
    )


def run_staged_mechanism_hybrid(
    bundle: China81Bundle,
    common_initial_solution: Solution,
    *,
    seed: int,
    runtime_seconds: float,
    hgs_share: float = 0.70,
) -> China81HybridRun:
    """Run broad population search, then mechanism ALNS intensification.

    PyVRP's HGS population and embedded neighbourhood search first establish a
    strong route skeleton.  The project ALNS then receives that exact completed
    incumbent and spends the remaining time on adaptive destruction/repair and
    mechanism-specific fleet/charging/carbon moves.  The first-stage incumbent
    is retained, so the second stage cannot erase an already better solution.
    """

    if not 0.0 < hgs_share < 1.0:
        raise ValueError("hgs_share must lie strictly between zero and one")
    if runtime_seconds <= 0.0:
        raise ValueError("runtime_seconds must be positive")
    started = perf_counter()
    hgs_runtime = float(runtime_seconds) * float(hgs_share)
    alns_runtime = float(runtime_seconds) - hgs_runtime
    hgs = run_pyvrp_hgs_skeleton(
        bundle,
        common_initial_solution,
        seed=seed,
        runtime_seconds=hgs_runtime,
        route_proxy_mode="mechanism_ev",
    )
    alns = run_project_alns(
        bundle,
        hgs.completion.solution,
        seed=seed,
        runtime_seconds=alns_runtime,
        mechanism_mode=True,
    )
    if alns.completion.objective < hgs.completion.objective - 1.0e-9:
        selected = "mechanism_alns_intensification"
        completion = alns.completion
    else:
        selected = "hgs_population_incumbent"
        completion = hgs.completion
    return China81HybridRun(
        solution=completion.solution,
        completion=completion,
        elapsed_seconds=perf_counter() - started,
        hgs_stage=hgs,
        alns_stage=alns,
        selected_stage=selected,
        stats={
            "algorithm": "PMA-HGS-ALNS-VNS",
            "story": (
                "HGS population exploration -> embedded VNS/SWAP* refinement "
                "-> mechanism-aware ALNS intensification -> shared nonlinear "
                "fleet/charging/carbon completion"
            ),
            "seed": int(seed),
            "runtime_seconds": float(runtime_seconds),
            "hgs_share": float(hgs_share),
            "hgs_search_seconds": hgs_runtime,
            "alns_search_seconds": alns_runtime,
            "selected_stage": selected,
            "hgs_objective": float(hgs.completion.objective),
            "alns_objective": float(alns.completion.objective),
            "final_objective": float(completion.objective),
            "alns_evaluations": int(alns.evaluations),
        },
    )


def run_multiview_mechanism_hybrid(
    bundle: China81Bundle,
    common_initial_solution: Solution,
    *,
    seed: int,
    population_seconds: float,
    alns_seconds: float,
    max_workers: int = 3,
) -> China81MultiViewHybridRun:
    """Run three mechanism views as parallel HGS populations, then ALNS.

    The views deliberately disagree about what route structure should value:
    a conservative CV-only view, a standard heterogeneous-fleet view with one
    flat electricity price, and a ReSETP mechanism view with city/time/carbon
    charging prices.  Their best exact full-model incumbent migrates into the
    mechanism ALNS stage.  The exact arbiter retains every population elite, so
    an aggressive mechanism view cannot erase a safer route plan.
    """

    if population_seconds <= 0.0 or alns_seconds <= 0.0:
        raise ValueError("population and ALNS seconds must be positive")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    started = perf_counter()
    modes = ("cv_only", "naive_ev", "mechanism_ev")

    def run_view(mode: str) -> tuple[str, PyVRPSkeletonRun]:
        return (
            mode,
            run_pyvrp_hgs_skeleton(
                bundle,
                common_initial_solution,
                seed=seed,
                runtime_seconds=population_seconds,
                route_proxy_mode=mode,
            ),
        )

    with ThreadPoolExecutor(
        max_workers=min(int(max_workers), len(modes))
    ) as executor:
        view_runs = dict(executor.map(run_view, modes))
    selected_view, selected_run = min(
        view_runs.items(),
        key=lambda item: (
            item[1].completion.objective,
            modes.index(item[0]),
        ),
    )
    alns = run_project_alns(
        bundle,
        selected_run.completion.solution,
        seed=seed,
        runtime_seconds=alns_seconds,
        mechanism_mode=True,
    )
    if (
        alns.completion.objective
        < selected_run.completion.objective - 1.0e-9
    ):
        selected_stage = "mechanism_alns_intensification"
        completion = alns.completion
    else:
        selected_stage = f"{selected_view}_population_elite"
        completion = selected_run.completion
    elapsed = perf_counter() - started
    return China81MultiViewHybridRun(
        solution=completion.solution,
        completion=completion,
        elapsed_seconds=elapsed,
        view_runs=view_runs,
        alns_stage=alns,
        selected_view=selected_view,
        selected_stage=selected_stage,
        stats={
            "algorithm": "MVHGS-ALNS",
            "algorithm_name_en": (
                "Multi-View Hybrid Genetic Search with Adaptive Large "
                "Neighborhood Intensification"
            ),
            "algorithm_name_zh": (
                "多视角混合遗传搜索—自适应大邻域强化算法"
            ),
            "story": (
                "three independent route-cost views maintain diverse HGS "
                "populations; exact full-model elite migration selects the "
                "best basin; mechanism ALNS performs late intensification; "
                "shared nonlinear completion is the final referee"
            ),
            "seed": int(seed),
            "population_seconds_per_view": float(population_seconds),
            "alns_seconds": float(alns_seconds),
            "worker_count": min(int(max_workers), len(modes)),
            "nominal_wall_search_seconds": (
                float(population_seconds) + float(alns_seconds)
            ),
            "aggregate_cpu_search_seconds_upper_bound": (
                len(modes) * float(population_seconds)
                + float(alns_seconds)
            ),
            "measured_elapsed_seconds": elapsed,
            "view_objectives": {
                mode: float(run.completion.objective)
                for mode, run in view_runs.items()
            },
            "selected_view": selected_view,
            "selected_stage": selected_stage,
            "alns_objective": float(alns.completion.objective),
            "alns_evaluations": int(alns.evaluations),
            "final_objective": float(completion.objective),
        },
    )


def run_homogeneous_hgs_alns_ensemble(
    bundle: China81Bundle,
    common_initial_solution: Solution,
    *,
    base_seed: int,
    route_proxy_mode: str,
    population_seconds: float,
    alns_seconds: float,
    population_count: int = 3,
    max_workers: int = 3,
) -> China81HomogeneousEnsembleRun:
    """Run an equal-compute homogeneous control for the multiview algorithm."""

    if population_count < 1 or max_workers < 1:
        raise ValueError("population_count and max_workers must be positive")
    started = perf_counter()
    seeds = tuple(
        int(base_seed) + 1_009 * index
        for index in range(int(population_count))
    )

    def run_population(seed: int) -> PyVRPSkeletonRun:
        return run_pyvrp_hgs_skeleton(
            bundle,
            common_initial_solution,
            seed=seed,
            runtime_seconds=population_seconds,
            route_proxy_mode=route_proxy_mode,
        )

    with ThreadPoolExecutor(
        max_workers=min(int(max_workers), len(seeds))
    ) as executor:
        population_runs = tuple(executor.map(run_population, seeds))
    best_population = min(
        population_runs,
        key=lambda item: item.completion.objective,
    )
    alns = run_project_alns(
        bundle,
        best_population.completion.solution,
        seed=base_seed,
        runtime_seconds=alns_seconds,
        mechanism_mode=True,
    )
    completion = min(
        (best_population.completion, alns.completion),
        key=lambda item: item.objective,
    )
    elapsed = perf_counter() - started
    return China81HomogeneousEnsembleRun(
        solution=completion.solution,
        completion=completion,
        elapsed_seconds=elapsed,
        population_runs=population_runs,
        alns_stage=alns,
        route_proxy_mode=route_proxy_mode,
        stats={
            "algorithm": (
                f"homogeneous-{route_proxy_mode}-HGS-ALNS-ensemble"
            ),
            "base_seed": int(base_seed),
            "population_seeds": list(seeds),
            "population_count": len(seeds),
            "population_seconds": float(population_seconds),
            "alns_seconds": float(alns_seconds),
            "worker_count": min(int(max_workers), len(seeds)),
            "population_objectives": [
                float(run.completion.objective)
                for run in population_runs
            ],
            "best_population_objective": float(
                best_population.completion.objective
            ),
            "alns_objective": float(alns.completion.objective),
            "final_objective": float(completion.objective),
            "measured_elapsed_seconds": elapsed,
        },
    )


def run_adaptive_multiview_hybrid(
    bundle: China81Bundle,
    common_initial_solution: Solution,
    *,
    base_seed: int,
    population_seconds: float,
    alns_seconds: float,
    scout_share: float = 0.20,
    exploitation_population_count: int = 3,
    max_workers: int = 3,
) -> China81AdaptiveMultiViewRun:
    """Race route-cost views, then migrate compute to the strongest view.

    Phase one gives the three views the same paired random seed and a small
    scouting allowance.  The exact full ReSETP objective chooses the winning
    view, with the conservative CV-only view winning exact ties.  Phase two
    assigns the remaining population budget to independent populations of that
    view.  The best scout or exploitation elite then enters mechanism ALNS.

    The total HGS CPU allowance is exactly
    ``3 * population_seconds`` when the default three exploitation
    populations are used, matching a three-population homogeneous control:
    ``3 * scout_seconds + 3 * exploitation_seconds``.
    """

    if population_seconds <= 0.0 or alns_seconds <= 0.0:
        raise ValueError("population and ALNS seconds must be positive")
    if not 0.0 < scout_share < 1.0:
        raise ValueError("scout_share must lie strictly between zero and one")
    if exploitation_population_count < 1 or max_workers < 1:
        raise ValueError(
            "exploitation_population_count and max_workers must be positive"
        )
    started = perf_counter()
    modes = ("cv_only", "naive_ev", "mechanism_ev")
    scout_seconds = float(population_seconds) * float(scout_share)
    exploitation_seconds = float(population_seconds) - scout_seconds

    def run_scout(mode: str) -> tuple[str, PyVRPSkeletonRun]:
        return (
            mode,
            run_pyvrp_hgs_skeleton(
                bundle,
                common_initial_solution,
                seed=base_seed,
                runtime_seconds=scout_seconds,
                route_proxy_mode=mode,
            ),
        )

    with ThreadPoolExecutor(
        max_workers=min(int(max_workers), len(modes))
    ) as executor:
        scout_runs = dict(executor.map(run_scout, modes))
    selected_view, _ = min(
        scout_runs.items(),
        key=lambda item: (
            item[1].completion.objective,
            modes.index(item[0]),
        ),
    )
    exploitation_seeds = tuple(
        int(base_seed) + 1_009 * (index + 1)
        for index in range(int(exploitation_population_count))
    )

    def run_exploitation(seed: int) -> PyVRPSkeletonRun:
        return run_pyvrp_hgs_skeleton(
            bundle,
            common_initial_solution,
            seed=seed,
            runtime_seconds=exploitation_seconds,
            route_proxy_mode=selected_view,
        )

    with ThreadPoolExecutor(
        max_workers=min(int(max_workers), len(exploitation_seeds))
    ) as executor:
        exploitation_runs = tuple(
            executor.map(run_exploitation, exploitation_seeds)
        )
    population_elites = (
        *(run.completion for run in scout_runs.values()),
        *(run.completion for run in exploitation_runs),
    )
    best_population = min(
        population_elites,
        key=lambda item: item.objective,
    )
    alns = run_project_alns(
        bundle,
        best_population.solution,
        seed=base_seed,
        runtime_seconds=alns_seconds,
        mechanism_mode=True,
    )
    if alns.completion.objective < best_population.objective - 1.0e-9:
        selected_stage = "mechanism_alns_intensification"
        completion = alns.completion
    else:
        selected_stage = f"{selected_view}_adaptive_population_elite"
        completion = best_population
    elapsed = perf_counter() - started
    return China81AdaptiveMultiViewRun(
        solution=completion.solution,
        completion=completion,
        elapsed_seconds=elapsed,
        scout_runs=scout_runs,
        exploitation_runs=exploitation_runs,
        alns_stage=alns,
        selected_view=selected_view,
        selected_stage=selected_stage,
        stats={
            "algorithm": "AMV-HGS-ALNS",
            "algorithm_name_en": (
                "Adaptive Multi-View Hybrid Genetic Search with Adaptive "
                "Large Neighborhood Intensification"
            ),
            "algorithm_name_zh": (
                "自适应多视角混合遗传搜索—大邻域强化算法"
            ),
            "story": (
                "paired multiview scouts diagnose the instance; exact "
                "full-model feedback reallocates independent HGS populations "
                "to the strongest view; all elites migrate to a common pool; "
                "mechanism ALNS performs final intensification"
            ),
            "base_seed": int(base_seed),
            "scout_seed": int(base_seed),
            "scout_share": float(scout_share),
            "scout_seconds_per_view": scout_seconds,
            "scout_objectives": {
                mode: float(run.completion.objective)
                for mode, run in scout_runs.items()
            },
            "selected_view": selected_view,
            "exploitation_population_seeds": list(exploitation_seeds),
            "exploitation_seconds_per_population": exploitation_seconds,
            "exploitation_objectives": [
                float(run.completion.objective)
                for run in exploitation_runs
            ],
            "hgs_cpu_search_seconds": (
                len(modes) * scout_seconds
                + len(exploitation_runs) * exploitation_seconds
            ),
            "alns_seconds": float(alns_seconds),
            "worker_count": min(
                int(max_workers),
                max(len(modes), len(exploitation_seeds)),
            ),
            "selected_stage": selected_stage,
            "alns_objective": float(alns.completion.objective),
            "alns_evaluations": int(alns.evaluations),
            "final_objective": float(completion.objective),
            "measured_elapsed_seconds": elapsed,
        },
    )
