"""Model-aware multi-depot regret construction for the second initializer.

Unlike the failed order decoder, this constructor evaluates every feasible
insertion position.  Its local route score includes fixed dispatch cost,
load-dependent fuel, carbon, distance, and cross-depot service cost.  A
route-local fleet/charging and carbon-time decoder then completes every start
symmetrically before the one complete candidate score is charged.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
from typing import Any

from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (
    score_reference_solution,
    score_search_candidate,
)
from setp_solver.algorithms.resetp_alns.support.fleet import (
    infer_fleet_limits,
    normalize_solution_vehicle_trips,
)
from setp_solver.check import check_solution
from setp_solver.cost import evaluate, route_node_schedule
from setp_solver.instance_loader import Instance
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import infer_customer_home_depots
from setp_solver.search.bundle import SearchBundle, load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import CrossSiteService, Route, Solution
from v5_carbon_retiming_solver import carbon_aware_depot_retime
from v6_monotone_mechanism_solver import exact_joint_fleet_charge_decode
from v7_responsibility_solver import annotate_cross_site_services

from initial_pool import (
    InitialPoolEntry,
    InitialPoolResult,
    route_structure_hash,
    select_quality_diverse_archive,
    solution_signature_hash,
)


@dataclass(frozen=True)
class RegretConfig:
    label: str
    regret_k: int
    customer_rcl_width: int
    seed_offset: int


@dataclass
class RoutePlan:
    depot_id: str
    customer_ids: list[str]


@dataclass
class ConstructionLedger:
    route_feasibility_checks: int = 0
    route_local_exact_evaluations: int = 0
    insertion_options: int = 0
    selected_cross_depot_customers: int = 0
    joint_route_proxy_evaluations: int = 0
    carbon_schedule_evaluations: int = 0


FROZEN_CONFIGS = (
    RegretConfig("global_regret2", 2, 1, 11_003),
    RegretConfig("global_regret3", 3, 1, 21_011),
    RegretConfig("global_regret2_rcl2", 2, 2, 31_013),
    RegretConfig("global_regret2_rcl3", 2, 3, 41_021),
    RegretConfig("global_regret3_rcl2", 3, 2, 51_031),
)


def build_and_score_mechanism_regret_pool(
    bundle_dir: str | Path,
    *,
    seed: int,
    prices: Any = DEFAULT_PRICES,
    archive_capacity: int = 4,
) -> tuple[InitialPoolResult, dict[str, ConstructionLedger]]:
    """Build one default and five model-aware starts under a K-1 ledger."""

    bundle = load_search_bundle(bundle_dir)
    owners = infer_customer_home_depots(bundle.instance)
    candidates: list[tuple[str, str, str, Solution]] = []
    ledgers: dict[str, ConstructionLedger] = {}

    default = make_shared_initial_solution(bundle, prices=prices)
    default_ledger = ConstructionLedger()
    default = route_local_complete(
        default,
        bundle,
        owners=owners,
        prices=prices,
        ledger=default_ledger,
    )
    candidates.append(("default_regret2", "default", "common_route_local_completion", default))
    ledgers["default_regret2"] = default_ledger

    for config in FROZEN_CONFIGS:
        ledger = ConstructionLedger()
        solution = build_global_regret_solution(
            bundle,
            config=config,
            seed=seed + config.seed_offset,
            prices=prices,
            owners=owners,
            ledger=ledger,
        )
        solution = route_local_complete(
            solution,
            bundle,
            owners=owners,
            prices=prices,
            ledger=ledger,
        )
        candidates.append(
            (
                config.label,
                "model_aware_global_regret",
                "common_route_local_completion",
                solution,
            )
        )
        ledgers[config.label] = ledger

    count = len(candidates)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=count - 1, target=count - 1),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    entries: list[InitialPoolEntry] = []
    for index, (label, family, type_mode, solution) in enumerate(candidates):
        violations = check_solution(solution, bundle.instance, prices)
        if violations:
            raise ValueError(f"{label} is infeasible before complete scoring: {violations[:8]}")
        if index == 0:
            prepared, objective = score_reference_solution(
                solution,
                context,
                phase="mechanism_regret_anchor",
            )
        else:
            prepared, objective = score_search_candidate(
                solution,
                context,
                channel="mechanism_regret_initial_choice",
            )
        breakdown = context.score_breakdowns[id(prepared)]
        entries.append(
            InitialPoolEntry(
                label=label,
                family=family,
                type_mode=type_mode,
                solution=prepared,
                objective=float(objective),
                raw_cost=float(breakdown["raw_cost"]),
                feasible=bool(breakdown["feasible"]),
                violation_count=int(breakdown["violation_count"]),
                full_signature=solution_signature_hash(prepared),
                route_signature=route_structure_hash(prepared, bundle.instance),
            )
        )
    if context.budget is None or context.budget.count != count - 1:
        raise RuntimeError("mechanism-regret K-1 candidate ledger did not close")
    best = min(entries, key=lambda item: (item.objective, item.full_signature))
    archive = select_quality_diverse_archive(
        entries,
        instance=bundle.instance,
        capacity=archive_capacity,
    )
    return (
        InitialPoolResult(
            entries=entries,
            archive=archive,
            best=best,
            anchor=entries[0],
            candidate_evaluations=int(context.budget.count),
            reference_replays=int(context.score_counts.get("reference", 0)),
            construction_attempts=count,
            construction_failures=[],
            score_counts={
                str(key): int(value)
                for key, value in context.score_counts.items()
            },
        ),
        ledgers,
    )


def build_global_regret_solution(
    bundle: SearchBundle,
    *,
    config: RegretConfig,
    seed: int,
    prices: Any,
    owners: dict[str, str],
    ledger: ConstructionLedger,
) -> Solution:
    """Construct routes by model-aware regret insertion over every depot."""

    instance = bundle.instance
    depots = sorted(
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() == "d"
    )
    customers = sorted(
        (
            node.node_id
            for node in instance.nodes
            if node.node_type.lower() == "c"
        )
    )
    if not depots:
        raise ValueError("global regret construction requires at least one depot")
    rng = random.Random(seed)
    plans: list[RoutePlan] = []
    unassigned = set(customers)
    feasible_cache: dict[tuple[str, tuple[str, ...]], bool] = {}
    cost_cache: dict[tuple[str, tuple[str, ...]], float] = {}
    while unassigned:
        customer_rows: list[
            tuple[float, float, str, list[tuple[float, str, int | None, int]]]
        ] = []
        for customer_id in sorted(unassigned):
            options = insertion_options(
                customer_id,
                plans,
                depots,
                bundle,
                owners=owners,
                prices=prices,
                feasible_cache=feasible_cache,
                cost_cache=cost_cache,
                ledger=ledger,
            )
            if not options:
                raise ValueError(f"no feasible global-regret insertion for {customer_id}")
            kth_index = min(max(1, int(config.regret_k)) - 1, len(options) - 1)
            regret = float(options[kth_index][0] - options[0][0])
            if len(options) < int(config.regret_k):
                regret += float(_price(prices, "vehicle_fixed_cost"))
            customer_rows.append(
                (-regret, float(options[0][0]), customer_id, options)
            )
        customer_rows.sort(key=lambda item: (item[0], item[1], item[2]))
        width = max(
            1,
            min(int(config.customer_rcl_width), len(customer_rows)),
        )
        chosen_row = customer_rows[rng.randrange(width)]
        customer_id = chosen_row[2]
        _, depot_id, plan_index, insert_position = chosen_row[3][0]
        if plan_index is None:
            plans.append(RoutePlan(depot_id, [customer_id]))
        else:
            plans[plan_index].customer_ids.insert(insert_position, customer_id)
        unassigned.remove(customer_id)

    routes = [
        Route(
            vehicle_id=f"CV{index + 1}",
            vehicle_type="cv",
            home_depot_id=plan.depot_id,
            node_sequence=[
                plan.depot_id,
                *plan.customer_ids,
                plan.depot_id,
            ],
        )
        for index, plan in enumerate(plans)
    ]
    solution = annotate_cross_site_services(
        Solution(routes=routes),
        owners,
    )
    limits = infer_fleet_limits(bundle.bundle_dir)
    solution = normalize_solution_vehicle_trips(
        solution,
        bundle.instance,
        max_cv=limits.cv,
        max_ev=limits.ev,
    )
    solution = annotate_cross_site_services(solution, owners)
    ledger.selected_cross_depot_customers = len(solution.cross_site_services)
    violations = check_solution(solution, bundle.instance, prices)
    if violations:
        raise ValueError(f"global regret solution is infeasible: {violations[:8]}")
    return solution


def insertion_options(
    customer_id: str,
    plans: list[RoutePlan],
    depots: list[str],
    bundle: SearchBundle,
    *,
    owners: dict[str, str],
    prices: Any,
    feasible_cache: dict[tuple[str, tuple[str, ...]], bool],
    cost_cache: dict[tuple[str, tuple[str, ...]], float],
    ledger: ConstructionLedger,
) -> list[tuple[float, str, int | None, int]]:
    """Enumerate every feasible route position and new-depot route."""

    options: list[tuple[float, str, int | None, int]] = []
    for plan_index, plan in enumerate(plans):
        old_key = (plan.depot_id, tuple(plan.customer_ids))
        old_cost = local_cv_route_cost(
            old_key,
            bundle,
            owners=owners,
            prices=prices,
            cache=cost_cache,
            ledger=ledger,
        )
        for position in range(len(plan.customer_ids) + 1):
            sequence = list(plan.customer_ids)
            sequence.insert(position, customer_id)
            key = (plan.depot_id, tuple(sequence))
            if not route_plan_feasible(
                key,
                bundle.instance,
                prices=prices,
                cache=feasible_cache,
                ledger=ledger,
            ):
                continue
            new_cost = local_cv_route_cost(
                key,
                bundle,
                owners=owners,
                prices=prices,
                cache=cost_cache,
                ledger=ledger,
            )
            options.append(
                (
                    float(new_cost - old_cost),
                    plan.depot_id,
                    plan_index,
                    position,
                )
            )
            ledger.insertion_options += 1
    for depot_id in depots:
        key = (depot_id, (customer_id,))
        if not route_plan_feasible(
            key,
            bundle.instance,
            prices=prices,
            cache=feasible_cache,
            ledger=ledger,
        ):
            continue
        new_cost = local_cv_route_cost(
            key,
            bundle,
            owners=owners,
            prices=prices,
            cache=cost_cache,
            ledger=ledger,
        )
        options.append((float(new_cost), depot_id, None, 0))
        ledger.insertion_options += 1
    return sorted(
        options,
        key=lambda item: (
            item[0],
            item[1],
            10**9 if item[2] is None else item[2],
            item[3],
        ),
    )


def route_plan_feasible(
    key: tuple[str, tuple[str, ...]],
    instance: Instance,
    *,
    prices: Any,
    cache: dict[tuple[str, tuple[str, ...]], bool],
    ledger: ConstructionLedger,
) -> bool:
    cached = cache.get(key)
    if cached is not None:
        return cached
    depot_id, customers = key
    lookup = {node.node_id: node for node in instance.nodes}
    feasible = (
        sum(float(lookup[item].demand) for item in customers)
        <= float(_price(prices, "Q_capacity")) + 1.0e-9
    )
    if feasible:
        route = Route(
            "CV_LOCAL",
            "cv",
            depot_id,
            [depot_id, *customers, depot_id],
        )
        for row in route_node_schedule(route, instance, prices):
            node = lookup[row.node_id]
            if row.t_start > float(node.due_time) + 1.0e-9:
                feasible = False
                break
    cache[key] = bool(feasible)
    ledger.route_feasibility_checks += 1
    return bool(feasible)


def local_cv_route_cost(
    key: tuple[str, tuple[str, ...]],
    bundle: SearchBundle,
    *,
    owners: dict[str, str],
    prices: Any,
    cache: dict[tuple[str, tuple[str, ...]], float],
    ledger: ConstructionLedger,
) -> float:
    cached = cache.get(key)
    if cached is not None:
        return cached
    depot_id, customers = key
    route = Route(
        "CV_LOCAL",
        "cv",
        depot_id,
        [depot_id, *customers, depot_id],
    )
    services = [
        CrossSiteService(customer_id, depot_id)
        for customer_id in customers
        if owners[customer_id] != depot_id
    ]
    value = float(
        evaluate(
            Solution(routes=[route], cross_site_services=services),
            bundle.instance,
            bundle.carbon_profile,
            prices,
        )["total_cost"]
    )
    cache[key] = value
    ledger.route_local_exact_evaluations += 1
    return value


def route_local_complete(
    solution: Solution,
    bundle: SearchBundle,
    *,
    owners: dict[str, str],
    prices: Any,
    ledger: ConstructionLedger,
) -> Solution:
    """Apply the same exact route-local lower layer without a full replay."""

    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    solution = annotate_cross_site_services(solution, owners)
    solution, proxy_objective, joint = exact_joint_fleet_charge_decode(
        solution,
        context,
        incumbent_objective=0.0,
    )
    solution, _, carbon = carbon_aware_depot_retime(
        solution,
        context,
        incumbent_objective=proxy_objective,
        consume_complete_evaluation=False,
    )
    solution = annotate_cross_site_services(solution, owners)
    ledger.joint_route_proxy_evaluations += int(
        joint.get("route_proxy_evaluations", 0)
    )
    ledger.carbon_schedule_evaluations += int(
        carbon.get("route_local_schedule_evaluations", 0)
    )
    violations = check_solution(solution, bundle.instance, prices)
    if violations:
        raise ValueError(f"route-local completion is infeasible: {violations[:8]}")
    return solution


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
