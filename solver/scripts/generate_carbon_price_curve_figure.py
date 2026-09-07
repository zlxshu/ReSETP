#!/usr/bin/env python3
"""生成论文图「单位碳价—总成本/碳排量/电动车派遣量」曲线（figure_5_carbon_price_curve）。

回答的问题：把单位碳价从 0 拉到 2.0 元/kgCO2e、每一档都完整重搜路线与车队后，
总成本、碳排量与派遣电动车占比各自怎么随碳价变化，翻转点落在哪几档。

数据源
  solver/reports/carbon_price_sweep_v2_20260906/P=<价>/run_01..03/best_solution.json
  （批次 2026-09-06 起跑，等差 21 档 0.0--2.0 步长 0.1 + 现行价 0.07502 共 22 档 × 3 次；
  本脚本运行时批次可能仍未跑完，只用已落盘的 best_solution.json，缺档跳过、缺次数照实报）。
  每一份 best_solution.json 只读 evaluation.breakdown 的
  total_cost / E_total / n_veh_ev / n_veh_cv（字段名核对自
  solver/scripts/build_policy_table.py 的读法）。
  每一档（同一 P= 目录）若有多次 run，取 total_cost 最低的一次代表该档
  （与 solver/reports/carbon_price_sweep_v2_20260906/summarise.py 的 best-of-n 规则一致）。

画风（与 solver/scripts/generate_carbon_charging_figure.py / generate_carbon_price_sweep_figure.py
同一套常量）：纯黑白灰、无阴影、无竖标注；通栏宽版心 501.06 pt；宋体走中文，Times 走数字。

两格并排（--mode level / --mode envelope）：
  (a) 总成本与碳排量：横轴单位碳价，左轴总成本（元，黑实线＋实心圆），
      右轴碳排量（kgCO2e，黑虚线＋空心圆）；两项图例放格内空白处。
  (b) 派遣电动车占比：横轴单位碳价，纵轴派遣电动车占比（%，
      =n_veh_ev/(n_veh_ev+n_veh_cv)×100），黑色阶梯线
      （drawstyle=steps-post），纵轴刻度 0--100 每格 20。

单格（--mode bars，仿陈婉茹 2023 图4(a)）：
  横轴＝单位碳价 22 个档位（0.0、0.07502、0.1、0.2、…、2.0），等间距分类刻度
  （档与档之间的实际价差不等，画成等距分类轴避免 0.07502 与 0.1 两档在线性轴上叠在一起）；
  只标 0、0.5、1.0、1.5、2.0 与 0.075（现行碳价）五个刻度，其余留空。
  每一档取值＝方案池（load_solution_pool 的 66 个已落盘方案）在该档碳价下重算的最优
  （min_i 非碳成本+P×碳排量，与 --mode envelope 同一口径，只是只在 22 个档位价上取值、
  不铺 0.01 步长的细网格）：
    柱（左轴，0--100%）＝该档最优方案的派遣电动车占比；浅灰填充＋细黑边。
    折线＋实心圆点（右轴）＝该档最优方案在该档碳价下重算的总成本（元，非碳成本+P×碳排量）；
      黑线；右轴范围＝该 22 档总成本数据的最小/最大值各留 5% 余量，刻度取整百。
  图例两项（柱、线）放格内空白处，不压柱与点；不加竖线标注、不加阴影、不分小题。

用法（仓库根目录）：
    export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts'
    .public-hgs-venv/bin/python3 solver/scripts/generate_carbon_price_curve_figure.py --mode bars
"""

from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from fontTools.ttLib import TTCollection
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.transforms import Bbox

REPO = Path(__file__).resolve().parents[2]
# 2026-09-06 派工：方案池数据源改为 v3（B 口径，prev_return，15 档新跑 + 7 档指向
# v2 的符号链接，见 carbon_price_sweep_v3_20260906/README.md）。旧 v2 目录常量保留
# 仅供追溯，不再作为默认数据源。
# DEFAULT_SWEEP_DIR = REPO / "solver/reports/carbon_price_sweep_v2_20260906"
DEFAULT_SWEEP_DIR = REPO / "solver/reports/carbon_price_sweep_v3_20260906"
# 现用图（若已存在）受保护；默认输出新文件名，与已有 figure_5_carbon_price_sweep.pdf
# （另一批「密扫，路线不重搜」数据画的图）区分开，不覆盖它。
OUT = REPO / "docs/paper_v2/generated_figures/figure_5_carbon_price_curve.pdf"

CURRENT_PRICE = 0.07502  # 现行单位碳价（China81 常量 CHINA81_CARBON_PRICE_CNY_PER_KG）
X_MAX = 2.0
X_MIN = 0.0

