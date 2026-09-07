"""「最优方案不用电就不再往下搜」这个出口，须先有一轮真正改进过（2026-09-05）。

病灶。轮次循环末尾原本是无条件的 ``if best 的 electricity_kwh <= 0: break``。
在任何一轮把精确最优压过见证解之前，``best`` 就是初始见证解本身；见证解若是
纯燃油的，这一行会在第 1 轮末把整跑送走，一个确认轮都不给。实测两例——
``solver/reports/grid2x2_20260905/midday/P=1.0/MT-HGS/run_08`` 与 ``run_10``：
``rounds=1``、``round_improved_by_round=[False]``、最终解就是 3333.49 元 8 辆
燃油车的见证解。彼时 ``confirming_round_should_stop`` 的 ``rounds > 1`` 护栏对
任何 ``stop_after_nonimproving_rounds`` 都返回 False，所以把停机规则从 N=1 改到
N=2 对这两跑逐位无效。

本文件验的是**出口判据与轮次循环的停机决定**，不验"改了以后成本会降多少"：
真实搜索的内核由 ``SystemRandom`` 播种，逐位重放不存在（见
``test_runner_improvement_trace`` 的模块说明）。所以这里用与 ``runner.py`` 循环
末尾同构、同顺序的重放器，喂脚本化的（本轮是否改进、本轮末最优是否用电）序列。
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from setp_solver.algorithms.problem_hgs.contracts import (  # noqa: E402
    SearchAccounting,
)
from setp_solver.algorithms.problem_hgs.runner import (  # noqa: E402
    confirming_round_should_stop,
    no_electricity_exit_should_fire,
)


REPO = Path(__file__).parents[2]
FAILED_FIRST_ROUND_RUNS = (
    REPO / "solver/reports/grid2x2_20260905/midday/P=1.0/MT-HGS/run_08",
    REPO / "solver/reports/grid2x2_20260905/midday/P=1.0/MT-HGS/run_10",
)


def _streak(flags, upto):
    streak = 0
    for flag in flags[:upto]:
        streak = 0 if flag else streak + 1
    return streak


def _replay(
    rounds_script,
    *,
    gated: bool,
    confirming: bool = True,
    stop_after: int = 2,
    round_cap: int = 8,
):
    """重放轮次循环的停机决定，返回停在第几轮；``None`` ＝ 脚本走完仍未停。

    ``rounds_script`` 是 ``(本轮是否改进, 本轮末最优的 electricity_kwh)`` 的序列。
    出口顺序与 ``runner.run_kernel_native_problem_hgs`` 循环末尾一致：
    停机规则 → 轮数上限 → 不用电出口。``gated=False`` ＝ 改动前的无条件出口。
    """

    flags = [bool(improved) for improved, _kwh in rounds_script]
    ever_improved = False
    for index, (improved, kwh) in enumerate(rounds_script, start=1):
        ever_improved = ever_improved or bool(improved)
        if confirming:
            if confirming_round_should_stop(
                rounds=index,
                nonimproving_streak=_streak(flags, index),
                stop_after_nonimproving_rounds=stop_after,
            ):
                return index
        elif index == 2:
            return index
        if index >= round_cap:
            return index
        if gated:
            if no_electricity_exit_should_fire(
                electricity_kwh=kwh, ever_improved=ever_improved
            ):
                return index
        elif float(kwh) <= 0.0:
            return index
    return None


# --------------------------------------------------------------------------
# 1. 判据本身。
# --------------------------------------------------------------------------


def test_the_exit_needs_both_no_electricity_and_a_prior_improvement():
    assert no_electricity_exit_should_fire(electricity_kwh=0.0, ever_improved=True)
    assert not no_electricity_exit_should_fire(
        electricity_kwh=0.0, ever_improved=False
    )
    assert not no_electricity_exit_should_fire(
        electricity_kwh=223.58, ever_improved=True
    )
    assert not no_electricity_exit_should_fire(
        electricity_kwh=223.58, ever_improved=False
    )
    # 负数与 0 同解（评价器不产生负电量，但判据按 <= 写，别留半个口子）。
    assert no_electricity_exit_should_fire(electricity_kwh=-1e-9, ever_improved=True)


# --------------------------------------------------------------------------
# 2. 三种情形。
# --------------------------------------------------------------------------


def test_first_round_fails_on_an_all_fuel_witness_now_gets_its_confirming_round():
    """情形一：第 1 轮没改进，最优（＝见证解）不用电。

    这正是 run_08 / run_10。改动前停在第 1 轮；改动后第 1 轮不再从这里退出，
    由 N=2 的停机规则接管——第 2 轮仍不改进才停，也就是至少多搜一轮。
    """

    script = [(False, 0.0), (False, 0.0)]
    assert _replay(script, gated=False) == 1
    assert _replay(script, gated=True) == 2

    # 第 2 轮真找到了用电的解：不用电出口不再适用，跑继续。
    script = [(False, 0.0), (True, 180.0), (False, 180.0), (False, 180.0)]
    assert _replay(script, gated=False) == 1
    assert _replay(script, gated=True) == 4

    # N=1（历史停机规则）下同样只改这一处：第 1 轮不停，第 2 轮不改进即停。
    assert _replay([(False, 0.0), (False, 0.0)], gated=True, stop_after=1) == 2
    assert _replay([(False, 0.0), (False, 0.0)], gated=False, stop_after=1) == 1


def test_first_round_improves_to_a_plan_without_electricity_still_exits_at_round_one():
    """情形二：第 1 轮改进了，改进出来的方案不用电——出口照常触发。

    这是这个出口本来要处理的事：第二阶段按实付电价重标定，对一度电都不用的
    方案没有意义。闸只挡"还没改进过"的跑。
    """

    script = [(True, 0.0), (False, 0.0), (False, 0.0)]
    assert _replay(script, gated=False) == 1
    assert _replay(script, gated=True) == 1


def test_multi_round_runs_are_untouched():
    """情形三：多轮跑（最优一路用电）——新旧逐位相同。"""

    for script in (
        [(True, 200.0), (False, 200.0), (False, 200.0)],
        [(True, 200.0), (True, 190.0), (False, 190.0), (False, 190.0)],
        [(True, 200.0), (False, 200.0), (True, 180.0), (False, 180.0), (False, 180.0)],
        [(True, 200.0)] * 8,
    ):
        assert _replay(script, gated=False) == _replay(script, gated=True), script


def test_every_sequence_whose_first_round_improved_is_bit_identical():
    """穷举：只要第 1 轮改进过，新旧两套逻辑停在同一轮。

    这是"不许改变已改进过的跑的行为"这条要求的证明：闸在第 1 轮末就已打开，
    此后每一轮的判据取值与改动前完全相同。
    """

    checked = 0
    for length in range(1, 7):
        for flags in itertools.product([True, False], repeat=length - 1):
            for kwhs in itertools.product([0.0, 200.0], repeat=length):
                script = list(zip((True, *flags), kwhs, strict=True))
                for stop_after in (1, 2):
                    assert _replay(
                        script, gated=False, stop_after=stop_after
                    ) == _replay(script, gated=True, stop_after=stop_after), script
                checked += 1
    assert checked == sum(2 ** (length - 1) * 2**length for length in range(1, 7))


def test_only_a_failed_first_round_without_electricity_can_differ():
    """反过来：新旧不同的序列，其首轮必定既没改进、最优又不用电。"""

    differing = 0
    for length in range(1, 6):
        for flags in itertools.product([True, False], repeat=length):
            for kwhs in itertools.product([0.0, 200.0], repeat=length):
                script = list(zip(flags, kwhs, strict=True))
                if _replay(script, gated=False) != _replay(script, gated=True):
                    assert not script[0][0], script
                    assert script[0][1] <= 0.0, script
                    differing += 1
    assert differing > 0


# --------------------------------------------------------------------------
# 3. 账本字段。
# --------------------------------------------------------------------------


def test_accounting_records_every_deferred_exit():
    accounting = SearchAccounting()
    assert accounting.to_dict()["no_electricity_exit_deferred_rounds"] == []
    accounting.no_electricity_exit_deferred_rounds = [1, 2]
    assert accounting.to_dict()["no_electricity_exit_deferred_rounds"] == [1, 2]


# --------------------------------------------------------------------------
# 4. 病灶的落盘证据还在（会不会哪天被人悄悄换掉）。
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not all(run.exists() for run in FAILED_FIRST_ROUND_RUNS),
    reason="二乘二补格批不在这份检出里",
)
def test_the_two_recorded_runs_are_exactly_the_case_this_gate_covers():
    for run in FAILED_FIRST_ROUND_RUNS:
        meta = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
        accounting = meta["accounting"]
        assert accounting["rounds"] == 1, run
        assert accounting["round_improved_by_round"] == [False], run
        assert float(meta["ev_observation"]["electricity_kwh"]) == 0.0, run
        # 停机规则那一侧当时确实没有出口：N=2、第 1 轮，护栏返回 False。
        assert not confirming_round_should_stop(
            rounds=1,
            nonimproving_streak=1,
            stop_after_nonimproving_rounds=int(
                accounting["stop_after_nonimproving_rounds"]
            ),
        ), run
