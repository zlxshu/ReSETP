# SCOUT3-A 混合车队效应探路

终态：`MEASURABLE_EFFECT`；`formal_result=false`。

## FACT

算例固定为 `cn-cy-100c-01-V2-LOCATIONS`，五档 0/25/50/75/100%，每档 10 种子；每个碳盲/碳感知搜索均为三个视角各 25000 次迭代，无无改善早停。

## INFERENCE

结论：有效应。最大档间差为 `{'metric': 'mean_aware_full_model_cost_cny', 'left_level': 0, 'right_level': 50, 'difference': -973.3009593406132, 'relative_percent_vs_left': -18.80981537302709}`；观测到的响应层为 `['charging', 'vehicle_type', 'route']`。

## DECISION

本组只回答效应是否可测，不升级为正式论文结果，也不选择论文保留机制数。
