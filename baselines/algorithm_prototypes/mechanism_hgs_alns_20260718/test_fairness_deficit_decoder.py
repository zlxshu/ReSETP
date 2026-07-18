"""Real-evaluator binding test for the deficit-directed fairness decoder."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from fairness_deficit_decoder import (
    evaluate_fairness_state,
    profit_floor_repair_decode,
)
from prototype import run_pure_alns
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.search.fairness import run_independent_profit_baselines


ROOT = Path(__file__).resolve().parents[3]
BUNDLE = (
    ROOT
    / "models/data_bundle/generated_instances/L-main"
    / "L-main-threeshift-20c-01"
)


def test_profit_floor_repair_is_binding_and_budget_separate() -> None:
    bundle = load_search_bundle(BUNDLE)
    owners = infer_customer_home_depots(bundle.instance)
    independent_runs: dict[int, dict[str, float]] = {}
    with TemporaryDirectory() as temporary:
        for seed in (1, 2, 3):
            report = run_independent_profit_baselines(
                BUNDLE,
                Path(temporary) / f"independent_profit_seed{seed}.json",
                eval_budget=100,
                max_runtime_seconds=60.0,
                seed=seed,
                prices=DEFAULT_PRICES,
                force=True,
            )
            independent_runs[seed] = report["independent_profit"]
    independent_profit = {
        depot_id: max(
            independent_runs[seed][depot_id] for seed in (1, 2, 3)
        )
        for depot_id in independent_runs[1]
    }
    base = run_pure_alns(
        BUNDLE,
        seed=1,
        eval_budget=100,
        prices=DEFAULT_PRICES,
    )
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=DEFAULT_PRICES,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    theta = 1.0
    initial = evaluate_fairness_state(
        base.best_solution,
        context,
        owners=owners,
        independent_profit=independent_profit,
        theta=theta,
    )
    repaired, activity = profit_floor_repair_decode(
        base.best_solution,
        context,
        owners=owners,
        independent_profit=independent_profit,
        theta=theta,
    )

    assert base.evaluations == 100
    assert initial.total_shortfall > 0.0
    assert not initial.fairness_satisfied
    assert repaired.fairness_satisfied
    assert repaired.minimum_profit_ratio >= theta - 1.0e-9
    assert repaired.system_cost > initial.system_cost
    assert activity["complete_route_search_evaluations"] == 0
    assert activity["profit_ledger_evaluations"] > 0
    assert activity["exact_decoder_updates"] >= 1
    assert activity["fairness_satisfied"]
    assert activity["cost_premium_percent"] == pytest.approx(
        100.0 * (repaired.system_cost / initial.system_cost - 1.0),
    )

    nonbinding_base = run_pure_alns(
        BUNDLE,
        seed=2,
        eval_budget=100,
        prices=DEFAULT_PRICES,
    )
    nonbinding_initial = evaluate_fairness_state(
        nonbinding_base.best_solution,
        context,
        owners=owners,
        independent_profit=independent_profit,
        theta=theta,
    )
    nonbinding_replay, nonbinding_activity = (
        profit_floor_repair_decode(
            nonbinding_base.best_solution,
            context,
            owners=owners,
            independent_profit=independent_profit,
            theta=theta,
        )
    )
    assert nonbinding_initial.fairness_satisfied
    assert nonbinding_replay.fairness_satisfied
    assert nonbinding_replay.system_cost == pytest.approx(
        nonbinding_initial.system_cost
    )
    assert nonbinding_activity["fairness_satisfied"]
    assert nonbinding_activity["exact_decoder_updates"] == 0
    assert nonbinding_activity["profit_ledger_evaluations"] == 0
    assert (
        nonbinding_activity["stop_reason"]
        == "profit_floor_already_satisfied"
    )
