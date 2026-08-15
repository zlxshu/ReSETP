"""Exact charging prescreen and trajectory-off regression tests."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import _build_context, _policy  # noqa: E402
from setp_solver.algorithms.problem_hgs.charging import (  # noqa: E402
    ChargingFeasibilityPrescreen,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
)
from setp_solver.algorithms.problem_hgs.operators import (  # noqa: E402
    RelocateMove,
)
from setp_solver.algorithms.problem_hgs.runner import (  # noqa: E402
    _TrajectoryRecorder,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402


INSTANCE_ID = "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS"


@pytest.fixture(scope="module")
def combat_input():
    repo = Path(__file__).parents[2]
    _bundle, initial, _pi0, context = _build_context(
        repo,
        INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
        depot_charging_scenario_name="60kw",
    )
    context = replace(context, depot_charge_window_mode="full_gap")
    evaluator = DutyFullEvaluator(context)
    return initial, context, _policy(
        evaluator,
        first_trip_prev_night_enabled=True,
    )


@pytest.mark.parametrize(
    ("target_trip", "target_position", "expected"),
    (
        (1, 0, "has no feasible departure time"),
        (2, 1, "misses C032's time window"),
    ),
)
def test_prescreen_reuses_exact_full_repair_rejection(
    combat_input,
    target_trip,
    target_position,
    expected,
):
    initial, context, policy = combat_input
    move = RelocateMove(
        action_id=f"prescreen-{target_trip}-{target_position}",
        channel="depot_collaboration",
        source_duty_id="CV_D_foshan_2",
        source_trip_index=1,
        customer_id="C032",
        target_duty_id="CV_D_guangzhou_1",
        target_trip_index=target_trip,
        target_position=target_position,
    )
    candidate = move.apply(initial)
    prescreen = ChargingFeasibilityPrescreen(
        context,
        policy,
        audit_limit=1,
    )

    failure = prescreen.screen(
        initial,
        candidate,
        changed_duty_ids=move.changed_duty_ids,
        channel=move.channel,
    )

    assert failure is not None
    assert expected in str(failure)
    assert prescreen.statistics()["audit"] == {
        "requested_limit": 1,
        "sampled": 1,
        "same_rejection": 1,
        "prescreen_false_rejections": 0,
    }


def test_prescreen_does_not_touch_other_channels(combat_input):
    initial, context, policy = combat_input
    move = RelocateMove(
        action_id="non-target-channel",
        channel="route_kernel",
        source_duty_id="CV_D_foshan_2",
        source_trip_index=1,
        customer_id="C032",
        target_duty_id="CV_D_guangzhou_1",
        target_trip_index=1,
        target_position=0,
    )
    prescreen = ChargingFeasibilityPrescreen(context, policy)

    assert prescreen.screen(
        initial,
        move.apply(initial),
        changed_duty_ids=move.changed_duty_ids,
        channel=move.channel,
    ) is None
    assert prescreen.statistics()["eligible_candidates"] == 0


def test_trajectory_recorder_can_drop_all_rows():
    recorder = _TrajectoryRecorder(None, retain=False)

    recorder.emit_many(())

    assert recorder.retained == []
