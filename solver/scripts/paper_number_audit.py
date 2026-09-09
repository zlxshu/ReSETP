#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文 docs/paper_v2/paper_main.tex 数字审计（2026-09-09）。

规矩（用户 2026-09-09 令）：正文与表里印出来的每一个数字，都必须由本脚本从结果文件
重新算一遍，不许用心算 / 大模型算；印出来的字符串与"全精度值按四舍五入到该位"必须逐位相同，
差 0.01 也算错。

用法：
    PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src' \
        .public-hgs-venv/bin/python3 solver/scripts/paper_number_audit.py

只读脚本：不跑求解器，不改任何论文文件。输出一张核对表到 stdout，
不一致的行以 MISMATCH 开头。台账写在 docs/paper_v2/number_audit_20260909.md。

口径说明
--------
* 四舍五入一律用 decimal.Decimal + ROUND_HALF_UP，绝不用 float 的 round()（后者是
  banker's rounding，2.675 会进成 2.67）。
* 每个量先取全精度浮点，再一次性量化到论文印出的小数位。
* 凡是论文里声称"某和 / 某差等于某值"的地方，同时算两种：
    diff_of_rounded  = 各单元格四舍五入后再相减 / 相加
    rounded_of_diff  = 全精度相减 / 相加后再四舍五入
  两者不同的地方要在正文里写明"表中数值为四舍五入后的结果"。
* 任何全精度值离四舍五入进位边界小于 1e-9 的，标记 BOUNDARY，人工复核。
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEX = REPO / "docs/paper_v2/paper_main.tex"
GEN = REPO / "docs/paper_v2/generated_tables"

# ---------------------------------------------------------------- rounding ---


def q(x, d: int) -> Decimal:
    """把 x 按 ROUND_HALF_UP 量化到小数点后 d 位，返回 Decimal。

    x 已是 Decimal 时按原值量化（用于标准算例那种"精确十进制"的量）；
    是 float 时取其精确二进制值量化。"""
    return (x if isinstance(x, Decimal) else Decimal(x)).quantize(
        Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)


def s(x, d: int) -> str:
    return f"{q(x, d):.{d}f}"


def boundary(x, d: int, eps: float = 1e-9) -> bool:
    """全精度值是否贴着四舍五入的进位边界（差一点点就翻一档）。"""
    scaled = abs(float(x)) * (10 ** d)  # noqa: E501
    frac = scaled - int(scaled)
    return abs(frac - 0.5) < eps


RESULTS: list[tuple] = []

# 口径开关（用户 2026-09-10 令，口径 A）
#   full    ：正文里由表格单元格导出的量，用全精度重算后再舍入（2026-09-09 口径）。
#   printed ：正文里凡是"表格单元格之间的差 / 和 / 比 / 百分比"，一律用**印出来的单元格**
#             重算，使读者拿计算器按表里的数就能复现；表内 Average 行同理，
#             取该列印出值的均值。表格单元格本身仍由全精度结果舍入得到。
CONV = "full"


def checkc(section: str, label: str, printed: str, full_value, cell_value,
           decimals: int, note: str = ""):
    """由表格单元格导出的正文数字：两种口径各算一份，按 CONV 选一份作判据。"""
    ref = cell_value if CONV == "printed" else full_value
    extra = f"[全精度={s(full_value, decimals)} 印格={s(cell_value, decimals)}]"
    return check(section, label, printed, ref, decimals,
                 (note + " " + extra).strip() if note else extra)


def check(section: str, label: str, printed: str, value, decimals: int, note: str = ""):
    """printed = 论文里那串字符；value = 本脚本从结果文件算出的全精度值。"""
    got = s(value, decimals)
    ok = (got == printed)
    flag = "OK      " if ok else "MISMATCH"
    if ok and boundary(value, decimals):
        flag = "BOUNDARY"
    RESULTS.append((flag, section, label, printed, got, str(value), note))
    return ok


def check_str(section: str, label: str, printed: str, got: str, note: str = ""):
    ok = (got == printed)
    RESULTS.append(("OK      " if ok else "MISMATCH", section, label, printed, got, got, note))
    return ok


# ------------------------------------------------------------ source loading ---


