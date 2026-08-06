# W2 车队 authority v3、冻结重锚与旧结果登记（2026-08-02）

状态：`W2_FLEET_AUTHORITY_V3_COMPLETE`。

## FACT：authority v3

用户已批准总量固定口径。旧 `num_ev(d)=max(1,ceil(0.25*R_d))` 公式废止，但 v1/v2 目录和哈希原地保留。新 authority 位于 `data/ChinaInstances/china81_finite_fleet_authority_v3_20260802/`，默认绑定位于 `solver/src/setp_solver/china81.py`；调用者仍可通过 `fleet_authority=` 显式选择 v1/v2。

v3 在 W1 合同（多趟开启、车场并发默认不设、固定成本按实体车计费）下使用两族确定性 EDF 路线见证和兼容 DAG 最小路径覆盖。五档仍用 Hamilton 最大余数分配。144 个车场的实体车上限合计 943；旧 X4 单趟总量为 1042；端点下界合计 830，有 85 个车场为同时覆盖五档在端点下界上增加共 113 辆。81 算例 × 5 档 = 405 单元全部认证，0/25/50/75/100% 均为 81/81，无违反项，路径搜索和正式实验均为 0。最小性只对登记的两族确定性路线见证成立，不冒充所有潜在路径的全局最优证明。

## FACT：冻结锚重置

四个长期红灯守卫已只更新活动 SHA 锚：E2 80 kWh 八个语义文件、PyVRP candidate probe、E4 manifest 的五个活动源码项、strong-bridge 对 W1 `cost.py` 的批准工作树哈希；旧 commit、旧 manifest、旧 probe metadata 和旧哈希均保留。v3 默认绑定又触发三个 10c 车队数字面锚，从旧 2/1、3/1、2/1 更新为 1/1。定向验收 11/11 通过。完整前后表见 `docs/handoff/frozen_baseline_reanchor_20260802.md`。

## FACT：旧结果引用状态

`docs/handoff/superseded_results_register_20260802.md` 已逐包登记 E2 五算法、E3、E4 405×28、E4 90 行、E5、E6 900 行与下游账本、E7、v1/v2 和旧车队诊断。旧目录未删除、未移动、未覆盖。数值或设定失效的包明确标为不得作为结果引用；公开 MDVRPTW 算法质量、W1 合同证据、逐位重放兼容性和页级文献证据按原范围保留。

## REGRESSION：全量测试

规范环境命令与 W1 相同，最终为 `907 passed, 1 skipped, 5 failed`。剩余失败为：

- 真实回归 2：`test_china81_shared_completion_20260720.py` 仍把每条路线直接占用一辆实体车，尚未接入多趟排班；一个单元的全燃油单调参照不满足 v3 车型上限，另一个把 3 条趟直接判为超过 2 辆。不能仅更新锚值转绿，断言保留。
- 未解决历史项 2：`test_e5_ablation.py` 的 carbon-aware 保存路线仍不可行；EV 翻转仍报告 `repair_logic_defect`。
- 旧契约 1：`test_ev_heavy_findability_gate.py` 仍要求旧按趟计费下候选严格改善；新按实体车计费后 `4954.204438573212` 不小于 `4923.553350198799`。断言保留待该历史门另行重定义。

本轮没有修改 `docs/paper_v2/paper_main.tex`、`solver/src/setp_solver/check.py` 或 `solver/src/setp_solver/search/evaluation.py`，也没有正式实验或路径搜索。权威交付为 `baselines/china_e3_e7/fleet_authority_v3_20260802/`。
