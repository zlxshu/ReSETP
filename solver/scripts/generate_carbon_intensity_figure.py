#!/usr/bin/env python3
"""图：TVGCI-CMDMF-DVRP 算例的逐时电网碳强度（4.1 节实验设置）。

重建 2026-08-29 生成的 ``figure_experiment_carbon_intensity.pdf``：原脚本已不在仓库，
且该图纵轴写作 kgCO$_2$e/kWh，与正文统一改用 CO$_2$（不带 e）后的口径不一致。
本脚本从算例自身的时变电价—碳强度日历重新绘制，除纵轴标签外与旧图逐点一致。

数据来源（运行时参数权威源，与求解器 china81.py 的默认取数路径同一份文件同一列）：
  data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/
      tariff_carbon_hourly_calendar.csv
  city=beijing，date=2025-02-12（china81.DEFAULT_CHINA81_DATE），
  列 carbon_factor_kgco2e_per_kwh。
日历按 48 个半小时槽存储，同一小时内两槽数值相同（求解器亦按此断言），故取整点值成 24 点序列。
列名仍保留 kgco2e 的历史命名，数值不变；仅图上标签按正文口径写作 kgCO$_2$/kWh。

画风沿用仓库既有图脚本：全图黑白灰、不使用彩色（宋体走中文、Times New Roman 走拉丁，
pdf.fonttype=42），四边封闭矩形框、无网格线、无标题；阶梯线 drawstyle="steps-post"，
横轴 0—24 时每 4 小时一个刻度。版面尺寸与旧图相同（442.8×104.4 pt），
以配合 paper_main.tex 中 width=0.95\\textwidth 的插图宽度。

顺带修掉旧图的一处渲染缺陷：旧图纵轴名按坐标框居中，字串长过画布，末尾的全角右括号被
MediaBox 裁掉。本图把纵轴名改按整张画布居中，标签得以完整显示；曲线、坐标框、刻度、
画布尺寸一律不动。

用法（须用仓库 venv）：
  .public-hgs-venv/bin/python3 solver/scripts/generate_carbon_intensity_figure.py
生成 docs/paper_v2/generated_figures/figure_experiment_carbon_intensity.pdf 与同名 PNG 预览。
"""

from __future__ import annotations

import argparse
import csv
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from fontTools.ttLib import TTCollection
from matplotlib import font_manager

REPO = Path(__file__).resolve().parents[2]
CALENDAR = (
    REPO
    / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
    / "tariff_carbon_hourly_calendar.csv"
)
CITY = "beijing"
DATE = "2025-02-12"  # = setp_solver.china81.DEFAULT_CHINA81_DATE
COLUMN = "carbon_factor_kgco2e_per_kwh"
OUT = (
    REPO
    / "docs/paper_v2/generated_figures/figure_experiment_carbon_intensity.pdf"
)

# 2026-08-29 旧图 PDF 内容流里逐点反解出的 24 个纵坐标（保留 4 位小数）。
# 留在这里当哨兵：若日历数据被换掉或取数路径漂移，脚本立刻报错而不是悄悄画出另一条线。
EXPECTED = (
    0.6433, 0.6439, 0.6360, 0.6253, 0.6002, 0.5937, 0.5849, 0.5944,
    0.5203, 0.3185, 0.2376, 0.1799, 0.1646, 0.1541, 0.1553, 0.1825,
    0.2687, 0.4309, 0.4748, 0.4723, 0.4858, 0.4858, 0.4749, 0.6155,
)

INK = "#000000"
AXIS_INK = "#1A1A1A"  # 旧图坐标框与刻度的灰度 0.1019607843
TEXT_PT = 8.0
CURVE_PT = 0.62
AXIS_PT = 0.468
TICK_LEN = 2.5

# 喂给 set_label_coords 的锚点横坐标（页面 pt），标定后纵轴名落在旧图同一列（x=23.78 pt）。
YLABEL_X_PT = 25.78

FIG_W_IN = 442.8 / 72.0  # 旧图 MediaBox 宽
FIG_H_IN = 104.4 / 72.0  # 旧图 MediaBox 高
# 旧图坐标框在页面中的位置：x 44.28—438.372，y 29.232—99.18。
AXES_RECT = dict(left=0.10, right=0.99, bottom=0.28, top=0.95)

_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_carbon_intensity_font_")


def _songti_regular() -> str:
    """从系统 Songti.ttc 里抽出 STSongti-SC-Regular 单个字面，供 matplotlib 嵌入。"""

    target = Path(_FONT_TMP.name) / "STSongti-SC-Regular.ttf"
    if target.is_file():
        return str(target)
    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    for font in TTCollection(source).fonts:
        names = {r.toUnicode() for r in font["name"].names if r.nameID == 6}
        if "STSongti-SC-Regular" in names:
            font.save(target)
            return str(target)
    raise RuntimeError("Songti SC Regular face not found in system Songti.ttc")


