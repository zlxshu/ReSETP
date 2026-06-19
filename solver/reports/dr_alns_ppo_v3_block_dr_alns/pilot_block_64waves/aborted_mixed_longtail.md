# Aborted Mixed Block PPO Pilot

The mixed 9-env pilot was stopped intentionally. It had correct system workers, but after roughly 20 minutes only one worker was active and no episode rows had reached `monitor.csv`. This is a synchronous VecEnv long-tail failure, not a PPO quality result. The next attempt uses `episode_bucketed` homogeneous phases so all parallel envs in a phase solve the same-size instance.
