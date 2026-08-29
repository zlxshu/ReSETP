# -*- coding: utf-8 -*-
"""生成正文图1“本文算法流程图”。

流程内容逐项对应当前 Problem-HGS 实现；正文不再使用原来的第二张串行链示意图。
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pubstyle import CN, CNs, TICK, RULE_HEAVY, RULE_LIGHT, MONEY, CARBON, GREY, DARK
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Polygon
from matplotlib.font_manager import FontProperties

HERE = os.path.dirname(os.path.abspath(__file__))
SONG = "/System/Library/Fonts/Supplemental/Songti.ttc"
FLOW_CN = FontProperties(fname=SONG, size=12.0)
FLOW_CNS = FontProperties(fname=SONG, size=10.5)





def box(ax, x, y, w, h, txt, ec=DARK, fc="white", fp=FLOW_CN, lw=RULE_LIGHT, ls="-"):
    ax.add_patch(FancyBboxPatch((x-w/2, y-h/2), w, h, boxstyle="round,pad=0.006,rounding_size=0.012",
                                ec=ec, fc=fc, lw=lw, ls=ls, zorder=2))
    ax.text(x, y, txt, ha="center", va="center", fontproperties=fp, color=DARK, zorder=3, linespacing=1.05)

def dia(ax, x, y, w, h, txt):
    ax.add_patch(Polygon([[x, y+h/2], [x+w/2, y], [x, y-h/2], [x-w/2, y]], closed=True,
                         ec=DARK, fc="white", lw=RULE_LIGHT, zorder=2))
    ax.text(x, y, txt, ha="center", va="center", fontproperties=FLOW_CNS, color=DARK, zorder=3, linespacing=1.05)

def arr(ax, p, q, color=DARK, ls="-", rad=0.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=8, lw=RULE_LIGHT,
                                 color=color, ls=ls, zorder=1,
                                 connectionstyle=f"arc3,rad={rad}"))

# ---------------- 图1：总流程 ----------------
fig = plt.figure(figsize=(5.4, 4.7)); ax = fig.add_axes([0.02, 0.025, 0.96, 0.96])
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
W, H, DH, cx = 0.46, 0.072, 0.110, 0.39
ys = [0.950, 0.860, 0.770, 0.680, 0.590, 0.500, 0.405, 0.310, 0.205, 0.090]
box(ax, cx, ys[0], W, H, "读取客户、车场、车辆\n及分时电价和碳强度")
box(ax, cx, ys[1], W, H, "生成初始解并计算目标函数")
box(ax, cx, ys[2], W, H, "建立可行与不可行子种群")
box(ax, cx, ys[3], W, H, "选择父代并执行路线交叉")
box(ax, cx, ys[4], W, H, "路线邻域搜索")
box(ax, cx, ys[5], W, H, "形成车辆多趟方案并调整充电安排")
box(ax, cx, ys[6], W, H, "计算目标函数并检验约束")
dia(ax, cx, ys[7], 0.40, DH, "满足约束？")
box(ax, cx, ys[8], W, H, "扩展邻域搜索、入群\n并更新当前最优解")
dia(ax, cx, ys[9], 0.40, DH, "满足终止条件？")

for i in range(7):
    arr(ax, (cx, ys[i]-H/2), (cx, ys[i+1]+(DH/2 if i == 6 else H/2)))
arr(ax, (cx, ys[7]-DH/2), (cx, ys[8]+H/2))
ax.text(cx+0.018, (ys[7]+ys[8])/2, "是", fontproperties=FLOW_CNS)
arr(ax, (cx, ys[8]-H/2), (cx, ys[9]+DH/2))

# 不可行候选按罚函数进入相应子种群，再统一检查停止条件。
box(ax, 0.82, ys[7], 0.29, 0.080, "计算约束违反程度\n并进入不可行子种群", fp=FLOW_CNS)
arr(ax, (cx+0.20, ys[7]), (0.675, ys[7]))
ax.text(0.635, ys[7]+0.017, "否", fontproperties=FLOW_CNS)
arr(ax, (0.82, ys[7]-0.040), (0.82, ys[9]))
arr(ax, (0.82, ys[9]), (cx+0.20, ys[9]))

# 未停止则返回父代选择；停止后输出完整可行的最好解。
arr(ax, (cx-0.20, ys[9]), (0.075, ys[9]))
ax.text(0.135, ys[9]+0.016, "否", fontproperties=FLOW_CNS)
arr(ax, (0.075, ys[9]), (0.075, ys[3]))
arr(ax, (0.075, ys[3]), (cx-W/2, ys[3]))
box(ax, 0.82, ys[9], 0.29, 0.080, "输出所得最优\n可行方案", fp=FLOW_CNS)
arr(ax, (cx+0.20, ys[9]), (0.675, ys[9]))
ax.text(0.635, ys[9]+0.017, "是", fontproperties=FLOW_CNS)

# 动态事件到达后只更新剩余任务，并重新进入同一搜索流程。
box(ax, 0.82, ys[2], 0.29, 0.105, "动态事件触发\n保留已执行任务\n更新车辆状态", fp=FLOW_CNS)
arr(ax, (0.675, ys[2]), (cx+W/2, ys[2]), ls=(0, (3, 2)))

fig.savefig(
    os.path.join(HERE, "figure_1_algorithm_flow.pdf"),
    format="pdf",
    facecolor="white",
    bbox_inches="tight",
    pad_inches=0.02,
)
print("written figure_1_algorithm_flow.pdf")
