from __future__ import annotations

from pathlib import Path
import tempfile

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, Polygon, Rectangle
import numpy as np
from fontTools.ttLib import TTCollection


OUT_DIR = Path(__file__).resolve().parent

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
FONT_TEMP_DIR = tempfile.TemporaryDirectory(prefix="resetp_figshell_font_")


def regular_songti_path() -> Path:
    """Extract the regular face: Matplotlib otherwise selects face 0 (Black) in Songti.ttc."""
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


SONGTI_REGULAR = regular_songti_path()
CN = font_manager.FontProperties(fname=SONGTI_REGULAR, size=TEXT_SIZE_PT)
CN_SMALL = font_manager.FontProperties(fname=SONGTI_REGULAR, size=TEXT_SIZE_PT)
EN = font_manager.FontProperties(family="Times New Roman", size=TEXT_SIZE_PT)
EN_SMALL = font_manager.FontProperties(family="Times New Roman", size=TEXT_SIZE_PT)
HEITI = font_manager.FontProperties(fname="/System/Library/Fonts/STHeiti Medium.ttc", size=9.0)
CAPTION_BAND_IN = 0.28


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
    """Add a caption band without resizing or redrawing the existing figure area."""
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


def save_pair(fig: plt.Figure, stem: str, title: str | None = None) -> None:
    if title is not None:
        add_figure_title(fig, title)
    pdf_path = OUT_DIR / f"{stem}.pdf"
    png_path = OUT_DIR / f"{stem}.png"
    fig.savefig(
        pdf_path,
        format="pdf",
        dpi=300,
        facecolor="white",
        metadata={"Title": stem, "Creator": "ReSETP figure-shell generator"},
    )
    fig.savefig(png_path, format="png", dpi=300, facecolor="white")
    plt.close(fig)


def status_label(target, *, x: float = 0.02, y: float = 0.98, transform=None) -> None:
    if transform is None:
        transform = target.transAxes
    target.text(
        x,
        y,
        "示意/占位",
        transform=transform,
        ha="left",
        va="top",
        color=PALETTE["gray"],
        fontproperties=CN,
        zorder=30,
    )


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


def tune_legend(legend, labels: list[str], chinese_labels: set[str] | None = None) -> None:
    chinese_labels = chinese_labels or set()
    legend.get_frame().set_linewidth(AXIS_WIDTH_PT)
    legend.get_frame().set_edgecolor(PALETTE["light_gray"])
    legend.get_frame().set_facecolor("white")
    for text, label in zip(legend.get_texts(), labels):
        text.set_fontproperties(CN if label in chinese_labels else EN)


def process_box(ax: plt.Axes, center: tuple[float, float], width: float, height: float, text: str) -> Rectangle:
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


def decision_box(ax: plt.Axes, center: tuple[float, float], width: float, height: float, text: str) -> Polygon:
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


def arrow(ax: plt.Axes, start: tuple[float, float], end: tuple[float, float]) -> None:
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


