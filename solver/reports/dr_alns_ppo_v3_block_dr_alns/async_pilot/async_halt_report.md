# Async Block PPO Halt Report

## Bottom Line
异步架构代码已经接上，完整性是好的，但吞吐不够，不能启动 72000 block-step pilot。

这次不是 solver 语义问题，也不是 worker 环境漂移：6/6 episode 都完整跑到 16000 eval，零违约，worker 全是 `/opt/anaconda3/bin/python3.13` + numpy `2.3.5`。

真正的问题是成本：self-check 用 6 actor 跑完 6 个完整 episode 花了约 112.8 分钟，吞吐只有 399.1 block steps/hour。按 72000 block steps 估算，要 180.4 小时。这个规模不能作为当前机器上的“小 pilot”。

## Gate Result
`HALT_ASYNC_SELF_CHECK`。完整性通过，但 busy ratio = 0.560，低于门禁 0.60。更重要的是 projected training time 过长。

## Evidence
| bundle | seed | block_steps | best_obj | actual_evals | wall_minutes | violation |
|---|---:|---:|---:|---:|---:|---:|
| E-UK100_02__u0_seed2_24h_20251113 | 1 | 125 | 3527.251637 | 16000 | 25.8 | 0 |
| E-UK24h-三班-150 | 2 | 125 | 5312.742616 | 16000 | 53.3 | 0 |
| E-UK24h-三班-200 | 3 | 125 | 7116.722566 | 16000 | 112.7 | 0 |
| E-UK100_02__u0_seed2_24h_20251113 | 4 | 125 | 3594.753889 | 16000 | 26.9 | 0 |
| E-UK24h-三班-150 | 5 | 125 | 5353.593306 | 16000 | 55.4 | 0 |
| E-UK24h-三班-200 | 6 | 125 | 6947.796362 | 16000 | 104.8 | 0 |

## Decision
不启动 pilot，不做 100-01 PPO 对照，因为训练门禁没有过。这里最诚实的结论是：异步采样解决了“同步等待”的结构问题，但在真实 150/200c 训练集上，完整 episode 太贵，当前 72000 block-step pilot 不现实。

## Next Engineering Options
下一步如果继续救 PPO，应先缩小学习问题，而不是硬训：可以做 100c-only 机制 pilot、训练期低 eval_budget curriculum、或用已完成 block traces 做离线/上下文 bandit。只有这些低成本门禁证明能超过 `random_block`，再回到完整 16000 eval。
