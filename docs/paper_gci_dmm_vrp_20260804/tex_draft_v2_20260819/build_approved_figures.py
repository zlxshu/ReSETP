from __future__ import annotations

# Source identity: PROJECT_DOMAIN orchestration script.
# Visual source: ../figure_shells_20260813/build_figure_shells.py (user-approved).

import csv
import json
import math
from pathlib import Path
import tempfile

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, Patch, Polygon, Rectangle
import numpy as np
from fontTools.ttLib import TTCollection


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
DATA_DIR = HERE / "data"
OUT_DIR = HERE / "figures"
NODE_SOURCE = (
    REPO_ROOT
    / "docs/handoff/reform_council_20260818/exhibits_20260819/figure2_nodes_routes.csv"
)
STANDALONE_A = (
    REPO_ROOT
    / "solver/reports/synergy_formal_20260819/standalone/ENT_A/seed_6/best_solution.json"
)
STANDALONE_B = (
    REPO_ROOT
    / "solver/reports/synergy_formal_20260819/standalone/ENT_B/seed_10/best_solution.json"
)
JOINT = REPO_ROOT / "solver/reports/synergy_formal_20260819/joint/seed_8/best_solution.json"

PALETTE = {
    "blue": "#0072B2",
    "green": "#009E73",
    "red": "#D55E00",
    "amber": "#E69F00",
    "purple": "#CC79A7",
    "gray": "#666666",
    "light_gray": "#D9D9D9",
    "dark": "#1A1A1A",
}

AXIS_WIDTH_PT = 0.468
CURVE_WIDTH_PT = 0.62
FLOW_WIDTH_PT = 0.75
TEXT_SIZE_PT = 8.0
MARKER_SIZE_PT = 3.0
CAPTION_BAND_IN = 0.28
FONT_TEMP_DIR = tempfile.TemporaryDirectory(prefix="resetp_approved_figure_font_")


def regular_songti_path() -> Path:
    """Extract the regular Songti face exactly as the approved shell generator does."""
    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    target = Path(FONT_TEMP_DIR.name) / "songti_sc_regular.ttf"
    collection = TTCollection(source)
    for font in collection.fonts:
        postscript_names = {
            record.toUnicode()
            for record in font["name"].names
            if record.nameID == 6
        }
        if "STSongti-SC-Regular" in postscript_names:
            font.save(target)
            return target
    raise RuntimeError("Songti SC Regular face not found in system Songti.ttc")


def medium_heiti_path() -> Path:
    """Extract the simplified-Chinese Heiti face from the two-face TTC."""
    source = Path("/System/Library/Fonts/STHeiti Medium.ttc")
    target = Path(FONT_TEMP_DIR.name) / "heiti_sc_medium.ttf"
    collection = TTCollection(source)
    for font in collection.fonts:
        postscript_names = {
            record.toUnicode()
            for record in font["name"].names
            if record.nameID == 6
        }
        if "STHeitiSC-Medium" in postscript_names:
            font.save(target)
            return target
    raise RuntimeError("Heiti SC Medium face not found in system STHeiti Medium.ttc")


SONGTI_REGULAR = regular_songti_path()
HEITI_MEDIUM = medium_heiti_path()
CN = font_manager.FontProperties(fname=SONGTI_REGULAR, size=TEXT_SIZE_PT)
CN_SMALL = font_manager.FontProperties(fname=SONGTI_REGULAR, size=TEXT_SIZE_PT)
EN = font_manager.FontProperties(family="Times New Roman", size=TEXT_SIZE_PT)
HEITI = font_manager.FontProperties(fname=HEITI_MEDIUM, size=9.0)


plt.rcParams.update(
    {
        "font.family": "Times New Roman",
        "font.size": TEXT_SIZE_PT,
        "axes.linewidth": AXIS_WIDTH_PT,
        "lines.linewidth": CURVE_WIDTH_PT,
        "xtick.major.width": AXIS_WIDTH_PT,
        "ytick.major.width": AXIS_WIDTH_PT,
        "xtick.minor.width": AXIS_WIDTH_PT,
        "ytick.minor.width": AXIS_WIDTH_PT,
        "legend.fontsize": TEXT_SIZE_PT,
        "legend.frameon": True,
        "legend.fancybox": False,
        "legend.framealpha": 1.0,
        "legend.edgecolor": PALETTE["light_gray"],
        "legend.facecolor": "white",
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.dpi": 300,
        "mathtext.fontset": "custom",
        "mathtext.rm": "Times New Roman",
        "mathtext.it": "Times New Roman:italic",
        "mathtext.bf": "Times New Roman:bold",
    }
)


