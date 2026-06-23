# Prompt 09i - Evidence-bound reoptimization confirmation

Run this only after `09h_parameter_evidence_review.md` has been executed and its report identifies at least one evidence-justified scenario that flips or near-flips mixed <= all-CV in fixed replay.

If 09h did not identify such a scenario, do not run this prompt. Write a short HANDOFF note saying 09i is blocked by the 09h verdict.

## First read

- `HANDOFF.md`
- `AGENTS.md` or `CLAUDE-FABLE-5.md` for the honesty/anti-sycophancy/evidence-first rules only
- `baselines/e2_alns/largescale_allcv_diagnostic.md`
- `baselines/e2_alns/parameter_evidence_review.md`
- `docs/handoff/parameter_evidence_brief_20260623.md`
- any 09h data files under `baselines/e2_alns/parameter_evidence_review_data/`

## Goal

Confirm, by true reoptimization rather than fixed replay, whether an evidence-bound non-carbon parameter scenario solves both problems:

- story/regime: mixed fleet is genuinely optimal or competitive at 100c/150c/200c under fixed real carbon price;
- algorithm: the E2 ALNS can reliably find those mixed solutions and no longer loses to the all-CV/GLNS-LNS path simply because the instance has become all-CV dominated.

## Boundaries

Do not modify `prices.py`, generated bundles, `cost.py`, `check.py`, `evaluation.py`, or algorithm semantics. Use in-memory `dataclasses.replace(DEFAULT_PRICES, ...)` only. Keep `carbon_price=0.05034` fixed.

Do not include 40 km/h as a cross-city default unless 09h explicitly classified the scenario as urban/local and the report says the paper is testing that fork.

Do not run a broad grid. Run only the scenario or scenarios justified by 09h.

## Required experiment

For each 09h-approved scenario:

- instances: `e2-threeshift-100c-01`, `e2-threeshift-150c-01`, `e2-threeshift-200c-01`
- seeds: start with 1-3; expand to 1-5 only if time permits and the first pass is not clearly negative
- algorithms: current E2 ALNS path and the 09d/09f all-CV/GLNS-LNS reference path
- budgets: 100c up to 300s/seed; 150c and 200c up to 900s/seed
- final check: all rows re-evaluated and checked independently under the same override

Report best, mean, std, paired wins, violations, route count, CV count, EV count, charging kWh, public kWh, occupancy cost, and carbon components.

## Verdicts

Use exactly one:

- `CONFIRMED_HIGHWAY_MIXED_AND_ALNS_RECOVERS`: evidence-bound highway/regional scenario makes mixed competitive and ALNS mean/best recover against GLNS-LNS.
- `CONFIRMED_URBAN_SCENARIO_ONLY`: urban/local scenario works, but it is not valid as the cross-city default.
- `MIXED_EXISTS_SEARCH_UNSTABLE`: good mixed best exists, but mean/std/paired wins remain unreliable.
- `ECONOMIC_ALLCV_REMAINS`: even evidence-bound modern parameters leave all-CV better on 200c.
- `HALT_REOPT_COLLECTION_COST`: true reoptimization could not be collected within budget.
- `HALT_ARTIFACT_MISMATCH`: 09h artifacts or checkpoint costs do not reproduce.

## Deliverables

Create:

- `baselines/e2_alns/evidence_bound_reopt_confirmation.py`
- `baselines/e2_alns/evidence_bound_reopt_confirmation.md`
- `baselines/e2_alns/evidence_bound_reopt_confirmation_data/`

Append `[M1]` to `HANDOFF.md` with the verdict and artifact commit hash. Commit all artifacts. Do not push unless asked.

If the verdict is positive, do not immediately edit `prices.py`. Prepare a follow-up parameter formalization plan that explicitly lists which paper scenario, vehicle class, and evidence source justify the change.
