from __future__ import annotations

# ruff: noqa: E402

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from micro_cases import conflict_micro_route
from prototype import (
    PiecewiseLinearCurve,
    PrototypeContractError,
    exhaustive_oracle,
    label_oracle,
    plan_fingerprint,
    replay_plan,
)


@pytest.mark.parametrize("budget", [0, 1, 2, 5])
def test_budget_prefix_matches_exhaustive_pointwise(budget: int) -> None:
    case = conflict_micro_route()
    exhaustive = exhaustive_oracle(case, budget=budget)
    labels = label_oracle(case, budget=budget, dominance=False)
    assert labels.complete_evaluations == exhaustive.complete_evaluations == budget
    assert labels.feasible_evaluations == exhaustive.feasible_evaluations
    assert plan_fingerprint(labels.best, digits=9) == plan_fingerprint(
        exhaustive.best, digits=9
    )


def test_unlimited_label_oracle_matches_exhaustive_with_dominance() -> None:
    case = conflict_micro_route()
    exhaustive = exhaustive_oracle(case, budget=None)
    labels = label_oracle(case, budget=None, dominance=True)
    assert labels.dominance_prunes > 0
    assert plan_fingerprint(labels.best, digits=9) == plan_fingerprint(
        exhaustive.best, digits=9
    )


def test_replay_closes_time_soc_segments_and_signals() -> None:
    case = conflict_micro_route()
    best = exhaustive_oracle(case, budget=None).best
    assert best is not None and best.feasible
    assert best.terminal_soc_kwh >= case.terminal_min_soc_kwh
    assert len(best.charge_traces) == 2
    assert any(
        len(
            [
                energy
                for energy in trace.slot_energy_kwh
                if energy > case.comparison_tolerance
            ]
        )
        >= 2
        for trace in best.charge_traces
    )
    assert any(
        trace.start_soc_kwh < 6.0 < trace.end_soc_kwh
        for trace in best.charge_traces
    )
    for trace in best.charge_traces:
        assert sum(trace.slot_energy_kwh) == pytest.approx(
            trace.end_soc_kwh - trace.start_soc_kwh, abs=1e-9
        )
        assert trace.finish_time_seconds - trace.start_time_seconds == pytest.approx(
            trace.duration_seconds, abs=1e-9
        )
    replayed = replay_plan(case, best.actions, plan_index=best.plan_index)
    assert plan_fingerprint(replayed, digits=9) == plan_fingerprint(best, digits=9)


def test_price_and_carbon_signals_are_both_active() -> None:
    case = conflict_micro_route()
    results = [
        replay_plan(case, actions, plan_index=index)
        for index, actions in enumerate(
            __import__("prototype").enumerate_action_plans(case)
        )
    ]
    feasible = [result for result in results if result.feasible]
    assert len({round(result.price_cost, 9) for result in feasible}) > 1
    assert len({round(result.carbon_amount, 9) for result in feasible}) > 1
    cheapest = min(feasible, key=lambda result: (result.price_cost, result.plan_index))
    cleanest = min(feasible, key=lambda result: (result.carbon_amount, result.plan_index))
    assert cheapest.plan_index != cleanest.plan_index


def test_no_formal_discretization_or_weight_defaults() -> None:
    with pytest.raises(TypeError):
        PiecewiseLinearCurve()  # type: ignore[call-arg]
    with pytest.raises(PrototypeContractError):
        PiecewiseLinearCurve((0.0, 5.0), (0.0,))


def test_finite_budget_rejects_dominance_to_preserve_prefix_contract() -> None:
    with pytest.raises(PrototypeContractError):
        label_oracle(conflict_micro_route(), budget=5, dominance=True)
