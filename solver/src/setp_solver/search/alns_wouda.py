"""Deprecated shim — ReSETP ALNS kernel lives in algorithms.resetp_alns.kernel.alns_core."""
from __future__ import annotations

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

def __getattr__(name: str):
    return getattr(_core, name)
