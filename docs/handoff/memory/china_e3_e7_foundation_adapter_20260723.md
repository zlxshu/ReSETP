# 中国 E3–E7 适配底座（2026-07-23）

已建立 `baselines/china_e3_e7/` 中国专用基础适配层及机器合同 `data/ChinaInstances/china_e3_e7_foundation_contract_v1_20260723.json`。只读预检加载 81/81 中国 runtime bundle，确认 27 个区域—规模 cell、5805 条订单、E2 `MV-HGS-SP` 封存引用和论文占位接线；任务清单、四件套、配对统计、Holm 校正、图表规格和论文映射均已接好。

当前状态是 `PASS_FOUNDATION_ADAPTER_FORMAL_SEARCH_HELD`，不是科学结果通过。`formal_search_allowed=false`、`search_evaluations=0`、UK 仅存档且 E3–E7 raw CSV 无结果行。旧 UK E3–E7 runner 不作为中国入口；任何未来正式批次必须使用冻结算法和独立复算，并先完成明确的 release/审批记录。
