# Task1 SA Fairness Audit

- Phase0 eval budget/runtime: None / Nones
- Prompt1 Phase2 eval budget/runtime: None / Nones
- Phase2 SA weaker by config: None
- Audit note: Phase0/Phase2 SA config audit not applicable for this explicit instance subset.

Fair SA means:
- Scale-150: mean=5754.712075, best=5670.480807, std=55.476091, routes=49.800
- Scale-200: mean=7601.907533, best=7461.505019, std=105.652291, routes=61.900

V2 crush claims must be computed against this fair SA baseline, not Prompt1 Phase2 SA.