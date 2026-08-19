"""Slice one enterprise from the sealed joint private problem.

declared_identity=PROJECT_ADAPTER
code_role=THIN_ADAPTER

This adapter only selects existing project facts and rewires their carriers. It
does not construct routes, assign customers, schedule trips, or search.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance, Node
from setp_solver.instance_subset import rebuild_instance_matrix

from .evaluation import RebuiltRouteConstraintContract


@dataclass(frozen=True)
class EnterpriseSeedInput:
    """Exact enterprise fields consumed by the disclosed legacy constructor."""

    instance: Instance
    orders_by_customer: Mapping[str, Mapping[str, float | str]]
    customer_home_depot: Mapping[str, str]


@dataclass(frozen=True)
class EnterpriseProblemSlice:
    """One immutable enterprise view over the sealed joint problem."""

    bundle: China81Bundle
    route_constraints: RebuiltRouteConstraintContract
    seed_input: EnterpriseSeedInput
    enterprise_id: str
    depot_id: str
    customer_ids: tuple[str, ...]
    source_id: str
    mapping_sha256: str


def _enterprise_scope(
    bundle: China81Bundle,
    route_constraints: RebuiltRouteConstraintContract,
    enterprise_id: str,
) -> tuple[str, tuple[str, ...], dict[str, str], str]:
    selected_enterprise = str(enterprise_id).strip()
    if not selected_enterprise:
        raise ValueError("enterprise id cannot be empty")
    assignment = bundle.enterprise_assignment_by_customer
    if not assignment:
        raise ValueError("enterprise assignment is unavailable")
    customer_ids = tuple(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
        and assignment.get(node.node_id) == selected_enterprise
    )
    if not customer_ids:
        raise ValueError(f"unknown enterprise id: {selected_enterprise}")
    if set(customer_ids) - set(route_constraints.customer_shift_by_id):
        raise ValueError("enterprise customers are outside the route contract")
    try:
        customer_home_depot = {
            customer_id: str(bundle.customer_home_depot[customer_id])
            for customer_id in customer_ids
        }
    except KeyError as exc:
        raise ValueError("enterprise customer has no registered home depot") from exc
    depot_ids = set(customer_home_depot.values())
    if len(depot_ids) != 1:
        raise ValueError("one enterprise must map to exactly one depot")
    return (
        selected_enterprise,
        customer_ids,
        customer_home_depot,
        next(iter(depot_ids)),
    )


def _selected_nodes(
    bundle: China81Bundle,
    depot_id: str,
    customer_ids: tuple[str, ...],
) -> tuple[tuple[Node, ...], tuple[str, ...]]:
    nodes_by_id = {node.node_id: node for node in bundle.instance.nodes}
    if depot_id not in nodes_by_id or nodes_by_id[depot_id].node_type.lower() != "d":
        raise ValueError("enterprise depot is absent from the sealed instance")
    public_stations = tuple(
        node for node in bundle.instance.nodes if node.node_type.lower() == "f"
    )
    try:
        selected_customers = tuple(
            nodes_by_id[customer_id] for customer_id in customer_ids
        )
    except KeyError as exc:
        raise ValueError("enterprise assignment references an absent customer") from exc
    return (
        (nodes_by_id[depot_id], *public_stations, *selected_customers),
        tuple(node.node_id for node in public_stations),
    )


def _selected_fleet_caps(
    bundle: China81Bundle,
    depot_id: str,
) -> tuple[Mapping[str, int], int, int]:
    try:
        selected_caps = MappingProxyType(
            {
                str(key): int(value)
                for key, value in bundle.fleet_caps_by_depot[depot_id].items()
            }
        )
        num_cv = int(selected_caps["num_cv"])
        num_ev = int(selected_caps["num_ev"])
        total_fleet_cap = int(selected_caps["total_fleet_cap"])
    except KeyError as exc:
        raise ValueError("enterprise fleet-cap row is incomplete") from exc
    if num_cv < 0 or num_ev < 0 or num_cv + num_ev > total_fleet_cap:
        raise ValueError("enterprise fleet-cap row is inconsistent")
    return selected_caps, num_cv, num_ev


def _selected_chargers(
    bundle: China81Bundle,
    charger_ids: tuple[str, ...],
) -> Mapping[str, Mapping[str, float | int | str]]:
    try:
        return MappingProxyType(
            {
                node_id: MappingProxyType(
                    dict(bundle.charger_scenario_by_node[node_id])
                )
                for node_id in charger_ids
            }
        )
    except KeyError as exc:
        raise ValueError("retained charging node has no scenario row") from exc


def _selected_route_constraints(
    route_constraints: RebuiltRouteConstraintContract,
    enterprise_id: str,
    customer_ids: tuple[str, ...],
) -> RebuiltRouteConstraintContract:
    selected_shifts = {
        customer_id: str(route_constraints.customer_shift_by_id[customer_id])
        for customer_id in customer_ids
    }
    return RebuiltRouteConstraintContract(
        source_id=f"{route_constraints.source_id}/enterprise/{enterprise_id}",
        customer_shift_by_id=MappingProxyType(selected_shifts),
        customer_volume_m3_by_id=MappingProxyType(
            {
                customer_id: float(
                    route_constraints.customer_volume_m3_by_id[customer_id]
                )
                for customer_id in customer_ids
            }
        ),
        shift_window_second_by_id=MappingProxyType(
            {
                shift_id: tuple(route_constraints.shift_window_second_by_id[shift_id])
                for shift_id in set(selected_shifts.values())
            }
        ),
        vehicle_volume_capacity_m3=float(
            route_constraints.vehicle_volume_capacity_m3
        ),
    )


def slice_enterprise_problem(
    bundle: China81Bundle,
    route_constraints: RebuiltRouteConstraintContract,
    enterprise_id: str,
) -> EnterpriseProblemSlice:
    """Select one depot, its customers, and every shared public station."""

    (
        selected_enterprise,
        customer_ids,
        customer_home_depot,
        depot_id,
    ) = _enterprise_scope(bundle, route_constraints, enterprise_id)
    selected_nodes, public_station_ids = _selected_nodes(
        bundle,
        depot_id,
        customer_ids,
    )
    selected_caps, num_cv, num_ev = _selected_fleet_caps(bundle, depot_id)
    sliced_instance = replace(
        rebuild_instance_matrix(bundle.instance, selected_nodes),
        num_cv=num_cv,
        num_ev=num_ev,
    )
    selected_chargers = _selected_chargers(
        bundle,
        (depot_id, *public_station_ids),
    )
    selected_route_constraints = _selected_route_constraints(
        route_constraints,
        selected_enterprise,
        customer_ids,
    )

    mapping_sha256 = bundle.enterprise_assignment_mapping_sha256
    if mapping_sha256 is None or len(mapping_sha256) != 64:
        raise ValueError("enterprise assignment identity is unavailable")
    source_id = (
        f"{bundle.instance_id}/enterprise/{selected_enterprise}/"
        f"{mapping_sha256}"
    )
    selected_bundle = replace(
        bundle,
        instance=sliced_instance,
        customer_home_depot=MappingProxyType(customer_home_depot),
        fleet_caps_by_depot=MappingProxyType({depot_id: selected_caps}),
        charger_scenario_by_node=selected_chargers,
        enterprise_assignment_by_customer=MappingProxyType(
            {
                customer_id: selected_enterprise
                for customer_id in customer_ids
            }
        ),
    )
    nodes_by_id = {node.node_id: node for node in selected_nodes}
    seed_input = EnterpriseSeedInput(
        instance=sliced_instance,
        orders_by_customer=MappingProxyType(
            {
                customer_id: MappingProxyType(
                    {
                        "shift_id": selected_route_constraints.customer_shift_by_id[
                            customer_id
                        ],
                        "time_window_early_minute": (
                            nodes_by_id[customer_id].ready_time / 60.0
                        ),
                        "time_window_late_minute": (
                            nodes_by_id[customer_id].due_time / 60.0
                        ),
                        "service_minutes": (
                            nodes_by_id[customer_id].service_time / 60.0
                        ),
                        "source_volume_m3": selected_route_constraints.customer_volume_m3_by_id[
                            customer_id
                        ],
                        "demand_kg": nodes_by_id[customer_id].demand,
                    }
                )
                for customer_id in customer_ids
            }
        ),
        customer_home_depot=selected_bundle.customer_home_depot,
    )
    return EnterpriseProblemSlice(
        bundle=selected_bundle,
        route_constraints=selected_route_constraints,
        seed_input=seed_input,
        enterprise_id=selected_enterprise,
        depot_id=depot_id,
        customer_ids=customer_ids,
        source_id=source_id,
        mapping_sha256=mapping_sha256,
    )