def build_algorithm_flow() -> None:
    fig, ax = plt.subplots(figsize=(4.30, 4.20))
    fig.subplots_adjust(left=0.02, right=0.98, top=0.98, bottom=0.02)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    status_label(ax)

    x_main = 0.31
    box_w = 0.34
    box_h = 0.075
    process_box(ax, (x_main, 0.88), box_w, box_h, "初始化")
    process_box(ax, (x_main, 0.73), box_w, box_h, "交叉")
    process_box(ax, (x_main, 0.59), box_w, box_h, "局部改进")

    group_x, group_y, group_w, group_h = 0.06, 0.285, 0.50, 0.225
    group = Rectangle(
        (group_x, group_y),
        group_w,
        group_h,
        linewidth=FLOW_WIDTH_PT,
        linestyle=(0, (5, 3)),
        edgecolor=PALETTE["dark"],
        facecolor="white",
        zorder=1,
    )
    ax.add_patch(group)
    ax.text(
        group_x + 0.012,
        group_y + group_h - 0.015,
        "串行改进链",
        ha="left",
        va="top",
        fontproperties=CN,
        color=PALETTE["dark"],
        zorder=4,
    )
    ax.text(
        group_x + group_w - 0.012,
        group_y + group_h - 0.015,
        "待算法定型后填",
        ha="right",
        va="top",
        fontproperties=CN_SMALL,
        color=PALETTE["gray"],
        zorder=4,
    )
    process_box(ax, (x_main, 0.415), 0.29, 0.058, "问题导向算子（占位）")
    ax.text(
        x_main + 0.06,
        0.375,
        "...",
        ha="left",
        va="center",
        fontproperties=EN_SMALL,
        color=PALETTE["dark"],
        zorder=4,
    )
    process_box(ax, (x_main, 0.335), 0.29, 0.058, "问题导向算子（占位）")
    process_box(ax, (x_main, 0.20), box_w, box_h, "完整评价")
    process_box(ax, (x_main, 0.075), box_w, box_h, "入群")

    decision_box(ax, (0.73, 0.075), 0.25, 0.12, "达到终止条件？")
    process_box(ax, (0.73, 0.31), 0.24, box_h, "结束")

    arrow(ax, (x_main, 0.8425), (x_main, 0.7675))
    arrow(ax, (x_main, 0.6925), (x_main, 0.6275))
    arrow(ax, (x_main, 0.5525), (x_main, 0.444))
    arrow(ax, (x_main, 0.386), (x_main, 0.364))
    arrow(ax, (x_main, 0.306), (x_main, 0.2375))
    arrow(ax, (x_main, 0.1625), (x_main, 0.1125))
    arrow(ax, (x_main + box_w / 2, 0.075), (0.605, 0.075))
    arrow(ax, (0.73, 0.135), (0.73, 0.2725))
    ax.text(0.75, 0.19, "是", ha="left", va="center", fontproperties=CN, color=PALETTE["dark"])

    # “否”分支返回交叉，采用母版同类的直角外循环。
    ax.plot([0.855, 0.94, 0.94, 0.94], [0.075, 0.075, 0.73, 0.73], color=PALETTE["dark"], linewidth=FLOW_WIDTH_PT)
    arrow(ax, (0.94, 0.73), (x_main + box_w / 2, 0.73))
    ax.text(0.915, 0.41, "否", ha="center", va="center", fontproperties=CN, color=PALETTE["dark"])

    save_pair(fig, "figure_1_algorithm_flow_shell", "图1  本文算法流程图（示意／占位）")


def build_algorithm_convergence() -> None:
    fig, ax = plt.subplots(figsize=(4.30, 2.80))
    fig.subplots_adjust(left=0.16, right=0.97, top=0.95, bottom=0.20)
    style_axes(ax)
    status_label(fig, x=0.78, y=0.985, transform=fig.transFigure)

    x = np.array([0.00, 0.04, 0.08, 0.13, 0.19, 0.27, 0.36, 0.48, 0.62, 0.78, 1.00])
    curves = [
        np.array([6250, 5350, 4950, 4620, 4380, 4170, 4020, 3920, 3860, 3830, 3820]),
        np.array([6300, 5200, 4720, 4300, 4040, 3890, 3800, 3740, 3715, 3705, 3700]),
        np.array([6100, 5050, 4550, 4190, 3910, 3750, 3660, 3610, 3575, 3560, 3555]),
        np.array([6200, 4920, 4310, 3970, 3750, 3600, 3500, 3440, 3405, 3395, 3390]),
    ]
    labels = ["VCGP", "MDFIHA", "MDFIHA-ETGA", "本文算法"]
    styles = [
        (PALETTE["blue"], "-"),
        (PALETTE["green"], (0, (5, 2))),
        (PALETTE["amber"], (0, (5, 2, 1.3, 2))),
        (PALETTE["red"], (0, (1, 1.8))),
    ]
    for values, label, (color, linestyle) in zip(curves, labels, styles):
        ax.plot(
            x,
            values,
            label=label,
            color=color,
            linestyle=linestyle,
            linewidth=CURVE_WIDTH_PT,
            drawstyle="steps-post",
        )

    ax.set_xlim(0, 1)
    ax.set_ylim(3250, 6500)
    ax.set_xticks([0, 0.25, 0.50, 0.75, 1.00])
    ax.set_xticklabels(["0", "T/4", "T/2", "3T/4", "T"])
    ax.set_yticks([3500, 4000, 4500, 5000, 5500, 6000, 6500])
    ax.set_xlabel("实际运行时间（秒）", fontproperties=CN)
    ax.set_ylabel("在职最好完整目标值（元）", fontproperties=CN)
    style_axes(ax)
    legend = ax.legend(loc="upper right", borderpad=0.35, handlelength=2.4, labelspacing=0.25)
    tune_legend(legend, labels, chinese_labels={"本文算法"})

    save_pair(fig, "figure_2a_algorithm_convergence_shell", "图2  不同算法迭代图（示意／占位）")