def add_figure_title(fig: plt.Figure, title: str) -> None:
    """Add the approved 0.28-inch, 9-point Heiti caption band below a figure."""
    old_width, old_height = fig.get_size_inches()
    axes_positions = [(ax, ax.get_position().frozen()) for ax in fig.axes]
    text_positions = [(artist, artist.get_position()) for artist in fig.texts]
    new_height = old_height + CAPTION_BAND_IN
    fig.set_size_inches(old_width, new_height, forward=True)

    for ax, bbox in axes_positions:
        ax.set_position(
            [
                bbox.x0,
                (bbox.y0 * old_height + CAPTION_BAND_IN) / new_height,
                bbox.width,
                bbox.height * old_height / new_height,
            ]
        )
    for artist, (x, y) in text_positions:
        artist.set_position((x, (y * old_height + CAPTION_BAND_IN) / new_height))

    fig.text(
        0.5,
        0.5 * CAPTION_BAND_IN / new_height,
        title,
        ha="center",
        va="center",
        color=PALETTE["dark"],
        fontproperties=HEITI,
    )


def save_pdf(fig: plt.Figure, stem: str, title: str) -> None:
    add_figure_title(fig, title)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        OUT_DIR / f"{stem}.pdf",
        format="pdf",
        dpi=300,
        facecolor="white",
        metadata={"Title": stem, "Creator": "ReSETP approved figure generator"},
    )
    plt.close(fig)


def style_axes(ax: plt.Axes, *, numeric_x: bool = True, numeric_y: bool = True) -> None:
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_color(PALETTE["dark"])
        spine.set_linewidth(AXIS_WIDTH_PT)
    ax.tick_params(
        which="major",
        direction="out",
        length=2.5,
        width=AXIS_WIDTH_PT,
        colors=PALETTE["dark"],
        pad=2,
    )
    ax.tick_params(
        which="minor",
        direction="out",
        length=1.3,
        width=AXIS_WIDTH_PT,
        colors=PALETTE["dark"],
    )
    if numeric_x:
        for label in ax.get_xticklabels():
            label.set_fontproperties(EN)
    if numeric_y:
        for label in ax.get_yticklabels():
            label.set_fontproperties(EN)


def tune_legend(legend, labels: list[str]) -> None:
    legend.get_frame().set_linewidth(AXIS_WIDTH_PT)
    legend.get_frame().set_edgecolor(PALETTE["light_gray"])
    legend.get_frame().set_facecolor("white")
    for text, _label in zip(legend.get_texts(), labels):
        text.set_fontproperties(CN)


def process_box(
    ax: plt.Axes,
    center: tuple[float, float],
    width: float,
    height: float,
    text: str,
) -> Rectangle:
    x, y = center
    patch = Rectangle(
        (x - width / 2, y - height / 2),
        width,
        height,
        linewidth=FLOW_WIDTH_PT,
        edgecolor=PALETTE["dark"],
        facecolor="white",
        zorder=3,
    )
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontproperties=CN, color=PALETTE["dark"], zorder=4)
    return patch


def decision_box(
    ax: plt.Axes,
    center: tuple[float, float],
    width: float,
    height: float,
    text: str,
) -> Polygon:
    x, y = center
    patch = Polygon(
        [(x, y + height / 2), (x + width / 2, y), (x, y - height / 2), (x - width / 2, y)],
        closed=True,
        linewidth=FLOW_WIDTH_PT,
        edgecolor=PALETTE["dark"],
        facecolor="white",
        zorder=3,
    )
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontproperties=CN, color=PALETTE["dark"], zorder=4)
    return patch


