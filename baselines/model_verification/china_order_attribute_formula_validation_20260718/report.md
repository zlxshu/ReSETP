# 中国订单属性公式与时间窗联合抽样验证

结论：PASS。本验证未运行算法搜索，也未生成正式China81实例。

五档体积均正确映射为139/208/278/347/417 kg和6/9/12/15/18 min；公斤值仅为容量占比场景代理，服务时长仅为文献案例参数。

| 检查 | 结果 | 证据 |
|---|---|---|
| source_row_count | PASS | rows=1222 |
| window_summary | PASS | min=30.015509, median=45.6985725, max=59.974984 |
| joint_empirical_row_semantics | PASS | all rows retain volume, mapped demand, service duration, delivery-window start and width jointly |
| machine_contract_boundaries | PASS | status=APPROVED_ORDER_ATTRIBUTE_METHODS_BLOCKED_BY_STAGE2_INPUT_GATES, formal_search_allowed=False |
| tex_formula_and_boundaries | PASS | all required formula, boundary and citation tokens present |

边界：该PASS只验证订单属性方法、论文公式和手册同步，不启动阶段二，不授权正式实例或算法搜索。
