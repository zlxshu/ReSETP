# SCOUT-D：随机归属基准

**结论：HALT_PRESEARCH_RANDOM_LABEL_DEPOT_CARDINALITY_MISMATCH。**

FACT：旧正式规则读取 `source_p_sequences.csv` 的 `Uniform_Unbalanced`、replicate 01；本算例前 100 个标签包含 0、1、2、3 四组。目标算例 `cn-cy-100c-01-V2-LOCATIONS` 只有 `D_chengdu`、`D_chongqing` 两个车场。旧 `capacity_rank_alignment` 使用 `zip(..., strict=True)` 将需求排序组与容量排序车场一一配对，直接执行得到：`ValueError: zip() argument 2 is shorter than argument 1`。

DECISION：未采用取模、丢组、合组或重新抽签，因为这些都是任务未批准的新分组规则。本基准及其处理臂 10 个种子均未启动搜索；20 条计划行原样保留在 `raw_runs.csv`。

HALT：因此本基准无法给出“处理后比未处理好多少”。这不是不利数值，而是输入规则与算例车场数不相容的技术停止。