COST_LABEL = "总成本（元）"
EMISSION_LABEL = "碳排量（kgCO$_2$e）"
PANEL_CAPTIONS = ("(a) 总成本与碳排量", "(b) 派遣电动车占比")

# ---- 画风常量：抄自 generate_carbon_charging_figure.py / generate_carbon_price_sweep_figure.py ----
TARGET_WIDTH_PT = 501.056875
PALETTE = {"ink": "#000000", "gray": "#666666", "light_gray": "#D9D9D9"}
AXIS_WIDTH_PT = 0.468
CURVE_WIDTH_PT = 0.62
TEXT_SIZE_PT = 8.0
LEGEND_SIZE_PT = 6.8
PANEL_SIZE_PT = 7.5
MARKER_SIZE_PT = 3.2

# ---- --mode bars 专用常量 ----
# 分类刻度只标这几个价位（现行价单独标 0.075，其余按 0.5 步长标一位小数）；
# 容差 1e-6 足够区分 0.07502 与旁边的 0.1（相差 0.02498，远大于容差）。
BAR_TICK_PRICES = (0.0, 0.5, 1.0, 1.5, 2.0)
BAR_FILL = "#D9D9D9"  # PALETTE["light_gray"]，浅灰填充
BAR_EDGE_WIDTH_PT = 0.35
BAR_WIDTH_FRAC = 0.62  # 柱宽占分类槽宽的比例

_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_carbon_price_curve_fig_font_")


def _songti_regular() -> Path:
    """取 Songti.ttc 中的常规字面；matplotlib 默认会选到 Black 字面。"""
    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    target = Path(_FONT_TMP.name) / "songti_sc_regular.ttf"
    for font in TTCollection(source).fonts:
        names = {r.toUnicode() for r in font["name"].names if r.nameID == 6}
        if "STSongti-SC-Regular" in names:
            font.save(target)
            return target
    raise RuntimeError("Songti SC Regular face not found in system Songti.ttc")


CN = font_manager.FontProperties(fname=_songti_regular(), size=TEXT_SIZE_PT)
CN_LEGEND = CN.copy()
CN_LEGEND.set_size(LEGEND_SIZE_PT)
CN_PANEL = CN.copy()
CN_PANEL.set_size(PANEL_SIZE_PT)

plt.rcParams.update(
    {
        "font.family": "Times New Roman",
        "font.size": TEXT_SIZE_PT,
        "axes.linewidth": AXIS_WIDTH_PT,
        "lines.linewidth": CURVE_WIDTH_PT,
        "xtick.major.width": AXIS_WIDTH_PT,
        "ytick.major.width": AXIS_WIDTH_PT,
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "savefig.dpi": 300,
    }
)

_PRICE_DIR_RE = re.compile(r"^P=([0-9.]+)$")
_REQUIRED_FIELDS = ("total_cost", "E_total", "n_veh_ev", "n_veh_cv")
_POOL_REQUIRED_FIELDS = (
    "total_cost", "cost_carbon", "E_total", "carbon_quota_kg", "n_veh_ev", "n_veh_cv",
)
ENVELOPE_STEP = 0.01


