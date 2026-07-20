# 2026-07-20 MV-HGS-SP 阶段一算法结构冻结

当前算法身份冻结为 `MV-HGS-SP`，中文名“多视角混合遗传搜索—精确路线池重组
算法”。它使用三个真正的 PyVRP 0.12.2 HGS 种群形成不同路线视角，完整非线性
ReSETP 模型重排精英，最后用集合划分精确重组跨视角路线；重组不严格改善时保留
最好的完整 HGS 父方案。

必须保留身份纠错：PyVRP 0.12.2 是 HGS，0.13.4 是 ILS。旧 G3/G4/G5 多视角
结果属于 ILS 历史诊断，不得拿来支撑 HGS 故事。H0 之后的 HGS 证据均使用仓库内
`build/python_envs/pyvrp-hgs-0.12.2/bin/python`。

H4 开发门为 2 胜 1 平 0 负；H5 新题门为 2 胜 1 平 0 负；H6 三题三种子为
5 胜 4 平 0 负。H6 中 75 客户层 3/3 改善，平均约 0.128222%；150 客户层
2/3 改善、1 平，平均约 0.453327%；25 客户层 3 平。九个结果全部可行，34 项
相关测试和 Ruff 通过，H6 十个登记文件哈希一致。

边界：这些结果证明精确路线池重组相对同批三个 HGS 视角中最好的完整父方案有稳定
增量信号，但重组额外消耗算力；尚未完成等墙钟纯 HGS/ALNS 对比、China81 全量或
V13/BKS。公平和动态机制没有在本门形成独立搜索贡献，ALNS 后接探针没有贡献。
裁决为 `PASS_PRIVATE_DIRECTIONAL_ARCHITECTURE_FREEZE`，
`formal_search_allowed=false`、`stage2_allowed=false`。

H0 清单中的早期 `pyvrp_adapter.py` 哈希因后续扩展而漂移；H0 结果文件未改，
H6 当前源码及证据哈希全匹配。完整收口见
`docs/handoff/mv_hgs_sp_stage1_closeout_20260720.md`。

