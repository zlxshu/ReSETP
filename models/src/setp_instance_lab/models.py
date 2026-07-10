from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


@dataclass
class Node:
    node_id: str
    node_type: str
    x: float
    y: float
    demand: float = 0.0
    ready_time: float = 0.0
    due_time: float = 0.0
    service_time: float = 0.0
    station_capacity: int | None = None
    # v2026-06-12: Z0b canonical charger-count field for paper C_s. The
    # legacy station_capacity field is kept for backward-compatible bundles.
    station_chargers: int | None = None
    charge_power_kw: float | None = None
    carbon_region: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateScore:
    candidate_id: str
    role: str
    x: float
    y: float
    score: float
    coverage_score: float
    balance_score: float
    distance_score: float
    separation_score: float
    feasibility_score: float
    selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DynamicEvent:
    event_id: int
    event_type: str
    t_appear: float
    customer_id: str
    x: float
    y: float
    old_demand: float
    new_demand: float
    delta_demand: float
    old_ready_time: float
    old_due_time: float
    new_ready_time: float
    new_due_time: float
    time_window_action: str
    demand_source: str
    time_window_source: str
    donor_instance_id: str
    donor_customer_id: str
    source: str
    seed: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Scenario:
    scenario_id: str
    seed: int
    nodes: list[Node]
    distance_matrix: np.ndarray
    depot_scores: list[CandidateScore]
    station_scores: list[CandidateScore]
    dynamic_events: list[DynamicEvent] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_instance_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "nodes": [node.to_dict() for node in self.nodes],
            "distance_unit": "meter",
            "time_unit": "second",
            "demand_unit": "kg",
            "metadata": self.metadata,
        }
