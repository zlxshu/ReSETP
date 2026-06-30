# 09y EV-heavy Regime Synthesis

Evidence level: **PROBE / 非正式 T3**.

## Plain Reading

Goeke80 代表大实例转不出 EV-heavy：80kWh 下多数 CV→EV 被充电时间窗或插站约束拦住。280kWh 诊断已在 threeshift-150c 构造出非退化且更优的混合解，但算法大对比未按墙钟帽闭合，所以只能说 modern battery 场景有机制头寸，不能说 vanilla ALNS 已赢。下一步若继续 modern regime，先修 Stage 2 单任务硬超时和增量落盘，再重跑算法对比；否则算法创新主线转 DR-ALNS。

## Verdicts

- Stage 0: `Z_EV_PHYSICALLY_UNSUPPORTED_80KWH`
- Stage 1: `SKIPPED_NO_STAGE0_X`
- Stage 2: `HALT_COLLECTION_COST`
