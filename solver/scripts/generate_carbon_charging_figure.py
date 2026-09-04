"""重画论文「分时电价、电网碳强度与车辆充电时刻」一图。

背景：该图此前在仓库中没有数据生成脚本，只有 2026-08-13 的占位壳
（docs/paper_gci_dmm_vrp_20260804/figure_shells_20260813/build_figure_shells.py，
其碳强度为编造的示例序列）。本脚本按用户 2026-09-01 令补齐生成器，全部数值取自实跑产物。

图形规格（用户 2026-09-01 定）：
  * 两格并列，碳强度与分时电价**不混合**，各占一格；
  * **两格都要标出企业作业时间**（作业时间不随格变化）；
  * 每格叠加两条充电时刻策略臂的逐时段充电量；
  * **黑白灰教科书画风**：曲线一律黑色实线，两条臂以点纹与斜纹区分（白底黑边），
    作业时间带用浅灰，全图不使用彩色。

数据来源
  逐时段电价与电网碳强度：
    data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/
    tariff_carbon_hourly_calendar.csv（city=beijing, date=2025-02-12，半小时粒度）
  两臂充电场次：由 --arm-dir 指定的批次目录下
    <arm-dir>/MT-HGS/run_1/best_solution.json  （有可用时段即充电）
    <arm-dir>/MTC-HGS/run_1/best_solution.json（考虑时变碳强度）
  企业作业时间：算例车场时间窗 08:00--19:00（论文初始客户点和车场详细信息表给定）。

⚠️ 数据源版本警告（2026-09-04）：
  --arm-dir 的默认值 solver/reports/ablation_reseed_20260901 是**两代参数以前**的批次
  （电动车日固定溢价 50、旧充电时间代理、精确账未按模型对齐），与当前论文参数
  （溢价 100、日固定成本 170/270）已不一致。该图绑定的「不同充电时刻安排下的配送方案对比」
  一表尚未按新参数重跑，因此本脚本此前只做样式修改、未换数据。
  **待该表按新参数重跑后，必须用 --arm-dir 指向新批次重新生成本图。**

用法：
  python3 solver/scripts/generate_carbon_charging_figure.py                     # 用默认（旧参数）批次
  python3 solver/scripts/generate_carbon_charging_figure.py \\
      --arm-dir solver/reports/<新批次目录>                                      # 表重跑后指向新批次
"""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from fontTools.ttLib import TTCollection
from matplotlib import font_manager
from matplotlib.patches import Patch
from matplotlib.transforms import Bbox

REPO = Path(__file__).resolve().parents[2]
CALENDAR = (
    REPO
    / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
    / "tariff_carbon_hourly_calendar.csv"
)
ARMS = (
    ("MT-HGS", "有可用时段即充电"),
    ("MTC-HGS", "考虑时变碳强度"),
)
# 默认值＝改为命令行参数之前写死的路径（旧参数批次，见文件头警告）。
DEFAULT_ARM_DIR = REPO / "solver/reports/ablation_reseed_20260901"
OUT = REPO / "docs/paper_v2/generated_figures/figure_3_carbon_tariff_charging.pdf"

CITY = "beijing"
DATE = "2025-02-12"
# 正文按 width=\textwidth 排版，画布宽度必须锁死在版心宽度上（历史产物即此值）。
TARGET_WIDTH_PT = 501.056875
# 每格编号后紧跟该格说明（国内期刊惯例），使读者不必回头猜哪格对应哪个量。
PANEL_CAPTIONS = (
    "(a) 电网碳强度与车辆充电时刻",
    "(b) 分时电价与车辆充电时刻",
)
DEPOT_OPEN_H = 8.0
DEPOT_CLOSE_H = 19.0
SLOTS = 48  # 半小时粒度

# 黑白灰教科书画风：只用黑、白与两级灰。
PALETTE = {
    "ink": "#000000",
    "gray": "#666666",
    "light_gray": "#D9D9D9",
}
ARM_HATCH = ("....", "///")
AXIS_WIDTH_PT = 0.468
CURVE_WIDTH_PT = 0.62
TEXT_SIZE_PT = 8.0

_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_carbon_fig_font_")


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


LEGEND_SIZE_PT = 7.0  # 图例字号比坐标轴标签小一档（母版图例亦小于轴标签）
PANEL_SIZE_PT = 7.5  # 格说明比正文小半档，不与坐标轴标签抢视觉重量

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


