"""Explicit charging-start policies shared by depot and public charging."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any

from .charging_curve import ChargePhase, ChargingCurveError, PiecewiseChargingCurve
from .cost import (
    CARBON_SLOT_SECONDS,
    GCO2_PER_KGCO2,
    best_charging_action_start,
    carbon_profile_row_for_slot,
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    charging_curve_for_action,
    time_profile_rows_for_node,
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


@dataclass(frozen=True)
class _ActionGeometry:
    """Validated action geometry that is independent of its clock placement."""

    duration_seconds: float
    energy_kwh: float
    curve: PiecewiseChargingCurve | None
    phases: tuple[ChargePhase, ...]
    phase_boundaries: tuple[float, ...]


class _ProfileView:
    """One station's immutable view of a solve-time price/carbon profile."""

    def __init__(
        self,
        instance: Instance,
        station_id: str,
        profile: list[dict[str, Any]],
        prices: PriceParameters | dict[str, Any] | Any,
    ) -> None:
        self.rows = time_profile_rows_for_node(instance, station_id, profile)
        self._slot_rows: dict[int, dict[str, Any]] = {}
        node_index = instance.node_index.get(station_id)
        node = None if node_index is None else instance.nodes[node_index]
        self._node_type = (
            None if node is None else node.node_type.lower()
        )
        self._prices = prices
        has_time_varying_price = any(
            "depot_energy_cny_per_kwh" in row
            or "public_total_cny_per_kwh" in row
            for row in self.rows
        )
        has_complete_time_varying_price = bool(self.rows) and all(
            "depot_energy_cny_per_kwh" in row
            and "public_total_cny_per_kwh" in row
            for row in self.rows
        )
        self._partial_time_varying_price = (
            has_time_varying_price and not has_complete_time_varying_price
        )
        self._price_field = (
            "depot_energy_cny_per_kwh"
            if has_complete_time_varying_price and self._node_type == "d"
            else "public_total_cny_per_kwh"
            if has_complete_time_varying_price
            else None
        )

    def row_for_slot(self, slot_index: int) -> dict[str, Any]:
        cached = self._slot_rows.get(int(slot_index))
        if cached is not None:
            return cached
        row = carbon_profile_row_for_slot(self.rows, int(slot_index))
        self._slot_rows[int(slot_index)] = row
        return row

    @property
    def price_field(self) -> str | None:
        if self._partial_time_varying_price:
            raise ValueError(
                "time-varying charging profile has partial price fields"
            )
        return self._price_field

    @property
    def fixed_unit_price(self) -> float:
        return (
            _price(self._prices, "depot_electricity_price")
            if self._node_type == "d"
            else _price(self._prices, "station_electricity_price")
        )


