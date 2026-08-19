"""Shared feasible warm-start construction used by retained data tools."""

from __future__ import annotations

from typing import Any

from ..check import check_solution
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import Solution
from .bundle import SearchBundle
from .construction import build_initial_solution
from .fleet import infer_fleet_limits


def make_shared_initial_solution(
    bundle: SearchBundle,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> Solution:
    limits = infer_fleet_limits(bundle.bundle_dir)
    solution = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        fleet_limits=limits,
        introduce_ev=True,
        require_charging_signal=False,
    )
    violations = check_solution(solution, bundle.instance, prices)
    if violations:
        detail = "; ".join(
            f"{item.type}:{item.vehicle_id}:{item.location}:{item.detail}"
            for item in violations[:6]
        )
        raise ValueError(f"shared warm start is infeasible: {detail}")
    return solution
