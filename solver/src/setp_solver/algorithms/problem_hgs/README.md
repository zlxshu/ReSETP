# Formal Problem-HGS algorithm

This directory is the project's independently runnable algorithm.  It is
separate from the frozen open PyVRP 0.12.2 baseline and from the historical
`duty_hgs` implementation.

The public benchmark path uses the copied kernel's SREX crossover together
with the copied population, penalty, and compiled local-search modules.  The
private path breeds one child per iteration with the same kernel SREX (ordered
crossover in the single-vehicle degenerate case) on the route skeleton, maps
the changed routes back onto physical-vehicle daily duties without guessing
from route order, rebuilds charging for the changed duties, and accepts or
rejects the child solely by the project's complete evaluation: multi-trip,
charging, carbon, dynamic, collaboration, profit, and participation
contracts.

The copied foundation lives in `third_party/setp_hgs_kernel`, is built under
the independent package name `setp_hgs_kernel`, and retains the upstream MIT
license and attribution.  This algorithm never imports `pyvrp`, and the
vanilla baseline never imports this directory.

Stopping follows the HGS-CVRP 2022 no-time-limit mode: the run ends after
20,000 consecutive complete iterations without strict improvement, and the
counter resets on every strict improvement.  The caller supplies the stopping
policy; no wall-clock ceiling is imposed here.

A retired crossover portfolio (DCREX) was removed from this directory; its
history remains in version control only.
