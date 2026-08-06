"""Explicit charging-start policies shared by depot and public charging."""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any

from .cost import (
    CARBON_SLOT_SECONDS,
    best_charging_action_start,
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    charging_curve_for_action,
)
from .instance_loader import Instance
from .prices import DEFAULT_PRICES, PriceParameters
from .solution import ChargingAction


CHARGE_TIMING_POLICIES = frozenset(
    {
        "asap",
        "cost_min",
        "cost_plus_carbon",
        "carbon_min",
    }
)
DEFAULT_CHARGE_TIMING_POLICY = "carbon_min"


def validate_charge_timing_policy(policy: str) -> str:
    """Validate and return one of the four registered timing policies."""

    if policy not in CHARGE_TIMING_POLICIES:
        raise ValueError(
            "unknown charge timing policy: "
            f"{policy!r}; expected one of {sorted(CHARGE_TIMING_POLICIES)}"
        )
    return policy


def _price(prices: Any, field: str) -> float:
    if isinstance(prices, dict):
        return float(prices[field])
    return float(getattr(prices, field))


def _timing_candidates(
    action: ChargingAction,
    earliest_start_second: float,
    latest_start_second: float,
    instance: Instance,
    prices: PriceParameters | dict[str, Any] | Any,
) -> tuple[float, ...]:
    """Return the probe-defined exact breakpoints for monetary timing."""

    earliest = float(earliest_start_second)
    latest = float(latest_start_second)
    if latest < earliest - 1.0e-9:
        raise ValueError("latest charging start precedes earliest start")
    duration = float(action.occupancy_minutes) * 60.0
    phase_boundaries = {0.0, duration}
    curve_state = charging_curve_for_action(action, instance, prices)
    if curve_state is not None:
        curve, start_energy, end_energy = curve_state
        for phase in curve.phases(start_energy, end_energy):
            phase_boundaries.add(float(phase.relative_start_seconds))
            phase_boundaries.add(float(phase.relative_end_seconds))
    candidates = {earliest, latest}
    first_grid = math.floor(earliest / CARBON_SLOT_SECONDS) - 1
    final_grid = math.ceil((latest + duration) / CARBON_SLOT_SECONDS) + 1
    for index in range(first_grid, final_grid + 1):
        boundary = float(index) * CARBON_SLOT_SECONDS
        for phase_boundary in phase_boundaries:
            candidate = boundary - phase_boundary
            if earliest - 1.0e-9 <= candidate <= latest + 1.0e-9:
                candidates.add(min(latest, max(earliest, candidate)))
    return tuple(sorted(round(value, 9) for value in candidates))


def charge_timing_objective_value(
    action: ChargingAction,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, Any] | Any = DEFAULT_PRICES,
    *,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
) -> float:
    """Return the registered timing objective for one already placed action."""

    policy = validate_charge_timing_policy(charge_timing_policy)
    if policy == "asap":
        return 0.0
    if policy == "carbon_min":
        return float(
            charging_action_emissions_kg(
                action,
                instance,
                carbon_profile,
                prices,
            )
        )
    electricity_cost = charging_action_electricity_cost(
        action,
        instance,
        carbon_profile,
        prices,
    )
    carbon_price = _price(prices, "carbon_price")
    if policy == "cost_min" or carbon_price == 0.0:
        return float(electricity_cost)
    charging_emissions = charging_action_emissions_kg(
        action,
        instance,
        carbon_profile,
        prices,
    )
    score = electricity_cost + carbon_price * charging_emissions
    return float(score)


def select_charge_timing_start(
    action: ChargingAction,
    *,
    earliest_start_second: float,
    latest_start_second: float,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, Any] | Any = DEFAULT_PRICES,
    charge_timing_policy: str = DEFAULT_CHARGE_TIMING_POLICY,
    intensity_field: str = "actual_gco2_per_kwh",
) -> float:
    """Choose a feasible start under one explicit registered policy."""

    policy = validate_charge_timing_policy(charge_timing_policy)
    earliest = float(earliest_start_second)
    latest = float(latest_start_second)
    if latest < earliest - 1.0e-9:
        raise ValueError("latest charging start precedes earliest start")
    if policy == "asap" or latest <= earliest + 1.0e-9:
        return earliest
    if policy == "carbon_min":
        return best_charging_action_start(
            action,
            earliest_start_second=earliest,
            latest_start_second=latest,
            instance=instance,
            carbon_profile=carbon_profile,
            prices=prices,
            intensity_field=intensity_field,
        )
    if intensity_field != "actual_gco2_per_kwh":
        raise ValueError(
            "charge timing only accepts the actual registered carbon field"
        )
    carbon_price = _price(prices, "carbon_price")
    if policy == "cost_plus_carbon" and carbon_price == 0.0:
        policy = "cost_min"
    candidates = _timing_candidates(
        action,
        earliest,
        latest,
        instance,
        prices,
    )
    scored: list[tuple[float, float]] = []
    for start in candidates:
        shifted = replace(action, charge_start_second=float(start))
        electricity_cost = charging_action_electricity_cost(
            shifted,
            instance,
            carbon_profile,
            prices,
        )
        if policy == "cost_min":
            score = electricity_cost
        else:
            charging_emissions = charging_action_emissions_kg(
                shifted,
                instance,
                carbon_profile,
                prices,
            )
            score = electricity_cost + carbon_price * charging_emissions
        scored.append((float(score), float(start)))
    return min(scored, key=lambda item: (item[0], item[1]))[1]
