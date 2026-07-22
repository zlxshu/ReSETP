# S3 代表题四臂正式批任务卡

只有在 S2 `PASS_S2_FULL_THREEVIEW` 后启动。代表题先按冻结输入做零搜索预选：客户数、车场数、需求标准差/均值、平均时间窗宽度/16 小时、以及按 EV 满电电量除以“所属车场到客户的半载 EV 行驶能耗”并截断到 1 的平均可达率；五特征在 81 题内分别 z-score，取离特征中位向量最近者，并列按 `instance_id` 字典序。登记写出后不得看求解结果换题。

代表题 × 种子 1–10 × 四臂：`cv_only`、`naive_ev`、`mechanism_ev` 单视角收敛，以及完整 `MV-HGS-SP`（沿用 P3 的 mechanism 母体、旋转视角 continuation 和精确 SP）。每个单元用完整 `complete_china81_route_skeleton`/`exact_china81_score` 复核；不改变 evaluator、实例、视角或停止规则。结果 raw 增量写入，已有 `OK` 键断点跳过，非 OK 不覆盖并触发 HALT。

轨迹是 exact incumbent 在公共初始解、母体 epoch、SP/continuation epoch 边界被观察到的改善点；保留实际 elapsed seconds，不把 PyVRP proxy cost 冒充 exact cost。每个单元保存解 witness，供 S4 独立复算。

产物：`representative_registration.json`、`raw_runs.csv`、`trajectories/`、`witnesses/`、`metadata.json`、`decision.json`、`artifact_hashes.json`、`report.md` 和最后的 `done.json`。AppleDouble 旁车不入哈希；发现时标记并清理后重算。
