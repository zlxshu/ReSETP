"""Isolated distance-only adapter for the China81 open-source HGS arm.

The frozen adapter remains untouched.  This module reuses its translation
helpers and constructs the new ``distance_only`` problem by temporarily
substituting only the arc-cost callback while the frozen ``cv_only`` model is
built.  The build is synchronous and each formal task runs in its own spawned
process, so the temporary module-local substitution cannot leak across tasks.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
SOLVER_SRC = REPO / "solver/src"
FROZEN_ADAPTER = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720/pyvrp_adapter.py"
)
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

_SPEC = importlib.util.spec_from_file_location(
    "_resetp_frozen_china81_pyvrp_adapter",
    FROZEN_ADAPTER,
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"cannot load frozen adapter: {FROZEN_ADAPTER}")
_FROZEN = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _FROZEN
_SPEC.loader.exec_module(_FROZEN)

China81PyVRPProblem = _FROZEN.China81PyVRPProblem
_native_solution_key = _FROZEN._native_solution_key
_project_initial_solution = _FROZEN._project_initial_solution
_translate_solution = _FROZEN._translate_solution
ROUTE_PROXY_MODES = frozenset((*_FROZEN.ROUTE_PROXY_MODES, "distance_only"))


def _distance_only_arc_cost(
    bundle: Any,
    left: str,
    right: str,
    load_kg: float,
    *,
    vehicle_type: str,
    fueling_depot_id: str | None = None,
    charging_depot_id: str | None = None,
    time_varying: bool = True,
) -> int:
    """Return raw directed distance metres and no project cost component."""

    del load_kg, fueling_depot_id, charging_depot_id, time_varying
    distance_m, _, _ = bundle.instance.arc_metrics(
        left,
        right,
        str(vehicle_type).lower(),
        fallback_speed_mps=float(bundle.prices.v_speed_ms),
    )
    return round(distance_m)


def build_pyvrp_problem(
    bundle: Any,
    *,
    route_proxy_mode: str = "distance_only",
    hard_home_depot_lock: bool = False,
) -> China81PyVRPProblem:
    """Build the isolated O-arm model without changing the frozen adapter."""

    normalized = str(route_proxy_mode).strip().lower()
    if normalized != "distance_only":
        raise ValueError(
            "isolated open-source adapter only supports 'distance_only'"
        )
    original = _FROZEN._proxy_arc_cost
    _FROZEN._proxy_arc_cost = _distance_only_arc_cost
    try:
        problem = _FROZEN.build_pyvrp_problem(
            bundle,
            route_proxy_mode="cv_only",
            hard_home_depot_lock=hard_home_depot_lock,
        )
    finally:
        _FROZEN._proxy_arc_cost = original
    return replace(problem, route_proxy_mode="distance_only")


__all__ = [
    "ROUTE_PROXY_MODES",
    "China81PyVRPProblem",
    "_distance_only_arc_cost",
    "_native_solution_key",
    "_project_initial_solution",
    "_translate_solution",
    "build_pyvrp_problem",
]
