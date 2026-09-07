#!/usr/bin/env python3
"""离线回放：给"不用电"提前出口加 ``ever_improved`` 闸之后，已入账的跑判定变没变。

2026-09-05。改动只有一处：轮次循环末尾那个
``if best 的 electricity_kwh <= 0: break``，现在要求"到这一轮为止至少有一轮把
精确最优压过见证解"（``runner.no_electricity_exit_should_fire``）。

本脚本**不重跑任何搜索**。它读每个 run 的 ``metadata.json``，取那串已经落盘的
每轮改善标记与该跑的停机参数，按新旧两套逻辑各重放一遍轮次循环的**停机决定**，
报告两者停在第几轮。能证的只有一件事：**停机决定是否逐位相同**；它不能、也不
声称能证明重跑一遍会得到同一个解（内核由 ``SystemRandom`` 播种）。

每轮的 ``electricity_kwh`` 没有逐轮落盘，只有最终解的有。所以重放对"该轮末最优
是否用电"取一个**保守假设**，并在结果里写明：

* 最终解用电（``ev_observation.electricity_kwh > 0``）⇒ 每轮末的最优都当作用电。
  理由：``best`` 只在改善时被替换，最终那个用电的 ``best`` 是最后一次改善的产物；
  在它之前的轮，最优要么是更早的某个解，要么是见证解。这个假设可能把"某个中间
  轮的最优不用电"错当成用电——那种情况下旧逻辑本会更早停，重放会低估旧逻辑的
  停机时机。**下面单独报有多少跑落在这个不确定区间**（判据：最终解用电但
  ``round_improved_by_round`` 首元素为 False）。
* 最终解不用电 ⇒ 每轮末的最优都当作不用电（最优从未变成用电的解）。

用法::

    export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts'
    .public-hgs-venv/bin/python3 solver/scripts/replay_no_electricity_exit_gate.py \
        solver/reports/grid2x2_20260905 solver/reports/ablation_formal_10x_v5_20260904
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
    MAX_OUTER_ROUNDS,
    STOP_AFTER_NONIMPROVING_ROUNDS,
    confirming_round_should_stop,
    no_electricity_exit_should_fire,
)


# ``confirming_round`` 没有单独落盘；它由 ``stop_semantics_actual`` 里那句
# "stop after N consecutive non-improving rounds" 是否出现来判别——该句只在
# ``confirming_round`` 为真时拼进去（runner.py 的 stop_semantics_actual）。
_CONFIRMING_MARK = "consecutive non-improving"


def _stop_round(
    improved_flags: list[bool],
    *,
    uses_electricity: bool,
    confirming: bool,
    stop_after: int,
    round_cap: int,
    gated: bool,
) -> int | None:
    """按轮次循环的出口顺序重放，返回它会停在第几轮（1 起算）。

    与 ``runner.run_kernel_native_problem_hgs`` 的循环末尾同构、同顺序：
    停机规则 → 轮数上限 → 不用电出口。``gated=False`` 是改动前的行为。

    返回 ``None`` ＝ 走完落盘的这几轮都没触发任何出口，也就是"这条逻辑会让这
    跑继续往下搜，而账本到这里就没有了"。落盘的跑是用旧逻辑跑出来的，所以
    ``gated=False`` 的重放必须恰好停在它自己记录的轮数上——那是本重放模型的
    自检；``gated=True`` 出现 ``None`` 才是这次改动真正要造成的差别。
    """

    ever_improved = False
    for index, flag in enumerate(improved_flags, start=1):
        ever_improved = ever_improved or bool(flag)
        if confirming:
            if confirming_round_should_stop(
                rounds=index,
                nonimproving_streak=_streak(improved_flags, index),
                stop_after_nonimproving_rounds=stop_after,
            ):
                return index
        elif index == 2:
            return index
        if index >= round_cap:
            return index
        kwh = 1.0 if uses_electricity else 0.0
        if gated:
            if no_electricity_exit_should_fire(
                electricity_kwh=kwh, ever_improved=ever_improved
            ):
                return index
        elif kwh <= 0.0:
            return index
    return None


def _streak(flags: list[bool], upto: int) -> int:
    streak = 0
    for flag in flags[:upto]:
        streak = 0 if flag else streak + 1
    return streak


def _runs(root: Path):
    for meta in sorted(root.rglob("metadata.json")):
        if meta.parent.name.startswith("run_"):
            yield meta


def _flags_from_convergence(run: Path) -> list[bool] | None:
    """没有 ``round_improved_by_round`` 的老跑：从 ``convergence.csv`` 反推。

    每行 ＝ 一个外层轮末的精确最优；第 1 轮的比较基准取 ``raw_runs.csv`` 的
    ``initial_cost``（参考见证解）。**这是推断不是直读**：轮次循环里 ``best``
    的初值是 25 个初始个体中可行者的最小成本，那 25 个成本没有落盘，可能低于
    见证解。所以这条路推出的首轮标记有可能把"其实没改善"读成"改善了"。结果里
    以 ``flags_source`` 标出，统计时单列。
    """

    convergence = run / "convergence.csv"
    raw = run / "raw_runs.csv"
    if not convergence.is_file() or not raw.is_file():
        return None
    rows = list(csv.DictReader(convergence.read_text(encoding="utf-8").splitlines()))
    costs = [float(row["best_feasible_raw_cost"]) for row in rows if row.get("best_feasible_raw_cost")]
    raw_rows = list(csv.DictReader(raw.read_text(encoding="utf-8").splitlines()))
    if not costs or not raw_rows or not raw_rows[0].get("initial_cost"):
        return None
    previous = float(raw_rows[0]["initial_cost"])
    flags: list[bool] = []
    for cost in costs:
        flags.append(cost < previous - 1e-9)
        previous = min(previous, cost)
    return flags


def main(argv: list[str]) -> int:
    roots = [Path(a) if Path(a).is_absolute() else REPO / a for a in argv[1:]]
    if not roots:
        raise SystemExit("give at least one report root")

    rows = []
    for root in roots:
        for meta_path in _runs(root):
            run_dir = meta_path.parent
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            acct = meta.get("accounting", {})
            ledger = acct.get("round_improved_by_round")
            if ledger:
                flags = [bool(f) for f in ledger]
                flags_source = "round_improved_by_round"
            else:
                flags = _flags_from_convergence(run_dir)
                flags_source = "convergence.csv (推断)"
            if not flags:
                rows.append(
                    {
                        "run": str(run_dir.relative_to(REPO)),
                        "status": "NO_ROUND_LEDGER",
                    }
                )
                continue
            semantics = str(acct.get("stop_semantics_actual") or "")
            confirming_recorded = _CONFIRMING_MARK in semantics
            # 09-04 及更早的跑没有 stop_semantics_actual，但它们同样是
            # ``--confirming-round`` 跑的（run_ideal_construction_one.sh），
            # 且轮数 >1 本身就说明走的是确认轮分支（非确认轮分支恒停在第 2 轮）。
            confirming = confirming_recorded or len(flags) != 2
            stop_after = acct.get("stop_after_nonimproving_rounds")
            stop_after = 1 if stop_after is None else int(stop_after)
            round_cap = acct.get("max_outer_rounds")
            round_cap = 10**6 if round_cap is None else int(round_cap)
            kwh = float(
                (meta.get("ev_observation") or {}).get("electricity_kwh", 0.0) or 0.0
            )
            uses_electricity = kwh > 0.0
            recorded_rounds = int(acct.get("rounds") or acct.get("restarts") or len(flags))
            old = _stop_round(
                flags,
                uses_electricity=uses_electricity,
                confirming=confirming,
                stop_after=stop_after,
                round_cap=round_cap,
                gated=False,
            )
            new = _stop_round(
                flags,
                uses_electricity=uses_electricity,
                confirming=confirming,
                stop_after=stop_after,
                round_cap=round_cap,
                gated=True,
            )
            rows.append(
                {
                    "run": str(run_dir.relative_to(REPO)),
                    "status": "OK",
                    "flags_source": flags_source,
                    "rounds_recorded": recorded_rounds,
                    "improved": flags,
                    "confirming": confirming,
                    "stop_after": stop_after,
                    "round_cap": round_cap,
                    "electricity_kwh": kwh,
                    "old_stop_round": old,
                    "new_stop_round": new,
                    "identical": old == new,
                    "model_selfcheck_ok": old == recorded_rounds,
                    "first_round_improved": flags[0],
                    "assumption_uncertain": bool(uses_electricity and not flags[0]),
                }
            )

    ok = [r for r in rows if r["status"] == "OK"]
    no_ledger = [r for r in rows if r["status"] == "NO_ROUND_LEDGER"]
    improved_first = [r for r in ok if r["first_round_improved"]]
    failed_first = [r for r in ok if not r["first_round_improved"]]
    differing = [r for r in ok if not r["identical"]]
    selfcheck_bad = [r for r in ok if not r["model_selfcheck_ok"]]

    print(f"读到 {len(rows)} 个 run 目录；能重放 {len(ok)}，不能 {len(no_ledger)}")
    print(
        "  改善标记直读 round_improved_by_round 的："
        f"{sum(1 for r in ok if r['flags_source'].startswith('round_'))}；"
        f"由 convergence.csv 推断的：{sum(1 for r in ok if not r['flags_source'].startswith('round_'))}"
    )
    print(
        f"重放模型自检（旧逻辑必须停在该跑自己记录的轮数）：不符 {len(selfcheck_bad)} 个"
    )
    for r in selfcheck_bad:
        print(
            f"  {r['run']}: 记录 {r['rounds_recorded']} 轮，旧逻辑重放停在 {r['old_stop_round']}"
            f"（improved={r['improved']} kwh={r['electricity_kwh']:.3f} "
            f"confirming={r['confirming']} N={r['stop_after']}）"
        )
    print()
    print(f"首轮改进过（改善标记首元素为 True）：{len(improved_first)}")
    print(
        "  其中新旧判定不同的："
        f"{sum(1 for r in improved_first if not r['identical'])}（应为 0）"
    )
    print(f"首轮未改进：{len(failed_first)}")
    for r in failed_first:
        print(
            f"  {r['run']}: improved={r['improved']} kwh={r['electricity_kwh']:.3f} "
            f"旧停在第 {r['old_stop_round']} 轮 → 新 "
            + ("不在落盘轮次内停（会继续往下搜）" if r["new_stop_round"] is None
               else f"停在第 {r['new_stop_round']} 轮")
        )
    print(f"新旧判定不同的 run 共 {len(differing)}：")
    for r in differing:
        print(
            f"  {r['run']}: {r['old_stop_round']} → "
            + ("继续（超出落盘轮次）" if r["new_stop_round"] is None else str(r["new_stop_round"]))
        )
    uncertain = [r for r in ok if r["assumption_uncertain"]]
    print(f"落在保守假设不确定区间的 run（最终解用电但首轮未改进）：{len(uncertain)}")
    for r in uncertain:
        print(f"  {r['run']}")
    if no_ledger:
        print(f"没有可用改善标记的 run：{len(no_ledger)}")
        for r in no_ledger:
            print(f"  {r['run']}")

    out = REPO / "solver" / "reports" / "grid2x2_20260905" / "no_electricity_gate_replay.json"
    out.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n逐跑结果写入 {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
