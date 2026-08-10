---
name: dcrex-independent-architecture-correction-20260809
description: "DCREX 未退役、旧 PyVRP 复用方案被退回、自研算法须完全独立运行"
metadata:
  node_type: memory
  type: user_decision_and_correction
  effective_date: 2026-08-09
  status: active
---

# DCREX 与独立算法边界更正

`USER DECISION`：开源 HGS 和新算法必须完全剥离、各成体系、运行时不相互调用。开源 HGS 只作独立冻结基线；自研算法不得调用 PyVRP 的种群、交叉、局部搜索、控制层或编译扩展。

`CORRECTION`：`duty_hgs_pdca_redesign_for_user_approval_20260809.md` 提出的“快速 SREX＋PyVRP 局部搜索＋PyVRP 种群”路线已被用户退回，不得施工。其全局指派、整日车辆匹配和非线性充电 DP 只保留为设计素材。

`FACT`：DCREX 当初因 Lei、Hao 与 Wu（2026）在同类多车场时间窗算例中的完整设计和消融阳性证据被引入，用来替换没有文献阳性证据的随机整车块交叉。当前 DCREX 已实现且真实运行；PR17A 十种子中，混合版对快速版 5 胜 5 负、平均成本只好 1.4、平均耗时 2.18 倍。公开 28 例单种子中自研对冻结母体 12 胜 16 负，双方跑满 20 分钟的 13 个大例为自研 0 胜 13 负。

`CORRECTION`：上述结果支持“当前 DCREX 的单位时间增量不足”，不支持“DCREX 已被用户决定退出”。旧设计中的退出只是代理建议，用户现已明确质疑；代码没有删除或停用 DCREX。P29 继续待用户决定。

`FACT`：当前自研入口仍直接导入 PyVRP 的种群、惩罚、SREX、局部搜索和编译搜索对象，未满足最新独立边界。因此，现有试跑证明的是“依赖 PyVRP 的 Duty-HGS 可以运行但效果不理想”，没有证明“完全独立的新算法”技术闭合或有效。

`BOUNDARY`：下一步先提交完全独立算法的流程图、伪代码、模块来源、接口、计算瓶颈和最小试跑设计。施工和 DCREX 处置仍由用户批准；本条不替用户选择保留、改造或退出。
