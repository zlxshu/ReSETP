"""确认轮的耐心值由本次跑自己的改善间隔标定（2026-09-05）。

背景。``solver/reports/reload_fix_shortrun_20260905`` 的 6 跑 16 轮里，第 2 轮
起的 10 轮有 8 轮零改善、各自烧满 20,000 圈，占总墙钟 43%；而有改善的两轮，
改善分别落在轮内第 2720 与第 13258 圈，都不超过该跑第 1 轮"两次相邻改善之间
等得最久的那一段"。据此，后续轮的耐心值改为按实测间隔定，而不是全轮固定。

夹具上的 cap 只有 300，夹不出 5000 的下限，所以下限、上限、模式这些边界一律
在纯函数上验；夹具那边只验"耐心值序列确实按规则走、并且真的送进了内核"。
"""

from __future__ import annotations

import csv
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
    CONFIRMING_ROUND_PATIENCE_FLOOR,
    CONFIRMING_ROUND_PATIENCE_SAFETY,
    confirming_round_patience,
    max_improvement_gap,
)


BATCH = (
    Path(__file__).parents[2]
    / "solver"
    / "reports"
    / "reload_fix_shortrun_20260905"
)


# --------------------------------------------------------------------------
# 1. 间隔的定义。
# --------------------------------------------------------------------------


def test_max_improvement_gap_counts_the_wait_before_the_first_improvement():
    """从圈 0 起算：第一次改善来得晚，本身就是一段该计入的等待。"""

    assert max_improvement_gap([]) == 0
    # 播种解记在圈 0，贡献 0。
    assert max_improvement_gap([0]) == 0
    # 直到第 900 圈才第一次改善＝等了 900 圈。
    assert max_improvement_gap([900]) == 900
    assert max_improvement_gap([0, 900]) == 900
    # MT-HGS/run_02 第 1 轮的真实序列。
    assert max_improvement_gap([0, 105, 598, 722, 1649, 17982]) == 16333


def test_max_improvement_gap_ignores_the_trailing_stagnation():
    """轮末那段再无改善的尾巴不是"两次改善之间"，计入即等于自证耐心值。"""

    # 这一轮实跑到第 20000 圈才停，但最后一次改善在第 2720 圈。
    assert max_improvement_gap([0, 2720]) == 2720


# --------------------------------------------------------------------------
# 2. 夹紧规则的边界。
# --------------------------------------------------------------------------


def test_fixed_mode_hands_every_round_the_declared_patience():
    """``fixed`` ＝ 2026-09-05 之前的行为：每轮都拿 stagnation_patience。

    真实搜索路径的内核用 ``SystemRandom`` 播种、无法逐位重放（见
    ``test_runner_improvement_trace`` 的模块说明），所以"逐位相同"在这里以它
    唯一的成因来证：轮次循环对内核的全部影响，就是送进 ``NoImprovement`` 的
    那个整数；只要它每轮都等于 patience，行为就与改动前无从区别。
    """

    for gap in (0, 1, 4516, 15812, 999_999):
        assert (
            confirming_round_patience(gap, mode="fixed", floor=5000, cap=20000)
            == 20000
        )
    # 上下限对 fixed 无效——它压根不看间隔。
    assert confirming_round_patience(0, mode="fixed", floor=1, cap=7) == 7


def test_adaptive_mode_returns_the_measured_gap_inside_the_clamp():
    for gap in (5000, 8555, 12432, 14449, 15812, 16333, 20000):
        assert (
            confirming_round_patience(
                gap, mode="adaptive", floor=5000, cap=20000
            )
            == gap
        )


def test_adaptive_mode_floor_lifts_a_fast_round_one():
    """第 1 轮收敛得快（最长间隔 4516）也不把确认轮压成走过场。"""

    assert (
        confirming_round_patience(4516, mode="adaptive", floor=5000, cap=20000)
        == 5000
    )
    assert (
        confirming_round_patience(0, mode="adaptive", floor=5000, cap=20000)
        == 5000
    )


def test_adaptive_mode_cap_is_the_declared_upper_bound():
    assert (
        confirming_round_patience(
            25_000, mode="adaptive", floor=5000, cap=20000
        )
        == 20000
    )


