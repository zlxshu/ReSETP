# DR-ALNS-PPO v2 100k Smoke

This smoke does not modify the formal runner or manuscript.

Each `env.step()` performs one full candidate solution scoring. The reported
`actual_evals` values come from the shared evaluator budget counter, not from
PPO inference calls.

Gate versus random: `HALT_RANDOM`.
Gate versus AlphaUCB-in-env: `FUTURE_WORK`.

If the 100k smoke does not beat random on held-out bundles, this lane remains a
wiring/debug task. If the 1-2M pilot does not beat AlphaUCB-in-env on the same
winner operators and 16000-eval budget, the result is a learnable alternative
rather than evidence that DRL scheduling significantly improves the kernel.
