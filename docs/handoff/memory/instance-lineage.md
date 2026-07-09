# Instance Lineage (formal vs archive)

Updated: 2026-07-09

## Formal default (mandatory for E2 and later experiments)

| Field | Value |
|-------|--------|
| Set | **L-main v2** |
| Path | `models/data_bundle/generated_instances/L-main/` |
| Family | **threeshift only** (三班倒) |
| Size ladder (9) | 10, 15, 20, 25, 50, 75, 100, 150, 200 |
| Stability slice | `-01` only → **9 instances** |
| Names | `L-main-threeshift-{size}c-01` |
| Registry | `solver/src/setp_solver/search/instance_registry.py` |
| Manifest | `models/data_bundle/generated_instances/L-main/l_main_benchmark_manifest.json` |

Source copies: `e2_benchmark/threeshift/e2-threeshift-{size}c-01` (including newly generated 10/15/20/25 on 2026-07-09).

## ARCHIVE_ONLY (keep for reference; do not use as formal E2 default)

| Set | Role |
|-----|------|
| `L-main_mixed23_archive_20260709` | Previous mixed vanilla+multidepot+threeshift 23-set |
| `L-main_legacy_pre_23` | Older 3-entry L-main |
| `e2_benchmark` vanilla / multidepot | Generation pool / diagnostics |
| `e2_benchmark` threeshift `-02/-03` | Stability expansion pool (Tier2/3 only) |
| `E-UK100_01...` / 100-01-24h | Historical £4878 anchor lineage |
| Pre-2026-07 T3 CSV under `baselines/e2_alns/e2_final_closure_20260703` | Material on **old** e2/mixed names — archive for method, not formal numbers after L-main v2 |

## Alias map

`e2-threeshift-{size}c-01` → `L-main-threeshift-{size}c-01` (see `E2_TO_LMAIN_ALIAS` in instance_registry).

## Decision log

- 2026-07-09 user: formal set = **9 threeshift ladders only**; mixed 23 and 100-01 not formal.
- Generator: `THREESHIFT_SIZES` extended to 9 steps in `models/scripts/build_e2_benchmark_instances.py`.