def build_budget_calibration() -> None:
    fig, ax = plt.subplots(figsize=(4.30, 2.80))
    fig.subplots_adjust(left=0.16, right=0.97, top=0.95, bottom=0.20)
    style_axes(ax)
    status_label(fig, x=0.78, y=0.985, transform=fig.transFigure)

    x = np.array([0.00, 0.04, 0.08, 0.12, 0.18, 0.25, 0.33, 0.42, 0.50, 0.56, 0.64, 0.74, 0.84, 0.92, 1.00])
    y = np.array([6200, 5150, 4580, 4210, 3890, 3660, 3490, 3370, 3305, 3280, 3265, 3255, 3252, 3251, 3250])
    label = "本文算法（名称待定）"
    ax.plot(
        x,
        y,
        color=PALETTE["red"],
        linestyle="-",
        linewidth=CURVE_WIDTH_PT,
        drawstyle="steps-post",
        label=label,
    )

    plateau_x = 0.56
    budget_x = 0.74
    plateau_y = y[np.where(x == plateau_x)[0][0]]
    budget_y = y[np.where(x == budget_x)[0][0]]
    ax.axvline(plateau_x, color=PALETTE["gray"], linestyle=(0, (5, 2, 1.3, 2)), linewidth=AXIS_WIDTH_PT)
    ax.axvline(budget_x, color=PALETTE["red"], linestyle=(0, (5, 2)), linewidth=AXIS_WIDTH_PT)
    ax.plot(
        [plateau_x],
        [plateau_y],
        marker="s",
        markersize=3.0,
        markerfacecolor="white",
        markeredgecolor=PALETTE["dark"],
        markeredgewidth=AXIS_WIDTH_PT,
        linestyle="none",
        zorder=5,
    )
    ax.annotate(
        "进入平台期的点",
        xy=(plateau_x, plateau_y),
        xytext=(0.34, 3650),
        textcoords="data",
        ha="center",
        va="center",
        fontproperties=CN,
        arrowprops={"arrowstyle": "->", "linewidth": AXIS_WIDTH_PT, "color": PALETTE["dark"]},
    )
    ax.annotate(
        "所取预算",
        xy=(budget_x, budget_y),
        xytext=(0.80, 3970),
        textcoords="data",
        ha="center",
        va="center",
        fontproperties=CN,
        color=PALETTE["red"],
        arrowprops={"arrowstyle": "->", "linewidth": AXIS_WIDTH_PT, "color": PALETTE["red"]},
    )

    ax.set_xlim(0, 1)
    ax.set_ylim(3100, 6500)
    ax.set_xticks([0, plateau_x, budget_x, 1.00])
    ax.set_xticklabels(["0", "t_p", "t_b", "T"])
    ax.set_yticks([3500, 4000, 4500, 5000, 5500, 6000, 6500])
    ax.set_xlabel("实际运行时间（秒）", fontproperties=CN)
    ax.set_ylabel("在职最好完整目标值（元）", fontproperties=CN)
    style_axes(ax)
    legend = ax.legend(loc="upper right", borderpad=0.35, handlelength=2.4, labelspacing=0.25)
    tune_legend(legend, [label], chinese_labels={label})

    save_pair(fig, "figure_2b_budget_calibration_shell")


