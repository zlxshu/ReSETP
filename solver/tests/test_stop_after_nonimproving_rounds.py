"""停机规则：连续 N 轮无改善才停（2026-09-05）。

背景。``docs/handoff/run_variance_diagnosis_20260905.md`` 把同配置十次冷启动的
离散拆开后，主因落在"这次跑有没有拿到第 3 轮"：同车队内，拿到第 3 轮的跑比只
跑两轮的低 18.47 元（B 批 2CV/3EV，4 对 2）与 19.19 元（A 批同车队，1 对 5），
两批同号同量级；而要检出的充电择时效应只有 7–10 元。改动前的规则是"第 2 轮起
任一轮没改善就收摊"——那是一次抽签，不是收敛判据。

本文件只验规则本身，不验"改了以后成本会降多少"：后者要靠正式批次的实跑数据，
单测给不出。真实搜索路径的内核由 ``SystemRandom`` 播种、不可逐位重放（见
``test_runner_improvement_trace`` 的模块说明），所以"N=1 与历史逐位相同"以其
唯一成因来证：轮次循环里改的只有那个 break 判据，而 N=1 时它在全部改善标记
序列上与 ``rounds > 1 and not improved`` 取值完全相同。
"""

from __future__ import annotations

import csv
import itertools
import json
import subprocess
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
    MAX_OUTER_ROUNDS,
    STOP_AFTER_NONIMPROVING_ROUNDS,
    confirming_round_should_stop,
)


BATCH = (
    Path(__file__).parents[2]
    / "solver"
    / "reports"
    / "reload_fix_shortrun_20260905"
)


def _replay(improved: list[bool], *, stop_after: int, cap: int = 10**6) -> int:
    """按轮次循环的规则重放一串改善标记，返回它会停在第几轮。

    与 ``runner.py`` 的确认轮分支同构：streak 在改善的那一轮归零、否则加一；
    第 1 轮从不停机；轮数到顶也停。
    """

    streak = 0
    for index, flag in enumerate(improved, start=1):
        streak = 0 if flag else streak + 1
        if confirming_round_should_stop(
            rounds=index,
            nonimproving_streak=streak,
            stop_after_nonimproving_rounds=stop_after,
        ):
            return index
        if index >= cap:
            return index
    return len(improved)


def _historical(improved: list[bool], *, cap: int = 10**6) -> int:
    """2026-09-05 之前那三行：``if rounds > 1 and not improved: break``。"""

    for index, flag in enumerate(improved, start=1):
        if index > 1 and not flag:
            return index
        if index >= cap:
            return index
    return len(improved)


# --------------------------------------------------------------------------
# 1. N=1 与历史逐位等价。
# --------------------------------------------------------------------------


def test_n_equals_one_is_the_historical_rule_on_every_sequence():
    """穷举长度 1–8 的全部改善标记序列，两条规则停在同一轮。"""

    checked = 0
    for length in range(1, 9):
        for improved in itertools.product([True, False], repeat=length):
            sequence = list(improved)
            assert _replay(sequence, stop_after=1) == _historical(sequence)
            checked += 1
    assert checked == sum(2**length for length in range(1, 9))


def test_round_one_never_stops_whatever_the_streak():
    """第 1 轮是被确认的那一轮本身，它自己不改善也不停。"""

    for stop_after in (1, 2, 3):
        assert not confirming_round_should_stop(
            rounds=1,
            nonimproving_streak=1,
            stop_after_nonimproving_rounds=stop_after,
        )


# --------------------------------------------------------------------------
# 2. N=2 的语义。
# --------------------------------------------------------------------------


def test_two_consecutive_are_required_and_an_improvement_resets_the_streak():
    # 改善—不改善—改善—不改善—不改善：只有最后那两连才停。
    sequence = [True, False, True, False, False]
    assert _historical(sequence) == 2
    assert _replay(sequence, stop_after=1) == 2
    assert _replay(sequence, stop_after=2) == 5

    # 一路改善到底：规则不介入，跑满序列。
    assert _replay([True] * 6, stop_after=2) == 6

    # 第 1 轮就没改善，第 2 轮也没有：第 2 轮停（streak 从第 1 轮起算）。
    assert _replay([False, False, True], stop_after=2) == 2


