"""Runtime-only battery, public-power, and curve overlay for E5-B."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from setp_solver.charging_curve import ChargingCurveSpec, L100_CONTROL
from setp_solver.china81 import China81Bundle


CAPACITY_SCENARIOS_KWH = (16.0, 20.0, 24.0, 28.0, 32.0)
PUBLIC_POWER_SCENARIOS_KW = (22.0, 60.0)

M17_22KW_NORMAL_PWL = ChargingCurveSpec(
    "M17_22KW_NORMAL_PWL",
    (0.0, 0.85, 0.95, 1.0),
    (
        21.93548387096774 / 22.0,
        10.66666666666667 / 22.0,
        3.333333333333333 / 22.0,
    ),
)

CURVES = {
    L100_CONTROL.curve_id: L100_CONTROL,
    M17_22KW_NORMAL_PWL.curve_id: M17_22KW_NORMAL_PWL,
}

def apply_runtime_overlay(
    bundle: China81Bundle,
    *,
    capacity_kwh: float,
    curve_id: str,
    public_charge_power_kw: float = 22.0,
) -> China81Bundle:
    """Return one full-departure battery/curve scenario without changing data."""

    capacity = float(capacity_kwh)
    if capacity not in CAPACITY_SCENARIOS_KWH:
        raise ValueError(
            f"capacity must be one of {CAPACITY_SCENARIOS_KWH}, got {capacity}"
        )
    public_power = float(public_charge_power_kw)
    if public_power not in PUBLIC_POWER_SCENARIOS_KW:
        raise ValueError(
            "public charge power must be one of "
            f"{PUBLIC_POWER_SCENARIOS_KW}, got {public_power}"
        )
    if curve_id not in CURVES:
        raise ValueError(f"unknown E5-B curve: {curve_id}")
    curve = CURVES[curve_id]

    if bundle.instance.vehicle_parameters is None:
        raise ValueError("E5-B requires the profiled China81 vehicle parameters")
    vehicle_parameters = dict(bundle.instance.vehicle_parameters)
    vehicle_parameters["ev"] = replace(
        vehicle_parameters["ev"],
        battery_kwh=capacity,
    )
    nodes = [
        replace(node, charge_power_kw=public_power)
        if node.node_type.lower() == "f"
        else node
        for node in bundle.instance.nodes
    ]
    instance = replace(
        bundle.instance,
        nodes=nodes,
        vehicle_parameters=vehicle_parameters,
    )
    prices = replace(
        bundle.prices,
        B_battery_kwh=capacity,
        initial_ev_battery_kwh=capacity,
        charging_curve_id=curve.curve_id,
        charging_soc_breakpoints=curve.soc_breakpoints,
        charging_relative_powers=curve.relative_powers,
        depot_charge_power_kw=22.0,
    )
    charger_scenario = {
        node_id: dict(values)
        for node_id, values in bundle.charger_scenario_by_node.items()
    }
    for node in nodes:
        if node.node_type.lower() == "f":
            charger_scenario[node.node_id]["charge_power_kw"] = public_power
    overlaid = replace(
        bundle,
        instance=instance,
        prices=prices,
        charger_scenario_by_node=MappingProxyType(
            {
                node_id: MappingProxyType(values)
                for node_id, values in charger_scenario.items()
            }
        ),
    )

    if not (
        overlaid.instance.battery_capacity_kwh(
            fallback=overlaid.prices.B_battery_kwh
        )
        == overlaid.prices.B_battery_kwh
        == overlaid.prices.initial_ev_battery_kwh
        == capacity
    ):
        raise RuntimeError("E5-B battery capacity is inconsistent at runtime")

    if any(
        current.node_id != original.node_id
        or current.charge_power_kw
        != (
            public_power
            if original.node_type.lower() == "f"
            else original.charge_power_kw
        )
        for original, current in zip(
            bundle.instance.nodes,
            instance.nodes,
            strict=True,
        )
    ):
        raise RuntimeError("E5-B public-station power overlay is inconsistent")
    return overlaid
