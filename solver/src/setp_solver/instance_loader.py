from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Node:
    node_id: str
    node_type: str
    x: float
    y: float
    demand: float = 0.0
    ready_time: float = 0.0
    due_time: float = 0.0
    service_time: float = 0.0
    # v2026-06-11: optional per-station rated charging power pi_s from generated instance metadata.
    charge_power_kw: float | None = None
    # v2026-06-12: Z0b station/depot charger count C_s for eq:station_capacity.
    # ``station_capacity`` in older generated bundles is accepted by loaders
    # and normalized into this field.
    station_chargers: int | None = None


@dataclass(frozen=True)
class Instance:
    nodes: list[Node]
    distance_matrix: list[list[float]]
    diesel_l_per_meter: float | None = None
    ev_kwh_per_meter: float | None = None
    unit_distance_cost_per_meter: float | None = None
    _node_index: dict[str, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_node_index", {node.node_id: idx for idx, node in enumerate(self.nodes)})

    @property
    def node_index(self) -> dict[str, int]:
        return self._node_index

    def distance(self, from_node_id: str, to_node_id: str) -> float:
        index = self.node_index
        if from_node_id not in index:
            raise KeyError(f"Unknown node id: {from_node_id}")
        if to_node_id not in index:
            raise KeyError(f"Unknown node id: {to_node_id}")
        return float(self.distance_matrix[index[from_node_id]][index[to_node_id]])


def load_instance(path: str | Path) -> Instance:
    instance_path = Path(path)
    nodes: list[Node] = []
    matrix_rows: list[list[float]] = []
    in_matrix = False

    with instance_path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("DistanceMatrix"):
                in_matrix = True
                continue
            if in_matrix:
                matrix_rows.append([float(value) for value in line.split()])
                continue
            if line.startswith("StringID"):
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            try:
                nodes.append(
                    Node(
                        node_id=parts[0],
                        node_type=parts[1],
                        x=float(parts[2]),
                        y=float(parts[3]),
                        demand=float(parts[4]),
                        ready_time=float(parts[5]),
                        due_time=float(parts[6]),
                        service_time=float(parts[7]),
                    )
                )
            except ValueError:
                continue

    if not nodes:
        raise ValueError(f"No nodes found in instance file: {instance_path}")
    if len(matrix_rows) != len(nodes) or any(len(row) != len(nodes) for row in matrix_rows):
        raise ValueError("Distance matrix shape does not match node count")
    return Instance(nodes=nodes, distance_matrix=matrix_rows)


def load_carbon_profile(path: str | Path) -> list[dict[str, Any]]:
    profile_path = Path(path)
    rows: list[dict[str, Any]] = []
    with profile_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                {
                    "time_index": int(row["time_index"]),
                    "datetime_utc": row["datetime_utc"],
                    "actual_gco2_per_kwh": float(row["actual_gco2_per_kwh"]),
                    "forecast_gco2_per_kwh": float(row["forecast_gco2_per_kwh"]),
                    "index_label": row["index_label"],
                    "index_code": int(row["index_code"]),
                    "horizon_second_start": float(row["horizon_second_start"]),
                }
            )
    rows.sort(key=lambda item: item["horizon_second_start"])
    return rows
