# Final Track17 Report

Final status: STOP_AFTER_METHOD_ABLATION
Final reason: Stopped after Track17 method ablation.

## Baseline Set
Healthy baselines: GA, VNS, SA, GWO, ACO, IWD
PSO exclusion: PSO adapter failed the common-referee health gate (3978 unique candidates but best_update_count=0, no candidate improved on warm start; search-direction failure, not an encoding bug); excluded from quantitative claims; root cause documented.

## Method Ablation
Verdict: MAIN_METHOD_SELECTED
Chosen main method: winner_kernel_true_repair_adaptive_q (winner_kernel+true_repair+adaptive_q)
Chosen gain vs plain_alns pct: 3.228262569500504
Component decisions: {"winner_kernel_charging_required": {"decision": "drop", "gain_vs_plain_pct": -3.1611261341384207, "gain_vs_winner_pct": -2.008986818764702, "label": "winner_kernel+charging_aware", "mean_cost": 733.4317008940101}, "winner_kernel_local_search": {"decision": "drop", "gain_vs_plain_pct": -2.5148739452317015, "gain_vs_winner_pct": -1.3699521989403285, "label": "winner_kernel+local_search", "mean_cost": 728.8371228792255}, "winner_kernel_sa_lns_cooling": {"decision": "drop", "gain_vs_plain_pct": -3.2466939346974018, "gain_vs_winner_pct": -2.093598968383756, "label": "winner_kernel+sa_lns_cooling", "mean_cost": 734.0400515378769}, "winner_kernel_scan_bridge": {"decision": "keep", "gain_vs_plain_pct": 1.8772185199106968, "gain_vs_winner_pct": 2.9730878508642666, "label": "winner_kernel+scan_bridge", "mean_cost": 697.6112147497954}, "winner_kernel_true_repair_adaptive_q": {"decision": "keep", "gain_vs_plain_pct": 3.228262569500504, "gain_vs_winner_pct": 4.309042970886651, "label": "winner_kernel+true_repair+adaptive_q", "mean_cost": 688.0058665686895}}

## Fair Comparison
Verdict: NOT_RUN
Main method:  ()
Mean gains vs baselines pct: {}
Median gains vs baselines pct: {}
Scale mean gains pct: {}
Wilcoxon p-values: {}

## Decision
DR static learning is not used as evidence in Track17; DR remains future work pending Track18 dynamic headroom and held-out tests.
Quantitative claims exclude PSO and use only the six Track16-healthy baselines.