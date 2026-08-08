# Formal Duty-HGS / DCREX algorithm

This directory is the project's formal self-developed algorithm.  It is
separate from both the frozen PyVRP 0.12.2 baseline and the historical
prototype under `baselines/algorithm_prototypes/duty_hgs_20260807/`.

The public benchmark path chooses between the shared DCREX core and PyVRP
0.12.2's compiled SREX, then uses PyVRP's population, penalty, and compiled
local-search modules.  The private path chooses between the same DCREX core
and a whole-trip assignment exchange before evaluating physical-vehicle daily
duties with the project's multi-trip, charging, carbon, dynamic,
collaboration, profit, and participation contracts.  The private action is
not called SREX because it preserves physical-vehicle and daily-duty meaning.
No module in the vanilla baseline imports this directory.

The crossover controller records work as the number of complete offspring
scored before the common downstream search: two for public SREX and one for
public DCREX, private DCREX, or private whole-trip assignment.

The caller supplies the iteration limit obtained from that algorithm's own
convergence trajectory.  The formal implementation does not impose equal
wall time or equal iteration counts across algorithms.
