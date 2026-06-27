# Algorithm Comparison Full Retrospective - 2026-06-27

> Purpose: give Claude or another reviewer a clear, evidence-first reconstruction of the E2 algorithm-comparison thread from the first relevant diagnostic task through the latest Goeke80/100 wall-clock preflight.
>
> Scope limit: this file cannot literally reconstruct Claude Desktop messages that were never pasted into this Codex thread or written to repo files. It uses the visible user instructions in the Codex thread, `HANDOFF.md`, `MASTER_codex_takeover_plan.md`, 09-series prompts/reports, git history, and Codex memory indexes. When a statement is inferred from artifacts rather than verbatim chat, it is marked as such by context.

## 0. User's Actual Goal

The user was not asking for a cosmetic win table. The underlying goal was:

1. Make the E2 algorithm comparison scientifically defensible.
2. Keep the model/parameter story explainable from literature or real vehicle evidence.
3. Avoid a degenerate fleet story: not all-CV, not all-EV, but a practical mixed CV/EV fleet, roughly within a 20%-80% EV/CV usage band where later clarified.
4. Keep carbon price fixed at the real value; do not use carbon price as a tuning knob.
5. Do not invent parameters or constraints just to make the story work.
6. Do not silently change the mathematical model or TeX; if code and TeX diverge, fix the translation or synchronize explicitly.
7. Report in plain Chinese, with enough context for decisions, not terse agent labels.

The user's emotional through-line was also clear: they were running out of Claude credits and needed Codex to preserve continuity, but Codex repeatedly blurred diagnostic findings, implementation actions, and decision-level conclusions. This caused understandable distrust.

## 1. First Algorithm-Comparison Problem

Before 09e, the algorithm-comparison lane had already hit a major problem:

- E2 ALNS variants were not convincingly beating LNS/GLNS.
- LNS/GLNS is a general routing baseline without EV/carbon-specific machinery.
- If that baseline wins in the paper's key comparison, the claimed contribution of the carbon/EV-aware ALNS becomes weak.

The initial working hypotheses were:

1. ALNS might be too slow or iteration-starved.
2. SA acceptance or search operators might be inadequate.
3. The benchmark economics might make EV irrelevant, so EV/carbon-aware search has no advantage.

## 2. Early Algorithm Fix Attempts: 09c and 09d

### 09c - SA Acceptance Gate

Goal:

- Try to improve ALNS acceptance/search behavior so it can compete with LNS.

Implementation:

- E2 SA acceptance gate was run with ALNS variants.
- Report: `baselines/e2_alns/sa_acceptance_halt_report.md`.

Feedback result:

- Verdict: `HALT_HARD_TIMEOUT_NOT_PROMOTED`.
- 100 returned rows were zero-violation, but 35 rows hit hard timeout.
- On completed threeshift rows, ALNS still did not consistently beat LNS.

Meaning:

- This did not prove model infeasibility.
- It did prove that the SA-ALNS variant could not honestly be promoted.

### 09d - Throughput Gate

Goal:

- Test whether ALNS was losing simply because it was too slow per iteration.

Implementation:

- Added throughput/caching repairs.
- Report: `baselines/e2_alns/throughput_halt_report.md`.

Feedback result:

- Verdict: `HALT_TRUE_GLNS_BETTER_AFTER_THROUGHPUT`.
- Caching improved speed; ALNS became faster than LNS in eval/s on threeshift groups.
- But LNS still had better mean cost in 4/5 threeshift size groups.
- Paired threeshift result: ALNS wins 9/25, loses 16/25.

Meaning:

- "Iteration starvation" was not sufficient as the root cause.
- The lane had to stop and investigate the instance/economic regime.

## 3. Parameter Root-Cause Diagnostics: 09e and 09f

### User intent

The user wanted to know whether the all-CV/all-oil outcome was real economics or an artifact. They also asked whether fuel vehicles had carbon emissions recorded and whether those emissions entered the carbon price/penalty.

### 09e - Small Instance Diagnostic

Goal:

- Verify price override penetration.
- Break down all-CV, all-EV, and mixed solutions on small instances.
- Keep carbon price fixed.

Implementation:

- Script/report: `baselines/e2_alns/instance_param_diagnostic.py` and `.md`.

