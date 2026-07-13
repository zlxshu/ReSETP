from __future__ import annotations

from dataclasses import asdict

import pytest

from setp_solver.search import (
    alns_crush,
    alns_crush_v2,
    alns_crush_v3,
    formal_runner,
    metaheuristic_baselines,
    winner_restoration,
)
from setp_solver.solution import ChargingAction, Route, Solution


LOADERS = (
    alns_crush._solution_from_dict,
    alns_crush_v2._solution_from_dict,
    alns_crush_v3.solution_from_dict,
    formal_runner._solution_from_dict,
    metaheuristic_baselines.solution_from_dict,
    winner_restoration._solution_from_dict,
)


def _payload(*, include_day_offset: bool) -> dict[str, object]:
    solution = Solution(
        routes=[Route("EV1#T1", "ev", "D0", ["D0", "C1", "D0"])],
        charging_actions=[ChargingAction("EV1#T1", "D0", 8.0, 30.0, 3_600.0, -1)],
    )
    action = asdict(solution.charging_actions[0])
    if not include_day_offset:
        action.pop("charge_day_offset")
    return {
        "routes": [asdict(solution.routes[0])],
        "charging_actions": [action],
        "cross_site_services": [],
    }


@pytest.mark.parametrize("loader", LOADERS)
def test_solution_loaders_preserve_pre_horizon_charge_day(loader) -> None:
    loaded = loader(_payload(include_day_offset=True))

    assert loaded.charging_actions[0].charge_day_offset == -1


@pytest.mark.parametrize("loader", LOADERS)
def test_solution_loaders_keep_legacy_default(loader) -> None:
    loaded = loader(_payload(include_day_offset=False))

    assert loaded.charging_actions[0].charge_day_offset == 0
