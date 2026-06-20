from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Route:
    vehicle_id: str
    vehicle_type: str
    home_depot_id: str
    node_sequence: list[str]


@dataclass(frozen=True)
class ChargingAction:
    vehicle_id: str
    station_id: str
    energy_kwh: float
    occupancy_minutes: float
    charge_start_second: float


@dataclass(frozen=True)
class CrossSiteService:
    customer_id: str
    served_by_depot_id: str


@dataclass(frozen=True)
class Solution:
    routes: list[Route] = field(default_factory=list)
    charging_actions: list[ChargingAction] = field(default_factory=list)
    cross_site_services: list[CrossSiteService] = field(default_factory=list)
