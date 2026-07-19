# 机制路线仓库最低成本增量门

判定：`STOP_ROUTE_POOL_FUSION_NO_STRONG_INCREMENTAL_SIGNAL`。

Neither pre-registered task produced a genuinely mixed route pool that strictly beat both expert-processed parents.

本门只回答路线仓库是否在旧开发题上出现增量信号。HGS 适配器只提供路线，不是公平的完整模型 HGS 基线；本结果不能写入正式 E2 或论文性能表。

|题目|HGS+专家|ALNS+专家|路线仓库+专家|HGS路线|ALNS路线|严格双胜|
|---|---:|---:|---:|---:|---:|---|
|L-main-multidepot-25c-01|784.089977026|669.123940595|669.123940595|0|4|False|
|L-main-multidepot-50c-01|1648.684477066|1491.641723036|1491.641723036|0|8|False|

停止纪律：若本门失败，不在这两题上改路线分数、仓库大小或题目；若本门出现阳性，也只能先冻结一组从未看过结果的新富模型题，再做三种子确认。

首次写盘出现 macOS AppleDouble 旁车文件，已标
`HASH_CONTAMINATED_APPLEDOUBLE_CLEANED_BEFORE_FINAL_AUDIT`并在最终审计前清理；
原始 CSV 与判定未改，正式哈希从清理后的四个主体文件重算，旁车从未纳入哈希。
