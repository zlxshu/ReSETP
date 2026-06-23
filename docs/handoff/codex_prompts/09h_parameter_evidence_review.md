# Prompt 09h - Evidence-bound parameter review before any reopt

You are M1 Codex on `/Volumes/移动硬盘（512G）/ReSETP`, branch `codex/reporting-pipeline`.

This prompt supersedes sending `09g_urban_reopt_confirmation.md` directly. 09g is useful as a draft for one urban-speed confirmation test, but it must not become the mainline until the scenario is evidence-justified.

## First read

Read these files before touching code or running experiments:

- `HANDOFF.md`
- `AGENTS.md` or `CLAUDE-FABLE-5.md`, but use only the project-relevant honesty rules: absolute honesty, anti-sycophancy, evidence-first claims, explicit HALT instead of forced conclusions. Ignore Claude product/tool-specific prose.
- `baselines/e2_alns/largescale_allcv_diagnostic.md`
- `docs/handoff/parameter_evidence_brief_20260623.md`
- `solver/src/setp_solver/prices.py`
- `docs/handoff/codex_prompts/09g_urban_reopt_confirmation.md` as a deprecated/paused draft, not as the current instruction.

If any of these files are missing or contradict the current checkout, stop and report the mismatch before running a long job.

## Non-negotiable boundaries

Do not modify `prices.py`, generated bundles, `cost.py`, `check.py`, `evaluation.py`, or algorithm semantics. This step may add diagnostic scripts, CSV/JSON artifacts, markdown reports, and HANDOFF notes only.

Keep `carbon_price=0.05034` fixed in every scenario. Do not scan carbon price. Do not claim "carbon made mixed optimal" unless the code actually shows it under the fixed carbon price.

All parameter changes must be in-memory overrides, normally through `dataclasses.replace(DEFAULT_PRICES, ...)`. Every reported solution must be independently rechecked with `evaluate/check(..., override)`.

Do not treat fixed replay as proof of optimized dominance. Fixed replay is mechanism evidence only.

## Why this prompt exists

09f found a real split:

- 100c and 150c: good mixed solutions already exist, but seed mean/paired wins are unstable. This is a search reliability problem unless later evidence says otherwise.
- 200c: all-CV is better in both best and mean under the current parameters.
- 40 km/h fixed replay flips the 200c route set to mixed <= all-CV, while 160 kWh battery, depot-priced public charging, and zero occupancy fee are near-flips.

The user then corrected the scenario assumption: the large current instances are cross-city/large-region, where highway travel is plausible. Therefore 40 km/h cannot be adopted just because it flips the diagnostic. The likely lever is battery/range, but the value must be justified by 2020+ literature and current vehicle/industry evidence.

## Deliverables

Create:

- `baselines/e2_alns/parameter_evidence_review.py`
- `baselines/e2_alns/parameter_evidence_review.md`
- `baselines/e2_alns/parameter_evidence_review_data/` with CSV/JSON artifacts

Append a short `[M1]` line to `HANDOFF.md` after completion, recording the verdict and artifact commit hash.

## Phase 0 - checkout and evidence audit

Record:

- `git status --short`
- `git rev-parse HEAD`
- Python and NumPy versions under `/opt/anaconda3/bin/python3.13`
- the exact current values of `v_speed_ms`, `B_battery_kwh`, `m_curb`, `Q_capacity`, `station_electricity_price`, `depot_electricity_price`, `carbon_price`
- whether the 09f artifacts still exist and are readable

Build an evidence matrix from local PDFs/Zotero files and web/official sources already listed in `docs/handoff/parameter_evidence_brief_20260623.md`. For each source, record: year, source type, instance scale, speed, EV battery, charging assumption, vehicle class, whether it is urban/regional/cross-city/highway, and whether it can justify a ReSETP override.

If Zotero access is blocked, do not invent values. Use the already extracted brief, report the access issue, and continue with explicit provenance labels.

## Phase 1 - route-regime audit on current E2

