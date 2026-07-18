from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for search_path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from run_contextual_expert_p1_training_gate import (  # noqa: E402
    INSTANCES,
    _decision,
    _solution_from_payload,
)
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


def test_solution_payload_round_trip_preserves_all_decisions() -> None:
    solution = Solution(
        routes=[
            Route(
                "EV1#T1",
                "ev",
                "D1",
                ["D1", "C1", "D1"],
            )
        ],
        charging_actions=[
            ChargingAction(
                "EV1#T1",
                "D1",
                12.5,
                30.0,
                3600.0,
                1,
            )
        ],
        cross_site_services=[
            CrossSiteService("C1", "D1")
        ],
    )
    assert _solution_from_payload(asdict(solution)) == solution


def test_frozen_p1_decision_requires_every_gate() -> None:
    rows = []
    for instance in INSTANCES:
        for arm in ("control", "candidate"):
            rows.append(
                {
                    "instance": instance,
                    "arm": arm,
                    "ledger_closed": True,
                    "reference_channel_closed": True,
                    "worker_feasible": True,
                    "parent_feasible": True,
                    "objective_match": True,
                    "terminal_completion_enabled": True,
                    "post_search_full_solution_replays": 5,
                    "terminal_reference_replays": 3,
                    "search_loop_count": 1,
                    "search_restart_count": 0,
                    "mechanism_scope_violation_count": 0,
                    "mechanism_candidate_evaluations": (
                        0 if arm == "control" else 1
                    ),
                    "mechanism_attempt_count": (
                        0 if arm == "control" else 1
                    ),
                }
            )
    comparisons = [
        {
            "instance": instance,
            "same_start": True,
            "strict_win": True,
            "nonloss": True,
            "mechanism_active": True,
            "improvement_percent": 2.0,
            "regression_percent": 0.0,
            "wall_time_ratio": 1.1,
        }
        for instance in INSTANCES
    ]
    passed = _decision(
        rows,
        comparisons,
        p0_preflight={"passed": True},
        drift_failures=[],
    )
    assert passed["passed"] is True

    comparisons[0] = {
        **comparisons[0],
        "strict_win": False,
        "nonloss": False,
        "improvement_percent": -2.0,
        "regression_percent": 2.0,
    }
    stopped = _decision(
        rows,
        comparisons,
        p0_preflight={"passed": True},
        drift_failures=[],
    )
    assert stopped["passed"] is False
    assert (
        stopped["verdict"]
        == "STOP_P1_OLD_THREE_INSTANCE_TRAINING_GATE"
    )
