# S5 v2 unified artifacts

Decision: `PASS_S5_ARTIFACTS` (v2). The earlier v1 materialization is preserved and superseded.

## Scope

This run is deterministic materialization from sealed S1/S2/S3/S4/P1 artifacts; it runs no solver and does not edit TeX or any protected evaluator. The v2 output contains Table 4, Table 5, renamed representative Table 6, renamed Figure 4, a 10-row China81 summary (three city groups × three contiguous tier bands plus Overall), and three global paired tests. It does not generate an A1 81-row appendix. The old v1 A1 files remain only as historical provenance.

The nine sealed tiers are reported in contiguous bands S=(10,15,20), M=(25,50,75), and L=(100,150,200); this is an aggregation-only reporting rule and does not alter the raw ledger.

## Naming and statistics

The output maps `cv_only` to HGS-F, `naive_ev` to HGS-E, `mechanism_ev` to HGS-M, and retains MV-HGS-SP. China81 cells are means across instances of each instance's Best and seed-average exact costs. Pairwise tests compare MV-HGS-SP with each single-view arm at the common instance-seed level using a two-sided Wilcoxon signed-rank statistic with zero differences discarded, tie-corrected normal approximation, and three-comparison Holm adjustment.

The registered S2 exception `S2-INFEASIBLE-UNIT-001` remains visible: HGS-E is feasible on 404/405 units, and its one affected instance uses four feasible seeds for Best/avg; the failed raw row was not rerun, replaced, filtered, or overwritten.

Table 6 and Figure 4 are convergent-run quality/CPU disclosures, not equal-compute evidence.

Integrity flag: HASH_CONTAMINATED_APPLEDOUBLE; AppleDouble sidecars were removed before hash refresh.

Integrity flag: HASH_CONTAMINATED_APPLEDOUBLE; AppleDouble sidecars were removed before the final hash refresh. Raw data files were not overwritten.
