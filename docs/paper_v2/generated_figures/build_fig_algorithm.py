# -*- coding: utf-8 -*-
"""图1 本文算法流程图 / 图2 串行改进链与完整评价裁决——统一画风。
依据 2026-08-06 已定口径：搜索内核直接采用成熟混合遗传搜索，贡献为问题特化组件；
多视角分解已废止。限时MIP路线池重组的去留尚未裁定，图中以虚线框标为"可选"。
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





def box(ax, x, y, w, h, txt, ec=DARK, fc="white", fp=CN, lw=RULE_LIGHT, ls="-"):
    ax.add_patch(FancyBboxPatch((x-w/2, y-h/2), w, h, boxstyle="round,pad=0.006,rounding_size=0.012",
                                ec=ec, fc=fc, lw=lw, ls=ls, zorder=2))
    ax.text(x, y, txt, ha="center", va="center", fontproperties=fp, color=DARK, zorder=3, linespacing=1.5)

def dia(ax, x, y, w, h, txt):
    ax.add_patch(Polygon([[x, y+h/2], [x+w/2, y], [x, y-h/2], [x-w/2, y]], closed=True,
                         ec=DARK, fc="white", lw=RULE_LIGHT, zorder=2))
    ax.text(x, y, txt, ha="center", va="center", fontproperties=CNs, color=DARK, zorder=3, linespacing=1.5)

def arr(ax, p, q, color=DARK, ls="-", rad=0.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=8, lw=RULE_LIGHT,
                                 color=color, ls=ls, zorder=1,
                                 connectionstyle=f"arc3,rad={rad}"))

# ---------------- 图1：总流程 ----------------
fig = plt.figure(figsize=(5.0, 6.4)); ax = fig.add_axes([0.02, 0.055, 0.96, 0.905])
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
W, H, cx = 0.46, 0.062, 0.42
ys = [0.955, 0.865, 0.775, 0.665, 0.575, 0.485, 0.375, 0.245, 0.115]
box(ax, cx, ys[0], W, H, "读取订单、车场、有限实体车队\n与分时电价、逐时碳强度序列")
box(ax, cx, ys[1], W, H, "生成初始个体并经完整评价")
box(ax, cx, ys[2], W, H, "混合遗传搜索主循环：\n选择父代、交叉", ec=CARBON)
box(ax, cx, ys[3], W, H, "分阶段提名与\n最优改进局部搜索（详见图2）", ec=MONEY, lw=RULE_HEAVY)
box(ax, cx, ys[4], W, H, "实体车多趟排班补全\n与碳感知充电排程", ec=MONEY)
box(ax, cx, ys[5], W, H, "完整评价：完整成本与完整可行性", ec=MONEY)
dia(ax, cx, ys[6], 0.40, 0.105, "完整可行\n且严格改善？")
dia(ax, cx, ys[7], 0.40, 0.105, "达到停止条件？")
box(ax, cx, ys[8], W, H, "输出最好解：路线、车型、车场、\n趟序、充电、成本与排放")
for i in range(6):
    arr(ax, (cx, ys[i]-H/2), (cx, ys[i+1]+H/2))
arr(ax, (cx, ys[6]-0.052), (cx, ys[7]+0.052)); ax.text(cx+0.018, (ys[6]+ys[7])/2, "是", fontproperties=CNs)
arr(ax, (cx, ys[7]-0.052), (cx, ys[8]+H/2));  ax.text(cx+0.018, (ys[7]+ys[8])/2, "是", fontproperties=CNs)
# 否：不改善 -> 记录失败原因，同样进入停机判断
box(ax, 0.855, ys[6], 0.24, 0.055, "保留失败原因\n不顶替最好解", ec=GREY, fp=CNs)
arr(ax, (cx+0.20, ys[6]), (0.735, ys[6])); ax.text(0.665, ys[6]+0.016, "否", fontproperties=CNs)
ymid = (ys[6]+ys[7])/2
arr(ax, (0.855, ys[6]-0.0275), (0.855, ymid), color=GREY)
arr(ax, (0.855, ymid), (cx+0.012, ymid), color=GREY)
# 否：未停机 -> 回主循环
arr(ax, (cx-0.20, ys[7]), (0.075, ys[7])); ax.text(0.135, ys[7]+0.016, "否", fontproperties=CNs)
arr(ax, (0.075, ys[7]), (0.075, ys[2])); arr(ax, (0.075, ys[2]), (cx-W/2, ys[2]))
# 动态触发：事件到达后回到主循环重排剩余任务
box(ax, 0.855, ys[2], 0.24, 0.075, "事件触发：冻结已执行\n前缀、继承车辆状态", ec=CARBON, fp=CNs)
arr(ax, (0.735, ys[2]), (cx+W/2, ys[2]), color=CARBON, ls=(0,(3,2)))

fig.savefig(os.path.join(HERE, "figure_1_algorithm_flow.pdf"), format="pdf", facecolor="white")

# ---------------- 图2：分阶段提名与最优改进局部搜索 ----------------
fig2 = plt.figure(figsize=(5.8, 2.7)); a2 = fig2.add_axes([0.02, 0.12, 0.96, 0.80])
a2.set_xlim(0, 1); a2.set_ylim(0, 1); a2.axis("off")
yc = 0.60
box(a2, 0.085, yc, 0.135, 0.22, "交叉子代", ec=CARBON)
box(a2, 0.325, yc+0.175, 0.245, 0.20, "阶段一　路线邻域动作\n重定位·交换·段反转\n段重定位·尾段交换", ec=MONEY, fp=CNs)
box(a2, 0.325, yc-0.185, 0.245, 0.20, "阶段二　机制动作\n整车车型交换·充电时刻\n调整·整趟交换", ec=MONEY, fp=CNs)
box(a2, 0.560, yc, 0.115, 0.20, "按序拼接\n并去重", ec=DARK, fp=CNs)
box(a2, 0.775, yc, 0.185, 0.26, "最优改进局部搜索\n每轮取全局最优动作", ec=MONEY, fp=CNs)
box(a2, 0.945, yc, 0.075, 0.20, "入群", ec=CARBON, fp=CNs)
arr(a2, (0.1525, yc), (0.2025, yc+0.14)); arr(a2, (0.1525, yc), (0.2025, yc-0.15))
arr(a2, (0.4475, yc+0.175), (0.5025, yc+0.06)); arr(a2, (0.4475, yc-0.185), (0.5025, yc-0.06))
arr(a2, (0.6175, yc), (0.6825, yc)); arr(a2, (0.8675, yc), (0.9075, yc))
# 循环：未收敛则重新提名
arr(a2, (0.775, yc-0.13), (0.775, 0.245), color=GREY)
arr(a2, (0.775, 0.245), (0.163, 0.245), color=GREY)
arr(a2, (0.163, 0.245), (0.163, yc-0.055), color=GREY)
a2.text(0.470, 0.275, "本轮仍有改善则重新提名", fontproperties=CNs, color=GREY, ha="center")
a2.text(0.5, 0.095, "动作取舍一律由完整评价器裁决：路线补全为实体车排班，补能可行性由固定路线充电求解器（frvcpy）判定",
        ha="center", fontproperties=CNs, color=DARK)
a2.text(0.5, 0.012, "每代只将一个最终子代送入种群", ha="center", fontproperties=CNs, color=GREY)

fig2.savefig(os.path.join(HERE, "figure_2_serial_chain.pdf"), format="pdf", facecolor="white")
print("written both")
