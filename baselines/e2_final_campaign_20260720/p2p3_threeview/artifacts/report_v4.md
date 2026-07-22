# S5-REV-V4 unified artifacts

Decision: PASS_S5_ARTIFACTS_V4.

This is a deterministic presentation and registered-observation rebuild. It does not run a solver and does not modify any sealed raw ledger, witness, evaluator, cost model, statistical input, or main TeX. All v3 files and the v3 hash manifest are preserved.

## Table repairs

Table 5 uses the requested instances header, two-line Best./avg. headers, BKS-relative error percentages formatted to two decimals, and row-wise minimum-error bolding. Its source values remain the P1 decision and raw ledger values.

Table 6 keeps the sealed S3 returned costs, converts CPU from seconds to minutes, uses the second header row 值 and CPU, and bolds the minimum value and minimum CPU independently within each algorithm column across the ten seeds and Min/Avg/Max rows.

The route table converts C001--C050 to 1--50, Guangzhou to 51, and Shenzhen to 52 in bracketed paths. The route audit covers each customer exactly once. The mean num and total load-rate cells are dashes; all other source values are retained.

The China81 summary retains the registered S2 exception S2-INFEASIBLE-UNIT-001 and independently bolds Best. and avg. row minima. Its CSV retains source precision; the TeX display is formatted to two decimals.

## Figures

Figure 3 is generated from the sealed February 2025 48-slot CSV for the three registered typical profiles: Beijing 2025-02-20, Guangdong 2025-02-16, and Chongqing 2025-02-24. The source values are converted to gCO2/kWh by multiplying by 1000.

Figure 4 uses the approved S3-TRAJ-CURVE-DEF-001 definition: historical snapshot skeletons are completed and scored offline with the full model, and the plotted quantity is the monotone best-so-far. It uses the pre-registered average-nearest seeds {'MV-HGS-SP': 9, 'cv_only': 3, 'mechanism_ev': 3, 'naive_ev': 9}. The 40/40 sealed final costs match exactly and the table costs are unchanged. The trajectory data retains the registered HGS-M/seed10 observation 2364.589958517462 versus its sealed table cost 2365.8780971446868; that historical value is trajectory-only and is never substituted into Table 6/Table 8 or any summary.

The S2 HGS-E infeasible unit remains disclosed under the registered statistical rule; no failed unit was rerun or resampled. This revision therefore changes presentation and the explicitly approved observation definition only.

Integrity flag: HASH_CONTAMINATED_APPLEDOUBLE; AppleDouble sidecars were removed before hash refresh.