def load_calendar() -> tuple[np.ndarray, np.ndarray]:
    """返回作业日的逐半小时（电价，碳强度）两条 48 点序列。"""
    price = np.full(SLOTS, np.nan)
    carbon = np.full(SLOTS, np.nan)
    with CALENDAR.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["city"] != CITY or row["date"] != DATE:
                continue
            slot = int(row["minute_of_day"]) // 30
            price[slot] = float(row["depot_energy_cny_per_kwh"])
            carbon[slot] = float(row["carbon_factor_kgco2e_per_kwh"])
    if np.isnan(price).any() or np.isnan(carbon).any():
        raise RuntimeError(f"calendar rows missing for {CITY} {DATE}")
    return price, carbon


def load_arm_energy(arm: str, arm_dir: Path) -> np.ndarray:
    """把一条臂的充电场次按开始时刻归入 48 个半小时槽，返回逐槽充电量。"""
    path = arm_dir / arm / "run_1" / "best_solution.json"
    solution = json.loads(path.read_text(encoding="utf-8"))
    energy = np.zeros(SLOTS)
    for duty in solution["individual"]["duties"]:
        for session in duty.get("charging_sessions", []):
            minute = (float(session["charge_start_second"]) // 60) % 1440
            energy[int(minute // 30)] += float(session["energy_kwh"])
    if not energy.any():
        raise RuntimeError(f"no charging sessions found in {path}")
    return energy


def _mark_working_hours(axes) -> None:
    """两格共用的企业作业时间带；作业时间由算例车场时间窗给定，不随格变化。"""
    axes.axvspan(
        DEPOT_OPEN_H * 2,
        DEPOT_CLOSE_H * 2,
        color=PALETTE["light_gray"],
        alpha=0.45,
        linewidth=0,
        zorder=0,
    )
    for edge in (DEPOT_OPEN_H * 2, DEPOT_CLOSE_H * 2):
        axes.axvline(
            edge,
            color=PALETTE["gray"],
            linestyle=(0, (3, 2)),
            linewidth=AXIS_WIDTH_PT,
            zorder=1,
        )


def _style(axes) -> None:
    axes.spines["top"].set_visible(False)
    axes.tick_params(axis="both", direction="out", length=2.5, width=AXIS_WIDTH_PT, pad=2)
    axes.set_xlim(0, SLOTS)
    axes.set_xticks(np.arange(0, SLOTS + 1, 8))
    axes.set_xticklabels([f"{h:02d}" for h in range(0, 25, 4)])
    axes.set_xlabel("时刻", fontproperties=CN)


def _draw_panel(axes, curve, curve_label, y_label, arms_energy, step_axis_max):
    _mark_working_hours(axes)
    edges = np.arange(SLOTS + 1)
    axes.step(
        edges,
        np.r_[curve, curve[-1]],
        where="post",
        color=PALETTE["ink"],
        linewidth=CURVE_WIDTH_PT,
        label=curve_label,
        zorder=3,
    )
    axes.set_ylabel(y_label, fontproperties=CN)
    axes.set_ylim(0, step_axis_max)
    # 两格统一按 0.2 一档打刻度：自动刻度会让右格退化成 0.25 一档、两位小数，
    # 与左格不成对，且顶端 1.4 那一档会消失。
    ticks = np.arange(0.0, step_axis_max + 1e-9, 0.2)
    axes.set_yticks(ticks)
    axes.set_yticklabels([f"{value:.1f}" for value in ticks])
    _style(axes)

    bars = axes.twinx()
    width = 0.42
    centres = np.arange(SLOTS) + 0.5
    for index, ((_, label), energy) in enumerate(arms_energy):
        bars.bar(
            centres + (index - 0.5) * width,
            energy,
            width=width,
            facecolor="white",
            edgecolor=PALETTE["ink"],
            hatch=ARM_HATCH[index],
            linewidth=AXIS_WIDTH_PT,
            label=label,
            zorder=2,
        )
    bars.set_ylabel("充电量（kWh）", fontproperties=CN)
    bars.set_ylim(0, 110)
    bars.spines["top"].set_visible(False)
    bars.grid(False)
    bars.tick_params(axis="y", direction="out", length=2.5, width=AXIS_WIDTH_PT, pad=2)
    return bars


def _report_legend_box(figure, legend, axes) -> None:
    """把格内图例的实际外框换算回左格数据坐标并打印，供人工核对是否压到东西。

    图例宽高由字体度量决定，改字号或改措辞都会变；与其凭眼睛猜，不如每次生成时报出
    它占住的时刻区间与纵轴区间，对照"该区间内曲线与柱形最高 0.520、19:00 虚线在第 38 槽"。
    """
    figure.canvas.draw()
    box = legend.get_window_extent(figure.canvas.get_renderer())
    (x0, y0), (x1, y1) = axes.transData.inverted().transform(box.get_points())
    print(
        f"  图例占位：时刻 {x0 / 2:.2f}--{x1 / 2:.2f} 时（第 {x0:.1f}--{x1:.1f} 槽），"
        f"左轴 {y0:.3f}--{y1:.3f}"
    )


def _save_at_target_width(figure, out_path: Path, pad_in: float = 0.05) -> tuple[float, float]:
    """按内容紧边界裁剪，但把宽度锁死在 TARGET_WIDTH_PT 上并让内容居中。

    此前用 bbox_inches="tight"，画布宽度是「内容宽度＋默认留白」的副产物，
    改动图例或格说明都会连带改变画布宽度；正文按 width=\\textwidth 排版，宽度必须稳定。
    """
    figure.canvas.draw()
    tight = figure.get_tightbbox(figure.canvas.get_renderer())
    target_in = TARGET_WIDTH_PT / 72.0
    if tight.width > target_in:
        raise RuntimeError(
            f"内容宽度 {tight.width * 72:.2f} pt 已超过版心宽度 {TARGET_WIDTH_PT:.2f} pt，"
            "居中裁剪会切掉两侧内容；请先压缩图例或坐标轴标签。"
        )
    centre = 0.5 * (tight.x0 + tight.x1)
    box = Bbox(
        [
            [centre - target_in / 2, tight.y0 - pad_in],
            [centre + target_in / 2, tight.y1 + pad_in],
        ]
    )
    figure.savefig(out_path, format="pdf", bbox_inches=box, pad_inches=0, facecolor="white")
    return TARGET_WIDTH_PT, box.height * 72


def _display(path: Path) -> str:
    """仓库内路径显示为相对路径，仓库外原样显示。"""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--arm-dir",
        type=Path,
        default=DEFAULT_ARM_DIR,
        help=(
            "两条充电时刻策略臂的结果批次目录（其下须有 MT-HGS/run_1/best_solution.json 与 "
            "MTC-HGS/run_1/best_solution.json）。默认＝旧参数批次 "
            f"{DEFAULT_ARM_DIR.relative_to(REPO)}，表重跑后应指向新批次。"
        ),
    )
    parser.add_argument("--out", type=Path, default=OUT, help="输出 PDF 路径。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    arm_dir = args.arm_dir if args.arm_dir.is_absolute() else REPO / args.arm_dir
    out_path = args.out if args.out.is_absolute() else REPO / args.out

    price, carbon = load_calendar()
    arms_energy = [(arm, load_arm_energy(arm[0], arm_dir)) for arm in ARMS]

    figure, (left, right) = plt.subplots(1, 2, figsize=(6.9, 2.61))
    # 图例改放坐标区内（见下），画布顶部不再需要留一行给共享图例，top 退回 0.94。
    # 画布高度取 2.61 英寸，使坐标区净高 2.61×(0.94−0.215)＝1.892 英寸不低于
    # 图例外置之前的 1.887 英寸——否则曲线在纸面上反而画得更小。
    figure.subplots_adjust(left=0.085, right=0.930, bottom=0.215, top=0.940, wspace=0.55)

    left_bars = _draw_panel(
        left,
        carbon,
        "电网碳强度",
        "电网碳强度\n（kgCO$_2$e/kWh）",
        arms_energy,
        # 纵轴上限维持 0.80：曲线最高 0.644、柱形最高折合 0.720，格内 y≥0.53 一带本就空着，
        # 放得下图例，不必为让位图例抬高上限。取 0.80 而非 0.78：0.78 会把顶端 0.8 那一档刻度挤掉。
        0.80,
    )
    _draw_panel(
        right,
        price,
        "分时电价",
        "分时电价\n（元/kWh）",
        arms_energy,
        # 同上：退回原值 1.42（0.2 一档的刻度下，顶端 1.4 那一档照常显示，无需迁就）。
        1.42,
    )

    # 图例：按目标期刊母版的实际做法放在坐标区**之内**的空白处，整图只出现一次。
    # 母版取证（2026-09-04，Zotero 原文逐幅核）：
    #   陈婉茹等 2023《碳交易机制下多中心混合车队配送路径和速度优化研究》
    #     图 4(a)（p.3332）图例在该格作图区内下方、横排两项、无框；图 5（p.3333）图例在坐标区内
    #     右上角、竖排八项、无框；图 2（p.3329）单序列无图例。
    #   陈雨蝶等 2025《双碳背景下复杂冷链物流模型及求解算法》
    #     图 3（p.11）图例在坐标区内左下角、竖排六项、无框；图 4（p.14）与图 7（p.19）图例在坐标区内
    #     右上角、竖排、带细框；图 6（p.18）四格各单序列，无图例，靠 (a)-(d) 说明区分。
    #   两篇合计五处图例**全部落在坐标区之内**，没有一处把图例横排放在两格上方——上一版的放法
    #   在母版里没有先例，故改回格内。竖排为主（五取四）；边框五取二，非通行做法，因此不加框：
    #   无框、无底色时图例不会在灰带上挖出白洞，符合"图例不压曲线、柱形、灰带与刻度"的验收线。
    # 落点由数据算出：左格 08:00--22:00（第 16--44 个半小时槽）内曲线与柱形的最高点为 0.520，
    # 该区间 y≥0.53 以上整片为空，是全图唯一放得下竖排三项的空白（右格没有这么大的洞：
    # 电价曲线 10--13 时与 17--21 时都顶到 1.149，剩下的空当窄到放不下八字标签）。
    # 实测图例占第 16.0--36.8 槽、左轴 0.545--0.722，故不压曲线、柱形，也不压 19:00 那条虚线
    # （第 38 槽）。字号因此卡在 7.0 pt：再放大到 7.5 pt 图例右沿就落到第 38.3 槽，压上虚线。
    # 图例挂在 twinx（柱形）坐标系上：twinx 画在上层，挂在左轴上会被柱形层盖住。
    # （图题只由 LaTeX 的 \caption 给出，图内不重复标题。）
    handles = [
        Patch(
            facecolor="white",
            edgecolor=PALETTE["ink"],
            hatch=ARM_HATCH[index],
            linewidth=AXIS_WIDTH_PT,
        )
        for index in range(len(ARMS))
    ] + [
        # 无框图例里浅灰块需要一道发丝黑边，否则无论压在白底还是压在同色灰带上都分不出来。
        Patch(
            facecolor=PALETTE["light_gray"],
            edgecolor=PALETTE["ink"],
            linewidth=AXIS_WIDTH_PT,
        )
    ]
    labels = [label for _, label in ARMS] + ["企业作业时间"]
    legend = left_bars.legend(
        handles,
        labels,
        loc="lower left",
        # 坐标区分数坐标：x=16/48（08:00 处），y=0.545/0.80（左轴 0.545 处）。
        # borderaxespad 必须清零：默认 0.5 字宽会把图例再往右推约一个半小时槽，
        # 右沿就压到 19:00 那条虚线上了。
        bbox_to_anchor=(16.0 / SLOTS, 0.545 / 0.80),
        borderaxespad=0.0,
        ncol=1,
        frameon=False,
        fontsize=LEGEND_SIZE_PT,
        # 图例色块比默认再放大一点：块太小时点纹会糊成"黑底白点"，与柱形上的"白底黑点"对不上。
        handlelength=1.4,
        handleheight=1.1,
        handletextpad=0.28,
        labelspacing=0.4,
        borderpad=0.15,
    )
    for text in legend.get_texts():
        text.set_fontproperties(CN_LEGEND)
    _report_legend_box(figure, legend, left)

    # 编号后紧跟该格说明；用相对坐标区下沿的定点偏移，不随坐标区高度变化而漂移。
    for axes, caption in zip((left, right), PANEL_CAPTIONS):
        axes.annotate(
            caption,
            xy=(0.5, 0.0),
            xycoords="axes fraction",
            xytext=(0, -32),
            textcoords="offset points",
            ha="center",
            va="top",
            fontproperties=CN_PANEL,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    width_pt, height_pt = _save_at_target_width(figure, out_path)
    print(f"wrote {_display(out_path)}  (arm-dir = {_display(arm_dir)})")
    print(f"  画布尺寸 {width_pt:.2f} pt × {height_pt:.2f} pt")
    for (arm, label), energy in arms_energy:
        inside = energy[int(DEPOT_OPEN_H * 2) : int(DEPOT_CLOSE_H * 2)].sum()
        print(
            f"  {arm:8s} {label}  总充电 {energy.sum():7.2f} kWh，"
            f"其中作业时间内 {inside:7.2f} kWh（{inside / energy.sum() * 100:.1f}%）"
        )


if __name__ == "__main__":
    main()
