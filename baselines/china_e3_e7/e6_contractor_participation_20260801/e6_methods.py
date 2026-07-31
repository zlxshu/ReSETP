"""Small E6 building blocks: coalition settlement and profit-constrained SP."""

from __future__ import annotations

import itertools
import math
from dataclasses import replace
from types import MappingProxyType
from typing import Any, Iterable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp

from route_pool_sp import RoutePoolRecord
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import annotate_cross_site_services, exact_china81_score
from setp_solver.instance_loader import Instance, RoadProfileMatrices
from setp_solver.profit import calculate_depot_profits
from setp_solver.solution import ChargingAction, Route, Solution


Coalition = tuple[str, ...]


def coalitions(members: Iterable[str]) -> tuple[Coalition, ...]:
    ordered = tuple(sorted(members))
    return tuple(
        group
        for size in range(1, len(ordered) + 1)
        for group in itertools.combinations(ordered, size)
    )


def subset_bundle(bundle: China81Bundle, members: Coalition) -> China81Bundle:
    """Keep member depots/customers and the shared public charging network."""

    member_set = set(members)
    owners = {
        customer: depot
        for customer, depot in bundle.customer_home_depot.items()
        if depot in member_set
    }
    keep = [
        index
        for index, node in enumerate(bundle.instance.nodes)
        if node.node_type.lower() == "f"
        or node.node_id in member_set
        or node.node_id in owners
    ]
    base = bundle.instance

    def square(matrix: Any) -> tuple[tuple[float, ...], ...]:
        return tuple(tuple(float(matrix[i][j]) for j in keep) for i in keep)

    profiles = {
        name: RoadProfileMatrices(
            distance_m=square(profile.distance_m),
            duration_s=square(profile.duration_s),
            sum_v2d_m3_s2=square(profile.sum_v2d_m3_s2),
        )
        for name, profile in base.road_profiles.items()
    }
    caps = {
        depot: bundle.fleet_caps_by_depot[depot]
        for depot in sorted(member_set)
    }
    instance = Instance(
        nodes=[base.nodes[index] for index in keep],
        distance_matrix=[
            [float(base.distance_matrix[i][j]) for j in keep]
            for i in keep
        ],
        num_cv=sum(int(row["num_cv"]) for row in caps.values()),
        num_ev=sum(int(row["num_ev"]) for row in caps.values()),
        road_profiles=profiles,
        vehicle_parameters=base.vehicle_parameters,
        demand_mass_per_unit_kg=base.demand_mass_per_unit_kg,
    )
    node_ids = {node.node_id for node in instance.nodes}
    return replace(
        bundle,
        instance=instance,
        customer_home_depot=MappingProxyType(owners),
        fleet_caps_by_depot=MappingProxyType(caps),
        charger_scenario_by_node=MappingProxyType(
            {
                node: row
                for node, row in bundle.charger_scenario_by_node.items()
                if node in node_ids
            }
        ),
    )


def coalition_revenue(bundle: China81Bundle) -> float:
    customers = set(bundle.customer_home_depot)
    demand = sum(
        float(node.demand)
        for node in bundle.instance.nodes
        if node.node_id in customers
    )
    return demand * float(bundle.prices.revenue_per_kg)


def shapley(values: dict[Coalition, float], members: Coalition) -> dict[str, float]:
    n = len(members)
    output = {member: 0.0 for member in members}
    for member in members:
        others = tuple(item for item in members if item != member)
        for size in range(n):
            weight = math.factorial(size) * math.factorial(n - size - 1) / math.factorial(n)
            for group in itertools.combinations(others, size):
                base = tuple(sorted(group))
                joined = tuple(sorted((*group, member)))
                output[member] += weight * (values[joined] - values.get(base, 0.0))
    return output


def core_allocation(
    values: dict[Coalition, float], members: Coalition
) -> tuple[bool, dict[str, float] | None]:
    proper = [group for group in coalitions(members) if len(group) < len(members)]
    matrix = np.array(
        [[-1.0 if member in group else 0.0 for member in members] for group in proper]
    )
    result = linprog(
        np.zeros(len(members)),
        A_ub=matrix,
        b_ub=np.array([-values[group] for group in proper]),
        A_eq=np.ones((1, len(members))),
        b_eq=np.array([values[members]]),
        bounds=[(None, None)] * len(members),
        method="highs",
    )
    if not result.success:
        return False, None
    return True, {member: float(result.x[index]) for index, member in enumerate(members)}


