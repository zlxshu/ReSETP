# S4 表4路径明细修订任务卡（S4-REV-V2）

这是验收脚本修复，不是算法或数据重跑。保留 v1 的 `decision.json`/`report.md`/原始表与 witness；只对 S3 已封存的最佳 MV-HGS-SP witness 重新验收。

- 整解层面调用全局 `check_solution` 与 `exact_china81_score`，要求 0 违约、客户恰好覆盖一次、recorded/direct/exact 成本一致。
- 逐路线片段不调用全局检查器；只用同一 `cost.py`/调度入口重算距离、成本、时间、油耗、电耗、碳排放、num、装载率。
- 加总字段与整解值做浮点闭合；装载率按整解和路线的最大值闭合，不作加总。
- 输出 v2 四件套与 `route_details_v2.csv`/`best_solution_witness_v2.json`；AppleDouble 清理后标记并重算 hash。

禁止修改解、witness、`cost.py`、`check.py`、`search/evaluation.py`、`prices.py`、主 TeX、S3 raw 或任何算法参数。