def test_cap_wins_a_conflict_with_the_floor():
    """夹具上 cap=300 < floor=5000：声明的上限不得被下限顶穿。"""

    assert (
        confirming_round_patience(0, mode="adaptive", floor=5000, cap=300)
        == 300
    )
    assert (
        confirming_round_patience(9999, mode="adaptive", floor=5000, cap=300)
        == 300
    )


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="confirming-round patience mode"):
        confirming_round_patience(100, mode="auto", floor=5000, cap=20000)


def test_safety_factor_is_currently_one_to_one():
    """SAFETY 是代码常量不是命令行开关：改它须重新给出标定数据。"""

    assert CONFIRMING_ROUND_PATIENCE_SAFETY == 1.0
    assert CONFIRMING_ROUND_PATIENCE_FLOOR == 5000


# --------------------------------------------------------------------------
# 3. 常量与它的证据对得上。
# --------------------------------------------------------------------------


_ROUND_ONE_WIDEST_GAP = {
    "MT-HGS/run_01": 4516,
    "MT-HGS/run_02": 16333,
    "MT-HGS/run_03": 12432,
    "MTC-HGS/run_01": 8555,
    "MTC-HGS/run_02": 15812,
    "MTC-HGS/run_03": 14449,
}


@pytest.mark.skipif(
    not BATCH.exists(), reason="2026-09-05 短跑批次不在这份检出里"
)
def test_the_calibration_numbers_come_from_the_recorded_batch():
    """规则里那些数字是从落盘 CSV 上算出来的，不是写死在文档里的。"""

    measured = {}
    for run in sorted(BATCH.glob("*/run_*")):
        trace = run / "improvement_trace.csv"
        if not trace.is_dir() and trace.exists():
            rows = list(
                csv.DictReader(trace.read_text(encoding="utf-8").splitlines())
            )
            first = [
                int(row["iteration"]) for row in rows if int(row["round"]) == 1
            ]
            measured[f"{run.parent.name}/{run.name}"] = max_improvement_gap(
                sorted(first)
            )
    assert measured == _ROUND_ONE_WIDEST_GAP
    # 下限 5000 只对一跑生效，其余五跑的间隔都在下限之上——下限不是主力。
    assert sum(1 for gap in measured.values() if gap < 5000) == 1


# --------------------------------------------------------------------------
# 4. 账本字段。
# --------------------------------------------------------------------------


def test_accounting_defaults_read_as_no_record():
    payload = SearchAccounting().to_dict()
    assert payload["round_patience_by_round"] == []
    assert payload["round_patience_mode"] is None
    assert payload["round1_max_improvement_gap"] is None


def test_accounting_publishes_the_patience_ledger():
    accounting = SearchAccounting()
    accounting.round_patience_by_round = [20000, 15812, 15812]
    accounting.round_patience_mode = "adaptive"
    accounting.round1_max_improvement_gap = 15812
    payload = accounting.to_dict()
    assert payload["round_patience_by_round"] == [20000, 15812, 15812]
    assert payload["round_patience_mode"] == "adaptive"
    assert payload["round1_max_improvement_gap"] == 15812
    # 0 是合法标定值（该轮只有播种事件），不得与"没有记录"混同。
    accounting.round1_max_improvement_gap = 0
    assert accounting.to_dict()["round1_max_improvement_gap"] == 0


# --------------------------------------------------------------------------
# 5. 帮助文本本身。
# --------------------------------------------------------------------------


def test_the_cli_help_renders():
    """argparse 会把 help 串过一遍 ``%`` 展开，一个没转义的 % 就让 --help 崩。

    2026-09-05 实证：新加的 ``--confirming-round-patience-mode`` 帮助里写了
    "43% of total wall clock"，``% o`` 被当成格式符，``--help`` 直接抛
    TypeError——而 300 个测试全绿，因为没有一个测试会去展开帮助文本。这条就
    是补上那个检测器：谁再往 help 里写百分号，这里当场红。
    """

    script = SCRIPTS / "run_problem_hgs_private_technical.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "--confirming-round-patience-mode" in completed.stdout
    assert "--confirming-patience-floor" in completed.stdout
    # 上一代的陈旧措辞不得复活：第 1 轮默认用的是初始种群的分位数，
    # 既不是"mean"，也不是"reference trip"。
    assert "mean reference trip in round one" not in completed.stdout
