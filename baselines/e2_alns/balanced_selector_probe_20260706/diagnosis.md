# Balanced Selector Probe Diagnosis

Verdict: `A4_BALANCED_SELECTOR_PROMISING`.

This is a diagnostic-only scheduler probe, not formal T3.

Profile summary:
- A0_MAIN_LOCAL_SEARCH: mean_gap=-0.004385253026182812, entropy=0.5479450509066646, top1=0.5102399430998055, top2=0.7646329728259733
- A4_BALANCED_SELECTOR_LOCAL_SEARCH: mean_gap=0.00048527397136235187, entropy=0.8227620351716587, top1=0.24319320523414537, top2=0.4628254343482945
- LNS_TRACE_REFERENCE: mean_gap=0.0, entropy=UNKNOWN, top1=UNKNOWN, top2=UNKNOWN

A4 vs A0: wins=23, losses=18, ties=7.

Support gates:
- a4_mean_gap_improves_vs_lns: True
- wins_vs_a0_at_least_losses: True
- normalized_entropy_higher_than_a0: True
- top1_top2_pair_share_lower_than_a0: True
- zero_fail_under_eval_infeasible_protected: True
