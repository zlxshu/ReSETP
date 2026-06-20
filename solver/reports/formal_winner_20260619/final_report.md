# ReSETP Winner-Kernel Formal Rerun Report

Formal lane: `solver/reports/formal_winner_20260619`

## Environment Fingerprint

- Pre-commit HEAD observed during final validation: `8336322e841623fb00622d4f82c4be0eb2e472e6`
- Python: `/opt/anaconda3/bin/python3.13`
- Python version: `3.13.9`
- NumPy: `2.3.5`
- `PYTHONHASHSEED=0`
- Winner flags:
  - `SETP_ALNS_CRUSH_TRUE_REPAIR=0`
  - `SETP_ALNS_CRUSH_ROUTE_ELIMINATION=0`
  - `SETP_ALNS_CRUSH_TRUE_ACCEPTANCE=0`
  - `SETP_ALNS_CRUSH_LOCAL_SEARCH=0`
  - `SETP_ALNS_CRUSH_ADAPTIVE_Q=0`

## Stage 0 Gate

Source: `stage0_system_worker_gate/gate_report.md`

- Gate: `PASS_SYSTEM_WORKER_SELF_CHECK`
- ALNS mean: `4878.331796187524`
- ALNS seed2: `4779.053444002934`
- Fair SA mean: `5346.986857132418`
- Zero violations: `True`
- Official-by-seed and alpha-UCB-by-seed matches: `True`

## Formal Runner Summary

Source manifest: `parallel_units/combined/formal_runner_manifest.json`
Compact RunKey ledger: `runkey_summary.csv`

- Total manifest rows: `471`
- Completed rows: `471`
- Failed rows: `0`
- Nonzero violation rows: `0`
- Rows below 16000 actual evals: `0`
- Experiment run counts: `E1=30`, `E2=141`, `E3=60`, `E4=160`, `E6=70`, `E7=10`
- E2 manifest note: one early stale `DR-ALNS` row remains in the merged manifest for provenance, but formal export/backfill excluded DR-ALNS; generated T3 contains no `DR-ALNS`.

## Generated Sources

Formal CSV root: `parallel_units/combined`

- Tables: `T3=4`, `T4=15`, `T4 seed detail=30`, `T5=6`, `T6=3`, `T7=16`, `T8=7`, `T9=91` rows.
- Figures: `F1 nodes=224`, `F1 lines=65`, `F2 curves=16080`, `F2 finals=140`, `F3=2`, `F4=96`, `F5=16`, `F5b=8`, `F6=7` rows.
- F4 source scenarios: `carbon_aware` and `naive_return_charge`, 48 slots each.
- F5b source note: `figures/f5b_carbon_stress.csv` is a provenance CSV for the separately labelled pressure test and points back to `solver/reports/parallel_r2_stress_final`.

## Reporting Checks

- T3 display labels are standardized in generated TeX: `ALNS-Wouda -> ALNS`, `scikit-opt-SA -> SA`; no `DR-ALNS` appears in T3.
- T5 display labels are standardized: `无多场协同`, `无碳感知`, `均值碳强度`, `无碳交易`, `无收益公平`, `完整模型`.
- F4 PNG is non-empty: size `(2029, 1204)`, RGB variance sum `16860.053`.
- `docs/paper_submission_final/paper_main.tex` was updated from `3298.8 kgCO2e` to `2330.7 kgCO2e` for CV-only T6.
- F5b pressure-test provenance was clarified in the paper text.
- Placeholder replacement ledger: `placeholder_replacements.md`.
- Paper rebuild: `latexmk -xelatex -interaction=nonstopmode -halt-on-error paper_main.tex` completed successfully.

## Validation

- Solver tests: `166 passed, 1 skipped in 84.00s`
- RL tests: `102 passed in 9.86s`
- Forbidden model/evaluation files had no diff at final validation:
  - `solver/src/setp_solver/cost.py`
  - `solver/src/setp_solver/check.py`
  - `solver/src/setp_solver/search/evaluation.py`
