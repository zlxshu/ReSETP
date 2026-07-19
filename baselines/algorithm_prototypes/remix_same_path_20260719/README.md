# ReMIX same-path shell

This directory contains only the disabled/zero-budget shell used by
`ALGO-COMPARE-FOUNDATION-003`.

It does not implement or test the proposed performance enhancements.  Its only
purpose is to prove that:

1. `mode=mother`,
2. `mode=hybrid_disabled`, and
3. `mode=hybrid_zero_budget`

all execute the same pinned PyVRP 0.13.4 mother search when every enhancement
is inactive.  The three modes must produce the same routes, objective and
iteration trace from separate processes.  Any component call is a failure.

PyVRP is MIT-licensed.  The frozen license and citation are stored under
`baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719/sources/`.