class ChargeTimingContext:
    """Precomputed static data and deterministic scores for one profile."""

    def __init__(
        self,
        instance: Instance,
        carbon_profile: list[dict[str, Any]],
        prices: PriceParameters | dict[str, Any] | Any,
    ) -> None:
        self.instance = instance
        self.carbon_profile = carbon_profile
        self.prices = prices
        self._profiles: dict[str, _ProfileView] = {}
        self._geometries: dict[
            tuple[str, float, float, float | None, float | None, str | None],
            _ActionGeometry,
        ] = {}
        self._slots: dict[
            tuple[
                tuple[str, float, float, float | None, float | None, str | None],
                float,
                int,
            ],
            tuple[tuple[int, float], ...],
        ] = {}
        self._selected_starts: dict[
            tuple[ChargingAction, float, float, str, str],
            float,
        ] = {}
        self._objective_values: dict[tuple[ChargingAction, str], float] = {}
        self._cost_values: dict[ChargingAction, float] = {}
        self._emissions_values: dict[ChargingAction, float] = {}
        self._weighted_values: dict[tuple[ChargingAction, str], float] = {}

    def assert_matches(
        self,
        instance: Instance,
        carbon_profile: list[dict[str, Any]],
        prices: PriceParameters | dict[str, Any] | Any,
    ) -> None:
        if (
            instance is not self.instance
            or carbon_profile is not self.carbon_profile
            or prices is not self.prices
        ):
            raise ValueError("charge timing context was reused with other inputs")

    def profile_for(self, station_id: str) -> _ProfileView:
        profile = self._profiles.get(station_id)
        if profile is None:
            profile = _ProfileView(
                self.instance,
                station_id,
                self.carbon_profile,
                self.prices,
            )
            self._profiles[station_id] = profile
        return profile

    @staticmethod
    def _geometry_key(
        action: ChargingAction,
    ) -> tuple[str, float, float, float | None, float | None, str | None]:
        return (
            action.station_id,
            float(action.energy_kwh),
            float(action.occupancy_minutes),
            None
            if action.start_energy_kwh is None
            else float(action.start_energy_kwh),
            None
            if action.end_energy_kwh is None
            else float(action.end_energy_kwh),
            action.charging_curve_id,
        )

    def geometry_for(self, action: ChargingAction) -> _ActionGeometry:
        key = self._geometry_key(action)
        cached = self._geometries.get(key)
        if cached is not None:
            return cached
        duration = float(action.occupancy_minutes) * 60.0
        curve_state = charging_curve_for_action(
            action,
            self.instance,
            self.prices,
        )
        if curve_state is None:
            phases: tuple[ChargePhase, ...] = ()
            curve = None
            phase_boundaries = (0.0, duration)
        else:
            curve, start_energy, end_energy = curve_state
            phases = curve.phases(start_energy, end_energy)
            phase_boundaries = tuple(
                sorted(
                    {
                        0.0,
                        duration,
                        *(
                            float(value)
                            for phase in phases
                            for value in (
                                phase.relative_start_seconds,
                                phase.relative_end_seconds,
                            )
                        ),
                    }
                )
            )
        geometry = _ActionGeometry(
            duration_seconds=duration,
            energy_kwh=float(action.energy_kwh),
            curve=curve,
            phases=phases,
            phase_boundaries=phase_boundaries,
        )
        self._geometries[key] = geometry
        return geometry

    def timing_candidates(
        self,
        action: ChargingAction,
        earliest_start_second: float,
        latest_start_second: float,
        *,
        rounded: bool = True,
    ) -> tuple[float, ...]:
        earliest = float(earliest_start_second)
        latest = float(latest_start_second)
        if latest < earliest - 1.0e-9:
            raise ValueError("latest charging start precedes earliest start")
        geometry = self.geometry_for(action)
        candidates = {earliest, latest}
        first_grid = math.floor(earliest / CARBON_SLOT_SECONDS) - 1
        final_grid = math.ceil(
            (latest + geometry.duration_seconds) / CARBON_SLOT_SECONDS
        ) + 1
        for index in range(first_grid, final_grid + 1):
            boundary = float(index) * CARBON_SLOT_SECONDS
            for phase_boundary in geometry.phase_boundaries:
                candidate = boundary - phase_boundary
                if earliest - 1.0e-9 <= candidate <= latest + 1.0e-9:
                    candidates.add(min(latest, max(earliest, candidate)))
        if rounded:
            return tuple(sorted(round(value, 9) for value in candidates))
        return tuple(sorted(float(value) for value in candidates))

    def _slot_energies(
        self,
        action: ChargingAction,
        start_second: float,
        slot_count: int,
    ) -> tuple[tuple[int, float], ...]:
        geometry_key = self._geometry_key(action)
        cache_key = (geometry_key, float(start_second), int(slot_count))
        cached = self._slots.get(cache_key)
        if cached is not None:
            return cached
        geometry = self.geometry_for(action)
        start = float(start_second)
        duration = geometry.duration_seconds
        if duration < 0.0:
            raise ValueError("occupancy_sec must be non-negative")
        if duration <= 1.0e-12:
            self._slots[cache_key] = ()
            return ()
        if not math.isfinite(start) or start < 0.0:
            raise ValueError(
                "charge_start_second is before the first carbon profile slot"
            )
        if int(slot_count) <= 0:
            raise ValueError("charging slot count must be positive")
        end = start + duration
        if geometry.curve is None:
            rows: list[tuple[int, float]] = []
            cursor = start
            while cursor < end - 1.0e-12:
                absolute_slot = math.floor(cursor / CARBON_SLOT_SECONDS)
                next_boundary = (
                    absolute_slot + 1
                ) * CARBON_SLOT_SECONDS
                overlap_end = min(end, next_boundary)
                overlap = overlap_end - cursor
                if overlap > 0.0:
                    rows.append(
                        (
                            int(absolute_slot) % int(slot_count),
                            geometry.energy_kwh * overlap / duration,
                        )
                    )
                cursor = overlap_end
            result = tuple(rows)
            self._slots[cache_key] = result
            return result

        first_absolute_slot = math.floor(start / CARBON_SLOT_SECONDS)
        final_boundary_slot = math.ceil(end / CARBON_SLOT_SECONDS)
        if final_boundary_slot <= first_absolute_slot:
            final_boundary_slot = first_absolute_slot + 1
        boundaries = tuple(
            float(slot) * CARBON_SLOT_SECONDS
            for slot in range(first_absolute_slot, final_boundary_slot + 1)
        )
        energies: list[float] = []
        for slot_start, slot_end in zip(
            boundaries,
            boundaries[1:],
        ):
            energy = 0.0
            for phase in geometry.phases:
                absolute_start = start + phase.relative_start_seconds
                absolute_end = start + phase.relative_end_seconds
                overlap = max(
                    0.0,
                    min(float(slot_end), absolute_end)
                    - max(float(slot_start), absolute_start),
                )
                energy += phase.power_kw * overlap / 3600.0
            energies.append(energy)
        expected = geometry.energy_kwh
        total_energy = sum(energies)
        if abs(total_energy - expected) > 1.0e-9 * max(
            1.0,
            abs(total_energy),
            abs(expected),
        ):
            raise ChargingCurveError(
                "time slots do not fully cover the charging action"
            )
        rows = []
        for offset, energy in enumerate(energies):
            absolute_slot = first_absolute_slot + offset
            left = boundaries[offset]
            right = boundaries[offset + 1]
            overlap = max(0.0, min(end, right) - max(start, left))
            if overlap <= 1.0e-12:
                continue
            rows.append(
                (int(absolute_slot) % int(slot_count), float(energy))
            )
        if abs(sum(energy for _, energy in rows) - expected) > 1.0e-7:
            raise ValueError("charging action slot energy does not close")
        result = tuple(rows)
        self._slots[cache_key] = result
        return result

    def _settle(
        self,
        action: ChargingAction,
        *,
        need_cost: bool,
        need_emissions: bool,
        intensity_field: str = "actual_gco2_per_kwh",
        weighted_carbon: bool = False,
    ) -> tuple[float, float, float]:
        calculate_cost = need_cost and action not in self._cost_values
        calculate_emissions = (
            need_emissions and action not in self._emissions_values
        )
        weighted_key = (action, intensity_field)
        calculate_weighted = (
            weighted_carbon and weighted_key not in self._weighted_values
        )
        if not (
            calculate_cost or calculate_emissions or calculate_weighted
        ):
            return (
                self._cost_values.get(action, 0.0),
                self._emissions_values.get(action, 0.0),
                self._weighted_values.get(weighted_key, 0.0),
            )
        profile = self.profile_for(action.station_id)
        price_field = profile.price_field if calculate_cost else None
        cost = (
            0.0
            if price_field is not None
            else float(action.energy_kwh) * profile.fixed_unit_price
            if calculate_cost
            else self._cost_values.get(action, 0.0)
        )
        emissions = self._emissions_values.get(action, 0.0)
        carbon_weighted = self._weighted_values.get(weighted_key, 0.0)
        if calculate_emissions or calculate_weighted or price_field is not None:
            for slot_index, energy in self._slot_energies(
                action,
                float(action.charge_start_second),
                len(profile.rows),
            ):
                row = profile.row_for_slot(slot_index)
                if price_field is not None:
                    cost += float(energy) * float(row[price_field])
                if calculate_emissions:
                    emissions += (
                        float(energy)
                        * float(row["actual_gco2_per_kwh"])
                        / GCO2_PER_KGCO2
                    )
                if calculate_weighted:
                    if intensity_field not in row:
                        raise ValueError(
                            "carbon profile is missing timing field "
                            f"{intensity_field!r}"
                        )
                    carbon_weighted += float(energy) * float(
                        row[intensity_field]
                    )
        if calculate_cost:
            self._cost_values[action] = float(cost)
        if calculate_emissions:
            self._emissions_values[action] = float(emissions)
        if calculate_weighted:
            self._weighted_values[weighted_key] = float(carbon_weighted)
        return float(cost), float(emissions), float(carbon_weighted)

    def objective_value(
        self,
        action: ChargingAction,
        policy: str,
    ) -> float:
        key = (action, policy)
        cached = self._objective_values.get(key)
        if cached is not None:
            return cached
        if policy == "asap":
            value = 0.0
        elif policy == "carbon_min":
            _, value, _ = self._settle(
                action,
                need_cost=False,
                need_emissions=True,
            )
        else:
            carbon_price = _price(self.prices, "carbon_price")
            if policy == "cost_min" or carbon_price == 0.0:
                value, _, _ = self._settle(
                    action,
                    need_cost=True,
                    need_emissions=False,
                )
            else:
                cost, emissions, _ = self._settle(
                    action,
                    need_cost=True,
                    need_emissions=True,
                )
                value = cost + carbon_price * emissions
        value = float(value)
        self._objective_values[key] = value
        return value

    def select_start(
        self,
        action: ChargingAction,
        earliest: float,
        latest: float,
        policy: str,
        intensity_field: str,
    ) -> float:
        # v2026-08-21: the answer never depends on where the action currently
        # sits on the clock -- every candidate is scored on a shifted copy, and
        # both the candidate set and the geometry are clock-independent.  The
        # incoming ``charge_start_second`` is therefore normalised out of the
        # key, otherwise re-timing the same action during repair misses the
        # cache and re-scores its whole candidate set.
        key = (
            replace(action, charge_start_second=0.0),
            float(earliest),
            float(latest),
            policy,
            intensity_field,
        )
        cached = self._selected_starts.get(key)
        if cached is not None:
            return cached
        if policy == "carbon_min":
            candidates = self.timing_candidates(
                action,
                earliest,
                latest,
                rounded=False,
            )
            scored = []
            for start in candidates:
                shifted = replace(action, charge_start_second=float(start))
                _, _, score = self._settle(
                    shifted,
                    need_cost=False,
                    need_emissions=False,
                    intensity_field=intensity_field,
                    weighted_carbon=True,
                )
                scored.append((float(score), float(start)))
        else:
            candidates = self.timing_candidates(action, earliest, latest)
            carbon_price = _price(self.prices, "carbon_price")
            scored = []
            for start in candidates:
                shifted = replace(action, charge_start_second=float(start))
                if policy == "cost_min":
                    score, _, _ = self._settle(
                        shifted,
                        need_cost=True,
                        need_emissions=False,
                    )
                else:
                    cost, emissions, _ = self._settle(
                        shifted,
                        need_cost=True,
                        need_emissions=True,
                    )
                    score = cost + carbon_price * emissions
                scored.append((float(score), float(start)))
        selected = min(scored, key=lambda item: (item[0], item[1]))[1]
        self._selected_starts[key] = selected
        return selected


