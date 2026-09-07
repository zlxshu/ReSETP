#!/usr/bin/env python3
"""图：各碳减排措施的实测成绩散点（4.4.3，2026-09-08）。

## 这张图为哪句话服务

4.4.3 正文的判断是"单一措施各有所长而不能兼得，只有本文的组合方案能同时大幅降本
减排"。政策表把这句话的证据摊成 12 列数字，读者要自己在脑子里比两列。本图只留
读者真正要比的两列——Δ总成本与Δ碳排量——把每个情形放到平面上：**左下象限＝降本
减排**，用淡灰底标出；其余三个象限就是"有所长而不能兼得"。

## 数据从哪来（不另立口径）

直接复用表 13 的生成器 `build_policy_table.py`：行清单用它的 `ROWS`，取数用它的
`resolve_row` / `resolve_carbon_price_row_from_pool`，分支顺序与它的 `build_table()`
一致。**不自己写 find_solutions + aggregate_breakdown**——`ROWS` 里的 `runs=(...)`
过滤（当前无行使用，机制仍在）就住在 `resolve_row` 里面，绕开它会悄悄改掉那个点的
采样深度。Δ 相对 `group=="baseline"` 的行计算，与政策表的 Δ 两列同义。

脚本默认做一次**对表核验**：把每个点的 Δ 用 `build_policy_table.fmt_delta` 格成
字符串，与 `docs/paper_v2/generated_tables/policy_table.tex` 里对应行的 Δ 两列
逐字比对，不一致就报错退出（`--no-check-table` 可关）。

## 画风（2026-09-09 晚按用户"散点画法视觉上怪、学别人画法模仿"改）

**为什么仍是散点，不改成柱状/折线**：目标期刊两篇母版里没有"多方案×两指标"的同类图
——陈婉茹等 2023 图 5 是"各车队配置的能耗成本分项"分组柱状图（一个指标拆成分项），
陈雨蝶等 2025 图 7 是每条路径的载重变化折线，都不是本图要做的事。柱状版本
（`generate_policy_bar_figure.py`）用户已于 2026-09-09 从正文移除，不再复活。
用户这次说的是"画法怪"和图例，属于同一体裁内的修法，故保留散点，只改下面三处。

1. **去掉左下象限的灰底矩形**。原来用淡灰块标"降本减排"象限，占掉半张图的面积，
   是这张图显得又空又怪的主因；改为只保留过原点的两条虚线零线，象限含义由零线交代。
2. **坐标范围贴紧数据**。原来 x∈[−170, 220]、y∈[−140, 15]，点只占约三分之一；
   现在 x∈[−165, 225]、y∈[−132, 14]，并把图高从 2.8 英寸压到 2.4 英寸，
   与前面图 4（`figure_4_tariff_carbon_windows.pdf`，496.8×187.2pt＝6.9×2.6 英寸，
   同样以 `width=\\textwidth` 插入）在版面上的高度相当。
   **不要改成 3.4 英寸宽**：本刊是单栏排版（版心 165mm），图仍以 `width=\\textwidth`
   插入，把 PDF 做成 3.4 英寸只会被 LaTeX 放大约 1.8 倍，8pt 的字实际印成 14pt。
3. **图例加白底细黑框**（`frameon=True`＋白色底＋黑色边框＋不透明），位置放在右上角
   的空白区——两篇母版的图例都是这么做的（陈婉茹图 5 右上角带框图例、
   陈雨蝶图 7 右侧带框图例），原来的无框图例浮在坐标区里没有边界。

标记：单一措施＝空心圆，`--highlight` 指定的本文方案＝实心五角星且标签加粗，
基准＝原点上的黑色十字，组合措施（当前表内已无此类点）＝实心方块。

用法（须用仓库 venv）：
  .public-hgs-venv/bin/python3 solver/scripts/generate_policy_scatter_figure.py \
      [--highlight 本文方案] [--exclude 碳价0.075 ...] [--no-wide] [--out PDF]
（`--highlight` / `--exclude` 只认 SHORT_BY_DIR 里现有的短名，给别的会直接退出。）
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fontTools.ttLib import TTCollection
from matplotlib import font_manager
from matplotlib.lines import Line2D

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver/scripts"))
import build_policy_table as bpt  # noqa: E402

OUT = REPO / "docs/paper_v2/generated_figures/figure_policy_scatter.pdf"
TABLE_TEX = REPO / "docs/paper_v2/generated_tables/policy_table.tex"
TEXT_PT = 8.0
_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_policy_scatter_font_")

# 短名：命令行 --highlight / --exclude 用的就是这一列。
# 键＝表 13 ROWS 的 new_dir（label 是带 \makecell[l]{...\\...} 的 LaTeX 串，
# 命令行没法用），值＝(短名, 图上标签)。
SHORT_BY_DIR: dict[str, tuple[str, str]] = {
    "solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS": ("基准", "基准"),
    "solver/reports/grid2x2_v3_20260906/midday/P=0.2/MTC-HGS": ("午间谷段", "午间谷段"),
    "solver/reports/policy_combos_20260907/green_window": ("午间谷价补贴", "午间谷价补贴"),
    "solver/reports/carbon_price_sweep_v3_20260906/P=0.07502": ("碳价0.075", "碳价0.075"),
    "solver/reports/grid2x2_v3_20260906/beijing/P=1.0/MTC-HGS": ("碳价1.0", "碳价1.0"),
    "solver/reports/carbon_price_sweep_v3_20260906/P=1.5": ("碳价1.5", "碳价1.5"),
    "solver/reports/policy_combos_20260907/quota200": ("碳配额200", "碳配额200"),
    "solver/reports/policy_combos_20260907/subsidy_alone": ("购置补贴", "购置补贴"),
    # 2026-09-08 用户定：三个两两组合行已移出表 13（只在正文里作设计路径叙述），
    # 本文方案改为午间谷段＋全生命周期价差补贴 46.97 元/日＋碳价 1.2。
    "solver/reports/policy_combos_20260907/midday_subsidy47_P1.2":
        ("本文方案", "谷段设在午间＋价差补贴\n＋碳价1.2"),
}

DEFAULT_HIGHLIGHT = "本文方案"

# 标签相对点的偏移（数据坐标：元, kg）与对齐方式，按短名手工调，
# 11 个点用不着 adjustText，venv 里也没装。
LABEL_OFFSET: dict[str, tuple[float, float, str, str]] = {
    # 短名: (dx 元, dy kg, ha, va)。左上角一簇点（基准/碳价0.075/碳配额200/午间谷段/
    # 午间谷价补贴）挤在一起，逐个错开方向；碳价1.5 贴右边界，标签放左侧。
    "基准":            (7.0, 4.0, "left", "bottom"),
    "碳价0.075":       (2.0, 5.0, "center", "bottom"),
    "午间谷段":        (7.0, 0.0, "left", "center"),
    "碳配额200":       (-7.0, 0.0, "right", "center"),
    "午间谷价补贴":    (-4.0, 5.0, "right", "bottom"),
    "购置补贴":        (-7.0, 0.0, "right", "center"),
    "碳价1.0":         (0.0, 6.0, "center", "bottom"),
    "碳价1.5":         (-7.0, 0.0, "right", "center"),
    "本文方案":        (8.0, 0.0, "left", "center"),
}


def rel(path: Path) -> str:
    """仓库内的路径报相对路径，仓库外（如 --out 指到别处）原样报绝对路径。"""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _songti_regular() -> Path:
    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    target = Path(_FONT_TMP.name) / "songti_sc_regular.ttf"
    for font in TTCollection(source).fonts:
        names = {r.toUnicode() for r in font["name"].names if r.nameID == 6}
        if "STSongti-SC-Regular" in names:
            font.save(target)
            return target
    raise RuntimeError("Songti SC Regular face not found")


def load_points() -> list[dict]:
    """按表 13 的口径取每一行，算出 Δ总成本 / Δ碳排量。"""
    pool: list = []
    if bpt.CARBON_ROWS_FROM_POOL and any(bpt.is_carbon_price_row(r) for r in bpt.ROWS):
        pool = bpt.load_carbon_sweep_pool()

    resolved: list[tuple[dict, dict]] = []
    baseline = None
    for row in bpt.ROWS:
        if bpt.CARBON_ROWS_FROM_POOL and bpt.is_carbon_price_row(row):
            result = bpt.resolve_carbon_price_row_from_pool(row, pool)
        else:
            result = bpt.resolve_row(row, False)
        if result is None:
            print(f"缺失：{row['new_dir']} —— 跳过该点", file=sys.stderr)
            continue
        _source, _paths, bd = result
        resolved.append((row, bd))
        if row["group"] == "baseline":
            baseline = bd
    if baseline is None:
        raise RuntimeError("基准行缺失，Δ 无从算起")

    points = []
    for row, bd in resolved:
        short, label = SHORT_BY_DIR.get(row["new_dir"], (row["new_dir"], row["new_dir"]))
        points.append(dict(
            short=short, label=label, group=row["group"], new_dir=row["new_dir"],
            n=bd.get("__n__", 1),
            dcost=bd["total_cost"] - baseline["total_cost"],
            dcarbon=bd["E_total"] - baseline["E_total"],
        ))
    return points


def quadrant(dcost: float, dcarbon: float) -> str:
    if dcost == 0 and dcarbon == 0:
        return "原点（基准）"
    if dcost < 0 and dcarbon < 0:
        return "左下：降本减排"
    if dcost < 0 and dcarbon >= 0:
        return "左上：降本增排"
    if dcost >= 0 and dcarbon < 0:
        return "右下：增本减排"
    return "右上：增本增排"


def check_against_table(points: list[dict]) -> list[str]:
    """把每个点的 Δ 与 policy_table.tex 的 Δ 两列逐字比对。"""
    if not TABLE_TEX.exists():
        return [f"跳过对表核验：{rel(TABLE_TEX)} 不存在（先跑 build_policy_table.py）"]
    body = TABLE_TEX.read_text()
    lines = [ln.strip() for ln in body.splitlines() if ln.strip().endswith(r"\\")]
    # 一条数据行以 \\ 结尾且含 n_cells 个 & 分隔的单元格；表头也是，靠"类别 &"排掉。
    # 列数跟着 build_policy_table.COMPACT_COST_COLUMNS 走：紧凑版 9 列
    # （类别/情形/燃油电动/运营成本/碳成本/总成本/碳排量/Δ总成本/Δ碳排量），
    # 旧的 12 列版把运营成本拆成启动/行驶/充电/油耗四列。Δ 两列恒为最后两格。
    n_cells = 9 if bpt.COMPACT_COST_COLUMNS else 12
    data_rows = [
        ln for ln in lines
        if ln.count("&") == n_cells - 1 and not ln.startswith("类别 &")
    ]
    out = []
    if len(data_rows) != len(points):
        return [f"对表核验失败：tex 数据行 {len(data_rows)} 条，图上点 {len(points)} 个，行数对不上"]
    for row_tex, pt in zip(data_rows, points):
        cells = [c.strip() for c in row_tex.rstrip("\\").split("&")]
        tex_dcost, tex_dcarbon = cells[-2], cells[-1]
        my_dcost = "" if pt["group"] == "baseline" else bpt.fmt_delta(pt["dcost"])
        my_dcarbon = "" if pt["group"] == "baseline" else bpt.fmt_delta(pt["dcarbon"])
        ok = (tex_dcost == my_dcost) and (tex_dcarbon == my_dcarbon)
        out.append(
            f"{'OK  ' if ok else '不符'} {pt['short']:<22s} "
            f"tex=({tex_dcost or '—'}, {tex_dcarbon or '—'})  图=({my_dcost or '—'}, {my_dcarbon or '—'})"
        )
        if not ok:
            out.append("对表核验失败：上面这一行的 Δ 与表 13 不一致，图与表口径已分家")
            raise SystemExit("\n".join(out))
    return out


def style_axes(ax):
    ax.tick_params(direction="out", length=2.5, width=0.5, pad=2, labelsize=TEXT_PT)
    for s in ax.spines.values():
        s.set_linewidth(0.5)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--highlight", default=DEFAULT_HIGHLIGHT,
                    help=f"本文方案的短名，用实心五角星并加粗标签（默认 {DEFAULT_HIGHLIGHT}；"
                         f"传空串则不高亮）")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="不画的点，按短名给（如 --exclude 午间谷段+碳价1.0）")
    ap.add_argument("--wide", action=argparse.BooleanOptionalAction, default=True,
                    help="通栏 6.9×2.4 英寸（默认）；--no-wide 出单栏 3.4×2.4")
    ap.add_argument("--check-table", action=argparse.BooleanOptionalAction, default=True,
                    help="与 policy_table.tex 的 Δ 两列逐字核对（默认开）")
    args = ap.parse_args()

    known = {v[0] for v in SHORT_BY_DIR.values()}
    for name in list(args.exclude) + ([args.highlight] if args.highlight else []):
        if name not in known:
            raise SystemExit(f"未知短名 {name!r}；可用：{sorted(known)}")

    points = load_points()

    if args.check_table:
        print("# 与表 13 的 Δ 两列对表核验", file=sys.stderr)
        for line in check_against_table(points):
            print("  " + line, file=sys.stderr)

    drawn = [p for p in points if p["short"] not in set(args.exclude)]
    if args.exclude:
        print(f"# 已排除：{', '.join(args.exclude)}", file=sys.stderr)

    print("\n# 各点坐标（Δ 相对基准）", file=sys.stderr)
    for p in drawn:
        kind = ("本文方案" if p["short"] == args.highlight
                else {"baseline": "基准", "single": "既有方案", "combo": "组合措施"}[p["group"]])
        print(f"  {p['short']:<22s} {kind:<6s} n={p['n']:<3d} "
              f"Δ总成本={p['dcost']:+9.2f} 元  Δ碳排量={p['dcarbon']:+9.2f} kg  "
              f"{quadrant(p['dcost'], p['dcarbon'])}", file=sys.stderr)

    font_path = _songti_regular()
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams["axes.unicode_minus"] = False

    figsize = (6.9, 2.4) if args.wide else (3.4, 2.4)
    fig, ax = plt.subplots(figsize=figsize)

    xs = [p["dcost"] for p in drawn]
    ys = [p["dcarbon"] for p in drawn]
    # 坐标范围贴数据手工定档（2026-09-08）：自适应留白会把点全挤到一角。
    # 越界时退回自适应，免得以后换数据被悄悄裁掉点。
    xlo, xhi = -165.0, 225.0
    ylo, yhi = -132.0, 14.0
    if min(xs) < xlo or max(xs) > xhi or min(ys) < ylo or max(ys) > yhi:
        print("警告：有点落在手工坐标范围之外，退回自适应留白", file=sys.stderr)
        xpad = max(60.0, 0.18 * (max(xs) - min(xs)))
        ypad = max(12.0, 0.16 * (max(ys) - min(ys)))
        xlo, xhi = min(xs) - xpad, max(xs) + xpad
        ylo, yhi = min(ys) - ypad, max(ys) + ypad

    # 只画过原点的两条零线；原来的"左下象限淡灰底"已去掉（见 docstring 画风第 1 条）。
    ax.axhline(0, color="0.45", linewidth=0.6, linestyle=(0, (4, 3)), zorder=1)
    ax.axvline(0, color="0.45", linewidth=0.6, linestyle=(0, (4, 3)), zorder=1)

    for p in drawn:
        if p["short"] == args.highlight:
            ax.plot(p["dcost"], p["dcarbon"], marker="*", markersize=9,
                    color="black", markeredgewidth=0.0, zorder=4)
        elif p["group"] == "baseline":
            ax.plot(p["dcost"], p["dcarbon"], marker="+", markersize=6,
                    color="black", markeredgewidth=1.0, zorder=4)
        elif p["group"] == "combo":
            ax.plot(p["dcost"], p["dcarbon"], marker="s", markersize=4,
                    color="black", markeredgewidth=0.0, zorder=4)
        else:
            ax.plot(p["dcost"], p["dcarbon"], marker="o", markersize=4.5,
                    markerfacecolor="white", markeredgecolor="black",
                    markeredgewidth=0.7, zorder=4)
        dx, dy, ha, va = LABEL_OFFSET.get(p["short"], (8.0, 0.0, "left", "center"))
        ax.annotate(p["label"], (p["dcost"] + dx, p["dcarbon"] + dy),
                    ha=ha, va=va, fontsize=TEXT_PT - 1.0, linespacing=1.15,
                    fontweight="bold" if p["short"] == args.highlight else "normal",
                    zorder=5)

    ax.set_xlim(xlo, xhi)
    ax.set_ylim(ylo, yhi)
    ax.set_xlabel("$\\Delta$总成本（元）", fontsize=TEXT_PT)
    ax.set_ylabel("$\\Delta$碳排量（kgCO$_2$e）", fontsize=TEXT_PT)
    style_axes(ax)

    handles = [
        Line2D([0], [0], linestyle="none", marker="o", markersize=4.5,
               markerfacecolor="white", markeredgecolor="black", markeredgewidth=0.7,
               label="既有方案"),
    ]
    # 组合措施（实心方块）在 2026-09-08 的表 13 里已无对应点，只有仍画出组合点时才列。
    if any(p["group"] == "combo" and p["short"] != args.highlight for p in drawn):
        handles.append(Line2D([0], [0], linestyle="none", marker="s", markersize=4,
                              color="black", label="组合措施"))
    if any(p["short"] == args.highlight for p in drawn):
        handles.append(Line2D([0], [0], linestyle="none", marker="*", markersize=7,
                              color="black", label="本文方案"))
    if any(p["group"] == "baseline" for p in drawn):
        handles.append(Line2D([0], [0], linestyle="none", marker="+", markersize=6,
                              color="black", markeredgewidth=1.0, label="基准"))
    legend = ax.legend(handles=handles, loc="upper right", frameon=True,
                       fontsize=TEXT_PT - 1.0, handlelength=1.2, labelspacing=0.3,
                       borderaxespad=0.5, borderpad=0.45)
    frame = legend.get_frame()
    frame.set_facecolor("white")
    frame.set_edgecolor("black")
    frame.set_linewidth(0.5)
    frame.set_alpha(1.0)
    legend.set_zorder(6)

    fig.subplots_adjust(left=0.085 if args.wide else 0.17, right=0.99,
                        bottom=0.20, top=0.96)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    fig.savefig(args.out.with_suffix(".png"), dpi=200)
    print(f"\n已写出 {rel(args.out)} 与同名 .png"
          f"（{figsize[0]}×{figsize[1]} 英寸）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
