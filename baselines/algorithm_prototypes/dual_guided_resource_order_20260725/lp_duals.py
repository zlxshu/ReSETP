"""LP-relaxation dual extraction and deterministic route-pair selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
from scipy.optimize import linprog

from mip_core import RouteColumn


TOL = 1.0e-7


@dataclass(frozen=True)
class ResourceRow:
    key: tuple[Any, ...]
    capacity: float
    marginal: float
    scarcity: float


@dataclass(frozen=True)
class LpDualResult:
    objective: float
    dual_objective: float
    primal_residual: float
    stationarity_residual: float
    customer_marginals: tuple[tuple[str, float], ...]
    resources: tuple[ResourceRow, ...]
    column_reduced_costs: tuple[float, ...]
    iterations: int


def solve_pool_lp_duals(
    customers: tuple[str, ...],
    columns: tuple[RouteColumn, ...],
    *,
    fleet_caps: tuple[int, ...],
    charger_caps: Mapping[str, int],
) -> LpDualResult:
    """Solve the frozen route-pool LP with HiGHS dual simplex."""

    if not customers or len(customers) != len(set(customers)):
        raise ValueError("customers must be non-empty and unique")
    if not columns:
        raise ValueError("route pool is empty")
    if any(len(column.fleet_delta) != len(fleet_caps) for column in columns):
        raise ValueError("fleet dimension mismatch")

    customer_index = {item: index for index, item in enumerate(customers)}
    cover = np.zeros((len(customers), len(columns)), dtype=float)
    for column_index, column in enumerate(columns):
        for customer in column.customers:
            cover[customer_index[customer], column_index] = 1.0

    fleet = np.asarray(
        [column.fleet_delta for column in columns],
        dtype=float,
    ).T
    slot_keys = sorted(
        {
            (station, day, slot)
            for column in columns
            for station, day, slot, _ in column.charger_use
        }
    )
    charger = np.zeros((len(slot_keys), len(columns)), dtype=float)
    slot_index = {key: index for index, key in enumerate(slot_keys)}
    for column_index, column in enumerate(columns):
        for station, day, slot, count in column.charger_use:
            charger[slot_index[(station, day, slot)], column_index] += int(count)

    upper_blocks = [fleet]
    upper_rhs = [np.asarray(fleet_caps, dtype=float)]
    resource_keys: list[tuple[Any, ...]] = [
        ("fleet", index) for index in range(len(fleet_caps))
    ]
    if slot_keys:
        upper_blocks.append(charger)
        upper_rhs.append(
            np.asarray(
                [int(charger_caps.get(station, 1)) for station, _, _ in slot_keys],
                dtype=float,
            )
        )
        resource_keys.extend(("charger", *key) for key in slot_keys)
    a_ub = np.vstack(upper_blocks)
    b_ub = np.concatenate(upper_rhs)
    costs = np.asarray([column.cost for column in columns], dtype=float)
    result = linprog(
        costs,
        A_ub=a_ub,
        b_ub=b_ub,
        A_eq=cover,
        b_eq=np.ones(len(customers), dtype=float),
        bounds=(0.0, 1.0),
        method="highs-ds",
    )
    if not result.success or int(result.status) != 0 or result.x is None:
        raise RuntimeError(
            f"route-pool LP is not optimal: {result.status}: {result.message}"
        )
    if (
        result.eqlin.marginals is None
        or result.ineqlin.marginals is None
        or result.lower.marginals is None
        or result.upper.marginals is None
    ):
        raise RuntimeError("HiGHS did not return complete LP marginals")

    vector = np.asarray(result.x, dtype=float)
    eq_marginals = np.asarray(result.eqlin.marginals, dtype=float)
    ub_marginals = np.asarray(result.ineqlin.marginals, dtype=float)
    lower_marginals = np.asarray(result.lower.marginals, dtype=float)
    upper_marginals = np.asarray(result.upper.marginals, dtype=float)
    primal_residual = max(
        float(np.max(np.abs(cover @ vector - 1.0))),
        float(np.max(np.maximum(a_ub @ vector - b_ub, 0.0))),
    )
    stationarity = (
        costs
        - cover.T @ eq_marginals
        - a_ub.T @ ub_marginals
        - lower_marginals
        - upper_marginals
    )
    stationarity_residual = float(np.max(np.abs(stationarity)))
    dual_objective = float(
        np.sum(eq_marginals)
        + b_ub @ ub_marginals
        + np.sum(upper_marginals)
    )
    if (
        primal_residual > TOL
        or stationarity_residual > TOL
        or not np.isclose(
            float(result.fun),
            dual_objective,
            rtol=1.0e-9,
            atol=1.0e-6,
        )
    ):
        raise RuntimeError(
            "LP primal/dual closure failed: "
            f"primal={primal_residual}, stationarity={stationarity_residual}, "
            f"primal_obj={result.fun}, dual_obj={dual_objective}"
        )

    resources = tuple(
        ResourceRow(
            key=key,
            capacity=float(capacity),
            marginal=float(marginal),
            scarcity=max(0.0, -float(marginal)),
        )
        for key, capacity, marginal in zip(
            resource_keys,
            b_ub,
            ub_marginals,
            strict=True,
        )
    )
    reduced_costs = costs - cover.T @ eq_marginals - a_ub.T @ ub_marginals
    return LpDualResult(
        objective=float(result.fun),
        dual_objective=dual_objective,
        primal_residual=primal_residual,
        stationarity_residual=stationarity_residual,
        customer_marginals=tuple(
            (customer, float(value))
            for customer, value in zip(customers, eq_marginals, strict=True)
        ),
        resources=resources,
        column_reduced_costs=tuple(float(value) for value in reduced_costs),
        iterations=int(result.nit),
    )


def route_resource_vector(
    column: RouteColumn,
    resources: tuple[ResourceRow, ...],
) -> tuple[float, ...]:
    """Return a route's use of each LP upper-bound resource."""

    slot_use = {
        ("charger", station, day, slot): int(count)
        for station, day, slot, count in column.charger_use
    }
    values: list[float] = []
    for resource in resources:
        if resource.key[0] == "fleet":
            values.append(float(column.fleet_delta[int(resource.key[1])]))
        else:
            values.append(float(slot_use.get(resource.key, 0)))
    return tuple(values)


def rank_route_pairs(
    route_columns: tuple[RouteColumn, ...],
    route_signatures: tuple[tuple[Any, ...], ...],
    duals: LpDualResult,
    *,
    limit: int = 2,
) -> tuple[tuple[int, int, float], ...]:
    """Rank unordered incumbent-route pairs by the frozen pressure formula."""

    if len(route_columns) != len(route_signatures):
        raise ValueError("route columns/signatures length mismatch")
    vectors = [
        route_resource_vector(column, duals.resources)
        for column in route_columns
    ]
    rows: list[tuple[float, tuple[Any, ...], int, int]] = []
    for first in range(len(route_columns)):
        for second in range(first + 1, len(route_columns)):
            pressure = 0.0
            for resource, left, right in zip(
                duals.resources,
                vectors[first],
                vectors[second],
                strict=True,
            ):
                pressure += resource.scarcity * (
                    left + right + min(left, right)
                )
            pair_signature = tuple(
                sorted((route_signatures[first], route_signatures[second]))
            )
            rows.append((-float(pressure), pair_signature, first, second))
    rows.sort()
    return tuple(
        (first, second, -negative_pressure)
        for negative_pressure, _, first, second in rows[:limit]
    )

