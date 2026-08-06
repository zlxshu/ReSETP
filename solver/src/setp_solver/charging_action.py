"""Neutral construction of charging actions shared by all solver layers."""

from __future__ import annotations

from typing import Any

from .charging_curve import ChargingCurveError, curve_from_parameters
from .instance_loader import Instance
from .prices import PriceParameters
from .solution import ChargingAction


def _curve_aware_action(
    *,
    vehicle_id: str,
    station_id: str,
    start_energy_kwh: float,
    energy_kwh: float,
    reference_power_kw: float,
    prices: PriceParameters | dict[str, Any] | Any,
    instance: Instance | None = None,
) -> ChargingAction:
    """Build one action whose duration and energy ledger share one curve."""

    try:
        curve = curve_from_parameters(
            prices,
            capacity_kwh=(
                _price(prices, "B_battery_kwh")
                if instance is None
                else instance.battery_capacity_kwh(
                    fallback=_price(prices, "B_battery_kwh"),
                )
            ),
            reference_power_kw=float(reference_power_kw),
        )
    except ChargingCurveError as exc:
        raise ValueError(f"invalid charging curve: {exc}") from exc
    start = float(start_energy_kwh)
    end = start + float(energy_kwh)
    if start < -1e-7 or end > curve.capacity_kwh + 1e-7:
        raise ValueError("charging action exceeds battery energy bounds")
    start = min(curve.capacity_kwh, max(0.0, start))
    end = min(curve.capacity_kwh, max(start, end))
    duration = curve.duration_seconds(start, end)
    return ChargingAction(
        vehicle_id=vehicle_id,
        station_id=station_id,
        energy_kwh=end - start,
        occupancy_minutes=duration / 60.0,
        charge_start_second=0.0,
        start_energy_kwh=start,
        end_energy_kwh=end,
        charging_curve_id=curve.curve_id,
    )


def _price(prices: PriceParameters | dict[str, Any] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
