"""Charging-station visit copies for the E5 nonlinear-charging sensitivity."""

from __future__ import annotations

from dataclasses import replace

from .instance_loader import Instance, Node, RoadProfileMatrices

COPY_SEPARATOR = "__visit_"


def physical_station_id(node: Node) -> str:
    return node.physical_station_id or node.node_id


def with_station_visit_copies(instance: Instance) -> Instance:
    """Give every public station enough aliases for any one route.

    The current repair inserts at most one charging stop before each remaining
    target. Customer count plus one is therefore a structural upper bound, not
    a calibrated experimental parameter.
    """

    base_nodes = list(instance.nodes)
    station_indices = [
        index
        for index, node in enumerate(base_nodes)
        if node.node_type.lower() == "f" and node.physical_station_id is None
    ]
    customer_count = sum(node.node_type.lower() == "c" for node in base_nodes)
    source_indices = list(range(len(base_nodes)))
    nodes = list(base_nodes)
    for source_index in station_indices:
        station = base_nodes[source_index]
        for visit in range(2, customer_count + 2):
            nodes.append(
                replace(
                    station,
                    node_id=f"{station.node_id}{COPY_SEPARATOR}{visit}",
                    physical_station_id=station.node_id,
                )
            )
            source_indices.append(source_index)

    def expand(matrix):
        return tuple(
            tuple(float(matrix[left][right]) for right in source_indices)
            for left in source_indices
        )

    profiles = None
    if instance.road_profiles is not None:
        profiles = {
            profile: RoadProfileMatrices(
                distance_m=expand(matrices.distance_m),
                duration_s=expand(matrices.duration_s),
                sum_v2d_m3_s2=expand(matrices.sum_v2d_m3_s2),
            )
            for profile, matrices in instance.road_profiles.items()
        }
    return Instance(
        nodes=nodes,
        distance_matrix=[list(row) for row in expand(instance.distance_matrix)],
        diesel_l_per_meter=instance.diesel_l_per_meter,
        ev_kwh_per_meter=instance.ev_kwh_per_meter,
        unit_distance_cost_per_meter=instance.unit_distance_cost_per_meter,
        num_cv=instance.num_cv,
        num_ev=instance.num_ev,
        road_profiles=profiles,
        vehicle_parameters=instance.vehicle_parameters,
        demand_mass_per_unit_kg=instance.demand_mass_per_unit_kg,
    )
