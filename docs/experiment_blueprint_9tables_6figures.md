# ReSETP Experimental Blueprint: 9 Tables and 6 Figures

<!-- v2026-06-12: create the formal experiment blueprint after the E5 mechanism gate and U0-U2 three-shift instance build. -->

## Positioning

The paper should not try to prove everything with one overloaded experiment. The clean story is:

1. **Electrification layer:** once depot charging and the forward station-insertion repairer are correct, the optimizer naturally replaces part of the CV fleet with EVs when the route is physically and economically suitable.
2. **Charging-timing layer:** conditional on the same route set, carbon-aware charging shifts depot/station charging into lower-carbon slots and reduces EV charging emissions relative to a return-immediate charging baseline.
3. **Coordination layer:** multi-depot sharing and the fairness lower bound determine how much of the system-level gain can be retained when each depot must preserve an acceptable share of its stand-alone profit.
4. **Dynamic layer:** rolling replanning must inherit executed state and remaining carbon/fairness state without retroactively changing already executed route segments.

The formal experiment suite therefore uses the 24h three-shift instance as the main case, keeps the 100-customer 24h instance as the mechanism pilot/regression case, and uses smaller/scaled batches for algorithm-comparison robustness.

## Fixed Controls

- Fairness is off until the independent-depot baseline pipeline for `Pi_d^0` is implemented and validated.
- CMEM, price, depot electricity price, public station electricity price, depot charging occupancy, carbon slot semantics, and battery semantics remain frozen unless a later paper-code audit explicitly reopens them.
- E5 is a charging-strategy ablation, not `carbon_weight=1` versus `carbon_weight=0`.
- Every reported number must be exported from JSON/CSV produced by the solver/export scripts. No hand-entered table values.
- If a public benchmark BKS is not available for the transformed collaborative/carbon instance, the paper must say "best observed feasible solution" rather than "BKS".

## Instance Sets

| Set | Purpose | Instances | Budget | Notes |
|---|---|---:|---:|---|
| S-debug | regression and smoke tests | 25/50 customer generated bundles | short | used before every larger run |
| M-mechanism | E5 mechanism pilot | `E-UK100_01__d2_s3_seed1_24h_20251113` and successor corrected bundle | 8000 evals or 180s | keeps continuity with T0/T1 evidence |
| L-main | formal static and mechanism case | `E-UK24h-三班-01` | 8000 evals or 180s, then extended if unstable | built by U0-U2, 219 customers |
| B-batch | algorithm comparison | 50/100/150 or 25/50/100/200 generated families, 3 seeds each | same wall/eval budget per algorithm | only after fairness and final solver runner are stable |
| D-dynamic | rolling replanning | one medium and one L-main-derived event stream | stage budget fixed | only after dynamic state inheritance is implemented |

## Experiment Modules

| Module | Question | Main Control | Output |
|---|---|---|---|
| E0 Data and validation gates | Are data, carbon slots, feasibility checks, and instance manifests defensible? | no optimization claims | Table 1, Table 2 |
| E1 Static main solution | What does the full model produce on the main 24h case? | fairness off first, then fairness on after E6 | Table 4, Figure 1 |
| E2 Algorithm comparison | Does the chosen ALNS beat reasonable baselines under the same evaluator? | same instances, same budget, same feasibility checker | Table 3, Figure 2 |
| E3 Mechanism ablation | Which modeling layers create the result? | add mechanisms one by one | Table 5 |
| E4 Carbon scenario sensitivity | How do carbon price, quota, and gamma profile change decisions? | route/solver budget fixed | Table 7, Figure 5 |
| E5 Two-layer decarbonization | How much comes from EV adoption and how much from charging timing? | same final route set for timing ablation | Table 6, Figure 3, Figure 4 |
| E6 Fairness threshold sensitivity | What is the cost of requiring depot profit preservation? | `Pi_d^0` computed by independent-depot runs | Table 8, Figure 6 |
| E7 Dynamic rolling replanning | Does the dynamic framework close state inheritance and frozen execution? | same revealed demand set for dynamic/static comparison | Table 9 |

## Nine Tables

| ID | Manuscript role | Rows | Required metrics | Source |
|---|---|---|---|---|
| T1 | Instance and data provenance | instance set x seed | customers, depots, stations, demand, time horizon, deleted customers, isolated share, validation status, gamma slots, carbon anchor | `scenario_manifest.json`, `three_shift_manifest.json`, carbon CSV verifier |
| T2 | Parameter settings | parameter groups | vehicle, battery, power, prices, carbon price/quota levels, ALNS budget, theta levels | config/export manifest and paper parameter registry |
| T3 | Algorithm comparison | instance x algorithm x seed summary | best, mean, std, feasible rate, time, evals, observed gap, Wilcoxon/sign test flag | E2 batch runner |
| T4 | Static main-solution decomposition | scenario x policy | total cost, fixed, km, fuel, electricity, occupancy, carbon trading, CV/EV routes, depot/station kWh, total carbon, stake, cross-depot services | full-model run report |
| T5 | Mechanism ablation ladder | base + added mechanism rows | cost, carbon, EV routes, charging kWh, cross-depot services, fairness metric, infeasible marker where applicable | E3 ablation runner |
| T6 | E5 two-layer decarbonization | CV-only, mixed-aware, mixed-naive replay | EV/CV routes, total carbon, CV direct carbon, EV charging carbon, mean charge intensity, delta carbon, delta intensity | E5 replay report |
| T7 | Carbon scenario sensitivity | quota x carbon price x gamma day/profile | total cost, total carbon, carbon trading cost, EV routes, charge timing centroid, binding quota flag | E4 scenario runner |
| T8 | Fairness threshold sensitivity | theta levels | `Pi_d^0`, `Pi_d`, min `Pi_d/Pi_d^0`, total cost, total carbon, cross-depot services, infeasible theta threshold | E6 fairness runner |
| T9 | Dynamic rolling replanning | replanning stages | trigger time, event counts, frozen routes, served/pending/cancelled customers, inherited battery/load/carbon state, stage cost, cumulative cost, cumulative carbon, feasibility | E7 dynamic runner |

