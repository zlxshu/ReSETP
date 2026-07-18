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