# --------------------------------------------------------------------------
# 取数
# --------------------------------------------------------------------------
def load_breakdown(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    bd = data["evaluation"]["breakdown"]
    missing = [k for k in _REQUIRED_FIELDS if k not in bd]
    if missing:
        raise KeyError(f"{path}: breakdown 缺字段 {missing}")
    return bd


def load_levels(sweep_dir: Path) -> list[dict]:
    """扫描 P=<价> 目录，每档取已落盘 run 中 total_cost 最低的一次。

    对没有任何 best_solution.json 的档位（还没跑完），跳过并打印提示，
    不编造数据、不用其它档位插值。
    """
    levels: list[dict] = []
    skipped: list[str] = []
    for price_dir in sorted(sweep_dir.iterdir()):
        if not price_dir.is_dir():
            continue
        m = _PRICE_DIR_RE.match(price_dir.name)
        if not m:
            continue
        price = float(m.group(1))
        run_dirs = sorted(
            d for d in price_dir.iterdir() if d.is_dir() and d.name.startswith("run_")
        )
        candidates = []
        for run_dir in run_dirs:
            best_path = run_dir / "best_solution.json"
            if not best_path.is_file():
                continue
            candidates.append((run_dir.name, load_breakdown(best_path)))
        if not candidates:
            skipped.append(price_dir.name)
            continue
        candidates.sort(key=lambda item: item[1]["total_cost"])
        best_run, best_bd = candidates[0]
        levels.append(
            {
                "price": price,
                "price_str": m.group(1),
                "n_runs_found": len(run_dirs),
                "n_runs_completed": len(candidates),
                "best_run": best_run,
                "total_cost": float(best_bd["total_cost"]),
                "E_total": float(best_bd["E_total"]),
                "n_veh_ev": int(best_bd["n_veh_ev"]),
                "n_veh_cv": int(best_bd["n_veh_cv"]),
            }
        )
    levels.sort(key=lambda lv: lv["price"])
    if skipped:
        print(f"跳过 {len(skipped)} 个尚无任何已完成 run 的档位：{'、'.join(skipped)}")
    return levels


def load_solution_pool(sweep_dir: Path) -> list[dict]:
    """扫描全部 P=<价>/run_*/best_solution.json，作为 --mode envelope 的方案池。

    每份方案只取 evaluation.breakdown 的 total_cost / cost_carbon / E_total /
    carbon_quota_kg / n_veh_ev / n_veh_cv，并核对恒等式
    cost_carbon == (E_total - carbon_quota_kg) × 目录标称碳价（容差 1e-6，
    与 summarise.py 的核验一致）；非碳成本 C = total_cost - cost_carbon。
    """
    pool: list[dict] = []
    mismatches: list[tuple[str, float, float]] = []
    for price_dir in sorted(sweep_dir.iterdir()):
        if not price_dir.is_dir():
            continue
        m = _PRICE_DIR_RE.match(price_dir.name)
        if not m:
            continue
        nominal_price = float(m.group(1))
        run_dirs = sorted(
            d for d in price_dir.iterdir() if d.is_dir() and d.name.startswith("run_")
        )
        for run_dir in run_dirs:
            best_path = run_dir / "best_solution.json"
            if not best_path.is_file():
                continue
            data = json.loads(best_path.read_text(encoding="utf-8"))
            bd = data["evaluation"]["breakdown"]
            missing = [k for k in _POOL_REQUIRED_FIELDS if k not in bd]
            if missing:
                raise KeyError(f"{best_path}: breakdown 缺字段 {missing}")
            quota = float(bd["carbon_quota_kg"])
            e_total = float(bd["E_total"])
            cost_carbon = float(bd["cost_carbon"])
            expect = (e_total - quota) * nominal_price
            if abs(expect - cost_carbon) > 1e-6:
                mismatches.append((str(best_path.relative_to(REPO)), expect, cost_carbon))
            pool.append(
                {
                    "path": str(best_path.relative_to(REPO)),
                    "nominal_price": nominal_price,
                    "non_carbon_cost": float(bd["total_cost"]) - cost_carbon,
                    "E_total": e_total,
                    "n_veh_ev": int(bd["n_veh_ev"]),
                    "n_veh_cv": int(bd["n_veh_cv"]),
                }
            )
    if mismatches:
        lines = "\n".join(f"  {p}：期望 {exp:.6f}，实读 {act:.6f}" for p, exp, act in mismatches)
        raise ValueError(f"cost_carbon 恒等式核验失败 {len(mismatches)} 处：\n{lines}")
    if not pool:
        raise SystemExit(f"{sweep_dir} 下没有任何 best_solution.json，方案池为空")
    return pool


def build_envelope(pool: list[dict], p_min: float, p_max: float, step: float):
    """在 [p_min, p_max] 步长 step 的细网格上，对方案池逐点取下包络 min_i(C_i + P·E_i)。

    返回 (grid_prices, envelope)：envelope[k] 是网格价 grid_prices[k] 处胜出的方案
    （沿用 pool 条目字段，外加该网格价下的总成本 cost_at_p）。
    """
    n_steps = round((p_max - p_min) / step)
    grid_prices = [round(p_min + i * step, 10) for i in range(n_steps + 1)]
    envelope = []
    for p in grid_prices:
        best = min(pool, key=lambda sol: sol["non_carbon_cost"] + p * sol["E_total"])
        envelope.append({**best, "cost_at_p": best["non_carbon_cost"] + p * best["E_total"]})
    return grid_prices, envelope


def _envelope_flip_price(prev: dict, cur: dict) -> float:
    """两段方案价格线 C+P·E 的解析交点（不受网格步长 0.01 限制的精确翻转碳价）。"""
    d_emission = prev["E_total"] - cur["E_total"]
    if d_emission == 0:
        return float("nan")
    return (cur["non_carbon_cost"] - prev["non_carbon_cost"]) / d_emission


# summary.md「全体 66 个方案的精确下包络」一节算出的翻转碳价，仅供本脚本核对用。
_SUMMARY_MD_EXPECTED_FLIPS = (1.3316, 1.7959)


def report_envelope(grid_prices: list[float], envelope: list[dict]) -> list[float]:
    step = grid_prices[1] - grid_prices[0]
    print(
        f"下包络网格：P∈[{grid_prices[0]:.2f},{grid_prices[-1]:.2f}]，"
        f"步长 {step:.3f}，共 {len(grid_prices)} 个网格点"
    )
    print("翻转碳价（下包络最优方案切换处，解析交点，不是网格坐标）：")
    flip_prices: list[float] = []
    flips = 0
    for (p_prev, prev), (p_cur, cur) in zip(
        zip(grid_prices, envelope), zip(grid_prices[1:], envelope[1:])
    ):
        if (cur["n_veh_ev"], cur["n_veh_cv"]) == (prev["n_veh_ev"], prev["n_veh_cv"]):
            continue
        flips += 1
        p_star = _envelope_flip_price(prev, cur)
        flip_prices.append(p_star)
        prev_share = 100.0 * prev["n_veh_ev"] / (prev["n_veh_ev"] + prev["n_veh_cv"])
        cur_share = 100.0 * cur["n_veh_ev"] / (cur["n_veh_ev"] + cur["n_veh_cv"])
        print(
            f"  网格 P≈{p_cur:.2f} 处检测到切换，解析翻转碳价 P*={p_star:.4f} 元/kg："
            f"(燃油{prev['n_veh_cv']},电{prev['n_veh_ev']}) → (燃油{cur['n_veh_cv']},电{cur['n_veh_ev']})，"
            f"电动车占比 {prev_share:.1f}% → {cur_share:.1f}%，"
            f"碳排量 {prev['E_total']:.2f} → {cur['E_total']:.2f} kgCO2e，"
            f"非碳成本 {prev['non_carbon_cost']:.2f} → {cur['non_carbon_cost']:.2f} 元"
            f"（方案出自 {prev['path']} → {cur['path']}）"
        )
    if flips == 0:
        print("  （网格内没有检测到切换）")
    print(f"合计切换 {flips} 次；解析翻转碳价：{['%.4f' % p for p in flip_prices]}")
    print(
        f"与 summarise.py/summary.md 的下包络分析核对（预期约 "
        f"{'、'.join(f'{p:.4f}' for p in _SUMMARY_MD_EXPECTED_FLIPS)}）：",
        end=" ",
    )
    if len(flip_prices) == len(_SUMMARY_MD_EXPECTED_FLIPS) and all(
        abs(a - b) < 0.01 for a, b in zip(flip_prices, _SUMMARY_MD_EXPECTED_FLIPS)
    ):
        print("一致")
    else:
        print("不一致，需人工核对")
    return flip_prices


def build_bar_levels(pool: list[dict]) -> list[dict]:
    """--mode bars 用：对方案池在「实际落盘的 22 个碳价档位」逐档取下包络最优。

    档位价直接取方案池里出现过的 nominal_price 去重集合（即 P=<价> 目录名），
    不铺 envelope 模式的 0.01 步长细网格；每档口径与 build_envelope 完全一致，
    只是求值点从细网格换成这 22 个真实档位。
    """
    prices = sorted({sol["nominal_price"] for sol in pool})
    levels = []
    for p in prices:
        best = min(pool, key=lambda sol: sol["non_carbon_cost"] + p * sol["E_total"])
        n_total = best["n_veh_ev"] + best["n_veh_cv"]
        levels.append(
            {
                "price": p,
                "cost_at_p": best["non_carbon_cost"] + p * best["E_total"],
                "E_total": best["E_total"],
                "n_veh_ev": best["n_veh_ev"],
                "n_veh_cv": best["n_veh_cv"],
                "ev_share": 100.0 * best["n_veh_ev"] / n_total,
                "path": best["path"],
            }
        )
    return levels


def report_bar_levels(levels: list[dict]) -> None:
    print(f"22 个档位（分类轴，等间距）逐档取值（方案池 min_i 非碳成本+P×碳排量，同 envelope 口径）：")
    for lv in levels:
        mark = " ← 现行价" if abs(lv["price"] - CURRENT_PRICE) < 1e-6 else ""
        print(
            f"  P={lv['price']:<8g} 电动车占比={lv['ev_share']:.1f}%"
            f"（燃油{lv['n_veh_cv']}/电{lv['n_veh_ev']}），"
            f"碳排量={lv['E_total']:.2f} kgCO2e，"
            f"该档最优总成本={lv['cost_at_p']:.2f} 元（方案出自 {lv['path']}）{mark}"
        )


def _bar_tick_label(price: float) -> str:
    if abs(price - CURRENT_PRICE) < 1e-6:
        return "0.075"
    for tick in BAR_TICK_PRICES:
        if abs(price - tick) < 1e-9:
            return f"{tick:g}" if tick != 0.0 else "0"
    return ""


def _round_hundred_ylim_and_ticks(
    values: list[float], margin_frac: float = 0.05
) -> tuple[tuple[float, float], list[float]]:
    """右轴范围＝数据 min/max 各留 margin_frac（5%）余量；刻度取整百步长。"""
    lo, hi = min(values), max(values)
    span = hi - lo
    margin = margin_frac * span if span > 0.0 else margin_frac * max(abs(hi), 1.0)
    lo2, hi2 = lo - margin, hi + margin
    tick_lo = math.floor(lo2 / 100.0) * 100.0
    tick_hi = math.ceil(hi2 / 100.0) * 100.0
    n_ticks = round((tick_hi - tick_lo) / 100.0)
    ticks = [tick_lo + 100.0 * i for i in range(n_ticks + 1)]
    return (lo2, hi2), ticks


def build_bars_figure(levels: list[dict]):
    """单格：柱＝派遣电动车占比（左轴 %），折线＋实心圆＝总成本（右轴 元）。

    横轴为 22 个档位的等间距分类轴（不是碳价本身的线性刻度）——相邻档实际价差
    悬殊（0.07502 与 0.1 只差 0.025，其余步长 0.1 或 0.2），线性轴会让前几档
    的柱子挤在一起；分类轴把每一档画成等宽的一格，仿陈婉茹 2023 图4(a)。
    """
    ink = PALETTE["ink"]
    xs = list(range(len(levels)))
    ev_share = [lv["ev_share"] for lv in levels]
    cost = [lv["cost_at_p"] for lv in levels]
    tick_labels = [_bar_tick_label(lv["price"]) for lv in levels]

    figure, ax_bar = plt.subplots(figsize=(6.9, 3.0))
    figure.subplots_adjust(left=0.085, right=0.905, bottom=0.12, top=0.96)

    ax_bar.bar(
        xs, ev_share,
        width=BAR_WIDTH_FRAC,
        facecolor=BAR_FILL, edgecolor=ink, linewidth=BAR_EDGE_WIDTH_PT,
        zorder=2,
    )
    ax_bar.set_xlim(-0.5, len(levels) - 0.5)
    ax_bar.set_xticks(xs)
    ax_bar.set_xticklabels(tick_labels, fontproperties=CN)
    ax_bar.set_ylim(0.0, 100.0)
    ax_bar.set_yticks(list(range(0, 101, 20)))
    ax_bar.set_xlabel("单位碳价（元/kgCO$_2$e）", fontproperties=CN, labelpad=2.0)
    ax_bar.set_ylabel("派遣电动车占比（%）", fontproperties=CN, labelpad=2.0)
    ax_bar.tick_params(axis="both", labelsize=TEXT_SIZE_PT, pad=1.8)
    ax_bar.spines["top"].set_visible(False)

    ax_em = ax_bar.twinx()
    cost_ylim, cost_ticks = _round_hundred_ylim_and_ticks(cost, margin_frac=0.05)
    (line_em,) = ax_em.plot(
        xs, cost,
        color=ink, linestyle="-", linewidth=CURVE_WIDTH_PT,
        marker="o", markersize=MARKER_SIZE_PT,
        markerfacecolor=ink, markeredgecolor=ink,
        zorder=3,
    )
    ax_em.set_ylim(*cost_ylim)
    ax_em.set_yticks(cost_ticks)
    ax_em.set_ylabel(COST_LABEL, fontproperties=CN, labelpad=3.0)
    ax_em.tick_params(axis="y", labelsize=TEXT_SIZE_PT, pad=1.8)
    ax_em.spines["top"].set_visible(False)

    handles = [
        Patch(facecolor=BAR_FILL, edgecolor=ink, linewidth=BAR_EDGE_WIDTH_PT,
              label="派遣电动车占比（左轴）"),
        Line2D(
            [], [], color=ink, linestyle="-", linewidth=CURVE_WIDTH_PT,
            marker="o", markersize=MARKER_SIZE_PT,
            markerfacecolor=ink, markeredgecolor=ink,
            label="总成本（右轴）",
        ),
    ]
    legend = ax_bar.legend(
        handles=handles,
        loc="upper left",
        prop=CN_LEGEND,
        frameon=True,
        framealpha=1.0,
        facecolor="white",
        edgecolor="none",
        borderpad=0.35,
        handlelength=2.4,
        handletextpad=0.45,
        labelspacing=0.32,
        borderaxespad=0.6,
    )
    legend.set_zorder(6)
    return figure, ax_bar, ax_em, legend


# --------------------------------------------------------------------------
# 画图
# --------------------------------------------------------------------------
def _headroom_ylim(values: list[float], top_frac: float, bottom_frac: float) -> tuple[float, float]:
    lo, hi = min(values), max(values)
    span = hi - lo
    if span <= 0.0:
        span = max(abs(hi), 1.0)
    return lo - bottom_frac * span, hi + top_frac * span


def build_figure(
    xs: list[float],
    cost: list[float],
    emission: list[float],
    ev_share: list[float],
    *,
    with_markers: bool,
    emission_steps: bool = False,
):
    """画两格图。level 模式（with_markers=True）逐档实心/空心圆点＋直线连接；

    envelope 模式（with_markers=False）不画散点，碳排量用 drawstyle=steps-post
    还原其阶梯本质（emission_steps=True），总成本仍是普通直线（分段线性）。
    """
    ink = PALETTE["ink"]
    xticks = [0.0, 0.5, 1.0, 1.5, 2.0]
    xlim = (X_MIN - 0.045 * X_MAX, X_MAX + 0.045 * X_MAX)

    figure, (left, right) = plt.subplots(1, 2, figsize=(6.9, 3.0))
    figure.subplots_adjust(left=0.085, right=0.905, bottom=0.185, top=0.945, wspace=0.60)

    # ---- (a) 总成本（左轴）与碳排量（右轴） ----
    ax_cost = left
    ax_em = ax_cost.twinx()

    cost_ylim = _headroom_ylim(cost, top_frac=0.22, bottom_frac=0.06)
    em_ylim = _headroom_ylim(emission, top_frac=0.22, bottom_frac=0.06)

    cost_marker_kwargs = (
        dict(marker="o", markersize=MARKER_SIZE_PT, markerfacecolor=ink, markeredgecolor=ink)
        if with_markers
        else dict(marker="None")
    )
    em_marker_kwargs = (
        dict(
            marker="o", markersize=MARKER_SIZE_PT,
            markerfacecolor="white", markeredgecolor=ink, markeredgewidth=AXIS_WIDTH_PT,
        )
        if with_markers
        else dict(marker="None")
    )

    (line_cost,) = ax_cost.plot(
        xs, cost,
        color=ink, linestyle="-", linewidth=CURVE_WIDTH_PT,
        zorder=3, **cost_marker_kwargs,
    )
    (line_em,) = ax_em.plot(
        xs, emission,
        color=ink, linestyle=(0, (4, 2.4)), linewidth=CURVE_WIDTH_PT,
        drawstyle="steps-post" if emission_steps else "default",
        zorder=2, **em_marker_kwargs,
    )

    ax_cost.set_xlim(*xlim)
    ax_cost.set_xticks(xticks)
    ax_cost.set_ylim(*cost_ylim)
    ax_em.set_ylim(*em_ylim)
    ax_cost.set_xlabel("单位碳价（元/kgCO$_2$e）", fontproperties=CN, labelpad=2.0)
    ax_cost.set_ylabel(COST_LABEL, fontproperties=CN, labelpad=2.0)
    ax_em.set_ylabel(EMISSION_LABEL, fontproperties=CN, labelpad=3.0)
    ax_cost.tick_params(axis="both", labelsize=TEXT_SIZE_PT, pad=1.8)
    ax_em.tick_params(axis="y", labelsize=TEXT_SIZE_PT, pad=1.8)
    ax_cost.spines["top"].set_visible(False)
    ax_em.spines["top"].set_visible(False)

    handles_a = [
        Line2D(
            [], [], color=ink, linestyle="-", linewidth=CURVE_WIDTH_PT,
            label="总成本（左轴）", **cost_marker_kwargs,
        ),
        Line2D(
            [], [], color=ink, linestyle=(0, (4, 2.4)), linewidth=CURVE_WIDTH_PT,
            label="碳排量（右轴）", **em_marker_kwargs,
        ),
    ]
    legend_a = ax_cost.legend(
        handles=handles_a,
        loc="best",
        prop=CN_LEGEND,
        frameon=True,
        framealpha=1.0,
        facecolor="white",
        edgecolor="none",
        borderpad=0.35,
        handlelength=2.4,
        handletextpad=0.45,
        labelspacing=0.32,
        borderaxespad=0.6,
    )
    legend_a.set_zorder(6)

    # ---- (b) 派遣电动车占比 ----
    ax_ev = right
    ax_ev.step(
        xs, ev_share, where="post",
        color=ink, linewidth=CURVE_WIDTH_PT * 1.2, zorder=3,
    )
    ax_ev.set_xlim(*xlim)
    ax_ev.set_xticks(xticks)
    ax_ev.set_ylim(-4.0, 104.0)
    ax_ev.set_yticks(list(range(0, 101, 20)))
    ax_ev.set_xlabel("单位碳价（元/kgCO$_2$e）", fontproperties=CN, labelpad=2.0)
    ax_ev.set_ylabel("派遣电动车占比（%）", fontproperties=CN, labelpad=2.0)
    ax_ev.tick_params(axis="both", labelsize=TEXT_SIZE_PT, pad=1.8)
    ax_ev.spines["top"].set_visible(False)
    ax_ev.spines["right"].set_visible(False)

    for axes, caption in zip((left, right), PANEL_CAPTIONS):
        axes.annotate(
            caption,
            xy=(0.5, 0.0),
            xycoords="axes fraction",
            xytext=(0, -34),
            textcoords="offset points",
            ha="center",
            va="top",
            fontproperties=CN_PANEL,
        )

    return figure, ax_cost, ax_em, ax_ev, legend_a


def _legend_overlap_report(figure, legend, ax_cost, ax_em, xs, cost, emission) -> None:
    """打印图例外框与两条曲线上各数据点的最小间距，替代肉眼估计。"""
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    box = legend.get_window_extent(renderer)
    inv_cost = ax_cost.transData.inverted()
    (cx0, cy0), (cx1, cy1) = inv_cost.transform([[box.x0, box.y0], [box.x1, box.y1]])
    inv_em = ax_em.transData.inverted()
    (_ex0, ey0), (_ex1, ey1) = inv_em.transform([[box.x0, box.y0], [box.x1, box.y1]])
    inside_cost = [
        (x, y) for x, y in zip(xs, cost) if cx0 <= x <= cx1 and cy0 <= y <= cy1
    ]
    inside_em = [
        (x, y) for x, y in zip(xs, emission) if cx0 <= x <= cx1 and ey0 <= y <= ey1
    ]
    print(
        f"  (a) 图例数据坐标范围：左轴 x∈[{cx0:.3f},{cx1:.3f}] y∈[{cy0:.1f},{cy1:.1f}]，"
        f"右轴 y∈[{ey0:.1f},{ey1:.1f}]"
    )
    print(
        f"  落在图例框内的数据点：总成本 {len(inside_cost)} 个、碳排量 {len(inside_em)} 个"
        + ("（⚠ 有数据被压住）" if inside_cost or inside_em else "（未压住数据点）")
    )


def _save_at_target_width(figure, out_path: Path, pad_in: float = 0.05):
    """按内容紧边界裁剪，宽度锁死在版心宽度上并让内容居中（抄自图 3/图 5 的生成器）。"""
    figure.canvas.draw()
    tight = figure.get_tightbbox(figure.canvas.get_renderer())
    target_in = TARGET_WIDTH_PT / 72.0
    if tight.width > target_in:
        raise RuntimeError(
            f"内容宽度 {tight.width * 72:.2f} pt 已超过版心宽度 {TARGET_WIDTH_PT:.2f} pt"
        )
    centre = 0.5 * (tight.x0 + tight.x1)
    box = Bbox(
        [
            [centre - target_in / 2, tight.y0 - pad_in],
            [centre + target_in / 2, tight.y1 + pad_in],
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path, format="pdf", bbox_inches=box, pad_inches=0, facecolor="white")
    png_path = out_path.with_suffix(".png")
    figure.savefig(png_path, format="png", bbox_inches=box, pad_inches=0, facecolor="white", dpi=300)
    return TARGET_WIDTH_PT, box.height * 72, png_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sweep-dir", type=Path, default=DEFAULT_SWEEP_DIR)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--mode",
        choices=("level", "envelope", "bars"),
        default="level",
        help=(
            "level（默认）＝每个碳价档取该档 3 次里 total_cost 最低的一次；"
            "envelope＝把全部已落盘 best_solution.json 当作方案池，在碳价 0~2.0 "
            f"步长 {ENVELOPE_STEP} 的细网格上逐点取 min_i(非碳成本+P×碳排量) 的下包络；"
            "bars＝单格柱状图，方案池在 22 个真实档位价上逐档取同一口径最优"
            "（柱＝电动车占比左轴，线＝碳排量右轴，等间距分类横轴）"
        ),
    )
    args = parser.parse_args(argv)
    print(f"数据源 {args.sweep_dir.relative_to(REPO)}（mode={args.mode}）")

    if args.mode == "level":
        levels = load_levels(args.sweep_dir)
        if not levels:
            raise SystemExit(f"{args.sweep_dir} 下没有任何已完成的档位，无法画图")

        total_expected_runs = 0
        total_found_runs = 0
        print(f"共 {len(levels)} 个已有数据的档位，每档所用 run 数：")
        for lv in levels:
            total_expected_runs += lv["n_runs_found"]
            total_found_runs += lv["n_runs_completed"]
            mark = " ← 现行价" if abs(lv["price"] - CURRENT_PRICE) < 1e-9 else ""
            n_total = lv["n_veh_ev"] + lv["n_veh_cv"]
            share = 100.0 * lv["n_veh_ev"] / n_total
            print(
                f"  P={lv['price_str']:<8} 已落盘目录 {lv['n_runs_found']} 个、"
                f"完成 {lv['n_runs_completed']} 个，取 {lv['best_run']}"
                f"（total_cost={lv['total_cost']:.2f}，E_total={lv['E_total']:.2f}，"
                f"n_veh_ev={lv['n_veh_ev']}，n_veh_cv={lv['n_veh_cv']}，"
                f"总车数={n_total}，电动车占比={share:.1f}%）{mark}"
            )
        print(f"合计：{total_found_runs}/{total_expected_runs} 次已落盘 run 参与取数（全批预期 66 次）")

        print("翻转点（相邻档电动车派遣数量变化处）：")
        flips = 0
        for prev, cur in zip(levels, levels[1:]):
            if prev["n_veh_ev"] != cur["n_veh_ev"]:
                flips += 1
                prev_share = 100.0 * prev["n_veh_ev"] / (prev["n_veh_ev"] + prev["n_veh_cv"])
                cur_share = 100.0 * cur["n_veh_ev"] / (cur["n_veh_ev"] + cur["n_veh_cv"])
                print(
                    f"  P={prev['price_str']} → P={cur['price_str']}："
                    f"派遣电动车 {prev['n_veh_ev']} → {cur['n_veh_ev']} 辆"
                    f"（燃油车 {prev['n_veh_cv']} → {cur['n_veh_cv']} 辆，"
                    f"占比 {prev_share:.1f}% → {cur_share:.1f}%）"
                )
        if flips == 0:
            print("  （相邻档之间没有变化）")

        xs = [lv["price"] for lv in levels]
        cost = [lv["total_cost"] for lv in levels]
        emission = [lv["E_total"] for lv in levels]
        ev_share = [
            100.0 * lv["n_veh_ev"] / (lv["n_veh_ev"] + lv["n_veh_cv"]) for lv in levels
        ]
        figure, ax_cost, ax_em, ax_ev, legend_a = build_figure(
            xs, cost, emission, ev_share, with_markers=True, emission_steps=False
        )
    elif args.mode == "envelope":
        pool = load_solution_pool(args.sweep_dir)
        print(f"方案池：{len(pool)} 个 best_solution.json（全批预期 66 个），cost_carbon 恒等式核验通过")
        grid_prices, envelope = build_envelope(pool, X_MIN, X_MAX, ENVELOPE_STEP)
        report_envelope(grid_prices, envelope)

        xs = grid_prices
        cost = [e["cost_at_p"] for e in envelope]
        emission = [e["E_total"] for e in envelope]
        ev_share = [
            100.0 * e["n_veh_ev"] / (e["n_veh_ev"] + e["n_veh_cv"]) for e in envelope
        ]
        figure, ax_cost, ax_em, ax_ev, legend_a = build_figure(
            xs, cost, emission, ev_share, with_markers=False, emission_steps=True
        )
        _legend_overlap_report(figure, legend_a, ax_cost, ax_em, xs, cost, emission)
    else:  # bars
        pool = load_solution_pool(args.sweep_dir)
        print(f"方案池：{len(pool)} 个 best_solution.json（全批预期 66 个），cost_carbon 恒等式核验通过")
        bar_levels = build_bar_levels(pool)
        n_levels = len(bar_levels)
        if n_levels != 22:
            print(f"警告：落盘档位数为 {n_levels}，不是预期的 22 档（照实画图，不编造缺档）")
        report_bar_levels(bar_levels)

        figure, ax_bar, ax_em, legend_a = build_bars_figure(bar_levels)
        ev_share = [lv["ev_share"] for lv in bar_levels]
        cost_at_p = [lv["cost_at_p"] for lv in bar_levels]
        xs = list(range(n_levels))
        _legend_overlap_report(figure, legend_a, ax_bar, ax_em, xs, ev_share, cost_at_p)

    width_pt, height_pt, png_path = _save_at_target_width(figure, args.out)
    print(f"\nwrote {args.out.relative_to(REPO)}")
    print(f"wrote {png_path.relative_to(REPO)}")
    print(f"画布 {width_pt:.2f} × {height_pt:.2f} pt")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