def flow_arrow(ax: plt.Axes, start: tuple[float, float], end: tuple[float, float]) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=7,
            linewidth=FLOW_WIDTH_PT,
            color=PALETTE["dark"],
            shrinkA=0,
            shrinkB=0,
            zorder=2,
        )
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_algorithm_flow() -> None:
    fig, ax = plt.subplots(figsize=(4.30, 4.20))
    fig.subplots_adjust(left=0.02, right=0.98, top=0.98, bottom=0.02)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.02, 0.98, "示意/占位", transform=ax.transAxes, ha="left", va="top", color=PALETTE["gray"], fontproperties=CN)

    x_main, box_w, box_h = 0.31, 0.34, 0.075
    process_box(ax, (x_main, 0.88), box_w, box_h, "初始化")
    process_box(ax, (x_main, 0.73), box_w, box_h, "交叉")
    process_box(ax, (x_main, 0.59), box_w, box_h, "局部改进")

    group_x, group_y, group_w, group_h = 0.06, 0.285, 0.50, 0.225
    ax.add_patch(
        Rectangle(
            (group_x, group_y),
            group_w,
            group_h,
            linewidth=FLOW_WIDTH_PT,
            linestyle=(0, (5, 3)),
            edgecolor=PALETTE["dark"],
            facecolor="white",
            zorder=1,
        )
    )
    ax.text(group_x + 0.012, group_y + group_h - 0.015, "串行改进链", ha="left", va="top", fontproperties=CN, color=PALETTE["dark"], zorder=4)
    ax.text(group_x + group_w - 0.012, group_y + group_h - 0.015, "待算法定型后填", ha="right", va="top", fontproperties=CN_SMALL, color=PALETTE["gray"], zorder=4)
    process_box(ax, (x_main, 0.415), 0.29, 0.058, "问题导向算子（占位）")
    ax.text(x_main + 0.06, 0.375, "...", ha="left", va="center", fontproperties=EN, color=PALETTE["dark"], zorder=4)
    process_box(ax, (x_main, 0.335), 0.29, 0.058, "问题导向算子（占位）")
    process_box(ax, (x_main, 0.20), box_w, box_h, "完整评价")
    process_box(ax, (x_main, 0.075), box_w, box_h, "入群")
    decision_box(ax, (0.73, 0.075), 0.25, 0.12, "达到终止条件？")
    process_box(ax, (0.73, 0.31), 0.24, box_h, "结束")

    for start, end in [
        ((x_main, 0.8425), (x_main, 0.7675)),
        ((x_main, 0.6925), (x_main, 0.6275)),
        ((x_main, 0.5525), (x_main, 0.444)),
        ((x_main, 0.386), (x_main, 0.364)),
        ((x_main, 0.306), (x_main, 0.2375)),
        ((x_main, 0.1625), (x_main, 0.1125)),
        ((x_main + box_w / 2, 0.075), (0.605, 0.075)),
        ((0.73, 0.135), (0.73, 0.2725)),
    ]:
        flow_arrow(ax, start, end)
    ax.text(0.75, 0.19, "是", ha="left", va="center", fontproperties=CN, color=PALETTE["dark"])
    ax.plot([0.855, 0.94, 0.94, 0.94], [0.075, 0.075, 0.73, 0.73], color=PALETTE["dark"], linewidth=FLOW_WIDTH_PT)
    flow_arrow(ax, (0.94, 0.73), (x_main + box_w / 2, 0.73))
    ax.text(0.915, 0.41, "否", ha="center", va="center", fontproperties=CN, color=PALETTE["dark"])

    save_pdf(fig, "figure_1_algorithm_flow", "图1  本文算法流程图")


def build_algorithm_convergence() -> None:
    convergence = read_csv(
        REPO_ROOT / "solver/reports/synergy_formal_20260819/joint/seed_8/convergence.csv"
    )
    wall_seconds = np.array([float(row["wall_seconds"]) for row in convergence])
    best_cost = np.array([float(row["best_feasible_raw_cost"]) for row in convergence])

    fig, ax = plt.subplots(figsize=(4.30, 2.80))
    fig.subplots_adjust(left=0.16, right=0.97, top=0.95, bottom=0.20)
    ax.set_xlim(0, 650)
    ax.set_ylim(2950, 4100)
    ax.set_xticks([0, 100, 200, 300, 400, 500, 600])
    ax.set_yticks([3000, 3200, 3400, 3600, 3800, 4000])
    ax.set_xlabel("实际运行时间（秒）", fontproperties=CN)
    ax.set_ylabel("在案最好完整目标值（元）", fontproperties=CN)
    style_axes(ax)

    labels = ["本文算法"]
    handles = ax.plot(
        wall_seconds,
        best_cost,
        color=PALETTE["red"],
        linestyle=(0, (1, 1.8)),
        linewidth=CURVE_WIDTH_PT,
    )
    legend = ax.legend(handles, labels, loc="upper right", borderpad=0.35, handlelength=2.4, labelspacing=0.25)
    tune_legend(legend, labels)
    ax.text(0.02, 0.98, "示意/占位：探针运行", transform=ax.transAxes, ha="left", va="top", color=PALETTE["gray"], fontproperties=CN)

    save_pdf(fig, "figure_2_algorithm_convergence", "图2  不同算法迭代图")


