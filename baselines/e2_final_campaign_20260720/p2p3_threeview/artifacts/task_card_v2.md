# S5-REV-V2 统一产物任务卡

本任务只从已封存的 S1/S2/S3/S4/P1 证据确定性生成表和图，不启动求解器，不修改 raw ledger、witness、评价器或主 TeX。

v2 的论文算法名按 `docs/handoff/algorithm_naming_map_20260722.md` 映射：`cv_only`=HGS-F、`naive_ev`=HGS-E、`mechanism_ev`=HGS-M、MV-HGS-SP 保持不变。v2 不生成附录 A1 或任何新的 81 行逐题表；China81 只生成三城市群×三连续规模层+Overall 的正文汇总源 CSV/TeX。旧 v1 A1 与 v1 产物原样保留为历史证据。

封存的九个客户规模 tier 按连续三档聚合：S=(10,15,20)、M=(25,50,75)、L=(100,150,200)。每个格内先按算例计算五种子 Best/avg，再对算例取均值；`cn-jjj-200c-01-V2-LOCATIONS` 的 HGS-E/seed 2 按审批条目 `S2-INFEASIBLE-UNIT-001` 记为不可行、不重跑，该算例的 HGS-E Best/avg 用其余四个可行种子并在报告披露。

全量统计输出 MV-HGS-SP 对 HGS-F/HGS-E/HGS-M 的同算例同种子配对胜平负、Wilcoxon 符号秩原始 p 值和三比较 Holm 校正 p 值。表6/图4使用论文名；私有批为收敛式并披露 CPU，不作等算力主张。图4继续按视觉合同输出 PDF、300 dpi PNG 和曲线 CSV。
