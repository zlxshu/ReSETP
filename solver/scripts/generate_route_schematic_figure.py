"""重画论文「不同配送模式的配送路径」一图（黑白灰教科书画风）。

背景：该图此前在仓库中同样没有生成脚本，只有一份成稿 PDF，且图内右上角残留“示意”
二字。本脚本按用户 2026-09-01 令补齐生成器并恢复黑白灰画风。

做法：几何**原样沿用**旧图，不改动任何节点位置或连线。旧图的矢量几何已一次性提取到
``assets_route_schematic_geometry.json``（路线折线 9 条、客户点 27 个、车场标记 6 个、
虚线 3 条，以及数字与中文的字形位置），本脚本只负责按新配色重绘：

  * 路线、客户点轮廓、车场标记一律黑色；客户点白底黑边，车场实心黑；
  * 成本结算归属的虚线用中灰虚线；
  * 全图不使用彩色；
  * **删去原图右上角的“示意”二字**（用户令：不要有示意等类似字样）。

坐标系沿用原图的 SVG 用户坐标（原点在左上、y 轴向下），画布尺寸与旧图逐点一致
（354.24 × 185.76 pt），因此换图后正文排版不变。注意旧图里图形与文字分处两套坐标：
矢量路径带一个 y 翻转矩阵 matrix(a, 0, 0, -a, 0, f)，文字的 x/y 则已是最终坐标，
故本脚本只对路径施加该翻转（``PATH_SCALE`` 与 ``PATH_Y_OFFSET``），文字位置原样使用。

用法：python3 solver/scripts/generate_route_schematic_figure.py
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from fontTools.ttLib import TTCollection
from matplotlib import font_manager
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch

REPO = Path(__file__).resolve().parents[2]
GEOMETRY = Path(__file__).resolve().parent / "assets_route_schematic_geometry.json"
OUT = (
    REPO
    / "docs/paper_v2/generated_figures/concept_collaboration_fairness_notitle.pdf"
)

PATH_SCALE = 0.997859
PATH_Y_OFFSET = 185.441415

INK = "#000000"
GRAY = "#575757"
LINE_PT = 0.50
TEXT_SIZE_PT = 7.5

# 每格题注拆成拉丁前缀与中文两段：前缀用 Times New Roman，中文用宋体，
# 免得整串交给中文字体后拉丁字母被替换成异形字。x 取旧图对应字形的原位置。
PANEL_CAPTIONS = (
    (40.180795, "(a)", 51.005966, "独立配送"),
    (155.123193, "(b)", 165.948364, "联合配送"),
    (250.556447, "(c)", 261.381271, "联合配送（转归解）"),
)
CAPTION_BASELINE = 156.43365
NOTE_BASELINE = 163.2
NOTE_TEXT = "虚线为成本结算归属"

_FONT_TMP = tempfile.TemporaryDirectory(prefix="resetp_route_fig_font_")


def _songti_regular() -> Path:
    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    target = Path(_FONT_TMP.name) / "songti_sc_regular.ttf"
    for font in TTCollection(source).fonts:
        names = {r.toUnicode() for r in font["name"].names if r.nameID == 6}
        if "STSongti-SC-Regular" in names:
            font.save(target)
            return target
    raise RuntimeError("Songti SC Regular face not found in system Songti.ttc")


CN = font_manager.FontProperties(fname=_songti_regular(), size=TEXT_SIZE_PT)
EN = font_manager.FontProperties(family="Times New Roman", size=TEXT_SIZE_PT)

plt.rcParams.update(
    {
        "font.family": "Times New Roman",
        "font.size": TEXT_SIZE_PT,
        "pdf.fonttype": 42,
        "savefig.dpi": 300,
    }
)

_TOKEN = re.compile(r"([MLCZ])|(-?\d*\.?\d+)")


def svg_path_to_mpl(data: str) -> MplPath:
    """把 SVG 的 d 属性翻成 matplotlib Path；旧图只用到 M/L/C/Z 四种指令。"""
    numbers: list[float] = []
    command: str | None = None
    vertices: list[tuple[float, float]] = []
    codes: list[int] = []

    def flush() -> None:
        nonlocal numbers
        if command == "M" and len(numbers) >= 2:
            for index in range(0, len(numbers) - 1, 2):
                vertices.append((numbers[index], numbers[index + 1]))
                codes.append(MplPath.MOVETO if index == 0 else MplPath.LINETO)
        elif command == "L":
            for index in range(0, len(numbers) - 1, 2):
                vertices.append((numbers[index], numbers[index + 1]))
                codes.append(MplPath.LINETO)
        elif command == "C":
            for index in range(0, len(numbers) - 5, 6):
                for offset in range(0, 6, 2):
                    vertices.append(
                        (numbers[index + offset], numbers[index + offset + 1])
                    )
                    codes.append(MplPath.CURVE4)
        numbers = []

    for match in _TOKEN.finditer(data):
        letter, number = match.group(1), match.group(2)
        if letter:
            flush()
            if letter == "Z":
                vertices.append((0.0, 0.0))
                codes.append(MplPath.CLOSEPOLY)
                command = None
            else:
                command = letter
        else:
            numbers.append(float(number))
    flush()
    placed = [
        (PATH_SCALE * x, PATH_Y_OFFSET - PATH_SCALE * y) for x, y in vertices
    ]
    return MplPath(placed, codes)


def main() -> None:
    geometry = json.loads(GEOMETRY.read_text(encoding="utf-8"))
    width, height = geometry["width"], geometry["height"]

    figure = plt.figure(figsize=(width / 72.0, height / 72.0))
    axes = figure.add_axes([0, 0, 1, 1])
    axes.set_xlim(0, width)
    axes.set_ylim(height, 0)  # SVG 坐标：y 轴向下
    axes.set_axis_off()

    for data in geometry["routes"]:
        axes.add_patch(
            PathPatch(
                svg_path_to_mpl(data),
                facecolor="none",
                edgecolor=INK,
                linewidth=LINE_PT,
                joinstyle="round",
                capstyle="round",
            )
        )
    for data in geometry["dashed"]:
        axes.add_patch(
            PathPatch(
                svg_path_to_mpl(data),
                facecolor="none",
                edgecolor=GRAY,
                linewidth=LINE_PT,
                linestyle=(0, (2.2, 1.6)),
            )
        )
    for data in geometry["customers"]:
        axes.add_patch(
            PathPatch(
                svg_path_to_mpl(data),
                facecolor="white",
                edgecolor=INK,
                linewidth=LINE_PT,
            )
        )
    for data in geometry["depots"]:
        axes.add_patch(
            PathPatch(
                svg_path_to_mpl(data),
                facecolor=INK,
                edgecolor=INK,
                linewidth=LINE_PT,
            )
        )

    # 客户编号：字形族 0 的前九个字形依次为数字 1--9，位置沿用旧图。
    for family, index, x, y in geometry["digits"]:
        if family != 0 or index > 8:
            continue
        axes.text(x, y, str(index + 1), fontproperties=EN, ha="left", va="baseline")

    for prefix_x, prefix, chinese_x, chinese in PANEL_CAPTIONS:
        axes.text(
            prefix_x, CAPTION_BASELINE, prefix,
            fontproperties=EN, ha="left", va="baseline",
        )
        axes.text(
            chinese_x, CAPTION_BASELINE, chinese,
            fontproperties=CN, ha="left", va="baseline",
        )
    axes.text(
        width - 12.0,
        NOTE_BASELINE,
        NOTE_TEXT,
        fontproperties=CN,
        ha="right",
        va="baseline",
    )
    # 旧图右上角的“示意”二字按用户令删除，此处不再绘制。

    OUT.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUT, format="pdf", facecolor="white")
    print(f"wrote {OUT.relative_to(REPO)}")
    print(
        f"  路线 {len(geometry['routes'])} 条，客户点 {len(geometry['customers'])} 个，"
        f"车场标记 {len(geometry['depots'])} 个，虚线 {len(geometry['dashed'])} 条；"
        f"画布 {width} × {height} pt"
    )


if __name__ == "__main__":
    main()
