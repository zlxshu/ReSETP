#!/usr/bin/env python3
"""表：四种充电安排在各充电窗口的充电电量与碳排量（4.4.2，2026-09-06）。

只证一句话：排放增加全部来自首趟出车前的补电窗口；只考虑碳强度的方案在每个窗口都已取到可达的最低排放。
形态：陈婉茹 2023 表 11 的"情形逐行 × 方案逐列组"壳——行＝三个充电窗口＋合计，列组＝四种充电安排，
每组三列：起充时刻（按电量加权的中位，前一日者标"前日"）、充电成本（元）、碳排量（kgCO$_2$），后两者为 10 次运算均值；
每行充电成本最低与碳排量最低各自加粗（用户 2026-09-06 定：图讲形状，表讲四方案×三窗口的账含起充时刻）。

窗口归类与排放核算与 diagnose_charging_windows_20260906.py 完全一致（那份脚本已核：近似账与求解器记录逐 run 零偏差）：
  第 k 趟前的补电按"第 k-1 趟回场 → 第 k 趟发车"归类：k=1 为首趟出车前；上一趟回场 ≤ 上午班结束且本趟发车 ≥ 下午班开始为午休；
  本趟发车 ≥ 下午班开始为下午趟间。
输出 docs/paper_v2/generated_tables/charging_windows_table.tex 的 tabular* 片段。
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAL = REPO / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv"
# 2026-09-06 用户："为何只考虑充电量和碳排放量，不考虑钱呢？充电量的意义是什么？"→ 电量列改为充电成本列（元），
# 每行成本最低与碳排量最低各自加粗；合计行与表10 的充电成本、电动车充电排放逐位一致（脚本内断言）。
SHIFT = REPO / "data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/shift_contract.json"
ARMS = [
    # 2026-09-10 用户令：删去第四种安排，名称改用文献用语
    ("无序充电", REPO / "solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MT-HGS", "asap"),
    ("电价引导有序充电", REPO / "solver/reports/charging_arrangements_20260906/cost_min", "cost_min"),
    ("碳强度引导有序充电", REPO / "solver/reports/charging_arrangements_20260906/carbon_min", "carbon_min"),
]
WINDOWS = [("first", "首次出车前"), ("lunch", "跨班次"), ("pm", "班次内")]
DAY, SLOT = 86400.0, 1800.0
OUT = REPO / "docs/paper_v2/generated_tables/charging_windows_table.tex"


def load_carbon():
    rows = [r for r in csv.DictReader(open(CAL, encoding="utf-8")) if r["city"] == "beijing" and r["date"] == "2025-02-12"]
    return {int(r["minute_of_day"]): float(r["carbon_factor_kgco2e_per_kwh"]) for r in rows}


def load_price():
    rows = [r for r in csv.DictReader(open(CAL, encoding="utf-8")) if r["city"] == "beijing" and r["date"] == "2025-02-12"]
    return {int(r["minute_of_day"]): float(r["depot_energy_cny_per_kwh"]) for r in rows}


def slot_of(second: float) -> int:
    return int((second % DAY) // 60 // 30) * 30


def session_emission(start, minutes, kwh, carbon):
    if minutes <= 0:
        return kwh * carbon[slot_of(start)]
    total, t, end = 0.0, start, start + minutes * 60
    while t < end - 1e-9:
        nxt = (t // SLOT + 1) * SLOT
        seg = min(nxt, end) - t
        total += kwh * (seg / (minutes * 60)) * carbon[slot_of(t)]
        t = nxt
    return total


def pick_run_paths(arm_dir: Path, statistic: str) -> list[str]:
    """mean=该臂全部 run；best=该臂 total_cost 最小的那一次（与表11 best 口径同一选取规则）。"""
    paths = sorted(glob.glob(str(arm_dir / "run_*/best_solution.json")))
    if not paths:
        raise SystemExit(f"{arm_dir}: 没有任何 run_*/best_solution.json")
    if statistic == "mean":
        return paths
    best_path, best_cost = None, None
    for p in paths:
        sol = json.load(open(p))
        tc = float(sol["evaluation"]["breakdown"]["total_cost"])
        if best_cost is None or tc < best_cost:
            best_cost, best_path = tc, p
    print(f"  → best（total_cost 最小）：{Path(best_path).parent.name}  total_cost={best_cost:.2f}", file=sys.stderr)
    return [best_path]


def arm_windows(paths: list[str], policy: str, carbon, price, am_end, pm_start):
    kwh = {w: 0.0 for w, _ in WINDOWS}; em = {w: 0.0 for w, _ in WINDOWS}; cost = {w: 0.0 for w, _ in WINDOWS}
    starts = {w: [] for w, _ in WINDOWS}
    ends = {w: [] for w, _ in WINDOWS}
    other = 0.0; n = 0; em_check = 0.0; em_rec = 0.0; cost_check = 0.0; cost_rec = 0.0
    for p in paths:
        sol = json.load(open(p)); meta = json.load(open(p.replace("best_solution.json", "metadata.json")))
        got = (meta.get("mechanism_closure") or {}).get("effective_charge_timing_policy")
        if got != policy or meta.get("status") != "COMPLETE":
            raise SystemExit(f"{p}: policy={got} status={meta.get('status')}")
        n += 1
        trips = {}
        for t in sol["trip_clock"]:
            trips.setdefault(t["physical_vehicle_id"], {})[t["trip_index"]] = t
        for duty in sol["individual"]["duties"]:
            tv = trips.get(duty["physical_vehicle_id"], {})
            for c in duty["charging_sessions"]:
                k = c["trip_index"]; start = c["charge_start_second"] + c["charge_day_offset"] * DAY
                dep = tv[k]["departure_second"]
                if k == 1:
                    w = "first"
                else:
                    w0 = tv[k - 1]["return_second"]
                    # 午休：上一趟回场在上午班结束前、本趟发车在下午班开始后；其余趟间（含极少的上午趟间）并入"趟间"，
                    # 使合计与表10 的充电电量/电动车充电排放逐位一致。
                    w = "lunch" if (w0 <= am_end + 1 and dep >= pm_start - 1) else "pm"
                e = session_emission(start, c["occupancy_minutes"], c["energy_kwh"], carbon)
                cc = session_emission(start, c["occupancy_minutes"], c["energy_kwh"], price)  # 同一分摊法算电费
                em_check += e; cost_check += cc
                if w is None:
                    other += c["energy_kwh"]
                    continue
                kwh[w] += c["energy_kwh"]; em[w] += e; cost[w] += cc
                starts[w].append((start / 3600.0, c["energy_kwh"]))
                ends[w].append(((start + c["occupancy_minutes"] * 60) / 3600.0, c["energy_kwh"]))
        em_rec += sol["evaluation"]["breakdown"]["E_ev_indirect"]; cost_rec += sol["evaluation"]["breakdown"]["cost_elec"]
    assert abs(em_check - em_rec) < 1e-6 * max(1.0, em_rec), (arm_dir, em_check, em_rec)
    assert abs(cost_check - cost_rec) < 1e-6 * max(1.0, cost_rec), (arm_dir, cost_check, cost_rec)
    return {w: (cost[w] / n, em[w] / n, kwh[w] / n, wmedian(starts[w]), wmedian(ends[w])) for w, _ in WINDOWS}, other / n, n


def wmedian(pairs):
    pairs = sorted(pairs); tot = sum(w for _, w in pairs); acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= tot / 2:
            return v
    return float("nan")


def fmt_time(h: float) -> str:
    prev = "前日" if h < 0 else ""
    hh = h % 24
    return f"{prev}{int(hh):02d}:{int(round((hh - int(hh)) * 60)):02d}"


def fmt(x): return f"{x:.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--statistic",
        choices=("mean", "best"),
        default="mean",
        help="每臂取值口径：mean=该臂全部 run 的均值（默认，行为不变）；"
        "best=只用该臂 total_cost 最小的那一次运算（与表11 best 口径同一 run）",
    )
    args = ap.parse_args()
    carbon = load_carbon(); price = load_price(); shifts = json.load(open(SHIFT))["shifts"]
    am_end = shifts["AM"]["end_minute"] * 60; pm_start = shifts["PM"]["start_minute"] * 60
    data = []
    for header, d, pol in ARMS:
        paths = pick_run_paths(d, args.statistic)
        w, other, n = arm_windows(paths, pol, carbon, price, am_end, pm_start)
        data.append(w)
        tot_k = sum(v[0] for v in w.values()); tot_e = sum(v[1] for v in w.values())
        print(f"[{pol:16s}] n={n} " + " ".join(f"{lab} {fmt_time(v[3])} {v[0]:.2f}元/{v[1]:.2f}kg（{v[2]:.1f}kWh）" for (key, lab), v in zip(WINDOWS, w.values())) + f" 合计 {tot_k:.2f}元/{tot_e:.2f}kg", file=sys.stderr)
    # 竖排：窗口分块 × 方案逐行（13 列横排超宽 23.9 pt，2026-09-06 改为此式；块内成本最低与碳排量最低各自加粗）
    names = [h for h, _, _ in ARMS]
    lines = [r"  \begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}llccccc@{}}", r"    \toprule",
             r"    充电阶段 & 充电安排 & 开始时刻 & 结束时刻 & 电量（kWh） & 成本（元） & 排放（kgCO$_2$）\\",
             r"    \midrule"]
    blocks = [(lab, [(d[key][0], d[key][1], fmt_time(d[key][3]), fmt_time(d[key][4]), d[key][2]) for d in data]) for key, lab in WINDOWS]
    blocks.append(("合计", [(sum(v[0] for v in d.values()), sum(v[1] for v in d.values()), "", "", sum(v[2] for v in d.values())) for d in data]))
    for bi, (lab, vals) in enumerate(blocks):
        if bi:
            lines.append(r"    \midrule")
        for ai, (k, e, tm, end_tm, energy) in enumerate(vals):
            kk = fmt(k); ee = fmt(e)
            first = (r"\multirow{" + str(len(ARMS)) + "}{*}{" + lab + "}") if ai == 0 else ""
            lines.append(f"    {first} & {names[ai]} & {tm} & {end_tm} & {fmt(energy)} & {kk} & {ee}\\\\")
    lines += [r"    \bottomrule", r"  \end{tabular*}"]
    tex = "\n".join(lines) + "\n"
    if not args.dry_run:
        args.out.write_text(tex, encoding="utf-8"); print(f"已写出 {args.out}", file=sys.stderr)
    print(tex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
