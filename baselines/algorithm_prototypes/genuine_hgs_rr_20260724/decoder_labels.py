"""Dominance labels for the depot--vehicle--charge--time decoder."""

from __future__ import annotations

from dataclasses import dataclass
import math


TOL = 1.0e-9


@dataclass(frozen=True)
class DecoderLabel:
    """One partial route completion state at a fixed customer prefix."""

    prefix_index: int
    current_node_id: str
    home_depot_id: str
    vehicle_type: str
    city_id: str
    date: str
    price_area_id: str
    carbon_source_column: str
    diesel_zone: str
    time_second: float
    remaining_capacity_kg: float
    remaining_energy_kwh: float | None
    cv_fleet_used: int
    ev_fleet_used: int
    variable_cost_cny: float
    carbon_kg: float
    objective_cost_cny: float

    def __post_init__(self) -> None:
        numeric = (
            self.time_second,
            self.remaining_capacity_kg,
            self.variable_cost_cny,
            self.carbon_kg,
            self.objective_cost_cny,
        )
        if any(not math.isfinite(float(value)) for value in numeric):
            raise ValueError("decoder label contains a non-finite value")
        if self.remaining_energy_kwh is not None and not math.isfinite(
            float(self.remaining_energy_kwh)
        ):
            raise ValueError("decoder label energy is non-finite")
        if self.cv_fleet_used < 0 or self.ev_fleet_used < 0:
            raise ValueError("fleet usage cannot be negative")

    @property
    def state_identity(self) -> tuple[object, ...]:
        return (
            self.prefix_index,
            self.current_node_id,
            self.home_depot_id,
            self.vehicle_type,
            self.city_id,
            self.date,
            self.price_area_id,
            self.carbon_source_column,
            self.diesel_zone,
        )


def dominates(
    left: DecoderLabel,
    right: DecoderLabel,
    *,
    tolerance: float = TOL,
) -> bool:
    """Return true only for a safe same-state resource dominance."""

    if left.state_identity != right.state_identity:
        return False
    if (left.remaining_energy_kwh is None) != (
        right.remaining_energy_kwh is None
    ):
        return False
    no_worse = (
        left.time_second <= right.time_second + tolerance
        and left.remaining_capacity_kg
        >= right.remaining_capacity_kg - tolerance
        and left.cv_fleet_used <= right.cv_fleet_used
        and left.ev_fleet_used <= right.ev_fleet_used
        and left.variable_cost_cny
        <= right.variable_cost_cny + tolerance
        and left.carbon_kg <= right.carbon_kg + tolerance
        and left.objective_cost_cny
        <= right.objective_cost_cny + tolerance
    )
    if left.remaining_energy_kwh is not None:
        no_worse = no_worse and (
            left.remaining_energy_kwh
            >= right.remaining_energy_kwh - tolerance
        )
    if not no_worse:
        return False
    strict = (
        left.time_second < right.time_second - tolerance
        or left.remaining_capacity_kg
        > right.remaining_capacity_kg + tolerance
        or left.cv_fleet_used < right.cv_fleet_used
        or left.ev_fleet_used < right.ev_fleet_used
        or left.variable_cost_cny
        < right.variable_cost_cny - tolerance
        or left.carbon_kg < right.carbon_kg - tolerance
        or left.objective_cost_cny
        < right.objective_cost_cny - tolerance
    )
    if left.remaining_energy_kwh is not None:
        strict = strict or (
            left.remaining_energy_kwh
            > right.remaining_energy_kwh + tolerance
        )
    return strict


class DominanceFrontier:
    """Keep only non-dominated decoder labels for one route prefix."""

    def __init__(self) -> None:
        self._labels: list[DecoderLabel] = []

    @property
    def labels(self) -> tuple[DecoderLabel, ...]:
        return tuple(self._labels)

    def add(self, candidate: DecoderLabel) -> bool:
        if any(dominates(row, candidate) for row in self._labels):
            return False
        self._labels = [
            row
            for row in self._labels
            if not dominates(candidate, row)
        ]
        if candidate not in self._labels:
            self._labels.append(candidate)
            self._labels.sort(
                key=lambda row: (
                    row.state_identity,
                    row.objective_cost_cny,
                    row.time_second,
                    -(
                        row.remaining_energy_kwh
                        if row.remaining_energy_kwh is not None
                        else 0.0
                    ),
                )
            )
        return True
