"""Runtime contract for the 2026-08-11 private-instance rebuild.

The shared evaluator reads vehicle-specific daily fixed costs from the
China81 data authority.  This module verifies the approved final EV
non-energy and daily fixed-cost parameters from that contract, and
enforces the two-shift route contract for witnessed routes.

The rebuilt bundle is authorized for the bounded mechanism search approved on
2026-08-11.  The loader still applies only the frozen rebuild contracts; it
does not enable profit fairness or any unrelated experiment feature.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .charging_curve import (
    ChargingCurveSpec,
    M17_22KW_NORMAL_PWL,
    M17_FAST_SHAPE_SCALED_60KW_PWL,
)
from .china81 import (
    CV_FIXED_CNY_PER_DAY,
    EV_FIXED_CNY_PER_DAY,
    EV_NON_ENERGY_CNY_PER_KM,
    ENDOGENOUS_FLEET_PARAMETERS,
    China81Bundle,
    China81FleetParameterClass,
    load_china81_bundle,
)
from .cost import evaluate
from .instance_loader import Instance, Node
from .search.multitrip_schedule import route_timing
from .solution import Route, Solution


INSTANCE_ID = "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS"
BUNDLE_RELATIVE = Path(
    "data/ChinaInstances/china81_private_rebuild_v1_20260811"
)
BATTERY_DEPRECIATION_CNY_PER_KM = 0.2445
EV_DAILY_FIXED_PREMIUM_CNY = 50.0
ATTENDANCE_START_SECOND = 8 * 60 * 60
ATTENDANCE_END_SECOND = 19 * 60 * 60


@dataclass(frozen=True)
class DepotChargingScenario:
    """One registered depot power/curve pairing for the rebuilt instance."""

    scenario_id: str
    power_kw: float
    curve: ChargingCurveSpec


DEPOT_CHARGING_22KW = DepotChargingScenario(
    scenario_id="depot_22kw_montoya_normal",
    power_kw=22.0,
    curve=M17_22KW_NORMAL_PWL,
)
DEPOT_CHARGING_60KW = DepotChargingScenario(
    scenario_id="depot_60kw_p35_registered_fast_shape",
    power_kw=60.0,
    curve=M17_FAST_SHAPE_SCALED_60KW_PWL,
)
DEPOT_CHARGING_SCENARIOS = {
    "22kw": DEPOT_CHARGING_22KW,
    "60kw": DEPOT_CHARGING_60KW,
}


@dataclass(frozen=True)
class PrivateInstanceRebuildBundle:
    """China81 runtime facts plus the approved rebuild-only contracts."""

    china81: China81Bundle
    orders_by_customer: Mapping[str, Mapping[str, str]]
    shift_contract: Mapping[str, Any]
    vehicle_cost_contract: Mapping[str, Mapping[str, str]]
    contestability_contract: Mapping[str, Any]
    depot_charging_scenario_id: str

    @property
    def instance(self) -> Instance:
        return self.china81.instance

    @property
    def prices(self):
        return self.china81.prices

    @property
    def time_profile(self) -> list[dict[str, Any]]:
        return self.china81.time_profile

    @property
    def customer_home_depot(self) -> Mapping[str, str]:
        return self.china81.customer_home_depot


def load_private_instance_rebuild(
    repo_root: str | Path,
    *,
    bundle_relative: str | Path = BUNDLE_RELATIVE,
    fleet_parameters: China81FleetParameterClass = ENDOGENOUS_FLEET_PARAMETERS,
    depot_charging_scenario: DepotChargingScenario = DEPOT_CHARGING_60KW,
) -> PrivateInstanceRebuildBundle:
    """Load the rebuilt instance and apply its explicit runtime contracts."""

    root = Path(repo_root).resolve()
    authority = (root / Path(bundle_relative)).resolve()
    if not authority.is_dir():
        raise ValueError(f"rebuilt instance authority is missing: {authority}")

    vehicle_rows = _read_csv(authority / "vehicle_costs.csv")
    vehicle_cost_contract = MappingProxyType(
        {
            row["vehicle_type"]: MappingProxyType(dict(row))
            for row in vehicle_rows
        }
    )
    if set(vehicle_cost_contract) != {"cv", "ev"}:
        raise ValueError("rebuilt vehicle-cost contract must contain CV and EV")
    ev_contract = vehicle_cost_contract["ev"]
    ev_contract_effective = float(
        ev_contract["effective_non_energy_cost_cny_per_km"]
    )
    # P55: component fields remain provenance only.  Runtime receives the
    # approved final constant and never reconstructs it with float addition.
    if ev_contract_effective != EV_NON_ENERGY_CNY_PER_KM:
        raise ValueError(
            "rebuilt EV effective non-energy cost disagrees with approved "
            "final constant"
        )

    base = load_china81_bundle(
        root,
        INSTANCE_ID,
        static_input_authority=authority,
        road_matrix_authority=authority,
        fleet_authority=authority,
        fleet_parameters=fleet_parameters,
    )

    depot_curve = depot_charging_scenario.curve
    adjusted_prices = replace(
        base.prices,
        depot_charge_power_kw=depot_charging_scenario.power_kw,
        charging_curve_id=depot_curve.curve_id,
        charging_soc_breakpoints=depot_curve.soc_breakpoints,
        charging_relative_powers=depot_curve.relative_powers,
        depot_charging_curve_id=depot_curve.curve_id,
        depot_charging_soc_breakpoints=depot_curve.soc_breakpoints,
        depot_charging_relative_powers=depot_curve.relative_powers,
    )

    adjusted_nodes = [
        replace(
            node,
            ready_time=float(ATTENDANCE_START_SECOND),
            due_time=float(ATTENDANCE_END_SECOND),
            charge_power_kw=(
                depot_charging_scenario.power_kw
                if node.node_type.lower() == "d"
                else node.charge_power_kw
            ),
        )
        if node.node_type.lower() in {"d", "f"}
        else node
        for node in base.instance.nodes
    ]
    parameters = dict(base.instance.vehicle_parameters or {})
    try:
        ev = parameters["ev"]
    except KeyError as exc:
        raise ValueError("rebuilt instance has no EV vehicle profile") from exc
    parameters["ev"] = replace(
        ev,
        non_energy_distance_cost_per_km=EV_NON_ENERGY_CNY_PER_KM,
        source_ids=tuple(
            dict.fromkeys(
                (
                    *ev.source_ids,
                    "BATTERY_DEPRECIATION_CHANGJIANG_2024_"
                    "GOEKE_SCHNEIDER_2015",
                )
            )
        ),
    )
    adjusted_instance = replace(
        base.instance,
        nodes=adjusted_nodes,
        vehicle_parameters=MappingProxyType(parameters),
    )
    adjusted_charger_scenarios = MappingProxyType(
        {
            node_id: MappingProxyType(
                {
                    **dict(values),
                    **(
                        {
                            "charge_power_kw": depot_charging_scenario.power_kw,
                            "charging_curve_id": depot_curve.curve_id,
                            "charging_scenario_id": (
                                depot_charging_scenario.scenario_id
                            ),
                        }
                        if adjusted_instance.nodes[
                            adjusted_instance.node_index[node_id]
                        ].node_type.lower()
                        == "d"
                        else {}
                    ),
                }
            )
            for node_id, values in base.charger_scenario_by_node.items()
        }
    )
    base = replace(
        base,
        instance=adjusted_instance,
        prices=adjusted_prices,
        charger_scenario_by_node=adjusted_charger_scenarios,
        formal_search_allowed=True,
    )

    orders = _read_csv(authority / "orders.csv")
    orders_by_customer = MappingProxyType(
        {
            row["customer_id"]: MappingProxyType(dict(row))
            for row in orders
            if row["instance_id"] == INSTANCE_ID
        }
    )
    expected = {
        node.node_id
        for node in adjusted_instance.nodes
        if node.node_type.lower() == "c"
    }
    if set(orders_by_customer) != expected:
        raise ValueError("rebuilt instance order/customer identities disagree")

    shift_contract = json.loads(
        (authority / "shift_contract.json").read_text(encoding="utf-8")
    )
    contestability_contract = json.loads(
        (authority / "contestability_definition.json").read_text(
            encoding="utf-8"
        )
    )
    _validate_loaded_contract(
        base,
        orders_by_customer,
        shift_contract,
        vehicle_cost_contract,
    )
    return PrivateInstanceRebuildBundle(
        china81=base,
        orders_by_customer=orders_by_customer,
        shift_contract=MappingProxyType(shift_contract),
        vehicle_cost_contract=vehicle_cost_contract,
        contestability_contract=MappingProxyType(contestability_contract),
        depot_charging_scenario_id=depot_charging_scenario.scenario_id,
    )


def validate_shifted_solution(
    solution: Solution,
    bundle: PrivateInstanceRebuildBundle,
    *,
    departure_second_by_route: Mapping[str, float],
) -> tuple[dict[str, float | str], ...]:
    """Validate witnessed route clocks against the two-shift hard contract.

    A route may only contain customers from one shift.  The caller supplies
    its witnessed departure clock because legacy ``Solution`` routes do not
    carry departure times.  The exact road timing recursion then proves the
    route returns by the corresponding shift boundary.
    """

    rows: list[dict[str, float | str]] = []
    for route in solution.routes:
        customer_ids = [
            node_id
            for node_id in route.node_sequence[1:-1]
            if node_id in bundle.orders_by_customer
        ]
        shifts = {
            bundle.orders_by_customer[node_id]["shift_id"]
            for node_id in customer_ids
        }
        if len(shifts) != 1:
            raise ValueError(
                f"route {route.vehicle_id} mixes shifts or has no customer: "
                f"{sorted(shifts)}"
            )
        shift_id = next(iter(shifts))
        shift = bundle.shift_contract["shifts"][shift_id]
        route_volume = sum(
            float(bundle.orders_by_customer[node_id]["source_volume_m3"])
            for node_id in customer_ids
        )
        capacity = float(bundle.shift_contract["vehicle_volume_capacity_m3"])
        if route_volume > capacity + 1.0e-9:
            raise ValueError(
                f"route {route.vehicle_id} exceeds volume capacity: "
                f"{route_volume} > {capacity}"
            )
        departure = float(departure_second_by_route[route.vehicle_id])
        start = float(shift["start_minute"]) * 60.0
        end = float(shift["end_minute"]) * 60.0
        if departure < start - 1.0e-6:
            raise ValueError(
                f"route {route.vehicle_id} departs before {shift_id}"
            )
        timing = route_timing(
            route,
            bundle.instance,
            bundle.prices,
            forced_departure_second=departure,
        )
        if float(timing.return_second) > end + 1.0e-6:
            raise ValueError(
                f"route {route.vehicle_id} returns after {shift_id} ends"
            )
        rows.append(
            {
                "vehicle_id": route.vehicle_id,
                "shift_id": shift_id,
                "departure_second": departure,
                "return_second": float(timing.return_second),
            }
        )
    return tuple(rows)


def evaluate_rebuild_solution(
    solution: Solution,
    bundle: PrivateInstanceRebuildBundle,
    *,
    carbon_quota_kg: float = 0.0,
) -> dict[str, float]:
    """Evaluate cost with battery depreciation and EV daily premium active."""

    breakdown = dict(
        evaluate(
            solution,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
            carbon_quota_kg=carbon_quota_kg,
        )
    )
    cv_fixed = bundle.instance.vehicle_fixed_cost_per_day(
        "cv",
        fallback=float(bundle.prices.vehicle_fixed_cost),
    )
    ev_fixed = bundle.instance.vehicle_fixed_cost_per_day(
        "ev",
        fallback=float(bundle.prices.vehicle_fixed_cost),
    )
    premium = float(breakdown["n_veh_ev"]) * (ev_fixed - cv_fixed)
    breakdown["cost_fix_ev_premium"] = premium
    return breakdown


def route_distance_m(
    route: Route,
    instance: Instance,
    *,
    profile: str | None = None,
) -> float:
    """Return an exact directed-road distance for one route."""

    chosen = profile or route.vehicle_type.lower()
    return sum(
        instance.arc_metrics(
            left,
            right,
            chosen,
            fallback_speed_mps=1.0,
        )[0]
        for left, right in zip(route.node_sequence, route.node_sequence[1:])
    )


def _validate_loaded_contract(
    base: China81Bundle,
    orders: Mapping[str, Mapping[str, str]],
    shifts: Mapping[str, Any],
    vehicle_costs: Mapping[str, Mapping[str, str]],
) -> None:
    if not base.formal_search_allowed:
        raise ValueError("rebuilt mechanism-validation authority must enable search")
    if set(shifts.get("shifts", {})) != {"AM", "PM"}:
        raise ValueError("rebuilt shift contract must contain AM and PM")
    counts = {
        shift_id: sum(row["shift_id"] == shift_id for row in orders.values())
        for shift_id in ("AM", "PM")
    }
    if counts != {"AM": 17, "PM": 33}:
        raise ValueError(f"rebuilt shift counts disagree: {counts}")
    for customer_id, row in orders.items():
        width = (
            float(row["time_window_late_minute"])
            - float(row["time_window_early_minute"])
        )
        if not math.isclose(
            width,
            float(row["source_time_window_width_minute"]),
            abs_tol=2.0e-6,
        ):
            raise ValueError(f"window width changed for {customer_id}")
    ev = base.instance.vehicle_parameters["ev"]
    expected_ev_km = float(
        vehicle_costs["ev"]["effective_non_energy_cost_cny_per_km"]
    )
    if (
        expected_ev_km != EV_NON_ENERGY_CNY_PER_KM
        or float(ev.non_energy_distance_cost_per_km)
        != EV_NON_ENERGY_CNY_PER_KM
    ):
        raise ValueError("approved EV non-energy cost is not active in runtime")
    approved_fixed_costs = {
        "cv": CV_FIXED_CNY_PER_DAY,
        "ev": EV_FIXED_CNY_PER_DAY,
    }
    for vehicle_type in ("cv", "ev"):
        runtime_cost = base.instance.vehicle_fixed_cost_per_day(
            vehicle_type,
            fallback=float(base.prices.vehicle_fixed_cost),
        )
        authority_cost = float(
            vehicle_costs[vehicle_type]["effective_daily_fixed_cost_cny"]
        )
        approved_cost = approved_fixed_costs[vehicle_type]
        if authority_cost != approved_cost or runtime_cost != approved_cost:
            raise ValueError(
                f"{vehicle_type.upper()} daily fixed cost is not active in runtime"
            )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))
