# 09k Evidence-Bound Battery Spectrum Gate

Commit: `7fe3db60`.
Python: `/opt/anaconda3/bin/python3.13`; NumPy: `2.3.5`.
Frozen parameters: `v_speed_ms=25.0`, `carbon_price=0.05034`. Battery is varied only through in-memory overrides.
Command: `/opt/anaconda3/bin/python3.13 baselines/e2_alns/battery_spectrum_transition.py --full-gate --screen-eval-budget 500 --screen-runtime-small 90 --screen-runtime-medium 180 --screen-runtime-large 300 --full-battery-values 80 100 113 141 210 280 --full-eval-budget 3000 --full-runtime-small 180 --full-runtime-medium 300 --full-runtime-large 900 --task-timeout-buffer 90 --workers 3`.

## Verdict

`BALANCED_EVIDENCE_BAND_FOUND`.

The only strict balanced full-gate candidate is a literature benchmark anchor; full-gated current vehicle-class anchors were EV-dominant or near-boundary, so do not promote a modern default battery from this verdict alone.

Strict balanced candidates: `80.0`.
Current vehicle-class balanced candidates: `none`.
Literature-only balanced candidates: `80.0`.
Near-boundary but EV-heavy candidates: `100.0`.
Vehicle-class EV-dominant candidates: `100.0, 113.0, 141.0, 210.0, 280.0`.

## Override Audit

Phase 0 status: `OK`.

The runner uses explicit override warm starts because the base `run_alns_wouda` default construction path does not pass the override `prices` into `build_initial_solution`. Final rows are still independently `evaluate/check` replayed with the same override.

## Evidence Candidate Set

| battery kWh | eligible | diagnostic | tiers | sources |
|---:|---|---|---|---|
| 60.0 | True | False | literature_benchmark;strong_current_vehicle_class | IsuzuNRREV;Qiu2024 |
| 80.0 | True | False | literature_benchmark | Chen2023;Goeke2015 |
| 81.0 | True | False | conditional_van | MercedesESprinter |
| 82.6 | True | False | strong_current_vehicle_class | FusoECanter |
| 89.0 | True | False | conditional_van | FordETransit2025 |
| 100.0 | True | False | strong_current_vehicle_class | IsuzuNRREV |
| 113.0 | True | False | conditional_van | MercedesESprinter |
| 123.9 | True | False | strong_current_vehicle_class | FusoECanter |
| 140.0 | True | False | strong_current_vehicle_class | IsuzuNRREV |
| 141.0 | True | False | strong_current_vehicle_class | DAFXBElectric |
| 150.0 | True | False | strong_current_vehicle_class | MackMDElectric |
| 160.0 | False | True | diagnostic_threshold | DiagnosticBridge160 |
| 176.0 | True | False | strong_current_vehicle_class | RenaultTrucksETechD |
| 180.0 | True | False | strong_current_vehicle_class | IsuzuNRREV |
| 194.0 | True | False | strong_current_vehicle_class | FreightlinerEM2 |
| 200.0 | True | False | strong_current_vehicle_class | RenaultTrucksETechD |
| 210.0 | True | False | strong_current_vehicle_class | DAFXBElectric;InternationalEMV |
| 240.0 | True | False | strong_current_vehicle_class | MackMDElectric |
| 280.0 | True | False | strong_current_vehicle_class | VolvoFLFE2023 |
| 282.0 | True | False | strong_current_vehicle_class | DAFXBElectric |
| 291.0 | True | False | strong_current_vehicle_class | FreightlinerEM2 |

Source URLs and PDF paths are preserved in `evidence_matrix.csv`; values are exact source/configuration values, not equal-spaced guesses. Capacity basis follows each source (usable/installed/gross where stated) and is not silently normalized.

## Fixed Replay Scope

Checkpoint fixed replay rows: 1841/1890 OK.

This replay is limited to existing 09d/09f checkpoint JSON coverage, not the full 17-instance representative gate. It is therefore a screen, not the final fleet-composition verdict.

## Screen Transition

