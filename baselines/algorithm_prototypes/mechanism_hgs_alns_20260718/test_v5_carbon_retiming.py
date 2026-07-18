from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
for path in (REPO / "solver/src", HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.evaluation import EvalBudget, EvaluationContext  # noqa: E402
from setp_solver.solution import ChargingAction, Route, Solution  # noqa: E402
from v5_carbon_retiming_solver import (  # noqa: E402
    carbon_aware_depot_retime,
    depot_charge_candidate_starts,
)


BUNDLE = (
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-20c-01"
)
PLATEAU_COST = 621.2913242409613


def _plateau_solution() -> Solution:
    return Solution(
        routes=[
            Route(
                "EV1#T1",
                "ev",
                "D1",
                [
                    "D1",
                    "C001",
                    "C006",
                    "C004",
                    "C002",
                    "C012",
                    "C015",
                    "C013",
                    "D1",
                ],
            ),
            Route(
                "EV1#T2",
                "ev",
                "D0",
                [
                    "D0",
                    "C003",
                    "C011",
                    "C018",
                    "C016",
                    "C010",
                    "C017",
                    "C014",
                    "D0",
                ],
            ),
            Route(
                "CV1#T1",
                "cv",
                "D0",
                [
                    "D0",
                    "C008",
                    "C009",
                    "C005",
                    "C007",
                    "C020",
                    "C019",
                    "D0",
                ],
            ),
        ],
        charging_actions=[
            ChargingAction(
                "EV1#T2",
                "D0",
                199.23734894483937,
                543.3745880313801,
                54000.0,
            ),
            ChargingAction(
                "EV1#T1",
                "D1",
                126.15083488573185,
                344.0477315065415,
                39600.0,
            ),
        ],
    )


def test_breakpoints_include_window_and_shifted_boundaries() -> None:
    starts = depot_charge_candidate_starts(
        earliest_start=1000.0,
        latest_start=8000.0,
        occupancy_seconds=2500.0,
        current_start=2000.0,
    )
    assert starts[0] == 1000.0
    assert starts[-1] == 8000.0
    assert 1800.0 in starts
    assert 3600.0 - 2500.0 in starts


def test_retime_falsifies_the_20c_plateau_with_one_complete_score() -> None:
    bundle = load_search_bundle(BUNDLE)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
    original = _plateau_solution()
    assert not check_solution(original, bundle.instance, prices)
    budget = EvalBudget(limit=1, target=1)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=budget,
    )
    improved, objective, activity = carbon_aware_depot_retime(
        original,
        context,
        incumbent_objective=PLATEAU_COST,
    )
    assert budget.count == 1
    assert activity["complete_evaluations"] == 1
    assert activity["actions_retimed"] == 2
    assert activity["improvements"] == 1
    assert objective < PLATEAU_COST - 1.0e-6
    assert abs(objective - 621.0831141941019) <= 1.0e-7
    assert not check_solution(improved, bundle.instance, prices)


def test_zero_complete_budget_is_a_hard_stop() -> None:
    bundle = load_search_bundle(BUNDLE)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
    original = _plateau_solution()
    budget = EvalBudget(limit=0, target=0)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=budget,
    )
    returned, objective, activity = carbon_aware_depot_retime(
        original,
        context,
        incumbent_objective=PLATEAU_COST,
    )
    assert returned == original
    assert objective == PLATEAU_COST
    assert budget.count == 0
    assert activity["stop_reason"] == "no_complete_evaluation_budget"


def test_exact_decoder_uses_no_complete_search_evaluation() -> None:
    bundle = load_search_bundle(BUNDLE)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
    original = _plateau_solution()
    budget = EvalBudget(limit=0, target=0)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=budget,
    )
    improved, objective, activity = carbon_aware_depot_retime(
        original,
        context,
        incumbent_objective=PLATEAU_COST,
        consume_complete_evaluation=False,
    )
    assert budget.count == 0
    assert activity["complete_evaluations"] == 0
    assert activity["exact_decoder_updates"] == 1
    assert activity["improvements"] == 1
    assert abs(objective - 621.0831141941019) <= 1.0e-7
    assert not check_solution(improved, bundle.instance, prices)