def load_hourly_intensity() -> list[float]:
    """读日历，取北京代表日的 24 个整点电网碳强度（kgCO2/kWh）。"""

    by_slot: dict[int, float] = {}
    with CALENDAR.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["city"].strip().lower() != CITY or row["date"] != DATE:
                continue
            by_slot[int(row["minute_of_day"])] = float(row[COLUMN])
    missing = [m for m in range(0, 1440, 30) if m not in by_slot]
    if missing:
        raise ValueError(
            f"{CALENDAR.name} 缺少 {CITY} {DATE} 的半小时槽：{missing[:5]}"
        )
    values: list[float] = []
    for hour in range(24):
        head = by_slot[hour * 60]
        tail = by_slot[hour * 60 + 30]
        if abs(head - tail) > 1e-12:
            raise ValueError(
                f"{CITY} {DATE} 第 {hour:02d} 小时两个半小时槽碳强度不一致：{head} vs {tail}"
            )
        values.append(head)
    return values


def check_against_old_figure(values: list[float]) -> None:
    for hour, (got, want) in enumerate(zip(values, EXPECTED)):
        if abs(round(got, 4) - want) > 1e-9:
            raise ValueError(
                f"第 {hour:02d} 小时碳强度与 2026-08-29 旧图不符："
                f"日历 {got!r}，旧图 {want!r}"
            )


def render(values: list[float], out_pdf: Path) -> None:
    cn = font_manager.FontProperties(fname=_songti_regular(), size=TEXT_PT)
    en = font_manager.FontProperties(family="Times New Roman", size=TEXT_PT)

    plt.rcParams.update(
        {
            "font.family": "Times New Roman",
            "font.size": TEXT_PT,
            "pdf.fonttype": 42,
            "savefig.dpi": 300,
        }
    )

    fig = plt.figure(figsize=(FIG_W_IN, FIG_H_IN))
    fig.subplots_adjust(**AXES_RECT)
    ax = fig.add_subplot(1, 1, 1)

    # 阶梯线：第 h 小时的强度在 [h, h+1) 上保持不变，故末点补一次以画满到 24 时。
    xs = list(range(25))
    ys = list(values) + [values[-1]]
    ax.plot(
        xs,
        ys,
        drawstyle="steps-post",
        color=INK,
        linewidth=CURVE_PT,
        solid_capstyle="projecting",
        solid_joinstyle="round",
    )

    ax.set_xlim(0, 24)
    ax.set_ylim(0.1, 0.7)
    ax.set_xticks(range(0, 25, 4))
    ax.set_yticks([0.2, 0.4, 0.6])
    # labelpad 取 3.33 / 4.0 是为了让两个轴名落在与旧图同一位置（误差 <0.01 pt），
    # 不是圆整值；旧图与本图的 matplotlib 版本字体度量略有差异。
    ax.set_xlabel("时刻", fontproperties=cn, labelpad=3.33, color=INK)
    ax.set_ylabel(
        "电网碳强度（kgCO$_2$/kWh）",
        fontproperties=cn,
        labelpad=4.0,
        color=INK,
    )
    # 旧图把纵轴名按坐标框（页面 y 29.232—99.18）居中，而这行标签长约 98 pt、比 104.4 pt
    # 的画布只矮 6 pt，于是末尾的全角右括号被 MediaBox 裁掉——旧图和正文里都缺这个括号。
    # 这里改为按整张画布居中，横向位置仍钉在旧图的 x=23.78 pt：曲线、坐标框、刻度全都不动，
    # 只把这一行字整体下移约 12 pt，标签即可完整显示。
    ax.yaxis.set_label_coords(
        YLABEL_X_PT / 442.8, 0.5, transform=fig.transFigure
    )

    for spine in ax.spines.values():
        spine.set_color(AXIS_INK)
        spine.set_linewidth(AXIS_PT)
    ax.tick_params(
        axis="both",
        which="major",
        direction="out",
        length=TICK_LEN,
        width=AXIS_PT,
        color=AXIS_INK,
        labelcolor=AXIS_INK,
        top=False,
        right=False,
        pad=2.0,
    )
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(en)

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, format="pdf", facecolor="white")
    fig.savefig(
        out_pdf.with_suffix(".png"), format="png", dpi=400, facecolor="white"
    )
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--skip-old-figure-check",
        action="store_true",
        help="跳过与 2026-08-29 旧图逐点一致的哨兵检查",
    )
    args = parser.parse_args()

    values = load_hourly_intensity()
    if not args.skip_old_figure_check:
        check_against_old_figure(values)
    render(values, args.out)
    print(f"wrote {args.out}")
    print(f"wrote {args.out.with_suffix('.png')}")
    print(
        f"source: {CALENDAR.relative_to(REPO)} :: city={CITY} date={DATE} "
        f"column={COLUMN}"
    )
    print(
        f"range: min={min(values):.4f} max={max(values):.4f} "
        f"peak-valley={max(values) - min(values):.4f} kgCO2/kWh"
    )


if __name__ == "__main__":
    main()