Feedback result:

- Override path worked.
- Small instances did not reproduce all-CV degeneration: mixed already won on the 09e selected small cases.
- CV carbon was correctly counted: direct fuel emissions entered total emissions and carbon cost.

Meaning:

- Carbon accounting was not missing.
- The all-CV problem was not universal; it was larger-instance/regime-specific.

### 09f - Large Instance All-CV Diagnostic

Goal:

- Move the diagnosis to large instances where LNS/all-CV actually looked strong.
- Distinguish "mixed exists but search unreliable" from "economic parameters really make all-CV better."

Feedback result:

- 100c/150c: best mixed solutions existed but mean/paired results were unstable. This pointed to search reliability/variance, not pure economic impossibility.
- 200c: all-CV was stronger in both best and mean. This looked like a real economic/parameter issue.

Meaning:

- The problem split by scale:
  - small: mixed already OK;
  - 100/150: search reliability issue;
  - 200: parameter/economic pressure against EV.

## 4. Speed vs Battery: 09g Paused, 09h Evidence Review

### User correction

The user correctly challenged the "40km/h urban speed" idea. Their instance scale is cross-city/regional; real logistics often uses highways. Therefore speed should not be casually lowered just because fixed replay flipped a result.

### 09h - Evidence-Bound Parameter Review

Goal:

- Use literature/vehicle evidence, not hand-tuned values.
- Keep speed at cross-city/highway if evidence supports it.
- Check whether old 80kWh battery was the real issue.

Implementation:

- Report: `baselines/e2_alns/parameter_evidence_review.md`.
- Carbon price fixed at `0.05034`.
- True reoptimization was run only after evidence/fixed-replay triggers.

Feedback result:

- Verdict: `HIGHWAY_BATTERY_UPDATE_SUPPORTED`.
- 90km/h remained compatible with UK strategic-road evidence.
- 280kWh had strong vehicle evidence from modern distribution trucks.
- In three-shift 100/150/200c, 280kWh reoptimization made mixed/EV solutions beat all-CV fixed reference. Example: 200c mean mixed/EV about 8616 vs all-CV fixed 8979, gap about -4.04%.

Meaning at that time:

- The old 80kWh battery looked like a plausible root cause for all-CV pressure in large cross-city cases.
- But this only proved "mixed/EV can beat all-CV"; it did not yet prove "balanced mixed fleet across scales."

## 5. Parameter Formalization and Immediate Reversal: 09i/09j, 280 Gate

### 09i/09j - Promote 280kWh

Goal:

- Formalize the evidence-supported 280kWh value.
- Synchronize code and TeX.

Implementation:

- `B_battery_kwh` was changed from 80 to 280.
- TeX parameter table and comments were synchronized.

Feedback problem:

- This promotion happened before a full fleet-composition gate.

### 280kWh Fleet-Composition Gate

Goal:

- Check whether 280kWh produces true mixed fleet or overcorrects into EV dominance.

Implementation:

- Runner/report: `baselines/e2_alns/fleet_composition_gate_280.py` and `280kwh_fleet_composition_gate.md`.

Feedback result:

- Verdict: `HALT_EV_DOMINANT`.
- Representative gate winners: 34 EV-heavy mixed, 16 all-EV, 1 all-CV, 0 balanced mixed.
- Mean EV share was very high.

Meaning:

- 280kWh fixed all-CV pressure but overcorrected toward EV-dominant behavior.
- The 280kWh default could not honestly support a "stable mixed fleet" story.

Process fault:

- Codex/Claude should have treated 09h as a candidate scenario requiring a composition gate before parameter promotion. The later gate corrected the conclusion, but the workflow created churn and user distrust.

## 6. Evidence-Bound Battery Spectrum: 09k

### User intent

The user agreed to a battery spectrum scan but insisted values must come from real literature/vehicle numbers, not arbitrary grids.

### Implementation

- Runner/report: `baselines/e2_alns/battery_spectrum_transition.py` and `.md`.
- Used evidence-bound battery values.
- Full gate used anchors: 80/100/113/141/210/280kWh.

### Feedback result

