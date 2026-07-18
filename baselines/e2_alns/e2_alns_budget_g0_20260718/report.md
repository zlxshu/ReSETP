# ALNS complete-solution budget G0

Verdict: `PASS_ALNS_BUDGET_G0_COMPLETE`.

Static blockers=0, unclassified=0. Behavior/regression tests=186 passed, returncode=0. Candidate limits are prechecked before the legacy scorer; reference phases and repair deltas remain separately visible. No formal search experiment was run.

The sealed 2026-07-17 HALT package is retained unchanged as the adverse baseline. This patch changes budget semantics and therefore does not rehabilitate old E2 comparisons or permit mixing old and new algorithm results.
