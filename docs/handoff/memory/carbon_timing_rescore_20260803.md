# XD-RESUME 碳择时新口径零搜索重打分（2026-08-03）

## DECISION：终态

任务终态为 `HALT_XD_CURRENT_CONTRACT_REQUIRES_SEARCH`，不是 `XD_CARBON_RESCORE_COMPLETE`。保存完整解在新计费口径下的减排/成本权衡方向不变，但大量保存解不满足 fleet authority v3；联合保存解还来自旧目标函数与旧可行域，因而不能证明当前合同下的正式 5.1 结论。

权威产物目录为 `baselines/china_e3_e7/carbon_timing_rescore_20260802/`。独立核验状态为 `PASS_INDEPENDENT_VERIFICATION`，终态文件为 `done.json`，详细口径与结果见 `report.md`、`summary.json` 和 `decision.json`。

## FACT：恢复边界与完整性

这是 `CORRECTION_NOTICE.json` 登记的第 4 次尝试在网络断流后的技术续跑，不是第 5 次尝试。恢复器逐条校验可用最终文件、`.tmp` 和检查点后，安全复用 15,240 条共同有效前缀，只重建缺失后缀 7,530 条；完整解档案和验证账本最终各 22,770 条。恢复期间每 200 条刷新数据和进度状态；全量重放得到的 `raw_runs.csv` 与已落盘文件逐字节一致。

`pre_registration.json` 恢复前后 SHA-256 均为 `fe0a984a1a1f1a388e32ae2ab94a6b91b6e23c4313f6c75d8d9f720f46927feb`。前三次尝试目录的全部普通文件及 AppleDouble 文件均原样保留，恢复前后全树哈希分别为：attempt1 `61ed461eaddb63376ce2aa41a0fcc007e6bb5988c9dbbb23c3028ab65d9740cb`，attempt2 `39ab468eaaec601526704e56daab4b0fe524f417a2940078d11c32b52973781d`，attempt3 `f2a2a663c80d286701f12d719d4984e9e39dfd418f375d01764a331819e589dd`。

技术恢复没有执行路径搜索：`route_search_executed=false`，`search_evaluations=0`。完整解为 22,770/22,770，冻结不变量失败为 0；这里不存在“缺完整源解”的文件缺口。

## FACT：固定路线新旧对照

固定路线为 405 个源解 × 28 个电网日 × 2 个动作臂，共 11,340 对、22,680 条。CARBON 相对 ASAP 的充电侧排放变化旧/新均为 -54.970372%，系统排放变化旧/新均为 -9.746263%，充电电费变化旧/新均为 +134.879777%。运营成本变化由 +1.907776% 变为 +1.913628%，增加 0.005852 个百分点；总成本变化由 +1.845375% 变为 +1.851005%，增加 0.005630 个百分点。

两臂路线总数均为 137,088，去重实体车总数均为 136,416，且 11,340/11,340 对的两臂实体车数相同。旧固定成本两臂均为 23,304,960 元，新固定成本两臂均为 23,190,720 元，故固定成本在配对差中抵消；成本百分比的小幅变化来自不变绝对差除以略低的新分母，不是两臂车辆使用差异。

## FACT：联合保存解新旧对照

COST_PLUS_CARBON 相对 COST_ONLY 的充电侧排放、系统排放、充电电费旧/新分别均为 -18.199896%、-2.679143%、-0.702261%；运营成本均约 +0.000045%。30/30 对实体车数相同。

PURE_CARBON 相对 COST_ONLY 的充电侧排放、系统排放、充电电费旧/新分别均为 -89.249723%、-13.935353%、+307.413380%；运营成本由 +2.486564% 变为 +2.561502%，增加 0.074939 个百分点。只有 `cn-prd-50c-01-V2-LOCATIONS__seed6` 少 1 辆、`cn-prd-50c-03-V2-LOCATIONS__seed8` 多 1 辆；由于汇总量是配对百分比的简单均值，两项 170 元不能直接抵消，平均固定成本变化为 +0.046296%。

## HALT：当前合同缺口与所需规模

固定路线有 13,832/22,680 条保存解未通过当前合同，涉及 6,916 对和 247 个源算例—种子单位；另有 8,848 条通过。联合 90/90 条均未通过，涉及 30 对。要形成当前合同下的正式结论，固定路线最小需替换这 247 个基础路线解，再做每个解 28 日 × 2 臂的零搜索重放；联合面板需 30 对 × 3 模式，共 90 次当前合同优化运行。本轮按边界 HALT，未擅自开跑。

## 证据定位

恢复脚本为 `baselines/china_e3_e7/recover_carbon_timing_rescore_archives_20260803.py`。四件套为 `metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`；另有 `solutions.jsonl.gz`、`validation_ledger.jsonl`、`summary.json`、`report.md`、`recovery_verification.json` 和 `independent_verification.json`。`artifact_hashes.json` 排除了自身、`._*`、隐藏运行目录和 `__pycache__`。
