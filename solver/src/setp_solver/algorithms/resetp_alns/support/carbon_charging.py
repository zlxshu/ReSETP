"""Carbon-aware charging subproblem helpers.

This module is deliberately isolated from the frozen E2 winner entrypoint.
It provides the small, auditable building blocks required by the item-4
mechanism gate before any carbon-aware route-search operator is activated.

The key distinction from the historical charging heuristic is that a charge
is scored over its complete occupancy interval.  A long charge that starts in
one green slot but spills into dirty slots is therefore not mistaken for a
green action.  Complete solution scoring remains the responsibility of the
shared evaluation shell; these helpers only solve a deterministic charging
subproblem and never consume or bypass ``EvalBudget``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from setp_solver.charge_timing import (
    ChargeTimingContexts,
    DEFAULT_CHARGE_TIMING_POLICY,
    charge_timing_objective_value,
    select_charge_timing_start,
    validate_charge_timing_policy,
)
from setp_solver.cost import (
    CARBON_SLOT_SECONDS,
    carbon_profile_row_for_slot,
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    charging_slot_breakdown,
    time_profile_rows_for_node,
)
from setp_solver.instance_loader import Instance
from setp_solver.prices import PriceParameters
from setp_solver.solution import ChargingAction


@dataclass(frozen=True)
class ChargeTimingChoice:
    start_second: float
    carbon_kg: float
    candidates_evaluated: int


@dataclass(frozen=True)
class ChargeOption:
    station_id: str
    node_type: str
    earliest_start_second: float
    latest_start_second: float
    energy_kwh: float
    power_kw: float
    detour_m: float = 0.0
    detour_seconds: float = 0.0
    occupancy_seconds_override: float | None = None
    start_energy_kwh: float | None = None
    end_energy_kwh: float | None = None
    charging_curve_id: str | None = None

    @property
    def occupancy_seconds(self) -> float:
        if self.occupancy_seconds_override is not None:
            if self.occupancy_seconds_override < 0.0:
                raise ValueError("charging duration must be non-negative")
            return float(self.occupancy_seconds_override)
        if self.power_kw <= 0.0:
            raise ValueError("charge power must be positive")
        if self.energy_kwh < 0.0:
            raise ValueError("charge energy must be non-negative")
        return float(self.energy_kwh) / float(self.power_kw) * 3600.0

    def action_at(self, start_second: float) -> ChargingAction:
        return ChargingAction(
            vehicle_id="CHARGE_OPTION",
            station_id=self.station_id,
            energy_kwh=float(self.energy_kwh),
            occupancy_minutes=self.occupancy_seconds / 60.0,
            charge_start_second=float(start_second),
            start_energy_kwh=self.start_energy_kwh,
            end_energy_kwh=self.end_energy_kwh,
            charging_curve_id=self.charging_curve_id,
        )

    @property
    def has_curve_metadata(self) -> bool:
        values = (
            self.occupancy_seconds_override,
            self.start_energy_kwh,
            self.end_energy_kwh,
            self.charging_curve_id,
        )
        return all(value is not None for value in values)


@dataclass(frozen=True)
class ScoredChargeOption:
    option: ChargeOption
    timing: ChargeTimingChoice
    electricity_cost: float
    detour_cost: float
    carbon_cost: float
    total_incremental_cost: float


def integrated_charge_carbon_kg(
    start_second: float,
    occupancy_seconds: float,
    energy_kwh: float,
    instance: Instance,
    carbon_profile: list[dict[str, object]],
    *,
    station_id: str | None = None,
) -> float:
    """Return emissions for the whole constant-power charging interval."""

    if not carbon_profile:
        raise ValueError("carbon_profile must be non-empty")
    has_city_rows = any(
        row.get("city") not in {None, ""}
        for row in carbon_profile
    )
    if has_city_rows and station_id is None:
        raise ValueError(
            "city-specific charging carbon requires a station id"
        )
    node_profile = (
        carbon_profile
        if station_id is None
        else time_profile_rows_for_node(
            instance,
            station_id,
            carbon_profile,
        )
    )
    total = 0.0
    for slot in charging_slot_breakdown(
        float(start_second),
        float(occupancy_seconds),
        float(energy_kwh),
        instance,
        n_slots=len(node_profile),
        cyclic=True,
    ):
        row = carbon_profile_row_for_slot(
            node_profile,
            slot.slot_index,
        )
        total += float(slot.y_skt_kwh) * float(row["actual_gco2_per_kwh"]) / 1000.0
    return float(total)


def score_charge_option(
    option: ChargeOption,
    instance: Instance,
    carbon_profile: list[dict[str, object]],
    prices: PriceParameters,
    *,
    carbon_weight: float = 1.0,
    charge_timing_policy: str | None = None,
    timing_contexts: ChargeTimingContexts | None = None,
) -> ScoredChargeOption:
    """Score station and timing with the same monetary units as the model."""

    effective_timing_policy = (
        "asap"
        if charge_timing_policy is None and float(carbon_weight) <= 1e-12
        else DEFAULT_CHARGE_TIMING_POLICY
        if charge_timing_policy is None
        else charge_timing_policy
    )
    validate_charge_timing_policy(effective_timing_policy)
    if option.has_curve_metadata:
        template = option.action_at(option.earliest_start_second)
        start = select_charge_timing_start(
            template,
            earliest_start_second=option.earliest_start_second,
            latest_start_second=option.latest_start_second,
            instance=instance,
            carbon_profile=carbon_profile,
            prices=prices,
            charge_timing_policy=effective_timing_policy,
            timing_contexts=timing_contexts,
        )
        placed_action = option.action_at(start)
        timing = ChargeTimingChoice(
            start_second=start,
            carbon_kg=(
                charging_action_emissions_kg(
                    placed_action,
                    instance,
                    carbon_profile,
                    prices,
                )
                if timing_contexts is None
                else charge_timing_objective_value(
                    placed_action,
                    instance,
                    carbon_profile,
                    prices,
                    charge_timing_policy="carbon_min",
                    timing_contexts=timing_contexts,
                )
            ),
            candidates_evaluated=-1,
        )
    else:
        start = select_charge_timing_start(
            option.action_at(option.earliest_start_second),
            earliest_start_second=option.earliest_start_second,
            latest_start_second=option.latest_start_second,
            instance=instance,
            carbon_profile=carbon_profile,
            prices=prices,
            charge_timing_policy=effective_timing_policy,
            timing_contexts=timing_contexts,
        )
        placed_action = option.action_at(start)
        timing = ChargeTimingChoice(
            start_second=start,
            carbon_kg=integrated_charge_carbon_kg(
                start,
                option.occupancy_seconds,
                option.energy_kwh,
                instance,
                carbon_profile,
                station_id=option.station_id,
            ),
            candidates_evaluated=-1,
        )
    electricity_cost = (
        charging_action_electricity_cost(
            placed_action,
            instance,
            carbon_profile,
            prices,
        )
        if timing_contexts is None
        else charge_timing_objective_value(
            placed_action,
            instance,
            carbon_profile,
            prices,
            charge_timing_policy="cost_min",
            timing_contexts=timing_contexts,
        )
    )
    detour_cost = float(option.detour_m) / 1000.0 * float(prices.c_km)
    carbon_cost = float(timing.carbon_kg) * float(prices.carbon_price) * float(carbon_weight)
    total = electricity_cost + detour_cost + carbon_cost
    return ScoredChargeOption(
        option=option,
        timing=timing,
        electricity_cost=electricity_cost,
        detour_cost=detour_cost,
        carbon_cost=carbon_cost,
        total_incremental_cost=float(total),
    )


def select_charge_option(
    options: Iterable[ChargeOption],
    instance: Instance,
    carbon_profile: list[dict[str, object]],
    prices: PriceParameters,
    *,
    carbon_weight: float = 1.0,
    charge_timing_policy: str | None = None,
    timing_contexts: ChargeTimingContexts | None = None,
) -> ScoredChargeOption:
    """Choose a station and time by complete incremental model cost."""

    scored = [
        score_charge_option(
            option,
            instance,
            carbon_profile,
            prices,
            carbon_weight=carbon_weight,
            charge_timing_policy=charge_timing_policy,
            timing_contexts=timing_contexts,
        )
        for option in options
    ]
    if not scored:
        raise ValueError("at least one charge option is required")
    return min(
        scored,
        key=lambda item: (
            item.total_incremental_cost,
            item.timing.carbon_kg,
            item.option.detour_m,
            item.option.station_id,
            item.timing.start_second,
        ),
    )
