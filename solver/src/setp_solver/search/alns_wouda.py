"""Deprecated shim — ReSETP ALNS kernel lives in algorithms.resetp_alns.kernel.alns_core."""
from __future__ import annotations

from pathlib import Path

from setp_solver.algorithms.resetp_alns.kernel.alns_core import (  # noqa: F401
    AlnsRunResult,
    AlnsState,
    SearchPolicy,
    greedy_insert_repair,
    random_customer_removal,
    regret2_insert_repair,
    regret3_insert_repair,
    route_elimination_removal,
    route_segment_removal,
    run_alns_wouda,
    shaw_related_removal,
    vehicle_type_swap_destroy,
    whole_route_removal,
    worst_customer_removal,
)
from setp_solver.algorithms.resetp_alns.kernel import alns_core as _core
from setp_solver.algorithms.resetp_alns.support.fleet import infer_fleet_limits


def search_policy_for_bundle(
    bundle_dir: str | Path,
    *,
    require_charging_signal: bool = False,
    max_cv: int | None = None,
    max_ev: int | None = None,
) -> SearchPolicy:
    """Build a search policy that preserves the bundle's fleet caps.

    Frozen DR-ALNS runners imported this helper from the legacy adapter.  Keep
    the compatibility surface here while delegating fleet semantics to M1's
    canonical ReSETP ALNS implementation.
    """

    limits = infer_fleet_limits(bundle_dir)
    return SearchPolicy(
        require_charging_signal=bool(require_charging_signal),
        max_cv=limits.cv if max_cv is None else int(max_cv),
        max_ev=limits.ev if max_ev is None else int(max_ev),
    )


def __getattr__(name: str):
    return getattr(_core, name)
