# PPO 第二层修复与 Debug 最终报告

## 一句话结论

当前这条 per-step PPO 路线还不能长训。episode 切碎问题已经修好，但 PPO 仍没有学到有效控制；动作空间降维的第一刀有改善但不够，第二刀 reduced_full 暴露出同步 per-step 环境过慢，继续烧时间不合理。

## 关键数字

| 项目 | 100-01 mean cost | 说明 |
|---|---:|---|
| full PPO | 6085.924 | 原始 per-step PPO，策略塌缩，失败 |
| operator-only PPO | 5457.406 | 降维后明显好于 full PPO，但仍输强基线 |
| AlphaUCB | 4875.047 | 强 ALNS operator selector 基线 |
| random_full | 4765.030 | 强随机 winner-action baseline，不是弱随机 |

## Debug 结论

1. 策略塌缩是真的。full PPO 的 destroy 维 top probability 约 0.999，基本固定到 vehicle_type_swap。
2. reward 有误导风险。full PPO 的 accepted_rate 是 1.0，但 improved_best_rate 很低，说明它学到的是“容易被接受”的动作，不是“最终更好”的动作。
3. random_full 很强。它随机探索 winner-kernel 动作空间，100-01 上比 AlphaUCB 还略强，因此不能再当弱基线。
4. operator_only 说明动作空间过大确实是问题之一，但只降到 destroy/repair 仍不够。
5. reduced_full 在当前同步 per-step 环境下太慢，10 分钟没有完成 episode，继续跑会变成数小时赌局。

## 修复尝试结果

- operator_only verdict: `FAILED_OPERATOR_ONLY`。100-01 上 PPO operator_only 比 full PPO 好很多，但仍比 AlphaUCB 贵 `11.87%`，比 random_full 贵 `14.14%`。
- held-out 上 PPO operator_only 比 AlphaUCB 贵 `8.27%`，比 random_full 贵 `19.41%`。
- reduced_full verdict: `HALT_REDUCED_FULL_TOO_SLOW_SYNC_ENV`。原因是同步 per-step env 太慢，不能作为小 probe 继续长跑。

## 下一步建议

不要继续当前 per-step PPO 长训。下一步应改架构：优先 block-level controller，让策略每 100-500 个 ALNS step 选一次 operator mix；同时用 random_full/AlphaUCB traces 做 imitation 或 offline action-value warm start。这样才有机会成为真正的 DR-ALNS，而不是把 PPO 套在一个信用分配很差的 16000-step 环境上。

## 诚信边界

本轮没有改 solver 成本/约束语义，没有跑正式 E1-E7。所有上报评估行都是 actual_evals=16000 且 violation_count=0。当前没有证据支持“PPO 已经可领先第二强 20%”；这个目标只能作为后续架构升级后的研究目标。
