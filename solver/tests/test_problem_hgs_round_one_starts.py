"""第 1 轮多起点与两个代理锚点的冻结（2026-09-08）。

两件事各自一个开关，各自可以单独关掉：

* ``round_one_starts``：第 1 轮独立起跑 K 次，按内核自己的轮内可行代理最优
  （``kernel_best_cost``）取最好的那一次继续，其余起点连一次完整精确评价都不
  付。K==1 ＝ 改动前的行为。
* ``frozen_reload_gap_seconds`` / ``frozen_first_trip_window_open_second``：把
  两个路线无关锚点钉死，整次运算每一轮同一个值。两者都是 None ＝ 改动前的行为。

"与改动前逐位相同"这件事在这里只能用它的唯一成因来证：内核由 ``SystemRandom``
播种，两次跑不可能自然重放。所以这里验的是（a）K==1 时轮循环记的东西与单起点
一致、（b）K>1 时选中的起点确实是代理最优的那一个、（c）冻结后每轮拿到的预留
逐位相同。改动前后的整跑哈希比对是离线做的一次性实测，记在
docs/handoff/multistart_build_20260908.md。
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
    PROXY_ESTIMATE_SOURCE_DEFAULT,
    PROXY_ESTIMATE_SOURCES,
    PROXY_REFERENCE_FIRST_TRIP_WINDOW_OPEN_SECOND,
    PROXY_REFERENCE_RELOAD_GAP_SECONDS,
    ROUND_ONE_STARTS_DEFAULT,
    _build_context,
    _parameters,
    _policy,
)
from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator  # noqa: E402
from setp_solver.algorithms.problem_hgs.kernel_proposals import (  # noqa: E402
    IndependentKernelDutyRouteProposalEngine,
    population_first_trip_window_open_second,
    population_inter_trip_reload_seconds,
)
from setp_solver.algorithms.problem_hgs.runner import (  # noqa: E402
    ROUND_ONE_STARTS,
    ProblemHGSSearchParameters,
    max_improvement_gap,
    run_kernel_native_problem_hgs,
)


_FIXTURE_PATIENCE = 300


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


def _run(formal, engine_kwargs=None, **kwargs):
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
            ev_charge_time_proxy_enabled=False,
            ev_reload_gap_proxy_enabled=True,
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
        stop=lambda _state: False,
        arm="round-one-starts-test",
        route_engine=make_engine(**(engine_kwargs or {})),
        route_engine_factory=make_engine,
        initial_evaluations=(reference,) * 4,
        charging_prescreen_enabled=True,
        include_charging_candidates=False,
        confirming_round=True,
        confirming_patience_floor=50,
        **kwargs,
    )


# --------------------------------------------------------------------------
# 纯参数校验
# --------------------------------------------------------------------------


def test_library_default_is_one_start():
    """库内默认必须是 1：调用方不明说就走改动前的行为。"""

    assert ROUND_ONE_STARTS == 1


@pytest.mark.parametrize("bad", [0, -1])
def test_round_one_starts_must_be_at_least_one(formal, bad):
    with pytest.raises(ValueError, match="round-one-starts"):
        _run(formal, round_one_starts=bad)


# --------------------------------------------------------------------------
# 第 1 轮多起点
# --------------------------------------------------------------------------


def test_one_start_records_exactly_one_start_and_that_start_is_the_round(formal):
    """K==1：起点记账只有一条，而且它就是第 1 轮本身。

    这是"K==1 ＝ 改动前行为"在盘上留下的痕迹：第 1 轮的圈数、改善次数、代理
    最优三项，与那唯一一个起点逐位相同；没有任何一次内核搜索被丢掉，因此
    总圈数仍等于各轮圈数之和。
    """

    result = _run(formal, round_one_starts=1)
    accounting = result.accounting
    assert accounting.round_one_starts == 1
    assert len(accounting.round_one_start_summaries) == 1
    only = accounting.round_one_start_summaries[0]
    assert only["start"] == 1
    assert only["selected"] is True

    round_one = accounting.kernel_round_summaries[0]
    assert only["iterations"] == round_one["iterations"]
    assert only["improvements"] == round_one["improvements"]
    assert only["kernel_best_cost"] == round_one["kernel_best_cost"]
    assert result.iterations == sum(
        int(summary["iterations"])
        for summary in accounting.kernel_round_summaries
    )
    assert accounting.frozen_reload_gap_seconds is None
    assert accounting.frozen_first_trip_window_open_second is None


def test_three_starts_keep_the_lowest_kernel_proxy_best(formal):
    """K==3：选中的起点在内核自己的记分牌上不差于其余起点。

    另外两条要一起验，否则多起点会顺手把别的旋钮也拧了：
    * 第 1 轮报出去的那一轮就是选中的那个起点（不是最后一个跑完的）；
    * ``round1_max_improvement_gap`` 只由选中起点的改善轨迹算出——落选起点的
      一段长等待若混进来，后续每一轮的耐心值都会被悄悄抬高。
    """

    result = _run(formal, round_one_starts=3)
    accounting = result.accounting
    summaries = accounting.round_one_start_summaries
    assert accounting.round_one_starts == 3
    assert len(summaries) == 3
    assert [summary["start"] for summary in summaries] == [1, 2, 3]
    assert sum(1 for summary in summaries if summary["selected"]) == 1

    winner = next(summary for summary in summaries if summary["selected"])
    assert winner["kernel_best_cost"] is not None
    for summary in summaries:
        if summary["kernel_best_cost"] is not None:
            assert winner["kernel_best_cost"] <= summary["kernel_best_cost"]

    round_one = accounting.kernel_round_summaries[0]
    assert round_one["iterations"] == winner["iterations"]
    assert round_one["kernel_best_cost"] == winner["kernel_best_cost"]

    # 落选起点的圈数是真花掉的时间，进总圈数；每轮记账只记赢家。
    assert result.iterations > sum(
        int(summary["iterations"])
        for summary in accounting.kernel_round_summaries
    )
    assert result.iterations == sum(
        int(summary["iterations"]) for summary in summaries
    ) + sum(
        int(summary["iterations"])
        for summary in accounting.kernel_round_summaries[1:]
    )

    # 后续轮的耐心标定量只看赢家的轨迹。
    winner_events = [
        int(event["iteration"])
        for event in accounting.improvement_events
        if int(event["round"]) == 1
    ]
    assert accounting.round1_max_improvement_gap == max_improvement_gap(
        winner_events
    )
    assert len(winner_events) == int(winner["improvements"])

    assert result.best_evaluation.feasible
    assert not result.best.unserved_customers


# --------------------------------------------------------------------------
# 两个锚点的冻结
# --------------------------------------------------------------------------


def test_frozen_reload_gap_is_the_same_number_in_every_round(formal):
    """冻结后每一轮拿到的趟间预留逐位相同，而且就是传进去的那个数。

    未冻结时这个数每轮按上一轮的精确最优重估，第 2 轮起因此换题；冻结的意义
    就在于把这一层跑内变化和跑间变化一起去掉。
    """

    frozen = float(PROXY_REFERENCE_RELOAD_GAP_SECONDS)
    opening = float(PROXY_REFERENCE_FIRST_TRIP_WINDOW_OPEN_SECOND)
    result = _run(
        formal,
        # 第 1 轮的引擎也要拿冻结值——正式入口正是这样接的（先按常数重建引擎，
        # 再把同一个数交给轮循环）。
        engine_kwargs={
            "ev_reload_gap_seconds": frozen,
            "first_trip_window_open_second": opening,
        },
        round_one_starts=1,
        frozen_reload_gap_seconds=frozen,
        frozen_first_trip_window_open_second=opening,
    )
    accounting = result.accounting
    gaps = accounting.reload_gap_seconds_by_round
    assert len(gaps) == accounting.rounds
    assert gaps == [frozen] * accounting.rounds
    assert accounting.frozen_reload_gap_seconds == frozen
    assert accounting.frozen_first_trip_window_open_second == opening
    assert result.best_evaluation.feasible


# --------------------------------------------------------------------------
# 正式入口：常数从哪来，默认是什么
# --------------------------------------------------------------------------


def test_the_reference_solution_carries_neither_statistic(formal):
    """常数不是"参照解自己的统计量"——参照解上两个估计器都没有数可给。

    这条测试把 2026-09-08 那次离线核验钉进仓库：本入口的参照解是纯燃油的，
    既没有趟间充电会话，也没有电动行程，两个估计器都返回 None。所以
    ``--proxy-estimate-source reference`` 只能取全批共用常数；若哪天参照解变成
    含电动车的解，这条测试会红，届时"从参照解估"才重新成为一个选项。
    """

    _bundle, initial, _context, evaluator, _policy_ = formal
    evaluation = evaluator.evaluate(initial)
    assert population_inter_trip_reload_seconds((initial,), quantile=0.75) is None
    assert population_first_trip_window_open_second((evaluation,)) is None


def test_entry_defaults_are_three_starts_and_the_shared_constants():
    assert ROUND_ONE_STARTS_DEFAULT == 3
    assert PROXY_ESTIMATE_SOURCE_DEFAULT == "reference"
    assert set(PROXY_ESTIMATE_SOURCES) == {"population", "reference"}
    # 常数落在四臂 40 跑实测到的窗口里，不是窗口外的一个新值。
    assert 1348.0 <= PROXY_REFERENCE_RELOAD_GAP_SECONDS <= 2117.4
    assert 55618.6 <= PROXY_REFERENCE_FIRST_TRIP_WINDOW_OPEN_SECOND <= 58731.7
