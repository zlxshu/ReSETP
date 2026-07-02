from __future__ import annotations

import importlib
from pathlib import Path
import sys


PALETTE = {
    "blue": "#0072B2",
    "green": "#009E73",
    "red": "#D55E00",
    "amber": "#E69F00",
    "purple": "#CC79A7",
    "sky": "#56B4E9",
    "gray": "#666666",
    "light_gray": "#D9D9D9",
    "dark": "#1A1A1A",
}

LINE_STYLES = ["-", "--", "-.", ":"]
MARKERS = ["o", "s", "^", "D", "v", "P"]
SINGLE_COL_FIGSIZE = (3.55, 2.45)
DOUBLE_COL_FIGSIZE = (6.65, 3.90)


def setup_matplotlib() -> str:
    import matplotlib

    if not hasattr(matplotlib, "use"):
        sys.modules.pop("matplotlib", None)
        sys.modules.pop("matplotlib.pyplot", None)
        matplotlib = importlib.import_module("matplotlib")
    matplotlib.use("Agg", force=True)
    from matplotlib import font_manager
    from matplotlib import pyplot as plt

    font_name = _find_font_name(font_manager)
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": [font_name, "Songti SC", "STSong", "SimSun", "Noto Serif CJK SC", "Source Han Serif SC", "Times New Roman", "STIXGeneral", "DejaVu Serif"],
            "font.sans-serif": ["Noto Sans CJK SC", "PingFang SC", "Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "axes.edgecolor": "#1A1A1A",
            "axes.labelcolor": "#1A1A1A",
            "axes.titleweight": "normal",
            "axes.titlesize": 8.5,
            "axes.labelsize": 8.0,
            "axes.grid": True,
            "axes.linewidth": 0.8,
            "font.size": 8.0,
            "grid.color": "#D0D0D0",
            "grid.linewidth": 0.45,
            "grid.alpha": 0.70,
            "legend.frameon": False,
            "legend.fontsize": 7.0,
            "lines.linewidth": 0.9,
            "patch.linewidth": 0.8,
            "xtick.labelsize": 7.0,
            "xtick.major.width": 0.8,
            "ytick.labelsize": 7.0,
            "ytick.major.width": 0.8,
            "mathtext.fontset": "stix",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.dpi": 300,
        }
    )
    return font_name


def cm_to_inch(width_cm: float, height_cm: float) -> tuple[float, float]:
    return width_cm / 2.54, height_cm / 2.54


def save_pdf_png(fig, output_stem: str | Path) -> tuple[Path, Path]:
    stem = Path(output_stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    pdf_path = stem.with_suffix(".pdf")
    png_path = stem.with_suffix(".png")
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, bbox_inches="tight", dpi=300)
    return pdf_path, png_path


def sample_watermark(ax) -> None:
    ax.text(
        0.5,
        0.5,
        "样例数据/非实验结果",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=24,
        color="#9CA3AF",
        alpha=0.22,
        rotation=18,
        zorder=20,
    )


def _find_font_name(font_manager) -> str:
    preferred = ("Songti SC", "STSong", "SimSun", "Noto Serif CJK SC", "Source Han Serif SC", "Noto Sans CJK SC", "PingFang SC", "Arial Unicode MS")
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in preferred:
        if name in available:
            return name
    return "DejaVu Sans"
