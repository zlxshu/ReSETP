# PyVRP 0.13.4 候选工具探针

判定：`PASS_PYVRP_0134_CANDIDATE_TOOL_PROBE`。本探针只求解一个3客户合成硬时间窗实例，没有读取Solomon算例或BKS，也没有授权正式搜索。

已核对官方wheel哈希、独立Python环境、单线程变量、0.13.4建模API、路线读取、统计点与逐迭代耗时增量，并验证Tbest必须由耗时增量累加后取得。该证据只把PyVRP固定为候选外部强基线；E7步骤1—6证明和最终工具冻结完成前，正式Solomon搜索仍被禁止。
