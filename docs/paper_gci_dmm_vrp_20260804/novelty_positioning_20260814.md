# 新颖性定位：与 Shi 等 2025 的分界（2026-08-14）

## 为什么单独立这份文档

2026-08-14 用户新增 29 篇（去重后）文献。其中 **Shi 等 2025, Expert Systems With Applications 273:126875**
（Zotero 条目 `JY2IQSFS`，附件 `XELF2U72`）与本文在**混合车队 + 协同 + 随时间变化的用电信号 + 碳目标**
四条轴上重合三条。这是目前检索到的与本文最接近的一篇，必须在引言的缺口句定稿前处理掉，
否则审稿人把这篇甩过来，本文的"新"就只剩算法。

本文档只记录 Claude 亲自逐页核过的原文事实，以及在其上做的推断（分开标注）。

---

## 一、Shi 等 2025 到底做了什么（FACT，逐页核对）

**题名**：The bi-objective mixed-fleet vehicle routing problem under decentralized collaboration
and time-of-use prices（PDF 共 17 页）

| 项 | 他们的做法 | 原文位置 |
|---|---|---|
| 车队 | 燃油车 + 电动车混合，同一车场同时停放 mE 辆电动车与 mIC 辆燃油车 | 第 4 页 §3.2 |
| 车场 | **单车场**。"Vertices 0 and N +1 correspond to the same depot" | 第 4 页 §3.2 |
| 协同 | 平台撮合的**接单选择**（分散式、部分信息共享）：企业把不划算的订单交给平台，别的企业挑走 | 第 4 页 §3.1 |
| 时变信号 | **分时电价** ρ(t)，分峰 T1／平 T2／谷 T3 三段 | 第 4 页 §3.2.2 |
| 充电策略 | **每次充满**。"we have chosen to assume full charging" | 第 4 页 §3.2 |
| 目标 | 双目标：f1 最大化利润、f2 最小化碳排放，用 ε-约束法求 Pareto 前沿 | 第 4–5 页 |
| 算法 | ε-约束 + 改进 k-means 时空聚类 + MS-ELS 混合进化 | 第 5–6 页 §4 |

## 二、最要害的一条：他们的电动车碳排放恒等于零（FACT）

碳排放目标函数（第 4 页 式(4)）：

```
min f2 = CER · Σ_{i∈V} Σ_{j∈V} x^IC_ij · f_ij(u_j) · d_ij
```

`x^IC_ij` 是**燃油车**走弧 (i,j) 的 0-1 变量。式中**没有任何电动车项，也没有任何电力排放因子**。
§3.2.1 全节只推导燃油消耗与载重的线性关系，再乘碳排放系数 CER。

第 6 页 Property 1 的证明把这件事说得不能再明白：

> "When the company serves every consumer through EVs in the collaborative network,
> carbon emissions will be minimal, that is, CER Σ Σ x^IC_ij f_ij(u_j) d_ij = 0."

即：**全部改用电动车 ⟹ 碳排放 = 0**。

同时，充电费用是时刻的函数（第 4 页 §3.2.3）：

```
P_E(τ_i) = ∫_{τ_i}^{τ_i + (B − y_i)/r} r · ρ'(t) dt ,   ρ'(t) = η · ρ(t)
```

`τ_i` 是到达充电站的时刻。

**推断（INFERENCE，由上面两式直接得出，无额外假设）**：
在 Shi 等 2025 的模型里，**什么时候充电只改变花多少钱，不改变排多少碳**。
充电时刻是一个纯经济决策变量。

## 三、本文与它的分界（这句话就是引言缺口句的内核）

本文的电动车充电排放 = 充入电量 × **该时刻电网碳强度**，碳强度逐时变化。因此：

> **在他们那里，充电时刻只搬动成本；在本文里，充电时刻直接搬动排放。**

进一步，本文与其余三处不同（均为 FACT 对照）：

1. **多车场 vs 单车场**：本文多车场且分属不同主体；他们单车场。
2. **协同的内容**：本文是跨车场的**客户重指派**并对协同收益做分配；他们是平台**接单选择**，
   且明写"平台与企业的总收入不变"，不涉及主体间的收益分配问题。
3. **充电量**：本文趟间按需补电；他们每次充满。充满假设下，充电量不是决策，只有充电时刻是。

## 四、这一篇反而变成了本文最好的靶子（判断，非事实）

它不是威胁，是证据。理由：这是 2025 年发表在 ESWA、把混合车队与协同与时变电力信号做到最全的一篇，
**它仍然把电动车当作零排放**。这说明本文开篇那句"电动化不等于减排"针对的不是稻草人，
而是 2025 年仍然活着的主流建模假设。

引言里的用法：不点名批评，而是作为"已有研究把时变电力信号当作价格信号"的代表，
指出价格信号与碳信号在时间上并不重合——谷电时段未必是低碳时段。
（**注意**：谷电≠低碳这一条本文尚未用中国电网数据核过，写进正文前必须先核，
否则就是本项目反复犯过的"推导出的数字未核前提"错误。见 memory `verify-field-before-stating-derived-number`。）

## 五、顺带捡到的一条：c^tr = 0 有文献依据了（FACT）

2026-07-12 用户拍板跨场费 c^tr = 0，当时是决策，没有文献锚。Shi 等 2025 第 4 页 §3.1 末段：

> "…the costs associated with inter-warehouse transfers are typically minimal compared to
> customer deliveries. Many studies on order sharing (Fernández et al., 2018; Soriano et al., 2023)
> often overlook the costs related to inter-warehouse transfers. Consistent with this trend,
> we also exclude inter-warehouse transfer costs from our order-sharing framework."

理由是"客户数远多于仓库数，转运成本相对客户配送成本可忽略"。本文算例正是这个形态。
**可用作 c^tr = 0 的假设说明脚注**，并可顺链引 Fernández 等 2018、Soriano 等 2023
（Soriano 2023 已是本文若干图型的第二母版）。

## 六、待办

- [ ] 引言缺口句按本文档第三节定稿（等三张待定图与正文串联一并处理）
- [ ] "谷电时段未必是低碳时段"必须用中国电网碳强度数据核实后才能写
- [ ] c^tr = 0 的假设说明脚注补上该出处
- [ ] Shi 等 2025 表 1 是"文献对照打勾表"（列：MO/CL/EV/TOU/TW/MF/CE）。本文表格清单已定为 10 张，
      **此处不重开**；仅记录该体例存在，若日后审稿要求补文献定位表再启用。
