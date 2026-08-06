# SCOUT3-C 非线性充电效应探路

终态：`MEASURABLE_EFFECT`；`formal_result=false`。

## FACT

在 `cn-cy-100c-01-V2-LOCATIONS` 与 v3 默认 25% 车队上，10 种子逐一配对比较 `L100_control` 与 `NL90_mild`；每臂三个视角各 25000 次迭代，无无改善早停。85% 指标是用户指定的暴露诊断；NL90 的实际折点仍是 90%，没有改曲线。

## INFERENCE

结论：有效应。最大配对差为 `{'seed': 1, 'metric': 'nl90_minus_linear_cost_cny', 'difference': 0.0, 'relative_percent': 0.0}`；效应层为 `['charging']`。

## DECISION

本组仅判断效应可测性；不因不利或零差结果改变曲线、种子、算例或预算。
