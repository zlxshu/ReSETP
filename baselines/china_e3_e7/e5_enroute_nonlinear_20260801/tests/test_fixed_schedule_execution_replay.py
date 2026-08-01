from __future__ import annotations

from dataclasses import asdict

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.run_fixed_schedule_execution_replay import (
    ALLOWED_ACTION_CHANGES,
    frozen_action_hash,
    retime_action,
    route_hash,
)
from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.runtime_overlay import (
    M17_22KW_NORMAL_PWL,
)
from setp_solver.solution import ChargingAction, Route, Solution


def test_execution_replay_changes_only_duration_and_curve() -> None:
    source = Solution(
        routes=[Route("EV1", "ev", "D0", ["D0", "S0", "C1", "D0"])],
        charging_actions=[
            ChargingAction(
                "EV1",
                "S0",
                4.0,
                4.0 * 60.0 / 22.0,
                12_345.0,
                0,
                12.0,
                16.0,
                "L100_control",
            )
        ],
    )
    before = source.charging_actions[0]
    after = retime_action(
        before,
        M17_22KW_NORMAL_PWL.scale(
            capacity_kwh=20.0, reference_power_kw=22.0
        ),
    )
    replay = Solution(routes=source.routes, charging_actions=[after])

    assert route_hash(replay) == route_hash(source)
    assert frozen_action_hash(replay) == frozen_action_hash(source)
    changed = {
        key
        for key, value in asdict(before).items()
        if value != asdict(after)[key]
    }
    assert changed == ALLOWED_ACTION_CHANGES
    assert after.occupancy_minutes > before.occupancy_minutes