## Six Figures

| ID | Manuscript role | Visual design | Required data |
|---|---|---|---|
| F1 | Main 24h solution map | depot/station/customer map with route overlays; EV and CV distinguished | T4 route export |
| F2 | Algorithm performance | convergence curves plus final-cost box/violin plot across seeds | T3 per-iteration logs |
| F3 | Two-layer carbon waterfall | CV-only baseline -> mixed fleet -> carbon-aware charging | T6 |
| F4 | 48-slot carbon and charging profile | gamma line plus aware/naive depot/station charging bars | E5 slot CSV |
| F5 | Carbon sensitivity heatmap | quota level x carbon price, color by total carbon or EV share | T7 |
| F6 | Fairness frontier | theta versus total cost, total carbon, and min profit-preservation ratio | T8 |

Dynamic replanning is table-led unless there is enough space for a supplementary figure. If the journal page budget allows one extra subfigure, add a small event timeline under F1 or as an appendix figure rather than dropping the fairness frontier.

## Execution Order

1. **Freeze formal instances:** keep `E-UK24h-三班-01`, then generate 2 more L-main siblings only if T3/E2 needs replicate main cases.
2. **Implement fairness baseline pipeline:** run each depot independently to compute `Pi_d^0`; reject or mark instances where any `Pi_d^0 <= 0`.
3. **Open fairness checker/objective integration:** add theta to config, checker, evaluator, and export. Run S-debug before L-main.
4. **Build unified experiment runner/exporter:** one runner writes normalized route, cost, carbon, charging, fairness, algorithm-log, and feasibility CSVs.
5. **Run E2 algorithm comparison:** implement only baselines that can use the same evaluator and checker; do not compare against methods with weaker constraints.
6. **Run E1/E3/E5 on L-main:** full model, ablation ladder, and fixed-route charging replay.
7. **Run E4 sensitivity:** carbon quota, carbon price, and gamma-profile scenarios.
8. **Run E6 fairness scan:** theta grid after `Pi_d^0` is validated.
9. **Implement and run E7 dynamic:** only after static/fairness export contracts are stable.
10. **Generate LaTeX tables/figures:** replace old placeholder tables/figures only from exported CSVs.

## Acceptance Gates

| Gate | Pass condition | Stop condition |
|---|---|---|
| G0 data | manifests exist, validation passed, gamma diff = 0, B2 safe | any generated instance fails validation without a recorded fix |
| G1 feasibility | every reported solution has zero hard violations | any table row would require reporting an infeasible solution as valid |
| G2 algorithm fairness | all algorithms use the same objective evaluator and checker | baseline cannot represent charging/fairness constraints comparably |
| G3 E5 | aware and naive replay feasible, `delta_carbon > 0`, `delta_intensity > 20 gCO2/kWh` on main case | delta zero/reversed without a documented physical reason |
| G4 fairness | all `Pi_d^0 > 0`, theta scan includes feasible and tightening regimes | independent baseline profit nonpositive |
| G5 dynamic | frozen executed segments unchanged, inherited state audited stage by stage | any stage mutates executed history |

## Current Artifact Mapping

| Artifact | Status | Use |
|---|---|---|
| `models/data_bundle/generated_instances/E-UK24h-三班-01` | ready after U0-U2 | L-main formal instance candidate |
| `solver/reports/u2_E-UK24h-three-shift-01_smoke_seed1_2000eval.json` | smoke only | confirms feasibility/runnability, not final evidence |
| `solver/reports/t0_100-01_24h_20251113_seed1_forward_repair_real_budget.json` | mechanism evidence | T0 EV adoption regression reference |
| `solver/reports/t1_100-01_24h_20251113_seed1_forward_repair_return_charge_ablation.json` | mechanism evidence | E5 pilot evidence |
| `docs/paper_submission_final/generated_tables/table3_batch_instance_results.tex` | legacy placeholder | retire/rebuild from T3 exporter |
| `docs/paper_submission_final/generated_tables/table10_dynamic_stage_results.tex` | legacy placeholder | retire/rebuild from E7 exporter |
| `docs/paper_submission_final/generated_figures/figure6_carbon_charge_load.pdf` | legacy placeholder | retire/rebuild from F4 exporter |
| `docs/paper_submission_final/generated_figures/figure7_fairness_frontier.pdf` | legacy placeholder | retire/rebuild from F6 exporter |

## Next Knife

The next implementation knife should be fairness baseline opening, not another E5 rerun:

1. Add an independent-depot solve mode that restricts each depot to its own customers and vehicles.
2. Export `Pi_d^0`, `Pi_d`, and `Pi_d/Pi_d^0`.
3. Add theta configuration and feasibility reporting while keeping fairness off by default.
4. Run S-debug, then L-main smoke, then stop for user review before formal E6 scans.

This order prevents E3/E5/E2 formal results from being invalidated later by a changed feasible region.
