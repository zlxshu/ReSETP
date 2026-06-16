from __future__ import annotations

from dataclasses import asdict
from typing import Any


def solution_to_json(solution: Any) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(item) for item in getattr(solution, "cross_site_services", [])],
    }


def solution_from_json(payload: dict[str, Any] | None) -> Any:
    from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution

    payload = payload or {}

    def rows(key: str) -> list[dict[str, Any]]:
        return list(payload.get(key) or [])

    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[str(node) for node in row["node_sequence"]],
            )
            for row in rows("routes")
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row["vehicle_id"]),
                station_id=str(row["station_id"]),
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(row["charge_start_second"]),
            )
            for row in rows("charging_actions")
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(row["served_by_depot_id"]),
            )
            for row in rows("cross_site_services")
        ],
    )
