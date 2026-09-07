"""Kernel-native route-then-charge search returns an exact, feasible answer.

2026-09-03: the kernel searches the route proxy to a no-improvement rule,
the exact model decodes, charges, evaluates and educates its population, the
realised EV price feeds back and the loop stops when a round no longer
improves the exact best.  A short patience keeps the test fast; the numbers
are exact evaluations either way.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    FLEET_PARAMETER_CLASSES,
    _build_context,
    _parameters,
    _policy,
)
from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator  # noqa: E402
from setp_solver.algorithms.problem_hgs.kernel_proposals import (  # noqa: E402
    IndependentKernelDutyRouteProposalEngine,
)
from setp_solver.algorithms.problem_hgs.runner import (  # noqa: E402
    ProblemHGSSearchParameters,
    confirming_round_patience,
    max_improvement_gap,
    run_kernel_native_problem_hgs,
)


@pytest.fixture(scope="module")
def formal():
    repo = Path(__file__).parents[2]
    bundle, initial, _neutral, context = _build_context(
        repo,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
    )
    evaluator = DutyFullEvaluator(context)
    return bundle, initial, context, evaluator, _policy(evaluator)


def test_kernel_native_search_returns_exact_feasible_best(formal):
    _bundle, initial, context, evaluator, policy = formal

    def make_engine(**extra):
        return IndependentKernelDutyRouteProposalEngine(
            context,
            initial,
            stream_role="main_route",
            depot_assignment_operator_enabled=True,
            rebuilt_volume_capacity_enabled=True,
            rebuilt_shift_neighbours_only=True,
            shift_aware_ev_unit_cost_enabled=True,
            **extra,
        )

    base = _parameters()
    parameters = ProblemHGSSearchParameters(
        population=base.population,
        stagnation_patience=300,
        objective_mode=base.objective_mode,
    )
    reference = evaluator.evaluate(initial)
    states = []
    result = run_kernel_native_problem_hgs(
        (initial, initial, initial, initial),
        evaluator=evaluator,
        charging_policy=policy,
        parameters=parameters,
        stop=lambda state: states.append(state) or False,
        arm="kernel-native-test",
        route_engine=make_engine(),
        route_engine_factory=make_engine,
        initial_evaluations=(reference, reference, reference, reference),
        charging_prescreen_enabled=True,
        include_charging_candidates=False,
    )
    assert result.termination_status == "STOPPED_BY_CALLER"
    assert result.best_evaluation.feasible
    assert not result.best.unserved_customers
    assert result.best_evaluation.total_cost <= reference.total_cost + 1e-9
    assert result.iterations >= 300
    assert 1 <= result.accounting.restarts <= 2  # phase 1, optional priced phase 2
    assert states and states[-1].best_feasible_raw_cost == pytest.approx(
        result.best_evaluation.total_cost
    )
    print(
        f"\nkernel-native: best={result.best_evaluation.total_cost:.2f} "
        f"(reference {reference.total_cost:.2f}) rounds={result.accounting.restarts} "
        f"kernel_iterations={result.iterations} wall={result.accounting.run_wall_seconds:.1f}s "
        f"fleet={result.best_evaluation.breakdown['n_veh_cv']}CV/{result.best_evaluation.breakdown['n_veh_ev']}EV"
    )


# --------------------------------------------------------------------------
# 确认轮的耐心值（2026-09-05）。边界情形在
# ``test_confirming_round_patience`` 的纯函数上验；这里只验"规则算出来的那个
# 数确实按轮送进了内核"，因为只有真跑一遍才看得到这一点。夹具的 cap 是 300，
# 所以下限用 50，否则 cap 一律压过下限，adaptive 与 fixed 在夹具上无从区分。
# --------------------------------------------------------------------------


_FIXTURE_PATIENCE = 300
_FIXTURE_FLOOR = 50


def _run_with_patience_mode(formal, mode):
    _bundle, initial, context, evaluator, policy = formal

    def make_engine(**extra):
        return IndependentKernelDutyRouteProposalEngine(
            context,
            initial,
            stream_role="main_route",
            depot_assignment_operator_enabled=True,
            rebuilt_volume_capacity_enabled=True,
            rebuilt_shift_neighbours_only=True,
            shift_aware_ev_unit_cost_enabled=True,
            **extra,
        )

    base = _parameters()
    parameters = ProblemHGSSearchParameters(
        population=base.population,
        stagnation_patience=_FIXTURE_PATIENCE,
        objective_mode=base.objective_mode,
    )
    reference = evaluator.evaluate(initial)
    return run_kernel_native_problem_hgs(
        (initial, initial, initial, initial),
        evaluator=evaluator,
        charging_policy=policy,
        parameters=parameters,
        stop=lambda state: False,
        arm=f"kernel-native-patience-{mode}",
        route_engine=make_engine(),
        route_engine_factory=make_engine,
        initial_evaluations=(reference, reference, reference, reference),
        charging_prescreen_enabled=True,
        include_charging_candidates=False,
        confirming_round_patience_mode=mode,
        confirming_patience_floor=_FIXTURE_FLOOR,
    )


def _iterations_by_round(accounting):
    by_round = {}
    for event in accounting.improvement_events:
        by_round.setdefault(int(event["round"]), []).append(
            int(event["iteration"])
        )
    return {index: sorted(values) for index, values in by_round.items()}


def test_fixed_mode_hands_every_round_the_declared_patience(formal):
    """``fixed`` ＝ 改动前的行为：每轮送进内核的都是 stagnation_patience。

    内核由 ``SystemRandom`` 播种，两次跑不可能逐位重放，所以"与历史逐位相同"
    在这里以其唯一成因来证：轮次循环对搜索的全部影响就是那个整数，而它每轮
    都等于 patience。``stop_semantics_actual`` 也留在历史那句上。
    """

    result = _run_with_patience_mode(formal, "fixed")
    rounds = int(result.accounting.rounds)
    assert rounds >= 1
    assert result.accounting.round_patience_by_round == [
        _FIXTURE_PATIENCE
    ] * rounds
    assert result.accounting.round_patience_mode == "fixed"
    assert result.accounting.stop_semantics_actual == (
        "per-round NoImprovement(patience) x rounds"
    )
    assert result.best_evaluation.feasible
    assert not result.best.unserved_customers


def test_adaptive_mode_sizes_each_round_from_the_measured_gaps(formal):
    result = _run_with_patience_mode(formal, "adaptive")
    accounting = result.accounting
    rounds = int(accounting.rounds)
    assert rounds >= 1
    assert accounting.round_patience_mode == "adaptive"
    assert result.best_evaluation.feasible

    by_round = _iterations_by_round(accounting)
    assert accounting.round1_max_improvement_gap == max_improvement_gap(
        by_round.get(1, [])
    )

    # 规则重算一遍：第 1 轮不动，后续轮吃"迄今所有轮的最长间隔"。
    expected = [_FIXTURE_PATIENCE]
    widest = max_improvement_gap(by_round.get(1, []))
    for index in range(2, rounds + 1):
        expected.append(
            confirming_round_patience(
                widest,
                mode="adaptive",
                floor=_FIXTURE_FLOOR,
                cap=_FIXTURE_PATIENCE,
            )
        )
        widest = max(widest, max_improvement_gap(by_round.get(index, [])))
    assert accounting.round_patience_by_round == expected

    # 参考量只增不减。
    patiences = accounting.round_patience_by_round[1:]
    assert patiences == sorted(patiences)

    # 那个数真的送进了内核：一轮的实跑圈数恒等于"最后一次改善所在圈 + 耐心值"。
    for summary in accounting.kernel_round_summaries:
        index = int(summary["round"])
        events = by_round.get(index, [])
        last = events[-1] if events else 0
        assert int(summary["iterations"]) == (
            last + accounting.round_patience_by_round[index - 1]
        )

    assert accounting.stop_semantics_actual.startswith("round 1: NoImprovement")
    assert "floor 50" in accounting.stop_semantics_actual
    assert "cap 300" in accounting.stop_semantics_actual


# --------------------------------------------------------------------------
# 停机规则：连续 N 轮无改善才停（2026-09-05）。规则本身的穷举等价性在
# ``test_stop_after_nonimproving_rounds`` 的纯函数上验，落盘序列的重放也在那
# 里；这里只验"轮次循环真的按这条规则走"——只有真跑一遍才看得到。
# 夹具的内核由 ``SystemRandom`` 播种，轮数不可预定，所以不断言轮数，断言规则
# 与实跑的改善标记序列相容。
# --------------------------------------------------------------------------


def _run_with_stop_after(formal, stop_after):
    _bundle, initial, context, evaluator, policy = formal

    def make_engine(**extra):
        return IndependentKernelDutyRouteProposalEngine(
            context,
            initial,
            stream_role="main_route",
            depot_assignment_operator_enabled=True,
            rebuilt_volume_capacity_enabled=True,
            rebuilt_shift_neighbours_only=True,
            shift_aware_ev_unit_cost_enabled=True,
            **extra,
        )

    base = _parameters()
    parameters = ProblemHGSSearchParameters(
        population=base.population,
        stagnation_patience=_FIXTURE_PATIENCE,
        objective_mode=base.objective_mode,
    )
    reference = evaluator.evaluate(initial)
    return run_kernel_native_problem_hgs(
        (initial, initial, initial, initial),
        evaluator=evaluator,
        charging_policy=policy,
        parameters=parameters,
        stop=lambda state: False,
        arm=f"kernel-native-stop-after-{stop_after}",
        route_engine=make_engine(),
        route_engine_factory=make_engine,
        initial_evaluations=(reference, reference, reference, reference),
        charging_prescreen_enabled=True,
        include_charging_candidates=False,
        confirming_round=True,
        confirming_patience_floor=_FIXTURE_FLOOR,
        stop_after_nonimproving_rounds=stop_after,
        max_outer_rounds=_FIXTURE_ROUND_CAP,
    )


_FIXTURE_ROUND_CAP = 6


def _assert_no_earlier_round_should_have_stopped(flags, stop_after):
    """规则的单向保证：任何一个更早的轮都不满足停机条件。

    这条断言与轮数是否随机无关，也不受"这一轮不用电所以提前收摊"之类的其他
    出口影响——那些出口只会让跑更早结束，不会让它在规则说停之后还继续。
    """

    streak = 0
    for index, flag in enumerate(flags[:-1], start=1):
        streak = 0 if flag else streak + 1
        assert not (index > 1 and streak >= stop_after), (flags, stop_after)


@pytest.mark.parametrize("stop_after", (1, 2))
def test_the_round_loop_obeys_the_stop_after_rule(formal, stop_after):
    result = _run_with_stop_after(formal, stop_after)
    accounting = result.accounting
    flags = accounting.round_improved_by_round
    assert len(flags) == int(accounting.rounds)
    assert accounting.stop_after_nonimproving_rounds == stop_after
    assert accounting.max_outer_rounds == _FIXTURE_ROUND_CAP
    assert int(accounting.rounds) <= _FIXTURE_ROUND_CAP
    assert result.best_evaluation.feasible
    _assert_no_earlier_round_should_have_stopped(flags, stop_after)
    assert (
        f"stop after {stop_after} consecutive non-improving rounds"
        in accounting.stop_semantics_actual
    )
    # 每个标记都是布尔，不是"没记录"的空位。
    assert all(isinstance(flag, bool) for flag in flags)
