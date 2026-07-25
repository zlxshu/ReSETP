from __future__ import annotations

import pytest
from split_core import (
    ResourceLimitError,
    SegmentChoice,
    solve_resource_constrained_split,
)


def choice(
    start: int,
    end: int,
    cost: float,
    *,
    fleet: tuple[int, ...] = (1,),
    charger: tuple[tuple[str, int, int, int], ...] = (),
) -> SegmentChoice:
    return SegmentChoice(
        start=start,
        end=end,
        cost=cost,
        fleet_delta=fleet,
        charger_delta=charger,
        payload=(start, end, cost),
    )


def test_split_matches_exhaustive_small_fixture() -> None:
    choices = {
        0: (choice(0, 1, 4), choice(0, 2, 5)),
        1: (choice(1, 2, 2), choice(1, 3, 8)),
        2: (choice(2, 3, 1),),
    }
    result = solve_resource_constrained_split(
        3,
        choices,
        fleet_caps=(3,),
        charger_caps={},
    )
    paths = [
        (choices[0][0], choices[1][0], choices[2][0]),
        (choices[0][0], choices[1][1]),
        (choices[0][1], choices[2][0]),
    ]
    exhaustive = min(sum(item.cost for item in path) for path in paths)
    assert result.cost == exhaustive == 6
    assert [(item.start, item.end) for item in result.choices] == [
        (0, 2),
        (2, 3),
    ]


def test_fleet_and_shared_charger_conflicts_are_rejected() -> None:
    slot = (("S", 0, 4, 1),)
    choices = {
        0: (
            choice(0, 1, 1, fleet=(1, 0), charger=slot),
            choice(0, 1, 3, fleet=(0, 1)),
        ),
        1: (
            choice(1, 2, 1, fleet=(1, 0), charger=slot),
            choice(1, 2, 3, fleet=(0, 1)),
        ),
    }
    result = solve_resource_constrained_split(
        2,
        choices,
        fleet_caps=(2, 2),
        charger_caps={"S": 1},
    )
    assert result.cost == 4
    assert result.fleet_use == (1, 1)


def test_dominance_keeps_more_expensive_but_resource_lighter_label() -> None:
    choices = {
        0: (
            choice(0, 1, 1, fleet=(1, 0)),
            choice(0, 1, 2, fleet=(0, 1)),
        ),
        1: (choice(1, 2, 1, fleet=(1, 0)),),
    }
    result = solve_resource_constrained_split(
        2,
        choices,
        fleet_caps=(1, 1),
        charger_caps={},
    )
    assert result.cost == 3
    assert result.fleet_use == (1, 1)


def test_safety_limit_fails_closed_without_beam_pruning() -> None:
    choices = {
        0: (
            choice(0, 1, 1, fleet=(1, 0)),
            choice(0, 1, 1, fleet=(0, 1)),
        )
    }
    with pytest.raises(ResourceLimitError):
        solve_resource_constrained_split(
            1,
            choices,
            fleet_caps=(1, 1),
            charger_caps={},
            max_labels_per_position=1,
        )
