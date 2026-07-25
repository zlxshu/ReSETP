#!/usr/bin/env python3
"""Small exact-cover MIP with residual fleet and per-slot charger limits."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import numpy as np
from mip_core import RouteColumn
from scipy.optimize import Bounds, LinearConstraint, milp


@dataclass(frozen=True)
class PairMipResult:
    selected: tuple[RouteColumn, ...]
    objective: float | None
    status: int
    status_class: str
    message: str
    dual_bound: float | None
    mip_gap: float | None
    mip_node_count: int | None
    elapsed_seconds: float
    integral: bool | None
    exact_cover: bool | None
    fleet_feasible: bool | None
    charger_feasible: bool | None


def solve_pair_columns(
    customers: tuple[str, ...],
    columns: tuple[RouteColumn, ...],
    *,
    residual_fleet_caps: tuple[int, ...],
    residual_charger_caps: Mapping[tuple[str, int, int], int],
    time_limit_seconds: float,
) -> PairMipResult:
    if not customers or len(customers) != len(set(customers)):
        raise ValueError("pair customers must be non-empty and unique")
    if not columns:
        raise ValueError("pair route-column pool is empty")
    if any(cap < 0 for cap in residual_fleet_caps):
        raise ValueError("negative residual fleet capacity")
    if any(cap < 0 for cap in residual_charger_caps.values()):
        raise ValueError("negative residual charger capacity")
    if any(len(column.fleet_delta) != len(residual_fleet_caps) for column in columns):
        raise ValueError("pair fleet dimension mismatch")

    customer_index = {customer_id: index for index, customer_id in enumerate(customers)}
    cover = np.zeros((len(customers), len(columns)), dtype=float)
    for column_index, column in enumerate(columns):
        for customer_id in column.customers:
            try:
                cover[customer_index[customer_id], column_index] = 1.0
            except KeyError as exc:
                raise ValueError(
                    f"pair column has outside customer {customer_id}"
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
            lb=np.full(len(residual_fleet_caps), -np.inf),
            ub=np.asarray(residual_fleet_caps, dtype=float),
        )
    )

    slot_keys = sorted(
        {
            (station, day, slot)
            for column in columns
            for station, day, slot, _ in column.charger_use
        }
    )
    charger: np.ndarray | None = None
    if slot_keys:
        missing = [key for key in slot_keys if key not in residual_charger_caps]
        if missing:
            raise ValueError(f"missing residual charger capacity for {missing[0]}")
        slot_index = {key: index for index, key in enumerate(slot_keys)}
        charger = np.zeros((len(slot_keys), len(columns)), dtype=float)
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
                    [residual_charger_caps[key] for key in slot_keys],
                    dtype=float,
                ),
            )
        )

    started = perf_counter()
    result = milp(
        c=np.asarray([column.cost for column in columns], dtype=float),
        integrality=np.ones(len(columns)),
        bounds=Bounds(np.zeros(len(columns)), np.ones(len(columns))),
        constraints=constraints,
        options={"time_limit": float(time_limit_seconds)},
    )
    elapsed = perf_counter() - started
    if result.x is None:
        return _empty_result(result, elapsed)

    vector = np.asarray(result.x, dtype=float)
    integral = bool(np.allclose(vector, np.rint(vector), rtol=0.0, atol=1.0e-7))
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
        and np.all(fleet @ selected_vector <= np.asarray(residual_fleet_caps) + 1.0e-7)
    )
    charger_feasible = bool(
        charger is None
        or (
            integral
            and np.all(
                charger @ selected_vector
                <= np.asarray([residual_charger_caps[key] for key in slot_keys])
                + 1.0e-7
            )
        )
    )
    accepted = integral and exact_cover and fleet_feasible and charger_feasible
    status_class = (
        "OPTIMAL"
        if accepted and bool(result.success) and int(result.status) == 0
        else ("LIMIT_WITH_INCUMBENT" if accepted else "REJECTED_INVALID_INCUMBENT")
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
    return PairMipResult(
        selected=selected,
        objective=None if result.fun is None else float(result.fun),
        status=int(result.status),
        status_class=status_class,
        message=str(result.message),
        dual_bound=_optional_float(result, "mip_dual_bound"),
        mip_gap=_optional_float(result, "mip_gap"),
        mip_node_count=_optional_int(result, "mip_node_count"),
        elapsed_seconds=elapsed,
        integral=integral,
        exact_cover=exact_cover,
        fleet_feasible=fleet_feasible,
        charger_feasible=charger_feasible,
    )


def _empty_result(result: Any, elapsed: float) -> PairMipResult:
    return PairMipResult(
        selected=(),
        objective=None,
        status=int(result.status),
        status_class="NO_INCUMBENT",
        message=str(result.message),
        dual_bound=_optional_float(result, "mip_dual_bound"),
        mip_gap=_optional_float(result, "mip_gap"),
        mip_node_count=_optional_int(result, "mip_node_count"),
        elapsed_seconds=elapsed,
        integral=None,
        exact_cover=None,
        fleet_feasible=None,
        charger_feasible=None,
    )


def _optional_float(result: Any, name: str) -> float | None:
    value = getattr(result, name, None)
    return None if value is None else float(value)


def _optional_int(result: Any, name: str) -> int | None:
    value = getattr(result, name, None)
    return None if value is None else int(value)
