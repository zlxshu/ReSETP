"""Frozen artificial fixtures for the mechanism-priced pair-resplit gate.

The fixtures exercise the real ReSETP evaluator and checker without invoking
ALNS, HGS, ``winner.py``, or any route-search entry point.  They are deliberately
small:

* ``binding_fixture`` makes distance-only ranking prefer short but
  responsibility-misaligned cuts, while the full mechanism score can expose a
  cheaper responsibility-aware cut.
* ``nonbinding_fixture`` is already at the only sensible route boundary.
* ``joint_station_conflict_fixture`` proves that two routes can each be
  feasible alone yet infeasible together at a one-plug public station.

These inputs are development fixtures, not performance evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.check import check_solution  # noqa: E402
from setp_solver.instance_loader import Instance, Node  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.evaluation import EvaluationContext  # noqa: E402
from setp_solver.solution import ChargingAction, Route, Solution  # noqa: E402
from v7_responsibility_solver import annotate_cross_site_services  # noqa: E402


@dataclass(frozen=True)
class PairResplitFixture:
    name: str
    context: EvaluationContext
    source: Solution
    expected_mechanism_left: tuple[str, ...] | None = None
    expected_mechanism_right: tuple[str, ...] | None = None


@dataclass(frozen=True)
class JointStationConflictFixture:
    name: str
    context: EvaluationContext
    left_only: Solution
    right_only: Solution
    joint: Solution


def binding_fixture() -> PairResplitFixture:
    """Return a six-customer fixture with a pre-registered ranking split."""

    coordinates = {
        "D0": (0.0, 0.0),
        "D1": (12_000.0, 0.0),
        "C1": (9_505.952588351165, 1_315.8462375264862),
        "C2": (6_034.212829161623, -718.771908802647),
        "C3": (2_646.3607440863125, 57.74134949141808),
        "C4": (7_127.941928282309, -4_505.167494376392),
        "C5": (148.77767077585895, 737.4639375989955),
        "C6": (-1_118.7894007578905, -1_865.0213863398558),
    }
    owners = {
        "C1": "D0",
        "C2": "D0",
        "C3": "D1",
        "C4": "D1",
        "C5": "D1",
        "C6": "D0",
    }
    instance = _coordinate_instance(
        coordinates,
        customer_ids=("C1", "C2", "C3", "C4", "C5", "C6"),
        num_cv=2,
        num_ev=0,
    )
    prices = replace(
        DEFAULT_PRICES,
        Q_capacity=5_000.0,
        B_battery_kwh=0.0,
        initial_ev_battery_kwh=0.0,
        vehicle_fixed_cost=10.0,
        cross_site_cost=100.0,
    )
    context = EvaluationContext(
        instance=instance,
        carbon_profile=_carbon_profile(),
        prices=prices,
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    source = annotate_cross_site_services(
        Solution(
            routes=[
                Route(
                    "CV_BIND_LEFT#T1",
                    "cv",
                    "D0",
                    ["D0", "C5", "C6", "C1", "D0"],
                ),
                Route(
                    "CV_BIND_RIGHT#T1",
                    "cv",
                    "D1",
                    ["D1", "C2", "C3", "C4", "D1"],
                ),
            ]
        ),
        owners,
    )
    _assert_feasible(source, context, "binding source")
    return PairResplitFixture(
        name="binding_cross_site_boundary_6c",
        context=context,
        source=source,
        expected_mechanism_left=("C5", "C6", "C1", "C2"),
        expected_mechanism_right=("C3", "C4"),
    )


def nonbinding_fixture() -> PairResplitFixture:
    """Return a two-customer fixture whose current boundary is already best."""

    coordinates = {
        "D0": (0.0, 0.0),
        "D1": (10_000.0, 0.0),
        "C1": (500.0, 0.0),
        "C2": (9_500.0, 0.0),
    }
    owners = {"C1": "D0", "C2": "D1"}
    instance = _coordinate_instance(
        coordinates,
        customer_ids=("C1", "C2"),
        num_cv=2,
        num_ev=0,
    )
    prices = replace(
        DEFAULT_PRICES,
        Q_capacity=5_000.0,
        B_battery_kwh=0.0,
        initial_ev_battery_kwh=0.0,
        vehicle_fixed_cost=10.0,
        cross_site_cost=100.0,
    )
    context = EvaluationContext(
        instance=instance,
        carbon_profile=_carbon_profile(),
        prices=prices,
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    source = annotate_cross_site_services(
        Solution(
            routes=[
                Route(
                    "CV_STABLE_LEFT#T1",
                    "cv",
                    "D0",
                    ["D0", "C1", "D0"],
                ),
                Route(
                    "CV_STABLE_RIGHT#T1",
                    "cv",
                    "D1",
                    ["D1", "C2", "D1"],
                ),
            ]
        ),
        owners,
    )
    _assert_feasible(source, context, "nonbinding source")
    return PairResplitFixture(
        name="nonbinding_aligned_boundary_2c",
        context=context,
        source=source,
    )


def joint_station_conflict_fixture() -> JointStationConflictFixture:
    """Return a real one-plug conflict with route-attached charging actions."""

    nodes = [
        Node(
            "D0",
            "d",
            0.0,
            0.0,
            due_time=100_000.0,
            station_chargers=2,
        ),
        Node("C1", "c", 0.0, 0.0, demand=0.0, due_time=100_000.0),
        Node("C2", "c", 0.0, 0.0, demand=0.0, due_time=100_000.0),
        Node(
            "F1",
            "f",
            0.0,
            0.0,
            due_time=0.0,
            charge_power_kw=60.0,
            station_chargers=1,
        ),
    ]
    instance = Instance(
        nodes=nodes,
        distance_matrix=[[0.0 for _ in nodes] for _ in nodes],
        num_cv=2,
        num_ev=2,
    )
    prices = replace(
        DEFAULT_PRICES,
        B_battery_kwh=80.0,
        initial_ev_battery_kwh=0.0,
        Q_capacity=5_000.0,
    )
    context = EvaluationContext(
        instance=instance,
        carbon_profile=_carbon_profile(),
        prices=prices,
        customer_home_depot={"C1": "D0", "C2": "D0"},
        allow_cross_depot=True,
    )
    left_ev = Route(
        "EV_CONFLICT_LEFT#T1",
        "ev",
        "D0",
        ["D0", "C1", "F1", "D0"],
    )
    right_ev = Route(
        "EV_CONFLICT_RIGHT#T1",
        "ev",
        "D0",
        ["D0", "C2", "F1", "D0"],
    )
    left_cv = Route(
        "CV_CONFLICT_LEFT#T1",
        "cv",
        "D0",
        ["D0", "C1", "F1", "D0"],
    )
    right_cv = Route(
        "CV_CONFLICT_RIGHT#T1",
        "cv",
        "D0",
        ["D0", "C2", "F1", "D0"],
    )
    left_action = ChargingAction(
        left_ev.vehicle_id,
        "F1",
        energy_kwh=5.0,
        occupancy_minutes=30.0,
        charge_start_second=0.0,
    )
    right_action = ChargingAction(
        right_ev.vehicle_id,
        "F1",
        energy_kwh=5.0,
        occupancy_minutes=30.0,
        charge_start_second=0.0,
    )
    left_only = Solution(
        routes=[left_ev, right_cv],
        charging_actions=[left_action],
    )
    right_only = Solution(
        routes=[left_cv, right_ev],
        charging_actions=[right_action],
    )
    joint = Solution(
        routes=[left_ev, right_ev],
        charging_actions=[left_action, right_action],
    )
    _assert_feasible(left_only, context, "joint-conflict left-only control")
    _assert_feasible(right_only, context, "joint-conflict right-only control")
    return JointStationConflictFixture(
        name="joint_public_station_capacity_conflict",
        context=context,
        left_only=left_only,
        right_only=right_only,
        joint=joint,
    )


def _coordinate_instance(
    coordinates: dict[str, tuple[float, float]],
    *,
    customer_ids: tuple[str, ...],
    num_cv: int,
    num_ev: int,
) -> Instance:
    ordered_ids = ("D0", "D1", *customer_ids)
    nodes = [
        Node(
            node_id=node_id,
            node_type=("d" if node_id.startswith("D") else "c"),
            x=float(coordinates[node_id][0]),
            y=float(coordinates[node_id][1]),
            demand=(0.0 if node_id.startswith("D") else 100.0),
            ready_time=0.0,
            due_time=100_000.0,
            service_time=0.0,
            station_chargers=(4 if node_id.startswith("D") else None),
        )
        for node_id in ordered_ids
    ]
    matrix = [
        [
            float(
                math.dist(
                    coordinates[left_id],
                    coordinates[right_id],
                )
            )
            for right_id in ordered_ids
        ]
        for left_id in ordered_ids
    ]
    return Instance(
        nodes=nodes,
        distance_matrix=matrix,
        num_cv=num_cv,
        num_ev=num_ev,
    )


def _carbon_profile() -> list[dict[str, Any]]:
    values = (
        300.0,
        280.0,
        260.0,
        240.0,
        220.0,
        200.0,
        180.0,
        160.0,
    )
    return [
        {
            "time_index": index,
            "datetime_utc": f"fixture-slot-{index:02d}",
            "actual_gco2_per_kwh": values[index % len(values)],
            "forecast_gco2_per_kwh": values[index % len(values)],
            "index_label": "fixture",
            "index_code": 0,
            "horizon_second_start": float(index * 1_800),
        }
        for index in range(48)
    ]


def _assert_feasible(
    solution: Solution,
    context: EvaluationContext,
    label: str,
) -> None:
    violations = check_solution(
        solution,
        context.instance,
        context.prices,
    )
    if violations:
        raise RuntimeError(f"{label} is infeasible: {violations[:8]}")
