"""SISR-inspired adjacent string removal for isolated ALNS development.

The ruin mechanism follows Christiaens and Vanden Berghe (2020),
doi:10.1287/trsc.2019.0914.  Frozen VRPTW parameters follow the Apache-2.0
reference implementation at hankarudova/open-source-sisr-routing, branch
``vrptw``, commit ``857c8eeafd95cbdf8245620486d309369f1aab20``.

Only the ruin operator is implemented here.  The paper's blinked recreate and
fleet-minimisation acceptance are deliberately excluded so the G1 ablation
changes one mechanism at a time.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from setp_solver.algorithms.resetp_alns.kernel.alns_core import (
    AlnsState,
    _customers_in_solution,
    _remove_customers,
    _route_customer_ids,
)


@dataclass(frozen=True)
class SisrStringRemovalParameters:
    """Literature-frozen parameters for the vehicle-count-first VRPTW phase."""

    max_string_length: int = 10
    average_removed_customers: int = 10
    split_probability: float = 0.5
    preserved_segment_stop_probability: float = 0.01


DEFAULT_SISR_STRING_PARAMETERS = SisrStringRemovalParameters()


def sisr_string_removal(
    state: AlnsState,
    rng: np.random.Generator,
    **kwargs: Any,
) -> AlnsState:
    """Remove spatially related route strings while preserving route order.

    ``remove_count_q`` is intentionally ignored: SISR derives both the number
    of affected routes and each removed-string length from its published
    parameters.  Letting the outer ALNS q-controller override them would turn
    this first G1 test into a parameter hybrid rather than a clean component
    ablation.
    """

    _ = kwargs
    parameters = DEFAULT_SISR_STRING_PARAMETERS
    route_customers = {
        route_index: _route_customer_ids(route, state.context.instance)
        for route_index, route in enumerate(state.solution.routes)
    }
    route_customers = {
        route_index: customers
        for route_index, customers in route_customers.items()
        if customers
    }
    customers = _customers_in_solution(state.solution, state.context.instance)
    if not customers or not route_customers:
        return state

    route_by_customer = {
        customer_id: route_index
        for route_index, customer_ids in route_customers.items()
        for customer_id in customer_ids
    }
    mean_route_length = len(customers) / len(route_customers)
    max_removed_from_route = min(
        float(parameters.max_string_length),
        float(mean_route_length),
    )
    max_affected_routes = (
        4.0 * float(parameters.average_removed_customers)
    ) / (1.0 + max_removed_from_route)
    affected_route_count = min(
        len(route_customers),
        max(
            1,
            int(math.floor(float(rng.uniform(1.0, max(1.0, max_affected_routes))))),
        ),
    )

    seed_customer = str(rng.choice(customers))
    spatial_order = sorted(
        customers,
        key=lambda customer_id: (
            float(state.context.instance.distance(seed_customer, customer_id)),
            customer_id,
        ),
    )
    selected_routes: set[int] = set()
    removed_customers: list[str] = []
    for nearby_customer in spatial_order:
        route_index = route_by_customer[nearby_customer]
        if route_index in selected_routes:
            continue
        customer_ids = route_customers[route_index]
        anchor_index = customer_ids.index(nearby_customer)
        route_length = len(customer_ids)
        removal_cap = min(float(route_length), max_removed_from_route)
        removal_length = int(math.floor(float(rng.uniform(0.0, removal_cap)))) + 1

        use_split_string = (
            removal_length > 1
            and removal_length < route_length
            and float(rng.random()) <= parameters.split_probability
        )
        if not use_split_string:
            start = _random_substring_start_including(
                route_length,
                removal_length,
                anchor_index,
                rng,
            )
            selected = customer_ids[start : start + removal_length]
        else:
            preserved_length = 1
            max_preserved_length = route_length - removal_length
            while (
                preserved_length < max_preserved_length
                and float(rng.random())
                > parameters.preserved_segment_stop_probability
            ):
                preserved_length += 1
            whole_length = removal_length + preserved_length
            whole_start = _random_substring_start_including(
                route_length,
                whole_length,
                anchor_index,
                rng,
            )
            whole = customer_ids[whole_start : whole_start + whole_length]
            preserved_start = int(
                rng.integers(0, whole_length - preserved_length + 1)
            )
            selected = [
                *whole[:preserved_start],
                *whole[preserved_start + preserved_length :],
            ]

        removed_customers.extend(selected)
        selected_routes.add(route_index)
        if len(selected_routes) >= affected_route_count:
            break

    if not removed_customers:
        return state
    return _remove_customers(state, removed_customers)


def _random_substring_start_including(
    full_length: int,
    substring_length: int,
    required_index: int,
    rng: np.random.Generator,
) -> int:
    """Choose a uniform valid substring start that contains one route index."""

    if not 0 < substring_length <= full_length:
        raise ValueError("substring length must be within the route")
    if not 0 <= required_index < full_length:
        raise ValueError("required index must be within the route")
    minimum = max(0, required_index - substring_length + 1)
    maximum = min(full_length - substring_length, required_index)
    return int(rng.integers(minimum, maximum + 1))

