# E2 proportional true-LNS-middle 短门任务卡

目标：在不增加1600总评价预算、不改变正式起点和评价合同的前提下，修正上一短门的阶段比例失真，判断真正LNS中段是否值得进入未见种子4000门。

输入：`true_lns_middle_gate/`的27行证据、冻结E2的15个负例、L-main v3九档正式入口。

要读的事实源：`HANDOFF.md`、`docs/handoff/e2_legacy_items_1_6_9_execution_plan_20260711.md`、`true_lns_middle_gate/decision.json`和`paired_comparisons.csv`。

允许改的文件：`winner.py`中新候选入口、`e2_loss_recovery_gate.py`候选分发、对应测试、本任务文档和新证据目录。

禁止改的文件：`cost.py`、`check.py`、`search/evaluation.py`、`prices.py`、算例、冻结E2证据和LNS基线语义。

命令：先跑目标测试和2-eval烟雾；代码提交后才运行9组×`staged/proportional_true_lns_middle/LNS`×1600评价，共27行，最多3个CPU worker。

验收：27/27 OK、全部1600评价、零违规、保存解复算一致、hash和执行提交匹配；开发负例相对staged均值改善、至少2组由输LNS转为不输、全部9组均值改善、guard最差不得低于-2%。门槛与上一门完全一致。

停止条件：任一合同失败先停；科学门未过则关闭true-LNS路线，不调比例、不换样本、不直接跑4000或全量。

产物：`metadata.json`、`raw_runs.csv`、`paired_comparisons.csv`、`decision.json`、`artifact_hashes.json`、`report.md`、保存解和`verification.json`。
