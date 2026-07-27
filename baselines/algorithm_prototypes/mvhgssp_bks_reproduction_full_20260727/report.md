# MV-HGS-SP full new-BKS reproduction

Decision: `STOP_NOT_ALL_TARGETS_REPRODUCED`.

Evaluated 18/18; passed 13; failed 5.
New extension rows: 16; sealed prior rows: 2.

This evidence does not show MV-HGS-SP beating plain HGS. It only tests whether the named method reproduces the same certified targets under the frozen warm-start protocol.

## Frozen outcome

The fixed protocol reproduced 13/18 targets and missed 5/18. The misses were
PR14A (+2.807), PR15A (+3.018), PR15B (+0.041), PR16A (+3.393), and PR24A
(+0.044), where positive values are the remaining distance above the frozen
target. No rescue seeds, iterations, or starts were added.

All 16 newly executed witnesses passed a PyVRP-independent arc-by-arc and
constraint certificate. Five results strictly improved the previous certified
targets: PR12A by 0.634, PR14B by 0.183, PR22B by 0.093, PR23B by 0.965, and
PR24B by 0.151. These are recorded in `NEW_BKS_UPDATES.csv`. They are locally
certified benchmark candidates; external publication or community adoption is
not implied.

Only PR14B has strict set-partitioning attribution within this run: its best
epoch HGS value was 8654.168 and pool assembly returned 8653.985. PR24A also
received a strict SP improvement (11634.129 to 11634.117) but still missed the
frozen 11634.073 target. The other four new candidates were HGS results or SP
ties, so they cannot be presented as standalone SP gains.

The 16 new tasks consumed 20790.890369 aggregate process CPU seconds and
21398.633284 aggregate per-task wall-clock seconds. The two sealed prior tasks
retain their original timing-label caveat and are not included in these sums.
