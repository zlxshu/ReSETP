#!/usr/bin/env python3
"""只读诊断：四种充电安排各自把电充在了哪、为什么只能充在那里（2026-09-06）。

回答 4.4.1 留下的三个问题，只用已落盘的解，不跑任何搜索：
  Q1 为什么只看电价会增排——把每次充电按"窗口类型"归类，算各窗口的电量、碳强度、排放，
     对照有电即充，看增排来自哪个窗口；
  Q2 为什么只看碳强度只能省几公斤——对每次充电算它在自己可行窗口内能拿到的最低碳强度、
     以及全天最低碳强度（0.154），看差距被什么锁住；再算充电排放占总排放的份额；
  Q3 为什么电价＋碳价（碳价 0.2）等于只看电价——对每次充电算窗口内"最便宜时刻"与
     "最干净时刻"的电价差与碳强度差，得到让碳进决策的盈亏平衡碳价，看分布。

窗口定义（按已实现的解反推，用的是各趟实际发车/回场时刻）：
  第 k 趟前的补电窗口 = [第 k-1 趟回场, 第 k 趟发车 − 本次充电占用时长]；
  首趟（k=1）前 = [该车前一日最后一趟回场（同一时刻表减 86400 s）, 首趟发车 − 占用]（前一晚回场即充口径）。
窗口类型：first（首趟前）／lunch（上午班结束到下午班开始之间）／pm（下午班趟间）／other。

碳强度与电价取日历 beijing 2025-02-12 半小时槽；一次充电的排放按其占用分钟数逐槽分摊电量，
并与解里记录的 E_ev_indirect 逐 run 核对（偏差打印出来）。

用法：python3 solver/scripts/diagnose_charging_windows_20260906.py [--out docs/handoff/xxx.md]
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import statistics as st
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAL = REPO / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv"
SHIFT = REPO / "data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/shift_contract.json"
ARMS = {
    "有电即充": REPO / "solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MT-HGS",
    "只看电价": REPO / "solver/reports/charging_arrangements_20260906/cost_min",
    "只看碳": REPO / "solver/reports/charging_arrangements_20260906/carbon_min",
    "电价+碳价": REPO / "solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS",
}
DAY = 86400.0
SLOT = 1800.0


def load_calendar():
    rows = [r for r in csv.DictReader(open(CAL, encoding="utf-8")) if r["city"] == "beijing" and r["date"] == "2025-02-12"]
    price, carbon = {}, {}
    for r in rows:
        m = int(r["minute_of_day"])
        price[m] = float(r["depot_energy_cny_per_kwh"])
        carbon[m] = float(r["carbon_factor_kgco2e_per_kwh"])
    assert len(price) == 48
    return price, carbon


def slot_of(second: float) -> int:
    return int((second % DAY) // 60 // 30) * 30


def session_emission(start: float, minutes: float, kwh: float, carbon) -> float:
    """按占用分钟逐槽分摊电量后的排放（近似：功率恒定）。"""
    if minutes <= 0:
        return kwh * carbon[slot_of(start)]
    total = 0.0
    t = start
    end = start + minutes * 60
    while t < end - 1e-9:
        s = slot_of(t)
        nxt = (t // SLOT + 1) * SLOT
        seg = min(nxt, end) - t
        total += kwh * (seg / (minutes * 60)) * carbon[s]
        t = nxt
    return total


def session_price(start: float, minutes: float, kwh: float, price) -> float:
    if minutes <= 0:
        return kwh * price[slot_of(start)]
    total = 0.0
    t = start
    end = start + minutes * 60
    while t < end - 1e-9:
        s = slot_of(t)
        nxt = (t // SLOT + 1) * SLOT
        seg = min(nxt, end) - t
        total += kwh * (seg / (minutes * 60)) * price[s]
        t = nxt
    return total


def feasible_starts(w0: float, w1: float):
    """窗口内所有可作为起充时刻的半小时槽起点（含 w0 本身作为最早起点）。"""
    starts = [w0]
    first = (w0 // SLOT + 1) * SLOT
    t = first
    while t <= w1:
        starts.append(t)
        t += SLOT
    return starts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO / "docs/handoff/charging_window_root_cause_20260906.md")
    ap.add_argument(
        "--statistic",
        choices=("mean", "best"),
        default="mean",
        help="每臂取值口径：mean=该臂全部 run（默认，行为不变）；"
        "best=只用该臂 total_cost 最小的那一次运算（与表11/表12 best 口径同一 run）",
    )
    args = ap.parse_args()
    price, carbon = load_calendar()
    shifts = json.load(open(SHIFT))["shifts"]
    am_end = shifts["AM"]["end_minute"] * 60
    pm_start = shifts["PM"]["start_minute"] * 60
    cmin_slot = min(carbon, key=carbon.get)
    print(f"全天最低碳强度 {carbon[cmin_slot]:.4f} @ {cmin_slot//60:02d}:{cmin_slot%60:02d}；最高 {max(carbon.values()):.4f}")

    report = {}
    chosen = {}
    for arm, d in ARMS.items():
        per_run = []
        paths = sorted(glob.glob(str(d / "run_*/best_solution.json")))
        if not paths:
            raise SystemExit(f"{d}: 没有任何 run_*/best_solution.json")
        if args.statistic == "best":
            costs = {q: json.load(open(q))["evaluation"]["breakdown"]["total_cost"] for q in paths}
            bp = min(costs, key=costs.get)
            paths = [bp]
            chosen[arm] = (Path(bp).parent.name, costs[bp])
            print(f"[{arm}] best（total_cost 最小）：{Path(bp).parent.name}  total_cost={costs[bp]:.2f}")
        for p in paths:
            sol = json.load(open(p))
            b = sol["evaluation"]["breakdown"]
            trips = collections.defaultdict(dict)
            for t in sol["trip_clock"]:
                trips[t["physical_vehicle_id"]][t["trip_index"]] = t
            sess_rows = []
            for duty in sol["individual"]["duties"]:
                if not duty["charging_sessions"]:
                    continue
                vid = duty["physical_vehicle_id"]
                tv = trips[vid]
                last_return = max(t["return_second"] for t in tv.values())
                for c in duty["charging_sessions"]:
                    k = c["trip_index"]
                    start = c["charge_start_second"] + c["charge_day_offset"] * DAY
                    occ = c["occupancy_minutes"]
                    dep = tv[k]["departure_second"]
                    if k == 1:
                        w0 = last_return - DAY
                        wtype = "first"
                    else:
                        w0 = tv[k - 1]["return_second"]
                        if w0 <= am_end + 1 and dep >= pm_start - 1:
                            wtype = "lunch"
                        elif dep >= pm_start - 1:
                            wtype = "pm"
                        else:
                            wtype = "other"
                    w1 = dep - occ * 60
                    kwh = c["energy_kwh"]
                    em = session_emission(start, occ, kwh, carbon)
                    cost = session_price(start, occ, kwh, price)
                    ci = em / kwh if kwh else 0.0
                    starts = feasible_starts(w0, w1) if w1 >= w0 else [start]
                    cand = [(s, session_emission(s, occ, kwh, carbon) / kwh, session_price(s, occ, kwh, price) / kwh) for s in starts]
                    cleanest = min(cand, key=lambda x: (x[1], x[2]))
                    cheapest = min(cand, key=lambda x: (x[2], x[1]))
                    dc = cheapest[1] - cleanest[1]
                    dp = cleanest[2] - cheapest[2]
                    breakeven = (dp / dc) if dc > 1e-9 else None
                    reach_global = any(abs(x[1] - carbon[cmin_slot]) < 1e-9 for x in cand)
                    sess_rows.append(dict(
                        wtype=wtype, kwh=kwh, em=em, cost=cost, ci=ci, start=start, w0=w0, w1=w1,
                        clean_ci=cleanest[1], clean_p=cleanest[2], cheap_ci=cheapest[1], cheap_p=cheapest[2],
                        breakeven=breakeven, reach_global=reach_global, win_hours=(w1 - w0) / 3600 if w1 >= w0 else 0.0,
                    ))
            em_sum = sum(r["em"] for r in sess_rows)
            per_run.append(dict(
                sessions=sess_rows, fleet=(b["n_veh_cv"], b["n_veh_ev"]), E_ev=b["E_ev_indirect"], E_total=b["E_total"],
                E_cv=b["E_cv_direct"], kwh=b["electricity_kwh"], cost_elec=b["cost_elec"], em_approx=em_sum,
                cost_approx=sum(r["cost"] for r in sess_rows),
            ))
        report[arm] = per_run

    tag = "四种充电安排各 10 次" if args.statistic == "mean" else "四种充电安排各取 10 次中总成本最低的那 1 次（best，与表 11／表 12 同一 run）"
    lines = [f"# 充电窗口根因诊断（脚本 diagnose_charging_windows_20260906.py，只读，{tag}）\n"]
    if args.statistic == "best":
        lines.append("选中的 run：" + "；".join(f"{a} = {r}（total_cost {c:.2f}）" for a, (r, c) in chosen.items()) + "\n")
    lines.append(f"全天最低碳强度 {carbon[cmin_slot]:.4f} kg/kWh（{cmin_slot//60:02d}:{cmin_slot%60:02d} 起的槽），最高 {max(carbon.values()):.4f}；"
                 f"上午班结束 {am_end/3600:.0f}:00、下午班开始 {pm_start/3600:.0f}:00。\n")
    lines.append("## 0. 近似账与解内记录的核对（逐 run 排放偏差）\n")
    for arm, runs in report.items():
        dev = [r["em_approx"] - r["E_ev"] for r in runs]
        devc = [r["cost_approx"] - r["cost_elec"] for r in runs]
        lines.append(f"- {arm}：排放偏差 均值 {st.mean(dev):+.2f} kg（最大绝对 {max(abs(x) for x in dev):.2f}）；电费偏差 均值 {st.mean(devc):+.2f} 元（最大绝对 {max(abs(x) for x in devc):.2f}）")
    lines.append("")

    per = "10 次均值/次" if args.statistic == "mean" else "该 1 次运算"
    lines.append(f"## 1. 各窗口的电量、碳强度与排放（{per}；括号内为只取 2 油 3 电那些次）\n")
    lines.append("| 安排 | 窗口 | 场次/次 | kWh/次 | 平均碳强度 | 排放 kg/次 | 窗口长度 h（中位） | 能碰到全天最净槽的场次占比 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    summary = {}
    for arm, runs in report.items():
        for wt in ("first", "lunch", "pm", "other"):
            rows = [s for r in runs for s in r["sessions"] if s["wtype"] == wt]
            rows23 = [s for r in runs if r["fleet"] == (2, 3) for s in r["sessions"] if s["wtype"] == wt]
            n23 = sum(1 for r in runs if r["fleet"] == (2, 3))
            if not rows:
                continue
            n = len(runs)
            kwh = sum(s["kwh"] for s in rows) / n
            em = sum(s["em"] for s in rows) / n
            ci = sum(s["em"] for s in rows) / max(sum(s["kwh"] for s in rows), 1e-9)
            kwh23 = sum(s["kwh"] for s in rows23) / n23 if n23 else float("nan")
            em23 = sum(s["em"] for s in rows23) / n23 if n23 else float("nan")
            wh = st.median(s["win_hours"] for s in rows)
            reach = sum(1 for s in rows if s["reach_global"]) / len(rows)
            summary[(arm, wt)] = (kwh, em, ci)
            lines.append(f"| {arm} | {wt} | {len(rows)/n:.1f} | {kwh:.1f}（{kwh23:.1f}） | {ci:.3f} | {em:.1f}（{em23:.1f}） | {wh:.1f} | {reach*100:.0f}% |")
    lines.append("")

    lines.append("## 2. 只看碳：实际拿到的碳强度 vs 窗口内最净 vs 全天最净\n")
    for arm in ("只看碳", "电价+碳价", "只看电价", "有电即充"):
        runs = report[arm]
        rows = [s for r in runs for s in r["sessions"]]
        kwh = sum(s["kwh"] for s in rows)
        real = sum(s["em"] for s in rows) / kwh
        winmin = sum(s["clean_ci"] * s["kwh"] for s in rows) / kwh
        glob_min = carbon[cmin_slot]
        n = len(runs)
        lines.append(f"- {arm}：电量加权碳强度 实际 {real:.3f}；若每次都取窗口内最净 {winmin:.3f}（差 {(real-winmin)*kwh/n:.2f} kg/次）；"
                     f"若每度都在全天最净 {glob_min:.3f}（差 {(real-glob_min)*kwh/n:.2f} kg/次）；充电排放占总排放 {100*st.mean(r['E_ev']/r['E_total'] for r in runs):.1f}%")
        hit = [s for s in rows if abs(s["ci"] - s["clean_ci"]) < 1e-9]
        lines.append(f"  - 其中实际碳强度＝本次充电所在窗口内可达最低碳强度的场次 {len(hit)}/{len(rows)}"
                     f"（{100*len(hit)/len(rows):.0f}%），占电量 {100*sum(s['kwh'] for s in hit)/kwh:.0f}%")
    lines.append("")

    lines.append("## 3. 只看电价 vs 有电即充：增排来自哪个窗口（2 油 3 电子集，kg/次）\n")
    for wt in ("first", "lunch", "pm"):
        a = summary.get(("有电即充", wt)); b = summary.get(("只看电价", wt)); c = summary.get(("只看碳", wt)); d = summary.get(("电价+碳价", wt))
        if a and b:
            lines.append(f"- {wt}：即充 {a[1]:.1f}（{a[2]:.3f}）→ 只看电价 {b[1]:.1f}（{b[2]:.3f}）Δ{b[1]-a[1]:+.1f}；只看碳 {c[1]:.1f}（{c[2]:.3f}）Δ{c[1]-a[1]:+.1f}；电价+碳价 {d[1]:.1f}（{d[2]:.3f}）Δ{d[1]-a[1]:+.1f}")
    lines.append("")

    lines.append("## 4. 碳价要多高才进决策：每次充电的盈亏平衡碳价（窗口内最便宜槽 vs 最净槽），按电量加权\n")
    for arm in ("只看电价", "电价+碳价"):
        rows = [s for r in report[arm] for s in r["sessions"] if s["breakeven"] is not None]
        rows.sort(key=lambda s: s["breakeven"])
        kwh_tot = sum(s["kwh"] for s in rows)
        acc = 0.0
        q = {}
        for s in rows:
            acc += s["kwh"]
            for qq in (0.25, 0.5, 0.75, 0.9):
                if qq not in q and acc >= qq * kwh_tot:
                    q[qq] = s["breakeven"]
        by_w = collections.defaultdict(list)
        for s in rows:
            by_w[s["wtype"]].append(s)
        lines.append(f"- {arm}：{len(rows)} 场次有取舍空间；盈亏平衡碳价 电量分位 25% {q.get(0.25, float('nan')):.2f} / 50% {q.get(0.5, float('nan')):.2f} / 75% {q.get(0.75, float('nan')):.2f} / 90% {q.get(0.9, float('nan')):.2f} 元/kg；"
                     + "；".join(f"{wt} 中位 {st.median(x['breakeven'] for x in v):.2f}（Δ电价 {st.median(x['clean_p']-x['cheap_p'] for x in v):.3f} 元/kWh，Δ碳 {st.median(x['cheap_ci']-x['clean_ci'] for x in v):.3f} kg/kWh）" for wt, v in by_w.items()))
        no_room = [s for r in report[arm] for s in r["sessions"] if s["breakeven"] is None]
        lines.append(f"  无取舍空间（窗口内最便宜即最净或窗口只有一个槽）的场次 {len(no_room)}，电量 {sum(s['kwh'] for s in no_room)/len(report[arm]):.1f} kWh/次")
    lines.append("")

    lines.append("## 5. 首趟前补电窗口本身\n")
    for arm in ARMS:
        rows = [s for r in report[arm] for s in r["sessions"] if s["wtype"] == "first"]
        if rows:
            w0s = [ (s["w0"] % DAY) / 3600 for s in rows]; w1s = [ (s["w1"] % DAY) / 3600 for s in rows]
            starts = [ (s["start"] % DAY) / 3600 + (24 if s["start"] < 0 else 0) for s in rows]
            lines.append(f"- {arm}：窗口起点（前一日回场）中位 {st.median(w0s):.2f} h，终点（发车−占用）中位 {st.median(w1s):.2f} h；实际起充时刻中位 {st.median(starts):.2f} h（>24 表示前一日）")
    lines.append("")
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已写出 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
