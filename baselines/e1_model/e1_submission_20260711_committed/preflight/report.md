# E1 model-structure gate

Verdict: `E1_PREFLIGHT_READY`.

Frozen mixed evidence rows: 1; CV-only completed: 1; EV-only completed/not-found: 0/1.
On the 200c mixed rows, mean EV shares by customers/demand/distance are 0.864/0.876/0.832; mean charging actions are 61.0.
Against CV-only on the same five seeds, mixed has mean cost gain 9.859% and W/T/L=[1, 0, 0]. Maximum cost-component reconciliation error is 1.819e-12.

EV-only NOT_FOUND is deliberately not labelled infeasible: direct conversion can fail because a route has no feasible depot charging window, but a different route structure may still exist.
