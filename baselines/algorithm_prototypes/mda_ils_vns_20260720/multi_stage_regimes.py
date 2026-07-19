"""Frozen regimes for the MPD-ILS-VNS dual-regime candidate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from selective_route_vns import SearchConfig


FAST = SearchConfig(
    "foundation",
    route_operators=("SwapStar",),
)
WIDE = SearchConfig(
    "wide",
    route_operators=("SwapStar",),
    weight_wait_time=0.5,
    weight_time_warp=0.5,
    num_neighbours=65,
    symmetric_neighbours=False,
    history_length=100,
    min_perturbations=5,
    max_perturbations=25,
)


@dataclass(frozen=True)
class Phase:
    regime: str
    cumulative_fraction: float


ARMS: dict[str, tuple[Phase, ...]] = {
    "foundation": (Phase("foundation", 1.0),),
    "wide": (Phase("wide", 1.0),),
    "wide70_fast30": (
        Phase("wide", 0.7),
        Phase("foundation", 1.0),
    ),
    "fast20_wide60_fast20": (
        Phase("foundation", 0.2),
        Phase("wide", 0.8),
        Phase("foundation", 1.0),
    ),
}

REGIMES = {"foundation": FAST, "wide": WIDE}

EXPERTS = (
    "depot_responsibility",
    "fleet_charge",
    "carbon_timing",
    "fairness",
    "dynamic_replanning",
)


def query_public_experts(phase_index: int) -> list[dict[str, Any]]:
    """Record the mandatory public-instance eligibility query.

    V13 stores routing, depot, capacity, duration and time-window semantics,
    but has no ReSETP extension fields for these five business mechanisms.
    """
    return [
        {
            "phase_index": phase_index,
            "expert": expert,
            "queried": True,
            "applicable": False,
            "action_count": 0,
            "reason": "required_resetp_semantics_absent_from_v13",
        }
        for expert in EXPERTS
    ]
