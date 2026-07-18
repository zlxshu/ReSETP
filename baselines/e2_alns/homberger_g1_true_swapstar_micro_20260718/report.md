# Homberger 真正 SWAP* 最小边际门

- 判定：`PROMOTE_TRUE_SWAPSTAR_TO_G1_INTEGRATION_REVIEW`
- 机械门：True
- 方向门：True
- 完整 G1 已运行：False
- 配对数：6
- 平均改善：0.003832056%
- 不退化：4/6
- 最差改善：-0.002331200%
- 平均时间开销：-54.205%
- 各实例接受动作：{'C1_2_1': 15, 'R1_2_8': 15}
- 总实耗：14.477s

本门复用冻结 baseline-B40 检查点，每臂只新增 5 次完整评价；没有读取 BKS、Solomon 参考解或中国正式结果。即使晋级，也只表示值得设计正式接入，不表示通过 12×3×1600 的 G1。

## 配对明细

- C1_2_1 seed=1: improvement=0.008182141%, distance_delta=-81.749124, time_overhead=-0.154%
- C1_2_1 seed=2: improvement=0.006434213%, distance_delta=-64.280522, time_overhead=-14.184%
- C1_2_1 seed=3: improvement=0.008182141%, distance_delta=-81.749124, time_overhead=-26.580%
- R1_2_8 seed=1: improvement=-0.002041958%, distance_delta=19.793660, time_overhead=-92.944%
- R1_2_8 seed=2: improvement=-0.002331200%, distance_delta=24.757618, time_overhead=-95.435%
- R1_2_8 seed=3: improvement=0.004566999%, distance_delta=-46.365061, time_overhead=-95.930%
