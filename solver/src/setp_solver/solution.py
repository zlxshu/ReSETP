from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


VEHICLE_TRIP_SEPARATOR = "#T"


def physical_vehicle_id(vehicle_id: str) -> str:
    """Return the physical vehicle id behind a route/trip id.

    ``CV1#T2`` means the second trip served by physical vehicle ``CV1``. The
    full id stays unique so charging actions remain tied to one trip and do
    not bleed into another trip's battery ledger.
    """

    return str(vehicle_id).split(VEHICLE_TRIP_SEPARATOR, 1)[0]


def route_trip_vehicle_id(base_vehicle_id: str, trip_index: int) -> str:
    """Build a route/trip id for one physical vehicle's dispatch."""

    return f"{base_vehicle_id}{VEHICLE_TRIP_SEPARATOR}{int(trip_index)}"


@dataclass(frozen=True)
class Route:
    vehicle_id: str
    vehicle_type: str
    home_depot_id: str
    node_sequence: list[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "vehicle_type", self.vehicle_type.lower())


@dataclass(frozen=True)
class ChargingAction:
    vehicle_id: str
    station_id: str
    energy_kwh: float
    occupancy_minutes: float
    charge_start_second: float
    charge_day_offset: int = 0
    start_energy_kwh: float | None = None
    end_energy_kwh: float | None = None
    charging_curve_id: str | None = None


def charging_action_from_dict(row: Mapping[str, Any]) -> ChargingAction:
    """Load both historical six-field and current curve-aware actions."""

    return ChargingAction(
        vehicle_id=str(row["vehicle_id"]),
        station_id=str(row["station_id"]),
        energy_kwh=float(row["energy_kwh"]),
        occupancy_minutes=float(row["occupancy_minutes"]),
        charge_start_second=float(row["charge_start_second"]),
        charge_day_offset=int(row.get("charge_day_offset", 0)),
        start_energy_kwh=(
            None
            if row.get("start_energy_kwh") is None
            else float(row["start_energy_kwh"])
        ),
        end_energy_kwh=(
            None
            if row.get("end_energy_kwh") is None
            else float(row["end_energy_kwh"])
        ),
        charging_curve_id=(
            None
            if row.get("charging_curve_id") is None
            else str(row["charging_curve_id"])
        ),
    )


@dataclass(frozen=True)
class CrossSiteService:
    customer_id: str
    served_by_depot_id: str


@dataclass(frozen=True)
class Solution:
    routes: list[Route] = field(default_factory=list)
    charging_actions: list[ChargingAction] = field(default_factory=list)
    cross_site_services: list[CrossSiteService] = field(default_factory=list)
