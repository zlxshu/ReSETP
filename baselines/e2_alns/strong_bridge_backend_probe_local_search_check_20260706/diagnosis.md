# A3 Strong-Bridge Backend Profile-Alignment Diagnosis

Verdict scope: diagnostic only, not formal T3.
Rows: 240/240; OK=240; fail=0.

Root-cause correction: this run separates backend-only from the current main profile with LOCAL_SEARCH.

Profile summary:
- A0_THROUGHPUT_ONLY: mean_gap_vs_lns=-0.0027550841310447025, unchanged_rate=0.5410776576661385, best_improved_rate=0.010956482629137445
- A3_BACKEND_ONLY: mean_gap_vs_lns=-0.01268965932170772, unchanged_rate=0.5409924374758114, best_improved_rate=0.013765258412392917
- A0_MAIN_LOCAL_SEARCH: mean_gap_vs_lns=-0.004385253026182812, unchanged_rate=0.5219023910633224, best_improved_rate=0.011338200531347405
- A3_BACKEND_LOCAL_SEARCH: mean_gap_vs_lns=-0.013673594831823434, unchanged_rate=0.5445287696596597, best_improved_rate=0.013980783614291468
- LNS_TRACE_REFERENCE: mean_gap_vs_lns=0.0, unchanged_rate=UNKNOWN, best_improved_rate=UNKNOWN

Comparison summary:
- BACKEND_ONLY: verdict=A3_BACKEND_ONLY_NOT_SUPPORTED, a0=A0_THROUGHPUT_ONLY, a3=A3_BACKEND_ONLY, wins=20, losses=24, ties=4, a0_mean_gap=-0.0027550841310447025, a3_mean_gap=-0.01268965932170772
- MAIN_LOCAL_SEARCH: verdict=A3_BACKEND_LOCAL_SEARCH_NOT_SUPPORTED, a0=A0_MAIN_LOCAL_SEARCH, a3=A3_BACKEND_LOCAL_SEARCH, wins=16, losses=24, ties=8, a0_mean_gap=-0.004385253026182812, a3_mean_gap=-0.013673594831823434