| battery | winners | all-EV | EV-heavy | balanced | CV-heavy | all-CV | mean EV share | eligible | sources |
|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 60.0 | 8 | 0 | 0 | 3 | 1 | 4 | 0.136 | True | IsuzuNRREV;Qiu2024 |
| 80.0 | 8 | 0 | 0 | 4 | 0 | 4 | 0.228 | True | Chen2023;Goeke2015 |
| 81.0 | 8 | 0 | 0 | 5 | 0 | 3 | 0.281 | True | MercedesESprinter |
| 82.6 | 8 | 0 | 1 | 3 | 0 | 4 | 0.229 | True | FusoECanter |
| 89.0 | 8 | 0 | 0 | 4 | 0 | 4 | 0.258 | True | FordETransit2025 |
| 100.0 | 8 | 0 | 1 | 3 | 0 | 4 | 0.340 | True | IsuzuNRREV |
| 113.0 | 8 | 0 | 2 | 4 | 0 | 2 | 0.499 | True | MercedesESprinter |
| 123.9 | 8 | 0 | 1 | 4 | 0 | 3 | 0.444 | True | FusoECanter |
| 140.0 | 8 | 1 | 2 | 2 | 0 | 3 | 0.526 | True | IsuzuNRREV |
| 141.0 | 8 | 1 | 2 | 2 | 0 | 3 | 0.526 | True | DAFXBElectric |
| 150.0 | 8 | 1 | 2 | 2 | 0 | 3 | 0.526 | True | MackMDElectric |
| 160.0 | 8 | 0 | 4 | 2 | 0 | 2 | 0.615 | False | DiagnosticBridge160 |
| 176.0 | 8 | 0 | 3 | 3 | 0 | 2 | 0.613 | True | RenaultTrucksETechD |
| 180.0 | 8 | 0 | 2 | 4 | 0 | 2 | 0.589 | True | IsuzuNRREV |
| 194.0 | 8 | 0 | 2 | 4 | 0 | 2 | 0.589 | True | FreightlinerEM2 |
| 200.0 | 8 | 0 | 2 | 4 | 0 | 2 | 0.589 | True | RenaultTrucksETechD |
| 210.0 | 8 | 0 | 2 | 4 | 0 | 2 | 0.589 | True | DAFXBElectric;InternationalEMV |
| 240.0 | 8 | 0 | 3 | 3 | 0 | 2 | 0.598 | True | MackMDElectric |
| 280.0 | 8 | 0 | 3 | 3 | 0 | 2 | 0.598 | True | VolvoFLFE2023 |
| 282.0 | 8 | 0 | 3 | 3 | 0 | 2 | 0.598 | True | DAFXBElectric |
| 291.0 | 8 | 0 | 3 | 3 | 0 | 2 | 0.598 | True | FreightlinerEM2 |

## Full-Gate Triggers

Triggered batteries: `60.0, 80.0, 81.0, 82.6, 89.0, 100.0, 113.0, 123.9, 140.0, 141.0, 150.0, 160.0, 176.0, 180.0, 194.0, 200.0, 210.0, 240.0, 280.0, 282.0, 291.0`.
Full-gate battery values actually requested: `80.0, 100.0, 113.0, 141.0, 210.0, 280.0`.

## Full Gate Transition

| battery | winners | all-EV | EV-heavy | balanced | CV-heavy | all-CV | mean EV share | eligible | sources |
|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 80.0 | 51 | 0 | 1 | 32 | 0 | 18 | 0.408 | True | Chen2023;Goeke2015 |
| 100.0 | 51 | 0 | 30 | 12 | 0 | 9 | 0.681 | True | IsuzuNRREV |
| 113.0 | 51 | 5 | 34 | 5 | 0 | 7 | 0.780 | True | MercedesESprinter |
| 141.0 | 51 | 14 | 32 | 1 | 0 | 4 | 0.877 | True | DAFXBElectric |
| 210.0 | 51 | 15 | 32 | 1 | 0 | 3 | 0.898 | True | DAFXBElectric;InternationalEMV |
| 280.0 | 51 | 16 | 31 | 1 | 0 | 3 | 0.898 | True | VolvoFLFE2023 |

## Output Files

- `baselines/e2_alns/battery_spectrum_transition_data/metadata.json`
- `baselines/e2_alns/battery_spectrum_transition_data/evidence_matrix.csv`
- `baselines/e2_alns/battery_spectrum_transition_data/battery_candidate_set.csv`
- `baselines/e2_alns/battery_spectrum_transition_data/phase1_override_audit.json`
- `baselines/e2_alns/battery_spectrum_transition_data/fixed_replay.csv`
- `baselines/e2_alns/battery_spectrum_transition_data/screen_raw_runs.csv`
- `baselines/e2_alns/battery_spectrum_transition_data/screen_winners.csv`
- `baselines/e2_alns/battery_spectrum_transition_data/screen_transition_summary.csv`
- `baselines/e2_alns/battery_spectrum_transition_data/full_gate_triggers.csv`
- `baselines/e2_alns/battery_spectrum_transition_data/full_gate_raw_runs.csv`
- `baselines/e2_alns/battery_spectrum_transition_data/full_gate_winners.csv`
- `baselines/e2_alns/battery_spectrum_transition_data/full_gate_transition_summary.csv`
- `baselines/e2_alns/battery_spectrum_transition_data/conclusion.json`

## Decision Boundary

Do not promote a battery value from this report automatically. If the only strict balanced value is a legacy literature anchor, treat it as a transition reference rather than a modern default. If no current vehicle-class value produces a stable balanced band, the next honest route is an operational-constraint scenario such as charging capacity, EV capital limit, or long-route eligibility, not more battery tuning.
