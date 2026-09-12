#!/usr/bin/env python3
"""图：不同配送模式下的实际配送路径（4.5 节，2026-09-09）。

替换此前的示意图 ``concept_collaboration_fairness_notitle.pdf``：那张图的几何是手绘示意，
本图改画算例 cn-jjj-50c-01-DEPOTSEARCH-d996f755bd 的**真实解**——独立配送与联合配送各取
第 1 次运行的最优解（十次运行的客户归属、启用车辆与配送趟数一致，取哪一次都相同）。

画风沿用仓库既有图脚本：全图黑白灰、不使用彩色（SimSun 走中文、Times New Roman 走拉丁，
pdf.fonttype=42）。两车场靠**墨色深浅**区分而非颜色：企业A车场（小车场）路径为黑实线，
企业B车场（大车场）路径为中灰实线；客户为白底黑边小圆点；两车场分别为黑色实心方块与实心三角，
并加白色描边，使其在多条路径汇聚处仍能被一眼认出。

版式仿陈婉茹等（2023，《系统工程理论与实践》43(11): 3320-3335）图 3(b)「实例求解结果」：
每格四边封闭的矩形框、刻度朝内且四边都打刻度、无网格线、车场标记远大于客户标记、
格名 (a)(b)(c) 连同中文小标题排在各格框线正下方居中。与原图的差别有两处并且是刻意的：
原图逐条路径用不同颜色区分车辆、并用虚线标出电动车路径，本文全图黑白，故只按车场分墨色深浅；
原图横纵轴为经纬度，本文换成以算例西南角为原点的公里坐标，并注明单位。

三格：
  (a) 独立配送（就近归属）：两车场各自成环，5 个客户对 45 个客户，3 趟对 14 趟；
  (b) 联合配送：客户与车辆统一调配，8 个客户对 42 个客户，2 趟对 13 趟；
  (c) 联合配送中的改派客户：底图整体压到浅灰，只把企业A车场那 1 辆电动车的 2 趟加粗为黑线，
      并把 5 个改派客户标成黑色实心点并注出编号（C004、C038、C042、C043 由大车场改归小车场，
      C014 反向）。第三格不再区分车场墨色，避免与高亮争夺注意力。

坐标为 nodes.csv 的经纬度按等距圆柱投影折算的公里数（x 方向乘 cos(平均纬度)），
纵横比锁死为 1:1，故图上距离可直接目测；坐标轴本身即是尺度，不再另画比例尺。

用法（须用仓库 venv）：
  .public-hgs-venv/bin/python3 solver/scripts/generate_synergy_routes_figure.py
生成 docs/paper_v2/generated_figures/routes_synergy_v7.pdf（三格）与
routes_synergy_v7_2panel.pdf（只保留 a、b 两格），各附同名 PNG 预览。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from fontTools.ttLib import TTCollection
from matplotlib import font_manager
from matplotlib.lines import Line2D

REPO = Path(__file__).resolve().parents[2]
INSTANCE = (
    REPO
    / "data/ChinaInstances/china81_final_suite_v2_20260815/instances"
    / "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
)
NODES = INSTANCE / "nodes.csv"
REPORTS = REPO / "solver/reports/synergy_v7_20260909"
INDEPENDENT = REPORTS / "independent/run_01/best_solution.json"
JOINT = REPORTS / "joint/run_01/best_solution.json"
OUTDIR = REPO / "docs/paper_v2/generated_figures"
FONT_DIR = Path("/Applications/Microsoft Word.app/Contents/Resources/DFonts")

DEPOT_A = "D_OSM_WAY_1003511503"  # 小车场＝企业A
DEPOT_B = "D_OSM_WAY_1071205721"  # 大车场＝企业B

INK = "#000000"
GRAY = "#666666"
PALE = "#D0D0D0"
ROUTE_PT = 0.42
HILITE_PT = 0.95
# 本图按版心原尺寸插入，图内文字统一为 8 pt，比 9 pt 图题小一号。
TEXT_PT = 8.0
LABEL_PT = 8.0
TICK_PT = 8.0

# 标记尺寸（磅）：车场远大于客户，是仿原图区分车场与客户的主要手段。
CUST_MS = 2.0
MOVED_MS = 3.6
DEPOT_A_MS = 5.2
DEPOT_B_MS = 6.0

# 改派客户：C004/C038/C042/C043 由企业B车场改归企业A车场，C014 反向。
MOVED_TO_A = ("C004", "C038", "C042", "C043")
MOVED_TO_B = ("C014",)
# 编号注记相对客户点的偏移（公里），按第一版渲染的实际重叠情况逐个调开。
LABEL_OFFSET_KM = {
    "C004": (5.2, -3.0),
    "C038": (2.6, 4.8),
    "C042": (5.0, 0.4),
    "C043": (-4.4, 2.2),
    "C014": (2.2, -0.4),
}
LABEL_ALIGN = {
    "C004": ("left", "top"),
    "C038": ("left", "bottom"),
    "C042": ("left", "bottom"),
    "C043": ("right", "bottom"),
    "C014": ("left", "center"),
}

_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_synergy_routes_font_")


def _simsun_regular() -> Path:
    source = FONT_DIR / "Simsun.ttc"
    target = Path(_FONT_TMP.name) / "simsun_regular.ttf"
    for font in TTCollection(source).fonts:
        names = {r.toUnicode() for r in font["name"].names if r.nameID == 6}
        if "SimSun" in names:
            font.save(target)
            return target
    raise RuntimeError("SimSun face not found in Word Simsun.ttc")


CN = font_manager.FontProperties(fname=_simsun_regular(), size=TEXT_PT)
CN_LEGEND = font_manager.FontProperties(fname=CN.get_file(), size=TEXT_PT)
EN = font_manager.FontProperties(family="Times New Roman", size=TEXT_PT)
EN_SMALL = font_manager.FontProperties(family="Times New Roman", size=LABEL_PT)
EN_TICK = font_manager.FontProperties(family="Times New Roman", size=TICK_PT)
EN_VAR = font_manager.FontProperties(fname=FONT_DIR / "timesi.ttf", size=TICK_PT)

plt.rcParams.update(
    {
        "font.family": "Times New Roman",
        "font.size": TEXT_PT,
        "pdf.fonttype": 42,
        "savefig.dpi": 300,
    }
)


def load_nodes() -> dict[str, tuple[float, float]]:
    """读经纬度并投影成公里坐标（等距圆柱，x 乘 cos(平均纬度)）。"""
    rows = list(csv.DictReader(NODES.open(encoding="utf-8")))
    keep = {r["node_id"]: (float(r["longitude"]), float(r["latitude"]))
            for r in rows if r["node_type"] in ("customer", "depot")}
    lat0 = sum(v[1] for v in keep.values()) / len(keep)
    lon0 = min(v[0] for v in keep.values())
    kx = 111.320 * math.cos(math.radians(lat0))
    ky = 110.574
    base_lat = min(v[1] for v in keep.values())
    return {k: ((lon - lon0) * kx, (lat - base_lat) * ky) for k, (lon, lat) in keep.items()}


def load_routes(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    routes = payload["evaluation"]["prepared_solution"]["routes"]
    for route in routes:
        sequence = route["node_sequence"]
        assert sequence[0] == sequence[-1] == route["home_depot_id"], "路径未闭合到自身车场"
        assert not any(n.startswith("S_") for n in sequence[1:-1]), "路径里混入了充电站节点"
    return routes


def customers_of(routes: list[dict], depot: str) -> set[str]:
    return {n for r in routes if r["home_depot_id"] == depot
            for n in r["node_sequence"] if n.startswith("C")}


def style_frame(ax) -> None:
    """仿陈婉茹图 3(b)：四边封闭框线、刻度朝内、四边都打刻度、无网格。"""
    ax.set_aspect("equal", adjustable="box")
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.6)
        spine.set_color(INK)
    ax.grid(False)
    ax.tick_params(axis="both", which="major", direction="in", length=2.4,
                   width=0.5, color=INK, labelsize=TICK_PT,
                   top=True, right=True, pad=1.8)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(EN_TICK)


def draw_map(ax, xy, routes, *, mode: str) -> None:
    """mode 取 'plain'（按车场分墨色）或 'highlight'（压灰底图、突出改派）。"""
    style_frame(ax)

    for route in routes:
        home = route["home_depot_id"]
        points = [xy[n] for n in route["node_sequence"]]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if mode == "plain":
            color = INK if home == DEPOT_A else GRAY
            width = ROUTE_PT
            order = 3 if home == DEPOT_A else 2
        else:
            highlighted = home == DEPOT_A
            color = INK if highlighted else PALE
            width = HILITE_PT if highlighted else ROUTE_PT
            order = 4 if highlighted else 2
        ax.plot(xs, ys, color=color, linewidth=width, solid_joinstyle="round",
                solid_capstyle="round", zorder=order)

    moved = set(MOVED_TO_A) | set(MOVED_TO_B)
    for node, (x, y) in xy.items():
        if not node.startswith("C"):
            continue
        if mode == "plain":
            ax.plot(x, y, marker="o", markersize=CUST_MS, markerfacecolor="white",
                    markeredgecolor=INK, markeredgewidth=0.4, zorder=5)
        elif node in moved:
            # 改派客户：黑色实心大点＋白色描边，压在浅灰底图之上一眼可见。
            ax.plot(x, y, marker="o", markersize=MOVED_MS, markerfacecolor=INK,
                    markeredgecolor="white", markeredgewidth=0.6, zorder=7)
        else:
            ax.plot(x, y, marker="o", markersize=CUST_MS - 0.2, markerfacecolor="white",
                    markeredgecolor=PALE, markeredgewidth=0.4, zorder=3)

    if mode == "highlight":
        for node in MOVED_TO_A + MOVED_TO_B:
            x, y = xy[node]
            dx, dy = LABEL_OFFSET_KM[node]
            ha, va = LABEL_ALIGN[node]
            # 白底无框衬底：编号压在浅灰底图或加粗路径上时仍读得清；
            # 引线拉到 3 km 以上，五个编号各自认得出对应的点。
            ax.annotate(node, xy=(x, y), xytext=(x + dx, y + dy),
                        fontproperties=EN_SMALL, color=INK, ha=ha, va=va,
                        zorder=8,
                        bbox=dict(boxstyle="square,pad=0.15", facecolor="white",
                                  edgecolor="none"),
                        arrowprops=dict(arrowstyle="-", linewidth=0.35,
                                        color=INK, shrinkA=1.0, shrinkB=2.0))

    # 车场：仿原图「车场标记远大于客户标记」，直径约为客户点的 2.6 倍；
    # 加白色描边，使汇聚到车场的十余条路径不糊住标记本身。
    ax.plot(*xy[DEPOT_A], marker="s", markersize=DEPOT_A_MS, markerfacecolor=INK,
            markeredgecolor="white", markeredgewidth=0.7, zorder=9)
    ax.plot(*xy[DEPOT_B], marker="^", markersize=DEPOT_B_MS, markerfacecolor=INK,
            markeredgecolor="white", markeredgewidth=0.7, zorder=9)


def panel_caption(fig, ax, prefix: str, chinese: str, drop_in: float = 0.085) -> None:
    box = ax.get_position()
    y = box.y0 - drop_in / fig.get_figheight()
    centre = (box.x0 + box.x1) / 2.0
    # 拉丁前缀与中文分两段写，免得整串交给中文字体后字母走形；
    # 先各自量出宽度，再把「前缀＋中文」整体在格宽内居中。
    renderer = fig.canvas.get_renderer()
    en_text = fig.text(centre, y, prefix, fontproperties=EN, ha="left", va="top")
    cn_text = fig.text(centre, y, chinese, fontproperties=CN, ha="left", va="top")
    en_width = en_text.get_window_extent(renderer=renderer).width / fig.bbox.width
    cn_width = cn_text.get_window_extent(renderer=renderer).width / fig.bbox.width
    start = centre - (en_width + cn_width) / 2.0
    en_text.set_position((start, y))
    cn_text.set_position((start + en_width, y))


def add_axis_unit_labels(ax):
    """把单字母变量设为 Times New Roman Italic，单位保持正体。"""
    x_var = ax.text(0, -0.14, "x", transform=ax.transAxes, fontproperties=EN_VAR,
                    ha="left", va="top", clip_on=False)
    x_unit = ax.text(0, -0.14, "/km", transform=ax.transAxes, fontproperties=EN_TICK,
                     ha="left", va="top", clip_on=False)
    y_var = ax.text(-0.17, 0, "y", transform=ax.transAxes, fontproperties=EN_VAR,
                    rotation=90, rotation_mode="anchor", ha="left", va="center", clip_on=False)
    y_unit = ax.text(-0.17, 0, "/km", transform=ax.transAxes, fontproperties=EN_TICK,
                     rotation=90, rotation_mode="anchor", ha="left", va="center", clip_on=False)
    return x_var, x_unit, y_var, y_unit


def center_axis_unit_labels(fig, ax, labels) -> None:
    renderer = fig.canvas.get_renderer()
    x_var, x_unit, y_var, y_unit = labels
    x_var_width = x_var.get_window_extent(renderer=renderer).width / ax.bbox.width
    x_unit_width = x_unit.get_window_extent(renderer=renderer).width / ax.bbox.width
    x_start = 0.5 - (x_var_width + x_unit_width) / 2.0
    x_var.set_position((x_start, -0.14))
    x_unit.set_position((x_start + x_var_width, -0.14))

    y_var_height = y_var.get_window_extent(renderer=renderer).height / ax.bbox.height
    y_unit_height = y_unit.get_window_extent(renderer=renderer).height / ax.bbox.height
    y_start = 0.5 - (y_var_height + y_unit_height) / 2.0
    y_var.set_position((-0.17, y_start))
    y_unit.set_position((-0.17, y_start + y_var_height))


def build(panels: int, out_pdf: Path) -> None:
    xy = load_nodes()
    independent = load_routes(INDEPENDENT)
    joint = load_routes(JOINT)

    specs = [("(a) ", "独立配送（就近归属）", independent, "plain"),
             ("(b) ", "联合配送", joint, "plain")]
    if panels == 3:
        specs.append(("(c) ", "联合配送中的改派客户", joint, "highlight"))

    fig_width = 6.51  # \textwidth = 469.47 pt
    outer_left = 0.03
    right_pad = 0.05
    gap = 0.16          # 两格框线之间的空档
    ylab_band = 0.38    # 每格左侧留给纵轴刻度数字与「y/km」的宽度
    cell_width = (fig_width - outer_left - right_pad - gap * (panels - 1)) / panels
    axes_width = cell_width - ylab_band

    xs = [p[0] for p in xy.values()]
    ys = [p[1] for p in xy.values()]
    pad = 3.0  # 四边等量留白，任何标记都不贴框线
    xlim = (min(xs) - pad, max(xs) + pad)
    ylim = (min(ys) - pad, max(ys) + pad)
    map_aspect = (ylim[1] - ylim[0]) / (xlim[1] - xlim[0])
    axes_height = axes_width * map_aspect  # 与 set_aspect("equal") 自洽，框内 1:1

    xlab_band = 0.30    # 框线以下留给横轴刻度数字与「x/km」的高度
    caption_band = 0.24
    bottom_pad = 0.04
    top_pad = 0.05
    fig_height = (axes_height + xlab_band + caption_band
                  + bottom_pad + top_pad)

    fig = plt.figure(figsize=(fig_width, fig_height))
    axes_bottom = (bottom_pad + caption_band + xlab_band) / fig_height

    made = []
    for index, (prefix, chinese, routes, mode) in enumerate(specs):
        cell_x = outer_left + index * (cell_width + gap)
        rect = [(cell_x + ylab_band) / fig_width, axes_bottom,
                axes_width / fig_width, axes_height / fig_height]
        ax = fig.add_axes(rect)
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        draw_map(ax, xy, routes, mode=mode)
        axis_labels = add_axis_unit_labels(ax)
        made.append((ax, prefix, chinese, axis_labels))

    fig.canvas.draw()
    for ax, prefix, chinese, axis_labels in made:
        center_axis_unit_labels(fig, ax, axis_labels)
        panel_caption(fig, ax, prefix, chinese, drop_in=xlab_band - 0.02)

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, format="pdf", facecolor="white")
    fig.savefig(out_pdf.with_suffix(".png"), format="png", dpi=400, facecolor="white")
    plt.close(fig)
    print(f"wrote {out_pdf} ({fig_width:.2f}x{fig_height:.2f} in)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", type=Path, default=OUTDIR)
    args = parser.parse_args()
    build(3, args.outdir / "routes_synergy_v7.pdf")
    build(2, args.outdir / "routes_synergy_v7_2panel.pdf")

    # 开跑即自检：格内趟数与客户数都必须与正文一致
    # （独立 3/14 趟、5/45 个客户；联合 2/13 趟、8/42 个客户）。
    for tag, path, want_trips, want_cust in (
        ("独立", INDEPENDENT, (3, 14), (5, 45)),
        ("联合", JOINT, (2, 13), (8, 42)),
    ):
        routes = load_routes(path)
        got = (sum(1 for r in routes if r["home_depot_id"] == DEPOT_A),
               sum(1 for r in routes if r["home_depot_id"] == DEPOT_B))
        assert got == want_trips, f"{tag}配送趟数 {got} 与正文 {want_trips} 不符"
        cust = (len(customers_of(routes, DEPOT_A)), len(customers_of(routes, DEPOT_B)))
        assert cust == want_cust, f"{tag}配送客户数 {cust} 与正文 {want_cust} 不符"
        print(f"{tag}配送：小车场{got[0]}趟、大车场{got[1]}趟，"
              f"客户{cust[0]}／{cust[1]}个")


if __name__ == "__main__":
    main()
