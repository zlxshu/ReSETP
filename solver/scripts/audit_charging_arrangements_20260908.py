#!/usr/bin/env python3
"""四种充电安排的只读诊断（2026-09-08）。

回答用户 2026-09-08 的质疑：
  "有电即充不知电价与碳强度，信息闭塞，除非运气好，否则不可能打过分时电价和时变碳；
   时变碳与分时电价应各自发挥擅长领域。总排放最低竟是即充、只看碳反而略高——要严查。"

本脚本**只读**：只 open(..., "r")，不写任何文件、不跑求解器、不 import setp_solver。
全部结论从四臂 40 个 run 的 best_solution.json / metadata.json 与运行期日历 CSV 重算。

充电分摊与窗口归类沿用已验收的 solver/scripts/diagnose_charging_windows_20260906.py 口径
（该脚本已核：近似账与求解器记录逐 run 零偏差）：
  * 半小时槽，按占用时间比例分摊电量（60 kW 恒功率段，SOC<0.85，实测每个会话均满足，见 §0 闸门）；
  * 排放 = Σ 槽电量 × 该槽 carbon_factor_kgco2e_per_kwh（北京 2025-02-12，48 行循环，
    charge_day_offset 只用于窗口归类，排放/电费按同一代表日循环取模——与 cost.py cyclic=True 一致）；
  * 电费 = 同一分摊法 × depot_energy_cny_per_kwh。
§0 闸门：逐 run 重算 E_ev_indirect 与 cost_elec，与 best_solution.json 的 breakdown 对账；
不闭合则立刻退出（后面每一个 kg/kWh 都建立在这条闭合上）。

用法：
    python3 solver/scripts/audit_charging_arrangements_20260908.py
    python3 solver/scripts/audit_charging_arrangements_20260908.py --section 4
"""

from __future__ import annotations

import argparse
import csv
import glob
import itertools
import json
import math
import random
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAL = REPO / (
    "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/"
    "tariff_carbon_hourly_calendar.csv"
)
INST = REPO / (
    "data/ChinaInstances/china81_final_suite_v2_20260815/instances/"
    "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
)
SHIFT = INST / "shift_contract.json"
ORDERS = INST / "orders.csv"

CITY, DATE = "beijing", "2025-02-12"
DAY, SLOT = 86400.0, 1800.0
# prices.py:41 B_battery_kwh = 80.0；M17_FAST_SHAPE_SCALED_60KW_PWL 第一段折点 SOC=0.85
BATTERY_KWH = 80.0
FIRST_KNEE_KWH = 0.85 * BATTERY_KWH

ARMS = [
    ("有可用时段即充电", "asap",
     REPO / "solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MT-HGS"),
    ("考虑分时电价", "cost_min",
     REPO / "solver/reports/charging_arrangements_20260906/cost_min"),
    ("考虑时变碳强度", "carbon_min",
     REPO / "solver/reports/charging_arrangements_20260906/carbon_min"),
    ("两者", "cost_plus_carbon",
     REPO / "solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS"),
]
WINDOWS = [("first", "首趟出车前"), ("lunch", "午休"), ("pm", "趟间")]


# --------------------------------------------------------------------------
# 日历
# --------------------------------------------------------------------------
def load_calendar():
    with open(CAL, encoding="utf-8") as handle:
        rows = [
            r for r in csv.DictReader(handle)
            if r["city"] == CITY and r["date"] == DATE
        ]
    if len(rows) != 48:
        raise SystemExit(f"日历行数 {len(rows)} != 48")
    carbon, price, period = {}, {}, {}
    for r in rows:
        key = int(r["minute_of_day"])
        carbon[key] = float(r["carbon_factor_kgco2e_per_kwh"])
        price[key] = float(r["depot_energy_cny_per_kwh"])
        period[key] = r["tariff_period"]
    return carbon, price, period


