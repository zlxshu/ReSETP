# E3--E7 技术底座候选与用户决策边界（2026-07-30）

状态：`PASS_TECHNICAL_FOUNDATION_OPTIONS_READY__FORMAL_HELD`。

本轮没有启动效果搜索，也没有批准任何方法变更。技术包位于
`baselines/china_e3_e7/mechanism_foundation_20260730/`：候选最小算例组合只涉及
`cn-prd-50c-01`、`cn-prd-100c-02`、`cn-prd-150c-01` 三题；E3 的 50/100 客户
0/25/50% 共同输入、E6 的 150 客户原责任输入和 E7 三规模各五条事件流均通过
零搜索构造。15 条 E7 流同时保存 JSON 与运行器 TSV，逐字段回读一致。三份受保护
文件未修改。

这些算例分工仍是候选，`case_plan_approval_status=AWAITING_USER_APPROVAL`。E7 的
逐阶段预算选择规则与数值同样未获批准。正式搜索保持 `formal_search_allowed=false`。

E5 方案 B 的代码仅作为未启用候选存在：把随机搜索候选的 `L_search/S_search` 与末端
路线池比较、独立证书闭合分开，末端两次评价仍保留在完整评价总账。结果盲复判包位于
`baselines/china_e3_e7/e5_option_b_assessment_20260730/`，只读取 150 条严格改进布尔
序列，不读取目标值或臂间差异。复判饥饿数为 32/56/80/160/240 档两臂均
12/9/7/5/5（分母 15）；240 档仍超过 20%。因此，即使用户以后批准 B，也必须从
320 档继续结果盲 pilot，不能直接进入正式实验。方案 A 未实现、未启用；A/B 决策
完全保留给用户。

针对性验收为 33 项测试全通过；两个新证据包的登记哈希零漂移。旧 3790 行
`e3e6_formal_20260729/run_e3e6_formal.py` 仍是未验证中间状态，不是新入口，也不得
作为已修好的正式 runner。
