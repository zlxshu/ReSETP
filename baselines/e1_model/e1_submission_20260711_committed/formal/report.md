# E1 model-structure gate

Verdict: `E1_280_STRUCTURE_SUPPORTED`.

Frozen mixed evidence rows: 20; CV-only completed: 5; EV-only completed/not-found: 0/5.
On the 200c mixed rows, mean EV shares by customers/demand/distance are 0.861/0.872/0.822; mean charging actions are 59.8.
Against CV-only on the same five seeds, mixed has mean cost gain 0.671% and W/T/L=[4, 0, 1]. Maximum cost-component reconciliation error is 1.819e-12.

EV-only NOT_FOUND is deliberately not labelled infeasible: direct conversion can fail because a route has no feasible depot charging window, but a different route structure may still exist.
