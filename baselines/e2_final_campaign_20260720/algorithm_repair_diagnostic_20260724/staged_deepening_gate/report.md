# Staged deepening v1 execution incident

Decision: `HALT_STAGED_DEEPENING_V1_BUDGET_SEMANTICS`.

The seed-12 panel started with three workers and ran for roughly sixteen
minutes. The first worker to finish raised `complete-evaluation budget
mismatch` before returning its result row. The parent then terminated the
remaining futures. No candidate cost direction was printed, returned, or
written.

The algorithm itself did not fail feasibility checking. The runner had
incorrectly treated 280 as a value that must be consumed exactly even when an
HGS stage contained fewer than 24 distinct final-population candidates. This
attempt remains stopped and its six instance-seed pairs must not be rerun.