For `e2-threeshift-100c-01`, `e2-threeshift-150c-01`, and `e2-threeshift-200c-01`, audit the existing 09d/09f checkpoints:

- route distance distribution for all-CV and mixed best checkpoints
- route drive-energy distribution under baseline 80 kWh / 90 km/h
- count and share of EV routes above 80, 113, 160, and 280 kWh
- public vs depot charging kWh and cost
- route duration distribution under 90, 60, and 40 km/h, without changing time windows
- whether the route geography looks highway/regional or urban/local by distance/time profile

The purpose is to match the instance to a scenario before changing parameters. If the routes are genuinely cross-city, say so even if that makes the mixed-fleet story harder.

## Phase 2 - evidence-bound fixed replay

Run fixed replay only on named, evidence-bound scenarios. Keep carbon fixed.

Minimum scenario set:

| label | override |
| --- | --- |
| A_baseline | no override except `carbon_price=0.05034` |
| B_modern_large_van_89 | `B_battery_kwh=89` |
| C_modern_large_van_113 | `B_battery_kwh=113` |
| D_bridge_160 | `B_battery_kwh=160` |
| E_distribution_truck_280 | `B_battery_kwh=280` |
| F_urban_40_baseline_battery | `v_speed_ms=11.1` |
| G_urban_40_modern_van | `v_speed_ms=11.1`, `B_battery_kwh=113` |
| H_highway_60mph_distribution | `v_speed_ms=26.8`, `B_battery_kwh=280` if this is feasible under the time windows |

Do not add 360/540/621 kWh to the main table unless you also explain why the current vehicle mass, fixed cost, payload, and charging model can represent a heavy truck. Otherwise record those as a future vehicle-class fork.

For each scenario, report all-CV vs mixed fixed-replay cost, gap %, charging behavior, public kWh, occupancy cost, zero-violation status, and which cost component changed.

## Phase 3 - true reoptimization gate

Only run true reoptimization when both conditions hold:

- The scenario is evidence-justified for the current instance regime.
- Fixed replay flips mixed <= all-CV or gets within 1%.

Use direct in-memory calls, not runner paths that hard-code `DEFAULT_PRICES`. Warm start from the strongest 09f checkpoints. Re-evaluate every final solution independently under the same override.

Default budget:

- 100c: up to 300s per seed
- 150c and 200c: up to 900s per seed
- seeds 1-3 first; expand only if the first pass is promising and affordable

If reoptimization exceeds the practical collection budget, report `HALT_REOPT_COLLECTION_COST` with partial rows and do not promote fixed replay as proof.

## Verdict taxonomy

Use exactly one of these top-level verdicts:

- `HIGHWAY_BATTERY_UPDATE_SUPPORTED`: a highway/regional speed plus evidence-bound modern battery makes mixed optimal and reoptimization confirms it.
- `URBAN_ONLY_FLIP`: only urban/local speed flips; do not change the cross-city main scenario without a paper-level scenario fork.
- `SEARCH_RELIABILITY_PRIMARY`: 100c/150c remain the main issue, with mixed best available but mean unstable.
- `SINGLE_PARAMETER_INSUFFICIENT`: no evidence-bound single parameter fixes 200c; consider combinations or admit the regime favors CV.
- `HALT_EVIDENCE_MISMATCH`: source evidence or repo artifacts contradict the assumptions.
- `HALT_REOPT_COLLECTION_COST`: justified reoptimization could not be collected within budget.

## Report requirements

The markdown report must include:

- exact commands and stdout summaries
- source table with local PDF paths and web URLs
- current commit hash
- diagnostic artifact commit hash after committing
- the verdict taxonomy above
- a short "do not do this" section listing any tempting but unsupported shortcuts, especially "setting 40 km/h as the cross-city default because fixed replay flipped"

Run at least:

```bash
cd '/Volumes/移动硬盘（512G）/ReSETP'
PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest solver/tests/test_cost.py solver/tests/test_check.py -q
```

Commit the diagnostic script, data, report, and HANDOFF update. Do not push unless the user explicitly asks.