def jload(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def bd(path):
    """一个 run 的官方 breakdown。"""
    return jload(path)["evaluation"]["breakdown"]


def arm_runs(root):
    """一个臂下所有 run 的 breakdown，按 run 目录名排序。"""
    out = []
    for p in sorted(Path(REPO / root).glob("run_*/best_solution.json")):
        out.append(bd(p))
    if not out:
        raise SystemExit(f"没有 run: {root}")
    return out


def arm_mean(root, key, scale=1.0):
    rs = arm_runs(root)
    return st.mean(r[key] for r in rs) * scale


SRC = {}


def load_sources():
    # --- 4.1.2 / 4.2.2 最终解：ablation_v6 MTC-HGS run_07（total_cost 最小的一次） ---
    SRC["final"] = bd("solver/reports/ablation_v6_20260906/MTC-HGS/run_07/best_solution.json")
    SRC["final_run"] = "solver/reports/ablation_v6_20260906/MTC-HGS/run_07"
    # --- 4.2.2 三臂 ---
    for arm in ("M-HGS", "MT-HGS", "MTC-HGS"):
        rs = arm_runs(f"solver/reports/ablation_v6_20260906/{arm}")
        SRC[f"abl_{arm}_runs"] = rs
        SRC[f"abl_{arm}_best"] = min(rs, key=lambda r: r["total_cost"])
    # --- 4.3 车队配置：每档枚举分法，最低成本分法跑 3 次取最优 ---
    tiers = {}
    root = REPO / "solver/reports/fleet_composition_formal_v3_20260904"
    for tier in sorted(os.listdir(root)):
        td = root / tier
        if not td.is_dir():
            continue
        cands = []
        for sp in sorted(os.listdir(td)):
            runs = sorted((td / sp).glob("run_*/best_solution.json"))
            if not runs:
                continue
            cands.append(min((bd(p) for p in runs), key=lambda r: r["total_cost"]))
        tiers[tier] = min(cands, key=lambda r: r["total_cost"])
    SRC["fleet"] = tiers
    # --- 4.4 三种充电安排（基准条件） ---
    SRC["cc"] = {
        "asap": arm_runs("solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MT-HGS"),
        "cost_min": arm_runs("solver/reports/charging_arrangements_20260906/cost_min"),
        "carbon_min": arm_runs("solver/reports/charging_arrangements_20260906/carbon_min"),
    }
    # --- 4.4.3 四格 ---
    SRC["grid"] = {
        ("beijing", 0.2, "asap"): arm_runs("solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MT-HGS"),
        ("beijing", 0.2, "carbon_min"): arm_runs("solver/reports/charging_arrangements_20260906/carbon_min"),
        ("midday", 0.2, "asap"): arm_runs("solver/reports/grid2x2_v3_20260906/midday/P=0.2/MT-HGS"),
        ("midday", 0.2, "carbon_min"): arm_runs("solver/reports/carbon_min_two_conditions_20260910/midday_P0.2"),
        ("beijing", 1.0, "asap"): arm_runs("solver/reports/grid2x2_v3_20260906/beijing/P=1.0/MT-HGS"),
        ("beijing", 1.0, "carbon_min"): arm_runs("solver/reports/carbon_min_two_conditions_20260910/beijing_P1.0"),
        ("midday", 1.0, "asap"): arm_runs("solver/reports/grid2x2_v3_20260906/midday/P=1.0/MT-HGS"),
        ("midday", 1.0, "carbon_min"): arm_runs("solver/reports/charging_arrangements_midday_P1.0_20260909/carbon_min"),
        ("midday", 1.0, "cost_min"): arm_runs("solver/reports/charging_arrangements_midday_P1.0_20260909/cost_min"),
    }
    # --- 4.5 / 4.6 ---
    SRC["syn"] = jload(REPO / "solver/reports/synergy_v7_20260909/synergy_table_v7.json")
    # 充电电量不在聚合 json 里，回到每个 run 的官方 breakdown 重算
    for arm in ("independent", "joint"):
        kwh, ev_ind = [], []
        for r in SRC["syn"]["arms"][arm]["runs"]:
            b = bd(REPO / r["path"] / "best_solution.json")
            kwh.append(b["electricity_kwh"]); ev_ind.append(b["E_ev_indirect"])
        SRC[f"syn_{arm}_kwh"] = kwh
        SRC[f"syn_{arm}_ev_ind"] = ev_ind
    # --- 4.7 ---
    with open(REPO / "solver/reports/dynamic_v7_20260909/raw_runs.csv", encoding="utf-8") as fh:
        SRC["dyn"] = {r["arm"]: r for r in csv.DictReader(fh)}
    with open(REPO / "solver/reports/dynamic_v7_20260909/dynamic_events.csv", encoding="utf-8") as fh:
        SRC["dyn_batches"] = list(csv.DictReader(fh))
    # 各臂最后一个批次的路径快照 -> 该臂最终服务的客户集合（口径 A 下"新增订单插入次数"用）
    SRC["dyn_served"] = {}
    for arm in {b["arm"] for b in SRC["dyn_batches"]}:
        last = max((b for b in SRC["dyn_batches"] if b["arm"] == arm),
                   key=lambda b: int(b["batch_index"]))
        SRC["dyn_served"][arm] = {n for r in json.loads(last["route_snapshot_after_json"])["routes"]
                                  for n in r["node_sequence"] if n.startswith("C")}
    # 事件定义的权威来源：算例自带的动态事件流（论文表 5 即由它排版）
    with open(REPO / "data/dynamic_streams/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd_mixed_events/events.tsv",
              encoding="utf-8") as fh:
        SRC["dyn_events"] = list(csv.DictReader(fh, delimiter="\t"))
    # --- 逐时碳强度日历 ---
    cal = REPO / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv"
    with open(cal, encoding="utf-8") as fh:
        SRC["cal"] = [r for r in csv.DictReader(fh)
                      if r["city"] == "beijing" and r["date"] == "2025-02-12"]
    # --- 算例订单 ---
    inst = (REPO / "data/ChinaInstances/china81_final_suite_v2_20260815/instances"
            / "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd")
    with open(inst / "orders.csv", encoding="utf-8") as fh:
        SRC["orders"] = list(csv.DictReader(fh))
    SRC["inst_dir"] = inst
    # --- 标准算例 ---
    pub = {}
    root = REPO / "solver/reports/public28_formal_20260830"
    for d in sorted(os.listdir(root)):
        if not (root / d).is_dir():
            continue
        vals = []
        for c in sorted((root / d).glob("run_*/raw_runs.csv")):
            with open(c, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    # cost 为整数（千分之一单位）。必须用 Decimal 精确相除：
                    # float(4771155)/1000 = 4771.154999…，ROUND_HALF_UP 会错判成 4771.15。
                    vals.append(Decimal(r["cost"]) / Decimal(1000))
        if vals:
            pub[d] = vals
    SRC["pub"] = pub
    # --- 生成表原文（用于逐格核对） ---
    for name in ("carbon_charging_table", "charging_windows_table", "two_conditions_table",
                 "carbon_charging_solved_table", "final_solution_trip_rows"):
        SRC[name] = (GEN / f"{name}.tex").read_text(encoding="utf-8")


# ------------------------------------------------------------------ helpers ---


# ---------------------------------------------- 印出的表格单元格（口径 A 用） ---


def gen_cells(name: str) -> dict:
    r"""读 generated_tables/<name>.tex，返回 {行名: [Decimal, ...]}（行名去掉 \makecell 等标记）。"""
    out = {}
    for line in (GEN / f"{name}.tex").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if ("&" not in line or "multicolumn" in line or "cmidrule" in line
                or line.startswith(("\\toprule", "\\midrule", "\\bottomrule",
                                    "\\begin", "\\end", "\\multirow"))):
            continue
        parts = [c.strip() for c in line.replace("\\\\", "").split("&")]
        lbl = re.sub(r"\\makecell\{|\}$", "", parts[0]).replace("\\\\", "").strip()
        vals = []
        for c in parts[1:]:
            c = c.replace("\\textbf{", "").replace("}", "").strip()
            if re.fullmatch(r"-?\d+(\.\d+)?", c):
                vals.append(Decimal(c))
            else:
                vals = None
                break
        if vals:
            out[lbl] = vals
    return out


def D(x) -> Decimal:
    return Decimal(str(x))


def m(runs, key, scale=1.0):
    return st.mean(r[key] for r in runs) * scale


def fleetcnt(runs):
    return Counter((r["n_veh_cv"], r["n_veh_ev"]) for r in runs)


def pct_change(a, b):
    """b 相对 a 的变化百分比。"""
    return (b - a) / a * 100.0


# ==================================================================== 4.1 ====


def audit_41():
    S = "4.1"
    # 参数表里两个推导值
    check(S, "电池折旧（元/km）=59000/241350", "0.2445", 59000.0 / 241350.0, 4)
    check(S, "电动车里程成本（元/km）=0.6700+电池折旧", "0.9145", 0.6700 + 59000.0 / 241350.0, 4)
    # 需求合计
    dem = sum(float(r["demand_kg"]) for r in SRC["orders"] if r.get("demand_kg"))
    check(S, "客户需求合计（kg）", "13264", dem, 0)
    check(S, "初始客户数", "50", len(SRC["orders"]), 0)

    f = SRC["final"]
    tc = f["total_cost"]
    S = "4.1.2"
    check(S, "车辆启动成本（元）", "1150.00", f["cost_fix"], 2)
    check(S, "启动成本占比（%）", "44.20", f["cost_fix"] / tc * 100, 2)
    check(S, "行驶成本（元）", "910.40", f["cost_km"], 2)
    check(S, "行驶成本占比（%）", "34.99", f["cost_km"] / tc * 100, 2)
    check(S, "油耗成本（元）", "321.84", f["cost_fuel"], 2)
    check(S, "油耗成本占比（%）", "12.37", f["cost_fuel"] / tc * 100, 2)
    check(S, "充电成本（元）", "181.06", f["cost_elec"], 2)
    check(S, "充电成本占比（%）", "6.96", f["cost_elec"] / tc * 100, 2)
    check(S, "碳排放成本（元）", "38.31", f["cost_carbon"], 2)
    check(S, "碳排放成本占比（%）", "1.47", f["cost_carbon"] / tc * 100, 2)
    # 79.20% —— 全精度和 vs 印出来两格之和
    full = (f["cost_fix"] + f["cost_km"]) / tc * 100
    check(S, "启动+行驶占比（%）全精度和", "79.20", full, 2,
          f"印出的两格之和={Decimal('44.20')+Decimal('34.99')}（差 0.01，属四舍五入）")
    check(S, "燃油车数", "2", f["n_veh_cv"], 0)
    check(S, "电动车数", "3", f["n_veh_ev"], 0)
    # 趟数
    rows = [l for l in SRC["final_solution_trip_rows"].splitlines()
            if l.startswith("{[") ]
    check(S, "配送趟数", "15", len(rows), 0)
    check(S, "车均趟数", "3.00", len(rows) / (f["n_veh_cv"] + f["n_veh_ev"]), 2)
    cv_trips = sum(1 for l in rows if float(l.split("&")[4]) > 0)
    ev_trips = len(rows) - cv_trips
    check(S, "燃油车趟数", "7", cv_trips, 0)
    check(S, "电动车趟数", "8", ev_trips, 0)
    # 表内印出的单元格（列：1 距离 / 2 成本 / 4 油耗 / 5 电耗 / 6 碳排放 / 8 装载率）
    cell = lambda l, i: Decimal(l.split("&")[i].replace("\\\\", "").strip())
    ev_rows = [l for l in rows if cell(l, 5) > 0]
    cv_rows = [l for l in rows if cell(l, 5) == 0]
    tot_line = [l for l in SRC["final_solution_trip_rows"].splitlines()
                if l.startswith("合计")][0]
    c_dist_tot = cell(tot_line, 1)
    c_em_tot = cell(tot_line, 6)
    c_dist_ev = sum(cell(l, 1) for l in ev_rows)
    c_dist_cv = sum(cell(l, 1) for l in cv_rows)
    c_em_ev = sum(cell(l, 6) for l in ev_rows)
    c_em_cv = sum(cell(l, 6) for l in cv_rows)
    checkc(S, "电动车行驶里程（km）", "716.07", f["distance_ev"] / 1000.0,
           c_dist_ev, 2, "表内 8 个电动车趟距离之和")
    checkc(S, "电动车里程占比（%）", "68.61", f["distance_ev"] / f["distance_total"] * 100,
           c_dist_ev / c_dist_tot * 100, 2)
    checkc(S, "燃油车直接排放（kg）", "113.67", f["E_cv_direct"], c_em_cv, 2,
           "表内 7 个燃油车趟碳排放之和")
    checkc(S, "燃油车排放占比（%）", "59.35", f["E_cv_direct"] / f["E_total"] * 100,
           c_em_cv / c_em_tot * 100, 2)
    checkc(S, "电动车充电排放（kg）", "77.86", f["E_ev_indirect"], c_em_ev, 2,
           "表内 8 个电动车趟碳排放之和")
    checkc(S, "电动车排放占比（%）", "40.65", f["E_ev_indirect"] / f["E_total"] * 100,
           c_em_ev / c_em_tot * 100, 2)
    ev_pk = f["E_ev_indirect"] / (f["distance_ev"] / 1000.0)
    cv_pk = f["E_cv_direct"] / (f["distance_cv"] / 1000.0)
    c_ev_pk, c_cv_pk = c_em_ev / c_dist_ev, c_em_cv / c_dist_cv
    checkc(S, "电动车单位里程排放（kg/km）", "0.109", ev_pk, c_ev_pk, 3)
    checkc(S, "燃油车单位里程排放（kg/km）", "0.347", cv_pk, c_cv_pk, 3)
    checkc(S, "单位里程排放降幅（%）", "68.66", (cv_pk - ev_pk) / cv_pk * 100,
           (c_cv_pk - c_ev_pk) / c_cv_pk * 100, 2,
           "由表内单元格算出的两个单位里程排放相比；"
           f"若改用正文已舍入的 0.109/0.347 则为 "
           f"{s((Decimal('0.347')-Decimal('0.109'))/Decimal('0.347')*100, 2)}")
    # 平均装载率：15 趟装载率的算术均值（全精度）
    loads = [float(l.split("&")[8].replace("\\\\", "").strip()) for l in rows]
    check(S, "平均装载率（%）（印出值的均值）", "51.57", st.mean(loads), 2,
          "注：由生成表 15 行装载率（已二位）取均值；源全精度均值见台账")


# ==================================================================== 4.2 ====


def audit_42():
    S = "4.2.1"
    tab = parse_benchmark_table()
    # 本文算法两列：从 public28_formal_20260830 重算
    for inst, (bks, cols) in tab["rows"].items():
        vals = SRC["pub"].get(inst)
        if not vals:
            RESULTS.append(("NOSOURCE", S, f"{inst} 本文算法", "-", "-", "-", "无 run"))
            continue
        check(S, f"{inst} 本文Best", cols["ours_best"], min(vals), 2, f"n={len(vals)}")
        check(S, f"{inst} 本文Avg", cols["ours_avg"], sum(vals) / len(vals), 2, f"n={len(vals)}")
    # Average 行：28 个算例的均值
    names = list(tab["rows"])
    for key, idx in (("bks", None), ("vcgp_best", "vcgp_best"), ("vcgp_avg", "vcgp_avg"),
                     ("mdfiha_best", "mdfiha_best"), ("mdfiha_avg", "mdfiha_avg"),
                     ("etga_best", "etga_best"), ("etga_avg", "etga_avg")):
        if idx is None:
            vals = [Decimal(tab["rows"][n][0]) for n in names]
            printed = tab["average"]["bks"]
        else:
            vals = [Decimal(tab["rows"][n][1][idx]) for n in names]
            printed = tab["average"][idx]
        check(S, f"Average 行 {key}（对印出各行取均值）", printed,
              sum(vals) / len(vals), 2)
    ours_best = [min(SRC["pub"][n]) for n in names]
    ours_avg = [sum(SRC["pub"][n]) / len(SRC["pub"][n]) for n in names]
    check(S, "Average 行 本文Best（全精度）", tab["average"]["ours_best"],
          sum(ours_best) / len(ours_best), 2)
    check(S, "Average 行 本文Avg（全精度）", tab["average"]["ours_avg"],
          sum(ours_avg) / len(ours_avg), 2)
    # Nbest：逐题最低的 Best
    nb = {"vcgp": 0, "mdfiha": 0, "etga": 0, "ours": 0}
    for i, n in enumerate(names):
        c = tab["rows"][n][1]
        cand = {"vcgp": float(c["vcgp_best"]), "mdfiha": float(c["mdfiha_best"]),
                "etga": float(c["etga_best"]), "ours": float(c["ours_best"])}
        lo = min(cand.values())
        for k, v in cand.items():
            if v == lo:
                nb[k] += 1
    for k, printed in (("vcgp", "0"), ("mdfiha", "0"), ("etga", "1"), ("ours", "27")):
        check(S, f"Nbest {k}", printed, nb[k], 0, "按表内印出的 Best 逐题取最低")
    # gap 百分比。口径已定：(该列 Average − BKS Average) / BKS Average，
    # 其中 Average 用表内印出的单元格（文献三列本来就只有印出值可用；本文两列的
    # Average 单元格已在上面核过等于全精度均值的正确舍入）。同时打印"逐题比取均值"
    # 与"全精度均值比"两种备选口径，供台账留痕。
    B = Decimal(tab["average"]["bks"])
    bkss = [Decimal(tab["rows"][n][0]) for n in names]
    for name, col, printed_best, printed_avg in (
            ("VCGP", "vcgp", "1.78", "2.52"),
            ("MDFIHA", "mdfiha", "1.61", "2.01"),
            ("MDFIHA-ETGA", "etga", "1.12", "1.45")):
        for lbl, sfx, pr in (("Best", "best", printed_best), ("Avg", "avg", printed_avg)):
            cell = Decimal(tab["average"][f"{col}_{sfx}"])
            per = [Decimal(tab["rows"][n][1][f"{col}_{sfx}"]) for n in names]
            alt = sum((x - y) / y * 100 for x, y in zip(per, bkss)) / len(per)
            check(S, f"{name} {lbl} 相对 BKS（%）", pr, (cell - B) / B * 100, 2,
                  f"备选口径 逐题比取均值={s(alt, 2)}")
    for lbl, key, pr in (("Best", "ours_best", "0.35"), ("Avg", "ours_avg", "0.73")):
        cell = Decimal(tab["average"][key])
        check(S, f"本文 {lbl} 相对 BKS（%）", pr, (cell - B) / B * 100, 2)
    # PR17B 与 BKS 相同
    check_str(S, "PR17B 本文Best 是否等于 BKS", "相同",
              "相同" if s(min(SRC["pub"]["PR17B"]), 2) == tab["rows"]["PR17B"][0] else "不同",
              f'本文Best 精确值={min(SRC["pub"]["PR17B"])} BKS={tab["rows"]["PR17B"][0]}')

    # ---- 4.2.2 消融 ----
    S = "4.2.2"
    printed = {"M-HGS": ("2704.00", "2718.73", "0.54"),
               "MT-HGS": ("2641.17", "2667.32", "0.99"),
               "MTC-HGS": ("2601.61", "2631.84", "1.16")}
    for arm, (pb, pa, pg) in printed.items():
        rs = SRC[f"abl_{arm}_runs"]
        best = min(r["total_cost"] for r in rs)
        avg = st.mean(r["total_cost"] for r in rs)
        check(S, f"{arm} 最优解（元）", pb, best, 2, f"n={len(rs)}")
        check(S, f"{arm} 平均值（元）", pa, avg, 2, f"n={len(rs)}")
        check(S, f"{arm} Gap（%）=(均值-最优)/最优", pg, (avg - best) / best * 100, 2)
    mb, tb, cb = (SRC["abl_M-HGS_best"], SRC["abl_MT-HGS_best"], SRC["abl_MTC-HGS_best"])
    check(S, "M-HGS 最优方案燃油车数", "6", mb["n_veh_cv"], 0)
    check(S, "M-HGS 最优方案电动车数", "0", mb["n_veh_ev"], 0)
    check(S, "M-HGS 最优方案碳排放（kg）", "319.24", mb["E_total"], 2)
    check(S, "MT-HGS 最优方案燃油车数", "2", tb["n_veh_cv"], 0)
    check(S, "MT-HGS 最优方案电动车数", "3", tb["n_veh_ev"], 0)
    check(S, "MT-HGS 最优方案碳排放（kg）", "172.33", tb["E_total"], 2)
    check(S, "碳排放降幅 M→MT（%）", "46.02", (mb["E_total"] - tb["E_total"]) / mb["E_total"] * 100, 2)
    check(S, "总成本降幅 M→MT（%）", "2.32", (mb["total_cost"] - tb["total_cost"]) / mb["total_cost"] * 100, 2)
    check(S, "MTC 最优方案充电成本（元）", "181.06", cb["cost_elec"], 2)
    check(S, "MT 最优方案充电成本（元）", "224.46", tb["cost_elec"], 2)
    d_full = tb["cost_elec"] - cb["cost_elec"]
    check(S, "充电成本差（元）全精度", "43.40", d_full, 2,
          f"印出两格之差={Decimal('224.46')-Decimal('181.06')}")
    check(S, "总成本降幅 MT→MTC（%）", "1.50",
          (tb["total_cost"] - cb["total_cost"]) / tb["total_cost"] * 100, 2)
    mt_avg = st.mean(r["total_cost"] for r in SRC["abl_MT-HGS_runs"])
    mtc_avg = st.mean(r["total_cost"] for r in SRC["abl_MTC-HGS_runs"])
    check(S, "平均总成本降幅 MT→MTC（%）", "1.33", (mt_avg - mtc_avg) / mt_avg * 100, 2)
    check(S, "MTC 平均碳排放（kg）", "190.33", st.mean(r["E_total"] for r in SRC["abl_MTC-HGS_runs"]), 2)
    check(S, "MT 平均碳排放（kg）", "189.81", st.mean(r["E_total"] for r in SRC["abl_MT-HGS_runs"]), 2)
    check(S, "MTC 最优方案电动车充电排放（kg）", "77.86", cb["E_ev_indirect"], 2)
    check(S, "MT 最优方案电动车充电排放（kg）", "58.66", tb["E_ev_indirect"], 2)
    gaps = []
    for arm in ("M-HGS", "MT-HGS", "MTC-HGS"):
        rs = SRC[f"abl_{arm}_runs"]
        b = min(r["total_cost"] for r in rs)
        gaps.append((st.mean(r["total_cost"] for r in rs) - b) / b * 100)
    check_str(S, "三臂 Gap 是否均 <1.2%", "是", "是" if max(gaps) < 1.2 else f"否（max={max(gaps):.4f}）")


BENCH_RE = re.compile(r"^\s{4}(PR\d\d[AB]) & " + " & ".join([r"([\d.]+)"] * 9) + r"\\\\")


def parse_benchmark_table():
    rows = {}
    avg = {}
    for line in TEX.read_text(encoding="utf-8").splitlines():
        mm = BENCH_RE.match(line)
        if mm:
            g = mm.groups()
            rows[g[0]] = (g[1], {"vcgp_best": g[2], "vcgp_avg": g[3],
                                 "mdfiha_best": g[4], "mdfiha_avg": g[5],
                                 "etga_best": g[6], "etga_avg": g[7],
                                 "ours_best": g[8], "ours_avg": g[9]})
        if line.strip().startswith("Average &"):
            g = re.findall(r"[\d.]+", line)
            avg = {"bks": g[0], "vcgp_best": g[1], "vcgp_avg": g[2],
                   "mdfiha_best": g[3], "mdfiha_avg": g[4], "etga_best": g[5],
                   "etga_avg": g[6], "ours_best": g[7], "ours_avg": g[8]}
    return {"rows": rows, "average": avg}


# ==================================================================== 4.3 ====

FLEET_PRINTED = {
    "6-0": ("1020.00", "716.30", "0.00", "903.86", "63.85", "319.24", "2704.00"),
    "5-1": ("1120.00", "759.30", "66.40", "662.66", "51.73", "258.66", "2660.10"),
    "4-2": ("1220.00", "786.49", "105.69", "483.28", "42.48", "212.38", "2637.94"),
    "3-3": ("1320.00", "815.56", "150.59", "312.86", "34.93", "174.66", "2633.94"),
    "2-4": ("1420.00", "829.59", "168.55", "210.95", "29.70", "148.49", "2658.79"),
    "1-5": ("1520.00", "836.84", "183.73", "121.76", "25.77", "128.83", "2688.10"),
    "0-6": ("1620.00", "877.22", "212.96", "0.00", "19.69", "98.43", "2729.86"),
}


def audit_43():
    S = "4.3"
    keys = ("cost_fix", "cost_km", "cost_elec", "cost_fuel", "cost_carbon", "E_total", "total_cost")
    names = ("启动成本", "行驶成本", "充电成本", "油耗成本", "碳成本", "碳排量", "总成本")
    for tier, printed in FLEET_PRINTED.items():
        r = SRC["fleet"][tier]
        for k, nm, p in zip(keys, names, printed):
            check(S, f"表 {tier} {nm}", p, r[k], 2)
    best = SRC["fleet"]["3-3"]["total_cost"]
    allcv = SRC["fleet"]["6-0"]["total_cost"]
    allev = SRC["fleet"]["0-6"]["total_cost"]
    t42 = SRC["fleet"]["4-2"]["total_cost"]
    check(S, "每替换1辆启动成本增量（元）", "100.00",
          SRC["fleet"]["5-1"]["cost_fix"] - SRC["fleet"]["6-0"]["cost_fix"], 2)
    check(S, "纯燃油较最佳增加（元）", "70.06", allcv - best, 2,
          f"印出两格之差={Decimal('2704.00')-Decimal('2633.94')}")
    check(S, "纯燃油较最佳增加（%）", "2.66", (allcv - best) / best * 100, 2)
    check(S, "纯电动较最佳增加（元）", "95.92", allev - best, 2,
          f"印出两格之差={Decimal('2729.86')-Decimal('2633.94')}")
    check(S, "纯电动较最佳增加（%）", "3.64", (allev - best) / best * 100, 2)
    check(S, "4/2 与最佳之差（元）", "4.00", t42 - best, 2,
          f"印出两格之差={Decimal('2637.94')-Decimal('2633.94')}")
    check(S, "纯电动较纯燃油碳排降幅（%）", "69.17",
          (SRC["fleet"]["6-0"]["E_total"] - SRC["fleet"]["0-6"]["E_total"]) / SRC["fleet"]["6-0"]["E_total"] * 100, 2)


# ==================================================================== 4.4 ====


def audit_44():
    S = "4.4.1"
    cal = SRC["cal"]
    cf = [float(r["carbon_factor_kgco2e_per_kwh"]) for r in cal]
    check(S, "碳强度下限（kg/kWh）", "0.154", min(cf), 3)
    check(S, "碳强度上限（kg/kWh）", "0.644", max(cf), 3)
    check(S, "碳强度峰谷比", "4.18", max(cf) / min(cf), 2)
    check(S, "碳强度峰谷差（kg/kWh）接近0.5", "0.49", max(cf) - min(cf), 2, "正文只说'接近0.5'")

    A, P, C = SRC["cc"]["asap"], SRC["cc"]["cost_min"], SRC["cc"]["carbon_min"]
    CC = gen_cells("carbon_charging_table")   # 列序：无序 / 电价引导 / 碳强度引导
    checkc(S, "电价引导较无序 总成本降（元）", "27.09",
           m(A, "total_cost") - m(P, "total_cost"),
           CC["总成本（元）"][0] - CC["总成本（元）"][1], 2)
    checkc(S, "电价引导较无序 总成本降（%）", "1.02",
           (m(A, "total_cost") - m(P, "total_cost")) / m(A, "total_cost") * 100,
           (CC["总成本（元）"][0] - CC["总成本（元）"][1]) / CC["总成本（元）"][0] * 100, 2)
    checkc(S, "电价引导 燃油直接排放减少（kg）", "15.17",
           m(A, "E_cv_direct") - m(P, "E_cv_direct"),
           CC["燃油车直接排放（kgCO$_2$）"][0] - CC["燃油车直接排放（kgCO$_2$）"][1], 2)
    checkc(S, "电价引导 充电排放增加（kg）", "22.33",
           m(P, "E_ev_indirect") - m(A, "E_ev_indirect"),
           CC["电动车充电排放（kgCO$_2$）"][1] - CC["电动车充电排放（kgCO$_2$）"][0], 2)
    checkc(S, "电价引导 总排放净增（kg）", "7.16",
           m(P, "E_total") - m(A, "E_total"),
           CC["总排放（kgCO$_2$）"][1] - CC["总排放（kgCO$_2$）"][0], 2)
    checkc(S, "碳强度引导 充电排放减少（kg）", "7.59",
           m(A, "E_ev_indirect") - m(C, "E_ev_indirect"),
           CC["电动车充电排放（kgCO$_2$）"][0] - CC["电动车充电排放（kgCO$_2$）"][2], 2)
    checkc(S, "碳强度引导 总排放增加（kg）", "1.36",
           m(C, "E_total") - m(A, "E_total"),
           CC["总排放（kgCO$_2$）"][2] - CC["总排放（kgCO$_2$）"][0], 2)
    fc = fleetcnt(C)
    n45 = sum(v for (cv, ev), v in fc.items() if cv in (4, 5))
    check(S, "碳强度引导 10次中燃油车4或5辆的次数", "4", n45, 0, f"构型计数={dict(fc)}")
    # 2油3电子集均值
    sub = lambda rs: [r for r in rs if (r["n_veh_cv"], r["n_veh_ev"]) == (2, 3)]
    sA, sP, sC = sub(A), sub(P), sub(C)
    note = f"nA={len(sA)} nP={len(sP)} nC={len(sC)}"
    check(S, "[2油3电子集] 电价引导充电成本低（元）", "43.84",
          m(sA, "cost_elec") - m(sP, "cost_elec"), 2, note)
    check(S, "[2油3电子集] 电价引导碳排量高（kg）", "23.82",
          m(sP, "E_total") - m(sA, "E_total"), 2, note)
    check(S, "[2油3电子集] 碳强度引导充电成本低（元）", "10.16",
          m(sA, "cost_elec") - m(sC, "cost_elec"), 2, note)
    check(S, "[2油3电子集] 碳强度引导碳排量低（kg）", "2.54",
          m(sA, "E_total") - m(sC, "E_total"), 2, note)

    # ---- 4.4.2 窗口表已由 build_charging_windows_table.py 逐位复现；此处只核正文导出量 ----
    S = "4.4.2"
    W = parse_windows_table()
    lunch_pm_cost = (W[("午休", "无序充电")][1] + W[("趟间", "无序充电")][1]
                     - W[("午休", "碳强度引导有序充电")][1] - W[("趟间", "碳强度引导有序充电")][1])
    lunch_pm_em = (W[("午休", "无序充电")][2] + W[("趟间", "无序充电")][2]
                   - W[("午休", "碳强度引导有序充电")][2] - W[("趟间", "碳强度引导有序充电")][2])
    check(S, "午休+趟间 碳强度较无序 充电成本减少（元）", "14.72", lunch_pm_cost, 2,
          "由窗口表印出的四格（二位）相加减；表由 builder 复现")
    check(S, "午休+趟间 碳强度较无序 碳排减少（kg）", "7.20", lunch_pm_em, 2, "同上")
    f_cost = W[("首趟出车前", "碳强度引导有序充电")][1] - W[("首趟出车前", "电价引导有序充电")][1]
    f_em = W[("首趟出车前", "电价引导有序充电")][2] - W[("首趟出车前", "碳强度引导有序充电")][2]
    check(S, "首趟前 电价较碳强度 充电成本减少（元）", "25.94", f_cost, 2, "由窗口表两格相减")
    check(S, "首趟前 电价较碳强度 碳排增加（kg）", "23.45", f_em, 2, "由窗口表两格相减")
    check(S, "首趟前 每减1kg须多付（元）", "1.11", f_cost / f_em, 2)
    check(S, "首趟前 基准碳价下节省碳成本（元）", "4.69", f_em * 0.20, 2)
    CC = gen_cells("carbon_charging_table")
    check(S, "碳强度引导 充电排放（kg）", "44.47", m(SRC["cc"]["carbon_min"], "E_ev_indirect"), 2)
    checkc(S, "碳强度引导 充电排放占总排放（%）", "23.3",
           m(SRC["cc"]["carbon_min"], "E_ev_indirect") / m(SRC["cc"]["carbon_min"], "E_total") * 100,
           CC["电动车充电排放（kgCO$_2$）"][2] / CC["总排放（kgCO$_2$）"][2] * 100, 1)
    checkc(S, "碳强度引导 燃油直接排放占比（%）", "76.7",
           m(SRC["cc"]["carbon_min"], "E_cv_direct") / m(SRC["cc"]["carbon_min"], "E_total") * 100,
           CC["燃油车直接排放（kgCO$_2$）"][2] / CC["总排放（kgCO$_2$）"][2] * 100, 1)
    kwh = m(SRC["cc"]["carbon_min"], "electricity_kwh")
    check(S, "碳强度引导 充电电量（kWh）", "181.21", kwh, 2)
    check(S, "全天最低碳强度（kg/kWh）", "0.1541", min(cf), 4)
    checkc(S, "全部按最低碳强度核算的充电排放（kg）", "27.92", kwh * min(cf),
           CC["充电电量（kWh）"][2] * Decimal("0.1541"), 2,
           "口径 printed 下＝表内充电电量 181.21 × 正文印出的 0.1541")
    checkc(S, "未利用的减排空间（kg）", "16.55",
           m(SRC["cc"]["carbon_min"], "E_ev_indirect") - kwh * min(cf),
           CC["电动车充电排放（kgCO$_2$）"][2] - Decimal("27.92"), 2,
           "口径 printed 下＝表内 44.47 − 正文印出的 27.92")
    checkc(S, "按碳强度充电的充电成本高于按电价（元）", "9.06",
           m(SRC["cc"]["carbon_min"], "cost_elec") - m(SRC["cc"]["cost_min"], "cost_elec"),
           CC["充电成本（元）"][2] - CC["充电成本（元）"][1], 2)
    # 首趟前窗口内"改到低碳时段充电"的每 kWh 代价与收益。
    # 电价差 = 峰段价 − 谷段价（该窗口内 cost_min 落在谷段、carbon_min 落在前一日峰段）。
    prices = sorted({float(r["depot_energy_cny_per_kwh"]) for r in cal})
    dprice = max(prices) - min(prices)
    check(S, "首趟前 每kWh多付电费（元）", "0.585", dprice, 3,
          f"峰段{max(prices)} − 谷段{min(prices)} = {dprice!r}")
    # 碳强度差：该窗口谷段各时隙碳强度均值 − carbon_min 实际落点（前日18:00 时隙）碳强度。
    win = [(int(r["minute_of_day"]), r["tariff_period"],
            float(r["carbon_factor_kgco2e_per_kwh"])) for r in cal]
    valley = [c for mn, tp, c in win if tp == "valley"]
    at_1800 = [c for mn, tp, c in win if mn == 18 * 60][0]
    dcarbon = st.mean(valley) - at_1800
    check(S, "首趟前 每kWh少排放（kgCO2e）", "0.143", dcarbon, 3,
          f"谷段碳强度均值{st.mean(valley)!r} − 前日18:00 时隙{at_1800!r}"
          "（口径为复原，非脚本原始记录，见台账）")
    check(S, "首趟前 改充的盈亏平衡碳价（元/kgCO2e）", "4.09", dprice / dcarbon, 2,
          "= 每kWh多付电费 / 每kWh少排放")

    # ---- 4.4.3 ----
    S = "4.4.3"
    G = SRC["grid"]
    for (cond, key, pa, pc) in (
            ("谷段设在午间，碳价0.20", ("midday", 0.2), "2669.90", "2616.19"),
            ("北京现行时段，碳价1.00", ("beijing", 1.0), "2816.09", "2802.84"),
            ("谷段设在午间，碳价1.00", ("midday", 1.0), "2850.78", "2761.86")):
        pass  # 表由 builder 复现，这里只核正文
    TC = gen_cells("two_conditions_table")
    # two_conditions 列序：无序[电动车数,占比,总成本,碳排量] + 碳强度[电动车数,占比,总成本,碳排量]
    R_MID02 = TC["谷段设在午间碳价0.20"]
    R_BJ10 = TC["北京现行时段碳价1.00"]
    R_MID10 = TC["谷段设在午间碳价1.00"]
    SV = gen_cells("carbon_charging_solved_table")   # 列序：无序 / 电价引导 / 碳强度引导
    CC = gen_cells("carbon_charging_table")
    a02, c02 = G[("midday", 0.2, "asap")], G[("midday", 0.2, "carbon_min")]
    checkc(S, "午谷0.2 总成本减少（元）", "53.71", m(a02, "total_cost") - m(c02, "total_cost"),
           R_MID02[2] - R_MID02[6], 2)
    checkc(S, "午谷0.2 总成本减少（%）", "2.01",
           (m(a02, "total_cost") - m(c02, "total_cost")) / m(a02, "total_cost") * 100,
           (R_MID02[2] - R_MID02[6]) / R_MID02[2] * 100, 2)
    checkc(S, "午谷0.2 总排放减少（kg）", "27.42", m(a02, "E_total") - m(c02, "E_total"),
           R_MID02[3] - R_MID02[7], 2)
    check(S, "午谷0.2 充电排放相差（kg）", "5.23",
          abs(m(a02, "E_ev_indirect") - m(c02, "E_ev_indirect")), 2, "充电排放不在表内，正文值")
    n_lt3 = sum(1 for r in a02 if r["n_veh_ev"] < 3)
    check(S, "午谷0.2 无序充电电动车<3辆的次数", "4", n_lt3, 0, f"构型={dict(fleetcnt(a02))}")
    ab, cb = G[("beijing", 1.0, "asap")], G[("beijing", 1.0, "carbon_min")]
    check(S, "京1.0 充电排放减少（kg）", "13.40", m(ab, "E_ev_indirect") - m(cb, "E_ev_indirect"), 2,
          "充电排放不在表内，正文值")
    check(S, "京1.0 无序充电 电动车数（辆）", "3.9", m(ab, "n_veh_ev"), 1)
    check(S, "京1.0 碳强度引导 电动车数（辆）", "3.4", m(cb, "n_veh_ev"), 1)
    check(S, "京1.0 燃油直接排放增加（kg）", "24.25", m(cb, "E_cv_direct") - m(ab, "E_cv_direct"), 2,
          "燃油直接排放不在表内，正文值")
    checkc(S, "京1.0 总排放增加（kg）", "10.85", m(cb, "E_total") - m(ab, "E_total"),
           R_BJ10[7] - R_BJ10[3], 2)
    checkc(S, "京1.0 总成本减少（元）", "13.25", m(ab, "total_cost") - m(cb, "total_cost"),
           R_BJ10[2] - R_BJ10[6], 2)
    am, cm, pm_ = G[("midday", 1.0, "asap")], G[("midday", 1.0, "carbon_min")], G[("midday", 1.0, "cost_min")]
    check(S, "午谷1.0 碳强度引导 电动车数（辆）", "4.8", m(cm, "n_veh_ev"), 1)
    n15 = sum(1 for r in cm if (r["n_veh_cv"], r["n_veh_ev"]) == (1, 5))
    check(S, "午谷1.0 碳强度引导 1油5电次数", "8", n15, 0, f"构型={dict(fleetcnt(cm))}")
    checkc(S, "午谷1.0 燃油直接排放减少（kg）", "69.49", m(am, "E_cv_direct") - m(cm, "E_cv_direct"),
           SV["燃油车直接排放（kgCO$_2$）"][0] - SV["燃油车直接排放（kgCO$_2$）"][2], 2)
    checkc(S, "午谷1.0 总成本减少（元）", "88.92", m(am, "total_cost") - m(cm, "total_cost"),
           R_MID10[2] - R_MID10[6], 2)
    checkc(S, "午谷1.0 总成本减少（%）", "3.12",
           (m(am, "total_cost") - m(cm, "total_cost")) / m(am, "total_cost") * 100,
           (R_MID10[2] - R_MID10[6]) / R_MID10[2] * 100, 2)
    checkc(S, "午谷1.0 总排放减少（kg）", "72.03", m(am, "E_total") - m(cm, "E_total"),
           R_MID10[3] - R_MID10[7], 2)
    checkc(S, "午谷1.0 总排放减少（%）", "42.44",
           (m(am, "E_total") - m(cm, "E_total")) / m(am, "E_total") * 100,
           (R_MID10[3] - R_MID10[7]) / R_MID10[3] * 100, 2)
    base_c = SRC["cc"]["carbon_min"]
    checkc(S, "较基准碳强度引导 总排放减少（kg）", "93.46", m(base_c, "E_total") - m(cm, "E_total"),
           CC["总排放（kgCO$_2$）"][2] - SV["总排放（kgCO$_2$）"][2], 2)
    checkc(S, "较基准碳强度引导 总排放减少（%）", "48.89",
           (m(base_c, "E_total") - m(cm, "E_total")) / m(base_c, "E_total") * 100,
           (CC["总排放（kgCO$_2$）"][2] - SV["总排放（kgCO$_2$）"][2])
           / CC["总排放（kgCO$_2$）"][2] * 100, 2)
    op_base = m(base_c, "total_cost") - m(base_c, "cost_carbon")
    op_now = m(cm, "total_cost") - m(cm, "cost_carbon")
    c_op_base = CC["总成本（元）"][2] - CC["碳成本（元）"][2]
    c_op_now = SV["总成本（元）"][2] - SV["碳成本（元）"][2]
    checkc(S, "较基准 运营成本（不含碳）增加（元）", "36.23", op_now - op_base,
           c_op_now - c_op_base, 2)
    checkc(S, "较基准 运营成本增加（%）", "1.38", (op_now - op_base) / op_base * 100,
           (c_op_now - c_op_base) / c_op_base * 100, 2)
    # solved 表正文
    check(S, "午谷1.0 碳强度引导 总排放（kg）", "97.71", m(cm, "E_total"), 2)
    checkc(S, "碳强度较电价 总排放减少（kg）", "47.99", m(pm_, "E_total") - m(cm, "E_total"),
           SV["总排放（kgCO$_2$）"][1] - SV["总排放（kgCO$_2$）"][2], 2)
    checkc(S, "碳强度较电价 总排放减少（%）", "32.94",
           (m(pm_, "E_total") - m(cm, "E_total")) / m(pm_, "E_total") * 100,
           (SV["总排放（kgCO$_2$）"][1] - SV["总排放（kgCO$_2$）"][2])
           / SV["总排放（kgCO$_2$）"][1] * 100, 2)
    check(S, "午谷1.0 碳强度引导 总成本（元）", "2761.86", m(cm, "total_cost"), 2)
    checkc(S, "碳强度较电价 总成本高（元）", "2.57", m(cm, "total_cost") - m(pm_, "total_cost"),
           SV["总成本（元）"][2] - SV["总成本（元）"][1], 2)
    checkc(S, "碳强度较电价 总成本高（%）", "0.09",
           (m(cm, "total_cost") - m(pm_, "total_cost")) / m(pm_, "total_cost") * 100,
           (SV["总成本（元）"][2] - SV["总成本（元）"][1]) / SV["总成本（元）"][1] * 100, 2)
    checkc(S, "碳强度较电价 充电排放低（kg）", "18.11", m(pm_, "E_ev_indirect") - m(cm, "E_ev_indirect"),
           SV["电动车充电排放（kgCO$_2$）"][1] - SV["电动车充电排放（kgCO$_2$）"][2], 2)
    checkc(S, "碳强度较电价 充电成本高（元）", "49.97", m(cm, "cost_elec") - m(pm_, "cost_elec"),
           SV["充电成本（元）"][2] - SV["充电成本（元）"][1], 2)
    check(S, "午谷1.0 电价引导 电动车数（辆）", "4.2", m(pm_, "n_veh_ev"), 1)
    checkc(S, "碳强度较电价 充电电量多（kWh）", "21.01",
           m(cm, "electricity_kwh") - m(pm_, "electricity_kwh"),
           SV["充电电量（kWh）"][2] - SV["充电电量（kWh）"][1], 2)
    checkc(S, "碳强度较电价 燃油直接排放低（kg）", "29.88", m(pm_, "E_cv_direct") - m(cm, "E_cv_direct"),
           SV["燃油车直接排放（kgCO$_2$）"][1] - SV["燃油车直接排放（kgCO$_2$）"][2], 2)
    checkc(S, "碳强度较电价 油耗成本低（元）", "84.60", m(pm_, "cost_fuel") - m(cm, "cost_fuel"),
           SV["油耗成本（元）"][1] - SV["油耗成本（元）"][2], 2)


WIN_ARMS = ("无序充电", "电价引导有序充电", "碳强度引导有序充电")


def parse_windows_table():
    out = {}
    win = None
    for line in SRC["charging_windows_table"].splitlines():
        mm = re.search(r"multirow\{3\}\{\*\}\{(.+?)\}", line)
        if mm:
            win = mm.group(1)
        for arm in WIN_ARMS:
            if f"& {arm} &" in line:
                cells = [c.strip() for c in line.split("&")]
                nums = [c.replace("\\textbf{", "").replace("}", "").replace("\\\\", "").strip()
                        for c in cells[-2:]]
                out[(win, arm)] = (cells[-3].strip(), float(nums[0]), float(nums[1]))
    return out


# ================================================================ 4.5 / 4.6 ====

SYN_PRINTED = [
    ("total_cost", "总成本（元）", "2853.58", "2624.94", "-8.01", 2),
    ("cost_fix", "车辆启动成本（元）", "1390.00", "1150.00", "-17.27", 2),
    ("cost_km", "行驶成本（元）", "804.45", "920.33", "+14.41", 2),
    ("cost_fuel", "油耗成本（元）", "523.40", "333.23", "-36.33", 2),
    ("cost_elec", "充电成本（元）", "90.71", "182.71", "+101.42", 2),
    ("cost_carbon", "碳排放成本（元）", "45.03", "38.67", "-14.12", 2),
    ("distance_total_km", "总距离（km）", "958.74", "1056.11", "+10.16", 2),
    ("emissions_total", "总排放（kgCO2e）", "225.14", "193.35", "-14.12", 2),
    ("n_veh_total", "车辆数（辆）", "7", "5", "-28.57", 0),
    ("n_veh_ev", "电动车数（辆）", "2", "3", "+50.00", 0),
    ("n_veh_cv", "燃油车数（辆）", "5", "2", "-60.00", 0),
    ("n_trips", "配送趟数（趟）", "17", "15", "-11.76", 0),
]


def audit_45_46():
    S = "4.5"
    syn = SRC["syn"]
    ind, jnt = syn["arms"]["independent"], syn["arms"]["joint"]
    for key, nm, pi, pj, pc, d in SYN_PRINTED:
        check(S, f"表 {nm} 独立", pi, ind["means"][key], d)
        check(S, f"表 {nm} 联合", pj, jnt["means"][key], d)
        check(S, f"表 {nm} 变化幅度（%）", pc.lstrip("+"),
              pct_change(ind["means"][key], jnt["means"][key]), 2)
    A, B = "D_OSM_WAY_1003511503", "D_OSM_WAY_1071205721"
    dep = [("服务客户数（个）", "customers", 0, ("5", "8", "45", "42")),
           ("启用车辆数（辆）", "vehicles_used", 0, ("2", "1", "5", "4")),
           ("配送趟数（趟）", "trips", 0, ("3", "2", "14", "13")),
           ("车辆作业时间（min）", "busy_minutes", 2, ("216.43", "331.54", "1675.21", "1504.99")),
           ("车辆时间利用率（%）", "utilisation_pct", 2, ("20.04", "61.40", "62.04", "69.68"))]
    for nm, key, d, (a1, a2, b1, b2) in dep:
        check(S, f"车场表 {nm} A独立", a1, ind["depot_means"][A][key], d)
        check(S, f"车场表 {nm} A联合", a2, jnt["depot_means"][A][key], d)
        check(S, f"车场表 {nm} B独立", b1, ind["depot_means"][B][key], d)
        check(S, f"车场表 {nm} B联合", b2, jnt["depot_means"][B][key], d)
    e_ind = ind["means"]["cost_fuel"] + ind["means"]["cost_elec"]
    e_jnt = jnt["means"]["cost_fuel"] + jnt["means"]["cost_elec"]
    checkc(S, "能源支出 独立（元）", "614.11", e_ind,
           Decimal("523.40") + Decimal("90.71"), 2, "表内油耗成本+充电成本两格之和")
    checkc(S, "能源支出 联合（元）", "515.94", e_jnt,
           Decimal("333.23") + Decimal("182.71"), 2, "表内油耗成本+充电成本两格之和")
    kwh_i, kwh_j = st.mean(SRC["syn_independent_kwh"]), st.mean(SRC["syn_joint_kwh"])
    check(S, "充电电量 独立（kWh）", "123.62", kwh_i, 2, "10 次 breakdown.electricity_kwh 均值")
    check(S, "充电电量 联合（kWh）", "223.58", kwh_j, 2, "10 次 breakdown.electricity_kwh 均值")
    # 电网碳强度另核一遍：充电排放 / 充电电量（与 json 的 grid_intensity 对齐）
    gi_i2 = st.mean(SRC["syn_independent_ev_ind"]) / kwh_i
    gi_j2 = st.mean(SRC["syn_joint_ev_ind"]) / kwh_j
    RESULTS.append(("INFO    ", S, "碳强度 独立 复核=充电排放均值/电量均值", "-", s(gi_i2, 4), repr(gi_i2), ""))
    RESULTS.append(("INFO    ", S, "碳强度 联合 复核=充电排放均值/电量均值", "-", s(gi_j2, 4), repr(gi_j2), ""))
    gi_i, gi_j = ind["means"]["grid_intensity"], jnt["means"]["grid_intensity"]
    check(S, "实际电网碳强度 独立（kgCO2e/kWh）", "0.3259", gi_i / 1000.0, 4,
          f"json 存的是 gCO2/kWh={gi_i!r}；论文改用 kgCO2e/kWh")
    check(S, "实际电网碳强度 联合（kgCO2e/kWh）", "0.3383", gi_j / 1000.0, 4,
          f"json 存的是 gCO2/kWh={gi_j!r}；论文改用 kgCO2e/kWh")
    check(S, "全网独立车辆数（辆）", "7", ind["means"]["n_veh_total"], 0)
    check(S, "全网独立趟数（趟）", "17", ind["means"]["n_trips"], 0)

    # ---- 4.6 Shapley ----
    S = "4.6"
    C_A = ind["depot_means"][A]["cost_total_ledger"]
    C_B = ind["depot_means"][B]["cost_total_ledger"]
    C_J = jnt["means"]["total_cost"]
    PCS = (C_A + C_B - C_J) / 2.0
    psiA, psiB = C_A - PCS, C_B - PCS
    check(S, "独立配送成本 C_A（元）", "687.72", C_A, 2)
    check(S, "独立配送成本 C_B（元）", "2165.87", C_B, 2)
    check(S, "分摊成本 psi_A（元）", "573.39", psiA, 2)
    check(S, "分摊成本 psi_B（元）", "2051.54", psiB, 2)
    cA, cB = Decimal("687.72"), Decimal("2165.87")
    pA, pB = Decimal("573.39"), Decimal("2051.54")
    checkc(S, "成本节约额 PCS_A（元）", "114.33", PCS, cA - pA, 2,
           "口径 printed 下＝表内 687.72−573.39")
    checkc(S, "成本节约额 PCS_B（元）", "114.33", PCS, cB - pB, 2,
           "口径 printed 下＝表内 2165.87−2051.54")
    checkc(S, "成本节约率 A（%）", "16.62", PCS / C_A * 100, (cA - pA) / cA * 100, 2)
    checkc(S, "成本节约率 B（%）", "5.28", PCS / C_B * 100, (cB - pB) / cB * 100, 2)
    check(S, "psi_A+psi_B 全精度（元）", s(C_J, 2), psiA + psiB, 2,
          f"印出两格之和={Decimal('573.39')+Decimal('2051.54')}（比联合总成本少 0.01）")
    check(S, "C_A+C_B 是否等于独立总成本（元）", s(ind["means"]["total_cost"], 2), C_A + C_B, 2)
    SRC["_46"] = dict(C_A=C_A, C_B=C_B, C_J=C_J, PCS=PCS, psiA=psiA, psiB=psiB)


# ==================================================================== 4.7 ====


def audit_47():
    S = "4.7"
    D = SRC["dyn"]
    ref, seq, roll = D["full_information_reference"], D["sequential_insertion"], D["rolling_reoptimization"]
    f = lambda r, k: float(r[k])
    for nm, k, pr, ps, prl, pc in (
            ("总成本（元）", "total_cost", "2735.03", "3117.01", "2897.34", "-7.05"),
            ("总排放（kgCO2e）", "total_emissions_kg", "234.40", "232.64", "195.86", "-15.81"),
            ("总距离（km）", "total_distance_km", "968.09", "1099.85", "966.28", "-12.14")):
        check(S, f"表 {nm} 完全信息", pr, f(ref, k), 2)
        check(S, f"表 {nm} 顺序插入", ps, f(seq, k), 2)
        check(S, f"表 {nm} 滚动重优化", prl, f(roll, k), 2)
        check(S, f"表 {nm} 相对变化（%）", pc.lstrip("-").lstrip("+"),
              abs(pct_change(f(seq, k), f(roll, k))), 2)
    for nm, r, p in (("完全信息", ref, "6"), ("顺序插入", seq, "7"), ("滚动重优化", roll, "7")):
        n = int(float(r["ev_route_count"] or 0)) + int(float(r["cv_route_count"] or 0))
        check(S, f"表 实际车辆数 {nm}", p, float(r["enabled_vehicles"]), 0,
              f"enabled_vehicles={r['enabled_vehicles']} ev_routes={r['ev_route_count']} cv_routes={r['cv_route_count']}")
    check(S, "客户数", "53", float(seq["customers_total"]), 0)
    check(S, "需求合计（kg）", "14133", float(seq["demand_total_kg"]), 0)
    check(S, "顺序插入 未服务订单数", "0",
          float(seq["customers_total"]) - float(seq["customers_served"]), 0)
    check(S, "滚动重优化 未服务订单数", "0",
          float(roll["customers_total"]) - float(roll["customers_served"]), 0)
    ev = SRC["dyn_events"]
    add = sum(float(e["new_demand_kg"]) for e in ev if e["event_type"] == "add")
    can = sum(float(e["old_demand_kg"]) for e in ev if e["event_type"] == "cancel")
    chg = sum(float(e["new_demand_kg"]) - float(e["old_demand_kg"])
              for e in ev if e["event_type"] == "demand_change")
    check(S, "新增需求（kg）", "1528", add, 0, "events.tsv 中 add 的 new_demand_kg 之和")
    check(S, "取消需求（kg）", "695", can, 0, "events.tsv 中 cancel 的 old_demand_kg 之和")
    check(S, "需求变化净增（kg）", "36", chg, 0, "events.tsv 中 demand_change 的新旧之差")
    check(S, "事件总数", "10", len(ev), 0)
    check(S, "批次数", "5", len({b["batch_index"] for b in SRC["dyn_batches"]}), 0)
    check(S, "新增订单笔数", "5", sum(1 for e in ev if e["event_type"] == "add"), 0)
    # 动态算例客户数 / 需求：初始 50 + 5 新增 - 2 取消 = 53
    init = sum(float(r["demand_kg"]) for r in SRC["orders"])
    check(S, "动态需求合计核对（kg）", "14133", init + add - can + chg, 0,
          "初始13264 + 新增 - 取消 + 变化净增")
    checkc(S, "滚动重优化 较完全信息 总成本高（%）", "5.93",
           pct_change(f(ref, "total_cost"), f(roll, "total_cost")),
           (Decimal("2897.34") - Decimal("2735.03")) / Decimal("2735.03") * 100, 2)
    checkc(S, "滚动重优化 较完全信息 总距离短（%）", "0.19",
           abs(pct_change(f(ref, "total_distance_km"), f(roll, "total_distance_km"))),
           (Decimal("968.09") - Decimal("966.28")) / Decimal("968.09") * 100, 2)
    check(S, "顺序插入 燃油直接排放（kg）", "178.09", f(seq, "fuel_direct_emissions_kg"), 2)
    check(S, "滚动重优化 燃油直接排放（kg）", "141.51", f(roll, "fuel_direct_emissions_kg"), 2)
    check(S, "完全信息 燃油直接排放高出（kg）", "54.22",
          f(ref, "fuel_direct_emissions_kg") - f(roll, "fuel_direct_emissions_kg"), 2)
    check(S, "完全信息 电动车路径数", "2", float(ref["ev_route_count"]), 0)
    # 行定义（2026-09-10 作者裁定）：新增订单落入路径的次数，不论经内核修复还是逐客户插入。
    # 算法：数 events.tsv 中 event_type=add 且该客户出现在该臂最终服务集合里的事件数。
    # dynamic_events.csv 的 mechanical_insertion_count 只数"逐客户插入"那一路，
    # 滚动重优化下为 2（第 3 批次 C052、C053），不等于本行定义。
    served = SRC["dyn_served"]
    for arm_key, arm_name, pr in (("sequential_insertion", "顺序插入", "5"),
                                  ("rolling_reoptimization", "滚动重优化", "5")):
        placed = sum(1 for e in ev if e["event_type"] == "add"
                     and e["customer_id"] in served[arm_key])
        check(S, f"{arm_name} 新增订单插入次数", pr, placed, 0,
              f"落入路径的新增订单={sorted(e['customer_id'] for e in ev
                  if e['event_type'] == 'add' and e['customer_id'] in served[arm_key])}；"
              f"其中逐客户插入 mechanical_insertion_count="
              f"{int(float(SRC['dyn'][arm_key]['mechanical_insertion_count']))}")
    check(S, "顺序插入 未执行路径重排批次数", "0",
          sum(1 for b in SRC["dyn_batches"] if b["arm"] == "sequential_insertion"
              and int(b["changed_old_old_unexecuted_arc_count"]) > 0), 0)
    # 4.4.3 两张表新增的"电动车数（辆）"格
    for lbl, key, pr in (("京1.0 无序", ("beijing", 1.0, "asap"), "3.9"),
                         ("京1.0 碳强度", ("beijing", 1.0, "carbon_min"), "3.4"),
                         ("午谷1.0 无序", ("midday", 1.0, "asap"), "3.3"),
                         ("午谷1.0 电价", ("midday", 1.0, "cost_min"), "4.2"),
                         ("午谷1.0 碳强度", ("midday", 1.0, "carbon_min"), "4.8"),
                         ("基准 无序", ("beijing", 0.2, "asap"), "2.6"),
                         ("基准 碳强度", ("beijing", 0.2, "carbon_min"), "2.5"),
                         ("午谷0.2 无序", ("midday", 0.2, "asap"), "2.4"),
                         ("午谷0.2 碳强度", ("midday", 0.2, "carbon_min"), "3.0")):
        check("4.4.3", f"表 电动车数（辆） {lbl}", pr, m(SRC["grid"][key], "n_veh_ev"), 1)
    # 4.7 第4/5 批次的结构性计数（route_snapshot 前后对比）
    for bi, (pc, po, pr_) in (("4", ("3", "2", "8")), ("5", ("0", "0", "9"))):
        row = [b for b in SRC["dyn_batches"]
               if b["arm"] == "rolling_reoptimization" and b["batch_index"] == bi][0]
        before = {x["route_id"]: x["node_sequence"]
                  for x in json.loads(row["route_snapshot_before_json"])["routes"]}
        after = {x["route_id"]: x["node_sequence"]
                 for x in json.loads(row["route_snapshot_after_json"])["routes"]}
        has_c = lambda seq: any(n.startswith("C") for n in seq)
        closed = [k for k in set(before) - set(after) if has_c(before[k])]
        opened = [k for k in set(after) - set(before) if has_c(after[k])]
        rew = [k for k in set(before) & set(after) if before[k] != after[k]]
        check(S, f"第{bi}批次 关闭路径数", pc, len(closed), 0, "只计承载客户的路径")
        check(S, f"第{bi}批次 新开路径数", po, len(opened), 0, "只计承载客户的路径")
        check(S, f"第{bi}批次 改写既有路径数", pr_, len(rew), 0)
        check(S, f"第{bi}批次 原有客户改派数",
              {"4": "28", "5": "20"}[bi], float(row["old_customers_changed_vehicle_count"]), 0)
        check(S, f"第{bi}批次 涉及车辆数",
              {"4": "8", "5": "5"}[bi], float(row["vehicles_with_old_customer_changes_count"]), 0)


