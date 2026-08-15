from __future__ import annotations

from pathlib import Path
import tempfile

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from fontTools.ttLib import TTCollection
import numpy as np


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
TEXT_SIZE_PT = 8.0
FIGSIZE_IN = (16.4 / 2.54, 7.2 / 2.54)
FONT_TEMP_DIR = tempfile.TemporaryDirectory(prefix="resetp_fleetfig_font_")


def regular_songti_path() -> Path:
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
    raise RuntimeError("Songti SC Regular face not found")


SONGTI_REGULAR = regular_songti_path()
CN = font_manager.FontProperties(fname=SONGTI_REGULAR, size=TEXT_SIZE_PT)
EN = font_manager.FontProperties(family="Times New Roman", size=TEXT_SIZE_PT)
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
    }
)


def style_axes(ax: plt.Axes) -> None:
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(True)
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
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(EN)


def set_cn_label(ax: plt.Axes, axis: str, text: str) -> None:
    if axis == "x":
        ax.set_xlabel(text, fontproperties=CN)
    else:
        ax.set_ylabel(text, fontproperties=CN)


def tune_legend(legend) -> None:
    legend.get_frame().set_linewidth(AXIS_WIDTH_PT)
    for item in legend.get_texts():
        item.set_fontproperties(CN)


def placeholder_stamp(fig: plt.Figure) -> None:
    fig.text(
        0.5,
        0.985,
        "示意／占位",
        ha="center",
        va="top",
        color=PALETTE["gray"],
        fontproperties=CN,
    )


def panel_letter(ax: plt.Axes, letter: str) -> None:
    ax.text(
        0.5,
        -0.28,
        f"({letter})",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontproperties=EN,
        color=PALETTE["dark"],
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


def save_pair(fig: plt.Figure, stem: str, title: str) -> None:
    add_figure_title(fig, title)
    fig.savefig(
        OUT_DIR / f"{stem}.pdf",
        format="pdf",
        dpi=300,
        facecolor="white",
        metadata={"Title": stem, "Creator": "ReSETP fleet figure placeholder generator"},
    )
    fig.savefig(OUT_DIR / f"{stem}.png", format="png", dpi=300, facecolor="white")
    plt.close(fig)


def build_candidate_a() -> None:
    """Three separated line panels following Li et al. Fig. 6."""
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=FIGSIZE_IN)
    fig.subplots_adjust(left=0.075, right=0.975, bottom=0.23, top=0.89, wspace=0.42)
    placeholder_stamp(fig)

    distance = np.array([50.0, 68.1, 86.8, 125.5, 145.0])
    fuel = np.array([980, 1040, 1120, 1290, 1420])
    electric = np.array([1180, 1110, 1050, 960, 930])
    ax1.plot(
        distance,
        fuel,
        color=PALETTE["blue"],
        linestyle="-",
        marker="o",
        markersize=3.0,
        markerfacecolor="white",
        markeredgewidth=AXIS_WIDTH_PT,
        label="燃油车",
    )
    ax1.plot(
        distance,
        electric,
        color=PALETTE["red"],
        linestyle="--",
        marker="^",
        markersize=3.2,
        markerfacecolor="white",
        markeredgewidth=AXIS_WIDTH_PT,
        label="电动车",
    )
    ax1.set_xticks([68.1, 86.8, 125.5])
    ax1.set_xlim(45, 150)
    ax1.set_ylim(850, 1500)
    set_cn_label(ax1, "x", "日里程（km）")
    set_cn_label(ax1, "y", "单目标总账（元）")
    style_axes(ax1)
    tune_legend(ax1.legend(loc="upper right", borderpad=0.35, handlelength=2.0))
    panel_letter(ax1, "a")

    share = np.array([0, 25, 50, 75, 100])
    charging = np.array([0, 18, 39, 61, 82])
    ax2.plot(
        share,
        charging,
        color=PALETTE["purple"],
        linestyle="-",
        marker="s",
        markersize=3.0,
        markerfacecolor="white",
        markeredgewidth=AXIS_WIDTH_PT,
        label="充电占比",
    )
    ax2.set_xticks(share)
    ax2.set_xlim(-3, 103)
    ax2.set_ylim(0, 100)
    set_cn_label(ax2, "x", "电动化比例（%）")
    set_cn_label(ax2, "y", "充电占比（%）")
    style_axes(ax2)
    tune_legend(ax2.legend(loc="upper right", borderpad=0.35, handlelength=2.0))
    panel_letter(ax2, "b")

    asap = np.array([128, 119, 108, 96, 87])
    aware = np.array([128, 116, 101, 85, 72])
    ax3.plot(
        share,
        asap,
        color=PALETTE["amber"],
        linestyle="-",
        marker="o",
        markersize=3.0,
        markerfacecolor="white",
        markeredgewidth=AXIS_WIDTH_PT,
        label="有空即充",
    )
    ax3.plot(
        share,
        aware,
        color=PALETTE["green"],
        linestyle="--",
        marker="^",
        markersize=3.2,
        markerfacecolor="white",
        markeredgewidth=AXIS_WIDTH_PT,
        label="碳感知",
    )
    ax3.set_xticks(share)
    ax3.set_xlim(-3, 103)
    ax3.set_ylim(65, 135)
    set_cn_label(ax3, "x", "电动化比例（%）")
    set_cn_label(ax3, "y", "配送作业阶段总排放（kgCO2e）")
    style_axes(ax3)
    tune_legend(ax3.legend(loc="upper right", borderpad=0.35, handlelength=2.0))
    panel_letter(ax3, "c")
    save_pair(
        fig,
        "candidate_a_line_panels_placeholder",
        "图5  日里程、电动化比例与混合车队结果（示意／占位）",
    )