- Verdict text: `BALANCED_EVIDENCE_BAND_FOUND`, but the interpretation was subtle.
- Strict balanced behavior appeared at 80kWh, a legacy/literature benchmark anchor.
- 100kWh was near-boundary but mostly EV-heavy.
- 113/141/210/280kWh were EV-dominant.

### Meaning

- There is a transition curve from CV-dominant to EV-dominant.
- But current modern vehicle-class values did not produce a stable balanced band.
- 80kWh cannot simply return as the modern main scenario because earlier large-instance diagnostics treated it as too weak.

## 7. User Correction and Source-Bound Mixed Band: 09l

### User correction

The user explicitly said:

- 80kWh had already been diagnosed as too small.
- The goal is not 1:1, but at least practical balance, later clarified as 20%-80%.
- Current research trend can be EV-leaning.
- Battery values need real sources.
- The story must hold across all gradient scales and stability instances, not just one case.

### Implementation

- Runner/report: `baselines/e2_alns/source_bound_mixed_band_gate.py` and `.md`.
- Candidate pool excluded 80 as main candidate.
- Candidates included real sourced values such as 60, 81, 82.6, 89, 100, 113, 123.9, 140, 141, 150, 176, 180, 194, 200, 210, 240, 280, 282, 291.

### Feedback result

- Verdict: `BATTERY_ONLY_INSUFFICIENT`.
- Stage A ran 1311/1311 raw rows, no timeout/error.
- No non-80kWh source-backed candidate passed or near-passed across the full gradient.
- Low-end values sometimes looked mixed on average but failed by scale.
- 100kWh only passed 11/23 instances and began EV-heavy/all-EV behavior.
- 113kWh and above mostly became EV-heavy/all-EV.

### Meaning

- Battery capacity alone could not support the user's required cross-scale mixed story.

## 8. Structural and Operational Diagnostics: 09m, 09n, 09o, 09q

### 09m - Structure Audit

Goal:

- Investigate whether geography, depot/station layout, fleet count, or route eligibility explains why battery-only fails.

Feedback result:

- 75-200 was not a clean battery problem.
- Customer density and station proximity did not naturally force mixed behavior.
- A strong clue emerged: fleet count was effectively unbounded in the active code path, while metadata still had `num_cv/num_ev`.
- EV-heavy solutions could use many EV routes, far beyond metadata EV count.

Meaning:

- "Modern EV + unlimited EV availability" may explain EV dominance.

### 09n - Fleet Cap Diagnostic

Goal:

- Test whether EV/fleet caps could restore mixed behavior.

Feedback result:

- Existing winners did exceed metadata vehicle counts.
- But simple diagnostic caps did not yield a promotable solution.
- `goeke_total_cap` and `depot_scaled_cap` mainly failed initialization.
- `goeke_ev_cap_only` reduced EV dominance but fell near/below lower bound and showed fake balance.
- Verdict: `HALT_COLLECTION_COST`.

Meaning:

- Fleet availability is a real clue, but the diagnostic cap shell was not a formal solution.

### 09o - Charging Infrastructure Pilot

Goal:

- Test whether EV-heavy solutions rely on public charging or generous depot charging.

Feedback result:

- Verdict: `HALT_COLLECTION_COST`.
- Completed rows suggested EV solutions used depot charging almost entirely, not public fast charging.
- Peak depot concurrency could be high.

Meaning:

- Depot charging capacity/capital became a plausible next mechanism.
- But evidence was incomplete and not formal.

### 09q - Battery x Operational Constraint Map

Goal:

- Combine real battery candidates and operational constraints instead of single-point tests.

Implementation:

- Runner/report: `baselines/e2_alns/source_bound_operational_mix_map.py` and `.md`.
- It eventually produced a Stage A map.

Feedback result:

- Verdict: `BATTERY_OPERATION_COMBINATION_INSUFFICIENT`.
- No tested battery x operational-constraint combination kept the required 10-200 full-gradient screen inside the practical mixed band.
- Some rows looked balanced by route count but failed customer/demand/distance checks or were diagnostic-only.

Meaning:

- The simple operational-constraint probes did not produce a clean, promotable mixed scenario.

Process fault:

- Codex initially drifted toward isolated tests, especially 280kWh-focused tests, while the user wanted a complete source-bound battery-gradient x operations map. The user had to correct this.