# ==================================================================== main ====


def main(argv=None) -> int:
    global CONV
    import argparse
    ap = argparse.ArgumentParser(description="论文数字审计")
    ap.add_argument("--convention", choices=("full", "printed"), default="full",
                    help="full=正文导出量按全精度重算；printed=按印出的表格单元格重算（口径 A）")
    args = ap.parse_args(argv)
    CONV = args.convention
    print(f"# 口径：{CONV}")
    load_sources()
    audit_41()
    audit_42()
    audit_43()
    audit_44()
    audit_45_46()
    audit_47()

    bad = [r for r in RESULTS if r[0] == "MISMATCH"]
    bnd = [r for r in RESULTS if r[0] == "BOUNDARY"]
    ns = [r for r in RESULTS if r[0] == "NOSOURCE"]
    for flag, sec, label, printed, got, full, note in RESULTS:
        if flag != "OK      ":
            print(f"{flag} [{sec}] {label}: 论文={printed} 重算={got} 全精度={full} {note}")
    print("-" * 100)
    print(f"合计核对 {len(RESULTS)} 个数字；MISMATCH {len(bad)}；BOUNDARY {len(bnd)}；NOSOURCE {len(ns)}")
    if "_46" in SRC:
        d = SRC["_46"]
        print("\n[4.6 全精度]")
        for k in ("C_A", "C_B", "C_J", "PCS", "psiA", "psiB"):
            print(f"  {k:5s} = {d[k]!r}  -> {s(d[k],2)}")
        print(f"  psiA+psiB 全精度 = {d['psiA']+d['psiB']!r} -> {s(d['psiA']+d['psiB'],2)}")
        print(f"  四舍五入后相加   = {q(d['psiA'],2)+q(d['psiB'],2)}")
    if os.environ.get("AUDIT_DUMP"):
        for row in RESULTS:
            print("\t".join(str(x) for x in row))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
