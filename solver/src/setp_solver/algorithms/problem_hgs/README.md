# Formal Problem-HGS / DCREX algorithm

This directory is the project's independently runnable algorithm.  It is
separate from the frozen open PyVRP 0.12.2 baseline and from the historical
`duty_hgs` implementation.

The public benchmark path chooses between the project DCREX core and the
copied kernel's SREX, then uses the copied population, penalty, and compiled
local-search modules.  The private path chooses between the same DCREX core
and a whole-trip assignment exchange before evaluating physical-vehicle daily
duties with the project's multi-trip, charging, carbon, dynamic,
collaboration, profit, and participation contracts.  The private action is
not called SREX because it preserves physical-vehicle and daily-duty meaning.
The copied foundation lives in `third_party/setp_hgs_kernel`, is built under
the independent package name `setp_hgs_kernel`, and retains the upstream MIT
license and attribution.  This algorithm never imports `pyvrp`, and the
vanilla baseline never imports this directory.

The crossover controller records work as the number of complete offspring
scored before the common downstream search: two for public SREX and one for
public DCREX, private DCREX, or private whole-trip assignment.

The caller supplies a run limit from this algorithm's own convergence
trajectory.  The user-set per-case hard ceiling is 20 minutes.
