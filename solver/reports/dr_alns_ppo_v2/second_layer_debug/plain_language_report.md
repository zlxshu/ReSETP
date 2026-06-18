# PPO 第二层诊断通俗报告

结论先说清楚：当前 PPO 不是因为 episode 切碎而失败了，那个问题已经修过。现在的问题是策略本身学偏了，学成了一个几乎固定的动作，而这个固定动作在 100-01 上明显输给 random_full 和 AlphaUCB。

在 100-01 上，本轮诊断看到的均值是：PPO `6085.924`，random_full `4765.030`，AlphaUCB `4875.047`。成本越低越好。

这说明 random_full 不能再被叫作弱随机基线。它是在强 winner-kernel 动作空间里随机探索，所以本身就是很强的对手。

目前不建议继续长训当前 PPO。下一步应先做动作空间降维和 reward 审计，优先顺序是：operator_only，小 q/threshold 动作空间，确认 reward 误导后再做 reward shaping。如果这些都失败，再升级到 block-level controller 或 imitation + RL。
