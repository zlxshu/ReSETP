"""Generated-instance bundle loading for solver search gates.

v2026-06-11: Search gates use generated JSON/numpy bundles rather than the
Goeke-style text file because paper_main.tex lines 449-457 require station
power ``pi_s`` and the text export does not carry ``charge_power_kw``. Use
``load_search_bundle(path)`` for verify_20251113 and later generated bundles.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np

from ..instance_loader import Instance, Node, load_carbon_profile
from .fleet import UNBOUNDED_FLEET, infer_fleet_limits


@dataclass(frozen=True)
class SearchBundle:
    bundle_dir: Path
    instance: Instance
    carbon_profile: list[dict[str, Any]]


def load_search_bundle(bundle_dir: str | Path) -> SearchBundle:
    """Load ``instance.json``, ``distance_matrix.npy``, and ``carbon_profile.csv``."""

    path = Path(bundle_dir)
    data = json.loads((path / "instance.json").read_text(encoding="utf-8"))
    metadata = data.get("metadata", {})
    num_cv = _optional_int(metadata.get("num_cv"))
    num_ev = _optional_int(metadata.get("num_ev"))
    if num_cv is None or num_ev is None:
        limits = infer_fleet_limits(path)
        if num_cv is None and limits.cv < UNBOUNDED_FLEET:
            num_cv = limits.cv
        if num_ev is None and limits.ev < UNBOUNDED_FLEET:
            num_ev = limits.ev
    raw_nodes = data["nodes"]
    customer_count = sum(1 for row in raw_nodes if str(row.get("node_type", "")).lower() == "c")
    nodes = [
        Node(
            node_id=str(row["node_id"]),
            node_type=str(row["node_type"]),
            x=float(row["x"]),
            y=float(row["y"]),
            demand=float(row.get("demand", 0.0)),
            ready_time=float(row.get("ready_time", row.get("e", 0.0))),
            due_time=float(row.get("due_time", row.get("l", 0.0))),
            service_time=float(row.get("service_time", row.get("ServiceTime", 0.0))),
            charge_power_kw=_optional_float(row.get("charge_power_kw")),
            # v2026-06-12: Z0b normalizes station capacity into C_s. Public
            # stations default to one scarce charger; depots default to a
            # static route-count upper bound so depot overnight charging is
            # capacity-checked but not made artificially scarce.
            station_chargers=_station_chargers(row, customer_count),
            physical_station_id=(
                None
                if row.get("physical_station_id") is None
                else str(row["physical_station_id"])
            ),
        )
        for row in raw_nodes
    ]
    matrix = np.load(path / "distance_matrix.npy").astype(float).tolist()
    carbon_profile = load_carbon_profile(path / "carbon_profile.csv")
    return SearchBundle(
        path,
        Instance(
            nodes=nodes,
            distance_matrix=matrix,
            num_cv=num_cv,
            num_ev=num_ev,
        ),
        carbon_profile,
    )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _station_chargers(row: dict[str, object], customer_count: int) -> int | None:
    node_type = str(row.get("node_type", "")).lower()
    raw = row.get("station_chargers", row.get("station_capacity"))
    if raw is not None:
        return int(raw)
    if node_type == "d":
        return max(1, int(customer_count))
    if node_type == "f":
        return 1
    return None
