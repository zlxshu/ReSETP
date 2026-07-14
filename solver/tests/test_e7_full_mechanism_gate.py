from __future__ import annotations

import pytest

from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as gate
from setp_solver.solution import ChargingAction, Route, Solution


def test_participation_floor_rejects_one_depot_loss_and_accepts_two_nonlosses() -> None:
    baseline = {"D0": 100.0, "D1": 80.0}

    assert gate._meets_participation_floor(
        {"D0": 100.0, "D1": 81.0}, baseline
    )
    assert not gate._meets_participation_floor(
        {"D0": 99.0, "D1": 90.0}, baseline
    )


def test_participation_floor_stops_on_nonpositive_baseline() -> None:
    with pytest.raises(RuntimeError, match="non-positive"):
        gate._meets_participation_floor(
            {"D0": 1.0, "D1": 2.0},
            {"D0": 0.0, "D1": 2.0},
        )


def test_execution_ledger_keeps_charge_locked_before_its_route() -> None:
    route = Route("EV_D0_1#T2", "ev", "D0", ["D0", "C1", "D0"])
    action = ChargingAction("EV_D0_1#T2", "D0", 10.0, 30.0, 1_000.0)

    merged = gate._merge_execution_plan(
        {},
        {gate.base.action_key(action): action},
        Solution(routes=[route]),
    )

    assert merged.routes == [route]
    assert merged.charging_actions == [action]


def test_execution_ledger_keeps_two_distinct_charges_before_one_trip() -> None:
    route = Route("EV_D0_1#T2", "ev", "D0", ["D0", "C1", "D0"])
    first = ChargingAction("EV_D0_1#T2", "D0", 10.0, 30.0, 1_000.0)
    second = ChargingAction("EV_D0_1#T2", "D0", 10.0, 30.0, 2_000.0)

    merged = gate._merge_execution_plan(
        {},
        {
            gate.base.action_key(first): first,
            gate.base.action_key(second): second,
        },
        Solution(routes=[route]),
    )

    assert merged.charging_actions == [first, second]
