from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .models import Node


@dataclass
class BaseDistribution:
    depot_xy: np.ndarray
    station_xy: np.ndarray
    customer_xy: np.ndarray
    customer_demand: np.ndarray
    ready_time: np.ndarray
    due_time: np.ndarray
    service_time: np.ndarray
    source_path: str

    @property
    def has_data(self) -> bool:
        return self.customer_xy.size > 0 and self.customer_demand.size > 0


def parse_evrptwmf(path: str | Path) -> tuple[list[Node], np.ndarray]:
    file_path = Path(path)
    lines = [line.strip() for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines()]
    nodes: list[Node] = []
    matrix_rows: list[list[float]] = []
    in_matrix = False

    for line in lines:
        if not line:
            continue
        if line.lower().startswith("distancematrix"):
            in_matrix = True
            continue
        if in_matrix:
            values = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", line)]
            if values:
                matrix_rows.append(values)
            continue
        parts = re.split(r"\s+", line)
        if len(parts) >= 8 and parts[0].lower() != "stringid":
            try:
                x, y, demand, ready, due, service = [float(v) for v in parts[2:8]]
            except ValueError:
                continue
            nodes.append(
                Node(
                    node_id=parts[0],
                    node_type=parts[1].lower(),
                    x=x,
                    y=y,
                    demand=demand,
                    ready_time=ready,
                    due_time=due,
                    service_time=service,
                )
            )

    if not nodes:
        raise ValueError(f"No EVRPTWMF nodes parsed from {file_path}")
    matrix = np.asarray(matrix_rows, dtype=float)
    if matrix_rows and matrix.shape != (len(nodes), len(nodes)):
        raise ValueError(f"Distance matrix shape {matrix.shape} does not match node count {len(nodes)}")
    if not matrix_rows:
        xy = np.asarray([(node.x, node.y) for node in nodes], dtype=float)
        matrix = pairwise_distances(xy)
    return nodes, matrix


def load_base_distribution(path: str | Path | None) -> BaseDistribution | None:
    if not path:
        return None
    nodes, _ = parse_evrptwmf(path)
    depots = [node for node in nodes if node.node_type == "d"]
    stations = [node for node in nodes if node.node_type == "f"]
    customers = [node for node in nodes if node.node_type == "c"]
    if not customers:
        return None
    return BaseDistribution(
        depot_xy=np.asarray([(node.x, node.y) for node in depots], dtype=float),
        station_xy=np.asarray([(node.x, node.y) for node in stations], dtype=float),
        customer_xy=np.asarray([(node.x, node.y) for node in customers], dtype=float),
        customer_demand=np.asarray([node.demand for node in customers], dtype=float),
        ready_time=np.asarray([node.ready_time for node in customers], dtype=float),
        due_time=np.asarray([node.due_time for node in customers], dtype=float),
        service_time=np.asarray([node.service_time for node in customers], dtype=float),
        source_path=str(Path(path)),
    )


def pairwise_distances(xy: np.ndarray) -> np.ndarray:
    delta = xy[:, None, :] - xy[None, :, :]
    return np.sqrt(np.sum(delta * delta, axis=2))
