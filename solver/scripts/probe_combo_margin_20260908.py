#!/usr/bin/env python3
"""方案池离线重新核算：找"干净车队相对脏车队成本优势明显超过跑间噪声"的政策情形（2026-09-08）。

## 为什么做这件事

论文 4.4.3 政策对比表里，"充换电设施午间谷段＋购置补贴 24 元/日（碳价 0.2）"是唯一同时
降本减排的一行，但 `docs/handoff/midday_subsidy_shrinkage_20260908.md` 查明：这一行把车队
钉在成本平价点上——1 燃油 5 电动与 2 燃油 3 电动两种构型总成本只差 22.9 元（约 0.9%），
算法落哪边看运气，碳排量却相差 75.6 kg。本脚本**不跑求解器**，只把仓库里已落盘的全部
方案当成一个池子，在若干候选政策情形下重新核算每个方案的总成本与碳排量，按车队构型分组
取每组最低，看哪些情形能把"干净构型比脏构型便宜"的幅度拉到明显超过跑间噪声
（同配置总成本 sd 约 10 元、极差约 30 元；判据 ≥ 40 元）。

## 重算模型（只重算价，不动路线与充电时刻）

对池内每个方案，读 `evaluation.breakdown` 与 `individual.duties[].charging_sessions`，
在目标情形（电价日历 / 碳价 P / 每车每日购置补贴 s / 碳配额 Q）下重算：

    cost_elec  = Σ_会话 按半小时槽分摊电量 × 该槽电价
                 （场站节点 `D_*` 用 depot_energy_cny_per_kwh，公共站 `S_*` 用
                  public_total_cny_per_kwh；分摊法逐字照抄
                  `solver/scripts/build_charging_windows_table.py` 的 session_emission）
    cost_fix   = 170 × (n_veh_cv + n_veh_ev) + n_veh_ev × (100 − s)
                 （170 元/车/日的基础固定成本与 100 元/车/日的电动车溢价由池内全部方案
                  实测反推并逐份断言，不是外部假设）
    cost_carbon= (E_total − Q) × P          （**不截断**，Q > E_total 时为负，即碳信用；
                                              由 quota200 三份产物实测确认）
    total_cost = cost_fix + cost_km + cost_fuel + cost_elec + cost_carbon

`cost_km` / `cost_fuel` / `E_total` 与情形无关（本脚本用到的全部候选日历只改电价列，
碳强度列逐位不动——脚本对此有断言），所以只有电费、固定成本、碳成本三项要重算。

**近似方向（重要）**：路线与充电时刻保持不动，等于给每种车队构型一个"已知可行解"的
成本，因此每格数字是该构型真实最优成本的**上界**，不是下界。两个构型的差值是两个上界
之差，符号没有数学保证。CSV 里为此给出每个构型的方案数与"最低—次低"间距：只有一两个
方案撑着的构型，其上界很松，据此下的结论脆弱。

## 池子与排除

数据源四个批次（`solver/reports/` 下）：`grid2x2_v3_20260906`、
`carbon_price_sweep_v3_20260906`、`policy_combos_20260907`、`charging_arrangements_20260906`，
共 207 份 `best_solution.json`。排除两类：

- **21 份 `route_engine_wiring.first_trip_window` 缺失的**（`carbon_price_sweep_v3` 下
  P=0.07502/0.1/0.2/0.3/0.4/0.5/0.6 七档，是指向 v2 旧批的符号链接）：旧首趟前补电口径，
  首趟前补电起点可写死 00:00 白捡谷价，与其余方案不同口径；
- **3 份 `midday_subsidy_lunch1114`**：算例是 `…-LUNCH1114`（午休后移版），不是同一算例。

余下 183 份进池。

## 用法（仓库根目录，只读）

    export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
    .public-hgs-venv/bin/python3 solver/scripts/probe_combo_margin_20260908.py

输出 `solver/reports/probe_combo_margin_20260908/margin_table.csv`（每情形一行）与
`.../config_detail.csv`（每情形 × 每车队构型一行），并把校准与自检结果打到 stderr。
`--dry-run` 只打印不落盘。本脚本**只读**：不改代码、不改论文、不跑求解器。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "solver/reports/probe_combo_margin_20260908"

POOL_ROOTS = [
    "solver/reports/grid2x2_v3_20260906",
    "solver/reports/carbon_price_sweep_v3_20260906",
    "solver/reports/policy_combos_20260907",
    "solver/reports/charging_arrangements_20260906",
]
KEEP_INSTANCE = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
SERVED_CUSTOMERS = 50   # 每份方案都逐份断言：可行、无违约、无未服务客户、50/50 客户全服务

CAL_DIR = REPO / "data/ChinaInstances"
BASE_CAL = "china81_runtime_parameter_authority_v4_20260723"
MIDDAY_CAL = "china81_cf_calendar_midday_valley_v1_20260904"
DISCOUNT_CAL = "china81_cf_calendar_midday_discount_v1_20260904"
# 池内方案还用到这两份（只把公共站服务费置 0）；本脚本不拿它们当候选情形，
# 只为"用方案自己的日历复算电费必须逐位对上"这道自检而读入。
NOFEE_CALS = ("china81_cf_calendar_beijing_nofee_v1_20260907",
              "china81_cf_calendar_midday_nofee_v1_20260907")

CITY = "beijing"
DATE = "2025-02-12"           # China81 的正式日期；脚本断言 28 个日期的日内曲线逐位相同
DAY, SLOT = 86400.0, 1800.0

FIX_BASE_PER_VEH = 170.0      # 由池内全部方案反推并逐份断言
EV_FULL_PREMIUM = 100.0       # 未补贴时的电动车日溢价，同上

# 北京三档电价（元/kWh），取自现行日历；公共站总价 = 电量价 + 0.4 服务费
P_VALLEY, P_FLAT, P_PEAK = 0.56328575, 0.83644275, 1.14862175
SERVICE_FEE = 0.4

# 跑间噪声判据（来自 midday_subsidy 10 次：总成本 sd 9.75、极差约 30 元）
MARGIN_BAR = 40.0

# 论文表 13 现登记的基准行（10 次均值口径），只作连续性参照，不作判据分母
PAPER_BASELINE_COST, PAPER_BASELINE_E = 2634.90, 194.96


# --------------------------------------------------------------------------
# 日历
# --------------------------------------------------------------------------
def read_calendar(name: str) -> tuple[dict, str]:
    """读一份日历目录，返回 ({minute_of_day: (depot_price, public_total)}, 碳强度列指纹)。

    实测：本仓库全部日历里 city=beijing 的**电价**在 28 个日期上逐位相同（脚本断言），
    所以给 charge_day_offset=-1 的会话用同一条日内电价曲线计价不会引入误差；
    **碳强度**逐日不同（27/28 个日期与 2025-02-12 不同），但本脚本的全部候选情形都不改
    碳强度，E_total 直接沿用方案自己落盘的值，因此这里只把整列碳强度做成指纹供跨日历比对。
    """
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
        assert prof == ref, f"{name}: {d} 的日内电价曲线与 {DATE} 不同，不能用单日曲线计价"
    assert len(ref) == 48, f"{name}: 半小时槽数 {len(ref)} != 48"
    return ref, hashlib.sha256("\n".join(carbon_col).encode()).hexdigest()


def build_province_calendar(open_h: float, close_h: float, base: dict) -> dict:
    """按 `docs/handoff/valley_window_sweep_20260905.md` §二 的确定性摆法，
    用北京自己的三档价重排出一份"午间谷段 = [open_h, close_h)"的日历。

    规则（该文档明说是调查者定的假设，不是省级文件内容）：
      谷 = 午间窗口 ∪ 夜谷 [01:00, 01:00 + (8h − 午间时长))；
      峰 = 傍晚块 [max(17:00, 午间关门), +6h]（封顶 23:00）+ 上午块承接剩余峰时，
           能从 10:00 起就从 10:00 起，否则贴着午间谷段开门时刻往前放；
      平 = 其余，断言恰好 8 h。
    三档各断言 16 个半小时槽。碳强度列照抄 base（候选情形只改电价，不改碳强度）。
    """
    def slots(a_h: float, b_h: float) -> set[int]:
        return {int(m) for m in range(int(a_h * 60), int(b_h * 60), 30)}

    mid_len = close_h - open_h
    valley = slots(open_h, close_h) | slots(1.0, 1.0 + max(0.0, 8.0 - mid_len))
    even_start = max(17.0, close_h)
    evening = slots(even_start, min(even_start + 6.0, 23.0))
    need = 16 - len(evening)
    morning_start = 10.0 if (10.0 + need / 2.0) <= open_h else open_h - need / 2.0
    peak = evening | slots(morning_start, morning_start + need / 2.0)
    assert not (valley & peak), "峰谷重叠，摆法规则不适用于该窗口"
    assert len(valley) == 16 and len(peak) == 16, (len(valley), len(peak))
    out = {}
    for m in base:
        p = P_VALLEY if m in valley else (P_PEAK if m in peak else P_FLAT)
        out[m] = (p, p + SERVICE_FEE)
    flat_n = sum(1 for m in out if m not in valley and m not in peak)
    assert flat_n == 16, flat_n
    return out


# --------------------------------------------------------------------------
# 池子
# --------------------------------------------------------------------------
def load_pool() -> tuple[list[dict], list[tuple[str, str]]]:
    pool, dropped = [], []
    for root in POOL_ROOTS:
        for sol_path in sorted((REPO / root).rglob("best_solution.json")):
            meta = json.loads((sol_path.parent / "metadata.json").read_text(encoding="utf-8"))
            rel = str(sol_path.relative_to(REPO))
            if meta.get("instance_id") != KEEP_INSTANCE:
                dropped.append((rel, f"算例 {meta.get('instance_id')} 不是 {KEEP_INSTANCE}"))
                continue
            if (meta.get("route_engine_wiring") or {}).get("first_trip_window") != "prev_return":
                dropped.append((rel, "first_trip_window 缺失或非 prev_return（旧首趟补电口径）"))
                continue
            assert meta.get("status") == "COMPLETE", rel
            sol = json.loads(sol_path.read_text(encoding="utf-8"))
            assert sol["evaluation"]["feasible"] and not sol["evaluation"]["violations"], rel
            assert not sol["individual"]["unserved_customers"], rel
            served = {n for r in sol["evaluation"]["prepared_solution"]["routes"]
                      for n in r["node_sequence"] if n.startswith("C")}
            assert len(served) == SERVED_CUSTOMERS, (rel, len(served))
            bd = sol["evaluation"]["breakdown"]
            sessions = [
                (c["charge_start_second"] + c["charge_day_offset"] * DAY,
                 c["occupancy_minutes"], c["energy_kwh"], c["station_id"])
                for duty in sol["individual"]["duties"] for c in duty["charging_sessions"]
            ]
            for _, _, _, sid in sessions:
                assert str(sid)[:2] in ("D_", "S_"), f"{rel}: 未知节点前缀 {sid}"
            pool.append(dict(
                path=rel,
                cal=Path(json.dumps(meta.get("bundle_source_paths"))).name,  # 仅占位，下面覆盖
                calendar=_calendar_of(meta),
                run_P=float(meta["carbon_price_cny_per_kg"]),
                run_s=EV_FULL_PREMIUM - float(meta["effective_ev_daily_premium_cny"]),
                run_Q=float(meta["effective_carbon_quota_kg"]),
                policy=(meta.get("mechanism_closure") or {}).get("effective_charge_timing_policy"),
                cv=int(bd["n_veh_cv"]), ev=int(bd["n_veh_ev"]),
                cost_fix=float(bd["cost_fix"]), cost_km=float(bd["cost_km"]),
                cost_fuel=float(bd["cost_fuel"]), cost_elec=float(bd["cost_elec"]),
                cost_carbon=float(bd["cost_carbon"]), total=float(bd["total_cost"]),
                E=float(bd["E_total"]), sessions=sessions,
            ))
    return pool, dropped


def _calendar_of(meta: dict) -> str:
    for v in json.dumps(meta.get("bundle_source_paths")).split('"'):
        if "calendar" in v and v.endswith(".csv"):
            return Path(v).parent.name
    raise KeyError("metadata 里找不到 tariff 日历路径")


# --------------------------------------------------------------------------
# 重算
# --------------------------------------------------------------------------
def slot_of(second: float) -> int:
    return int((second % DAY) // 60 // 30) * 30


def session_cost(start: float, minutes: float, kwh: float, price: dict) -> float:
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


def elec_cost(sol: dict, cal: dict) -> float:
    depot = {m: v[0] for m, v in cal.items()}
    public = {m: v[1] for m, v in cal.items()}
    return math.fsum(
        session_cost(st, mn, kwh, depot if str(sid)[:2] == "D_" else public)
        for st, mn, kwh, sid in sol["sessions"]
    )


def recompute(sol: dict, cal: dict, P: float, s: float, Q: float) -> dict:
    ce = elec_cost(sol, cal)
    cf = FIX_BASE_PER_VEH * (sol["cv"] + sol["ev"]) + sol["ev"] * (EV_FULL_PREMIUM - s)
    cc = (sol["E"] - Q) * P
    operating = cf + sol["cost_km"] + sol["cost_fuel"] + ce
    return dict(total=operating + cc, operating=operating, carbon_payment=cc, E=sol["E"])


# --------------------------------------------------------------------------
# 自检
# --------------------------------------------------------------------------
def self_checks(pool: list[dict], cals: dict, prints: dict) -> None:
    for s in pool:
        five = s["cost_fix"] + s["cost_km"] + s["cost_fuel"] + s["cost_elec"] + s["cost_carbon"]
        assert abs(five - s["total"]) < 1e-6, (s["path"], five, s["total"])
        cf = FIX_BASE_PER_VEH * (s["cv"] + s["ev"]) + s["ev"] * (EV_FULL_PREMIUM - s["run_s"])
        assert abs(cf - s["cost_fix"]) < 1e-9, (s["path"], cf, s["cost_fix"])
        cc = (s["E"] - s["run_Q"]) * s["run_P"]
        assert abs(cc - s["cost_carbon"]) < 1e-6, (s["path"], cc, s["cost_carbon"])
        own = elec_cost(s, cals[s["calendar"]])
        assert abs(own - s["cost_elec"]) <= 1e-9 * max(1.0, s["cost_elec"]), \
            (s["path"], own, s["cost_elec"])
    ref = prints[BASE_CAL]
    for name, fp in prints.items():
        assert fp == ref, f"{name}: 碳强度列与基准日历不同（指纹 {fp[:12]} vs {ref[:12]}）"
    print(f"[自检] {len(pool)} 份方案：五项加总、固定成本公式、碳成本公式、"
          f"自有日历电费复算 全部通过；{len(prints)} 份日历的碳强度整列 sha256 相同"
          f"（{ref[:16]}…），故 E_total 与情形无关", file=sys.stderr)


# --------------------------------------------------------------------------
# 情形评估
# --------------------------------------------------------------------------
CLEAN_MAX_CV = 1   # 干净组＝燃油车 ≤1 辆（0油6电、1油5电…），脏组＝燃油车 ≥2 辆


def evaluate(pool: list[dict], cal: dict, P: float, s: float, Q: float) -> dict:
    """按车队构型分组重算，并把构型切成"干净组"（燃油车 ≤1）与"脏组"（燃油车 ≥2）。

    切分按**燃油车数量**这个结构量，不按算出来的碳排量，免得用结论去定分组。
    两组的碳排量**大体分开但并非绝无重叠**：干净组 61.9–136.5 kg、脏组 135.0–235 kg，
    1油4电（136.52 kg）与 2油4电（135.01 kg）这一对是唯一交叉处。所以每行都同时给出
    两组各自的碳排量，读者可以自己看这一次的"优势"到底买到了多少减排。

    干净对脏成本优势 = 脏组最低总成本 − 干净组最低总成本。为正表示"最便宜的干净车队
    比最便宜的脏车队还便宜"，即企业按成本最小化自己就会选干净车队；为负表示干净车队
    仍然更贵，政策没把车队推过去。
    """
    by_cfg: dict[tuple[int, int], list[tuple[float, dict, dict]]] = {}
    for sol in pool:
        r = recompute(sol, cal, P, s, Q)
        by_cfg.setdefault((sol["cv"], sol["ev"]), []).append((r["total"], r, sol))
    cfgs = {}
    for key, items in by_cfg.items():
        items.sort(key=lambda x: x[0])
        cfgs[key] = dict(
            n=len(items), best=items[0][0], second=(items[1][0] if len(items) > 1 else None),
            r=items[0][1], src=items[0][2]["path"],
        )
    order = sorted(cfgs.items(), key=lambda kv: kv[1]["best"])

    def group_best(pred):
        cand = [(k, v) for k, v in order if pred(k)]
        if not cand:
            return None, None
        return cand[0]

    clean_key, clean = group_best(lambda k: k[0] <= CLEAN_MAX_CV)
    dirty_key, dirty = group_best(lambda k: k[0] > CLEAN_MAX_CV)
    win_key, win = order[0]
    runner_key, runner = (order[1] if len(order) > 1 else (None, None))
    margin = (dirty["best"] - clean["best"]) if (clean and dirty) else float("nan")
    margin_op = ((dirty["r"]["operating"] - clean["r"]["operating"])
                 if (clean and dirty) else float("nan"))
    n_clean = sum(v["n"] for k, v in order if k[0] <= CLEAN_MAX_CV)
    n_dirty = sum(v["n"] for k, v in order if k[0] > CLEAN_MAX_CV)
    return dict(
        cfgs=cfgs, order=order,
        win_key=win_key, win=win, runner_key=runner_key, runner=runner,
        clean_key=clean_key, clean=clean, dirty_key=dirty_key, dirty=dirty,
        n_clean=n_clean, n_dirty=n_dirty,
        margin=margin, margin_op=margin_op,
        top2_gap=(runner["best"] - win["best"]) if runner else float("nan"),
    )


def fmt_cfg(k) -> str:
    return "-" if k is None else f"{k[0]}油{k[1]}电"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    _read = {n: read_calendar(n) for n in (BASE_CAL, MIDDAY_CAL, DISCOUNT_CAL, *NOFEE_CALS)}
    cals = {n: v[0] for n, v in _read.items()}
    prints = {n: v[1] for n, v in _read.items()}
    # 摆法规则自检：用 12–15 重建应与仓库里的午谷日历电价逐位相同
    rebuilt = build_province_calendar(12.0, 15.0, cals[BASE_CAL])
    assert all(abs(rebuilt[m][0] - cals[MIDDAY_CAL][m][0]) < 1e-12 and
               abs(rebuilt[m][1] - cals[MIDDAY_CAL][m][1]) < 1e-12 for m in rebuilt), \
        "摆法规则重建 12–15 与仓库午谷日历不符"
    print("[自检] 摆法规则重建「午间 12:00–15:00」与仓库 midday_valley 日历电价逐位相同",
          file=sys.stderr)

    prov = {
        "冀北/湖北/江西12-14": build_province_calendar(12.0, 14.0, cals[BASE_CAL]),
        "蒙西11-16": build_province_calendar(11.0, 16.0, cals[BASE_CAL]),
        "山东10-15": build_province_calendar(10.0, 15.0, cals[BASE_CAL]),
    }
    pool, dropped = load_pool()
    print(f"[池子] 进池 {len(pool)} 份；排除 {len(dropped)} 份", file=sys.stderr)
    for rel, why in dropped:
        print(f"        排除 {rel}：{why}", file=sys.stderr)
    self_checks(pool, cals, prints)

    # ---- 候选情形 ----
    M, B, D = cals[MIDDAY_CAL], cals[BASE_CAL], cals[DISCOUNT_CAL]
    S = []  # (键, 说明, 日历名, 日历, P, s, Q, 参数出处)
    S.append(("基准", "北京现行时段，碳价0.20，无补贴", "北京现行", B, 0.2, 0.0, 0.0,
              "论文表13基准行同参数；此处按本脚本同一池子口径重算，作为全部Δ的分母"))
    S.append(("现用组合", "午间谷段＋补贴24＋碳价0.20", "午谷12-15", M, 0.2, 24.0, 0.0,
              "河北南网 12:00–15:00（省发改委通知 2022-10-28）；补贴＝6.32万÷(8年×330日)=23.94≈24"))
    S.append(("a", "午间谷段＋补贴24＋碳价1.0", "午谷12-15", M, 1.0, 24.0, 0.0,
              "同上；碳价1.0 元/kg 为表13已列档位（grid2x2_v3 midday/P=1.0）"))
    S.append(("b", "午间谷段＋补贴24＋现行碳价0.075", "午谷12-15", M, 0.07502, 24.0, 0.0,
              "同上；0.07502 元/kg＝China81 常量 CHINA81_CARBON_PRICE_CNY_PER_KG（现行市场价）"))
    for nm, cal in prov.items():
        S.append((f"c:{nm}", f"{nm} 午间谷段＋补贴24＋碳价0.20", nm, cal, 0.2, 24.0, 0.0,
                  "valley_window_sweep_20260905.md §五 省级文件时段；摆法规则同 §二"))
    S.append(("d1", "午间谷段＋补贴23.94（8年×330日）＋碳价0.20", "午谷12-15", M, 0.2, 23.94, 0.0,
              "6.32万目录价差 ÷ 2640 日；instance_rebuild_literature_20260811.md §4"))
    S.append(("d2", "午间谷段＋补贴24.12（10年×262日）＋碳价0.20", "午谷12-15", M, 0.2, 24.12, 0.0,
              "6.32万 ÷ 2620 日；同上文献可核口径之一"))
    S.append(("d3", "午间谷段＋补贴8.66（20年×365日）＋碳价0.20", "午谷12-15", M, 0.2, 8.66, 0.0,
              "6.32万 ÷ 7300 日；同上文献可核口径之一"))
    S.append(("d4", "午间谷段＋补贴46.97（100kWh含一次换电池）＋碳价0.20", "午谷12-15", M, 0.2, 46.97, 0.0,
              "12.40万资本价差 ÷ 2640 日；改的是资本口径不是年限，同文献表内一行"))
    S.append(("d5", "午间谷段＋补贴49.24（200kWh仅初购）＋碳价0.20", "午谷12-15", M, 0.2, 49.24, 0.0,
              "13.00万 ÷ 2640 日；同文献明示 200kWh 车型与本算例 77.28kWh 不匹配"))
    S.append(("e", "午间谷段＋补贴24＋碳配额200＋碳价0.20", "午谷12-15", M, 0.2, 24.0, 200.0,
              "配额200 kg＝表13 碳配额与交易行档位；对照，预期只平移"))
    S.append(("f1", "午间充电按谷价补贴＋补贴24＋碳价0.20", "午间谷价补贴", D, 0.2, 24.0, 0.0,
              "midday_discount 日历＝表13「午间充电按谷价补贴」行（运营侧补贴）"))
    S.append(("g1", "午间谷段＋补贴46.97＋碳价1.0", "午谷12-15", M, 1.0, 46.97, 0.0,
              "a 与 d4 叠加"))
    S.append(("g2", "午间谷段＋补贴24＋碳价0.6", "午谷12-15", M, 0.6, 24.0, 0.0,
              "碳价 0.6 为扫描已跑档位"))
    S.append(("g3", "北京现行时段＋补贴24＋碳价1.0", "北京现行", B, 1.0, 24.0, 0.0,
              "隔离：只有补贴与碳价，不挪时段"))
    S.append(("R1", "北京现行时段＋无补贴＋碳价1.2（纯碳价参照）", "北京现行", B, 1.2, 0.0, 0.0,
              "参照：只抬碳价、不挪时段不给补贴，用来看组合里哪一件在起作用"))
    S.append(("R2", "北京现行时段＋无补贴＋碳价1.5（纯碳价参照）", "北京现行", B, 1.5, 0.0, 0.0,
              "参照，同上；碳价1.5 已是表13 一行"))
    S.append(("A2", "午间谷段＋补贴24＋碳价1.2", "午谷12-15", M, 1.2, 24.0, 0.0,
              "碳价 1.2 元/kg 是碳价扫描已跑档位（carbon_price_sweep_v3/P=1.2）"))
    S.append(("A3", "午间谷段＋补贴24＋碳价1.5", "午谷12-15", M, 1.5, 24.0, 0.0,
              "碳价 1.5 元/kg 已是表13 现有一行（碳价升至1.5）；三个参数全部已在论文里出现过"))
    S.append(("H1", "午间谷段＋补贴46.97＋碳价0.6", "午谷12-15", M, 0.6, 46.97, 0.0,
              "补贴见 d4 的资本口径；碳价 0.6 为扫描已跑档位"))
    S.append(("C4", "冀北/湖北/江西12-14＋补贴24＋碳价1.2", "冀北/湖北/江西12-14",
              prov["冀北/湖北/江西12-14"], 1.2, 24.0, 0.0,
              "省级时段见 valley_window_sweep_20260905.md §五；其余同 A2"))

    rows, detail = [], []
    base_res = None
    for key, desc, calname, cal, P, s, Q, prov_txt in S:
        res = evaluate(pool, cal, P, s, Q)
        if key == "基准":
            base_res = res
        win, clean, dirty, runner = res["win"], res["clean"], res["dirty"], res["runner"]
        rows.append(dict(
            情形=key, 说明=desc, 日历=calname, 碳价=P, 每车每日补贴=round(s, 2), 碳配额=Q,
            干净组最优构型=fmt_cfg(res["clean_key"]),
            干净组总成本=round(clean["r"]["total"], 2) if clean else "",
            干净组运营成本=round(clean["r"]["operating"], 2) if clean else "",
            干净组碳排=round(clean["r"]["E"], 2) if clean else "",
            脏组最优构型=fmt_cfg(res["dirty_key"]),
            脏组总成本=round(dirty["r"]["total"], 2) if dirty else "",
            脏组运营成本=round(dirty["r"]["operating"], 2) if dirty else "",
            脏组碳排=round(dirty["r"]["E"], 2) if dirty else "",
            干净对脏成本优势=round(res["margin"], 2),
            干净对脏运营成本优势=round(res["margin_op"], 2),
            达到40元判据=("是" if res["margin"] >= MARGIN_BAR else "否"),
            全局最优构型=fmt_cfg(res["win_key"]),
            全局最优总成本=round(win["r"]["total"], 2),
            全局最优碳排=round(win["r"]["E"], 2),
            次优构型=fmt_cfg(res["runner_key"]),
            前二名成本差=round(res["top2_gap"], 2),
            干净组方案数=res["n_clean"], 脏组方案数=res["n_dirty"],
            干净组最低次低间距=(round(clean["second"] - clean["best"], 2)
                              if clean and clean["second"] else ""),
            脏组最低次低间距=(round(dirty["second"] - dirty["best"], 2)
                            if dirty and dirty["second"] else ""),
            Δ干净组总成本对重算基准=round(clean["r"]["total"] - base_res["win"]["r"]["total"], 2),
            Δ干净组运营成本对重算基准运营=round(
                clean["r"]["operating"] - base_res["win"]["r"]["operating"], 2),
            Δ干净组碳排对重算基准=round(clean["r"]["E"] - base_res["win"]["r"]["E"], 2),
            Δ干净组总成本对表13基准=round(clean["r"]["total"] - PAPER_BASELINE_COST, 2),
            Δ干净组碳排对表13基准=round(clean["r"]["E"] - PAPER_BASELINE_E, 2),
            干净组每日财政补贴支出=round(s * res["clean_key"][1], 2) if clean else "",
            干净组每日碳费支付=round(clean["r"]["carbon_payment"], 2) if clean else "",
            干净组最优方案出处=clean["src"] if clean else "",
            脏组最优方案出处=dirty["src"] if dirty else "",
            参数出处=prov_txt,
        ))
        for k, v in res["order"]:
            detail.append(dict(
                情形=key, 构型=fmt_cfg(k), 燃油=k[0], 电动=k[1], 方案数=v["n"],
                最低总成本=round(v["best"], 2),
                次低总成本=round(v["second"], 2) if v["second"] else "",
                最低次低间距=round(v["second"] - v["best"], 2) if v["second"] else "",
                运营成本=round(v["r"]["operating"], 2),
                碳支付=round(v["r"]["carbon_payment"], 2),
                碳排=round(v["r"]["E"], 2), 出处=v["src"],
            ))

    # ---- 校准：现用组合只用它自己那 10 份产物 ----
    own = [s for s in pool if s["path"].startswith("solver/reports/policy_combos_20260907/midday_subsidy/")]
    own_res = evaluate(own, M, 0.2, 24.0, 0.0)
    print("\n[校准] 「午间谷段＋补贴24＋碳价0.20」只用它自己那 %d 份产物重算：" % len(own),
          file=sys.stderr)
    for k, v in own_res["order"]:
        print(f"        {fmt_cfg(k)}  n={v['n']}  最低总成本 {v['best']:.2f}  碳排 {v['r']['E']:.2f}",
              file=sys.stderr)
    print(f"        干净对脏成本优势 {own_res['margin']:+.2f} 元"
          f"（诊断报告按均值口径给的是 −22.9 元，同量级即通过）", file=sys.stderr)

    # ---- 碳价门槛扫描：补贴 24 与 46.97 两档下，干净对脏优势何时越过 40 元 ----
    print("\n[扫描] 干净对脏成本优势随碳价的变化（碳价门槛在哪里）：", file=sys.stderr)
    for calname, cal_, s_val in (("午谷12-15", M, 24.0), ("午谷12-15", M, 46.97),
                                 ("北京现行", B, 0.0)):
        hits = []
        for i in range(0, 61):
            P = round(i * 0.05, 4)
            r = evaluate(pool, cal_, P, s_val, 0.0)
            hits.append((P, r["margin"], r["clean"]["r"]["total"], r["clean"]["r"]["E"],
                         fmt_cfg(r["clean_key"])))
        first = next((h for h in hits if h[1] >= MARGIN_BAR), None)
        print(f"        {calname}＋补贴 {s_val} 元/日：越过 {MARGIN_BAR:.0f} 元的最低碳价 = "
              + (f"{first[0]:.2f} 元/kg（优势 {first[1]:.2f} 元，"
                 f"干净组最优 {first[4]} 总成本 {first[2]:.2f} 元 / {first[3]:.2f} kg）"
                 if first else "扫描区间 0–3.0 内没有"), file=sys.stderr)
        for P, m_, t, e, w in hits:
            if int(round(P * 20)) % 4 == 0:
                print(f"          P={P:.2f}  优势 {m_:+7.2f}  干净组最优 {w} {t:8.2f} 元 / {e:6.2f} kg",
                      file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] 不落盘", file=sys.stderr)
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with (OUT_DIR / "margin_table.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        with (OUT_DIR / "config_detail.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(detail[0].keys()))
            w.writeheader()
            w.writerows(detail)
        print(f"\n已写出 {OUT_DIR/'margin_table.csv'} 与 {OUT_DIR/'config_detail.csv'}",
              file=sys.stderr)

    hdr = ["情形", "干净组最优构型", "干净组总成本", "干净组运营成本", "干净组碳排",
           "脏组最优构型", "脏组总成本", "脏组碳排", "干净对脏成本优势", "达到40元判据",
           "Δ干净组总成本对重算基准", "Δ干净组运营成本对重算基准运营",
           "Δ干净组总成本对表13基准", "Δ干净组碳排对重算基准"]
    print("\n" + " | ".join(hdr))
    for r in rows:
        print(" | ".join(str(r[h]) for h in hdr))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
