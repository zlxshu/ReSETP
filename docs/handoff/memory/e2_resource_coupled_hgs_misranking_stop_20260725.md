# E2 资源耦合 HGS 代理误判门记忆节点

2026-07-25，用户批准在保留三视角 HGS 备份且不复活历史失败路径的前提下，先验证
“HGS 的简化代理是否错杀完整模型下更优客户顺序”这一因果前提。

六个冻结 `HGS-M` witness、每个 96 个固定动作候选由 6 workers 完成零搜索审计。
576 个候选中只有 32 个能由完整模型完成，严格代理排序逆转为 3/6 任务，但完整模型
严格改善为 0/6，代理前八名漏掉最优改善为 0/6，合格规模为 0。正式判
`STOP_RCE_HGS_NO_VERIFIED_PROXY_MISRANK_HEADROOM`。

该候选永久停止，不得增加候选、换动作、换题、换 witness、调阈值或转入搜索救援。
三视角 HGS 和 corrected China81 v7 保持不变，只作为受保护备份；本结果不证明
三视角存在因果互补，也不授权 E3、BKS/SOTA、论文性能或 `1+1>2`。

权威终局：
`docs/handoff/e2_resource_coupled_hgs_misranking_audit_final_stop_20260725.md`。
