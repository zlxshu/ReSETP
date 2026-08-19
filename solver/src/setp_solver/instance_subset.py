"""Exact node-induced subinstances for profiled project inputs.

declared_identity=PROJECT_DOMAIN
code_role=PURE_FUNCTION
"""

from __future__ import annotations

from collections.abc import Sequence

from .instance_loader import Instance, Node, RoadProfileMatrices


def rebuild_instance_matrix(
    source: Instance,
    nodes: Sequence[Node],
) -> Instance:
    """Keep selected nodes and slice every same-path matrix identically."""

    selected_nodes = list(nodes)
    source_index = source.node_index
    missing_profiled_nodes = [
        node.node_id
        for node in selected_nodes
        if node.node_id not in source_index
    ]
    if source.road_profiles is not None and missing_profiled_nodes:
        raise ValueError(
            "profiled dynamic customers require precomputed CV/EV road "
            "metrics; missing nodes: "
            + ", ".join(sorted(missing_profiled_nodes))
        )
    matrix: list[list[float]] = []
    for from_node in selected_nodes:
        row: list[float] = []
        for to_node in selected_nodes:
            if (
                from_node.node_id in source_index
                and to_node.node_id in source_index
            ):
                row.append(
                    float(source.distance(from_node.node_id, to_node.node_id))
                )
            else:
                row.append(
                    float(
                        (
                            (from_node.x - to_node.x) ** 2
                            + (from_node.y - to_node.y) ** 2
                        )
                        ** 0.5
                    )
                )
        matrix.append(row)
    road_profiles = None
    if source.road_profiles is not None:
        indices = [source_index[node.node_id] for node in selected_nodes]
        road_profiles = {
            profile: RoadProfileMatrices(
                distance_m=tuple(
                    tuple(
                        float(matrices.distance_m[left][right])
                        for right in indices
                    )
                    for left in indices
                ),
                duration_s=tuple(
                    tuple(
                        float(matrices.duration_s[left][right])
                        for right in indices
                    )
                    for left in indices
                ),
                sum_v2d_m3_s2=tuple(
                    tuple(
                        float(matrices.sum_v2d_m3_s2[left][right])
                        for right in indices
                    )
                    for left in indices
                ),
            )
            for profile, matrices in source.road_profiles.items()
        }
    return Instance(
        nodes=selected_nodes,
        distance_matrix=matrix,
        diesel_l_per_meter=source.diesel_l_per_meter,
        ev_kwh_per_meter=source.ev_kwh_per_meter,
        unit_distance_cost_per_meter=source.unit_distance_cost_per_meter,
        num_cv=source.num_cv,
        num_ev=source.num_ev,
        road_profiles=road_profiles,
        vehicle_parameters=source.vehicle_parameters,
        demand_mass_per_unit_kg=source.demand_mass_per_unit_kg,
    )
