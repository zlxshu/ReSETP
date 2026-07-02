# Final Track21 Reclaim Report

Final status: HALT_INVALID_COMPARISON
Final reason: GWO invalid on E-UK50_01__curric_d2_s3_seed1_24h/seed902: INVALID_NOT_RUN.

## Method Ablation
Verdict: MAIN_METHOD_SELECTED
Reason: winner_kernel_true_repair_adaptive_q selected on Track21 validation; gain vs plain=3.228%.

## Fair Comparison
Verdict: HALT_INVALID_COMPARISON
Reason: GWO invalid on E-UK50_01__curric_d2_s3_seed1_24h/seed902: INVALID_NOT_RUN.
Mean gains vs baselines pct: {'GA': nan, 'VNS': nan, 'SA': nan, 'GWO': nan, 'ACO': nan, 'IWD': nan}
Scale mean gains pct: {}
Wilcoxon p-values: {'GA': nan, 'VNS': nan, 'SA': nan, 'GWO': nan, 'ACO': nan, 'IWD': nan}

## Track21 Notes
Track17/Track19 winner rows superseded by `SUPERSEDED_BY_TRACK21_FLEET_FIX` manifest.
PSO remains transparently excluded; comparison uses six Track16-healthy baselines.
DR worker contamination was fixed, but DR was not retrained in this Track21 reclaim run.