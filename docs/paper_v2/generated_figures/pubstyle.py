# -*- coding: utf-8 -*-
"""出版社规格常量：由 setp-new.cls 与成品 PDF 实测得出，四张图统一从此处取值。
实测依据（2026-08-20，量自 paper_main.pdf）：
  正文 10.5 pt；表题 9.0 pt 宋体加粗；
  表格粗线 0.84 pt（booktabs \heavyrulewidth 0.08em @10.5pt）、
  表格细线 0.525 pt（\lightrulewidth 0.05em @10.5pt）。
图题不再烧进图内，改由 LaTeX \caption 出，以保证与表题同规格。
"""
from matplotlib.font_manager import FontProperties

SONG = "/System/Library/Fonts/Supplemental/Songti.ttc"
# 字号：图内文字一律不超过图题（9 pt），刻度与标注依次递减
CN   = FontProperties(fname=SONG, size=9.0)    # 轴标签
CNs  = FontProperties(fname=SONG, size=7.5)    # 标注、图例
TICK = 8.0                                     # 刻度数字

# 线宽：对齐表格线标准
RULE_HEAVY = 0.84    # 数据曲线／主要图形元素
RULE_LIGHT = 0.525   # 坐标轴、刻度、框线、辅助线

# 黑白印刷配色：类别差异主要由线型、点型和纹理承担
MONEY  = "#D9D9D9"
CARBON = "#666666"
GREY   = "#A6A6A6"
DARK   = "#333333"

def apply_axes(ax, spines=("left", "bottom")):
    """按出版社线宽设置坐标轴与刻度。"""
    for k, sp in ax.spines.items():
        if k in spines:
            sp.set_visible(True); sp.set_linewidth(RULE_LIGHT)
        else:
            sp.set_visible(False)
    ax.tick_params(labelsize=TICK, width=RULE_LIGHT, length=3)
