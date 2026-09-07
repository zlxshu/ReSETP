#!/usr/bin/env python3
"""从 4.3 动力配置表推导「换一辆燃油车为电动车」的平价碳价 P*（2026-09-09）。

## 为什么做这件事

4.4.3 组合方案里的碳价 1.2 / 0.6 和购置补贴 46.97 元/日，出处是本方的离线裕度分析与
敏感性扫描，不是文献，也没有推导（`docs/paper_gci_dmm_vrp_20260804/pending_decisions.md`
2026-09-09 16:00 条）。本脚本把这些参数改成**由机理推导**：4.3 动力配置表的七档
（6 燃油 0 电动 … 0 燃油 6 电动，全方案总车数恒为 6）给出每档的运营成本与碳排量，
相邻两档之间恰好是「换一辆燃油车为电动车」这一个动作，于是

    P*  =  Δ运营成本 / Δ减排量
        = [ (OC_{k+1} − s·nEV_{k+1}) − (OC_k − s·nEV_k) ] / ( E_k − E_{k+1} )

就是让企业在这两档之间无差异的碳价；每辆电动车每日补贴 s 把分子减少 s（因为
nEV 只差 1），于是 P*(s) 是 s 的一条直线。**这不是新模型，只是把落盘解的五项成本
按定义重排**，所以可以完全离线、不跑求解器地算出来。

## 口径

- 运营成本 OC = cost_fix(满额溢价) + cost_km + cost_fuel + cost_elec，**不含碳费**。
  落盘 `cost_fix` 已是满额溢价口径（七档 metadata 的 `effective_ev_daily_premium_cny`
  实测均为 100.0、`effective_carbon_quota_kg` 均为 0.0、碳价均为 0.2），脚本逐份断言
  `cost_fix == 170×(燃油车+电动车) + 100×电动车`，所以补贴 s 只在这里以 −s×nEV 出现。
- 碳排量 E 直接取落盘 `E_total`；本脚本用到的两份日历**只改电价列，碳强度整列逐位相同**
  （脚本对整列做 sha256 断言），所以换电价日历不改 E。
- 某档的代表解 = 该档全部分法、全部 run 里**总成本最低**的一份。七档的胜出分法各有
  3 个 run（其余分法只有 1 个），脚本报出胜出分法 3 次的极差，并用 3×3 个组合给出 P*
  的噪声区间——单点 P* 不是常数。

## 三层证据，强度依次递减（报告里不许混为一谈）

1. **北京现行日历、固定 6 车（第一层，最硬）**：七档解本身就是在这个口径下搜出来的，
   P* 是对这七个解的**精确**重排，除了「每档代表解是否已是该档最优」以外没有近似。
2. **午谷日历、只重新计价（第二层，任务书指定的近似）**：路线与充电时刻一律不动，
   只把充电会话按 `china81_cf_calendar_midday_valley_v1_20260904` 的电价重算
   （半小时槽分摊，逐字照抄 `build_charging_windows_table.py` 的 session_emission）。
   **方向不是单向的**：七档解的充电时刻是在北京夜谷（23:00–07:00）下挑的，换成午谷
   12:00–15:00 后，夜间充电多的档变贵、白天充电多的档变便宜，实测 1/5 档 +10.42 元、
   0/6 档 +2.83 元，而 5/1 档 −8.93 元、4/2 档 −8.63 元。所以任务书说的「一律高估
   电动车成本、P* 偏高」只对一部分转换成立，脚本把每档的电费增减逐档报出来。
3. **午谷日历、重优化方案池（第三层，用来裁决与实跑的一致性）**：仓库里已有 89 份
   在午谷日历下**真正重搜**过的解（配置覆盖 0/6、1/5、2/4、3/3、4/2、5/1 与 5 车的
   2/3、1/4）。第二层的近似误差实测大于它要分辨的信号（重新计价给 1/5 的上界是
   2578.52 元，而午谷下实跑的 1/5 解只要 2530.99 元，差 47.5 元，比第二层七档之间的
   全部差距 21 元还大），所以**与实跑批次对不对得上这件事只用第三层裁决**，第二层
   只作为任务书指定方法的留档。

## 一条贯穿全篇的边界：本推导是「固定 6 车」的

七档全部是 6 辆车，只动油电比例。而用来核对的批次（碳价扫描、午谷组合）**车队规模
是搜出来的**：扫描下包络的低碳价赢家是 2 燃油 3 电动＝5 辆车，午谷＋补贴 24 那 10 次
里也有 2 次落到 2/3。也就是说，**九个实测点没有一个来自固定 6 车的运算**，本推导的
动作空间不含它们的真实最优。因此：

- 与实测点比对只能做「方向一致 / 落在哪个区间」这种粗判，几元的出入没有意义；
- 扫描下包络的 1.5506（1/5→0/6）与本推导的 1.5737（1/5→0/6）是**同一类转换、
  两个互不相交的解池**给出的独立读数，差 1.5%，这一条才是真正的交叉验证；
- 扫描下包络的 1.3294 是 2/3→1/5，是「5 车变 6 车」，本推导表示不了，**不得**拿去和
  1.149 或 1.691 配对；0.7891 是同构型折点（更好的解接管），根本不是车队翻转。

## 用法（仓库根目录，只读；不跑求解器、不改代码、不改论文）

    .public-hgs-venv/bin/python3 solver/scripts/derive_fleet_parity_carbon_price_20260909.py

输出（`solver/reports/derive_fleet_parity_20260909/`）：
  tier_costs.csv       七档代表解的成本分项、E、午谷重新计价后的电费与运营成本
  parity_prices.csv    每个相邻转换 × 每个补贴档 × 三层口径的 ΔC / ΔE / P* 与噪声区间
  envelope_regions.csv 每个补贴档下最优档位随碳价的分段（含各段端点碳价）
  measured_points.csv  九个实测点的观测构型与三层口径下的推导构型
  pool_configs.csv     午谷 / 北京两个重优化方案池按构型的最优解、份数与最低−次低间距
图：`docs/paper_v2/generated_figures/figure_parity_map.pdf`（候选，黑白，默认 3.4×2.6 英寸）
  `--wide` 出 6.9×2.6 英寸版（本刊单栏版心 165mm、图以 \\textwidth 插入，3.4 英寸会被
  放大约 1.8 倍，8pt 字实印约 14pt——真要进正文用 --wide 那一版）。
  `--no-figure` 只出 CSV。`--dry-run` 只打印不落盘。

## 这张图的图注（跟着 PDF 走，别只留在报告里）

> 补贴—碳价平面上的最优动力配置分区。实线为 4.3 动力配置结果（北京现行分时电价、
> 总车数固定 6 辆）按 P*(s)=(ΔC−s)/ΔE 解析求出的分区边界，标注为「燃油车数/电动车数」；
> 虚线为同一算法在午间谷段日历下、用已重优化方案池（仅 6 车构型）得到的边界。
> 实心圆为北京日历下的实测点，空心方为午间谷段日历下的实测点，点旁标注为该点若干次
> 运算的众数构型。**图中没有任何一个实测点来自「总车数固定 6 辆」的运算**（实测允许
> 搜索自行决定车队规模），故实测点与实线只能作趋势对照，不作逐点吻合的证据。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "solver/reports/derive_fleet_parity_20260909"
FIG_OUT = REPO / "docs/paper_v2/generated_figures/figure_parity_map.pdf"

FLEET_ROOT = REPO / "solver/reports/fleet_composition_formal_v3_20260904"
TIERS = ["6-0", "5-1", "4-2", "3-3", "2-4", "1-5", "0-6"]   # 燃油-电动，总车数恒 6

CAL_DIR = REPO / "data/ChinaInstances"
BASE_CAL = "china81_runtime_parameter_authority_v4_20260723"
MID_CAL = "china81_cf_calendar_midday_valley_v1_20260904"

KEEP_INSTANCE = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
SERVED_CUSTOMERS = 50
FIX_BASE_PER_VEH = 170.0
EV_FULL_PREMIUM = 100.0
CITY, DATE = "beijing", "2025-02-12"
DAY, SLOT = 86400.0, 1800.0

SUBSIDIES = (0.0, 24.0, 46.97)     # 元/车/日：无补贴、目录价差折算、含一次换电池的资本口径
P_MAX_FIG = 2.0
S_MAX_FIG = 50.0

# 重优化方案池（与 probe_combo_margin_20260908.py 同源同排除规则）
POOL_ROOTS = [
    "solver/reports/grid2x2_v3_20260906",
    "solver/reports/carbon_price_sweep_v3_20260906",
    "solver/reports/policy_combos_20260907",
    "solver/reports/charging_arrangements_20260906",
]

# 九个实测点：(补贴 s, 碳价 P, 日历, 产物目录)。前六个是午谷组合批，后三个是北京碳价扫描。
MEASURED = [
    (24.0, 0.2, "midday", "solver/reports/policy_combos_20260907/"
                          "midday_subsidy_parallel_pre_split_20260908"),
    (24.0, 0.6, "midday", "solver/reports/policy_combos_20260907/midday_subsidy24_P0.6"),
    (24.0, 1.2, "midday", "solver/reports/policy_combos_20260907/midday_subsidy24_P1.2"),
    (46.97, 0.2, "midday", "solver/reports/policy_combos_20260907/midday_subsidy47_P0.2"),
    (46.97, 0.6, "midday", "solver/reports/policy_combos_20260907/midday_subsidy47_P0.6"),
    (46.97, 1.2, "midday", "solver/reports/policy_combos_20260907/midday_subsidy47_P1.2"),
    (0.0, 0.2, "beijing", "solver/reports/carbon_price_sweep_v3_20260906/P=0.2"),
    (0.0, 1.0, "beijing", "solver/reports/carbon_price_sweep_v3_20260906/P=1.0"),
    (0.0, 1.5, "beijing", "solver/reports/carbon_price_sweep_v3_20260906/P=1.5"),
]

# 碳价扫描 summary.md 已登记的下包络翻转价（只作对照，脚本不重算它）
SWEEP_FLIPS = {"0.7891": "同构型折点(2/3→2/3，更好的解接管)",
               "1.3294": "2/3→1/5（5 车变 6 车，本推导表示不了）",
               "1.5506": "1/5→0/6（与本推导 1/5→0/6 同类转换）"}


# --------------------------------------------------------------------------
# 日历与电费
# --------------------------------------------------------------------------
def read_calendar(name: str) -> tuple[dict[int, tuple[float, float]], str]:
    """读一份日历，返回 ({半小时槽起点分钟: (场站电价, 公共站总价)}, 碳强度整列 sha256)。"""
    path = CAL_DIR / name / "tariff_carbon_hourly_calendar.csv"
    by_date: dict[str, dict[int, tuple[float, float]]] = {}
    carbon_col: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            carbon_col.append(f'{r["city"]}|{r["date"]}|{r["minute_of_day"]}|'
                              f'{r["carbon_factor_kgco2e_per_kwh"]}')
            if r["city"] != CITY:
                continue
            by_date.setdefault(r["date"], {})[int(r["minute_of_day"])] = (
                float(r["depot_energy_cny_per_kwh"]),
                float(r["public_total_cny_per_kwh"]),
            )
    ref = by_date[DATE]
    for d, prof in by_date.items():
        assert prof == ref, f"{name}: {d} 的日内电价曲线与 {DATE} 不同"
    assert len(ref) == 48, f"{name}: 半小时槽数 {len(ref)} != 48"
    return ref, hashlib.sha256("\n".join(carbon_col).encode()).hexdigest()


def slot_of(second: float) -> int:
    return int((second % DAY) // 60 // 30) * 30


def session_cost(start: float, minutes: float, kwh: float, price: dict[int, float]) -> float:
    """按半小时槽分摊电量计价，逐字照抄 build_charging_windows_table.py 的 session_emission。"""
    if minutes <= 0:
        return kwh * price[slot_of(start)]
    total, t, end = 0.0, start, start + minutes * 60
    while t < end - 1e-9:
        nxt = (t // SLOT + 1) * SLOT
        seg = min(nxt, end) - t
        total += kwh * (seg / (minutes * 60)) * price[slot_of(t)]
        t = nxt
    return total


def elec_cost(sessions, cal) -> float:
    depot = {m: v[0] for m, v in cal.items()}
    public = {m: v[1] for m, v in cal.items()}
    return math.fsum(
        session_cost(st, mn, kwh, depot if str(sid)[:2] == "D_" else public)
        for st, mn, kwh, sid in sessions
    )


def valley_hours(cal) -> list[float]:
    lo = min(v[0] for v in cal.values())
    return sorted(m / 60.0 for m, v in cal.items() if abs(v[0] - lo) < 1e-9)


# --------------------------------------------------------------------------
# 读一份落盘解
# --------------------------------------------------------------------------
def read_solution(run_dir: Path, *, require_beijing_cal: bool | None = None) -> dict | None:
    """读一个 run 目录，做完整自检；不合格返回 None（附原因打到 stderr 由调用方决定）。"""
    sol_path = run_dir / "best_solution.json"
    meta_path = run_dir / "metadata.json"
    if not sol_path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    rel = str(run_dir.relative_to(REPO))
    if meta.get("instance_id") != KEEP_INSTANCE:
        return None
    if (meta.get("route_engine_wiring") or {}).get("first_trip_window") != "prev_return":
        return None            # 旧首趟补电口径，首趟前补电起点可写死 00:00 白捡谷价
    assert meta.get("status") == "COMPLETE", rel
    sol = json.loads(sol_path.read_text(encoding="utf-8"))
    ev = sol["evaluation"]
    assert ev["feasible"] and not ev["violations"], rel
    assert not sol["individual"]["unserved_customers"], rel
    served = {n for r in ev["prepared_solution"]["routes"]
              for n in r["node_sequence"] if n.startswith("C")}
    assert len(served) == SERVED_CUSTOMERS, (rel, len(served))
    bd = ev["breakdown"]
    cal_name = _calendar_of(meta)
    if require_beijing_cal is True:
        assert cal_name == BASE_CAL, (rel, cal_name)
    sessions = [
        (c["charge_start_second"] + c["charge_day_offset"] * DAY,
         c["occupancy_minutes"], c["energy_kwh"], c["station_id"])
        for duty in sol["individual"]["duties"] for c in duty["charging_sessions"]
    ]
    for _, _, _, sid in sessions:
        assert str(sid)[:2] in ("D_", "S_"), f"{rel}: 未知节点前缀 {sid}"
    cv, nev = int(bd["n_veh_cv"]), int(bd["n_veh_ev"])
    run_s = EV_FULL_PREMIUM - float(meta["effective_ev_daily_premium_cny"])
    run_P = float(meta["carbon_price_cny_per_kg"])
    run_Q = float(meta["effective_carbon_quota_kg"])
    # 自检：五项加总、固定成本公式、碳成本公式
    five = (bd["cost_fix"] + bd["cost_km"] + bd["cost_fuel"]
            + bd["cost_elec"] + bd["cost_carbon"])
    assert abs(five - bd["total_cost"]) < 1e-6, (rel, five, bd["total_cost"])
    fix_expect = FIX_BASE_PER_VEH * (cv + nev) + nev * (EV_FULL_PREMIUM - run_s)
    assert abs(fix_expect - bd["cost_fix"]) < 1e-9, (rel, fix_expect, bd["cost_fix"])
    cc = (float(bd["E_total"]) - run_Q) * run_P
    assert abs(cc - bd["cost_carbon"]) < 1e-6, (rel, cc, bd["cost_carbon"])
    return dict(
        path=rel, calendar=cal_name, cv=cv, nev=nev, veh=cv + nev,
        run_s=run_s, run_P=run_P, run_Q=run_Q,
        cost_fix=float(bd["cost_fix"]), cost_km=float(bd["cost_km"]),
        cost_fuel=float(bd["cost_fuel"]), cost_elec=float(bd["cost_elec"]),
        cost_carbon=float(bd["cost_carbon"]), total=float(bd["total_cost"]),
        E=float(bd["E_total"]), sessions=sessions,
        # 满额溢价口径的运营成本（补贴 s 之后再减 s×nev）
        oc_full=(FIX_BASE_PER_VEH * (cv + nev) + nev * EV_FULL_PREMIUM
                 + float(bd["cost_km"]) + float(bd["cost_fuel"]) + float(bd["cost_elec"])),
    )


def _calendar_of(meta: dict) -> str:
    for v in json.dumps(meta.get("bundle_source_paths")).split('"'):
        if "calendar" in v and v.endswith(".csv"):
            return Path(v).parent.name
    raise KeyError("metadata 里找不到 tariff 日历路径")


# --------------------------------------------------------------------------
# 七档代表解
# --------------------------------------------------------------------------
def load_tiers(cal_base, cal_mid) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for tier in TIERS:
        cv_want, ev_want = (int(x) for x in tier.split("-"))
        runs: list[tuple[str, dict]] = []
        for split_dir in sorted((FLEET_ROOT / tier).iterdir()):
            if not split_dir.is_dir():
                continue
            for run_dir in sorted(split_dir.iterdir()):
                if not run_dir.is_dir():
                    continue
                s = read_solution(run_dir, require_beijing_cal=True)
                if s is None:
                    continue
                assert (s["cv"], s["nev"]) == (cv_want, ev_want), (s["path"], s["cv"], s["nev"])
                assert s["run_s"] == 0.0 and s["run_Q"] == 0.0 and s["run_P"] == 0.2, s["path"]
                own = elec_cost(s["sessions"], cal_base)
                assert abs(own - s["cost_elec"]) <= 1e-9 * max(1.0, s["cost_elec"]), \
                    (s["path"], own, s["cost_elec"])
                runs.append((f"{split_dir.name}/{run_dir.name}", s))
        assert runs, tier
        runs.sort(key=lambda kv: kv[1]["total"])
        best_split = runs[0][0].split("/")[0]
        sibs = [s for k, s in runs if k.split("/")[0] == best_split]
        rep = runs[0][1]
        rep = dict(rep)
        rep["src"] = runs[0][0]
        rep["n_runs_tier"] = len(runs)
        rep["best_split"] = best_split
        rep["split_runs"] = sibs                      # 胜出分法的全部 run（噪声区间用）
        rep["split_range"] = max(x["total"] for x in sibs) - min(x["total"] for x in sibs)
        rep["elec_mid"] = elec_cost(rep["sessions"], cal_mid)
        rep["oc_mid"] = rep["oc_full"] - rep["cost_elec"] + rep["elec_mid"]
        for x in sibs:
            x["elec_mid"] = elec_cost(x["sessions"], cal_mid)
            x["oc_mid"] = x["oc_full"] - x["cost_elec"] + x["elec_mid"]
        out[tier] = rep
    return out


# --------------------------------------------------------------------------
# 平价碳价与下包络
# --------------------------------------------------------------------------
def pstar(a: dict, b: dict, key: str, s: float) -> tuple[float, float, float]:
    """a→b（b 比 a 多一辆电动车）的 ΔC / ΔE / P*。key ∈ {oc_full, oc_mid}。"""
    dC = (b[key] - s * b["nev"]) - (a[key] - s * a["nev"])
    dE = a["E"] - b["E"]
    return dC, dE, dC / dE


def envelope(items: list[dict], key: str, s: float, p_max: float) -> list[dict]:
    """min_i (A_i + E_i·P) 在 P∈[0, p_max] 上的下包络分段。A_i = key − s·nev。

    解析求：P=0 时取截距最小者；此后在**斜率更小**（碳排更低）的候选里找交点碳价最小的
    那个，依次接管。返回 [{p_lo, p_hi, item, cost_lo, cost_hi}, ...]。
    """
    lines = [(x[key] - s * x["nev"], x["E"], x) for x in items]
    cur = min(lines, key=lambda t: (t[0], t[1]))
    segs, p = [], 0.0
    while True:
        nxt, p_cross = None, math.inf
        for A, E, obj in lines:
            if E >= cur[1] - 1e-12:
                continue
            pc = (A - cur[0]) / (cur[1] - E)
            if pc > p + 1e-9 and (pc < p_cross - 1e-9
                                  or (abs(pc - p_cross) <= 1e-9 and E < nxt[1])):
                nxt, p_cross = (A, E, obj), pc
        end = min(p_cross, p_max) if nxt else p_max
        segs.append(dict(p_lo=p, p_hi=end, item=cur[2],
                         cost_lo=cur[0] + cur[1] * p, cost_hi=cur[0] + cur[1] * end))
        if not nxt or p_cross >= p_max - 1e-12:
            break
        cur, p = nxt, p_cross
    return segs


def envelope_curves(items: list[dict], key: str, s_grid: list[float], p_max: float):
    """对每个补贴 s 求下包络，返回 {构型: [(s, p_lo, p_hi), ...]}（同构型多段已合并）。"""
    out: dict[str, list[tuple[float, float, float]]] = {}
    for s in s_grid:
        merged: dict[str, tuple[float, float]] = {}
        for sg in envelope(items, key, s, p_max):
            t = f'{sg["item"]["cv"]}/{sg["item"]["nev"]}'
            lo, hi = merged.get(t, (sg["p_lo"], sg["p_hi"]))
            merged[t] = (min(lo, sg["p_lo"]), max(hi, sg["p_hi"]))
        for t, (lo, hi) in merged.items():
            out.setdefault(t, []).append((s, lo, hi))
    return out


def cheapest_config(items: list[dict], key: str, s: float, P: float):
    """给定 (s, P)，返回按构型排序的 [(构型, 最低总成本, 份数, 来源)]。"""
    by: dict[tuple[int, int], list[tuple[float, dict]]] = {}
    for x in items:
        by.setdefault((x["cv"], x["nev"]), []).append(
            (x[key] - s * x["nev"] + P * x["E"], x))
    rows = []
    for cfg, lst in by.items():
        lst.sort(key=lambda t: t[0])
        rows.append((cfg, lst[0][0], len(lst),
                     lst[0][1].get("src", lst[0][1]["path"]),
                     (lst[1][0] - lst[0][0]) if len(lst) > 1 else float("nan")))
    rows.sort(key=lambda r: r[1])
    return rows


# --------------------------------------------------------------------------
# 重优化方案池
# --------------------------------------------------------------------------
def load_pool(cal_base) -> list[dict]:
    pool, seen = [], set()
    for root in POOL_ROOTS:
        for sol_path in sorted((REPO / root).rglob("best_solution.json")):
            key = str(sol_path)
            if key in seen:
                continue
            seen.add(key)
            s = read_solution(sol_path.parent)
            if s is None:
                continue
            if s["calendar"] == BASE_CAL:
                own = elec_cost(s["sessions"], cal_base)
                assert abs(own - s["cost_elec"]) <= 1e-9 * max(1.0, s["cost_elec"]), s["path"]
            pool.append(s)
    return pool


def observed_modes(dirpath: str) -> tuple[Counter, int, float, float]:
    cnt, totals = Counter(), []
    for sol_path in sorted((REPO / dirpath).rglob("best_solution.json")):
        s = read_solution(sol_path.parent)
        if s is None:
            continue
        cnt[(s["cv"], s["nev"])] += 1
        totals.append(s["total"])
    return cnt, len(totals), (min(totals) if totals else float("nan")), \
        (max(totals) if totals else float("nan"))


# --------------------------------------------------------------------------
# 图
# --------------------------------------------------------------------------
def _songti_regular(tmpdir: str) -> Path:
    from fontTools.ttLib import TTCollection
    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    target = Path(tmpdir) / "songti_sc_regular.ttf"
    for font in TTCollection(source).fonts:
        if "STSongti-SC-Regular" in {r.toUnicode() for r in font["name"].names
                                     if r.nameID == 6}:
            font.save(target)
            return target
    raise RuntimeError("Songti SC Regular face not found")


def draw_figure(tiers: dict, pool6_mid: list[dict], measured_rows: list[dict],
                out: Path, wide: bool) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.lines import Line2D

    tmp = tempfile.TemporaryDirectory(prefix="resetp_parity_font_")
    fp = _songti_regular(tmp.name)
    font_manager.fontManager.addfont(str(fp))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(fp)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    pt = 8.0

    items = list(tiers.values())
    ss = [i * S_MAX_FIG / 400.0 for i in range(401)]

    fig, ax = plt.subplots(figsize=((6.9, 2.6) if wide else (3.4, 2.6)))

    # 底图区域：北京现行日历下的 4.3 七档推导（固定 6 车），灰阶填充＋黑色边界
    tier_of = envelope_curves(items, "oc_full", ss, P_MAX_FIG)
    greys = {"4/2": "0.97", "3/3": "0.90", "2/4": "0.78", "1/5": "0.64", "0/6": "0.48"}
    labels_at: dict[str, tuple[float, float]] = {}
    for t, pts in tier_of.items():
        xs = [p[0] for p in pts]
        lo = [p[1] for p in pts]
        hi = [min(p[2], P_MAX_FIG) for p in pts]
        ax.fill_between(xs, lo, hi, facecolor=greys.get(t, "0.9"), edgecolor="none", zorder=0)
        ax.plot(xs, hi, color="black", lw=0.9, zorder=2)
        # 区域标签放在「带宽最大且离左右边界都不太近」的地方，免得贴到轴线上或压住实测点
        inner = [j for j, x in enumerate(xs)
                 if 0.10 * S_MAX_FIG <= x <= 0.86 * S_MAX_FIG]
        widths = [h - l for l, h in zip(lo, hi)]
        cand = inner or list(range(len(widths)))
        i = max(cand, key=lambda j: widths[j])
        if widths[i] > 0.14:
            labels_at[t] = (xs[i], (lo[i] + hi[i]) / 2.0)
    for t, (x, y) in labels_at.items():
        ax.text(x, min(y, P_MAX_FIG * 0.78), t, fontsize=pt, ha="center", va="center",
                zorder=4, bbox=dict(boxstyle="round,pad=0.14", fc="white",
                                    ec="none", alpha=0.85))

    # 叠加：午谷日历下**重优化方案池**（仅 6 车构型）的同一张区域图的边界，虚线。
    # 六个午谷实测点只跟这组虚线可比；底图那组实线是北京日历口径。
    for t, pts in envelope_curves(pool6_mid, "oc_full", ss, P_MAX_FIG).items():
        xs = [p[0] for p in pts]
        hi = [min(p[2], P_MAX_FIG) for p in pts]
        if max(hi) >= P_MAX_FIG - 1e-9 and min(hi) >= P_MAX_FIG - 1e-9:
            continue
        ax.plot(xs, hi, color="black", lw=0.8, ls=(0, (3.5, 2)), zorder=3)

    for row in measured_rows:
        filled = row["calendar"] == "beijing"
        ax.plot(row["s"], row["P"], marker="o" if filled else "s",
                ms=4.0, mfc="black" if filled else "white",
                mec="black", mew=0.8, ls="none", zorder=5)
        # 标注＝该点 3 或 10 次运算的**众数构型**；靠右边界的点把标签放到左侧
        right = row["s"] > 0.80 * S_MAX_FIG
        ax.annotate(row["obs_mode"], (row["s"], row["P"]),
                    textcoords="offset points",
                    xytext=(-6 if right else 5.5, 2.5),
                    ha="right" if right else "left",
                    fontsize=pt - 1.5, zorder=6,
                    bbox=dict(boxstyle="square,pad=0.08", fc="white",
                              ec="none", alpha=0.7))

    ax.set_xlim(0, S_MAX_FIG)
    ax.set_ylim(0, P_MAX_FIG)
    ax.set_xlabel("每车每日购置补贴 $s$（元）", fontsize=pt)
    ax.set_ylabel("碳价 $P$（元/kg）", fontsize=pt)
    ax.tick_params(labelsize=pt - 0.5, length=2.5, width=0.6)
    for sp in ax.spines.values():
        sp.set_linewidth(0.6)
    handles = [
        Line2D([], [], color="black", lw=0.9, label="北京日历"),
        Line2D([], [], color="black", lw=0.8, ls=(0, (3.5, 2)), label="午谷日历"),
        Line2D([], [], marker="o", color="black", ls="none", ms=4.0, label="实测·北京"),
        Line2D([], [], marker="s", mfc="white", mec="black", color="black",
               ls="none", ms=4.0, label="实测·午谷"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=pt - 2.0, frameon=True,
              facecolor="white", edgecolor="black", framealpha=1.0, ncol=2,
              handlelength=1.3, labelspacing=0.22, columnspacing=0.9, borderpad=0.3,
              handletextpad=0.4)
    fig.tight_layout(pad=0.35)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    fig.savefig(out.with_suffix(".png"), dpi=200)
    print(f"[图] {out.relative_to(REPO)}（{'6.9' if wide else '3.4'}×2.6 英寸）", file=sys.stderr)


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-figure", action="store_true")
    ap.add_argument("--wide", action="store_true")
    args = ap.parse_args()

    cal_base, fp_base = read_calendar(BASE_CAL)
    cal_mid, fp_mid = read_calendar(MID_CAL)
    assert fp_base == fp_mid, "两份日历的碳强度整列不同，E_total 不能跨日历沿用"
    print(f"[自检] 两份日历碳强度整列 sha256 相同（{fp_base[:16]}…），E_total 与电价情形无关",
          file=sys.stderr)
    print(f"[日历] 北京谷段小时 {sorted(set(int(h) for h in valley_hours(cal_base)))}；"
          f"午谷 {sorted(set(int(h) for h in valley_hours(cal_mid)))}", file=sys.stderr)

    tiers = load_tiers(cal_base, cal_mid)
    print(f"[自检] 七档共 {sum(t['n_runs_tier'] for t in tiers.values())} 个 run 全部通过："
          f"算例、COMPLETE、可行、无违约、50/50 客户、五项加总、"
          f"cost_fix==170×车数+100×电动车、cost_carbon==0.2×E、自有日历电费复算 ≤1e-9",
          file=sys.stderr)

    rows_tier = []
    for t in TIERS:
        x = tiers[t]
        rows_tier.append(dict(
            tier=t, cv=x["cv"], nev=x["nev"], src=x["src"],
            best_split=x["best_split"], n_runs_tier=x["n_runs_tier"],
            split_n=len(x["split_runs"]), split_range_cny=round(x["split_range"], 4),
            total_cost=round(x["total"], 4), cost_carbon=round(x["cost_carbon"], 4),
            cost_fix=round(x["cost_fix"], 4), cost_km=round(x["cost_km"], 4),
            cost_fuel=round(x["cost_fuel"], 4),
            cost_elec_beijing=round(x["cost_elec"], 4),
            cost_elec_midday=round(x["elec_mid"], 4),
            d_elec_midday=round(x["elec_mid"] - x["cost_elec"], 4),
            n_sessions=len(x["sessions"]),
            oc_beijing=round(x["oc_full"], 4), oc_midday=round(x["oc_mid"], 4),
            E_total=round(x["E"], 4),
        ))

    # 平价碳价
    pool = load_pool(cal_base)
    pool_mid = [x for x in pool if x["calendar"] == MID_CAL]
    pool_bj = [x for x in pool if x["calendar"] == BASE_CAL]
    print(f"[池] 重优化方案池 {len(pool)} 份：午谷 {len(pool_mid)}、北京 {len(pool_bj)}、"
          f"其余日历 {len(pool) - len(pool_mid) - len(pool_bj)}", file=sys.stderr)

    rows_par = []
    for a, b in zip(TIERS, TIERS[1:]):
        for s in SUBSIDIES:
            dC, dE, p = pstar(tiers[a], tiers[b], "oc_full", s)
            # 噪声区间：胜出分法各 3 个 run 的 3×3 组合
            combos = []
            for xa in tiers[a]["split_runs"]:
                for xb in tiers[b]["split_runs"]:
                    dc = (xb["oc_full"] - s * xb["nev"]) - (xa["oc_full"] - s * xa["nev"])
                    de = xa["E"] - xb["E"]
                    combos.append(dc / de if abs(de) > 1e-9 else float("nan"))
            dCm, dEm, pm = pstar(tiers[a], tiers[b], "oc_mid", s)
            rows_par.append(dict(
                transition=f"{a}→{b}", subsidy_cny=s,
                dC_beijing=round(dC, 4), dE_kg=round(dE, 4), pstar_beijing=round(p, 4),
                pstar_beijing_lo=round(min(combos), 4), pstar_beijing_hi=round(max(combos), 4),
                dC_midday_repriced=round(dCm, 4), pstar_midday_repriced=round(pm, 4),
            ))

    # 下包络分段
    rows_env = []
    for key, cal_tag, items, scope in (("oc_full", "beijing", list(tiers.values()), "表4.3七档(固定6车)"),
                                       ("oc_mid", "midday_repriced", list(tiers.values()), "表4.3七档重新计价(固定6车)"),
                                       ("oc_full", "midday_pool6", [x for x in pool_mid if x["veh"] == 6], "午谷重优化池(仅6车)"),
                                       ("oc_full", "midday_pool_all", pool_mid, "午谷重优化池(全部)"),
                                       ("oc_full", "beijing_pool6", [x for x in pool_bj if x["veh"] == 6], "北京重优化池(仅6车)"),
                                       ("oc_full", "beijing_pool_all", pool_bj, "北京重优化池(全部)")):
        if not items:
            continue
        for s in SUBSIDIES:
            for sg in envelope(items, key, s, P_MAX_FIG):
                it = sg["item"]
                mid = (sg["p_lo"] + min(sg["p_hi"], P_MAX_FIG)) / 2.0
                top = cheapest_config(items, key, s, mid)
                gap = (top[1][1] - top[0][1]) if len(top) > 1 else float("nan")
                rows_env.append(dict(
                    scope=scope, calendar=cal_tag, subsidy_cny=s,
                    p_lo=round(sg["p_lo"], 4), p_hi=round(sg["p_hi"], 4),
                    config=f'{it["cv"]}/{it["nev"]}', n_veh=it["veh"],
                    cost_at_p_lo=round(sg["cost_lo"], 4), cost_at_p_hi=round(sg["cost_hi"], 4),
                    # 段中点处「领先者比第二名便宜多少」——这是判断该区域抗不抗跑间噪声的量
                    p_mid=round(mid, 4), leader_margin_at_mid_cny=round(gap, 4),
                    E_total=round(it["E"], 4), src=it.get("src", it["path"]),
                ))

    # 每个构型在补贴轴上「什么时候进入 / 退出最优区域」，以及它最宽时的区域宽度
    s_grid = [i * S_MAX_FIG / 500.0 for i in range(501)]
    rows_life = []
    for tag, key, items in (("表4.3七档(固定6车)", "oc_full", list(tiers.values())),
                            ("午谷重优化池(仅6车)", "oc_full",
                             [x for x in pool_mid if x["veh"] == 6])):
        curves = envelope_curves(items, key, s_grid, P_MAX_FIG)
        for t, pts in sorted(curves.items(), key=lambda kv: -max(p[1] for p in kv[1])):
            widths = [(min(hi, P_MAX_FIG) - lo, s) for s, lo, hi in pts]
            wmax, s_at = max(widths)
            top = cheapest_config(items, key, s_at, next(
                (lo + min(hi, P_MAX_FIG)) / 2 for s, lo, hi in pts if s == s_at))
            rows_life.append(dict(
                scope=tag, config=t,
                s_first_cny=round(min(p[0] for p in pts), 3),
                s_last_cny=round(max(p[0] for p in pts), 3),
                widest_band_cny_per_kg=round(wmax, 4), at_subsidy_cny=round(s_at, 3),
                leader_margin_at_that_mid_cny=(round(top[1][1] - top[0][1], 3)
                                               if len(top) > 1 else ""),
            ))

    # 方案池按构型
    rows_pool = []
    for tag, items in (("midday", pool_mid), ("beijing", pool_bj)):
        for cfg, best, n, src, gap in cheapest_config(items, "oc_full", 0.0, 0.0):
            sub = [x for x in items if (x["cv"], x["nev"]) == cfg]
            rows_pool.append(dict(
                calendar=tag, config=f"{cfg[0]}/{cfg[1]}", n_veh=cfg[0] + cfg[1],
                n_solutions=n, min_operating_cny=round(best, 4),
                second_minus_min_cny=(round(gap, 4) if gap == gap else ""),
                E_min_kg=round(min(x["E"] for x in sub), 4),
                E_max_kg=round(max(x["E"] for x in sub), 4), src=src,
            ))

    # 实测点核对
    rows_meas = []
    for s, P, cal_tag, d in MEASURED:
        cnt, n, tmin, tmax = observed_modes(d)
        mode = max(cnt.items(), key=lambda kv: kv[1])[0] if cnt else (None, None)
        der_bj = envelope(list(tiers.values()), "oc_full", s, P_MAX_FIG)
        der_mid = envelope(list(tiers.values()), "oc_mid", s, P_MAX_FIG)
        pool_items = [x for x in (pool_mid if cal_tag == "midday" else pool_bj)]

        def at(segs, P_):
            for sg in segs:
                if sg["p_lo"] - 1e-9 <= P_ <= sg["p_hi"] + 1e-9:
                    it = sg["item"]
                    return f'{it["cv"]}/{it["nev"]}'
            return "?"

        pool6 = [x for x in pool_items if x["veh"] == 6]
        top_all = cheapest_config(pool_items, "oc_full", s, P)
        top6 = cheapest_config(pool6, "oc_full", s, P) if pool6 else []
        rows_meas.append(dict(
            subsidy_cny=s, carbon_price=P, calendar=cal_tag, run_dir=d, n_runs=n,
            observed_modes="; ".join(f"{a}/{b}×{c}" for (a, b), c in
                                     sorted(cnt.items(), key=lambda kv: -kv[1])),
            observed_mode=f"{mode[0]}/{mode[1]}" if mode[0] is not None else "",
            observed_total_min=round(tmin, 2), observed_total_max=round(tmax, 2),
            derived_tier_beijing=at(der_bj, P),
            derived_tier_midday_repriced=at(der_mid, P),
            derived_pool_6veh=(f"{top6[0][0][0]}/{top6[0][0][1]}" if top6 else ""),
            derived_pool_all=(f"{top_all[0][0][0]}/{top_all[0][0][1]}" if top_all else ""),
            pool_all_gap_to_second=(round(top_all[1][1] - top_all[0][1], 2)
                                    if len(top_all) > 1 else ""),
        ))
        rows_meas[-1]["obs_mode_short"] = rows_meas[-1]["observed_mode"]

    # ---- 打印 ----
    def show(title, rows, cols):
        print(f"\n## {title}", file=sys.stderr)
        w = [max(len(str(c)), max((len(str(r[c])) for r in rows), default=0)) for c in cols]
        print("  " + "  ".join(str(c).rjust(x) for c, x in zip(cols, w)), file=sys.stderr)
        for r in rows:
            print("  " + "  ".join(str(r[c]).rjust(x) for c, x in zip(cols, w)), file=sys.stderr)

    show("七档代表解", rows_tier,
         ["tier", "src", "split_range_cny", "total_cost", "cost_elec_beijing",
          "cost_elec_midday", "d_elec_midday", "oc_beijing", "oc_midday", "E_total"])
    show("平价碳价 P*", rows_par,
         ["transition", "subsidy_cny", "dC_beijing", "dE_kg", "pstar_beijing",
          "pstar_beijing_lo", "pstar_beijing_hi", "pstar_midday_repriced"])
    show("下包络分段", rows_env,
         ["scope", "subsidy_cny", "p_lo", "p_hi", "config", "n_veh",
          "leader_margin_at_mid_cny", "E_total"])
    show("各构型在补贴轴上的存活区间", rows_life,
         ["scope", "config", "s_first_cny", "s_last_cny", "widest_band_cny_per_kg",
          "at_subsidy_cny", "leader_margin_at_that_mid_cny"])
    show("方案池按构型", rows_pool,
         ["calendar", "config", "n_veh", "n_solutions", "min_operating_cny",
          "second_minus_min_cny", "E_min_kg", "E_max_kg"])
    show("实测点核对", rows_meas,
         ["subsidy_cny", "carbon_price", "calendar", "n_runs", "observed_modes",
          "derived_tier_beijing", "derived_tier_midday_repriced",
          "derived_pool_6veh", "derived_pool_all", "pool_all_gap_to_second"])
    print("\n[对照] 碳价扫描 summary.md 已登记的下包络翻转：", file=sys.stderr)
    for k, v in SWEEP_FLIPS.items():
        print(f"  {k}  {v}", file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] 不落盘", file=sys.stderr)
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in (("tier_costs.csv", rows_tier), ("parity_prices.csv", rows_par),
                       ("envelope_regions.csv", rows_env), ("region_lifetimes.csv", rows_life),
                       ("pool_configs.csv", rows_pool),
                       ("measured_points.csv", rows_meas)):
        path = OUT_DIR / name
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"[写] {path.relative_to(REPO)}（{len(rows)} 行）", file=sys.stderr)

    if not args.no_figure:
        pts = [dict(s=r["subsidy_cny"], P=r["carbon_price"], calendar=r["calendar"],
                    obs_mode=r["observed_mode"]) for r in rows_meas]
        draw_figure(tiers, [x for x in pool_mid if x["veh"] == 6], pts, FIG_OUT, args.wide)


if __name__ == "__main__":
    main()
