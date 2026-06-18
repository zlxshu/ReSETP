# Reduced-Full PPO Halt Report

- verdict: `HALT_REDUCED_FULL_TOO_SLOW_SYNC_ENV`
- reason: 147456-timestep episode-safe reduced_full training was too slow and produced zero completed episodes in the stability window. Continuing would be a multi-hour synchronous-env run, not a controlled small probe.
- next_step: move to block-level controller or offline imitation/action-value learning rather than long-training this per-step reduced action mode.
