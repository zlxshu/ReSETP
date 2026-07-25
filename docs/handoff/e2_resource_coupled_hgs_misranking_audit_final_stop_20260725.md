# E2 资源耦合 HGS 代理误判因果门终局

日期：2026-07-25

合同：`E2-RCE-HGS-MISRANK-001`

终态：`STOP_RCE_HGS_NO_VERIFIED_PROXY_MISRANK_HEADROOM`

## 本门回答的问题

本门没有运行新算法，也没有修改封存成绩。它只检查一个因果前提：现有 HGS 的
`mechanism_ev` 代理，是否会把完整 China81 模型下更好的客户顺序错误地排到后面，
从而为“在 HGS 教育阶段加入资源耦合评价”留下可验证的改进空间。

冻结样本为三个规模各两个封存 `HGS-M` witness，共六任务。每任务从原 witness
独立生成 96 个固定动作候选，合计 576 个；不连续接受、不迭代、不按结果调动作。
所有候选均通过共同完成器、完整检查器和精确评分器判定。

## 工程门

六个 worker 完成六份封存 witness 的独立重放，576 行候选结构账闭合；候选完整
目标评价数为 0，搜索次数为 0，接受候选数为 0。监督器正常结束，保护文件哈希
无漂移，判 `PASS_RCE_HGS_ZERO_SEARCH_ENGINEERING_GATE`。

## 正式因果门结果

- 576 个固定动作候选中，32 个可由完整模型完成并独立验解，544 个无法形成可行的
  全燃油完成方案。
- 按动作分组，可行数分别为：relocate 1/144、swap 9/144、segment reversal
  18/144、tail exchange 4/144。
- 六任务中存在严格代理排序逆转的任务为 3/6，未达到预登记的 5/6。
- 存在完整模型严格改善的任务为 0/6，未达到预登记的 4/6。
- “完整最优改善候选未进入代理前八名”为 0/6；覆盖的合格规模为 0。
- 监督器用时约 20.25 秒，六任务账本闭合，无异常、无保护文件漂移。

## 结论与边界

冻结样本没有支持“代理错杀了可改进客户顺序”这一因果解释。该结果不能证明所有
可能的资源耦合教育都无效，但已足以按预登记合同停止当前机制：不得增加候选、换
动作、换 witness、换题、放宽阈值或进入搜索救援。

三视角 HGS 与 corrected China81 v7 未修改、未重跑，继续作为受保护备份。本门
不证明三视角收益来自真实视角互补，也不授权 E3、China81 新全量、公开 BKS/SOTA、
论文性能或 `1+1>2` 主张。

## 权威证据

- 合同：`docs/handoff/e2_resource_coupled_hgs_misranking_audit_contract_20260725.md`
- 工程门：`baselines/e2_final_campaign_20260720/rce_hgs_proxy_misrank_gate_20260725/engineering/`
- 正式因果门：`baselines/e2_final_campaign_20260720/rce_hgs_proxy_misrank_gate_20260725/formal/`
- 实现前保护标签：`safety/e2-resource-coupled-education-before-implementation-20260725`
- 正式门前保护提交：`fd7735fd`
- 正式门前保护标签：`safety/e2-rce-hgs-misrank-before-formal-20260725`
