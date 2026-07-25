"""Generic customer-cover, fleet, and charger-capacity route-column MIP."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


@dataclass(frozen=True)
class RouteColumn:
    customers: tuple[str, ...]
    cost: float
    fleet_delta: tuple[int, ...]
    charger_use: tuple[tuple[str, int, int, int], ...]
    payload: Any
    source: str


@dataclass(frozen=True)
class MipAssemblyResult:
    selected: tuple[RouteColumn, ...]
    objective: float | None
    status: int
    status_class: str
    message: str
    incumbent_available: bool
    dual_bound: float | None
    mip_gap: float | None
    mip_node_count: int | None
    elapsed_seconds: float
    integral: bool | None
    exact_cover: bool | None
    fleet_feasible: bool | None
    charger_feasible: bool | None


def solve_route_columns(
    customers: tuple[str, ...],
    columns: tuple[RouteColumn, ...],
    *,
    fleet_caps: tuple[int, ...],
    charger_caps: Mapping[str, int],
    time_limit_seconds: float,
) -> MipAssemblyResult:
    if not customers or len(set(customers)) != len(customers):
        raise ValueError("customers must be non-empty and unique")
    if not columns:
        raise ValueError("route-column pool is empty")
    if time_limit_seconds <= 0:
        raise ValueError("MIP time limit must be positive")
    if any(len(column.fleet_delta) != len(fleet_caps) for column in columns):
        raise ValueError("route-column fleet dimension mismatch")

    customer_index = {
        customer_id: index for index, customer_id in enumerate(customers)
    }
    cover = np.zeros((len(customers), len(columns)), dtype=float)
    for column_index, column in enumerate(columns):
        if not column.customers:
            raise ValueError("route column cannot be empty")
        if len(set(column.customers)) != len(column.customers):
            raise ValueError("route column repeats a customer")
        for customer_id in column.customers:
            try:
                cover[customer_index[customer_id], column_index] = 1.0
            except KeyError as exc:
                raise ValueError(
                    f"route column has unknown customer {customer_id!r}"
                ) from exc

    constraints: list[LinearConstraint] = [
        LinearConstraint(
            cover,
            lb=np.ones(len(customers)),
            ub=np.ones(len(customers)),
        )
    ]
    fleet = np.asarray(
        [column.fleet_delta for column in columns],
        dtype=float,
    ).T
    constraints.append(
        LinearConstraint(
            fleet,
            lb=np.full(len(fleet_caps), -np.inf),
            ub=np.asarray(fleet_caps, dtype=float),
        )
    )
    slot_keys = sorted(
        {
            (station, day, slot)
            for column in columns
            for station, day, slot, _ in column.charger_use
        }
    )
    if slot_keys:
        slot_index = {key: index for index, key in enumerate(slot_keys)}
        charger = np.zeros(
            (len(slot_keys), len(columns)),
            dtype=float,
        )
        for column_index, column in enumerate(columns):
            for station, day, slot, count in column.charger_use:
                charger[
                    slot_index[(station, day, slot)],
                    column_index,
                ] += int(count)
        constraints.append(
            LinearConstraint(
                charger,
                lb=np.full(len(slot_keys), -np.inf),
                ub=np.asarray(
                    [
                        int(charger_caps.get(station, 1))
                        for station, _, _ in slot_keys
                    ],
                    dtype=float,
                ),
            )
        )

    started = perf_counter()
    result = milp(
        c=np.asarray([column.cost for column in columns]),
        integrality=np.ones(len(columns)),
        bounds=Bounds(
            np.zeros(len(columns)),
            np.ones(len(columns)),
        ),
        constraints=constraints,
        options={"time_limit": float(time_limit_seconds)},
    )
    elapsed = perf_counter() - started
    if result.x is None:
        return MipAssemblyResult(
            selected=(),
            objective=None,
            status=int(result.status),
            status_class="NO_INCUMBENT",
            message=str(result.message),
            incumbent_available=False,
            dual_bound=_optional_float(result, "mip_dual_bound"),
            mip_gap=_optional_float(result, "mip_gap"),
            mip_node_count=_optional_int(result, "mip_node_count"),
            elapsed_seconds=elapsed,
            integral=None,
            exact_cover=None,
            fleet_feasible=None,
            charger_feasible=None,
        )
    vector = np.asarray(result.x, dtype=float)
    integral = bool(
        np.allclose(vector, np.rint(vector), rtol=0.0, atol=1.0e-7)
    )
    selected_vector = np.rint(vector)
    exact_cover = bool(
        integral
        and np.allclose(
            cover @ selected_vector,
            np.ones(len(customers)),
            rtol=0.0,
            atol=1.0e-7,
        )
    )
    fleet_feasible = bool(
        integral
        and np.all(fleet @ selected_vector <= np.asarray(fleet_caps) + 1e-7)
    )
    charger_feasible = True
    if slot_keys:
        charger_feasible = bool(
            integral
            and np.all(
                charger @ selected_vector
                <= np.asarray(
                    [
                        int(charger_caps.get(station, 1))
                        for station, _, _ in slot_keys
                    ]
                )
                + 1.0e-7
            )
        )
    accepted = (
        integral and exact_cover and fleet_feasible and charger_feasible
    )
    status_class = (
        "OPTIMAL"
        if accepted and bool(result.success) and int(result.status) == 0
        else (
            "LIMIT_WITH_INCUMBENT"
            if accepted
            else "REJECTED_INVALID_INCUMBENT"
        )
    )
    selected = (
        tuple(
            column
            for column, value in zip(columns, selected_vector, strict=True)
            if value > 0.5
        )
        if accepted
        else ()
    )
    return MipAssemblyResult(
        selected=selected,
        objective=(
            None if result.fun is None else float(result.fun)
        ),
        status=int(result.status),
        status_class=status_class,
        message=str(result.message),
        incumbent_available=True,
        dual_bound=_optional_float(result, "mip_dual_bound"),
        mip_gap=_optional_float(result, "mip_gap"),
        mip_node_count=_optional_int(result, "mip_node_count"),
        elapsed_seconds=elapsed,
        integral=integral,
        exact_cover=exact_cover,
        fleet_feasible=fleet_feasible,
        charger_feasible=charger_feasible,
    )


def _optional_float(result: Any, name: str) -> float | None:
    value = getattr(result, name, None)
    return None if value is None else float(value)


def _optional_int(result: Any, name: str) -> int | None:
    value = getattr(result, name, None)
    return None if value is None else int(value)
