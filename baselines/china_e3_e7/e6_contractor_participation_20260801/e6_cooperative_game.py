"""Exact allocation rules for the small E6 cooperative game."""

from __future__ import annotations

import itertools
import math
from typing import Iterable

import numpy as np
from scipy.optimize import linprog

Coalition = tuple[str, ...]


def coalitions(members: Iterable[str]) -> tuple[Coalition, ...]:
    ordered = tuple(sorted(members))
    return tuple(
        group
        for size in range(1, len(ordered) + 1)
        for group in itertools.combinations(ordered, size)
    )


def shapley(values: dict[Coalition, float], members: Coalition) -> dict[str, float]:
    n = len(members)
    output = {member: 0.0 for member in members}
    for member in members:
        others = tuple(item for item in members if item != member)
        for size in range(n):
            weight = math.factorial(size) * math.factorial(n - size - 1) / math.factorial(n)
            for group in itertools.combinations(others, size):
                base = tuple(sorted(group))
                joined = tuple(sorted((*group, member)))
                output[member] += weight * (values[joined] - values.get(base, 0.0))
    return output


def core_allocation(
    values: dict[Coalition, float], members: Coalition
) -> tuple[bool, dict[str, float] | None]:
    proper = [group for group in coalitions(members) if len(group) < len(members)]
    matrix = np.array(
        [[-1.0 if member in group else 0.0 for member in members] for group in proper]
    )
    result = linprog(
        np.zeros(len(members)),
        A_ub=matrix,
        b_ub=np.array([-values[group] for group in proper]),
        A_eq=np.ones((1, len(members))),
        b_eq=np.array([values[members]]),
        bounds=[(None, None)] * len(members),
        method="highs",
    )
    if not result.success:
        return False, None
    return True, {member: float(result.x[index]) for index, member in enumerate(members)}


def core_violations(
    allocation: dict[str, float], values: dict[Coalition, float], members: Coalition
) -> dict[Coalition, float]:
    return {
        group: values[group] - sum(allocation[member] for member in group)
        for group in coalitions(members)
        if values[group] - sum(allocation[member] for member in group) > 1e-7
    }


def nucleolus(
    values: dict[Coalition, float], members: Coalition, *, tolerance: float = 1e-7
) -> dict[str, float]:
    """Return the exact LP nucleolus of a small transferable-utility game."""

    members = tuple(sorted(members))
    proper = [group for group in coalitions(members) if len(group) < len(members)]
    incidence = {
        group: np.array([1.0 if member in group else 0.0 for member in members])
        for group in proper
    }
    fixed: dict[Coalition, float] = {}
    remaining = list(proper)

    while remaining:
        equality_rows = [np.append(np.ones(len(members)), 0.0)]
        equality_rhs = [values[members]]
        for group, excess in fixed.items():
            equality_rows.append(np.append(incidence[group], 0.0))
            equality_rhs.append(values[group] - excess)

        stage = linprog(
            np.append(np.zeros(len(members)), 1.0),
            A_ub=np.array([np.append(-incidence[group], -1.0) for group in remaining]),
            b_ub=np.array([-values[group] for group in remaining]),
            A_eq=np.array(equality_rows),
            b_eq=np.array(equality_rhs),
            bounds=[(None, None)] * (len(members) + 1),
            method="highs",
        )
        if not stage.success:
            raise RuntimeError(f"nucleolus LP failed: {stage.message}")
        stage_excess = float(stage.x[-1])

        face_ub = np.array([-incidence[group] for group in remaining])
        face_rhs = np.array([stage_excess - values[group] for group in remaining])
        face_eq = np.array([row[:-1] for row in equality_rows])
        newly_fixed: list[Coalition] = []
        for group in remaining:
            objective = incidence[group]
            low = linprog(
                objective,
                A_ub=face_ub,
                b_ub=face_rhs,
                A_eq=face_eq,
                b_eq=np.array(equality_rhs),
                bounds=[(None, None)] * len(members),
                method="highs",
            )
            high = linprog(
                -objective,
                A_ub=face_ub,
                b_ub=face_rhs,
                A_eq=face_eq,
                b_eq=np.array(equality_rhs),
                bounds=[(None, None)] * len(members),
                method="highs",
            )
            if not low.success or not high.success:
                raise RuntimeError("nucleolus optimal-face check failed")
            lower = float(low.fun)
            upper = float(-high.fun)
            boundary = values[group] - stage_excess
            if upper - lower <= tolerance and abs(lower - boundary) <= tolerance:
                newly_fixed.append(group)

        if not newly_fixed:
            raise RuntimeError("nucleolus LP did not expose a fixed coalition")
        for group in newly_fixed:
            fixed[group] = stage_excess
        remaining = [group for group in remaining if group not in fixed]

        equality_rank = np.linalg.matrix_rank(
            np.array([np.ones(len(members))] + [incidence[group] for group in fixed]),
            tol=tolerance,
        )
        if equality_rank == len(members):
            break

    final_rows = [np.ones(len(members))]
    final_rhs = [values[members]]
    for group, excess in fixed.items():
        final_rows.append(incidence[group])
        final_rhs.append(values[group] - excess)
    matrix = np.array(final_rows, dtype=float)
    rhs = np.array(final_rhs, dtype=float)
    allocation, *_ = np.linalg.lstsq(matrix, rhs, rcond=None)
    residual = float(np.max(np.abs(matrix @ allocation - rhs)))
    if residual > 10 * tolerance:
        raise RuntimeError(f"nucleolus equalities do not close: {residual}")
    return {member: float(allocation[index]) for index, member in enumerate(members)}