def build_carbon_tariff_charging() -> None:
    hourly = read_csv(DATA_DIR / "figure3_hourly_source.csv")
    events = read_csv(DATA_DIR / "figure3_charging_events.csv")
    scan = read_csv(DATA_DIR / "carbon_price_scan.csv")
    if len(hourly) != 24 or len(events) != 10 or len(scan) != 6:
        raise RuntimeError("Figure 3 source counts must be 24 hourly rows, 10 events, and 6 carbon-price points")

    sample_vehicles = ["EV_B_1", "EV_B_2", "EV_B_3", "EV_B_4"]
    sample_events = [row for row in events if row["day"] == "D" and row["vehicle"] in sample_vehicles]
    if len(sample_events) != 5 or any(not row["window_start_hour"] for row in sample_events):
        raise RuntimeError("Figure 3(b) requires five registered route-day charging windows for four sample EVs")

    hours = np.arange(25, dtype=float)
    prices = np.array([float(row["场内电价_元每kWh"]) for row in hourly])
    carbon = np.array([float(row["碳强度_kgCO2e每kWh"]) for row in hourly])
    prices_step = np.r_[prices, prices[-1]]
    carbon_step = np.r_[carbon, carbon[-1]]

    # Restore the approved vertical shell at its original 4.30-inch width.
    fig = plt.figure(figsize=(4.30, 6.00))
    ax_a = fig.add_axes([0.15, 0.7500000, 0.68, 0.18])
    ax_a_carbon = ax_a.twinx()
    ax_b = fig.add_axes([0.15, 0.4250000, 0.68, 0.18])
    ax_b_carbon = ax_b.twinx()
    ax_c = fig.add_axes([0.15, 0.1000000, 0.68, 0.18])

    price_style = {
        "color": PALETTE["amber"],
        "linestyle": (0, (5, 2)),
        "linewidth": CURVE_WIDTH_PT,
    }
    carbon_style = {
        "color": PALETTE["blue"],
        "linestyle": "-",
        "linewidth": CURVE_WIDTH_PT,
    }
    ax_a.step(hours, prices_step, where="post", **price_style)
    ax_a_carbon.step(hours, carbon_step, where="post", **carbon_style)
    ax_a.set_xlim(0, 24)
    ax_a.set_ylim(0.50, 1.20)
    ax_a.set_yticks([0.6, 0.9, 1.2])
    ax_a.set_ylabel("电价（元/kWh）", fontproperties=CN)
    ax_a.set_xticks([0, 8, 16, 24])
    style_axes(ax_a)
    ax_a.tick_params(axis="x", labelbottom=False)
    ax_a_carbon.set_ylim(0.10, 0.70)
    ax_a_carbon.set_yticks([0.1, 0.4, 0.7])
    ax_a_carbon.set_ylabel("碳强度（kgCO$_2$e/kWh）", fontproperties=CN)
    style_axes(ax_a_carbon)
    labels_a = ["分时电价", "电网碳强度"]
    handles_a = [Line2D([], [], **price_style), Line2D([], [], **carbon_style)]
    legend_a = ax_a.legend(handles_a, labels_a, loc="upper right", borderpad=0.25, handlelength=1.7, labelspacing=0.20)
    tune_legend(legend_a, labels_a)

    # Liao et al. Fig. 8(c): four sample EV rows, stay/charging event bars,
    # and an event-count column on the right.  Only registered route-day
    # windows and selected charging intervals are drawn.
    y_by_vehicle = {vehicle: 4.4 - index for index, vehicle in enumerate(sample_vehicles)}
    carbon_underlay_style = {
        "color": PALETTE["light_gray"],
        "linestyle": "-",
        "linewidth": CURVE_WIDTH_PT,
    }
    carbon_underlay = ax_b_carbon.step(hours, carbon_step, where="post", zorder=0, **carbon_underlay_style)[0]
    ax_b_carbon.set_xlim(0, 24)
    ax_b_carbon.set_ylim(0.10, 1.12)
    ax_b_carbon.set_yticks([])
    ax_b_carbon.grid(False)
    for spine in ax_b_carbon.spines.values():
        spine.set_visible(False)
    ax_b_carbon.set_zorder(0)
    ax_b.set_zorder(1)
    ax_b.patch.set_alpha(0.0)
    ax_b.set_xlim(0, 24)
    ax_b.set_ylim(0.20, 10.56)
    ax_b.set_xticks([0, 8, 16, 24])
    ax_b.set_yticks([4.4, 3.4, 2.4, 1.4])
    ax_b.set_yticklabels(["B场电1", "B场电2", "B场电3", "B场电4"])
    ax_b.set_xlabel("时刻", fontproperties=CN)
    style_axes(ax_b, numeric_y=False)
    for label in ax_b.get_yticklabels():
        label.set_fontproperties(CN)
    counts = {vehicle: 0 for vehicle in sample_vehicles}
    for row in sample_events:
        window_start = float(row["window_start_hour"])
        window_end = float(row["window_end_hour"])
        start = float(row["start_hour"])
        end = float(row["end_hour"])
        y = y_by_vehicle[row["vehicle"]]
        counts[row["vehicle"]] += 1
        ax_b.add_patch(
            Rectangle(
                (window_start, y - 0.23),
                window_end - window_start,
                0.46,
                facecolor=PALETTE["purple"],
                edgecolor=PALETTE["purple"],
                linewidth=AXIS_WIDTH_PT,
                zorder=2,
            )
        )
        ax_b.add_patch(
            Rectangle(
                (start, y - 0.11),
                end - start,
                0.22,
                facecolor=PALETTE["amber"],
                edgecolor=PALETTE["amber"],
                linewidth=AXIS_WIDTH_PT,
                zorder=3,
            )
        )
    labels_b = ["可充停留", "实际充电", "电网碳强度"]
    handles_b = [
        Patch(facecolor=PALETTE["purple"], edgecolor=PALETTE["purple"], linewidth=AXIS_WIDTH_PT),
        Patch(facecolor=PALETTE["amber"], edgecolor=PALETTE["amber"], linewidth=AXIS_WIDTH_PT),
        carbon_underlay,
    ]
    legend_b = ax_b.legend(
        handles_b,
        labels_b,
        loc="upper right",
        ncol=1,
        borderpad=0.20,
        handlelength=1.1,
        columnspacing=0.7,
        labelspacing=0.15,
    )
    tune_legend(legend_b, labels_b)

    scan_x = np.array([float(row["price"]) for row in scan])
    scan_y = np.array([float(row["delta"]) for row in scan])
    scan_line = ax_c.step(scan_x, scan_y, where="post", color=PALETTE["green"], linestyle="-", linewidth=CURVE_WIDTH_PT, label="碳感知－有空即充")[0]
    ax_c.axhline(0, color=PALETTE["gray"], linestyle="-", linewidth=AXIS_WIDTH_PT)
    ax_c.axvline(0.4489498210731408, color=PALETTE["gray"], linestyle=(0, (5, 2)), linewidth=AXIS_WIDTH_PT)
    ax_c.text(0.49, -104, "翻转点0.449", rotation=90, ha="left", va="bottom", color=PALETTE["gray"], fontproperties=CN)
    ax_c.set_xlim(0, 2.2)
    ax_c.set_ylim(-110, 30)
    ax_c.set_xticks([0, 0.6, 1.2, 1.8])
    ax_c.set_yticks([-100, -75, -50, -25, 0, 25])
    ax_c.set_xlabel("碳价（元/kgCO$_2$e）", fontproperties=CN)
    ax_c.set_ylabel("完整目标变化（元）", fontproperties=CN)
    style_axes(ax_c)
    labels_c = ["碳感知－有空即充"]
    legend_c = ax_c.legend([scan_line], labels_c, loc="upper right", borderpad=0.25, handlelength=1.7, labelspacing=0.20)
    tune_legend(legend_c, labels_c)

    fig.text(0.49, 0.6533333, "(a)", ha="center", va="center", fontproperties=EN)
    fig.text(0.49, 0.3283333, "(b)", ha="center", va="center", fontproperties=EN)
    fig.text(0.49, 0.0033333, "(c)", ha="center", va="center", fontproperties=EN)
    save_pdf(fig, "figure_3_carbon_tariff_charging", "图3  电网碳强度、分时电价与充电负荷图")


