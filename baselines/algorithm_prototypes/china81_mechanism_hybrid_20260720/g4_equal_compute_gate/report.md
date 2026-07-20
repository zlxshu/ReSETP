# China81 G4：MVHGS-ALNS 等算力多视角价值门

机器结论：`HOLD_MVHGS_ALNS_EQUAL_COMPUTE_GATE`。

- `mvhgs_alns_vs_homogeneous_cv_only`：1 胜 / 0 平 / 2 负。
- `mvhgs_alns_vs_homogeneous_naive_ev`：1 胜 / 2 平 / 0 负。
- `mvhgs_alns_vs_homogeneous_mechanism_ev`：1 胜 / 2 平 / 0 负。

候选和三个对照都使用三个 HGS 种群、相同单种群时长、三个
worker，以及同样的机制 ALNS 收尾。唯一差别是候选让三个
种群看不同的路线代价，而对照把算力重复在同一种视角。

边界：只是一组种子和三道开发题，证明多视角有增量价值，
尚不能替代多种子和正式 China81 统计。
