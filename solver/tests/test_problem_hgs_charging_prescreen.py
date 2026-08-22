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
    repair_changed_duties,
)
from setp_solver.algorithms.problem_hgs.education import (  # noqa: E402
    _screen_route_clock,
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










def test_trajectory_recorder_can_drop_all_rows():
    recorder = _TrajectoryRecorder(None, retain=False)

    recorder.emit_many(())

    assert recorder.retained == []
