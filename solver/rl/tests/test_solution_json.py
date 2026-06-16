import json

from dr_alns_ppo.solution_json import solution_from_json, solution_to_json
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution


def test_solution_json_round_trip_preserves_routes_charging_and_cross_site_services() -> None:
    solution = Solution(
        routes=[Route("EV1", "ev", "D0", ["D0", "F1", "C1", "D0"])],
        charging_actions=[ChargingAction("EV1", "F1", 12.5, 15.0, 1800.0)],
        cross_site_services=[CrossSiteService("C1", "D1")],
    )

    payload = json.loads(json.dumps(solution_to_json(solution)))
    restored = solution_from_json(payload)

    assert restored == solution


def test_solution_from_json_none_payload_returns_empty_solution() -> None:
    assert solution_from_json(None) == Solution()


def test_solution_from_json_defaults_missing_or_none_sections_to_empty() -> None:
    assert solution_from_json({}) == Solution()
    assert solution_from_json(
        {
            "routes": None,
            "charging_actions": None,
            "cross_site_services": None,
        }
    ) == Solution()
