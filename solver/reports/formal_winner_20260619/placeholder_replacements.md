# Placeholder Replacement Ledger

Formal CSV root: `solver/reports/formal_winner_20260619/parallel_units/combined`

## Replaced in `docs/paper_submission_final/paper_main.tex`

- Section 4.6, two-layer carbon paragraph: `3298.8 kgCO2e` -> `2330.7 kgCO2e`.
  Source: `tables/t6_two_layer_carbon.csv`, row `CV-only`, `total_carbon_kg=2330.666`.

- Section 4.6, two-layer carbon paragraph: `1935.2 kgCO2e`, `1885.6 kgCO2e`, `49.7 kgCO2e`, and `78.6 kgCO2e` were rechecked against the new formal T6 source and remain valid after rounding.
  Source: `tables/t6_two_layer_carbon.csv`, rows `混合择时` and `混合即充`.

- Section 4.6, F5b pressure-test paragraph: added an explicit provenance boundary stating that F5b is a separate high-carbon-price pressure output, not an extension of the formal T7 realistic price/quota grid.
  Source boundary: F5b figure points are written to `figures/f5b_carbon_stress.csv` during backfill, with `source_means_csv` and `source_seed_detail_csv` columns pointing to `solver/reports/parallel_r2_stress_final`.

## Not Replaced by E1-E7

- F5b pressure-test values such as `42`, `3222`, `800`, `1600`, `1305`, `1214`, `1086`, `57`, `13%`, `30倍`, and `2%` are not E1-E7 terminal values. They are retained only as the separately labelled pressure-test result because the formal E4 grid in this rerun covers carbon-price factors `0.5, 1, 2, 4` by quota factors `0.5, 0.8, 1.0, 1.2`, not the high-price stress ladder up to `64x`.
