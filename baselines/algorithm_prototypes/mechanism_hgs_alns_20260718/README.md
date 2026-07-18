# Mechanism HGS--ALNS development prototype

This directory is isolated from the formal solver.  `prototype.py` implements
an HGS-style outer population over customer orders and uses the existing
ReSETP ALNS as the education step under one exact complete-evaluation budget.

Run the cheapest accounting gate first:

```bash
PYTHONPATH=solver/src python baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/run_gate.py --functional
```

Only after that passes may the small three-arm development gate run.  The
combination must beat both pure arms on every paired task; a tie is a failure.
Even a pass does not authorize formal experiments.

## Latest mechanism-specific development result

The sequential shell and the first interleaved memetic version both failed the
strict double-win gate.  The useful redesign keeps 80% of the exact evaluation
budget in ALNS, then always applies cross-depot responsibility moves and
fleet/charging closure before using any unused evaluations for ALNS
continuation.  This is an isolated development implementation, not the formal
solver entry.

On the frozen 280 kWh diagnostic development slice, the intensified method beat
both pure arms in all six paired 25/50-customer tasks at B100.  The 20-customer
tasks did not pass: one B100 loss and two ties.  At B500 all three methods using
ALNS reached exactly 621.2913242409613 while the HGS-style outer arm remained
worse.  The strict preregistered rule counts those ties as failures, so the
decision remains `HOLD_REDESIGN_NOT_DOUBLE_WIN`; no formal experiment or
manuscript claim is authorized.

The archived multi-depot scale slice is unsuitable as a responsibility-repair
performance gate: cross-depot candidates were mostly inactive or infeasible.
It is retained as negative evidence and must not be used to claim that the
cross-depot mechanism works.