def build_candidate_b() -> None:
    """Two bar-line panels following Qiu et al. Fig. 4."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=FIGSIZE_IN)
    fig.subplots_adjust(left=0.105, right=0.90, bottom=0.27, top=0.89, wspace=0.52)
    placeholder_stamp(fig)

    premium_labels = ["13", "25", "47", "50"]
    x1 = np.arange(len(premium_labels))
    ev_count = np.array([6, 5, 3, 2])
    cv_count = np.array([2, 3, 5, 6])
    ax1r = ax1.twinx()
    ax1r.bar(
        x1,
        cv_count,
        width=0.56,
        color=PALETTE["blue"],
        edgecolor=PALETTE["dark"],
        linewidth=AXIS_WIDTH_PT,
        label="燃油车",
        zorder=1,
    )
    ax1r.bar(
        x1,
        ev_count,
        bottom=cv_count,
        width=0.56,
        color=PALETTE["red"],
        hatch="///",
        edgecolor=PALETTE["dark"],
        linewidth=AXIS_WIDTH_PT,
        label="电动车",
        zorder=1,
    )
    total_account = np.array([970, 1015, 1100, 1140])
    ax1.plot(
        x1,
        total_account,
        color=PALETTE["green"],
        marker="o",
        markersize=3.0,
        markerfacecolor="white",
        markeredgewidth=AXIS_WIDTH_PT,
        label="单目标总账",
        zorder=3,
    )
    ax1.set_xticks(x1, premium_labels)
    ax1.set_xlim(-0.5, 7.5)
    ax1.set_ylim(650, 1250)
    ax1r.set_ylim(0, 10)
    set_cn_label(ax1, "x", "电动车固定成本溢价（元／车日）")
    set_cn_label(ax1, "y", "单目标总账（元）")
    set_cn_label(ax1r, "y", "实际派遣车辆数（辆）")
    style_axes(ax1)
    style_axes(ax1r)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax1r.get_legend_handles_labels()
    tune_legend(
        ax1.legend(
            h2 + h1,
            l2 + l1,
            loc="upper right",
            ncol=1,
            borderpad=0.3,
            columnspacing=0.7,
            handlelength=1.6,
        )
    )
    fig.text(0.302, 0.035, "(a)", ha="center", va="bottom", fontproperties=EN)

    share = np.array([0, 25, 50, 75, 100])
    x2 = np.arange(len(share))
    ax2r = ax2.twinx()
    charging_share = np.array([0, 17, 38, 60, 82])
    ax2r.bar(
        x2,
        charging_share,
        width=0.54,
        color=PALETTE["red"],
        hatch="///",
        edgecolor=PALETTE["dark"],
        linewidth=AXIS_WIDTH_PT,
        label="充电占比",
        zorder=1,
    )
    asap = np.array([128, 119, 108, 96, 87])
    aware = np.array([128, 116, 101, 85, 72])
    ax2.plot(
        x2,
        asap,
        color=PALETTE["amber"],
        marker="o",
        markersize=3.0,
        markerfacecolor="white",
        markeredgewidth=AXIS_WIDTH_PT,
        label="有空即充",
        zorder=3,
    )
    ax2.plot(
        x2,
        aware,
        color=PALETTE["green"],
        linestyle="--",
        marker="^",
        markersize=3.2,
        markerfacecolor="white",
        markeredgewidth=AXIS_WIDTH_PT,
        label="碳感知",
        zorder=3,
    )
    ax2.set_xticks(x2, [str(v) for v in share])
    ax2.set_xlim(-0.5, 7.5)
    ax2.set_ylim(65, 135)
    ax2r.set_ylim(0, 100)
    set_cn_label(ax2, "x", "电动化比例（%）")
    set_cn_label(ax2, "y", "配送作业阶段总排放（kgCO2e）")
    set_cn_label(ax2r, "y", "充电占比（%）")
    style_axes(ax2)
    style_axes(ax2r)
    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax2r.get_legend_handles_labels()
    tune_legend(
        ax2.legend(
            h2 + h1,
            l2 + l1,
            loc="upper right",
            borderpad=0.3,
            handlelength=1.7,
        )
    )
    fig.text(0.715, 0.035, "(b)", ha="center", va="bottom", fontproperties=EN)
    save_pair(
        fig,
        "candidate_b_bar_line_panels_placeholder",
        "图5  固定成本溢价、电动化比例与混合车队结果（示意／占位）",
    )


def main() -> None:
    build_candidate_a()
    build_candidate_b()


if __name__ == "__main__":
    main()
