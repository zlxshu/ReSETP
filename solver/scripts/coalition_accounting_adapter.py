"""Thin pyCoopGame adapter for the two-enterprise cost game.

declared_identity=PROJECT_ADAPTER
code_role=THIN_ADAPTER
"""

from __future__ import annotations

import importlib.util
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SOURCE_RELATIVE_PATH = Path(
    "third_party/harvested_materials/07_collaboration_profit/"
    "pycoopgame/upstream/pyCoopGame/Shapley.py"
)
_ABS_TOL = 1.0e-9
_REL_TOL = 1.0e-12


@dataclass(frozen=True)
class TwoEnterpriseCoalitionCosts:
    enterprise_a: str
    enterprise_b: str
    standalone_cost_a: float
    standalone_cost_b: float
    joint_cost: float


@dataclass(frozen=True)
class TwoEnterpriseParticipationInputs:
    joint_revenue: Mapping[str, float]
    joint_cost_total: Mapping[str, float]
    joint_profit: Mapping[str, float]
    pi0_profit: Mapping[str, float]


@dataclass(frozen=True)
class TwoEnterpriseShapleyAllocation:
    allocated_cost: Mapping[str, float]
    saving_cny: Mapping[str, float]
    saving_pct: Mapping[str, float]
    allocated_total: float
    joint_prior_profit: Mapping[str, float]
    allocated_profit: Mapping[str, float]
    operational_participation_margin: Mapping[str, float]
    allocated_participation_margin: Mapping[str, float]


class _CoalitionTable(dict[str, list[object]]):
    """Minimal column table accepted by the upstream Shapley function."""

    @property
    def index(self) -> range:
        return range(len(self["value"]))


def coalition_value_rows(
    costs: TwoEnterpriseCoalitionCosts,
) -> list[dict[str, object]]:
    """Return the complete, ordered two-player cost game."""

    _validate_costs(costs)
    return [
        {"coalition": [], "value": 0.0},
        {"coalition": [costs.enterprise_a], "value": costs.standalone_cost_a},
        {"coalition": [costs.enterprise_b], "value": costs.standalone_cost_b},
        {
            "coalition": [costs.enterprise_a, costs.enterprise_b],
            "value": costs.joint_cost,
        },
    ]


def allocate_two_enterprise_costs(
    costs: TwoEnterpriseCoalitionCosts,
    participation: TwoEnterpriseParticipationInputs,
    *,
    repo_root: Path,
) -> TwoEnterpriseShapleyAllocation:
    """Call the frozen upstream Shapley function and derive report fields."""

    rows = coalition_value_rows(costs)
    enterprises = (costs.enterprise_a, costs.enterprise_b)
    _validate_participation(participation, set(enterprises))
    shapley = _load_upstream_shapley(repo_root / SOURCE_RELATIVE_PATH)
    shares = shapley(
        _CoalitionTable(
            coalition=[row["coalition"] for row in rows],
            value=[row["value"] for row in rows],
        )
    )
    allocated_cost = {
        enterprise: float(shares[enterprise]) for enterprise in enterprises
    }
    allocated_total = sum(allocated_cost.values())
    if not _close(allocated_total, costs.joint_cost):
        raise RuntimeError("pyCoopGame allocation does not close to joint cost")
    standalone = {
        costs.enterprise_a: float(costs.standalone_cost_a),
        costs.enterprise_b: float(costs.standalone_cost_b),
    }
    saving = {
        enterprise: standalone[enterprise] - allocated_cost[enterprise]
        for enterprise in enterprises
    }
    prior = {
        enterprise: (
            float(participation.joint_profit[enterprise])
            - float(participation.joint_revenue[enterprise])
            + float(participation.joint_cost_total[enterprise])
        )
        for enterprise in enterprises
    }
    allocated_profit = {
        enterprise: float(participation.pi0_profit[enterprise])
        + saving[enterprise]
        for enterprise in enterprises
    }
    for enterprise in enterprises:
        rebuilt = (
            prior[enterprise]
            + float(participation.joint_revenue[enterprise])
            - float(participation.joint_cost_total[enterprise])
        )
        if not _close(rebuilt, participation.joint_profit[enterprise]):
            raise RuntimeError("joint ledger profit identity does not close")
    if not _close(
        sum(allocated_profit.values()),
        sum(float(value) for value in participation.joint_profit.values()),
    ):
        raise RuntimeError("allocated profit does not close to joint profit")
    return TwoEnterpriseShapleyAllocation(
        allocated_cost=allocated_cost,
        saving_cny=saving,
        saving_pct={
            enterprise: 100.0 * saving[enterprise] / standalone[enterprise]
            for enterprise in enterprises
        },
        allocated_total=allocated_total,
        joint_prior_profit=prior,
        allocated_profit=allocated_profit,
        operational_participation_margin={
            enterprise: (
                float(participation.joint_profit[enterprise])
                - float(participation.pi0_profit[enterprise])
            )
            for enterprise in enterprises
        },
        allocated_participation_margin={
            enterprise: (
                allocated_profit[enterprise]
                - float(participation.pi0_profit[enterprise])
            )
            for enterprise in enterprises
        },
    )


def _validate_costs(costs: TwoEnterpriseCoalitionCosts) -> None:
    if not costs.enterprise_a or not costs.enterprise_b:
        raise ValueError("enterprise names cannot be empty")
    if costs.enterprise_a == costs.enterprise_b:
        raise ValueError("enterprise names must differ")
    standalone = (costs.standalone_cost_a, costs.standalone_cost_b)
    if any(not math.isfinite(value) or value <= 0.0 for value in standalone):
        raise ValueError("standalone costs must be finite and positive")
    if not math.isfinite(costs.joint_cost) or costs.joint_cost < 0.0:
        raise ValueError("joint cost must be finite and nonnegative")


def _validate_participation(
    values: TwoEnterpriseParticipationInputs,
    enterprises: set[str],
) -> None:
    for name, mapping in (
        ("joint_revenue", values.joint_revenue),
        ("joint_cost_total", values.joint_cost_total),
        ("joint_profit", values.joint_profit),
        ("pi0_profit", values.pi0_profit),
    ):
        if set(mapping) != enterprises:
            raise ValueError(f"{name} must cover both enterprises exactly")
        if any(not math.isfinite(float(value)) for value in mapping.values()):
            raise ValueError(f"{name} values must be finite")


def _load_upstream_shapley(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "resetp_pycoopgame_shapley", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load pyCoopGame Shapley module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Shapley


def _close(left: float, right: float) -> bool:
    return math.isclose(
        float(left),
        float(right),
        rel_tol=_REL_TOL,
        abs_tol=_ABS_TOL,
    )
