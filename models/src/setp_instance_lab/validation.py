from __future__ import annotations

from typing import Any

import numpy as np

from .config import ScenarioConfig
from .models import Node


def validate_scenario(nodes: list[Node], distance_matrix: np.ndarray, config: ScenarioConfig) -> dict[str, Any]:
    depots = [node for node in nodes if node.node_type == "d"]
    stations = [node for node in nodes if node.node_type == "f"]
    customers = [node for node in nodes if node.node_type == "c"]
    xy = np.asarray([(node.x, node.y) for node in nodes], dtype=float)
    customer_xy = np.asarray([(node.x, node.y) for node in customers], dtype=float)
    depot_xy = np.asarray([(node.x, node.y) for node in depots], dtype=float)

    duplicate_coordinate_count = _duplicate_coordinate_count(xy)
    min_depot_distance = _min_pairwise(depot_xy)
    max_customer_demand = max((node.demand for node in customers), default=0.0)
    customer_cap = config.vehicle_capacity * config.max_customer_demand_ratio

    if len(depot_xy) and len(customer_xy):
        nearest_depot = np.min(_dist(customer_xy, depot_xy), axis=1)
        threshold = max((config.coord_bounds[1] - config.coord_bounds[0]), (config.coord_bounds[3] - config.coord_bounds[2])) * 0.45
        isolated_share = float(np.mean(nearest_depot > threshold))
    else:
        isolated_share = 1.0

    checks = {
        "node_count": len(nodes),
        "depot_count": len(depots),
        "station_count": len(stations),
        "customer_count": len(customers),
        "distance_matrix_shape": list(distance_matrix.shape),
        "duplicate_coordinate_count": duplicate_coordinate_count,
        "min_depot_distance": min_depot_distance,
        "max_customer_demand": max_customer_demand,
        "customer_demand_cap": customer_cap,
        "isolated_customer_share": isolated_share,
    }
    exact_base_layout = bool(config.empirical_exact_base)
    checks["passed"] = (
        len(depots) == config.n_depots
        and len(stations) == config.n_stations
        and len(customers) == config.n_customers
        and distance_matrix.shape == (len(nodes), len(nodes))
        and (duplicate_coordinate_count == 0 or exact_base_layout)
        and (config.n_depots < 2 or min_depot_distance >= config.min_depot_distance * 0.5)
        and max_customer_demand <= customer_cap + 1e-9
        and (isolated_share <= config.max_isolated_customer_share + 1e-9 or exact_base_layout)
    )
    checks["exact_base_layout_relaxed"] = exact_base_layout
    return checks


def _dist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    delta = a[:, None, :] - b[None, :, :]
    return np.sqrt(np.sum(delta * delta, axis=2))


def _min_pairwise(xy: np.ndarray) -> float:
    if len(xy) < 2:
        return float("inf")
    d = _dist(xy, xy)
    d[d == 0] = np.inf
    return float(np.min(d))


def _duplicate_coordinate_count(xy: np.ndarray) -> int:
    if len(xy) == 0:
        return 0
    rounded = np.round(xy, decimals=6)
    return int(len(rounded) - len({tuple(row) for row in rounded}))