## 9. Model-Semantics Shock: Hard Fleet Caps and Q

### User correction

The user clarified that vehicle number limits in the paper were already hard limits. They did not authorize adding new TeX model constraints. The issue was code translation, not a new model.

### 09r - Read-Only Hard-Cap Audit

Goal:

- Check whether the E2 generated instances are feasible if vehicle counts are hard caps.

Feedback result:

- Verdict: `HARD_CAP_CAPACITY_INFEASIBLE_CURRENT_Q`.
- Under `Q=1600kg`, hard fleet caps, and route=vehicle semantics, 69/69 E2 instances were infeasible by capacity lower bound.
- Goeke `Q=3650kg` counterfactual made 68/69 capacity-feasible.

Meaning:

- The current capacity parameter and hard cap semantics were incompatible.
- This was not an ALNS/warm-start issue.

### User correction on Q and route semantics

The user stated:

- 1600kg likely came from UK medium/light vehicle interpretation, but Goeke parameter alignment matters.
- A vehicle can run multiple routes/trips in a day; route should not equal one physical vehicle forever.
- The paper model did not need to say each vehicle is single-use.

### 09s - Goeke Parameter and Multi-Trip Semantics

Goal:

- Return to Goeke physical parameters.
- Correct code translation of physical fleet caps.

Implementation:

- `Q_capacity` restored to 3650kg.
- `B_battery_kwh` restored to 80kWh.
- Vehicle hard cap interpreted as physical vehicle count.
- Trip IDs like `CV1#T1` and `CV1#T2` allow one physical vehicle to serve multiple trips.
- Checker counts physical vehicle prefixes and enforces type consistency/time feasibility.

Feedback result:

- Report: `baselines/e2_alns/goeke80_multitrip_rescue_gate.md`.
- 69/69 E2 warm starts became zero-violation feasible.
- Small algorithm smoke completed 34/34 rows OK.
- Paired result: ALNS 2 wins, LNS 0 wins, 15 ties.

Meaning:

- The semantic feasibility blockage was cleared.
- But this was not yet formal algorithm victory.
- EV route share under Goeke80 was low, especially at larger scales.

## 10. Goeke80 Algorithm Preflight: 09t and Latest Wall-Clock/100kWh

### 09t - Goeke80 Multi-Trip T3 Preflight

Goal:

- Test whether under corrected Goeke80 semantics, ALNS can compete with LNS.

Feedback result:

- Stage A passed: 138/138 rows, 0 collection failure.
- Paired counts: ALNS 7, LNS 2, ties 60.
- Mean EV route share for 75-200 winners about 0.057.
- Stage B fixed 16000 eval attempt halted because LNS did not close within runtime caps.
- Verdict: `HALT_COLLECTION_COST`.

Meaning:

- LNS did not systemically dominate at Stage A.
- But Goeke80 mixed-fleet story was weak because EV usage was very low.
- Fixed 16000-eval comparison was not a good collection protocol for slow baselines.

### User's latest experimental instruction

The user asked to:

- Compare by equal wall-clock time, not forced 16000 eval.
- Lower Stage B eval budget to what LNS can close.
- Optimize LNS collection path if needed.
- Accept Goeke80 only as a baseline scenario if the mixed story remains weak.
- Try battery 100kWh across the full gradient.
- Monitor autonomously but not too frequently, and keep the dialogue open.

### Latest implementation

- New runner/report: `baselines/e2_alns/wallclock_battery_preflight.py` and `wallclock_battery_preflight_wallclock_retry.md`.
- Diagnostic only; no default parameter/model changes.
- Ran full gradient `-01` instances with 80/100kWh, ALNS/LNS, seed 1.
- Fixed a diagnostic-runner collection problem: hard timeout now returns readable checkpoint when available.

### Feedback result

- Wall-clock retry completed 92/92 rows OK.
- 80kWh: paired winners `ALNS 2 / LNS 1 / tie 20`; mean gap ALNS-LNS about -2.04%.
- 100kWh: paired winners `ALNS 2 / LNS 1 / tie 20`; mean gap about +0.59%.
- 75-200 winner EV route share about 0.057 for both 80 and 100kWh.

