# Instance Lineage (formal vs archive)

Updated: 2026-07-10

## Formal default (mandatory for E2 and later experiments)

| Field | Value |
|-------|--------|
| Set | **L-main v3** |
| Path | `models/data_bundle/generated_instances/L-main/` |
| Family | **threeshift only** (三班倒) |
| Source-scale ladder (9) | 10, 15, 20, 25, 50, 75, 100, 150, 200 |
| Actual merged customers | 22, 34, 45, 55, 114, 163, 221, 322, 449 |
| Stability slice | `-01` only → **9 instances** |
| Names | `L-main-threeshift-{size}c-01` |
| Registry | `solver/src/setp_solver/search/instance_registry.py` |
| Manifest | `models/data_bundle/generated_instances/L-main/resetp-l-main-main-benchmark.v3.json` |
| Activation audit | `baselines/e2_alns/l_main_v3_activation/decision.json` = `LMAIN_V3_READY` |

Each active bundle is rebuilt from three complete Goeke child sources at
`0h/9h/18h`, with only the shifted third-shift tail beyond 24h removed.  The
first child supplies the shared `D0`/generated `D1` facility layout.

## ARCHIVE_ONLY (keep for reference; do not use as formal E2 default)

| Set | Role |
|-----|------|
| `L-main_mixed23_archive_20260709` | Previous mixed vanilla+multidepot+threeshift 23-set |
| `L-main_legacy_pre_23` | Older 3-entry L-main |
| `e2_benchmark` vanilla / multidepot | Generation pool / diagnostics |
| `e2_benchmark` threeshift `-02/-03` | Stability expansion pool (Tier2/3 only) |
| `E-UK100_01...` / 100-01-24h | Historical £4878 anchor lineage |
| `L-main_unverified_v3_pre_activation_20260710_74ce9045` | Pre-activation generated directory; preserved, not formal evidence |
| Pre-2026-07 T3 CSV under `baselines/e2_alns/e2_final_closure_20260703` | Material on **old** e2/mixed names — archive for method, not formal numbers after L-main v3 |

## Alias map

`e2-threeshift-{size}c-01` → `L-main-threeshift-{size}c-01` (see `E2_TO_LMAIN_ALIAS` in instance_registry).

## Decision log

- 2026-07-09 user: formal set = **9 threeshift ladders only**; mixed 23 and 100-01 not formal.
- Generator: `THREESHIFT_SIZES` extended to 9 steps in `models/scripts/build_e2_benchmark_instances.py`.

## 2026-07-10 reconstruction activation

The reconstruction contract is now active.  Generator commit
`48efe1208d2a5f56d481dd1defff4c143eb09bc0` produced the nine bundles;
the audit reported zero failures and zero shared-initial-solution violations.
The active manifest SHA-256 is
`bf904ef254aeeb1a76cb1308eae7a5caee14a814a15e1087254b024992c5d39c`.
Formal runners reject a missing or mismatched audit decision.  See
`docs/handoff/e2_lmain_reconstruction_design_20260710.md`.
