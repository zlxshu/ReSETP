"""Temporary E5-B2 completion hook for the existing HGS/SP pipeline."""

from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from importlib import import_module
from typing import Iterator

from setp_solver.algorithms.resetp_alns.support.charging import (
    CHARGE_AMOUNT_STRATEGIES,
    normalize_charge_amount_strategies,
)
from setp_solver.china81_completion import (
    China81CompletionResult,
    complete_china81_route_skeleton,
)
from setp_solver.china81 import China81Bundle
from setp_solver.solution import Solution


B2_CHARGE_AMOUNT_STRATEGIES = CHARGE_AMOUNT_STRATEGIES


def complete_b2_route_skeleton(
    skeleton: Solution,
    bundle: China81Bundle,
    *,
    charge_amount_strategies: tuple[str, ...] = B2_CHARGE_AMOUNT_STRATEGIES,
) -> China81CompletionResult:
    return complete_china81_route_skeleton(
        skeleton,
        bundle,
        charge_amount_strategies=normalize_charge_amount_strategies(
            charge_amount_strategies
        ),
    )


@contextmanager
def b2_completion_hook(
    charge_amount_strategies: tuple[str, ...] = B2_CHARGE_AMOUNT_STRATEGIES,
) -> Iterator[object]:
    """Use B2 route-level charge choices only inside this context."""

    strategies = normalize_charge_amount_strategies(
        charge_amount_strategies
    )
    hooked = partial(
        complete_china81_route_skeleton,
        charge_amount_strategies=strategies,
    )
    modules = tuple(
        import_module(name)
        for name in ("pyvrp_adapter", "epochal_hgs", "route_pool_sp")
    )
    original = tuple(
        module.complete_china81_route_skeleton
        for module in modules
    )
    for module in modules:
        module.complete_china81_route_skeleton = hooked
    try:
        yield hooked
    finally:
        for module, completion in zip(modules, original, strict=True):
            module.complete_china81_route_skeleton = completion
