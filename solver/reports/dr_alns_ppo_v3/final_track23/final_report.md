# Track23 DR-ALNS Standing Report

Final status: `TRACK23_COMPLETE`
Final reason: DR_PILLAR_QUALITY=站住, DR_PILLAR_EFFICIENCY=没站住, DR_PILLAR_DYNAMIC=未判

## Pillars

- DR_PILLAR_QUALITY: `站住`
- DR_PILLAR_EFFICIENCY: `没站住`
- DR_PILLAR_DYNAMIC: `未判`

## Stage Status

- Stage A: `NO_DESTROY_LEVERAGE_ANY_BUDGET` - All budget ladder rows are <1%; max=-0.960% at 25c_4000.
- Stage A2: `SKIP_A2_NO_LEVERAGE` - Stage A status=NO_DESTROY_LEVERAGE_ANY_BUDGET; learned-destroy training skipped.
- Stage B: `CARBON_MECHANISM_WEAK` - Default carbon ceiling is not the hard stop, but timing did not eat >=2%: avg=0.000%, ceiling=1.934%.
- Stage C: `NO_TUNING_PARITY_CLEAN` - DR stayed within -2% of the strongest non-DR opponent on every bundle; min_gap=-1.926%.
- Stage D: `NOT_RUN` -

## Claim List

- Now writable: DR no-tuning parity held against the strongest non-DR opponent in Stage C using a current 24d checkpoint; evidence `stage_c24_no_tuning_parity_rows.csv` and `stage_c_train24/best_val_checkpoint.json`.
- Not yet writable: learned-destroy efficiency needs Stage A leverage plus a clean Stage A2 pass.
- Not yet writable: dynamic pillar needs fixed-worker headroom plus a heuristic action that eats it.

## Evidence Files

- `stage_a_destroy_ladder_rows.csv`
- `stage_a_destroy_ladder_summary.json`
- `track22_carbon_timing_rows.csv`
- `stage_b_carbon_scenario_knobs.csv`
- `stage_c_train24/best_val_checkpoint.json`
- `stage_c24_no_tuning_parity_rows.csv`
- `stage_c_pilot16_clean_reval_rows.csv`
- `stage_d_track18/track18_headroom.csv`
- `stage_d_dynamic_summary.json`
- `track23_final_report.json`
