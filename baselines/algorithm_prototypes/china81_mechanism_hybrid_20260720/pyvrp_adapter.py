"""Neutral PyVRP route-skeleton adapter for China81.

PyVRP decides customer grouping and order using the frozen CV road profile and
a static half-payload cost proxy.  The resulting skeleton is always sent to
``complete_china81_route_skeleton`` for the real CV/EV, nonlinear charging,
time-varying electricity/carbon, and project feasibility calculation.

The repository carries two intentionally separate PyVRP engines: 0.12.2 uses
the published HGS population framework, whereas 0.13.4 uses iterated local
search.  This adapter supports both and records the actual engine identity.
It must never call 0.13.4 "HGS".
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
import inspect
import math
from time import perf_counter
from typing import Any

import pyvrp
from pyvrp import Model
from pyvrp import Route as PyVRPRoute
from pyvrp import Solution as PyVRPSolution
from pyvrp.stop import MaxRuntime

from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    complete_china81_route_skeleton,
)
from setp_solver.cost import (
    cv_instance_arc_fuel_liters,
    diesel_price_for_route,
    ev_instance_arc_energy_kwh,
    time_profile_rows_for_node,
)
from setp_solver.solution import Route, Solution


COST_SCALE = 1_000
ROUTE_PROXY_MODES = frozenset(
    {"cv_only", "naive_ev", "mechanism_ev"}
)


@dataclass(frozen=True)
class China81PyVRPProblem:
    model: Model
    node_id_by_location: dict[int, str]
    location_by_node_id: dict[str, int]
    cv_vehicle_type_by_depot: dict[str, int]
    vehicle_type_by_depot_and_route_type: dict[
        tuple[str, str],
        int,
    ]
    route_type_by_vehicle_type: dict[int, str]
    cv_proxy_load_kg: float
    ev_proxy_load_kg: float
    route_proxy_mode: str
    hard_home_depot_lock: bool


@dataclass(frozen=True)
class PyVRPSkeletonRun:
    skeleton: Solution
    completion: China81CompletionResult
    elapsed_seconds: float
    pyvrp_objective: int | None
    pyvrp_feasible: bool
    stats: dict[str, Any]


@dataclass(frozen=True)
class PyVRPPopulationArchiveRun:
    skeleton: Solution
    completion: China81CompletionResult
    elapsed_seconds: float
    proxy_best: PyVRPSkeletonRun
    archive_exact_objectives: tuple[float, ...]
    stats: dict[str, Any]


def build_pyvrp_problem(
    bundle: China81Bundle,
    *,
    route_proxy_mode: str = "mechanism_ev",
    hard_home_depot_lock: bool = False,
) -> China81PyVRPProblem:
    """Build the common CV route-skeleton problem with explicit scaling."""

    normalized_mode = str(route_proxy_mode).strip().lower()
    if normalized_mode not in ROUTE_PROXY_MODES:
        raise ValueError(
            f"unsupported China81 route proxy mode {route_proxy_mode!r}"
        )
    include_ev = normalized_mode != "cv_only"
    instance = bundle.instance
    depots = [
        node
        for node in instance.nodes
        if node.node_type.lower() == "d"
    ]
    customers = [
        node
        for node in instance.nodes
        if node.node_type.lower() == "c"
    ]
    if not depots or not customers:
        raise ValueError("China81 PyVRP adapter requires depots and customers")
    depot_dimension = {
        depot.node_id: index
        for index, depot in enumerate(depots)
    }
    cv_vehicle = instance.vehicle_profile("cv")
    ev_vehicle = instance.vehicle_profile("ev")
    cv_proxy_load = 0.5 * float(cv_vehicle.payload_capacity_kg)
    ev_proxy_load = 0.5 * float(ev_vehicle.payload_capacity_kg)

    model = Model()
    location_object: dict[str, Any] = {}
    node_id_by_location: dict[int, str] = {}
    location_by_node_id: dict[str, int] = {}
    location_index = 0
    for node in depots:
        depot_kwargs = {
            "tw_early": round(node.ready_time),
            "tw_late": round(node.due_time),
            "name": node.node_id,
        }
        if "service_duration" in inspect.signature(
            model.add_depot
        ).parameters:
            depot_kwargs["service_duration"] = round(node.service_time)
        location_object[node.node_id] = model.add_depot(
            node.x,
            node.y,
            **depot_kwargs,
        )
        node_id_by_location[location_index] = node.node_id
        location_by_node_id[node.node_id] = location_index
        location_index += 1
    for node in customers:
        if hard_home_depot_lock:
            owner = bundle.customer_home_depot.get(node.node_id)
            if owner not in depot_dimension:
                raise ValueError(
                    f"China81 customer {node.node_id!r} has no valid "
                    "home-depot lock"
                )
            ownership_delivery = [
                1 if depot.node_id == owner else 0
                for depot in depots
            ]
            delivery: int | list[int] = [
                round(node.demand),
                *ownership_delivery,
            ]
        else:
            delivery = round(node.demand)
        location_object[node.node_id] = model.add_client(
            node.x,
            node.y,
            delivery=delivery,
            service_duration=round(node.service_time),
            tw_early=round(node.ready_time),
            tw_late=round(node.due_time),
            name=node.node_id,
        )
        node_id_by_location[location_index] = node.node_id
        location_by_node_id[node.node_id] = location_index
        location_index += 1

    cv_road_profiles = {
        depot.node_id: model.add_profile(
            name=f"china81-cv-profile@{depot.node_id}"
        )
        for depot in depots
    }
    ev_road_profiles = (
        {
            depot.node_id: model.add_profile(
                name=f"china81-ev-profile@{depot.node_id}"
            )
            for depot in depots
        }
        if include_ev
        else {}
    )
    ordered_nodes = [*depots, *customers]
    for left in ordered_nodes:
        for right in ordered_nodes:
            if left.node_id == right.node_id:
                continue
            _, duration_s, _ = instance.arc_metrics(
                left.node_id,
                right.node_id,
                "cv",
                fallback_speed_mps=float(bundle.prices.v_speed_ms),
            )
            for depot in depots:
                model.add_edge(
                    location_object[left.node_id],
                    location_object[right.node_id],
                    distance=_proxy_arc_cost(
                        bundle,
                        left.node_id,
                        right.node_id,
                        cv_proxy_load,
                        vehicle_type="cv",
                        fueling_depot_id=depot.node_id,
                    ),
                    duration=max(0, round(duration_s)),
                    profile=cv_road_profiles[depot.node_id],
                )
            for depot in depots if include_ev else []:
                _, ev_duration_s, _ = instance.arc_metrics(
                    left.node_id,
                    right.node_id,
                    "ev",
                    fallback_speed_mps=float(bundle.prices.v_speed_ms),
                )
                model.add_edge(
                    location_object[left.node_id],
                    location_object[right.node_id],
                    distance=_proxy_arc_cost(
                        bundle,
                        left.node_id,
                        right.node_id,
                        ev_proxy_load,
                        vehicle_type="ev",
                        charging_depot_id=depot.node_id,
                        time_varying=normalized_mode == "mechanism_ev",
                    ),
                    duration=max(0, round(ev_duration_s)),
                    profile=ev_road_profiles[depot.node_id],
                )

    cv_vehicle_type_by_depot: dict[str, int] = {}
    vehicle_type_by_depot_and_route_type: dict[
        tuple[str, str],
        int,
    ] = {}
    route_type_by_vehicle_type: dict[int, str] = {}
    vehicle_type_index = 0
    unit_duration_cost = round(
        float(bundle.prices.route_time_cost_per_hour)
        * COST_SCALE
        / 3600.0
    )
    for depot in depots:
        depot_caps = bundle.fleet_caps_by_depot.get(depot.node_id)
        if depot_caps is None:
            raise ValueError(
                f"China81 finite fleet has no depot {depot.node_id!r}"
            )
        cv_available = int(depot_caps["num_cv"])
        ev_available = int(depot_caps["num_ev"])
        if cv_available < 1 or ev_available < 1:
            raise ValueError(
                f"China81 finite fleet has invalid caps at "
                f"{depot.node_id!r}"
            )
        model.add_vehicle_type(
            num_available=cv_available,
            capacity=(
                [
                    round(cv_vehicle.payload_capacity_kg),
                    *[
                        len(customers)
                        if item.node_id == depot.node_id
                        else 0
                        for item in depots
                    ],
                ]
                if hard_home_depot_lock
                else round(cv_vehicle.payload_capacity_kg)
            ),
            start_depot=location_object[depot.node_id],
            end_depot=location_object[depot.node_id],
            fixed_cost=round(
                float(bundle.prices.vehicle_fixed_cost) * COST_SCALE
            ),
            tw_early=round(depot.ready_time),
            tw_late=round(depot.due_time),
            unit_distance_cost=1,
            unit_duration_cost=unit_duration_cost,
            profile=cv_road_profiles[depot.node_id],
            name=f"CV@{depot.node_id}",
        )
        cv_vehicle_type_by_depot[depot.node_id] = vehicle_type_index
        vehicle_type_by_depot_and_route_type[
            (depot.node_id, "cv")
        ] = vehicle_type_index
        route_type_by_vehicle_type[vehicle_type_index] = "cv"
        vehicle_type_index += 1
        if include_ev:
            model.add_vehicle_type(
                num_available=ev_available,
                capacity=(
                    [
                        round(ev_vehicle.payload_capacity_kg),
                        *[
                            len(customers)
                            if item.node_id == depot.node_id
                            else 0
                            for item in depots
                        ],
                    ]
                    if hard_home_depot_lock
                    else round(ev_vehicle.payload_capacity_kg)
                ),
                start_depot=location_object[depot.node_id],
                end_depot=location_object[depot.node_id],
                fixed_cost=round(
                    float(bundle.prices.vehicle_fixed_cost) * COST_SCALE
                ),
                tw_early=round(depot.ready_time),
                tw_late=round(depot.due_time),
                unit_distance_cost=1,
                unit_duration_cost=unit_duration_cost,
                profile=ev_road_profiles[depot.node_id],
                name=f"EV@{depot.node_id}",
            )
            vehicle_type_by_depot_and_route_type[
                (depot.node_id, "ev")
            ] = vehicle_type_index
            route_type_by_vehicle_type[vehicle_type_index] = "ev"
            vehicle_type_index += 1

    return China81PyVRPProblem(
        model=model,
        node_id_by_location=node_id_by_location,
        location_by_node_id=location_by_node_id,
        cv_vehicle_type_by_depot=cv_vehicle_type_by_depot,
        vehicle_type_by_depot_and_route_type=(
            vehicle_type_by_depot_and_route_type
        ),
        route_type_by_vehicle_type=route_type_by_vehicle_type,
        cv_proxy_load_kg=cv_proxy_load,
        ev_proxy_load_kg=ev_proxy_load,
        route_proxy_mode=normalized_mode,
        hard_home_depot_lock=bool(hard_home_depot_lock),
    )


def run_pyvrp_hgs_skeleton(
    bundle: China81Bundle,
    initial_skeleton: Solution,
    *,
    seed: int,
    runtime_seconds: float,
    route_proxy_mode: str = "mechanism_ev",
) -> PyVRPSkeletonRun:
    """Run the installed PyVRP engine and apply the shared completion.

    The historical function name is retained for compatibility with frozen
    prototype scripts.  The returned ledger, rather than this name, is the
    authority on whether the active interpreter provides HGS or ILS.
    """

    if runtime_seconds <= 0.0:
        raise ValueError("runtime_seconds must be positive")
    started = perf_counter()
    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode=route_proxy_mode,
    )
    data = problem.model.data()
    initial = _project_initial_solution(
        initial_skeleton,
        data,
        problem,
    )
    solve_kwargs: dict[str, Any] = {
        "seed": int(seed),
        "display": False,
        "collect_stats": True,
    }
    if "initial_solution" in inspect.signature(
        problem.model.solve
    ).parameters:
        solve_kwargs["initial_solution"] = initial
    result = problem.model.solve(
        MaxRuntime(float(runtime_seconds)),
        **solve_kwargs,
    )
    initial_completion = complete_china81_route_skeleton(
        initial_skeleton,
        bundle,
    )
    searched_skeleton = _translate_solution(result.best, problem)
    searched_completion_failure: str | None = None
    try:
        searched_completion = complete_china81_route_skeleton(
            searched_skeleton,
            bundle,
        )
    except (IndexError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        searched_completion_failure = str(exc)
        searched_completion = None
    if (
        searched_completion is not None
        and searched_completion.objective
        < initial_completion.objective - 1.0e-9
    ):
        selected_source = "pyvrp_search"
        skeleton = searched_skeleton
        completion = searched_completion
    else:
        selected_source = "common_initial_incumbent"
        skeleton = initial_skeleton
        completion = initial_completion
    engine_family = (
        "HGS"
        if hasattr(pyvrp, "GeneticAlgorithm")
        else "ILS"
    )
    pyvrp_version = version("pyvrp")
    raw_pyvrp_objective = float(result.cost())
    pyvrp_objective = (
        int(raw_pyvrp_objective)
        if math.isfinite(raw_pyvrp_objective)
        else None
    )
    return PyVRPSkeletonRun(
        skeleton=skeleton,
        completion=completion,
        elapsed_seconds=perf_counter() - started,
        pyvrp_objective=pyvrp_objective,
        pyvrp_feasible=bool(result.best.is_feasible()),
        stats={
            "algorithm": (
                f"PyVRP-{pyvrp_version}-{engine_family}"
                "-with-mechanism-route-proxy"
                if problem.route_proxy_mode == "mechanism_ev"
                else (
                    f"PyVRP-{pyvrp_version}-{engine_family}"
                    "-with-naive-EV-proxy"
                    if problem.route_proxy_mode == "naive_ev"
                    else (
                        f"PyVRP-{pyvrp_version}-{engine_family}"
                        "-neutral-China81-adapter"
                    )
                )
            ),
            "pyvrp_version": pyvrp_version,
            "engine_family": engine_family,
            "warm_start_supported": (
                "initial_solution"
                in inspect.signature(problem.model.solve).parameters
            ),
            "seed": int(seed),
            "runtime_seconds": float(runtime_seconds),
            "cost_scale": COST_SCALE,
            "cv_proxy_load_kg": problem.cv_proxy_load_kg,
            "ev_proxy_load_kg": problem.ev_proxy_load_kg,
            "route_proxy_mode": problem.route_proxy_mode,
            "pyvrp_objective_finite": (
                pyvrp_objective is not None
            ),
            "route_count": len(skeleton.routes),
            "searched_route_count": len(searched_skeleton.routes),
            "searched_ev_skeleton_route_count": sum(
                route.vehicle_type.lower() == "ev"
                for route in searched_skeleton.routes
            ),
            "searched_complete_model_status": (
                "PASS"
                if searched_completion is not None
                else "INFEASIBLE_OR_ERROR"
            ),
            "searched_complete_model_failure": (
                searched_completion_failure
            ),
            "searched_exact_objective": (
                None
                if searched_completion is None
                else float(searched_completion.objective)
            ),
            "initial_exact_objective": float(
                initial_completion.objective
            ),
            "selected_source": selected_source,
            "shared_completion_schema": completion.activity[
                "schema_version"
            ],
        },
    )


def run_pyvrp_hgs_population_archive(
    bundle: China81Bundle,
    initial_skeleton: Solution,
    *,
    seed: int,
    runtime_seconds: float,
    route_proxy_mode: str = "mechanism_ev",
    max_archive_candidates: int = 24,
) -> PyVRPPopulationArchiveRun:
    """Run genuine HGS and re-rank its feasible population exactly.

    PyVRP's published HGS keeps a diverse feasible/infeasible population, but
    its standard ``Result`` exposes only the best solution under the proxy
    objective.  This function uses the same public HGS components as PyVRP's
    official ``solve`` orchestration, retains the final population, and sends
    its best proxy candidates through the shared full ReSETP completion.

    This is intentionally unavailable under PyVRP 0.13.4 ILS.
    """

    if runtime_seconds <= 0.0:
        raise ValueError("runtime_seconds must be positive")
    if max_archive_candidates < 1:
        raise ValueError("max_archive_candidates must be positive")
    if not hasattr(pyvrp, "GeneticAlgorithm"):
        raise RuntimeError(
            "population archive requires the PyVRP 0.12.2 HGS environment"
        )

    from pyvrp.GeneticAlgorithm import GeneticAlgorithm
    from pyvrp.PenaltyManager import PenaltyManager
    from pyvrp.Population import Population
    from pyvrp._pyvrp import RandomNumberGenerator
    from pyvrp._pyvrp import Solution as NativeSolution
    from pyvrp.crossover import ordered_crossover
    from pyvrp.crossover import selective_route_exchange
    from pyvrp.diversity import broken_pairs_distance
    from pyvrp.search import LocalSearch, compute_neighbours
    from pyvrp.solve import SolveParams

    started = perf_counter()
    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode=route_proxy_mode,
    )
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
    initial_solutions = [
        NativeSolution.make_random(data, rng)
        for _ in range(params.population.min_pop_size)
    ]
    crossover = (
        selective_route_exchange
        if data.num_vehicles > 1
        else ordered_crossover
    )
    algorithm = GeneticAlgorithm(
        data,
        penalty_manager,
        rng,
        population,
        local_search,
        crossover,
        initial_solutions,
        params.genetic,
    )
    result = algorithm.run(
        MaxRuntime(float(runtime_seconds)),
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    cost_evaluator = penalty_manager.cost_evaluator()
    feasible = [item for item in population if item.is_feasible()]
    feasible.append(result.best)
    unique: dict[tuple[Any, ...], Any] = {}
    for item in feasible:
        unique.setdefault(_native_solution_key(item), item)
    proxy_ranked = sorted(
        unique.values(),
        key=cost_evaluator.cost,
    )[: int(max_archive_candidates)]

    exact_candidates: list[
        tuple[Solution, China81CompletionResult, int]
    ] = []
    failures: list[str] = []
    for native in proxy_ranked:
        try:
            skeleton = _translate_solution(native, problem)
            completion = complete_china81_route_skeleton(
                skeleton,
                bundle,
            )
            exact_candidates.append(
                (
                    skeleton,
                    completion,
                    int(cost_evaluator.cost(native)),
                )
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            failures.append(str(exc))
    initial_completion = complete_china81_route_skeleton(
        initial_skeleton,
        bundle,
    )
    if exact_candidates:
        archive_skeleton, archive_completion, archive_proxy = min(
            exact_candidates,
            key=lambda item: item[1].objective,
        )
    else:
        archive_skeleton = initial_skeleton
        archive_completion = initial_completion
        archive_proxy = -1
    proxy_best_skeleton = _translate_solution(result.best, problem)
    proxy_best_completion = complete_china81_route_skeleton(
        proxy_best_skeleton,
        bundle,
    )
    if archive_completion.objective < initial_completion.objective - 1.0e-9:
        selected_source = "exact_population_archive"
        skeleton = archive_skeleton
        completion = archive_completion
    else:
        selected_source = "common_initial_incumbent"
        skeleton = initial_skeleton
        completion = initial_completion
    proxy_best = PyVRPSkeletonRun(
        skeleton=proxy_best_skeleton,
        completion=proxy_best_completion,
        elapsed_seconds=float(result.runtime),
        pyvrp_objective=int(result.cost()),
        pyvrp_feasible=bool(result.best.is_feasible()),
        stats={
            "algorithm": (
                f"PyVRP-{version('pyvrp')}-HGS-proxy-best"
            ),
            "pyvrp_version": version("pyvrp"),
            "engine_family": "HGS",
            "seed": int(seed),
            "runtime_seconds": float(runtime_seconds),
            "route_proxy_mode": problem.route_proxy_mode,
        },
    )
    return PyVRPPopulationArchiveRun(
        skeleton=skeleton,
        completion=completion,
        elapsed_seconds=perf_counter() - started,
        proxy_best=proxy_best,
        archive_exact_objectives=tuple(
            float(item[1].objective)
            for item in exact_candidates
        ),
        stats={
            "algorithm": (
                "PyVRP-HGS-exact-ReSETP-population-archive"
            ),
            "pyvrp_version": version("pyvrp"),
            "engine_family": "HGS",
            "seed": int(seed),
            "runtime_seconds": float(runtime_seconds),
            "route_proxy_mode": problem.route_proxy_mode,
            "population_size": len(population),
            "feasible_population_size": len(feasible),
            "unique_feasible_population_size": len(unique),
            "archive_candidate_limit": int(max_archive_candidates),
            "archive_candidates_completed": len(exact_candidates),
            "archive_completion_failures": failures,
            "proxy_best_proxy_objective": int(result.cost()),
            "proxy_best_exact_objective": float(
                proxy_best_completion.objective
            ),
            "archive_best_proxy_objective": archive_proxy,
            "archive_best_exact_objective": float(
                archive_completion.objective
            ),
            "archive_improvement_over_proxy_best": float(
                proxy_best_completion.objective
                - archive_completion.objective
            ),
            "selected_source": selected_source,
            "final_objective": float(completion.objective),
            "hgs_iterations": int(result.num_iterations),
        },
    )


def _native_solution_key(solution: Any) -> tuple[Any, ...]:
    return tuple(
        sorted(
            (
                int(route.vehicle_type()),
                tuple(int(client) for client in route),
            )
            for route in solution.routes()
        )
    )


def _proxy_arc_cost(
    bundle: China81Bundle,
    left: str,
    right: str,
    load_kg: float,
    *,
    vehicle_type: str,
    fueling_depot_id: str | None = None,
    charging_depot_id: str | None = None,
    time_varying: bool = True,
) -> int:
    instance = bundle.instance
    prices = bundle.prices
    normalized_type = str(vehicle_type).lower()
    distance_m, _, _ = instance.arc_metrics(
        left,
        right,
        normalized_type,
        fallback_speed_mps=float(prices.v_speed_ms),
    )
    distance_cost = (
        distance_m / 1_000.0
        * instance.non_energy_distance_cost_per_km(
            normalized_type,
            fallback=float(prices.c_km),
        )
    )
    if normalized_type == "cv":
        if fueling_depot_id is None:
            raise ValueError("CV proxy requires a fueling depot")
        fuel_liters = cv_instance_arc_fuel_liters(
            instance,
            left,
            right,
            load_kg,
            prices,
        )
        energy_cost = (
            fuel_liters
            * diesel_price_for_route(
                Route(
                    vehicle_id="CV-PROXY",
                    vehicle_type="cv",
                    home_depot_id=fueling_depot_id,
                    node_sequence=[
                        fueling_depot_id,
                        fueling_depot_id,
                    ],
                ),
                instance,
                prices,
            )
            + fuel_liters
            * float(prices.diesel_ef)
            * float(prices.carbon_price)
        )
    elif normalized_type == "ev":
        if charging_depot_id is None:
            raise ValueError("EV proxy requires a charging depot")
        energy_kwh = ev_instance_arc_energy_kwh(
            instance,
            left,
            right,
            load_kg,
            prices,
        )
        if time_varying:
            rows = time_profile_rows_for_node(
                instance,
                charging_depot_id,
                bundle.time_profile,
            )
            unit_energy_cost = min(
                float(row["depot_energy_cny_per_kwh"])
                + float(row["actual_gco2_per_kwh"])
                / 1_000.0
                * float(prices.carbon_price)
                for row in rows
            )
        else:
            unit_energy_cost = float(prices.depot_electricity_price)
        energy_cost = energy_kwh * unit_energy_cost
    else:
        raise ValueError(f"unsupported vehicle type {vehicle_type!r}")
    monetary_cost = distance_cost + energy_cost
    return max(1, round(monetary_cost * COST_SCALE))


def _project_initial_solution(
    initial_skeleton: Solution,
    data: Any,
    problem: China81PyVRPProblem,
) -> PyVRPSolution:
    routes: list[PyVRPRoute] = []
    for route in initial_skeleton.routes:
        route_type = str(route.vehicle_type).strip().lower()
        if problem.route_proxy_mode == "cv_only":
            route_type = "cv"
        vehicle_type = (
            problem.vehicle_type_by_depot_and_route_type.get(
                (route.home_depot_id, route_type)
            )
        )
        if vehicle_type is None:
            raise ValueError(
                "no PyVRP vehicle type for warm-start route "
                f"{route.vehicle_id!r}: depot={route.home_depot_id!r}, "
                f"route_type={route_type!r}, "
                f"proxy_mode={problem.route_proxy_mode!r}"
            )
        visits = [
            problem.location_by_node_id[node_id]
            for node_id in route.node_sequence
            if node_id in problem.location_by_node_id
            and node_id != route.home_depot_id
        ]
        if not visits:
            continue
        routes.append(
            PyVRPRoute(
                data,
                visits,
                vehicle_type,
            )
        )
    return PyVRPSolution(data, routes)


def _translate_solution(
    solution: PyVRPSolution,
    problem: China81PyVRPProblem,
) -> Solution:
    routes: list[Route] = []
    for route_index, pyvrp_route in enumerate(solution.routes()):
        home_depot_id = problem.node_id_by_location[
            int(pyvrp_route.start_depot())
        ]
        customers = [
            problem.node_id_by_location[int(location)]
            for location in pyvrp_route.visits()
        ]
        routes.append(
            Route(
                vehicle_id=f"PYVRP-{route_index + 1:04d}",
                vehicle_type=problem.route_type_by_vehicle_type[
                    int(pyvrp_route.vehicle_type())
                ],
                home_depot_id=home_depot_id,
                node_sequence=[
                    home_depot_id,
                    *customers,
                    home_depot_id,
                ],
            )
        )
    return Solution(routes=routes)
