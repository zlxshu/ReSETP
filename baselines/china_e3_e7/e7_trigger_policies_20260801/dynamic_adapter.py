"""Full-fleet handoff and per-order rejection for rebuilt E7."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from setp_solver.search.dynamic_multitrip_schedule import DynamicAssetState


@dataclass(frozen=True)
class PlanAttempt:
    feasible: bool
    payload: Any = None
    reason: str = ""


@dataclass(frozen=True)
class AdmissionResult:
    accepted_customer_ids: tuple[str, ...]
    rejected_customer_ids: tuple[str, ...]
    rejected_revenue: float
    plan_payload: Any
    planner_call_count: int


Planner = Callable[[tuple[str, ...], Mapping[str, DynamicAssetState]], PlanAttempt]


def inject_full_fleet_asset_states(
    existing: Mapping[str, DynamicAssetState],
    fleet_caps: Mapping[str, Mapping[str, int]],
    *,
    available_second: float,
    unused_ev_battery_kwh: float,
) -> Mapping[str, DynamicAssetState]:
    """Preserve active assets and add every missing vehicle allowed by the caps."""

    release = float(available_second)
    ev_battery = float(unused_ev_battery_kwh)
    if not math.isfinite(release) or not math.isfinite(ev_battery) or ev_battery < 0.0:
        raise ValueError("invalid unused-vehicle state")

    result = dict(existing)
    counts: dict[tuple[str, str], int] = {}
    for asset_id, state in result.items():
        vehicle_type = state.vehicle_type.lower()
        if (
            asset_id != state.physical_vehicle_id
            or vehicle_type not in {"cv", "ev"}
            or state.home_depot_id not in fleet_caps
        ):
            raise ValueError(f"asset {asset_id} is outside the fleet authority")
        key = (state.home_depot_id, vehicle_type)
        counts[key] = counts.get(key, 0) + 1

    for depot_id, caps in sorted(fleet_caps.items()):
        for vehicle_type, field in (("cv", "num_cv"), ("ev", "num_ev")):
            cap = int(caps[field])
            present = counts.get((depot_id, vehicle_type), 0)
            if cap < present:
                raise ValueError(f"existing {vehicle_type} assets at {depot_id} exceed cap")
            suffix = 1
            while present < cap:
                asset_id = f"{vehicle_type.upper()}_{depot_id}_{suffix}"
                suffix += 1
                if asset_id in result:
                    continue
                result[asset_id] = DynamicAssetState(
                    asset_id,
                    vehicle_type,
                    depot_id,
                    release,
                    ev_battery if vehicle_type == "ev" else 0.0,
                    1,
                )
                present += 1
    return MappingProxyType(result)


def admit_new_orders_or_reject_individually(
    already_accepted: Sequence[str],
    new_orders: Sequence[str],
    demand_kg: Mapping[str, float],
    *,
    revenue_per_kg: float,
    full_asset_states: Mapping[str, DynamicAssetState],
    planner: Planner,
) -> AdmissionResult:
    """Try the full batch, then reject only individually infeasible orders."""

    accepted = tuple(map(str, already_accepted))
    new = tuple(map(str, new_orders))
    if len(set((*accepted, *new))) != len(accepted) + len(new):
        raise ValueError("order ids overlap or repeat")
    rho = float(revenue_per_kg)
    if not math.isfinite(rho) or rho < 0.0:
        raise ValueError("invalid revenue per kg")
    if any(
        not math.isfinite(float(demand_kg[customer_id]))
        or float(demand_kg[customer_id]) <= 0.0
        for customer_id in new
    ):
        raise ValueError("new-order demand must be positive")

    base = planner(accepted, full_asset_states)
    if not base.feasible:
        raise RuntimeError(f"accepted orders are already infeasible: {base.reason}")
    if not new:
        return AdmissionResult(accepted, (), 0.0, base.payload, 1)

    whole = planner((*accepted, *new), full_asset_states)
    if whole.feasible:
        return AdmissionResult((*accepted, *new), (), 0.0, whole.payload, 2)

    current = list(accepted)
    rejected: list[str] = []
    payload = base.payload
    calls = 2
    for customer_id in new:
        attempt = planner((*current, customer_id), full_asset_states)
        calls += 1
        if attempt.feasible:
            current.append(customer_id)
            payload = attempt.payload
        else:
            rejected.append(customer_id)
    lost_revenue = sum(rho * float(demand_kg[customer_id]) for customer_id in rejected)
    return AdmissionResult(tuple(current), tuple(rejected), lost_revenue, payload, calls)