class ChargeTimingContexts:
    """Own one static timing context per exact profile object in a solve."""

    def __init__(
        self,
        instance: Instance,
        prices: PriceParameters | dict[str, Any] | Any,
    ) -> None:
        self.instance = instance
        self.prices = prices
        self._contexts: list[
            tuple[list[dict[str, Any]], ChargeTimingContext]
        ] = []

    def for_profile(
        self,
        instance: Instance,
        carbon_profile: list[dict[str, Any]],
        prices: PriceParameters | dict[str, Any] | Any,
    ) -> ChargeTimingContext:
        if instance is not self.instance or prices is not self.prices:
            raise ValueError("charge timing contexts were reused with other inputs")
        for cached_profile, cached_context in self._contexts:
            if cached_profile is carbon_profile:
                return cached_context
        context = ChargeTimingContext(instance, carbon_profile, prices)
        self._contexts.append((carbon_profile, context))
        return context


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
    timing_contexts: ChargeTimingContexts | None = None,
) -> float:
    """Return the registered timing objective for one already placed action."""

    policy = validate_charge_timing_policy(charge_timing_policy)
    if policy == "asap":
        return 0.0
    if timing_contexts is not None:
        context = timing_contexts.for_profile(
            instance,
            carbon_profile,
            prices,
        )
        return context.objective_value(action, policy)
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
    timing_contexts: ChargeTimingContexts | None = None,
) -> float:
    """Choose a feasible start under one explicit registered policy."""

    policy = validate_charge_timing_policy(charge_timing_policy)
    earliest = float(earliest_start_second)
    latest = float(latest_start_second)
    if latest < earliest - 1.0e-9:
        raise ValueError("latest charging start precedes earliest start")
    if policy == "asap" or latest <= earliest + 1.0e-9:
        return earliest
    if policy == "carbon_min" and not carbon_profile:
        return earliest
    if (
        policy != "carbon_min"
        and intensity_field != "actual_gco2_per_kwh"
    ):
        raise ValueError(
            "charge timing only accepts the actual registered carbon field"
        )
    if timing_contexts is not None:
        context = timing_contexts.for_profile(
            instance,
            carbon_profile,
            prices,
        )
        if policy == "cost_plus_carbon" and _price(prices, "carbon_price") == 0.0:
            policy = "cost_min"
        return context.select_start(
            action,
            earliest,
            latest,
            policy,
            intensity_field,
        )
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