### Meaning

- Collection is now better for wall-clock preflight.
- ALNS is not dead, but most pairs tie.
- 100kWh does not rescue mixed composition.
- Goeke80/100 can be baseline algorithm-comparison scenarios, but not strong modern mixed-fleet stories.

## 11. What the User Asked, and How It Was Translated

This section maps the user's key directions to actions and outcomes.

### "Carbon price pinned; don't touch carbon"

Action:

- 09e-09h diagnostics kept `carbon_price=0.05034`.

Outcome:

- CV carbon was confirmed included.
- Carbon price was not used as a tuning knob.

### "Is CV carbon recorded and counted?"

Action:

- Cost pipeline was audited in diagnostics.

Outcome:

- Yes: fuel emissions enter carbon cost. All-CV cheapness was not a carbon-accounting bug.

### "Speed may be wrong; cross-city should be highway"

Action:

- 40km/h urban idea was downgraded.
- 90km/h kept for cross-city/highway.

Outcome:

- Speed was not changed in the mainline.

### "Battery must have real source; no arbitrary values"

Action:

- 09k/09l used source-bound battery candidates.

Outcome:

- No non-80kWh source-backed single battery value stabilized the practical mixed band.

### "80kWh was already too small; don't let it come back as modern main"

Action:

- 80 was treated as historical/reference in 09l/09q.

Outcome:

- Later Goeke80 was restored only as Goeke baseline after the user explicitly chose Goeke parameter alignment, not as a modern-main scenario.

### "20%-80% across all gradients and stability instances"

Action:

- 09l/09q reports used scale/family checks and fake-balance warnings.

Outcome:

- Battery-only and tested operational combinations failed this standard at Stage A screen level.

### "Do not change my model"

Action:

- This was not honored clearly enough at first. There was confusion around fleet caps.
- Later TeX cap changes were reverted/realigned; code was treated as translation correction.

Outcome:

- 09s corrected code to match physical fleet hard caps and multi-trip semantics.

### "Vehicles can run multiple routes"

Action:

- 09s implemented physical vehicle trip IDs and packing/checking semantics.

Outcome:

- 69/69 E2 warm starts became feasible under Goeke parameters.

### "Try 100kWh"

Action:

- Latest wall-clock runner tested 100kWh as in-memory override.

Outcome:

- It did not materially improve mixed-fleet composition.

### "Monitor but don't overprobe; don't close dialogue"

Action:

- Monitoring was done in-dialogue with long intervals after user correction.

Outcome:

- The final run was monitored to completion.
- But earlier I violated the user's expectation by creating/using extra monitoring structure and by reporting in overly technical terms.

## 12. Main Root Causes Found

### Root cause 1: The original ALNS loss was not just a speed bug

09d showed ALNS could be made faster, yet LNS still beat it on key threeshift means. So pure throughput repair did not solve algorithm comparison.

### Root cause 2: The benchmark regime changes the value of EV

80kWh makes EV too weak in large cross-city cases. 280kWh makes EV too strong. The transition is real, but it is not stable across all family/size cases.

### Root cause 3: Battery capacity alone cannot satisfy the user's mixed-fleet standard

09l is the key result: no non-80kWh source-backed battery candidate passed the full-gradient practical mixed-band screen. This is why repeated battery attempts failed.

### Root cause 4: Some previously observed EV dominance came from operational assumptions

Unbounded EV route availability and generous depot charging were plausible contributors. But simple diagnostic caps/charging constraints did not yet become a promotable, source-backed model scenario.

### Root cause 5: There was a model-code translation error around physical vehicles

The code/checker initially conflated route count and vehicle count in ways that conflicted with the user's intended model semantics. 09s corrected this by allowing physical vehicles to run multiple trips.

### Root cause 6: Fixed eval-budget comparison was a bad protocol for slow baselines

LNS can be slow in large cases. Equal wall-clock comparison is more realistic and matches the later E2 protocol note. Latest wall-clock preflight closed cleanly.

## 13. What Is Still Valid

Valid:

