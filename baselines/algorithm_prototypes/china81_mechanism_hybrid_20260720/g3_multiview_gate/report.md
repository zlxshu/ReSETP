# China81 G3：MVHGS-ALNS 三题门

机器结论：`PASS_MVHGS_ALNS_THREE_CASE_ZERO_LOSS_SIGNAL`。

- `mvhgs_alns_vs_pyvrp_hgs_cv_only`：1 胜 / 2 平 / 0 负。
- `mvhgs_alns_vs_pyvrp_hgs_naive_ev`：1 胜 / 2 平 / 0 负。
- `mvhgs_alns_vs_project_alns`：2 胜 / 1 平 / 0 负。

MVHGS-ALNS 同时保留燃油路线、朴素异构车队和机制感知车队
三个种群的完整模型精英，再把最优精英交给机制 ALNS 后期强化。
因此机制视角有利时可以进攻，不利时不会覆盖保守种群的好解。

计算边界：三种群并行使用三个 worker，名义墙钟搜索时间与对手
相同，但 CPU 总量更高。这一门只证明多视角架构的质量和稳健性，
不证明等 CPU 效率；正式结论前必须补 CPU 平衡敏感性和多种子。
