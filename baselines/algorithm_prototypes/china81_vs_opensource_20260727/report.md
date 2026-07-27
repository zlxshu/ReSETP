# China81 MV-HGS-SP vs open-source distance-only HGS

Decision: `CONFIRMATION_COMPLETE`.

Scope: confirmation; rows 2025/2025.
New O rows: 405; sealed F/E/M/MV rows: 1620.

## Required disclosure

O was newly run with `NoImprovement(3000)` and no wall-clock algorithm stop. F/E/M/MV were imported from the sealed 2026-07-24 v7 fixed-iteration batch. They were not rerun in the O batch, and the historical batch has CPU but no separately recoverable wall-clock field. This evidence must not be described as same-batch, same-machine, same-stop-rule, or equal-compute.

## Frozen readings

MV vs O: {'win': 354, 'tie': 46, 'loss': 5}.
Mean MV improvement vs O: 1.919118015025895%.
Monotone O→F→E→M→MV units: 299/405.
Transition counts: `{"E_to_M": {"improve": 79, "regress": 77, "tie": 249}, "F_to_E": {"improve": 290, "regress": 29, "tie": 86}, "M_to_MV": {"improve": 114, "regress": 0, "tie": 291}, "O_to_F": {"improve": 268, "regress": 22, "tie": 115}}`.

## O-arm completion and resource disclosure

All 405 O units passed the common exact scorer with zero violations. The final
safe selection used the distance-only HGS search result in 390 units and retained
the common initial incumbent in 15 units (three instances, all five seeds). This
must not be described as 405 search improvements.

O consumed 18435.601032 aggregate CPU seconds and 19388.929480863968 aggregate
per-unit wall-clock seconds. Stop iterations were 3001/4121/30509 at the
minimum/median/maximum. The wall-clock total is a sum over concurrently executed
units, not batch elapsed time. No comparable independent wall-clock field exists
for the sealed F/E/M/MV archive.
