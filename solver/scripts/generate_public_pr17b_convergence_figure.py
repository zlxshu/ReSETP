#!/usr/bin/env python3
"""按出版社字体规范重绘图 3 的 PR17B 收敛曲线，不改变轨迹数据。"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fontTools.ttLib import TTCollection
from matplotlib import font_manager

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "solver/reports/public28_formal_20260830/PR17B/run_09_trajectory.csv"
OUT = REPO / "docs/paper_v2/generated_figures/figure_2_public_pr17b_convergence.pdf"
FONT_DIR = Path("/Applications/Microsoft Word.app/Contents/Resources/DFonts")
TEXT_PT = 9.3  # 按 0.45\textwidth 缩放后约为 8 pt
_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_pr17b_font_")


def simsun_regular() -> Path:
    target = Path(_FONT_TMP.name) / "SimSun.ttf"
    for font in TTCollection(FONT_DIR / "Simsun.ttc").fonts:
        names = {record.toUnicode() for record in font["name"].names if record.nameID == 6}
        if "SimSun" in names:
            font.save(target)
            return target
    raise RuntimeError("SimSun face not found")


def load_trajectory() -> tuple[list[int], list[float]]:
    rows = list(csv.DictReader(SOURCE.open(encoding="utf-8")))
    points = [
        (int(row["iteration"]), float(row["best_cost"]) / 1000.0)
        for row in rows
        if float(row["best_cost"]) < 1.0e12
    ]
    if points[-1] != (16861, 4782.344):
        raise ValueError(f"PR17B 轨迹终点发生变化：{points[-1]}")
    return [point[0] for point in points], [point[1] for point in points]


def main() -> None:
    cn_path = simsun_regular()
    font_manager.fontManager.addfont(str(cn_path))
    cn = font_manager.FontProperties(fname=str(cn_path), size=TEXT_PT)
    en = font_manager.FontProperties(family="Times New Roman", size=TEXT_PT)
    plt.rcParams.update(
        {
            "font.family": ["Times New Roman", cn.get_name()],
            "font.size": TEXT_PT,
            "pdf.fonttype": 42,
            "axes.unicode_minus": False,
        }
    )

    iterations, costs = load_trajectory()
    fig, ax = plt.subplots(figsize=(3.4, 2.3))
    fig.subplots_adjust(left=0.18, right=0.96, bottom=0.24, top=0.96)
    ax.step(iterations, costs, where="post", color="black", linewidth=0.7)
    ax.set_xlim(0, 17000)
    ax.set_ylim(4700, 5700)
    ax.set_xticks(range(0, 15001, 2500))
    ax.set_yticks(range(4800, 5601, 200))
    ax.set_xlabel("迭代次数", fontproperties=cn, labelpad=2.0)
    ax.set_ylabel("当前最优距离", fontproperties=cn, labelpad=2.0)
    ax.tick_params(direction="out", length=2.5, width=0.5, pad=2.0)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(en)
    for spine in ax.spines.values():
        spine.set_linewidth(0.5)
    ax.grid(False)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, format="pdf", facecolor="white")
    fig.savefig(OUT.with_suffix(".png"), dpi=400, facecolor="white")
    plt.close(fig)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
