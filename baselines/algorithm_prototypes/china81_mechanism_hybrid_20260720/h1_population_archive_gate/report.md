# China81 H1：HGS 种群完整模型重排门

机器结论：`PASS_HGS_EXACT_POPULATION_RERANKING_SIGNAL`。

九个配对中严格改善 6 个；全部不倒退：True；全部可行：True。

本门没有增加 HGS 搜索，只把同一次 HGS 最终种群中的
可行个体交给完整 ReSETP 模型重新判分。

边界：Seen development cases and one seed only. This isolates population re-ranking, not a final algorithm.
