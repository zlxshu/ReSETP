# Task1 SA Fairness Audit

- Phase0 eval budget/runtime: 16000 / 900.0s
- Prompt1 Phase2 eval budget/runtime: 4000 / 600.0s
- Phase2 SA weaker by config: True
- 100-01 seed1 reproduction cost: 5331.576889799002
- Phase0 target: 5331.576889799002
- Absolute delta: 0.000000000000

Fair SA means:
- 100-01-24h: mean=5346.986857, best=5166.498854, std=82.283460, routes=32.700
- L-main: mean=8319.837849, best=8180.722121, std=113.675307, routes=64.900

V2 crush claims must be computed against this fair SA baseline, not Prompt1 Phase2 SA.