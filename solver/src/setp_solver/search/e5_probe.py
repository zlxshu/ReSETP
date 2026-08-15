"""E5 charging time-of-use probe.

v2026-06-11: Produces the charging-slot tables required by paper_main.tex
lines 657-677. It runs the same ALNS adapter with normal carbon cost and with
carbon price weight zero, then replays both solutions under the real carbon
profile for reporting. Use ``run_e5_probe`` after G4 passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..cost import (
    CARBON_N_SLOTS,
    CARBON_SLOT_SECONDS,
    carbon_slot_index,
    charging_action_slot_breakdown,
    evaluate,
    route_next_day_departure_second,
    route_node_schedule,
    route_return_arrival_without_charging,
)
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import Solution
from .alns_wouda import AlnsRunResult, SearchPolicy, run_alns_wouda
from .bundle import load_search_bundle


@dataclass(frozen=True)
class SlotChargeRow:
    slot_index: int
    gamma: float
    energy_kwh: float


@dataclass(frozen=True)
class E5ScenarioResult:
    label: str
    run: AlnsRunResult
    rows: list[SlotChargeRow]
    total_charge_kwh: float
    charge_carbon_kg: float
    mean_intensity_gco2_per_kwh: float
    timing_diagnostics: list["ChargingTimingDiagnostic"]
    ev_route_count: int
    charging_event_count: int


@dataclass(frozen=True)
class E5ProbeResult:
    carbon_on: E5ScenarioResult
    carbon_off: E5ScenarioResult
    delta_intensity: float
    delta_carbon: float
    routes_differ: bool


@dataclass(frozen=True)
class ChargingTimingDiagnostic:
    vehicle_id: str
    station_id: str
    chosen_start_second: float
    chosen_slot: int
    chosen_gamma: float
    earliest_second: float
    latest_second: float
    greenest_start_second: float
    greenest_slot: int
    greenest_gamma: float
    gamma_gap: float


def run_e5_probe(
    bundle_dir: str | Path,
    *,
    iterations: int | None = None,
    seed: int = 1,
    eval_budget: int = 3000,
    max_runtime_seconds: float = 60.0,
    enforce_k0: bool | None = None,
    policy: SearchPolicy | None = None,
    allow_zero_charge: bool = False,
    prices: PriceParameters | dict[str, Any] | Any = DEFAULT_PRICES,
) -> E5ProbeResult:
    """Run carbon-on vs carbon-price-zero ALNS probes and aggregate slots.

    v2026-06-12: K0/K1 real-budget E5 gate. By default this uses an
    evaluation budget of 3000 or 60 seconds, whichever comes first. Passing
    ``iterations`` explicitly preserves the previous smoke-test mode and does
    not enforce K0 unless ``enforce_k0=True`` is supplied.
    """

    bundle = load_search_bundle(bundle_dir)
    real_budget_mode = iterations is None
    check_k0 = real_budget_mode if enforce_k0 is None else enforce_k0
    probe_policy = policy or SearchPolicy(require_charging_signal=True)
    carbon_on = run_alns_wouda(
        bundle_dir,
        iterations=iterations,
        seed=seed,
        carbon_weight=1.0,
        policy=probe_policy,
        eval_budget=eval_budget if real_budget_mode else None,
        max_runtime_seconds=max_runtime_seconds,
        prices=prices,
    )
    carbon_off = run_alns_wouda(
        bundle_dir,
        iterations=iterations,
        seed=seed,
        carbon_weight=0.0,
        policy=probe_policy,
        eval_budget=eval_budget if real_budget_mode else None,
        max_runtime_seconds=max_runtime_seconds,
        prices=prices,
    )
    if check_k0:
        _assert_k0_improved(carbon_on, carbon_off)
    on_result = _scenario(
        "A_carbon_on",
        carbon_on,
        carbon_on.best_solution,
        bundle.instance,
        bundle.carbon_profile,
        prices,
    )
    off_result = _scenario(
        "B_carbon_weight_zero",
        carbon_off,
        carbon_off.best_solution,
        bundle.instance,
        bundle.carbon_profile,
        prices,
    )
    # v2026-06-12: N2 natural-adoption stake probes must report zero-charge
    # tables instead of stopping early; default behavior stays guarded.
    if not allow_zero_charge and (on_result.total_charge_kwh <= 1e-9 or off_result.total_charge_kwh <= 1e-9):
        raise RuntimeError(
            "HALT_H3: E5 probe has no EV charging signal in one or both scenarios "
            f"(A={on_result.total_charge_kwh:.6f} kWh, B={off_result.total_charge_kwh:.6f} kWh)"
        )
    return E5ProbeResult(
        carbon_on=on_result,
        carbon_off=off_result,
        delta_intensity=off_result.mean_intensity_gco2_per_kwh - on_result.mean_intensity_gco2_per_kwh,
        delta_carbon=off_result.charge_carbon_kg - on_result.charge_carbon_kg,
        routes_differ=_route_signature(carbon_on.best_solution) != _route_signature(carbon_off.best_solution),
    )


def slot_charge_table(
    solution: Solution,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, Any] | Any = DEFAULT_PRICES,
) -> list[SlotChargeRow]:
    """Aggregate solution charging energy into the carbon-profile slots."""

    # v2026-06-12: Q1/Q3 24h bundles expose 48 rows; legacy fixtures still expose 18.
    n_slots = len(carbon_profile) or CARBON_N_SLOTS
    energy = [0.0] * n_slots
    gamma = [float(row["actual_gco2_per_kwh"]) for row in carbon_profile[:n_slots]]
    for action in solution.charging_actions:
        for slot in charging_action_slot_breakdown(
            action,
            instance,
            prices,
            n_slots=n_slots,
            cyclic=True,
        ):
            energy[slot.slot_index] += slot.y_skt_kwh
    return [SlotChargeRow(idx, gamma[idx], energy[idx]) for idx in range(n_slots)]


def _scenario(
    label: str,
    run: AlnsRunResult,
    solution: Solution,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, Any] | Any = DEFAULT_PRICES,
) -> E5ScenarioResult:
    rows = slot_charge_table(solution, instance, carbon_profile, prices)
    total_energy = sum(row.energy_kwh for row in rows)
    charge_carbon = evaluate(
        solution,
        instance,
        carbon_profile,
        prices,
    )["E_ev_indirect"]
    mean_intensity = 0.0 if total_energy <= 1e-12 else charge_carbon * 1000.0 / total_energy
    ev_route_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
    return E5ScenarioResult(
        label,
        run,
        rows,
        total_energy,
        charge_carbon,
        mean_intensity,
        charging_timing_diagnostics(
            solution,
            instance,
            carbon_profile,
            prices,
        ),
        ev_route_count,
        len(solution.charging_actions),
    )


def charging_timing_diagnostics(
    solution: Solution,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> list[ChargingTimingDiagnostic]:
    """Compare each chosen charge start with its greenest feasible slot.

    v2026-06-12: K1 diagnostic for paper_main.tex lines 428-457 and 673.
    For each ChargingAction, recompute the arrival/ready lower bound and the
    successor time-window upper bound used by the search repair. The greenest
    feasible candidate is the lowest-gamma half-hour slot start in that
    window; if no slot start lies inside, the action start itself is used.
    """

    node_lookup = {node.node_id: node for node in instance.nodes}
    n_slots = len(carbon_profile) or CARBON_N_SLOTS
    gamma = [float(row["actual_gco2_per_kwh"]) for row in carbon_profile[:n_slots]]
    diagnostics: list[ChargingTimingDiagnostic] = []
    for route in solution.routes:
        route_actions = [action for action in solution.charging_actions if action.vehicle_id == route.vehicle_id]
        if not route_actions:
            continue
        schedule = {row.node_id: row for row in route_node_schedule(route, instance, prices, charging_actions=solution.charging_actions)}
        for action in route_actions:
            if action.station_id not in route.node_sequence or action.station_id not in node_lookup:
                continue
            station = node_lookup[action.station_id]
            station_type = station.node_type.lower()
            if station_type == "d":
                # v2026-06-12: S0 depot timing freedom is the overnight
                # return-to-next-departure window. The route has the same depot
                # id at both endpoints, so do not use the node-id keyed
                # schedule map for depot actions.
                if action.station_id != route.node_sequence[0] or len(route.node_sequence) < 2:
                    continue
                station_idx = 0
                occupancy_sec = float(action.occupancy_minutes) * 60.0
                earliest = route_return_arrival_without_charging(route, instance, prices)
                latest = route_next_day_departure_second(
                    route,
                    instance,
                    prices,
                    period_seconds=float(n_slots) * CARBON_SLOT_SECONDS,
                ) - occupancy_sec
            else:
                station_idx = route.node_sequence.index(action.station_id)
                if station_idx >= len(route.node_sequence) - 1:
                    continue
                successor = node_lookup[route.node_sequence[station_idx + 1]]
                occupancy_sec = float(action.occupancy_minutes) * 60.0
                earliest = max(float(schedule[action.station_id].t_arrive), float(station.ready_time))
                _, travel_to_successor, _ = instance.arc_metrics(
                    action.station_id,
                    successor.node_id,
                    "ev",
                    fallback_speed_mps=_price(prices, "v_speed_ms"),
                )
                latest = min(
                    float(station.due_time),
                    float(successor.due_time)
                    - occupancy_sec
                    - travel_to_successor,
                )
            if station_idx >= len(route.node_sequence) - 1:
                continue
            green_start, green_slot, green_gamma = _greenest_feasible_slot(earliest, latest, action.charge_start_second, gamma, carbon_profile)
            chosen_slot = carbon_slot_index(action.charge_start_second, n_slots=n_slots, cyclic=True)
            chosen_gamma = gamma[chosen_slot]
            diagnostics.append(
                ChargingTimingDiagnostic(
                    action.vehicle_id,
                    action.station_id,
                    float(action.charge_start_second),
                    chosen_slot,
                    chosen_gamma,
                    earliest,
                    latest,
                    green_start,
                    green_slot,
                    green_gamma,
                    chosen_gamma - green_gamma,
                )
            )
    return diagnostics


def _greenest_feasible_slot(
    earliest: float,
    latest: float,
    fallback_start: float,
    gamma: list[float],
    carbon_profile: list[dict[str, Any]],
) -> tuple[float, int, float]:
    candidates: list[tuple[float, float, int]] = []
    n_slots = len(carbon_profile) or CARBON_N_SLOTS
    period = float(n_slots) * CARBON_SLOT_SECONDS
    first_cycle = int((float(earliest) // period) - 1)
    last_cycle = int((float(latest) // period) + 2)
    for row in carbon_profile[:n_slots]:
        base_start = float(row["horizon_second_start"])
        for cycle in range(first_cycle, last_cycle + 1):
            start = base_start + cycle * period
            if earliest - 1e-9 <= start <= latest + 1e-9:
                slot = carbon_slot_index(start, n_slots=n_slots, cyclic=True)
                candidates.append((gamma[slot], start, slot))
    if not candidates:
        slot = carbon_slot_index(fallback_start, n_slots=n_slots, cyclic=True)
        return float(fallback_start), slot, gamma[slot]
    chosen_gamma, start, slot = min(candidates, key=lambda item: (item[0], item[1]))
    return start, slot, chosen_gamma


def _assert_k0_improved(carbon_on: AlnsRunResult, carbon_off: AlnsRunResult) -> None:
    failures = []
    for label, run in (("A_carbon_on", carbon_on), ("B_carbon_weight_zero", carbon_off)):
        if not run.best_obj < run.initial_obj - 1e-9:
            failures.append(
                f"{label}: best={run.best_obj:.6f}, S0={run.initial_obj:.6f}, "
                f"destroy_counts={run.destroy_operator_counts}"
            )
    if failures:
        raise RuntimeError("HALT_K0: ALNS did not improve both E5 scenarios; " + " | ".join(failures))


def _route_signature(solution: Solution) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    return tuple(sorted((route.vehicle_id, route.vehicle_type.lower(), tuple(route.node_sequence)) for route in solution.routes))


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
