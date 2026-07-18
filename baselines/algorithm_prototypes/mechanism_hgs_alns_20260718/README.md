# Mechanism-first ALNS development prototypes

This directory is isolated from the formal solver. Nothing here authorizes a
formal E2 run, China81, an E2--E7 rerun, formal solver integration, or stage 2.

## Honest current status

The original plan was to put the ReSETP ALNS inside an HGS-style outer search.
That plan did not survive component ablation:

- the official-HGS direct insertion beat the equal-budget no-HGS version on
  only 1 of 6 paired 25/50-customer tasks;
- the official HGS improved the warm solution directly on only 1 of 6 tasks;
- native official-HGS routes used as route-pool columns produced no final gain
  on the two seed-1 diagnostic tasks.

Official HGS therefore remains a pinned external open-source control, not a
component of the candidate. Do not describe this work as an HGS--ALNS fusion.

The current development candidate is `v7_responsibility_solver.py`. The
project ALNS receives the full B100 route-search budget. Five model-born
decoders then handle decisions that generic route search misses:

1. cross-depot customer handover or reciprocal exchange;
2. joint CV/EV and charging-plan selection for fixed customer routes;
3. exact fixed-duration charge retiming at carbon-signal breakpoints;
4. depot-profit-floor repair directed by the normalized profit deficit;
5. frozen-history insertion of a newly arrived order, with a bounded
   regret/ejection fallback.

Every decoder uses a separate activity ledger. No decoder consumes hidden
complete route-search evaluations. The final solution is independently
recomputed, and the responsibility branch is compared with an exact bypass
branch so that the added mechanism cannot make the candidate worse.

## Cheapest reproducible checks

Run the focused tests:

```bash
PYTHONPATH="solver/src:models/src:baselines/algorithm_prototypes/mechanism_hgs_alns_20260718:.:Reference Algorithm/ALNS-7.0.0@N-Wouda" \
python -m pytest -q \
baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/test_v4_mechanism_alns.py \
baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/test_v5_carbon_retiming.py \
baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/test_v6_monotone_mechanism.py \
baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/test_v7_responsibility.py \
baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/test_fairness_deficit_decoder.py \
baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/test_dynamic_event_decoder.py
```

Rebuild the unified development closeout:

```bash
PYTHONPATH="solver/src:models/src:baselines/algorithm_prototypes/mechanism_hgs_alns_20260718:.:Reference Algorithm/ALNS-7.0.0@N-Wouda" \
python baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/run_stage1_algorithm_closeout.py
```

The runner verifies the hashes of reused v6 controls before it runs v7. It
writes `metadata.json`, `raw_runs.csv`, `decision.json`,
`artifact_hashes.json`, `report.md`, the algorithm story, and solution
witnesses to `mechanism_v7_stage1_closeout_gate/`.

## Latest development evidence

The unified B100 closeout returned
`PASS_STAGE1_ALGORITHM_INFRASTRUCTURE_DEVELOPMENT_CLOSEOUT`:

- 9/9 strict wins over the pinned official Vidal HGS-CVRP neutral adapter,
  original `alns 7.0.0`, and the current project ALNS;
- 9/9 nonlosses against v6, including a strict improvement on the former
  20-customer plateau from `621.2913242409613` to
  `621.0831141941019`;
- four binding cross-depot tasks improved by 1.265%--5.673%, while fourteen
  nonbinding tasks were exact ties;
- the fixed 100% stand-alone-profit floor was repaired on its one binding
  seed, while two already-satisfied seeds were exact no-ops;
- the frozen real add-order event used one fewer future route and reduced
  cost by `29.675378723731683`; the bounded depth-two fallback retained exact
  0/1/2/5 accounting.

These are development signals, not formal benchmark or paper results. The
fairness evidence contains only one binding task, the dynamic evidence only
one real event, and the three post-discovery multi-depot controls are not an
unbiased generalization sample. Nonlinear charging, time-varying electricity
prices, formal E2--E7, China81, large-scale statistics, formal integration,
and stage 2 remain unapproved and unproven.
