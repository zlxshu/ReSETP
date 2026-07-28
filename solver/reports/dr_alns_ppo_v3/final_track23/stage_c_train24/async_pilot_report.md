# Async Block PPO Pilot

Training completed. This is not a performance verdict until `evaluate_policy` writes the 100-01 comparison table.

Completed episodes: 1831.
Valid block steps: 7200.
Stale episodes discarded: 31.
Final policy version: 148.
Device: `cuda`.
Shared baseline by bundle: `True`.

GPU use is limited to the main-process PPO model, batch tensors, and gradient updates; solver rollout remains CPU-bound.