def core_violations(
    allocation: dict[str, float], values: dict[Coalition, float], members: Coalition
) -> dict[Coalition, float]:
    return {
        group: values[group] - sum(allocation[member] for member in group)
        for group in coalitions(members)
        if values[group] - sum(allocation[member] for member in group) > 1e-7
    }


def route_profit(record: RoutePoolRecord, bundle: China81Bundle) -> float:
    lookup = {node.node_id: node for node in bundle.instance.nodes}
    revenue = sum(
        float(lookup[customer].demand) * float(bundle.prices.revenue_per_kg)
        for customer in record.customers
    )
    return revenue - float(record.route_cost)


def solve_profit_floor(
    bundle: China81Bundle,
    records: tuple[RoutePoolRecord, ...],
    standalone_profit: dict[str, float],
    theta: float | None,
    time_limit_seconds: float,
) -> tuple[Solution | None, dict[str, Any]]:
    """Solve the existing route-pool model with four optional profit floors."""

    customers = tuple(bundle.customer_home_depot)
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    index = {customer: row for row, customer in enumerate(customers)}
    cover = np.zeros((len(customers), len(records)))
    for column, record in enumerate(records):
        for customer in record.customers:
            cover[index[customer], column] = 1.0

    constraints = [LinearConstraint(cover, np.ones(len(customers)), np.ones(len(customers)))]
    for vehicle_type, limit in (("cv", bundle.instance.num_cv), ("ev", bundle.instance.num_ev)):
        row = np.array([record.route.vehicle_type.lower() == vehicle_type for record in records])
        constraints.append(LinearConstraint(row, -np.inf, float(limit)))
    for depot in depots:
        for vehicle_type in ("cv", "ev"):
            row = np.array(
                [
                    record.route.home_depot_id == depot
                    and record.route.vehicle_type.lower() == vehicle_type
                    for record in records
                ]
            )
            constraints.append(
                LinearConstraint(row, -np.inf, float(bundle.fleet_caps_by_depot[depot][f"num_{vehicle_type}"]))
            )
        if theta is not None:
            profits = np.array(
                [route_profit(record, bundle) if record.route.home_depot_id == depot else 0.0 for record in records]
            )
            constraints.append(
                LinearConstraint(profits, float(theta) * standalone_profit[depot], np.inf)
            )

    costs = np.array([float(record.route_cost) for record in records])
    result = milp(
        c=costs,
        integrality=np.ones(len(records)),
        bounds=Bounds(np.zeros(len(records)), np.ones(len(records))),
        constraints=constraints,
        options={"time_limit": float(time_limit_seconds)},
    )
    stats = {
        "theta": theta,
        "status": int(result.status),
        "message": str(result.message),
        "feasible": result.x is not None,
        "objective": None if result.fun is None else float(result.fun),
    }
    if result.x is None:
        return None, stats
    selected_vector = np.rint(np.asarray(result.x))
    if not np.allclose(result.x, selected_vector, atol=1e-7) or not np.allclose(
        cover @ selected_vector, np.ones(len(customers)), atol=1e-7
    ):
        raise RuntimeError("route-pool MIP returned an invalid incumbent")

    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for serial, record in enumerate(
        (item for item, take in zip(records, selected_vector) if take > 0.5), start=1
    ):
        vehicle_id = f"E6-{record.route.vehicle_type.upper()}-{serial:03d}"
        routes.append(replace(record.route, vehicle_id=vehicle_id))
        actions.extend(replace(action, vehicle_id=vehicle_id) for action in record.actions)
    solution = annotate_cross_site_services(
        Solution(routes=routes, charging_actions=actions), bundle.customer_home_depot
    )
    objective, _, violations = exact_china81_score(solution, bundle)
    if violations or not math.isclose(objective, float(result.fun), abs_tol=1e-6):
        raise RuntimeError("profit-constrained incumbent failed complete-model recheck")
    ledger = calculate_depot_profits(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        customer_home_depot=dict(bundle.customer_home_depot),
        carbon_quota_kg=0.0,
    )
    stats["profit"] = {depot: float(row.profit) for depot, row in ledger.items()}
    stats["cost_closure_abs_cny"] = abs(
        sum(float(row.cost_total) for row in ledger.values()) - objective
    )
    stats["profit_closure_abs_cny"] = abs(
        sum(float(row.profit) for row in ledger.values())
        - (sum(float(row.revenue) for row in ledger.values()) - objective)
    )
    stats["objective"] = objective
    return solution, stats


def theta_grid(step: float, maximum: float = 1.0) -> tuple[float, ...]:
    return tuple(round(index * step, 10) for index in range(round(maximum / step) + 1))