def test_alternating_improvement_never_stops_without_the_round_cap():
    """N≥2 时"改善—不改善"交替的跑凑不满连续，硬上限就是它的唯一出口。

    改动前的确认轮分支没有任何总轮数上限，N=1 时靠"任一轮不改善即停"自然终
    止；N≥2 起这个上限不是调参旋钮，是循环的出口。
    """

    alternating = [index % 2 == 0 for index in range(40)]
    assert _replay(alternating, stop_after=2) == len(alternating)
    assert _replay(alternating, stop_after=2, cap=8) == 8
    assert MAX_OUTER_ROUNDS == 8
    assert STOP_AFTER_NONIMPROVING_ROUNDS == 2


def test_a_non_positive_n_is_refused():
    for bad in (0, -1):
        with pytest.raises(ValueError, match="at least 1"):
            confirming_round_should_stop(
                rounds=3,
                nonimproving_streak=3,
                stop_after_nonimproving_rounds=bad,
            )


# --------------------------------------------------------------------------
# 3. 在落盘的真实改善序列上重放。
# --------------------------------------------------------------------------


def _recorded_improved_flags(run: Path) -> list[bool]:
    """从 ``convergence.csv`` 反推每轮有没有把精确最优压下去。

    每行 ＝ 一个外层轮末的精确最优。第 1 轮的比较基准取参考见证解
    （``raw_runs.csv`` 的 ``initial_cost``）。**注意口径**：轮次循环里的初值是
    25 个初始个体里可行者的最小成本，不是见证解，而那 25 个个体的逐个成本没有
    落盘（见 run_variance_diagnosis_20260905.md §3）——两者可能不同。这批 6 跑
    的第 1 轮末落在 2600–2681，比见证解 3073.78 低 390 元以上，量级上这个口径
    差别不影响"第 1 轮改善了"这个判断，但它是推断不是直读，故不在断言里声称
    第 1 轮必为改善。
    """

    rows = list(
        csv.DictReader((run / "convergence.csv").read_text().splitlines())
    )
    costs = [float(row["best_feasible_raw_cost"]) for row in rows]
    initial = float(
        list(csv.DictReader((run / "raw_runs.csv").read_text().splitlines()))[
            0
        ]["initial_cost"]
    )
    previous = initial
    flags = []
    for cost in costs:
        flags.append(cost < previous - 1e-9)
        previous = min(previous, cost)
    return flags


@pytest.mark.skipif(
    not BATCH.exists(), reason="2026-09-05 短跑批次不在这份检出里"
)
def test_the_recorded_batch_replays_to_its_own_round_counts_under_n_equals_one():
    runs = [
        run
        for run in sorted(BATCH.glob("*/run_*"))
        if run.is_dir() and (run / "convergence.csv").exists()
    ]
    assert len(runs) == 6
    for run in runs:
        flags = _recorded_improved_flags(run)
        recorded = int(
            json.loads((run / "metadata.json").read_text())["accounting"][
                "rounds"
            ]
        )
        assert len(flags) == recorded, run
        # 这批是用 N=1 的代码跑的：重放必须回到它自己的轮数。
        assert _replay(flags, stop_after=1) == recorded, run
        # 同一串标记在 N=2 下至少多跑一轮（那一轮的结果未知，重放到序列尽头
        # 就是"多跑一轮且不再改善"这一种情形）。
        assert _replay(flags + [False], stop_after=2) == recorded + 1, run


# --------------------------------------------------------------------------
# 4. 账本字段。
# --------------------------------------------------------------------------


def test_accounting_defaults_read_as_no_record():
    payload = SearchAccounting().to_dict()
    assert payload["round_improved_by_round"] == []
    assert payload["stop_after_nonimproving_rounds"] is None
    assert payload["max_outer_rounds"] is None


def test_accounting_publishes_the_stop_rule_ledger():
    accounting = SearchAccounting()
    accounting.round_improved_by_round = [True, True, False, False]
    accounting.stop_after_nonimproving_rounds = 2
    accounting.max_outer_rounds = 8
    payload = accounting.to_dict()
    assert payload["round_improved_by_round"] == [True, True, False, False]
    assert payload["stop_after_nonimproving_rounds"] == 2
    assert payload["max_outer_rounds"] == 8


# --------------------------------------------------------------------------
# 5. 命令行开关本身。
# --------------------------------------------------------------------------


def test_the_cli_exposes_the_switch():
    script = SCRIPTS / "run_problem_hgs_private_technical.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "--stop-after-nonimproving-rounds" in completed.stdout
    assert "--max-outer-rounds" in completed.stdout
