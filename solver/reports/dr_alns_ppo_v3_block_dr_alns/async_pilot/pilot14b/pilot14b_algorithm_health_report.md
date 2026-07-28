# Pilot14b Algorithm Health Check

Date: 2026-06-27

Scope: literature-backed DR-ALNS health check plus runtime-safe candidate-generator repair. No long PPO training and no baseline performance verdict were run here.

## Human Summary

The previous contradiction was real: Pilot14 proved that stronger candidate generation can create useful changed solutions, but the first runtime path was too expensive for training. If we had launched a long PPO run at that point, the model would likely have spent too much wall time inside candidate construction instead of collecting enough learning episodes.

Pilot14b fixes that training-risk point by separating two profiles. The exhaustive profile remains available for offline diagnosis. The runtime profile used by PPO is capped to a small search window: one removal fraction, greedy repair only, at most 8 route candidates, 4 insertion positions per route, and 16 candidates per action. A 50c action smoke dropped from the previous tens-of-seconds behavior to 0.143s, with 5 generated candidates, 733 repair-delta probes, zero violations, and a changed candidate.

The all-scale three-shift probe now covers 50c, 75c, 100c, 150c, and 200c, three bundles each. With the capped runtime profile, `stronger_insertion_repair` passed the interface gate on all 15 bundles: changed rate 0.8361, improving rate 0.4426, train mean relative +2.3753%, held mean relative +3.3811%, overall +2.0445%, and 15/15 bundles non-worse in this small-budget probe. This is evidence that the action interface is trainable; it is not yet proof that a trained policy will beat the tuned ALNS baselines at full budget.

## Sources Checked

Zotero was reachable through the local plugin, and these full texts were extracted under `pilot14b/literature_health_check/`: Wang 2025 PPO-ALNS (`EH3X7IXI`), Chao Wang 2025 DRL-ALNS for CEVRP (`7HGUI8ZL`), Daysalilar 2026 curriculum EVRP (`7H4BZNNE`), and Narayanan 2022 EVRP/V2G RL (`5AJNZFPP`).

Repository reference code checked: `Reference Algorithm/DR-ALNS@RobbertReijnen`, `Reference Algorithm/ppo-alns-main`, `Reference Algorithm/ALNS-7.0.0@N-Wouda`, and the CEVRP DRL-ALNS reference folder. Web lookup was also used for the public method/source trail, including the DR-ALNS and ALNS GitHub references.

## Literature Diagnosis

The shared pattern in PPO-ALNS and DRL-ALNS papers is not "replace ALNS with a giant neural selector." The working structures keep the neural decision small and tied to search control: destroy/repair family, destruction size, acceptance/temperature, stop/continue, or charging-aware repair choice. The reference PPO-ALNS code also uses a compact action vector with destroy, repair, accept, and stop, plus many short parallel environments. This points directly at our earlier failure: operator-only PPO was too weak, while exhaustive candidate generation was too slow.

The curriculum papers do not jump straight to large 100c+ hard instances. They train through staged difficulty and evaluate generalization separately. That supports the current requirement: final training should use all-scale three-shift curriculum, but it must pass cheap gates first. The new all-scale manifest and all-scale smoke exist for that reason.

The EVRP/CEVRP DRL-ALNS papers emphasize state/reward features that distinguish search progress, operator history, feasibility pressure, and charging/energy behavior. In our current implementation, the next learning risk is not basic feasibility anymore; the risk is whether the observation/reward gives the policy enough signal to choose the new candidate-generator head at the right time, especially on 150c and 200c where the small probe is only near-flat positive.

The ALNS references also highlight acceptance and stopping as first-class control points. Our current candidate-generator rescue only adds a stronger candidate source. It does not yet learn stop/acceptance the same way the papers do. That is an intentional boundary for this repair step, not a claim that the full literature structure is complete.

## Fixes Made

`pilot14_candidate_generation_tools.py` now has explicit candidate-generation profiles. `exhaustive_candidate_generation_limits()` keeps the wide diagnostic search. `runtime_candidate_generation_limits()` is the PPO-safe profile and is what `generate_candidate_solutions()` uses by default in the worker path.

The candidate-generation gate now measures changed/improving rates over real generated candidates, not over budget-padding rows. This matters because runtime mode deliberately generates a small candidate set and pads the scoring budget with the baseline to preserve `actual_evals == eval_budget`. Counting the padding as failed candidates was a false HALT.

The probe bundle list now includes 15 three-shift bundles: 50c, 75c, 100c, 150c, and 200c, three each. A new all-scale training manifest is written at `pilot14b/training_manifest_three_shift_allscale.json`.

## Gates Run

Unit tests: `solver/rl/tests/test_pilot14_candidate_generation_tools.py -q` passed, 12 tests.

Single 50c runtime action smoke: `elapsed_seconds=0.1428`, `candidate_generator_candidate_count=5`, `repair_delta_count=733`, `actual_evals=1`, zero violations.

50/75c runtime candidate gate, seeds 1-2, budget 50, all variants: READY. Best variant was `stronger_insertion_repair`, with train mean +2.7164%, held mean +3.3700%, overall +3.0432%, and 6/6 bundles non-worse.

100/150/200c runtime probe, seed 1, budget 20, `stronger_insertion_repair`: no row-gate failure, overall +1.4888%, 9/9 bundles non-worse. This standalone scale-only run cannot produce READY because the classifier is defined around train/held roles.

All-scale runtime candidate gate, seed 1, budget 20, `stronger_insertion_repair`: READY. It covered all 15 three-shift bundles, with train mean +2.3753%, held mean +3.3811%, overall +2.0445%, changed rate 0.8361, improving rate 0.4426, and 15/15 bundles non-worse.

All-scale PPO smoke: passed training-path gates. It loaded 15 train bundles, touched all 15 in 20 episodes, reached route -> energy -> carbon, ran on CUDA, used py313 worker with NumPy 2.3.5, had zero violations, finite rewards/objectives, 6 PPO updates, and exercised the candidate-generator head (`candidate_generator_unique_total=62`, `candidate_generator_nondefault_total=71`). Throughput in this tiny smoke was about 587 episodes/hour with 3 actors.

## Current Medical Judgment

The earlier "DR cannot learn" diagnosis was too broad. More precisely: the old operator-selection DR path had no headroom against AlphaUCB, and the first stronger-candidate path had headroom but was too expensive. Pilot14b changes the status to: the interface is now plausible for PPO training, but full success is still unproven.

The main remaining risk is large-scale strength. On 100c the probe has visible room. On 150c it is small but positive. On 200c it is mostly flat. That means the next full training must be all-scale and must use evaluation gates that punish small-scale-only wins. A trained model that wins 50/75/100 but does nothing on 150/200 should not be accepted as the final DR result.

## Next Training Gate

Before a long run, use this manifest: `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot14b/training_manifest_three_shift_allscale.json`.

Run one bounded calibration with `--candidate-generator-mode`, all-scale manifest, py313 worker, CUDA PPO, and the same route/energy/carbon curriculum. Acceptance for starting the long run should require: all 15 bundles touched, route -> energy -> carbon reached, zero violations, worker py313/NumPy 2.3.5, finite rewards/objectives, candidate-generator head used in at least 50% of episodes, and throughput high enough to project at least 1000 episodes overnight. If that passes, then launch the full all-scale PPO run. If not, stop and fix observation/reward or action scheduling first.