def build_mixed_fleet() -> None:
    fig, ax = plt.subplots(figsize=(4.30, 2.80))
    fig.subplots_adjust(left=0.16, right=0.97, top=0.95, bottom=0.20)
    ax.set_xlim(0, 2.5)
    ax.set_ylim(0, 20)
    ax.set_xticks([0, 0.5, 1.0, 1.5, 2.0, 2.5])
    ax.set_yticks([0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20])
    ax.set_xlabel("单位碳价（元/千克二氧化碳当量）", fontproperties=CN)
    ax.set_ylabel("车辆数（辆）", fontproperties=CN)
    style_axes(ax)
    labels = ["燃油车", "电动车"]
    handles = [
        Line2D([], [], color=PALETTE["blue"], linestyle="-", linewidth=CURVE_WIDTH_PT, marker="o", markersize=3.0, markerfacecolor="white", markeredgewidth=AXIS_WIDTH_PT, label="燃油车"),
        Line2D([], [], color=PALETTE["red"], linestyle="--", linewidth=CURVE_WIDTH_PT, marker="^", markersize=3.2, markerfacecolor="white", markeredgewidth=AXIS_WIDTH_PT, label="电动车"),
    ]
    legend = ax.legend(handles, labels, loc="upper right", borderpad=0.35, handlelength=2.4, labelspacing=0.25)
    tune_legend(legend, labels)
    ax.axvline(0.4489498210731408, color=PALETTE["gray"], linestyle=(0, (5, 2)), linewidth=AXIS_WIDTH_PT)
    ax.text(0.49, 0.8, "充电时移阈值（见图3）", rotation=90, ha="left", va="bottom", color=PALETTE["gray"], fontproperties=CN)
    ax.text(1.25, 10.0, "燃油车／电动车折线数据待补", ha="center", va="center", color=PALETTE["gray"], fontproperties=CN)
    save_pdf(fig, "figure_4_mixed_fleet", "图4  不同碳价下混合车队车辆数图")