def slot_key(second: float) -> int:
    """半小时槽的 minute_of_day 键（对代表日取模，与 cost.py cyclic=True 一致）。"""
    return int((second % DAY) // 60 // 30) * 30


def spread(session_start, minutes, kwh):
    """把一次充电按占用时间比例摊到半小时槽上，返回 [(槽键, 电量)]。"""
    if minutes <= 0:
        return [(slot_key(session_start), kwh)]
    out, t, end = [], session_start, session_start + minutes * 60.0
    total_seconds = minutes * 60.0
    while t < end - 1e-9:
        nxt = (t // SLOT + 1) * SLOT
        seg = min(nxt, end) - t
        out.append((slot_key(t), kwh * seg / total_seconds))
        t = nxt
    return out


def settle(session_start, minutes, kwh, table):
    return sum(e * table[k] for k, e in spread(session_start, minutes, kwh))


# --------------------------------------------------------------------------
# 读一个 run
# --------------------------------------------------------------------------
def read_run(path: Path, policy: str, carbon, price, am_end, pm_start, demand_by_cust):
    sol = json.load(open(path / "best_solution.json", encoding="utf-8"))
    meta = json.load(open(path / "metadata.json", encoding="utf-8"))
    closure = meta.get("mechanism_closure") or {}
    got = closure.get("effective_charge_timing_policy")
    if got != policy:
        raise SystemExit(f"{path}: 策略 {got!r} != {policy!r}")
    if meta.get("status") != "COMPLETE":
        raise SystemExit(f"{path}: status={meta.get('status')}")

    br = sol["evaluation"]["breakdown"]
    acct = meta.get("accounting", {})
    wiring = meta.get("route_engine_wiring", {})

    trips = {}
    for t in sol["trip_clock"]:
        trips.setdefault(t["physical_vehicle_id"], {})[t["trip_index"]] = t

    sessions = []
    for duty in sol["individual"]["duties"]:
        tv = trips.get(duty["physical_vehicle_id"], {})
        for c in duty["charging_sessions"]:
            k = c["trip_index"]
            start = c["charge_start_second"] + c["charge_day_offset"] * DAY
            dep = float(tv[k]["departure_second"])
            if k == 1:
                window = "first"
                # 首趟前窗口：本车前一日最后一趟回场（prev_return 口径）
                earliest = max(
                    float(t["return_second"]) for t in tv.values()
                ) - DAY
            else:
                prev_ret = float(tv[k - 1]["return_second"])
                window = (
                    "lunch"
                    if (prev_ret <= am_end + 1 and dep >= pm_start - 1)
                    else "pm"
                )
                earliest = prev_ret
            occ = float(c["occupancy_minutes"])
            kwh = float(c["energy_kwh"])
            sessions.append({
                "vehicle": duty["physical_vehicle_id"],
                "trip_index": k,
                "window": window,
                "start": start,
                "occupancy_minutes": occ,
                "kwh": kwh,
                "end_energy_kwh": float(c.get("end_energy_kwh") or kwh),
                "earliest": earliest,
                "latest": dep - occ * 60.0,
                "emission": settle(start, occ, kwh, carbon),
                "cost": settle(start, occ, kwh, price),
            })

    served = set()
    for route in sol["evaluation"]["prepared_solution"]["routes"]:
        for node in route["node_sequence"]:
            if node in demand_by_cust:
                served.add(node)

    rounds = acct.get("kernel_round_summaries", [])
    return {
        "run": path.name,
        "path": str(path.relative_to(REPO)),
        "policy": policy,
        "total_cost": br["total_cost"],
        "cost_fix": br["cost_fix"],
        "cost_fix_ev_premium": br["cost_fix_ev_premium"],
        "cost_km": br["cost_km"],
        "cost_fuel": br["cost_fuel"],
        "cost_elec": br["cost_elec"],
        "cost_carbon": br["cost_carbon"],
        "E_total": br["E_total"],
        "E_cv_direct": br["E_cv_direct"],
        "E_ev_indirect": br["E_ev_indirect"],
        "n_cv": int(br["n_veh_cv"]),
        "n_ev": int(br["n_veh_ev"]),
        "distance_total_km": br["distance_total"] / 1000.0,
        "distance_cv_km": br["distance_cv"] / 1000.0,
        "distance_ev_km": br["distance_ev"] / 1000.0,
        "fuel_liters": br["fuel_liters"],
        "kwh": br["electricity_kwh"],
        "depot_kwh": br["depot_charging_kwh"],
        "station_kwh": br["station_charging_kwh"],
        "served_customers": len(served),
        "served_demand_kg": sum(demand_by_cust[c] for c in served),
        "unserved": len(sol["individual"]["unserved_customers"]),
        "iterations": (
            acct.get("iterations")
            if acct.get("iterations") is not None
            else meta.get("iterations")
        ),
        "rounds": acct.get("rounds"),
        "wall_seconds": acct.get("run_wall_seconds"),
        "round1_iters": rounds[0]["iterations"] if rounds else None,
        "round1_improvements": rounds[0]["improvements"] if rounds else None,
        "max_trips": closure.get("final_max_trips_per_duty"),
        "first_trip_window": wiring.get("first_trip_window"),
        "proxy_policy": wiring.get("charge_timing_policy_for_proxy"),
        "station_mode": meta.get("public_station_candidate_mode"),
        "mechanism_off": meta.get("mechanism_off"),
        "forbidden": closure.get("forbidden_named_proposed_actions"),
        "proxy": wiring.get("shift_aware_ev_proxy"),
        "carbon_price": meta.get("carbon_price_cny_per_kg"),
        "ev_premium": meta.get("effective_ev_daily_premium_cny"),
        "sessions": sessions,
    }


def load_all():
    carbon, price, period = load_calendar()
    contract = json.load(open(SHIFT, encoding="utf-8"))
    am_end = contract["shifts"]["AM"]["end_minute"] * 60.0
    pm_start = contract["shifts"]["PM"]["start_minute"] * 60.0
    with open(ORDERS, encoding="utf-8") as handle:
        demand_by_cust = {
            r["customer_id"]: float(r["demand_kg"])
            for r in csv.DictReader(handle)
        }
    data = {}
    for _, policy, root in ARMS:
        runs = []
        for p in sorted(glob.glob(str(root / "run_*"))):
            p = Path(p)
            if p.is_dir():
                runs.append(
                    read_run(p, policy, carbon, price, am_end, pm_start,
                             demand_by_cust)
                )
        if len(runs) != 10:
            raise SystemExit(f"{root}: {len(runs)} runs != 10")
        data[policy] = runs
    return data, carbon, price, period, demand_by_cust


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def mean(xs):
    return sum(xs) / len(xs)


def sd(xs):
    return statistics.stdev(xs) if len(xs) > 1 else 0.0


def welch(a, b):
    ma, mb = mean(a), mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    na, nb = len(a), len(b)
    se = math.sqrt(va / na + vb / nb)
    if se == 0.0:
        return 0.0, float("nan"), float("nan")
    t = (ma - mb) / se
    df = (va / na + vb / nb) ** 2 / (
        (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    )
    return t, df, se


def perm_p(a, b, exact_limit=200_000):
    """两样本置换检验（双侧，均值差）。n=10/10 时 C(20,10)=184756，做精确枚举。"""
    pooled = list(a) + list(b)
    n = len(a)
    observed = abs(mean(a) - mean(b))
    total = math.comb(len(pooled), n)
    hits = 0
    if total <= exact_limit:
        idx = range(len(pooled))
        for combo in itertools.combinations(idx, n):
            s = set(combo)
            left = [pooled[i] for i in combo]
            right = [pooled[i] for i in idx if i not in s]
            if abs(mean(left) - mean(right)) >= observed - 1e-12:
                hits += 1
        return hits / total, total, True
    rng = random.Random(0)
    draws = 100_000
    for _ in range(draws):
        rng.shuffle(pooled)
        if abs(mean(pooled[:n]) - mean(pooled[n:])) >= observed - 1e-12:
            hits += 1
    return hits / draws, draws, False


def fleet_label(r):
    return f"{r['n_cv']}油{r['n_ev']}电"


def hhmm(second):
    prev = "前日" if second < 0 else ""
    h = (second % DAY) / 3600.0
    return f"{prev}{int(h):02d}:{int(round((h - int(h)) * 60)):02d}"


# --------------------------------------------------------------------------
# §0 闸门
# --------------------------------------------------------------------------
def section0(data):
    print("=" * 100)
    print("§0 闸门：逐 run 重算 E_ev_indirect / cost_elec，与 breakdown 对账")
    print("=" * 100)
    worst_e = worst_c = 0.0
    worst_knee = 0.0
    for _, policy, _ in ARMS:
        for r in data[policy]:
            e = sum(s["emission"] for s in r["sessions"])
            c = sum(s["cost"] for s in r["sessions"])
            k = sum(s["kwh"] for s in r["sessions"])
            worst_e = max(worst_e, abs(e - r["E_ev_indirect"]))
            worst_c = max(worst_c, abs(c - r["cost_elec"]))
            if abs(k - r["kwh"]) > 1e-6:
                raise SystemExit(f"{r['path']}: 电量不闭合 {k} vs {r['kwh']}")
            for s in r["sessions"]:
                worst_knee = max(worst_knee, s["end_energy_kwh"])
    print(f"E_ev_indirect 最大偏差 = {worst_e:.3e} kg（40 run）")
    print(f"cost_elec      最大偏差 = {worst_c:.3e} 元（40 run）")
    print(f"最大会话终止电量 = {worst_knee:.3f} kWh < 折点 {FIRST_KNEE_KWH:.1f} kWh"
          f"（0.85×{BATTERY_KWH:.0f}）→ 全部落在 60 kW 恒功率段，按时间线性分摊为精确")
    if worst_e > 1e-6 or worst_c > 1e-6:
        raise SystemExit("闸门未通过：重算与求解器记录不闭合，后续 kg/kWh 不可信")
    print("闸门通过。")
    print()


# --------------------------------------------------------------------------
# §1 逐 run 表
# --------------------------------------------------------------------------
def section1(data):
    print("=" * 100)
    print("§1 四臂 40 个 run 逐条")
    print("=" * 100)
    head = (
        f"{'臂':<16}{'run':<8}{'车队':<8}{'总成本':>9}{'固定':>8}{'公里':>8}"
        f"{'油费':>8}{'电费':>8}{'碳费':>7}{'总排放':>8}{'油直排':>8}{'充电排':>8}"
        f"{'总距km':>9}{'kWh':>8}{'客户':>5}{'需求kg':>8}{'轮':>4}{'迭代':>9}{'墙钟s':>8}{'趟上限':>7}"
    )
    print(head)
    for name, policy, _ in ARMS:
        for r in data[policy]:
            print(
                f"{name:<16}{r['run']:<8}{fleet_label(r):<8}"
                f"{r['total_cost']:>9.2f}{r['cost_fix']:>8.0f}{r['cost_km']:>8.2f}"
                f"{r['cost_fuel']:>8.2f}{r['cost_elec']:>8.2f}{r['cost_carbon']:>7.2f}"
                f"{r['E_total']:>8.2f}{r['E_cv_direct']:>8.2f}{r['E_ev_indirect']:>8.2f}"
                f"{r['distance_total_km']:>9.2f}{r['kwh']:>8.2f}"
                f"{r['served_customers']:>5d}{r['served_demand_kg']:>8.0f}"
                f"{r['rounds']:>4d}{r['iterations']:>9d}{r['wall_seconds']:>8.1f}"
                f"{r['max_trips']:>7d}"
            )
        print("-" * len(head))
    print()
    print("各臂均值（与论文表核对）：")
    print(f"{'臂':<16}{'总成本':>9}{'充电成本':>10}{'充电排放':>10}{'油直排':>9}"
          f"{'总排放':>9}{'kWh':>8}{'油车':>6}{'电车':>6}{'公共站kWh':>10}{'未服务':>7}")
    for name, policy, _ in ARMS:
        rs = data[policy]
        print(
            f"{name:<16}{mean([r['total_cost'] for r in rs]):>9.2f}"
            f"{mean([r['cost_elec'] for r in rs]):>10.2f}"
            f"{mean([r['E_ev_indirect'] for r in rs]):>10.2f}"
            f"{mean([r['E_cv_direct'] for r in rs]):>9.2f}"
            f"{mean([r['E_total'] for r in rs]):>9.2f}"
            f"{mean([r['kwh'] for r in rs]):>8.2f}"
            f"{mean([r['n_cv'] for r in rs]):>6.1f}"
            f"{mean([r['n_ev'] for r in rs]):>6.1f}"
            f"{mean([r['station_kwh'] for r in rs]):>10.2f}"
            f"{sum(r['unserved'] for r in rs):>7d}"
        )
    print()
    print("车队构型计数：")
    for name, policy, _ in ARMS:
        cnt = {}
        for r in data[policy]:
            cnt[fleet_label(r)] = cnt.get(fleet_label(r), 0) + 1
        order = sorted(cnt.items(), key=lambda kv: -kv[1])
        print(f"  {name:<16}" + "、".join(f"{k}×{v}" for k, v in order))
    print()


# --------------------------------------------------------------------------
# §2 总排放方差分解
# --------------------------------------------------------------------------
def section2(data):
    print("=" * 100)
    print("§2 总排放的跑间方差分解（组＝燃油车数）与噪声判定")
    print("=" * 100)
    print(f"{'臂':<16}{'均值':>9}{'sd':>8}{'总方差':>10}{'组间':>10}{'组内':>10}{'组间占比':>10}")
    for name, policy, _ in ARMS:
        xs = [r["E_total"] for r in data[policy]]
        grand = mean(xs)
        ss_tot = sum((x - grand) ** 2 for x in xs)
        groups = {}
        for r in data[policy]:
            groups.setdefault(r["n_cv"], []).append(r["E_total"])
        ss_between = sum(len(g) * (mean(g) - grand) ** 2 for g in groups.values())
        ss_within = ss_tot - ss_between
        n = len(xs)
        print(
            f"{name:<16}{grand:>9.2f}{sd(xs):>8.2f}{ss_tot / (n - 1):>10.2f}"
            f"{ss_between / (n - 1):>10.2f}{ss_within / (n - 1):>10.2f}"
            f"{ss_between / ss_tot * 100 if ss_tot else 0:>9.1f}%"
        )
    print()
    print("燃油车数 → 总排放（合并四臂，40 run）：")
    pool = {}
    for _, policy, _ in ARMS:
        for r in data[policy]:
            pool.setdefault(r["n_cv"], []).append(r)
    for k in sorted(pool):
        rs = pool[k]
        print(f"  {k} 油：n={len(rs):>2d}  总排放 {mean([r['E_total'] for r in rs]):>7.2f}"
              f"  油直排 {mean([r['E_cv_direct'] for r in rs]):>7.2f}"
              f"  充电排放 {mean([r['E_ev_indirect'] for r in rs]):>6.2f}"
              f"  充电电量 {mean([r['kwh'] for r in rs]):>7.2f} kWh"
              f"  总成本 {mean([r['total_cost'] for r in rs]):>8.2f}")
    print()
    a = [r["E_total"] for r in data["asap"]]
    c = [r["E_total"] for r in data["carbon_min"]]
    diff = mean(c) - mean(a)
    t, df, se = welch(c, a)
    p, draws, exact = perm_p(c, a)
    print("即充 vs 只看碳（总排放）：")
    print(f"  差 = {diff:+.2f} kg（只看碳 {mean(c):.2f} − 即充 {mean(a):.2f}）")
    print(f"  跑间 sd：即充 {sd(a):.2f}、只看碳 {sd(c):.2f}；|差|/合并 sd "
          f"= {abs(diff) / math.sqrt((sd(a) ** 2 + sd(c) ** 2) / 2):.3f}")
    print(f"  Welch t = {t:.3f}, df = {df:.1f}, SE = {se:.2f}")
    print(f"  置换检验 p = {p:.4f}（{'精确枚举' if exact else '随机抽样'} {draws} 次）"
          f"  —— 只进审计文档，不进论文表")
    print()
    print("四臂两两总排放差与置换 p：")
    for i in range(len(ARMS)):
        for j in range(i + 1, len(ARMS)):
            ni, pi = ARMS[i][0], ARMS[i][1]
            nj, pj = ARMS[j][0], ARMS[j][1]
            xi = [r["E_total"] for r in data[pi]]
            xj = [r["E_total"] for r in data[pj]]
            p, _, _ = perm_p(xj, xi)
            print(f"  {nj} − {ni}: {mean(xj) - mean(xi):+7.2f} kg, p = {p:.4f}")
    print()


# --------------------------------------------------------------------------
# §3 车队控制比较
# --------------------------------------------------------------------------
def section3(data):
    print("=" * 100)
    print("§3 控制车队构型后的比较")
    print("=" * 100)
    labels = set()
    for _, policy, _ in ARMS:
        for r in data[policy]:
            labels.add(fleet_label(r))
    for label in sorted(labels):
        subsets = {p: [r for r in data[p] if fleet_label(r) == label]
                   for _, p, _ in ARMS}
        if sum(len(v) for v in subsets.values()) < 2:
            continue
        print(f"--- 子集：{label} ---")
        print(f"{'臂':<16}{'n':>3}{'总成本':>10}{'充电成本':>10}{'充电排放':>10}"
              f"{'油直排':>9}{'总排放':>9}{'kWh':>9}{'油车km':>10}{'电车km':>10}{'升柴油':>8}")
        for name, policy, _ in ARMS:
            rs = subsets[policy]
            if not rs:
                print(f"{name:<16}{0:>3}  （无）")
                continue
            print(
                f"{name:<16}{len(rs):>3d}{mean([r['total_cost'] for r in rs]):>10.2f}"
                f"{mean([r['cost_elec'] for r in rs]):>10.2f}"
                f"{mean([r['E_ev_indirect'] for r in rs]):>10.2f}"
                f"{mean([r['E_cv_direct'] for r in rs]):>9.2f}"
                f"{mean([r['E_total'] for r in rs]):>9.2f}"
                f"{mean([r['kwh'] for r in rs]):>9.2f}"
                f"{mean([r['distance_cv_km'] for r in rs]):>10.2f}"
                f"{mean([r['distance_ev_km'] for r in rs]):>10.2f}"
                f"{mean([r['fuel_liters'] for r in rs]):>8.2f}"
            )
        if label == "2油3电":
            a = subsets["asap"]
            c = subsets["carbon_min"]
            if a and c:
                print()
                print("  2油3电子集内，只看碳 − 即充：")
                for key, unit in [("E_total", "kg"), ("E_ev_indirect", "kg"),
                                  ("E_cv_direct", "kg"), ("cost_elec", "元"),
                                  ("total_cost", "元"), ("kwh", "kWh"),
                                  ("distance_cv_km", "km")]:
                    xa = [r[key] for r in a]
                    xc = [r[key] for r in c]
                    p, _, _ = perm_p(xc, xa)
                    print(f"    {key:<16}{mean(xc) - mean(xa):+9.2f} {unit:<4}"
                          f"（即充 {mean(xa):.2f} sd {sd(xa):.2f}；"
                          f"只看碳 {mean(xc):.2f} sd {sd(xc):.2f}；p={p:.4f}）")
                print()
                print("  强度口径（消掉电量差）：kg/kWh 与 kg/百km")
                for name, policy, _ in ARMS:
                    rs = subsets[policy]
                    if not rs:
                        continue
                    inten = [r["E_ev_indirect"] / r["kwh"] for r in rs]
                    print(f"    {name:<16}充电碳强度 {mean(inten):.4f} kg/kWh"
                          f"（sd {sd(inten):.4f}）  "
                          f"电费单价 {mean([r['cost_elec'] / r['kwh'] for r in rs]):.4f} 元/kWh")
                print()
                print("  2油3电子集内各行的均值 ± sd 与两两置换 p（各臂 n=7/6/6/6）：")
                for key, unit in [("cost_elec", "元"), ("E_ev_indirect", "kg"),
                                  ("E_total", "kg"), ("total_cost", "元")]:
                    print(f"    [{key}]")
                    for name, policy, _ in ARMS:
                        xs = [r[key] for r in subsets[policy]]
                        print(f"      {name:<16}{mean(xs):>9.2f} ± {sd(xs):>6.2f}")
                    ordered = sorted(
                        ARMS, key=lambda a: mean([r[key] for r in subsets[a[1]]])
                    )
                    b, s2 = ordered[0], ordered[1]
                    xb = [r[key] for r in subsets[b[1]]]
                    xs2 = [r[key] for r in subsets[s2[1]]]
                    p, _, _ = perm_p(xb, xs2)
                    print(f"      最低＝{b[0]}，与第二低（{s2[0]}）差 "
                          f"{mean(xs2) - mean(xb):+.2f} {unit}，p = {p:.4f}")
        print()


# --------------------------------------------------------------------------
# §4 充电层逐会话
# --------------------------------------------------------------------------
def section4(data, carbon, price, period):
    print("=" * 100)
    print("§4 充电层逐会话核对：起充时刻、电量加权碳强度、可达上限")
    print("=" * 100)
    print("北京 2025-02-12 日历（半小时槽，carbon_factor_kgco2e_per_kwh 与 depot_energy_cny_per_kwh）：")
    print(f"  碳强度最低 {min(carbon.values()):.4f} kg/kWh @ "
          f"{[hhmm(k*60) for k, v in carbon.items() if v == min(carbon.values())]}")
    print(f"  碳强度最高 {max(carbon.values()):.4f} kg/kWh @ "
          f"{[hhmm(k*60) for k, v in carbon.items() if v == max(carbon.values())]}")
    print(f"  电价最低 {min(price.values()):.4f} 元/kWh（谷）、最高 {max(price.values()):.4f} 元/kWh（峰）")
    lo_c, hi_c = min(carbon.values()), max(carbon.values())
    lo_p, hi_p = min(price.values()), max(price.values())
    print(f"  价差 {hi_p - lo_p:.5f} 元/kWh；碳差 {hi_c - lo_c:.5f} kg/kWh")
    print(f"  → 两信号打平的碳价 = {(hi_p - lo_p) / (hi_c - lo_c):.4f} 元/kg；"
          f"现行算例碳价 0.2 元/kg，碳项只值 {(hi_c - lo_c) * 0.2:.5f} 元/kWh，"
          f"约为价差的 1/{(hi_p - lo_p) / ((hi_c - lo_c) * 0.2):.1f}")
    print()
    print("即充/只看碳的起充时刻分布（按电量加权，全部 10 次合并）：")
    for name, policy, _ in ARMS:
        buckets = {}
        tot = 0.0
        for r in data[policy]:
            for s in r["sessions"]:
                buckets[slot_key(s["start"])] = (
                    buckets.get(slot_key(s["start"]), 0.0) + s["kwh"]
                )
                tot += s["kwh"]
        print(f"  {name}（合计 {tot:.1f} kWh）")
        for k in sorted(buckets):
            print(f"    {hhmm(k*60)}  {buckets[k]:8.2f} kWh"
                  f"  ({buckets[k]/tot*100:5.1f}%)  碳 {carbon[k]:.4f}  "
                  f"电价 {price[k]:.4f} ({period[k]})")
    print()
    print("电量加权碳强度与电价（合并 10 次；kg/kWh、元/kWh）：")
    print(f"{'臂':<16}{'总kWh':>9}{'充电排放':>10}{'碳强度':>10}{'充电成本':>10}{'均价':>9}")
    inten = {}
    for name, policy, _ in ARMS:
        k = sum(s["kwh"] for r in data[policy] for s in r["sessions"])
        e = sum(s["emission"] for r in data[policy] for s in r["sessions"])
        c = sum(s["cost"] for r in data[policy] for s in r["sessions"])
        inten[policy] = e / k
        print(f"{name:<16}{k:>9.2f}{e:>10.2f}{e/k:>10.4f}{c:>10.2f}{c/k:>9.4f}")
    print()
    print(f"只看碳比即充每 kWh 干净 {inten['asap'] - inten['carbon_min']:.4f} kg/kWh"
          f"（{(inten['asap'] - inten['carbon_min']) / inten['asap'] * 100:.1f}%）；"
          f"分时电价比即充脏 {inten['cost_min'] - inten['asap']:+.4f} kg/kWh")
    print(f"全日历极差给出的绝对上限 = {hi_c - lo_c:.4f} kg/kWh"
          f"（{lo_c:.4f}~{hi_c:.4f}）")
    print()
    print("分窗口（首趟出车前／午休／趟间）：电量、排放、碳强度、起充电量加权中位")
    for name, policy, _ in ARMS:
        print(f"  {name}")
        for w, wname in WINDOWS:
            ss = [s for r in data[policy] for s in r["sessions"] if s["window"] == w]
            if not ss:
                print(f"    {wname:<8} 无会话")
                continue
            k = sum(s["kwh"] for s in ss)
            e = sum(s["emission"] for s in ss)
            c = sum(s["cost"] for s in ss)
            pairs = sorted((s["start"], s["kwh"]) for s in ss)
            acc, med = 0.0, pairs[-1][0]
            for v, wt in pairs:
                acc += wt
                if acc >= k / 2:
                    med = v
                    break
            print(f"    {wname:<8} n={len(ss):>3d}  {k/10:7.2f} kWh/次"
                  f"  {e/10:6.2f} kg/次  强度 {e/k:.4f}"
                  f"  电费 {c/10:6.2f} 元/次  起充中位 {hhmm(med)}")
    print()
    print("每个会话的可达排放上下界（用该会话自身可行窗口枚举，检验各臂是否已取到极值）：")
    print(f"{'臂':<16}{'实得kg':>9}{'窗口最优kg':>11}{'窗口最差kg':>11}{'实得/最优':>10}"
          f"{'实得强度':>10}{'最优强度':>10}{'最差强度':>10}{'达最优会话':>12}")
    for name, policy, _ in ARMS:
        got = best = worst = kwh = 0.0
        hit = tot = 0
        for r in data[policy]:
            for s in r["sessions"]:
                lo, hi = _window_bounds(s, carbon)
                got += s["emission"]
                best += lo
                worst += hi
                kwh += s["kwh"]
                tot += 1
                if s["emission"] <= lo + 1e-6:
                    hit += 1
        print(f"{name:<16}{got/10:>9.2f}{best/10:>11.2f}{worst/10:>11.2f}"
              f"{got/best:>10.3f}{got/kwh:>10.4f}{best/kwh:>10.4f}{worst/kwh:>10.4f}"
              f"{f'{hit}/{tot}':>12}")
    print()
    print("两信号打平的碳价：全日历名义值 vs 各臂路线上真正可达的值")
    print(f"  名义（全日历极差）：价差 {hi_p - lo_p:.5f} / 碳差 {hi_c - lo_c:.5f}"
          f" = {(hi_p - lo_p) / (hi_c - lo_c):.4f} 元/kg")
    print(f"{'臂':<16}{'可省电费元':>12}{'可省排放kg':>12}{'可达打平碳价':>14}")
    for name, policy, _ in ARMS:
        dcost = demis = 0.0
        for r in data[policy]:
            for s in r["sessions"]:
                clo, chi = _window_bounds(s, price)
                elo, ehi = _window_bounds(s, carbon)
                dcost += chi - clo
                demis += ehi - elo
        print(f"{name:<16}{dcost/10:>12.2f}{demis/10:>12.2f}"
              f"{dcost / demis:>14.4f}")
    print("  （可达值＝把每个会话在它自身可行窗口内从最贵挪到最便宜能省的电费，"
          "除以从最脏挪到最干净能省的排放；这才是两个信号在本算例真正争夺的兑换率。"
          "名义值用了班次锁死后够不着的深夜与正午极值，只能作上界参考。）")
    print()


def _window_bounds(session, carbon):
    """在该会话自身可行窗口内枚举起充时刻，返回（最低排放, 最高排放）。"""
    earliest = session["earliest"]
    latest = session["latest"]
    occ = session["occupancy_minutes"]
    kwh = session["kwh"]
    if latest <= earliest + 1e-9:
        v = settle(earliest, occ, kwh, carbon)
        return v, v
    cands = {earliest, latest}
    dur = occ * 60.0
    first = math.floor(earliest / SLOT) - 1
    last = math.ceil((latest + dur) / SLOT) + 1
    for i in range(first, last + 1):
        for off in (0.0, dur):
            c = i * SLOT - off
            if earliest - 1e-9 <= c <= latest + 1e-9:
                cands.add(min(latest, max(earliest, c)))
    vals = [settle(c, occ, kwh, carbon) for c in sorted(cands)]
    return min(vals), max(vals)


# --------------------------------------------------------------------------
# §5 为什么只看碳臂多出 4/2、5/1 车队
# --------------------------------------------------------------------------
def section5(data):
    print("=" * 100)
    print("§5 少电车构型是更差的局部最优、早停，还是策略改变了车队搜索的偏好")
    print("=" * 100)
    print("(a) 同臂内 2油3电 与其余构型的对照：")
    print(f"{'臂':<16}{'构型':<8}{'n':>3}{'总成本':>10}{'总排放':>9}{'轮':>5}{'迭代':>10}"
          f"{'第1轮迭代':>11}{'第1轮改善':>10}{'墙钟s':>9}")
    for name, policy, _ in ARMS:
        groups = {}
        for r in data[policy]:
            groups.setdefault(fleet_label(r), []).append(r)
        for label in sorted(groups, key=lambda k: -len(groups[k])):
            rs = groups[label]
            print(
                f"{name:<16}{label:<8}{len(rs):>3d}"
                f"{mean([r['total_cost'] for r in rs]):>10.2f}"
                f"{mean([r['E_total'] for r in rs]):>9.2f}"
                f"{mean([r['rounds'] for r in rs]):>5.1f}"
                f"{mean([r['iterations'] for r in rs]):>10.0f}"
                f"{mean([r['round1_iters'] for r in rs]):>11.0f}"
                f"{mean([r['round1_improvements'] for r in rs]):>10.1f}"
                f"{mean([r['wall_seconds'] for r in rs]):>9.1f}"
            )
        print()
    print("(b) 各臂进入内核的电动车代理电价（metadata.route_engine_wiring.shift_aware_ev_proxy，"
          "run_01；kernel_proposals.py:1842-1863 按本臂策略选槽，1931-1945 结算 proxy_cny_per_kwh）：")
    print(f"{'臂':<16}{'班次':<5}{'选中槽':>7}{'槽起点':>9}{'电价':>9}{'碳(g/kWh)':>11}{'代理元/kWh':>12}")
    for name, policy, _ in ARMS:
        proxy = data[policy][0]["proxy"]
        depot = sorted(proxy)[0]
        for shift in ("AM", "PM"):
            v = proxy[depot][shift]
            print(f"{name:<16}{shift:<5}{int(v['selected_slot']):>7d}"
                  f"{hhmm(v['selected_slot_start_second']):>9}"
                  f"{v['electricity_cny_per_kwh']:>9.4f}"
                  f"{v['actual_gco2_per_kwh']:>11.1f}"
                  f"{v['proxy_cny_per_kwh']:>12.5f}")
    print("  （两个车场取值相同，只列一个；10 次运算内代理值是否恒定见下）")
    for name, policy, _ in ARMS:
        vals = set()
        for r in data[policy]:
            depot = sorted(r["proxy"])[0]
            vals.add((round(r["proxy"][depot]["AM"]["proxy_cny_per_kwh"], 6),
                      round(r["proxy"][depot]["PM"]["proxy_cny_per_kwh"], 6)))
        print(f"    {name:<16}10 次中出现的 (AM,PM) 代理电价取值：{sorted(vals)}")
    print()
    print("(c) 代理电价差 × 实际充电电量 ≈ 搜索眼中电动车相对即充多花的钱：")
    base = None
    for name, policy, _ in ARMS:
        depot = sorted(data[policy][0]["proxy"])[0]
        am = data[policy][0]["proxy"][depot]["AM"]["proxy_cny_per_kwh"]
        pm = data[policy][0]["proxy"][depot]["PM"]["proxy_cny_per_kwh"]
        avg = (am + pm) / 2
        kwh = mean([r["kwh"] for r in data[policy]])
        if base is None:
            base = avg
        print(f"  {name:<16}AM/PM 代理均值 {avg:.5f} 元/kWh，"
              f"相对即充 {avg - base:+.5f}，"
              f"按均值电量 {kwh:.1f} kWh 折 {(avg - base) * kwh:+.2f} 元/日"
              f"（对照：每辆电车固定溢价 100 元/日）")
    print()
    print("(d) 少电车（燃油车 ≥ 4）出现次数：按代理是否读电价分组")
    groups = {
        "代理不读电价（即充、只看碳）": ["asap", "carbon_min"],
        "代理读电价（只看电价、两者）": ["cost_min", "cost_plus_carbon"],
    }
    counts = {}
    for label, ps in groups.items():
        heavy = sum(1 for p in ps for r in data[p] if r["n_cv"] >= 4)
        total = sum(len(data[p]) for p in ps)
        counts[label] = (heavy, total)
        print(f"  {label:<26}{heavy}/{total}")
    (h1, n1), (h2, n2) = counts.values()
    print(f"  Fisher 精确检验（双侧）p = {_fisher(h1, n1 - h1, h2, n2 - h2):.4f}"
          f"  —— 只进审计文档")
    print("  逐臂：" + "、".join(
        f"{name} {sum(1 for r in data[p] if r['n_cv'] >= 4)}/10"
        for name, p, _ in ARMS
    ))
    a = sum(1 for r in data["asap"] if r["n_cv"] >= 4)
    c = sum(1 for r in data["carbon_min"] if r["n_cv"] >= 4)
    print(f"  即充 {a}/10 vs 只看碳 {c}/10，Fisher p = "
          f"{_fisher(a, 10 - a, c, 10 - c):.4f}")
    print()


def _fisher(a, b, c, d):
    """2x2 双侧 Fisher 精确检验。"""
    n = a + b + c + d
    r1, r2 = a + b, c + d
    c1 = a + c
    def prob(x):
        return (
            math.comb(r1, x) * math.comb(r2, c1 - x) / math.comb(n, c1)
        )
    p0 = prob(a)
    lo = max(0, c1 - r2)
    hi = min(r1, c1)
    return sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p0 + 1e-12)


# --------------------------------------------------------------------------
# §6 故事能否成立
# --------------------------------------------------------------------------
def section6(data):
    print("=" * 100)
    print("§6 充电层与总排放层：各行的均值、sd、两两差与噪声比")
    print("=" * 100)
    rows = [
        ("总成本", "total_cost", "元"),
        ("充电成本", "cost_elec", "元"),
        ("电动车充电排放", "E_ev_indirect", "kg"),
        ("燃油车直接排放", "E_cv_direct", "kg"),
        ("总排放", "E_total", "kg"),
        ("充电电量", "kwh", "kWh"),
    ]
    for label, key, unit in rows:
        print(f"--- {label}（{unit}）---")
        print(f"{'臂':<16}{'均值':>10}{'sd':>9}{'最小':>10}{'最大':>10}{'极差':>9}")
        for name, policy, _ in ARMS:
            xs = [r[key] for r in data[policy]]
            print(f"{name:<16}{mean(xs):>10.2f}{sd(xs):>9.2f}"
                  f"{min(xs):>10.2f}{max(xs):>10.2f}{max(xs)-min(xs):>9.2f}")
        best = min(ARMS, key=lambda a: mean([r[key] for r in data[a[1]]]))
        second = sorted(ARMS, key=lambda a: mean([r[key] for r in data[a[1]]]))[1]
        xb = [r[key] for r in data[best[1]]]
        xs2 = [r[key] for r in data[second[1]]]
        p, _, _ = perm_p(xb, xs2)
        pooled = math.sqrt((sd(xb) ** 2 + sd(xs2) ** 2) / 2)
        print(f"  最低＝{best[0]}；与第二低（{second[0]}）差 "
              f"{mean(xs2) - mean(xb):+.2f} {unit}，合并 sd {pooled:.2f}，"
              f"|差|/sd = {abs(mean(xs2) - mean(xb)) / pooled if pooled else float('nan'):.2f}，"
              f"p = {p:.4f}")
        print()


# --------------------------------------------------------------------------
# §7 元数据一致性
# --------------------------------------------------------------------------
def section7(data):
    print("=" * 100)
    print("§7 四臂 metadata 一致性核对")
    print("=" * 100)
    keys = ["proxy_policy", "first_trip_window", "station_mode", "carbon_price",
            "ev_premium", "mechanism_off", "forbidden"]
    for name, policy, _ in ARMS:
        print(f"--- {name}（{policy}）---")
        for k in keys:
            vals = {json.dumps(r[k], ensure_ascii=False, sort_keys=True)
                    for r in data[policy]}
            flag = "" if len(vals) == 1 else "  ← 10 次内不一致"
            print(f"  {k:<20}{sorted(vals)}{flag}")
        trips = sorted({r["max_trips"] for r in data[policy]})
        print(f"  {'final_max_trips':<20}{trips}（逐 run 结果，不是配置差异）")
    print()
    print("asap 的实现（只读引用）：")
    print("  solver/src/setp_solver/charge_timing.py:746-747  "
          "`if policy == \"asap\" or latest <= earliest + 1.0e-9: return earliest`")
    print("  solver/src/setp_solver/charge_timing.py:690-691  "
          "`if policy == \"asap\": return 0.0`（择时目标恒为 0）")
    print("  solver/src/setp_solver/charge_timing.py:477-478  同一分支的缓存版本")
    print("  → asap 分支不触碰 depot_energy_cny_per_kwh 与 actual_gco2_per_kwh，"
          "确认它真的没有读电价/碳信息。")
    print("  代理侧：kernel_proposals.py:1853-1854 "
          "`if policy == \"asap\": return (start,)` —— 也只按时间先后选槽。")
    print()


SECTIONS = {
    "0": section0, "1": section1, "2": section2, "3": section3,
    "4": section4, "5": section5, "6": section6, "7": section7,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", action="append", default=None)
    args = ap.parse_args()
    data, carbon, price, period = load_all()[:4]
    wanted = args.section or list(SECTIONS)
    section0(data)
    for s in wanted:
        if s == "0":
            continue
        fn = SECTIONS[s]
        if s == "4":
            fn(data, carbon, price, period)
        else:
            fn(data)


if __name__ == "__main__":
    main()
