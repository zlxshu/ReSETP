"""Depot profit accounting for optional fairness constraints.

v2026-06-12: V2 makes the paper's profit-fairness equations executable while
keeping fairness disabled by default. This module only allocates revenue and
cost components from an existing ``Solution``; it does not change CMEM, carbon,
price, or route-feasibility semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from .cost import (
    _evaluate_route,
    _price,
    charging_action_electricity_cost,
    charging_action_emissions_kg,
)
from .instance_loader import Instance, Node
from .prices import DEFAULT_PRICES, PriceParameters
from .solution import ChargingAction, Route, Solution


@dataclass(frozen=True)
class DepotProfitBreakdown:
    depot_id: str
    revenue: float
    cost_fixed: float
    cost_km: float
    cost_fuel: float
    cost_electricity: float
    cost_occupancy: float
    cost_transship: float
    cost_carbon: float
    cost_total: float
    profit: float
    customers_served: int
    demand_kg: float
    emissions_kg: float
    cv_direct_emissions_kg: float
    ev_indirect_emissions_kg: float
    depot_charging_kwh: float
    station_charging_kwh: float

    def to_dict(self) -> dict[str, float | str | int]:
        return asdict(self)


def infer_customer_home_depots(instance: Instance) -> dict[str, str]:
    """Infer ``d_i^0`` as the nearest depot when no explicit owner is stored."""

    depots = [node for node in instance.nodes if node.node_type.lower() == "d"]
    if not depots:
        raise ValueError("Cannot infer customer home depots without depot nodes")
    return {
        node.node_id: min(depots, key=lambda depot: instance.distance(depot.node_id, node.node_id)).node_id
        for node in instance.nodes
        if node.node_type.lower() == "c"
    }


def calculate_depot_profits(
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    customer_home_depot: dict[str, str] | None = None,
    prior_profit: dict[str, float] | None = None,
    carbon_quota_kg: float = 0.0,
    revenue_per_kg: float | None = None,
) -> dict[str, DepotProfitBreakdown]:
    """Return paper ``Pi_d`` and ``C_d`` components by service depot.

    Revenue follows ``R_i = rho * q_i`` and is credited to the depot serving the
    customer. Fixed, distance, fuel, electricity, occupancy, and carbon costs
    are allocated to the vehicle's route home depot. Cross-site service cost is
    charged when the service depot differs from inferred or supplied
    ``d_i^0``.
    """

    node_lookup = {node.node_id: node for node in instance.nodes}
    depot_ids = sorted(node.node_id for node in instance.nodes if node.node_type.lower() == "d")
    owners = customer_home_depot or infer_customer_home_depots(instance)
    prior = prior_profit or {}
    rho = _price(prices, "revenue_per_kg") if revenue_per_kg is None else float(revenue_per_kg)
    route_by_vehicle = {route.vehicle_id: route for route in solution.routes}
    data = {_depot: _empty_row(_depot, prior.get(_depot, 0.0)) for _depot in depot_ids}

    for route in solution.routes:
        depot_id = route.home_depot_id
        if depot_id not in data:
            data[depot_id] = _empty_row(depot_id, prior.get(depot_id, 0.0))
        row = data[depot_id]
        route_energy = _evaluate_route(route, instance, node_lookup, prices)
        row["cost_fixed"] += _price(prices, "vehicle_fixed_cost")
        row["cost_km"] += (
            route_energy.distance_m
            / 1000.0
            * instance.non_energy_distance_cost_per_km(
                route.vehicle_type,
                fallback=_price(prices, "c_km"),
            )
        )
        if route.vehicle_type.lower() == "cv":
            row["cost_fuel"] += route_energy.fuel_liters * _price(prices, "diesel_price")
            row["cv_direct_emissions_kg"] += route_energy.fuel_liters * _price(prices, "diesel_ef")
        for customer_id in _route_customer_ids(route, node_lookup):
            customer = node_lookup[customer_id]
            demand = float(customer.demand)
            row["revenue"] += rho * demand
            row["customers_served"] += 1
            row["demand_kg"] += demand
            if owners.get(customer_id) != depot_id:
                row["cost_transship"] += _price(prices, "cross_site_cost")

    for action in solution.charging_actions:
        route = route_by_vehicle.get(action.vehicle_id)
        if route is None:
            continue
        depot_id = route.home_depot_id
        if depot_id not in data:
            data[depot_id] = _empty_row(depot_id, prior.get(depot_id, 0.0))
        row = data[depot_id]
        station = node_lookup.get(action.station_id)
        station_type = station.node_type.lower() if station is not None else ""
        row["cost_electricity"] += charging_action_electricity_cost(
            action,
            instance,
            carbon_profile,
            prices,
        )
        if station_type == "d":
            row["depot_charging_kwh"] += float(action.energy_kwh)
        else:
            row["cost_occupancy"] += float(action.occupancy_minutes) * _price(prices, "occupancy_fee")
            row["station_charging_kwh"] += float(action.energy_kwh)
        row["ev_indirect_emissions_kg"] += _charging_action_emissions(
            action,
            instance,
            carbon_profile,
            prices,
        )

    total_emissions = sum(row["cv_direct_emissions_kg"] + row["ev_indirect_emissions_kg"] for row in data.values())
    # v2026-06-12: W2a keeps depot-profit allocation numerically consistent
    # with cost.evaluate: CE=inf is a safe no-trading sentinel, while the paper
    # no-trading experiment switch is p_car=0.
    quota = float(carbon_quota_kg)
    total_carbon_cost = 0.0 if math.isinf(quota) else (total_emissions - quota) * _price(prices, "carbon_price")
    for row in data.values():
        emissions = row["cv_direct_emissions_kg"] + row["ev_indirect_emissions_kg"]
        row["emissions_kg"] = emissions
        row["cost_carbon"] = 0.0 if total_emissions <= 1e-12 else total_carbon_cost * emissions / total_emissions

    return {
        depot_id: _finalize_row(depot_id, row)
        for depot_id, row in sorted(data.items())
    }


def depot_profit_values(breakdowns: dict[str, DepotProfitBreakdown]) -> dict[str, float]:
    return {depot_id: row.profit for depot_id, row in breakdowns.items()}


def _empty_row(depot_id: str, prior_profit: float) -> dict[str, float]:
    _ = depot_id
    return {
        "prior_profit": float(prior_profit),
        "revenue": 0.0,
        "cost_fixed": 0.0,
        "cost_km": 0.0,
        "cost_fuel": 0.0,
        "cost_electricity": 0.0,
        "cost_occupancy": 0.0,
        "cost_transship": 0.0,
        "cost_carbon": 0.0,
        "customers_served": 0.0,
        "demand_kg": 0.0,
        "emissions_kg": 0.0,
        "cv_direct_emissions_kg": 0.0,
        "ev_indirect_emissions_kg": 0.0,
        "depot_charging_kwh": 0.0,
        "station_charging_kwh": 0.0,
    }


def _finalize_row(depot_id: str, row: dict[str, float]) -> DepotProfitBreakdown:
    cost_total = (
        row["cost_fixed"]
        + row["cost_km"]
        + row["cost_fuel"]
        + row["cost_electricity"]
        + row["cost_occupancy"]
        + row["cost_transship"]
        + row["cost_carbon"]
    )
    profit = row["prior_profit"] + row["revenue"] - cost_total
    return DepotProfitBreakdown(
        depot_id=depot_id,
        revenue=row["revenue"],
        cost_fixed=row["cost_fixed"],
        cost_km=row["cost_km"],
        cost_fuel=row["cost_fuel"],
        cost_electricity=row["cost_electricity"],
        cost_occupancy=row["cost_occupancy"],
        cost_transship=row["cost_transship"],
        cost_carbon=row["cost_carbon"],
        cost_total=cost_total,
        profit=profit,
        customers_served=int(row["customers_served"]),
        demand_kg=row["demand_kg"],
        emissions_kg=row["emissions_kg"],
        cv_direct_emissions_kg=row["cv_direct_emissions_kg"],
        ev_indirect_emissions_kg=row["ev_indirect_emissions_kg"],
        depot_charging_kwh=row["depot_charging_kwh"],
        station_charging_kwh=row["station_charging_kwh"],
    )


def _route_customer_ids(route: Route, node_lookup: dict[str, Node]) -> list[str]:
    return [
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
    ]


def _charging_action_emissions(
    action: ChargingAction,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, Any] | Any,
) -> float:
    return charging_action_emissions_kg(
        action,
        instance,
        carbon_profile,
        prices,
    )