def build_carbon_tariff_charging() -> None:
    fig = plt.figure(figsize=(4.30, 4.25))
    top = fig.add_axes([0.15, 0.61, 0.68, 0.30])
    top_price = top.twinx()
    bottom = fig.add_axes([0.15, 0.18, 0.68, 0.29])

    status_label(fig, x=0.02, y=0.985, transform=fig.transFigure)

    # 24个示意逐小时值；每个值严格复制到两个30分钟槽。
    carbon_hourly = np.array(
        [
            0.58,
            0.56,
            0.54,
            0.52,
            0.50,
            0.48,
            0.45,
            0.41,
            0.36,
            0.31,
            0.27,
            0.23,
            0.20,
            0.22,
            0.26,
            0.31,
            0.38,
            0.45,
            0.51,
            0.55,
            0.57,
            0.60,
            0.61,
            0.59,
        ]
    )
    carbon_48 = np.repeat(carbon_hourly, 2)
    slot_edges = np.arange(49)
    top.step(
        slot_edges,
        np.r_[carbon_48, carbon_48[-1]],
        where="post",
        color=PALETTE["blue"],
        linestyle="-",
        linewidth=CURVE_WIDTH_PT,
        label="电网碳强度（逐小时）",
    )

    # 四级占位序列覆盖“谷/平/峰”和石家庄额外“尖峰”的最复杂壳。
    tariff = np.zeros(48, dtype=float)
    tariff[0:14] = 0
    tariff[14:22] = 1
    tariff[22:30] = 0
    tariff[30:36] = 1
    tariff[36:42] = 3
    tariff[42:46] = 2
    tariff[46:48] = 1
    top_price.step(
        slot_edges,
        np.r_[tariff, tariff[-1]],
        where="post",
        color=PALETTE["amber"],
        linestyle=(0, (5, 2)),
        linewidth=CURVE_WIDTH_PT,
        label="分时电价类别",
    )

    top.set_xlim(0, 48)
    top.set_ylim(0.15, 0.85)
    top.set_yticks([0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    top.set_ylabel("电网碳强度\n（千克二氧化碳当量/千瓦时）", fontproperties=CN)
    top.set_xticks(np.arange(0, 49, 8))
    top.set_xticklabels([])
    top.set_xticks(np.arange(0, 49, 1), minor=True)
    style_axes(top, numeric_x=False, numeric_y=True)

    top_price.set_ylim(-0.25, 5.0)
    top_price.set_yticks([0, 1, 2, 3])
    top_price.set_yticklabels(["谷", "平", "峰", "尖峰"])
    top_price.set_ylabel("分时电价类别", fontproperties=CN)
    top_price.grid(False)
    top_price.spines["right"].set_color(PALETTE["dark"])
    top_price.spines["right"].set_linewidth(AXIS_WIDTH_PT)
    top_price.spines["left"].set_visible(False)
    top_price.spines["top"].set_visible(False)
    top_price.spines["bottom"].set_visible(False)
    top_price.tick_params(axis="y", direction="out", length=2.5, width=AXIS_WIDTH_PT, pad=2)
    for label in top_price.get_yticklabels():
        label.set_fontproperties(CN)

    handles_1, labels_1 = top.get_legend_handles_labels()
    handles_2, labels_2 = top_price.get_legend_handles_labels()
    legend_top = top.legend(
        handles_1 + handles_2,
        labels_1 + labels_2,
        loc="upper right",
        borderpad=0.35,
        handlelength=2.4,
        labelspacing=0.25,
    )
    tune_legend(legend_top, labels_1 + labels_2, chinese_labels=set(labels_1 + labels_2))

    top.annotate(
        "每小时值复制到\n两个半小时槽",
        xy=(10.8, carbon_48[10]),
        xytext=(1.5, 0.79),
        ha="left",
        va="center",
        fontproperties=CN_SMALL,
        color=PALETTE["dark"],
        arrowprops={"arrowstyle": "->", "linewidth": AXIS_WIDTH_PT, "color": PALETTE["dark"]},
    )

    load_asap = np.zeros(48)
    load_price = np.zeros(48)
    load_carbon = np.zeros(48)
    load_asap[33:41] = [2.5, 5.0, 8.0, 10.0, 9.5, 7.0, 4.5, 2.0]
    load_price[0:7] = [3.0, 5.5, 8.0, 9.0, 8.0, 5.0, 2.5]
    load_price[22:26] = [2.0, 3.5, 3.5, 2.0]
    load_carbon[21:29] = [1.5, 4.0, 7.0, 9.5, 10.0, 8.0, 5.0, 2.0]

    load_specs = [
        (load_asap, "有空即充", PALETTE["red"], "-"),
        (load_price, "电费最省", PALETTE["blue"], (0, (5, 2))),
        (load_carbon, "碳感知", PALETTE["green"], (0, (5, 2, 1.3, 2))),
    ]
    for values, label, color, linestyle in load_specs:
        bottom.step(
            slot_edges,
            np.r_[values, values[-1]],
            where="post",
            color=color,
            linestyle=linestyle,
            linewidth=CURVE_WIDTH_PT,
            label=label,
        )

    bottom.set_xlim(0, 48)
    bottom.set_ylim(0, 14)
    bottom.set_yticks([0, 2, 4, 6, 8, 10, 12, 14])
    bottom.set_xticks(np.arange(0, 49, 8))
    bottom.set_xticklabels(["00:00", "04:00", "08:00", "12:00", "16:00", "20:00", "24:00"])
    bottom.set_xticks(np.arange(0, 49, 1), minor=True)
    bottom.set_xlabel("时刻", fontproperties=CN)
    bottom.set_ylabel("半小时汇总充电负荷（千瓦时）", fontproperties=CN)
    style_axes(bottom)
    labels_bottom = [spec[1] for spec in load_specs]
    legend_bottom = bottom.legend(loc="upper right", borderpad=0.35, handlelength=2.4, labelspacing=0.25)
    tune_legend(legend_bottom, labels_bottom, chinese_labels=set(labels_bottom))

    fig.text(0.49, 0.535, "(a)", ha="center", va="center", fontproperties=EN)
    fig.text(0.49, 0.055, "(b)", ha="center", va="center", fontproperties=EN)

    save_pair(
        fig,
        "figure_3_carbon_tariff_charging_shell",
        "图3  电网碳强度、分时电价与充电负荷图（示意／占位）",
    )


def main() -> None:
    build_algorithm_flow()
    build_algorithm_convergence()
    build_budget_calibration()
    build_carbon_tariff_charging()


if __name__ == "__main__":
    main()
