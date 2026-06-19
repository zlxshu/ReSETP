# Block PPO Throughput Halt Report

## Bottom Line
The V3 full gate passed, but the PPO pilot should not continue in the current SB3 synchronous VecEnv architecture.

This is not a claim that PPO failed to learn. The training runs did not produce valid episode data. The real failure is sampling throughput: synchronous vectorized PPO waits for the slowest DR-ALNS worker at every block step, and the solver has heavy-tailed step times. That collapses practical CPU utilization into long single-worker tails.

## Evidence
The strict full gate passed: 50/50 rows completed 16,000 evals after one official seed10 retry, zero violations, system worker `/opt/anaconda3/bin/python3.13`, numpy `2.3.5`. `official_winner_kernel` reproduced mean £4878.331796 and best £4779.053444.

The mixed 9-env block PPO pilot was stopped after roughly 20 minutes: all workers launched, but only one worker remained active and `monitor.csv` still had no episode rows.

The `episode_bucketed` rescue restored concurrent launch, but `block_size=128` still produced no completed 4096-eval episode after roughly 12 minutes because the phase was dominated by a single long-tail worker.

The `block_size=512` rescue reduced synchronization barriers but still produced no completed 4096-eval episode after roughly 9 minutes, again dominated by one long-tail worker. Larger blocks alone are not enough.

## Human Read
The chessboard is valid, but the training treadmill is wrong. We are asking PPO to train through SB3 synchronous vector envs, while each solver worker can take very different wall-clock time. That means eight workers often sit idle waiting for one slow worker. This is why CPU looks bad and why scaling timesteps would waste hours.

## Decision
Do not run longer SB3 synchronous PPO. The next real repair is architectural: build an asynchronous episode/block collector, or first train a lighter contextual bandit/offline selector from completed block traces. Only after the sampler produces many complete episodes per hour should PPO training resume.
