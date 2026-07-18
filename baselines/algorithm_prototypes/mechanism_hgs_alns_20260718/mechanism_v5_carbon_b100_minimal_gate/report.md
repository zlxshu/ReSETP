# 机制优先 ALNS v5：时变碳充电排时最小门

判定：`HOLD_V5_CHEAP_STRICT_DEVELOPMENT_GATE`。

## 结果

三规模×三共同种子共 9 个配对任务；预算、可行性与独立复算全部通过=`True`。
完整版同时严格胜两套固定原装开源对照 9/9，严格胜当前项目 ALNS 9/9，严格胜拿掉充电排时的等预算版本 8/9。
九对均保持路线、车型和充电量不变，只改变充电开始时刻；隔离见证 8/9，机制活跃见证 9/9。
相对拿掉该步骤的成本改善范围为 -0.027711%--0.074588%；每任务充电间接排放减少范围为 2.137190--18.467786 kg。
旧 20 客户共同值 `621.2913242409613` 已被一个保持路线、车型和充电量不变的可行方案严格改进，因此不是已证最优，反证状态=`True`。
九任务总墙钟：v5 7.520 秒，当前项目 ALNS 6.462 秒，v5 相对变化 16.4%。该短门只如实记账，不作正式速度结论。

## 为什么这个动作成立

路线回来以后，算法不再默认立刻充电，而是在不耽误下一次出车的整个窗口里比较所有可能改变碳账的时间分界点。路线、车型和充电量不动，便宜计算先选时刻，最后只用一次完整方案评分确认。这个动作直接对应时变电网碳强度，而不是通用拼接。

## 边界

This is a three-instance development gate. It proves a time-varying-carbon depot-charge timing component on the current linear 280-kWh development model. It does not prove nonlinear charging, time-varying electricity price, fairness, dynamic replanning, formal E2 performance, China81 validity, or stage-2 readiness.