- CV carbon is counted.
- Cross-city speed should not be casually reduced to 40km/h.
- Goeke `Q=3650` and `B=80` are the aligned Goeke baseline parameters after 09s.
- Physical vehicle caps should count physical vehicles, not route/trip count.
- A vehicle may serve multiple trips if time-feasible and type/depot-consistent.
- 80/100kWh Goeke-style baseline preflight shows ALNS is comparable to LNS in many gradient cases, but not a strong mixed-fleet story.
- 280kWh is a modern EV-dominant scenario, not a stable mixed default.
- Battery-only tuning should stop unless a new source-backed scenario changes the evidence.

Not valid as final claims:

- "280kWh solves the whole story."
- "80kWh is a modern mixed-fleet main scenario."
- "Vehicle caps alone solved EV dominance."
- "Charging infrastructure pilot proves the cause."
- "Stage A or smoke means formal E2/T3 is ready."
- "ALNS formally beats LNS/GLNS."

## 14. Where Codex Failed the User

1. I blurred diagnostic evidence and decision-level conclusions. Example: 09h supported 280kWh against all-CV, but I did not sufficiently separate that from proving balanced mixed composition.
2. I let the branch jump between parameter tuning, operational constraints, model semantics, and algorithm comparison without repeatedly restating which goal was active.
3. I sometimes reported with internal labels instead of plain Chinese decision language.
4. I did not preserve the user's emotional/strategic intent strongly enough: they wanted a stable story and defensible paper, not just another diagnostic artifact.
5. I treated some monitoring/execution behaviors as helpful automation when the user wanted in-dialogue accountability.
6. I did not make a single authoritative timeline early enough, so the user had to keep correcting the same conceptual drift.

## 15. Current State as of This Retrospective

Current parameter/semantic mainline after 09s:

- `Q_capacity = 3650kg`
- `B_battery_kwh = 80kWh`
- `v_speed_ms = 25.0m/s`
- `carbon_price = 0.05034`
- physical vehicle hard caps are active
- physical vehicles may serve multiple trips

Latest algorithm preflight:

- Report: `baselines/e2_alns/wallclock_battery_preflight_wallclock_retry.md`
- 92/92 wall-clock rows OK
- 80kWh and 100kWh both show low EV share around 5.7% for 75-200 winners
- ALNS and LNS mostly tie; no formal T3 conclusion yet

Current honest interpretation:

- Goeke80 is a baseline algorithm-comparison scenario.
- It is not a modern stable mixed-fleet story.
- Modern battery values tend to push toward EV dominance unless a source-backed operational constraint is introduced.
- The next decision must be scenario-level, not another blind parameter run.

## 16. Decision Options for the User / Claude

### Option A - Baseline-first algorithm comparison

Use Goeke-aligned parameters and corrected multi-trip fleet semantics. Treat this as a Goeke benchmark baseline, not a modern mixed-fleet scenario. Continue algorithm comparison under equal wall-clock protocol and formal baselines.

Pros:

- Cleanest model alignment.
- Least new modeling risk.
- Algorithm comparison can proceed.

Cons:

- Mixed-fleet story is weak because EV usage is low.

### Option B - Modern mixed-fleet scenario with explicit operational constraint

Keep modern battery evidence, but introduce or formalize a source-backed operational constraint such as EV capital/fleet availability, depot charging capacity, or long-route eligibility.

Pros:

- Better matches modern logistics reality.
- Can potentially support a true mixed story.

Cons:

- Requires model/TeX/source work.
- Must be justified by literature/industry evidence.
- Cannot be smuggled in as a diagnostic wrapper.

### Option C - Reframe paper story

Accept that the current cross-city modern-battery regime tends toward EV dominance. Present mixed fleet as a transition/resource-constrained condition rather than universal optimum.

Pros:

- Most honest if future operational constraints do not pass.

Cons:

- May require rewriting the paper's narrative.

## 17. Recommended Next Action

Do not launch another compute-heavy experiment immediately.

First create a short "mainline decision memo" for the user to approve:

1. Is the paper's main E2 scenario Goeke benchmark baseline or modern logistics scenario?
2. If Goeke baseline: proceed to formal equal-wall-clock E2/T3 and accept weak EV usage as a limitation.
3. If modern logistics: pause T3 and formally design one source-backed operational constraint, with TeX/model/code changes explicitly approved before experiments.

Only after this decision should Codex run more experiments.

