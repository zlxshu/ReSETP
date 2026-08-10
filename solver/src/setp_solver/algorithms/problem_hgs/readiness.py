"""Observed-demand EV readiness for rolling Problem-HGS trials.

The routing population remains responsible for all revealed orders.  This
module only advances an otherwise idle physical EV between two disclosure
events.  It never receives hidden customer ids and it uses the shared
nonlinear charging curve rather than a linear energy/power shortcut.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from setp_solver.charging_curve import curve_for_charging_node
from setp_solver.cost import ev_instance_arc_energy_kwh
from setp_solver.search.dynamic_multitrip_schedule import DynamicAssetState
from setp_solver.solution import ChargingAction

OBSERVED_MAX_SINGLE_ORDER = "observed_max_single_order"


@dataclass(frozen=True)
class ObservedSingleOrderEnvelope:
    """One visible-demand reserve and its explicit physical limitations."""

    target_by_depot_kwh: Mapping[str, float]
    over_capacity_customer_ids_by_depot: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class ReadinessChargeInterval:
    """One actually elapsed part of an idle-EV depot charge."""

    physical_vehicle_id: str
    home_depot_id: str
    start_second: float
    end_second: float
    start_energy_kwh: float
    end_energy_kwh: float
    target_energy_kwh: float
    charging_curve_id: str

    @property
    def energy_kwh(self) -> float:
        return float(self.end_energy_kwh) - float(self.start_energy_kwh)

    def as_reserved_action(self) -> ChargingAction:
        """Expose the interval to cost/carbon/capacity accounting.

        The physical id is intentional: this is an asset-level standby action,
        not a charge attached retrospectively to a customer route.
        """

        return ChargingAction(
            vehicle_id=self.physical_vehicle_id,
            station_id=self.home_depot_id,
            energy_kwh=self.energy_kwh,
            occupancy_minutes=(self.end_second - self.start_second) / 60.0,
            charge_start_second=self.start_second,
            charge_day_offset=0,
            start_energy_kwh=self.start_energy_kwh,
            end_energy_kwh=self.end_energy_kwh,
            charging_curve_id=self.charging_curve_id,
        )


def observed_single_order_envelope(
    bundle,
    visible_customer_ids: Iterable[str],
) -> ObservedSingleOrderEnvelope:
    """Return one parameter-free observed service-energy envelope per depot.

    For each depot, the envelope is the largest exact EV energy needed to
    leave that depot, serve one *already visible* owned customer with its
    demand load, and return empty.  Hidden customers cannot influence it.
    A customer needing more than one complete battery is reported explicitly;
    the returned target is capped at physical battery capacity and is not
    described as covering that customer.
    """

    visible = {str(customer_id) for customer_id in visible_customer_ids}
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    unknown = visible.difference(nodes)
    if unknown:
        raise ValueError(
            "readiness reserve received unknown customer ids: "
            + ", ".join(sorted(unknown))
        )
    depots = sorted(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    )
    reserves = {depot_id: 0.0 for depot_id in depots}
    over_capacity = {depot_id: [] for depot_id in depots}
    capacity = bundle.instance.battery_capacity_kwh(
        fallback=float(bundle.prices.B_battery_kwh)
    )
    for customer_id in sorted(visible):
        node = nodes[customer_id]
        if node.node_type.lower() != "c":
            raise ValueError("readiness reserve accepts customer ids only")
        depot_id = str(bundle.customer_home_depot[customer_id])
        energy = ev_instance_arc_energy_kwh(
            bundle.instance,
            depot_id,
            customer_id,
            float(node.demand),
            bundle.prices,
        ) + ev_instance_arc_energy_kwh(
            bundle.instance,
            customer_id,
            depot_id,
            0.0,
            bundle.prices,
        )
        if energy > capacity + 1.0e-9:
            over_capacity[depot_id].append(customer_id)
        reserves[depot_id] = max(reserves[depot_id], min(capacity, energy))
    return ObservedSingleOrderEnvelope(
        target_by_depot_kwh=MappingProxyType(reserves),
        over_capacity_customer_ids_by_depot=MappingProxyType(
            {
                depot_id: tuple(customer_ids)
                for depot_id, customer_ids in over_capacity.items()
                if customer_ids
            }
        ),
    )


def observed_single_order_reserves_kwh(
    bundle,
    visible_customer_ids: Iterable[str],
) -> Mapping[str, float]:
    """Compatibility view of the observed envelope targets only."""

    return observed_single_order_envelope(
        bundle,
        visible_customer_ids,
    ).target_by_depot_kwh


def advance_idle_ev_readiness(
    asset_states: Mapping[str, DynamicAssetState],
    *,
    idle_asset_ids: Iterable[str],
    target_by_depot_kwh: Mapping[str, float],
    interval_start_second: float,
    interval_end_second: float,
    instance,
    prices,
) -> tuple[Mapping[str, DynamicAssetState], tuple[ReadinessChargeInterval, ...]]:
    """Advance only the declared idle EVs through one elapsed interval."""

    interval_start = float(interval_start_second)
    interval_end = float(interval_end_second)
    if interval_end < interval_start:
        raise ValueError("readiness interval end precedes its start")
    capacity = instance.battery_capacity_kwh(
        fallback=float(prices.B_battery_kwh)
    )
    curve = curve_for_charging_node(
        prices,
        node_type="d",
        capacity_kwh=capacity,
        reference_power_kw=float(prices.depot_charge_power_kw),
    )
    idle = {str(asset_id) for asset_id in idle_asset_ids}
    missing = idle.difference(asset_states)
    if missing:
        raise ValueError(
            "readiness interval received unknown assets: "
            + ", ".join(sorted(missing))
        )

    advanced = dict(asset_states)
    intervals: list[ReadinessChargeInterval] = []
    for asset_id in sorted(idle):
        state = asset_states[asset_id]
        if state.vehicle_type.lower() != "ev":
            raise ValueError("readiness charging accepts EV assets only")
        start = max(interval_start, float(state.available_second))
        if start >= interval_end:
            continue
        initial = float(state.remaining_battery_kwh)
        target = min(
            capacity,
            max(0.0, float(target_by_depot_kwh.get(state.home_depot_id, 0.0))),
        )
        if initial >= target - 1.0e-9:
            continue
        reachable = curve.reachable_energy_kwh(
            initial,
            interval_end - start,
        )
        final = min(target, reachable)
        if final <= initial + 1.0e-9:
            continue
        duration = curve.duration_seconds(initial, final)
        end = start + duration
        intervals.append(
            ReadinessChargeInterval(
                physical_vehicle_id=asset_id,
                home_depot_id=state.home_depot_id,
                start_second=start,
                end_second=end,
                start_energy_kwh=initial,
                end_energy_kwh=final,
                target_energy_kwh=target,
                charging_curve_id=curve.curve_id,
            )
        )
        advanced[asset_id] = replace(
            state,
            available_second=max(float(state.available_second), end),
            remaining_battery_kwh=final,
        )
    return MappingProxyType(advanced), tuple(intervals)
