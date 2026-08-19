"""Solution JSON conversion retained by active Problem-HGS runners."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..solution import (
    CrossSiteService,
    Route,
    Solution,
    charging_action_from_dict,
)


def solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [
            asdict(action) for action in solution.charging_actions
        ],
        "cross_site_services": [
            asdict(item) for item in solution.cross_site_services
        ],
    }


def solution_from_dict(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                str(row["vehicle_id"]),
                str(row["vehicle_type"]),
                str(row["home_depot_id"]),
                [str(node) for node in row["node_sequence"]],
            )
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            charging_action_from_dict(row)
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                str(row["customer_id"]),
                str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )
