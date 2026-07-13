from __future__ import annotations

from setp_solver.solution import ChargingAction, Route, Solution

from baselines.e6_fairness.e6_participation_formal_20260714 import (
    depot_caps,
    dominance_closed_rows,
    extract_depot_start,
    merge_depot_solutions,
)


def _sample_solution() -> Solution:
    return Solution(
        routes=[
            Route("CV_D0_1#T1", "cv", "D0", ["D0", "C0", "D0"]),
            Route("EV_D1_1#T1", "ev", "D1", ["D1", "C1", "D1"]),
        ],
        charging_actions=[
            ChargingAction("EV_D1_1#T1", "D1", 10.0, 30.0, 0.0, -1),
        ],
    )


def test_extract_depot_start_keeps_only_linked_routes_and_charging() -> None:
    source = _sample_solution()
    d0 = extract_depot_start(source, "D0")
    d1 = extract_depot_start(source, "D1")
    assert [route.vehicle_id for route in d0.routes] == ["CV_D0_1#T1"]
    assert d0.charging_actions == []
    assert [route.vehicle_id for route in d1.routes] == ["EV_D1_1#T1"]
    assert [action.vehicle_id for action in d1.charging_actions] == ["EV_D1_1#T1"]


def test_merge_depot_solutions_preserves_unique_trip_links() -> None:
    source = _sample_solution()
    merged = merge_depot_solutions(
        {
            "D0": extract_depot_start(source, "D0"),
            "D1": extract_depot_start(source, "D1"),
        }
    )
    assert [route.vehicle_id for route in merged.routes] == ["CV_D0_1#T1", "EV_D1_1#T1"]
    assert [action.vehicle_id for action in merged.charging_actions] == ["EV_D1_1#T1"]


def test_merge_rejects_duplicate_trip_identifiers() -> None:
    duplicate = Solution(routes=[Route("CV1#T1", "cv", "D0", ["D0", "C0", "D0"])])
    try:
        merge_depot_solutions({"D0": duplicate, "D1": duplicate})
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate trip identifiers must be rejected")


def test_frozen_114_customer_caps_are_condition_invariant_and_close() -> None:
    geographic = depot_caps("L-main-threeshift-50c-01", "geographic")
    mixed = depot_caps("L-main-threeshift-50c-01", "mixed")
    assert geographic == mixed == {
        "D0": {"cv": 3, "ev": 3},
        "D1": {"cv": 2, "ev": 2},
    }
    assert sum(row["cv"] for row in geographic.values()) == 5
    assert sum(row["ev"] for row in geographic.values()) == 5


def test_dominance_closure_respects_nested_feasible_sets() -> None:
    independent = {"arm": "independent", "total_cost": 100.0, "both_depots_no_worse": True}
    unrestricted = {"arm": "unrestricted", "total_cost": 95.0, "both_depots_no_worse": False}
    no_loss = {"arm": "no_loss", "total_cost": 90.0, "both_depots_no_worse": True}
    unrestricted_adopted, no_loss_adopted = dominance_closed_rows(
        independent, unrestricted, no_loss
    )
    assert unrestricted_adopted["arm"] == "no_loss"
    assert no_loss_adopted["arm"] == "no_loss"
