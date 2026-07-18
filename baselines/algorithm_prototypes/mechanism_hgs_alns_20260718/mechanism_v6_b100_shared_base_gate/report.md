# 机制优先 ALNS v6：单次搜索 + 双精确解码小门

判定：`PASS_V6_MONOTONE_MECHANISM_DEVELOPMENT_GATE`。

## 大白话结论

当前 ALNS 先用满 100 次路线评分，把客户分组和顺序做好。然后车型—补能解码器在固定路线下选整套油电方案，碳排时解码器在固定路线和电量下选充电时刻。两个小账都不挤占路线评分，只接受改善，最后统一独立复算。

## 数字

九个配对任务中，v6 同时严格胜两套原装开源对照 9/9，严格胜新鲜同跑的当前 ALNS 9/9，非退步 9/9。
碳排时相对删减版严格胜 9/9，改善范围 0.033512%--0.088880%。
车型—补能解码器在 6 个实际改型任务上严格胜 6/6，改善范围 11.210959%--13.493405%；在 3 个已是最佳车型组合的任务上全部精确平局，不倒退。
两个解码器新增完整路线评分为 0；预算门=`True`。
新鲜同跑的九任务总墙钟：v6 7.733 秒，当前 ALNS 7.656 秒，解码开销 1.0%。

## 边界

This is a three-instance shared-base development gate on the current linear 280-kWh model. It proves only the fleet/charging pattern and time-varying-carbon depot-timing decoders. It does not prove nonlinear charging, time-varying electricity prices, cross-depot responsibility, profit fairness, dynamic replanning, formal E2 performance, China81 validity, or stage-2 readiness.