def load_route_nodes() -> dict[str, dict[str, float | str]]:
    nodes: dict[str, dict[str, float | str]] = {}
    for row in read_csv(NODE_SOURCE):
        if row["记录类型"] != "节点" or row["节点类型"] not in {"customer", "depot"}:
            continue
        nodes[row["节点ID"]] = {
            "kind": row["节点类型"],
            "lat": float(row["纬度"]),
            "lon": float(row["经度"]),
            "enterprise": row["所属企业"],
        }
    if sum(node["kind"] == "customer" for node in nodes.values()) != 50 or sum(node["kind"] == "depot" for node in nodes.values()) != 2:
        raise RuntimeError("Route source must contain exactly 50 customers and 2 depots")
    lat0, lon0 = 39.89502235, 116.33687655
    for node in nodes.values():
        node["x"] = (float(node["lon"]) - lon0) * 111.32 * math.cos(math.radians(lat0))
        node["y"] = (float(node["lat"]) - lat0) * 110.57
    return nodes


def load_route_sequences(path: Path) -> list[tuple[str, list[str]]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return [
        (route["home_depot_id"], route["node_sequence"])
        for route in payload["evaluation"]["prepared_solution"]["routes"]
    ]


def draw_route_axes(
    ax: plt.Axes,
    nodes: dict[str, dict[str, float | str]],
    routes: list[tuple[str, list[str]]],
    *,
    blank_note: str | None = None,
) -> None:
    depot_colors = {
        "D_OSM_WAY_1003511503": PALETTE["blue"],
        "D_OSM_WAY_1071205721": PALETTE["amber"],
    }
    depot_styles = {
        "D_OSM_WAY_1003511503": "-",
        "D_OSM_WAY_1071205721": (0, (5, 2)),
    }
    for depot_id, sequence in routes:
        color = depot_colors[depot_id]
        for start_id, end_id in zip(sequence, sequence[1:]):
            start, end = nodes[start_id], nodes[end_id]
            ax.add_patch(
                FancyArrowPatch(
                    (float(start["x"]), float(start["y"])),
                    (float(end["x"]), float(end["y"])),
                    arrowstyle="-|>",
                    mutation_scale=7,
                    linewidth=FLOW_WIDTH_PT,
                    linestyle=depot_styles[depot_id],
                    color=color,
                    shrinkA=1.5,
                    shrinkB=1.5,
                    zorder=1,
                )
            )

    for node_id, node in nodes.items():
        x, y = float(node["x"]), float(node["y"])
        if node["kind"] == "customer":
            ax.plot(x, y, marker="o", markersize=MARKER_SIZE_PT, markerfacecolor="white", markeredgecolor=PALETTE["dark"], markeredgewidth=AXIS_WIDTH_PT, linestyle="none", zorder=3)
            ax.text(x, y, node_id[1:], ha="center", va="bottom", color=PALETTE["dark"], fontproperties=EN, zorder=4)
        else:
            color = depot_colors[node_id]
            ax.plot(x, y, marker="*", markersize=MARKER_SIZE_PT, markerfacecolor=color, markeredgecolor=color, markeredgewidth=AXIS_WIDTH_PT, linestyle="none", zorder=5)
            ax.text(x, y, "A场" if node["enterprise"] == "ENT_A" else "B场", ha="left", va="bottom", color=color, fontproperties=CN, zorder=5)

    if blank_note:
        ax.text(0, 0, blank_note, ha="center", va="center", color=PALETTE["gray"], fontproperties=CN, zorder=6)
    ax.set_xlim(-36, 36)
    ax.set_ylim(-27, 27)
    ax.set_xticks([-30, -15, 0, 15, 30])
    ax.set_yticks([-20, -10, 0, 10, 20])
    ax.set_xlabel("横向距离（千米，中心等距近似投影）", fontproperties=CN)
    ax.set_ylabel("纵向距离（千米）", fontproperties=CN)
    ax.set_aspect("equal", adjustable="box")
    style_axes(ax)


def build_route_figure(
    stem: str,
    title: str,
    left_label: str,
    right_label: str,
    left_routes: list[tuple[str, list[str]]],
    right_routes: list[tuple[str, list[str]]],
    *,
    right_blank_note: str | None = None,
) -> None:
    nodes = load_route_nodes()
    for _depot, sequence in left_routes + right_routes:
        missing = [node_id for node_id in sequence if node_id not in nodes]
        if missing:
            raise RuntimeError(f"Route contains nodes absent from source: {missing}")
    fig, axes = plt.subplots(1, 2, figsize=(4.30, 2.80), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.12, right=0.98, top=0.95, bottom=0.24, wspace=0.34)
    draw_route_axes(axes[0], nodes, left_routes)
    draw_route_axes(axes[1], nodes, right_routes, blank_note=right_blank_note)
    axes[1].set_ylabel("")
    fig.text(0.255, 0.13, "(a)", ha="right", va="center", fontproperties=EN)
    fig.text(0.265, 0.13, left_label, ha="left", va="center", fontproperties=CN)
    fig.text(0.735, 0.13, "(b)", ha="right", va="center", fontproperties=EN)
    fig.text(0.745, 0.13, right_label, ha="left", va="center", fontproperties=CN)
    save_pdf(fig, stem, title)


def build_routes() -> None:
    standalone = load_route_sequences(STANDALONE_A) + load_route_sequences(STANDALONE_B)
    joint = load_route_sequences(JOINT)
    build_route_figure(
        "figure_5_standalone_joint_routes",
        "图5  独立配送与联合配送最终路径图",
        "各场单干",
        "联合",
        standalone,
        joint,
    )
    build_route_figure(
        "figure_6_fair_routes",
        "图6  成本最优与全员不劣最终路径图（待定）",
        "成本最优",
        "全员不劣",
        joint,
        [],
        right_blank_note="全员不劣路线待补",
    )


def main() -> None:
    build_algorithm_flow()
    build_algorithm_convergence()
    build_carbon_tariff_charging()
    build_mixed_fleet()


if __name__ == "__main__":
    main()
