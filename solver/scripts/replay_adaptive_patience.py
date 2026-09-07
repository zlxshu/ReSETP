"""重放：把已跑完的批次按"确认轮耐心值随实测改善间隔走"的规则再算一遍。

2026-09-05。本脚本**不开搜索**，只读 ``solver/reports/reload_fix_shortrun_
20260905`` 已落盘的 ``improvement_trace.csv`` 与 ``kernel_rounds.csv``，回答
两个问题：新规则会不会丢掉真实发生过的改善，以及能省多少墙钟。

停止模型（已在实跑数据上逐轮核对）。内核的 ``NoImprovement(patience)`` 在
``counter >= patience`` 时停，counter 每逢内核最优被刷新即归零，所以一轮的
实际圈数恒等于 ``最后一次改善所在圈 + patience``。以 MT-HGS/run_01 第 1 轮为
例：最后一次改善在第 14907 圈，14907 + 20000 = 34907，与 ``kernel_rounds.csv``
的 34907 逐位相符；16 轮全部对得上（脚本会逐轮断言，对不上就报错退出）。

重放能证明什么、不能证明什么。能证明的是：模拟出的停圈一律落在该轮最后一次
保留下来的改善之后（脚本逐轮断言），因此**该轮内核最优的代价按构造不变**——
新规则砍掉的只是改善之后的空转尾巴。不能证明的是终局种群的**多样性**：精确
阶段解码的是 ``[kernel_result.best, *population]``，尾巴变短后种群成员分布会
不同，精确阶段选出的那一个可能随之不同。故本表是"内核侧的账"，不是对最终成
本的预测。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "solver" / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "solver" / "src"))

from setp_solver.algorithms.problem_hgs.runner import (  # noqa: E402
    CONFIRMING_ROUND_PATIENCE_FLOOR,
    CONFIRMING_ROUND_PATIENCE_SAFETY,
    confirming_round_patience,
    max_improvement_gap,
)

BATCH = REPO / "solver" / "reports" / "reload_fix_shortrun_20260905"
OUTPUT = BATCH / "adaptive_patience_replay.md"


def _read_rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def _run_dirs() -> list[Path]:
    return sorted(
        d
        for d in BATCH.glob("*/run_*")
        if d.is_dir() and (d / "improvement_trace.csv").exists()
    )


def _actual_patience(run: Path) -> int:
    """本次跑声明的 stagnation_patience，从 metadata.json 读，不写死。"""

    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    return int(metadata["stagnation_patience"])


def _simulate_round(events: list[int], patience: int) -> tuple[int, list[int]]:
    """按 NoImprovement(patience) 走一遍事件序列。

    返回（停在第几圈, 保留下来的改善圈号）。事件之间的间隔一旦超过 patience，
    这一轮就在"上一次改善 + patience"处停住，其后的事件都看不到了。
    """

    kept: list[int] = []
    previous = 0
    for iteration in events:
        if iteration - previous > patience:
            return previous + patience, kept
        kept.append(iteration)
        previous = iteration
    return previous + patience, kept


def replay() -> dict:
    rows: list[dict] = []
    runs: list[dict] = []
    for run in _run_dirs():
        cap = _actual_patience(run)
        trace = _read_rows(run / "improvement_trace.csv")
        summaries = _read_rows(run / "kernel_rounds.csv")
        by_round: dict[int, list[int]] = {}
        for event in trace:
            by_round.setdefault(int(event["round"]), []).append(
                int(event["iteration"])
            )

        widest = 0
        run_rows: list[dict] = []
        for summary in summaries:
            index = int(summary["round"])
            actual_iterations = int(summary["iterations"])
            actual_runtime = float(summary["runtime_seconds"])
            events = sorted(by_round.get(index, []))

            # 停止模型自检：实跑圈数必须等于"最后一次改善 + cap"。
            last_actual = events[-1] if events else 0
            if last_actual + cap != actual_iterations:
                raise AssertionError(
                    f"{run}: round {index} does not fit the stop model: "
                    f"{last_actual} + {cap} != {actual_iterations}"
                )

            simulated_patience = (
                cap
                if index == 1
                else confirming_round_patience(
                    widest,
                    mode="adaptive",
                    floor=CONFIRMING_ROUND_PATIENCE_FLOOR,
                    cap=cap,
                )
            )
            stop_at, kept = _simulate_round(events, simulated_patience)
            lost = [i for i in events if i not in kept]

            # 保留下来的改善之后才停：该轮内核最优代价按构造不变。
            if kept and stop_at < kept[-1]:
                raise AssertionError(
                    f"{run}: round {index} would stop at {stop_at}, before its "
                    f"last kept improvement at {kept[-1]}"
                )

            saved_iterations = actual_iterations - stop_at
            saved_seconds = (
                actual_runtime * saved_iterations / actual_iterations
                if actual_iterations
                else 0.0
            )
            # 播种事件（圈 0）不是轮内搜索改善，单列计数，免得"0 个丢失"被
            # 一堆必然保留的种子事件撑成好看的样子。
            in_round = [i for i in events if i > 0]
            run_rows.append(
                {
                    "run": f"{run.parent.name}/{run.name}",
                    "round": index,
                    "reference_gap": widest,
                    "patience": simulated_patience,
                    "actual_iterations": actual_iterations,
                    "simulated_stop": stop_at,
                    "saved_iterations": saved_iterations,
                    "actual_runtime": actual_runtime,
                    "saved_seconds": saved_seconds,
                    "in_round_improvements": in_round,
                    "lost": lost,
                }
            )
            # 参考量只用"新规则下还看得见"的事件更新：轮变短了，尾巴上的事件
            # 本就不会发生，拿它们放宽下一轮等于用未来的信息。
            widest = max(widest, max_improvement_gap(kept))

        rows.extend(run_rows)
        runs.append(
            {
                "run": f"{run.parent.name}/{run.name}",
                "cap": cap,
                "round1_gap": run_rows[0]["reference_gap"] if run_rows else 0,
                "round1_widest": max_improvement_gap(sorted(by_round.get(1, []))),
                "actual_seconds": sum(r["actual_runtime"] for r in run_rows),
                "saved_seconds": sum(r["saved_seconds"] for r in run_rows),
                "lost": sum(len(r["lost"]) for r in run_rows),
            }
        )
    return {"rows": rows, "runs": runs}


def render(result: dict) -> str:
    rows = result["rows"]
    runs = result["runs"]
    total_actual = sum(r["actual_runtime"] for r in rows)
    total_saved = sum(r["saved_seconds"] for r in rows)
    total_iterations = sum(r["actual_iterations"] for r in rows)
    total_saved_iterations = sum(r["saved_iterations"] for r in rows)
    lost_total = sum(len(r["lost"]) for r in rows)
    confirming = [r for r in rows if r["round"] > 1]
    real_events = [i for r in confirming for i in r["in_round_improvements"]]

    lines: list[str] = []
    lines.append("# 确认轮自适应耐心值：对 2026-09-05 短跑批次的重放")
    lines.append("")
    lines.append(
        f"生成自 `solver/scripts/replay_adaptive_patience.py`，只读 "
        f"`{BATCH.relative_to(REPO)}` 已落盘的 CSV，**未开任何搜索**。"
    )
    lines.append("")
    lines.append(
        "规则：第 1 轮耐心值不变；第 2 轮起 ＝ "
        f"clamp(迄今所有轮里相邻两次内核改善之间最长的一段 × "
        f"{CONFIRMING_ROUND_PATIENCE_SAFETY:g}, "
        f"{CONFIRMING_ROUND_PATIENCE_FLOOR}, stagnation_patience)。"
    )
    lines.append("")
    lines.append("## 1. 逐轮重放（16 轮）")
    lines.append("")
    lines.append(
        "| 跑 | 轮 | 参考间隔 | 模拟耐心 | 实跑圈数 | 模拟停圈 | 省下圈数 | "
        "实跑秒 | 省下秒 | 轮内改善（圈号） | 丢失 |"
    )
    lines.append(
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |"
    )
    for row in rows:
        improvements = (
            ", ".join(str(i) for i in row["in_round_improvements"]) or "—"
        )
        reference = "—" if row["round"] == 1 else f"{row['reference_gap']}"
        lines.append(
            f"| {row['run']} | {row['round']} | {reference} | {row['patience']} "
            f"| {row['actual_iterations']} | {row['simulated_stop']} "
            f"| {row['saved_iterations']} | {row['actual_runtime']:.1f} "
            f"| {row['saved_seconds']:.1f} | {improvements} | {len(row['lost'])} |"
        )
    lines.append("")
    lines.append("## 2. 逐跑小结")
    lines.append("")
    lines.append(
        "| 跑 | 第 1 轮最长间隔 | 实跑墙钟(s) | 省下墙钟(s) | 省下占比 | 丢失事件 |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for run in runs:
        share = run["saved_seconds"] / run["actual_seconds"] * 100
        lines.append(
            f"| {run['run']} | {run['round1_widest']} "
            f"| {run['actual_seconds']:.1f} | {run['saved_seconds']:.1f} "
            f"| {share:.1f}% | {run['lost']} |"
        )
    lines.append("")
    lines.append("## 3. 合计")
    lines.append("")
    lines.append(
        f"- 内核圈数：实跑 {total_iterations}，模拟省下 {total_saved_iterations}"
        f"（{total_saved_iterations / total_iterations * 100:.1f}%）。"
    )
    lines.append(
        f"- 内核墙钟：实跑 {total_actual:.1f} s，模拟省下 {total_saved:.1f} s"
        f"（{total_saved / total_actual * 100:.1f}%）。"
    )
    lines.append(f"- 丢失的改善事件：**{lost_total} 个**。")
    lines.append("")
    lines.append("## 4. 这份表能证明什么、不能证明什么")
    lines.append("")
    lines.append(
        "- 停止模型经过自检：脚本对 16 轮逐轮断言"
        "「实跑圈数 ＝ 最后一次改善所在圈 ＋ 耐心值」，任何一轮对不上即报错退出。"
    )
    lines.append(
        "- 「0 个丢失」不要读成强验证。第 1 轮压根没动，它的事件是白送的；"
        "第 2 轮起每条轨迹在圈 0 都有一个事件，那是**播种**，不是轮内搜索改善。"
        f"真正构成考验的样本只有 {len(real_events)} 个轮内改善事件"
        f"（{', '.join(f'第 {i} 圈' for i in real_events) if real_events else '无'}），"
        "都出自 MTC-HGS/run_02。"
    )
    if real_events:
        margins = []
        for row in confirming:
            for i in row["in_round_improvements"]:
                margins.append((i, row["patience"], i / row["patience"] * 100))
        worst = max(margins, key=lambda m: m[2])
        lines.append(
            f"- 余量最紧的一次：第 {worst[0]} 圈的改善对耐心值 {worst[1]}，"
            f"用掉了 {worst[2]:.0f}%，只剩 {100 - worst[2]:.0f}% 余量。"
            f"SAFETY 目前是 {CONFIRMING_ROUND_PATIENCE_SAFETY:g}（代码常量，"
            "不是命令行开关）；要放宽余量就得改它，改它就得重新给出这一类数据。"
        )
    lines.append(
        "- 按构造不变的是**内核侧**：模拟停圈一律落在该轮最后一个保留事件之后，"
        "所以该轮内核最优代价不变；变的是终局种群的多样性，而精确阶段解码的是"
        "`[kernel_result.best, *population]`，故最终成本可能仍有出入。"
        "本表是内核侧的账，不是对最终成本的预测。"
    )
    # 下限触发（间隔 < floor）与自适应本身各省了多少，按行算，不靠断言。
    floor_saved = sum(
        row["saved_seconds"]
        for row in confirming
        if row["reference_gap"] < CONFIRMING_ROUND_PATIENCE_FLOOR
    )
    best_run = max(runs, key=lambda r: r["saved_seconds"] / r["actual_seconds"])
    worst_run = min(runs, key=lambda r: r["saved_seconds"] / r["actual_seconds"])
    lines.append(
        "- 收益极不均匀，别只看合计：省得最多的 "
        f"{best_run['run']}（第 1 轮最长间隔 {best_run['round1_widest']}）省下 "
        f"{best_run['saved_seconds'] / best_run['actual_seconds'] * 100:.1f}%，"
        f"省得最少的 {worst_run['run']}（{worst_run['round1_widest']}）只省下 "
        f"{worst_run['saved_seconds'] / worst_run['actual_seconds'] * 100:.1f}%。"
        "第 1 轮就等得久的跑，后续轮本来就该等得久，新规则给不出便宜。"
    )
    lines.append(
        f"- 其中下限 {CONFIRMING_ROUND_PATIENCE_FLOOR} 触发的那些轮"
        f"（参考间隔小于下限）省下 {floor_saved:.1f} s，"
        f"占总省下的 {floor_saved / total_saved * 100:.0f}%；"
        f"其余 {total_saved - floor_saved:.1f} s"
        f"（{(total_saved - floor_saved) / total_saved * 100:.0f}%）"
        "来自自适应本身。下限不是摆设，但也不是省下墙钟的主力。"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    result = replay()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(result), encoding="utf-8")
    lost = sum(len(row["lost"]) for row in result["rows"])
    print(f"wrote {OUTPUT}")
    print(f"rounds={len(result['rows'])} lost_improvement_events={lost}")
    return 1 if lost else 0


if __name__ == "__main__":
    raise SystemExit(main())
