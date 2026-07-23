# Pre-E3 decisions that cannot be made silently

The audit can repair deterministic wiring and mapping defects, but the items
below change a model parameter, algorithm boundary, experimental arm, or
statistical-compute contract. Formal search remains held until every item has
an explicit, versioned answer.

## D1 — Date-aligned diesel prices

Recommended: activate the audit register's 2025-02-12 city/price-zone values:
Beijing 7.48; Tianjin and Shijiazhuang/Hebei 7.43; Guangzhou, Shenzhen,
Dongguan and Foshan 7.44; Chengdu 7.48; Chongqing 7.50 yuan/L. This replaces
the July 2026 three-region proxy and forces a complete China81 E2 rerun.

## D2 — Finite fleet and depot charging capacity

Recommended: replace the nonbinding one-vehicle-per-customer ceilings with an
algorithm-independent sizing rule derived only from demand and time-window
inputs, add a preregistered reserve factor, and include a small sensitivity
panel. Depot charger counts and 22 kW power must remain explicitly labelled
constructed-scenario parameters unless a named site's contract is obtained.
The exact sizing rule and reserve factor still require approval after a
source-backed zero-search design note.

## D3 — Executable E3 control and treatment

Recommended: the control hard-locks each customer to its registered home
depot; the treatment removes that lock and enables reciprocal cross-depot
search. Both arms must share the same input bytes, initial-solution rule,
seed, evaluation budget, evaluator and strict certificate. Merely disabling
one operator is not a valid control because other operators can still create
cross-depot service.

## D4 — Reproducible formal budget

Recommended: use the same deterministic complete-candidate evaluation budget
for paired arms, with wall clock only as a safety cap and CPU reported
separately. A result-blind throughput/feasibility pilot may choose the number,
but it may not inspect treatment effects.

## D5 — Route-pool recombination claim

Recommended: rename the component as time-limited MIP route-pool
recombination and retain HiGHS status, incumbent, bound and MIP gap. The
alternative is to accept a recombination only when optimality is proved;
that preserves the word exact but changes runtime and potentially results.
The current hybrid—time-limited incumbent plus the word exact—is not
defensible.

## D6 — Rerun boundary

Recommended: after D1--D5 are frozen, rerun the full corrected-authority
China81 E2 private campaign and the representative-instance S3--S5 chain,
then run E3. Keep public P1, but first replay its sealed witnesses through the
current checker without optimization. Do not overwrite the historical E2
artifacts.
