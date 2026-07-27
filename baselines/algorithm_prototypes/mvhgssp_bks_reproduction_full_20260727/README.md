# MV-HGS-SP full new-BKS reproduction

Task: `E2-MVHGSSP-BKS-REPRODUCTION-FULL-002`.

This directory extends the sealed 2/18 check in
`mvhgssp_bks_reproduction_20260727` to the remaining 16 independently certified
new-BKS targets. It does not modify or overwrite the original evidence.

Frozen protocol per new instance: start from the 2013 BKS witness; run three
PyVRP 0.12.2 HGS epochs of 12,000 iterations with seeds 1, 2, and 3; accumulate
feasible routes across epochs; solve the same set-partitioning model for at most
180 seconds after each epoch; retain `min(current incumbent, SP solution)`.

Six process workers are allowed after the six-PID preflight. Algorithm search
has no wall-clock stop. `PYTHONHASHSEED=0` and BLAS thread counts are fixed to
one. Results are written atomically after every completed instance. CPU and
wall-clock fields are separately recorded; the original 2/18 rows are imported
as sealed prior evidence and retain their historical timing-label caveat.

Passing means reproducing the independently certified target cost or a lower
cost. Failure is preserved and is not rescued by changing seeds, iterations,
targets, or start solutions.
