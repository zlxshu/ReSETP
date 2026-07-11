# E2 loss-recovery audit

The frozen E2 result has 25 wins, 5 ties, and 15 losses against LNS.  The mean loss magnitude is 2.270%, while 3 losses exceed 5%.

The losses are not one defect.  Some use extra routes, one large 150c loss uses fewer routes but a much worse fleet/emissions mix, and nine of fifteen losses finish with their best solution in the middle strong-search stage.  The first bounded recovery hypothesis is therefore a restart of the strong middle stage, not another parameter sweep.

No frozen E2 row is rewritten by this audit.  The candidate must first pass an equal-budget 1600-evaluation short gate, then unseen-seed validation, before any full paper matrix is rerun.  A smaller budget would leave no meaningful strong middle stage after the fixed 400-evaluation opening and closing stages.
