#!/usr/bin/env python3
"""Minimum E7 probe with cooperation, forecast timing, and participation active.

This probe deliberately runs only stream 1 and the first two rolling stages.
It does not replace the sealed two-arm dynamic diagnostic.  Its purpose is to
prove that the three paper mechanisms are present in the released decisions
before any five-stream formal batch is allowed to start.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import asdict, replace
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e4_e5 import e4_multiday_forecast_probe_20260713 as e4
from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as base
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.bundle import SearchBundle
from setp_solver.search.dynamic_multitrip_schedule import (
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    reschedule_dynamic_charging,
)
from setp_solver.search.multitrip_schedule import (
    prepare_multitrip_solution,
    reschedule_between_trip_charging,
    validate_multitrip_certificate,
)
from setp_solver.solution import ChargingAction, Route, Solution


OUT = ROOT / "baselines/e7_dynamic/e7_full_mechanism_gate_v6_20260715"
CONTRACT_ID = "E7_FULL_MECHANISM_GATE_V6_PROVENANCE_CLOSED"
OPERATING_DAY = date(2025, 11, 13)
STREAM_SEED = 1
MAX_STAGES = 2
DEFAULT_EVALUATIONS = 8
ARMS = ("full", "no_cooperation", "no_participation", "simple_insertion")
FULL_DAY_EXECUTION_SCHEMA = "setp.e7.full_day_execution.v2"
CONDITIONS = ("geographic", "historical_mixed")
RESPONSIBILITY_ROOT = (
    ROOT / "baselines/e7_dynamic/e7_responsibility_scenario_design_20260714"
)
MULTINETWORK_EVENT_ROOT = (
    ROOT / "baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715"
)
NETWORKS = {
    "N114": "L-main-threeshift-50c-01",
    "N221": "L-main-threeshift-100c-01",
    "N322": "L-main-threeshift-150c-01",
}
TOL = 1e-6
SOURCE_FILES = (
    Path(__file__).resolve(),
    Path(base.__file__).resolve(),
    Path(base.gate.__file__).resolve(),
    Path(base.p2.__file__).resolve(),
    ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
    ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    ROOT / "solver/src/setp_solver/algorithms/resetp_alns/operators/feasible_repair.py",
    ROOT / "solver/src/setp_solver/search/dynamic_multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/profit.py",
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def route_hash(solution: Solution) -> str:
    return canonical_sha256([asdict(route) for route in solution.routes])


def energy_hash(solution: Solution) -> str:
    return canonical_sha256(
        sorted(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.energy_kwh), 12),
                round(float(action.occupancy_minutes), 12),
                int(action.charge_day_offset),
            )
            for action in solution.charging_actions
        )
    )


def _merge_execution_plan(
    committed_routes: Mapping[str, Route],
    committed_actions: Mapping[tuple[Any, ...], ChargingAction],
    future: Solution,
    detached_route_sources: Mapping[str, Route] | None = None,
) -> Solution:
    routes = dict(committed_routes)
    for route in future.routes:
        previous = routes.get(route.vehicle_id)
        if previous is not None and previous != route:
            raise RuntimeError(f"executed route {route.vehicle_id} was rewritten")
        routes[route.vehicle_id] = route
    actions = dict(committed_actions)
    for action in future.charging_actions:
        key = base.action_key(action)
        previous = actions.get(key)
        if previous is not None and previous != action:
            raise RuntimeError(f"executed charging action {key} was rewritten")
        actions[key] = action
    route_ids = set(routes)
    detached = [action.vehicle_id for action in actions.values() if action.vehicle_id not in route_ids]
    source_routes = dict(detached_route_sources or {})
    for route_id in detached:
        source = source_routes.get(route_id)
        if source is None:
            continue
        # Charging that has already happened remains a sunk action even if a
        # later cancellation removes the associated future trip.  A depot-only
        # placeholder keeps the action in the full-day cost/emissions ledger
        # without reintroducing canceled customer service.
        routes[route_id] = replace(
            source,
            node_sequence=[source.home_depot_id, source.home_depot_id],
        )
    route_ids = set(routes)
    detached = [action.vehicle_id for action in actions.values() if action.vehicle_id not in route_ids]
    if detached:
        raise RuntimeError(f"charging ledger contains detached routes: {sorted(detached)}")
    return Solution(
        routes=[routes[key] for key in sorted(routes)],
        charging_actions=[actions[key] for key in sorted(actions, key=str)],
    )


def _profit_closure(
    solution: Solution,
    instance: Any,
    sources: Mapping[str, Any],
    owners: Mapping[str, str],
) -> dict[str, Any]:
    rows = calculate_depot_profits(
        solution,
        instance,
        sources["bundle"].carbon_profile,
        sources["prices"],
        customer_home_depot=dict(owners),
        carbon_quota_kg=0.0,
    )
    parts = base.evaluate_parts(
        solution.routes,
        solution.charging_actions,
        instance,
        sources,
    )
    total_revenue = sum(float(row.revenue) for row in rows.values())
    total_profit = sum(float(row.profit) for row in rows.values())
    expected_profit = total_revenue - float(parts["total_cost"])
    if abs(total_profit - expected_profit) > 1e-6:
        raise RuntimeError(
            "depot profit ledger did not close with system revenue and cost"
        )
    return {
        "total_revenue": total_revenue,
        "total_cost": float(parts["total_cost"]),
        "total_profit": total_profit,
        "depot_profit": {key: float(row.profit) for key, row in rows.items()},
        "direct_emissions_kg": float(parts["E_cv_direct"]),
    }


def _full_day_execution_summary(
    solution: Solution,
    instance: Any,
    owners: Mapping[str, str],
) -> dict[str, Any]:
    """Close the full-day workload and cross-depot service ledger."""

    nodes = {node.node_id: node for node in instance.nodes}
    completed: list[str] = []
    cross_site: list[str] = []
    for route in solution.routes:
        for customer_id in base.p2.route_customers(route, instance):
            if customer_id not in owners:
                raise RuntimeError(
                    f"full-day customer has no responsibility owner: {customer_id}"
                )
            completed.append(customer_id)
            if owners[customer_id] != route.home_depot_id:
                cross_site.append(customer_id)
    if len(completed) != len(set(completed)):
        raise RuntimeError("full-day execution serves a customer more than once")
    if len(cross_site) != len(set(cross_site)):
        raise RuntimeError("full-day cross-depot ledger contains duplicates")
    missing = sorted(customer_id for customer_id in completed if customer_id not in nodes)
    if missing:
        raise RuntimeError(f"full-day execution contains unknown customers: {missing}")
    completed_ids = sorted(completed)
    cross_site_ids = sorted(cross_site)
    return {
        "schema": FULL_DAY_EXECUTION_SCHEMA,
        "completed_customer_ids": completed_ids,
        "completed_customer_count": len(completed_ids),
        "completed_demand": sum(float(nodes[item].demand) for item in completed_ids),
        "cross_site_customer_ids": cross_site_ids,
        "cross_site_customer_count": len(cross_site_ids),
        "solution_sha256": canonical_sha256(base.solution_to_dict(solution)),
    }


def _profiles() -> dict[int, list[dict[str, Any]]]:
    return e4.profiles_for_operating_day(e4.load_national_rows(), OPERATING_DAY)


def _sources_for_day(
    condition: str,
    network: str = "N221",
) -> tuple[dict[str, Any], dict[int, list[dict[str, Any]]]]:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown responsibility condition {condition}")
    if network not in NETWORKS:
        raise ValueError(f"unknown E7 network {network}")
    instance_id = NETWORKS[network]
    bundle_dir = (
        ROOT
        / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets"
        / instance_id
        / "bundle"
    )
    bundle = base.load_search_bundle(bundle_dir)
    case_condition = "mixed" if condition == "historical_mixed" else "geographic"
    case = f"{instance_id}__{case_condition}__seed1__independent"
    solution_path = base.E6_ROOT / "solutions" / f"{case}.json"
    certificate_path = base.E6_ROOT / "certificates" / f"{case}.json"
    sources = {
        "case": case,
        "bundle": bundle,
        "prices": base.legacy.prices_for("M1", 0.0),
        "solution": base.solution_from_dict(
            json.loads(solution_path.read_text(encoding="utf-8"))
        ),
        "certificate": base.p2.load_certificate(certificate_path),
        "solution_path": solution_path,
        "certificate_path": certificate_path,
        "instance_path": bundle_dir / "instance.json",
    }
    profiles = _profiles()
    bundle = sources["bundle"]
    sources["bundle"] = SearchBundle(
        bundle.bundle_dir,
        bundle.instance,
        profiles[0],
    )
    return sources, profiles


def _stream_for_condition(
    stream_seed: int,
    condition: str,
    network: str = "N221",
) -> tuple[list[Any], dict[str, str], Path, Path]:
    if network not in NETWORKS:
        raise ValueError(f"unknown E7 network {network}")
    event_path = MULTINETWORK_EVENT_ROOT / network / f"stream_seed{stream_seed}.events.json"
    events = [
        base.DynamicEvent(**row)
        for row in json.loads(event_path.read_text(encoding="utf-8"))
    ]
    owner_path = MULTINETWORK_EVENT_ROOT / network / (
        f"stream_seed{stream_seed}__{condition}.owners.csv"
    )
    if not owner_path.is_file():
        raise FileNotFoundError(
            f"frozen E7 responsibility map is missing: {owner_path}"
        )
    with owner_path.open(newline="", encoding="utf-8") as handle:
        owners = {
            str(row["customer_id"]): str(row["owner_depot_id"])
            for row in csv.DictReader(handle)
        }
    if len(owners) != len({*owners}) or set(owners.values()) - {"D0", "D1"}:
        raise RuntimeError(f"invalid responsibility map {owner_path}")
    return events, owners, event_path, owner_path


def _validated_multinetwork_trigger_batches(
    network: str,
    stream_seed: int,
    events: Sequence[Any],
) -> list[dict[str, Any]]:
    batches = [
        batch
        for batch in base._build_trigger_batches(list(events), base.ROLLING_PARAMETERS)
        if batch["events"]
    ]
    observed = {
        str(event.event_id): float(batch["trigger_time"])
        for batch in batches
        for event in batch["events"]
    }
    expected: dict[str, float] = {}
    with (MULTINETWORK_EVENT_ROOT / "raw_runs.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        for row in csv.DictReader(handle):
            if row["network"] == network and int(row["seed"]) == stream_seed:
                expected[str(row["event_id"])] = float(row["trigger_second"])
    if observed != expected:
        raise RuntimeError(
            f"{network} stream {stream_seed} trigger contract differs"
        )
    return batches


def _charging_emissions_kg(
    solution: Solution,
    instance: Any,
    profiles: Mapping[int, list[dict[str, Any]]],
    field: str,
) -> float:
    return sum(
        e4.action_emissions_kg(action, instance, dict(profiles), field)
        for action in solution.charging_actions
    )


def _timing_comparison(
    immediate: Solution,
    aware: Solution,
    instance: Any,
    profiles: Mapping[int, list[dict[str, Any]]],
) -> dict[str, float]:
    if route_hash(immediate) != route_hash(aware):
        raise RuntimeError("charging comparison changed routes")
    if energy_hash(immediate) != energy_hash(aware):
        raise RuntimeError("charging comparison changed charging energy")

    def action_identity(action: ChargingAction) -> tuple[str, str, float, float, int]:
        return (
            str(action.vehicle_id),
            str(action.station_id),
            round(float(action.energy_kwh), 9),
            round(float(action.occupancy_minutes), 9),
            int(action.charge_day_offset),
        )

    immediate_actions = {
        action_identity(action): action for action in immediate.charging_actions
    }
    aware_actions = {
        action_identity(action): action for action in aware.charging_actions
    }
    if len(immediate_actions) != len(immediate.charging_actions):
        raise RuntimeError("immediate charging comparison contains duplicate actions")
    if len(aware_actions) != len(aware.charging_actions):
        raise RuntimeError("forecast-timed charging comparison contains duplicate actions")
    if immediate_actions.keys() != aware_actions.keys():
        raise RuntimeError("charging comparison changed action identities")
    timing_shifted_keys = [
        key
        for key in immediate_actions
        if abs(
            float(immediate_actions[key].charge_start_second)
            - float(aware_actions[key].charge_start_second)
        )
        > TOL
    ]
    values = {
        "immediate_predicted_charging_emissions_kg": _charging_emissions_kg(
            immediate, instance, profiles, "forecast_gco2_per_kwh"
        ),
        "aware_predicted_charging_emissions_kg": _charging_emissions_kg(
            aware, instance, profiles, "forecast_gco2_per_kwh"
        ),
        "immediate_actual_charging_emissions_kg": _charging_emissions_kg(
            immediate, instance, profiles, "actual_gco2_per_kwh"
        ),
        "aware_actual_charging_emissions_kg": _charging_emissions_kg(
            aware, instance, profiles, "actual_gco2_per_kwh"
        ),
        "aware_vs_immediate_moved_action_count": len(timing_shifted_keys),
        "aware_vs_immediate_moved_energy_kwh": sum(
            float(aware_actions[key].energy_kwh) for key in timing_shifted_keys
        ),
    }
    values["predicted_charging_saving_kg"] = (
        values["immediate_predicted_charging_emissions_kg"]
        - values["aware_predicted_charging_emissions_kg"]
    )
    values["actual_charging_saving_kg"] = (
        values["immediate_actual_charging_emissions_kg"]
        - values["aware_actual_charging_emissions_kg"]
    )
    if values["predicted_charging_saving_kg"] < -TOL:
        raise RuntimeError("forecast-timed charging increased predicted emissions")
    return values


def _initial_plan(
    arm: str,
    sources: Mapping[str, Any],
    profiles: Mapping[int, list[dict[str, Any]]],
) -> tuple[Solution, Any, dict[str, Any]]:
    strategy = "aware"
    original_solution = sources["solution"]
    original_certificate = sources["certificate"]
    immediate = reschedule_between_trip_charging(
        original_solution,
        original_certificate,
        sources["bundle"].instance,
        profiles[0],
        strategy="naive",
        carbon_profiles_by_day_offset=profiles,
        intensity_field="forecast_gco2_per_kwh",
    )
    aware = reschedule_between_trip_charging(
        original_solution,
        original_certificate,
        sources["bundle"].instance,
        profiles[0],
        strategy="aware",
        carbon_profiles_by_day_offset=profiles,
        intensity_field="forecast_gco2_per_kwh",
    )
    timing_comparison = _timing_comparison(
        immediate,
        aware,
        sources["bundle"].instance,
        profiles,
    )
    timed = immediate if strategy == "naive" else aware
    synced_solution, synced_certificate = prepare_multitrip_solution(
        timed,
        sources["bundle"].instance,
        sources["prices"],
    )
    validate_multitrip_certificate(
        synced_certificate,
        list(synced_solution.routes),
        sources["prices"],
    )
    if route_hash(original_solution) != route_hash(synced_solution):
        raise RuntimeError("initial carbon timing changed routes")
    if energy_hash(original_solution) != energy_hash(synced_solution):
        raise RuntimeError("initial carbon timing changed charging energy")
    old_starts = {
        action.vehicle_id: float(action.charge_start_second)
        for action in original_solution.charging_actions
    }
    moved = sum(
        abs(float(action.charge_start_second) - old_starts[action.vehicle_id]) > TOL
        for action in synced_solution.charging_actions
    )
    return synced_solution, synced_certificate, {
        "strategy": strategy,
        "moved_action_count": moved,
        "route_sha256": route_hash(synced_solution),
        "energy_sha256": energy_hash(synced_solution),
        **timing_comparison,
    }


def _profit_values(
    solution: Solution,
    instance: Any,
    sources: Mapping[str, Any],
    owners: Mapping[str, str],
    *,
    prior_profit: Mapping[str, float] | None = None,
) -> dict[str, float]:
    rows = calculate_depot_profits(
        solution,
        instance,
        sources["bundle"].carbon_profile,
        sources["prices"],
        customer_home_depot=dict(owners),
        prior_profit=dict(prior_profit or {}),
        carbon_quota_kg=0.0,
    )
    return {depot: float(row.profit) for depot, row in rows.items()}


def _participation_margins(
    candidate: Mapping[str, float],
    baseline: Mapping[str, float],
) -> dict[str, float]:
    if not baseline or any(not math.isfinite(value) or value <= TOL for value in baseline.values()):
        raise RuntimeError(
            "same-state no-cooperation baseline has non-positive depot profit"
        )
    if set(candidate) != set(baseline):
        raise RuntimeError("candidate and baseline depot sets differ")
    if any(not math.isfinite(value) for value in candidate.values()):
        raise RuntimeError("candidate depot profit is not finite")
    return {depot: candidate[depot] - value for depot, value in baseline.items()}


def _meets_participation_floor(
    candidate: Mapping[str, float],
    baseline: Mapping[str, float],
) -> bool:
    return all(
        value >= -TOL
        for value in _participation_margins(candidate, baseline).values()
    )


def _timing_variant_for_strategy(strategy: str) -> str:
    if strategy == "naive":
        return "immediate"
    if strategy == "aware":
        return "aware"
    raise ValueError(f"unknown charging strategy {strategy}")


def _add_committed_profit(
    prior: Mapping[str, float],
    routes: Sequence[Route],
    actions: Sequence[ChargingAction],
    instance: Any,
    sources: Mapping[str, Any],
    owners: Mapping[str, str],
) -> dict[str, float]:
    return _profit_values(
        Solution(routes=list(routes), charging_actions=list(actions)),
        instance,
        sources,
        owners,
        prior_profit=prior,
    )


def _same_state_no_cooperation(
    construction: Any,
    sources: Mapping[str, Any],
    cut: Any,
    owners: dict[str, str],
    committed_customers: set[str],
    *,
    trigger: float,
    seed: int,
    evaluations: int,
    stage_new_customer_ids: Sequence[str],
) -> dict[str, Any]:
    existing_cross_ids = base._cross_site_ids_for_routes(
        construction.solution.routes,
        construction.effective_instance,
        owners,
    )
    failure_diagnostics: dict[str, Any] = {}
    owner_fixed = base.asset_aware_future_repack_candidate(
        construction,
        owners,
        sources["prices"],
        asset_states=cut.asset_states,
        stage_start_second=trigger,
        allow_cross_depot=False,
        failure_diagnostics=failure_diagnostics,
    )
    if owner_fixed is not None:
        controlled = replace(construction, solution=owner_fixed)
        baseline_start_source = "owner_fixed_asset_repack"
        allowed_inherited_cross_ids: set[str] = set()
    else:
        if failure_diagnostics.get("reason") not in {
            "greedy_customer_has_no_asset_placement",
            "no_open_customers",
        }:
            raise RuntimeError(
                "could not audit the same-state no-cooperation repack: "
                + json.dumps(failure_diagnostics, ensure_ascii=False, sort_keys=True)
            )
        # The dynamic stage builder has already preserved the inherited asset
        # state and inserted the current events.  Discarding this cross-free
        # structure and rebuilding every open customer from scratch can create
        # a false infeasibility before search begins.
        controlled = construction
        allowed_inherited_cross_ids = set(existing_cross_ids)
        baseline_start_source = (
            "existing_open_stage_with_frozen_cross"
            if allowed_inherited_cross_ids
            else "existing_cross_free_open_stage"
        )

    def no_cross_gate(solution: Solution, _certificate: Any, _cost: float) -> bool:
        observed = set(
            base._cross_site_ids_for_routes(
                solution.routes,
                construction.effective_instance,
                owners,
            )
        )
        return observed.issubset(allowed_inherited_cross_ids)

    result = base.search_stage(
        controlled,
        sources,
        cut,
        owners,
        committed_customers,
        trigger=trigger,
        seed=seed,
        evaluations=evaluations,
        allow_cross_depot=bool(allowed_inherited_cross_ids),
        stage_new_customer_ids=stage_new_customer_ids,
        candidate_best_gate=no_cross_gate,
    )
    released_cross_ids = set(
        base._cross_site_ids_for_routes(
            result["solution"].routes,
            construction.effective_instance,
            owners,
        )
    )
    if not released_cross_ids.issubset(allowed_inherited_cross_ids):
        raise RuntimeError("same-state baseline introduced a new cross-depot customer")
    result["same_state_baseline_start_source"] = baseline_start_source
    result["same_state_baseline_start_construction"] = controlled
    result["same_state_baseline_allowed_cross_ids"] = sorted(
        allowed_inherited_cross_ids
    )
    return result


def _dynamic_timing_pair(
    solution: Solution,
    certificate: Any,
    construction: Any,
    sources: Mapping[str, Any],
    profiles: Mapping[int, list[dict[str, Any]]],
    cut: Any,
    *,
    trigger: float,
) -> dict[str, Any]:
    immediate_solution, immediate_certificate, immediate_stats = (
        reschedule_dynamic_charging(
            solution,
            certificate,
            construction.effective_instance,
            profiles[0],
            sources["prices"],
            asset_states=cut.asset_states,
            stage_start_second=trigger,
            locked_charging_actions=cut.locked_charging_actions,
            strategy="naive",
            intensity_field="forecast_gco2_per_kwh",
        )
    )
    aware_solution, aware_certificate, aware_stats = reschedule_dynamic_charging(
        solution,
        certificate,
        construction.effective_instance,
        profiles[0],
        sources["prices"],
        asset_states=cut.asset_states,
        stage_start_second=trigger,
        locked_charging_actions=cut.locked_charging_actions,
        strategy="aware",
        intensity_field="forecast_gco2_per_kwh",
    )
    comparison = _timing_comparison(
        immediate_solution,
        aware_solution,
        construction.effective_instance,
        {0: profiles[0]},
    )
    return {
        "immediate_solution": immediate_solution,
        "immediate_certificate": immediate_certificate,
        "immediate_stats": immediate_stats,
        "aware_solution": aware_solution,
        "aware_certificate": aware_certificate,
        "aware_stats": aware_stats,
        "comparison": comparison,
    }


def _controlled_stage(
    arm: str,
    construction: Any,
    sources: Mapping[str, Any],
    profiles: Mapping[int, list[dict[str, Any]]],
    cut: Any,
    owners: dict[str, str],
    committed_customers: set[str],
    committed_profit: Mapping[str, float],
    *,
    trigger: float,
    seed: int,
    evaluations: int,
    stage_new_customer_ids: Sequence[str],
) -> dict[str, Any]:
    stage_new_customer_ids = tuple(stage_new_customer_ids)
    baseline = _same_state_no_cooperation(
        construction,
        sources,
        cut,
        owners,
        committed_customers,
        trigger=trigger,
        seed=seed * 10 + 1,
        evaluations=evaluations,
        stage_new_customer_ids=stage_new_customer_ids,
    )
    baseline_future_profit = _profit_values(
        baseline["solution"],
        construction.effective_instance,
        sources,
        owners,
        prior_profit=committed_profit,
    )
    _participation_margins(baseline_future_profit, baseline_future_profit)
    second_start = replace(construction, solution=baseline["search_structure"])
    second_start_sha256 = canonical_sha256(
        base.solution_to_dict(baseline["search_structure"])
    )

    def no_cross_gate(solution: Solution, _certificate: Any, _cost: float) -> bool:
        return not base._cross_site_ids_for_routes(
            solution.routes,
            construction.effective_instance,
            owners,
        )

    def participation_gate(
        solution: Solution,
        _certificate: Any,
        _cost: float,
    ) -> bool:
        candidate = _profit_values(
            solution,
            construction.effective_instance,
            sources,
            owners,
            prior_profit=committed_profit,
        )
        return _meets_participation_floor(candidate, baseline_future_profit)

    if arm == "simple_insertion":
        # A dynamic open-stage structure may require one exact insertion/repair
        # evaluation before it becomes an executable physical-vehicle plan.
        # Run exactly that one evaluation from the pre-search baseline start;
        # never release the shadow search's multi-evaluation endpoint.
        selected = base.search_stage(
            baseline["same_state_baseline_start_construction"],
            sources,
            cut,
            owners,
            committed_customers,
            trigger=trigger,
            seed=seed * 10 + 2,
            evaluations=1,
            allow_cross_depot=False,
            stage_new_customer_ids=stage_new_customer_ids,
            candidate_best_gate=no_cross_gate,
        )
    elif arm == "no_cooperation":
        selected = base.search_stage(
            second_start,
            sources,
            cut,
            owners,
            committed_customers,
            trigger=trigger,
            seed=seed * 10 + 2,
            evaluations=evaluations,
            allow_cross_depot=False,
            stage_new_customer_ids=stage_new_customer_ids,
            candidate_best_gate=no_cross_gate,
        )
    else:
        selected = base.search_stage(
            second_start,
            sources,
            cut,
            owners,
            committed_customers,
            trigger=trigger,
            seed=seed * 10 + 2,
            evaluations=evaluations,
            allow_cross_depot=True,
            stage_new_customer_ids=stage_new_customer_ids,
            candidate_best_gate=(
                None if arm == "no_participation" else participation_gate
            ),
        )
    if arm != "simple_insertion" and selected["future_cost"] > baseline["future_cost"] + TOL:
        raise RuntimeError("second search lost the same-state cost fallback")
    paired_existing_fields = (
        "existing_cross_operator_id",
        "existing_cross_scheduled_slots",
        "existing_cross_scheduled_call_count",
        "existing_cross_actual_call_count",
    )
    if arm != "simple_insertion" and any(
        selected[field] != baseline[field] for field in paired_existing_fields
    ):
        raise RuntimeError(
            "paired searches did not use the same existing-customer call schedule"
        )

    strategy = "aware"
    timing_variant = _timing_variant_for_strategy(strategy)
    baseline_timing = _dynamic_timing_pair(
        baseline["solution"],
        baseline["certificate"],
        construction,
        sources,
        profiles,
        cut,
        trigger=trigger,
    )
    selected_timing = _dynamic_timing_pair(
        selected["solution"],
        selected["certificate"],
        construction,
        sources,
        profiles,
        cut,
        trigger=trigger,
    )
    timed_solution = selected_timing[f"{timing_variant}_solution"]
    timed_certificate = selected_timing[f"{timing_variant}_certificate"]
    timing = selected_timing[f"{timing_variant}_stats"]
    baseline_timed_solution = baseline_timing[f"{timing_variant}_solution"]
    baseline_cost = float(
        base.evaluate_parts(
            baseline_timed_solution.routes,
            baseline_timed_solution.charging_actions,
            construction.effective_instance,
            sources,
        )["total_cost"]
    )
    selected_cost = float(
        base.evaluate_parts(
            timed_solution.routes,
            timed_solution.charging_actions,
            construction.effective_instance,
            sources,
        )["total_cost"]
    )
    baseline_timed_profit = _profit_values(
        baseline_timed_solution,
        construction.effective_instance,
        sources,
        owners,
        prior_profit=committed_profit,
    )
    selected_future_profit = _profit_values(
        timed_solution,
        construction.effective_instance,
        sources,
        owners,
        prior_profit=committed_profit,
    )
    margins = _participation_margins(
        selected_future_profit,
        baseline_timed_profit,
    )
    ratios = {
        depot: selected_future_profit[depot] / value
        for depot, value in baseline_timed_profit.items()
    }
    if arm == "full" and any(
        value < -TOL for value in margins.values()
    ):
        raise RuntimeError("released solution violated the same-state participation floor")
    return {
        **selected,
        "solution": timed_solution,
        "certificate": timed_certificate,
        "future_cost": selected_cost,
        "timing": timing,
        "timing_comparison": selected_timing["comparison"],
        "charging_strategy": strategy,
        "same_state_baseline_cost": baseline_cost,
        "same_state_baseline_profit": baseline_timed_profit,
        "selected_future_profit": selected_future_profit,
        "profit_margins": margins,
        "profit_ratios": ratios,
        "minimum_profit_margin": min(margins.values()),
        "minimum_profit_ratio": min(ratios.values()),
        "same_state_cost_saving_pct": 100.0
        * (baseline_cost - selected_cost)
        / max(baseline_cost, TOL),
        "shadow_evaluations": int(baseline["evaluations"]),
        "shadow_search_seed": int(baseline["search_seed"]),
        "same_state_baseline_start_source": baseline[
            "same_state_baseline_start_source"
        ],
        "same_state_baseline_allowed_cross_ids": baseline[
            "same_state_baseline_allowed_cross_ids"
        ],
        "main_search_seed": int(selected["search_seed"]),
        "second_start_sha256": second_start_sha256,
        "baseline_output_sha256": canonical_sha256(
            base.solution_to_dict(baseline["search_structure"])
        ),
        "stage_new_customer_ids": list(stage_new_customer_ids),
        "stage_new_customer_count": len(stage_new_customer_ids),
        "forced_cross_attempt_count": int(
            selected["forced_cross_attempt_count"]
        ),
        "shadow_existing_cross_actual_call_count": int(
            baseline["existing_cross_actual_call_count"]
        ),
    }


def run_probe_arm(
    arm: str,
    *,
    condition: str,
    stream_seed: int,
    evaluations: int,
    max_stages: int,
    network: str = "N221",
) -> dict[str, Any]:
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm}")
    sources, profiles = _sources_for_day(condition, network)
    events, owners, event_path, owner_path = _stream_for_condition(
        stream_seed,
        condition,
        network,
    )
    all_batches = _validated_multinetwork_trigger_batches(network, stream_seed, events)
    batches = all_batches[:max_stages]
    current_solution, current_certificate, initial_timing = _initial_plan(
        arm, sources, profiles
    )
    current_instance = sources["bundle"].instance
    route_history = {
        route.vehicle_id: route for route in current_solution.routes
    }
    inherited_states = None
    inherited_locked_actions: Sequence[ChargingAction] = ()
    previous_stage_start = None
    committed_customers: set[str] = set()
    committed_routes: dict[str, Route] = {}
    committed_actions: dict[tuple[Any, ...], ChargingAction] = {}
    rows: list[dict[str, Any]] = []
    final_running: dict[str, Any] | None = None
    final_execution_solution: Solution | None = None

    for stage_index, batch in enumerate(batches, start=1):
        started = time.perf_counter()
        trigger = float(batch["trigger_time"])
        if stage_index == 1:
            cut = cut_certificate_at_trigger(
                current_solution,
                current_certificate,
                current_instance,
                sources["prices"],
                trigger_second=trigger,
            )
        else:
            cut = cut_dynamic_certificate_at_trigger(
                current_solution,
                current_certificate,
                current_instance,
                sources["prices"],
                inherited_asset_states=inherited_states,
                previous_stage_start_second=float(previous_stage_start),
                trigger_second=trigger,
                inherited_locked_charging_actions=inherited_locked_actions,
            )
        locked_ids = [*cut.completed_route_ids, *cut.in_progress_route_ids]
        locked_routes = base.gate._cut_routes(current_solution, locked_ids)
        new_routes = [
            route for route in locked_routes if route.vehicle_id not in committed_routes
        ]
        for route in new_routes:
            committed_customers.update(base.p2.route_customers(route, current_instance))
            committed_routes[route.vehicle_id] = route
        for action in cut.locked_charging_actions:
            committed_actions.setdefault(base.action_key(action), action)

        construction = base.gate.build_open_stage(
            base.gate._cut_routes(current_solution, cut.editable_route_ids),
            current_instance,
            batch["events"],
            trigger,
            committed_customers,
            owners,
            sources["prices"],
            stage_index=stage_index,
            isolate_changed_customers=True,
        )
        base._validate_stage_application(construction, batch["events"])
        committed_profit = _profit_values(
            Solution(
                routes=list(committed_routes.values()),
                charging_actions=list(committed_actions.values()),
            ),
            current_instance,
            sources,
            owners,
        )
        try:
            result = _controlled_stage(
                arm,
                construction,
                sources,
                profiles,
                cut,
                owners,
                committed_customers,
                committed_profit,
                trigger=trigger,
                seed=stream_seed * 1000 + stage_index,
                evaluations=evaluations,
                stage_new_customer_ids=tuple(
                    sorted(
                        event.customer_id
                        for event in batch["events"]
                        if event.event_type.lower() == "add"
                    )
                ),
            )
        except base.NoExecutableContinuation as exc:
            raise base.NoExecutableContinuation(
                str(exc),
                stage=stage_index,
                trigger_second=trigger,
                completed_stage_count=len(rows),
            ) from exc
        future_customers = [
            customer_id
            for route in result["solution"].routes
            for customer_id in base.p2.route_customers(
                route, construction.effective_instance
            )
        ]
        active_customers = {
            node.node_id
            for node in construction.effective_instance.nodes
            if node.node_type.lower() == "c"
        }
        if len(future_customers) != len(set(future_customers)):
            raise RuntimeError("future plan contains duplicate customers")
        if committed_customers | set(future_customers) != active_customers:
            raise RuntimeError("customer accounting did not close")
        if committed_customers & set(future_customers):
            raise RuntimeError("a committed customer was planned twice")
        running_solution = _merge_execution_plan(
            committed_routes,
            committed_actions,
            result["solution"],
            route_history,
        )
        final_running = _profit_closure(
            running_solution,
            construction.effective_instance,
            sources,
            owners,
        )
        final_execution_solution = running_solution
        final_running["predicted_charging_emissions_kg"] = _charging_emissions_kg(
            running_solution,
            construction.effective_instance,
            profiles,
            "forecast_gco2_per_kwh",
        )
        final_running["actual_charging_emissions_kg"] = _charging_emissions_kg(
            running_solution,
            construction.effective_instance,
            profiles,
            "actual_gco2_per_kwh",
        )
        final_running["total_actual_emissions_kg"] = (
            final_running["direct_emissions_kg"]
            + final_running["actual_charging_emissions_kg"]
        )
        rows.append(
            {
                "arm": arm,
                "network": network,
                "responsibility_condition": condition,
                "stream_seed": stream_seed,
                "stage": stage_index,
                "trigger_second": trigger,
                "main_evaluations": int(result["evaluations"]),
                "shadow_evaluations": int(result["shadow_evaluations"]),
                "future_cost": float(result["future_cost"]),
                "running_total_cost": float(final_running["total_cost"]),
                "running_total_profit": float(final_running["total_profit"]),
                "running_total_actual_emissions_kg": float(
                    final_running["total_actual_emissions_kg"]
                ),
                "running_actual_charging_emissions_kg": float(
                    final_running["actual_charging_emissions_kg"]
                ),
                "running_predicted_charging_emissions_kg": float(
                    final_running["predicted_charging_emissions_kg"]
                ),
                "running_depot_profit_json": json.dumps(
                    final_running["depot_profit"], sort_keys=True
                ),
                "same_state_baseline_cost": float(result["same_state_baseline_cost"]),
                "same_state_baseline_start_source": result[
                    "same_state_baseline_start_source"
                ],
                "same_state_baseline_allowed_cross_count": len(
                    result["same_state_baseline_allowed_cross_ids"]
                ),
                "same_state_cost_saving_pct": float(result["same_state_cost_saving_pct"]),
                "minimum_profit_margin": float(result["minimum_profit_margin"]),
                "minimum_profit_ratio": float(result["minimum_profit_ratio"]),
                "participation_gate_rejections": int(
                    result["best_gate_rejection_count"]
                ),
                "charging_strategy": result["charging_strategy"],
                "eligible_charge_actions": int(
                    result["timing"]["eligible_action_count"]
                ),
                "charge_actions_at_earliest": int(
                    result["timing"]["actions_at_earliest_count"]
                ),
                "moved_charge_actions": int(result["timing"]["moved_action_count"]),
                "moved_charge_kwh": float(result["timing"]["moved_energy_kwh"]),
                "moved_from_search_schedule_actions": int(
                    result["timing"]["moved_action_count"]
                ),
                "moved_from_search_schedule_kwh": float(
                    result["timing"]["moved_energy_kwh"]
                ),
                "feasible_cross_candidate_count": int(
                    result["feasible_cross_candidate_count"]
                ),
                "forced_cross_attempt_count": int(
                    result["forced_cross_attempt_count"]
                ),
                "existing_cross_operator_id": result[
                    "existing_cross_operator_id"
                ],
                "existing_cross_scheduled_slots": ";".join(
                    str(value)
                    for value in result["existing_cross_scheduled_slots"]
                ),
                "existing_cross_scheduled_call_count": int(
                    result["existing_cross_scheduled_call_count"]
                ),
                "existing_cross_actual_call_count": int(
                    result["existing_cross_actual_call_count"]
                ),
                "shadow_existing_cross_actual_call_count": int(
                    result["shadow_existing_cross_actual_call_count"]
                ),
                "existing_cross_pair_removal_count": int(
                    result["existing_cross_pair_removal_count"]
                ),
                "existing_cross_forced_insertion_count": int(
                    result["existing_cross_forced_insertion_count"]
                ),
                "existing_cross_within_depot_reinsert_count": int(
                    result["existing_cross_within_depot_reinsert_count"]
                ),
                "existing_cross_candidate_build_count": int(
                    result["existing_cross_candidate_build_count"]
                ),
                "existing_cross_changed_candidate_count": int(
                    result["existing_cross_changed_candidate_count"]
                ),
                "existing_cross_dynamic_feasible_count": int(
                    result["existing_cross_dynamic_feasible_count"]
                ),
                "existing_cross_gate_rejection_count": int(
                    result["existing_cross_gate_rejection_count"]
                ),
                "existing_cross_accepted_count": int(
                    result["existing_cross_accepted_count"]
                ),
                "existing_cross_best_improved_count": int(
                    result["existing_cross_best_improved_count"]
                ),
                "existing_cross_moved_customer_ids": ";".join(
                    result["existing_cross_moved_customer_ids"]
                ),
                "existing_cross_rejection_counts_json": json.dumps(
                    result["existing_cross_rejections"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "stage_new_customer_count": int(
                    result["stage_new_customer_count"]
                ),
                "stage_new_customer_ids_json": json.dumps(
                    result["stage_new_customer_ids"],
                    ensure_ascii=False,
                ),
                "cross_site_customer_count": len(
                    base._cross_site_ids_for_routes(
                        result["solution"].routes,
                        construction.effective_instance,
                        owners,
                    )
                ),
                "customer_accounting_pass": True,
                "route_sha256": route_hash(result["solution"]),
                "energy_sha256": energy_hash(result["solution"]),
                "solution_sha256": canonical_sha256(
                    base.solution_to_dict(result["solution"])
                ),
                "certificate_sha256": canonical_sha256(
                    result["certificate"].as_dict()
                ),
                "same_state_baseline_profit_json": json.dumps(
                    result["same_state_baseline_profit"], sort_keys=True
                ),
                "selected_future_profit_json": json.dumps(
                    result["selected_future_profit"], sort_keys=True
                ),
                "profit_margins_json": json.dumps(
                    result["profit_margins"], sort_keys=True
                ),
                "profit_ratios_json": json.dumps(
                    result["profit_ratios"], sort_keys=True
                ),
                "shadow_search_seed": int(result["shadow_search_seed"]),
                "main_search_seed": int(result["main_search_seed"]),
                "second_start_sha256": result["second_start_sha256"],
                "baseline_output_sha256": result["baseline_output_sha256"],
                **result["timing_comparison"],
                "elapsed_seconds": time.perf_counter() - started,
            }
        )
        inherited_states = cut.asset_states
        inherited_locked_actions = cut.locked_charging_actions
        previous_stage_start = trigger
        current_solution = result["solution"]
        route_history.update(
            {route.vehicle_id: route for route in current_solution.routes}
        )
        current_certificate = result["certificate"]
        current_instance = construction.effective_instance

    if final_running is None or final_execution_solution is None:
        raise RuntimeError("dynamic arm completed no rolling stage")
    full_day_execution = _full_day_execution_summary(
        final_execution_solution,
        current_instance,
        owners,
    )
    return {
        "execution_status": "PASS",
        "arm": arm,
        "network": network,
        "responsibility_condition": condition,
        "stream_seed": stream_seed,
        "available_stages": len(all_batches),
        "stages": len(rows),
        "rows": rows,
        "initial_timing": initial_timing,
        "event_path": str(event_path.relative_to(ROOT)),
        "event_sha256": sha256(event_path),
        "owner_path": str(owner_path.relative_to(ROOT)),
        "owner_sha256": sha256(owner_path),
        "final_solution": base.solution_to_dict(current_solution),
        "final_certificate": current_certificate.as_dict(),
        "final_running": final_running,
        "full_day_execution": full_day_execution,
        "full_day_solution": base.solution_to_dict(final_execution_solution),
        "full_day_instance_nodes": [asdict(node) for node in current_instance.nodes],
    }


def _artifact_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }


def _run_probe_task(task: tuple[str, str, int, int, int]) -> dict[str, Any]:
    condition, arm, stream_seed, evaluations, max_stages = task
    return run_probe_arm(
        arm,
        condition=condition,
        stream_seed=stream_seed,
        evaluations=evaluations,
        max_stages=max_stages,
    )


def _parse_streams(value: str) -> tuple[int, ...]:
    streams = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not streams or len(streams) != len(set(streams)):
        raise argparse.ArgumentTypeError("streams must be a non-empty unique list")
    if any(seed not in {1, 2, 3, 4, 5} for seed in streams):
        raise argparse.ArgumentTypeError("streams must be selected from 1,2,3,4,5")
    return streams


def _parse_conditions(value: str) -> tuple[str, ...]:
    conditions = tuple(item.strip() for item in value.split(",") if item.strip())
    if not conditions or len(conditions) != len(set(conditions)):
        raise argparse.ArgumentTypeError("conditions must be a non-empty unique list")
    unknown = set(conditions) - set(CONDITIONS)
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown responsibility conditions: {sorted(unknown)}"
        )
    return conditions


def main() -> int:
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluations", type=int, default=DEFAULT_EVALUATIONS)
    parser.add_argument("--max-stages", type=int, default=MAX_STAGES)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--require-observable", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--streams", type=_parse_streams, default=(STREAM_SEED,))
    parser.add_argument(
        "--conditions",
        type=_parse_conditions,
        default=("geographic",),
    )
    args = parser.parse_args()
    if args.evaluations <= 0:
        raise ValueError("evaluations must be positive")
    if args.max_stages <= 0:
        raise ValueError("max stages must be positive")
    if args.workers <= 0:
        raise ValueError("workers must be positive")
    OUT = args.output if args.output.is_absolute() else ROOT / args.output
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    tasks = [
        (condition, arm, stream_seed, args.evaluations, args.max_stages)
        for condition in args.conditions
        for stream_seed in args.streams
        for arm in ARMS
    ]
    with ProcessPoolExecutor(max_workers=min(args.workers, len(tasks))) as pool:
        payloads = list(
            pool.map(
                _run_probe_task,
                tasks,
            )
        )
    rows = [row for payload in payloads for row in payload["rows"]]
    write_csv(OUT / "raw_runs.csv", rows)
    write_json(OUT / "sessions.json", payloads)

    protected_hashes = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in SOURCE_FILES
        if path.name in {"cost.py", "check.py", "evaluation.py"}
    }
    failures: list[str] = []
    if len(payloads) != len(ARMS) * len(args.streams) * len(args.conditions):
        failures.append("session count did not close")
    if any(len(payload["rows"]) != payload["stages"] for payload in payloads):
        failures.append("row count did not close")
    if any(int(row["main_evaluations"]) != args.evaluations for row in rows):
        failures.append("main search budget did not close")
    if any(int(row["shadow_evaluations"]) != args.evaluations for row in rows):
        failures.append("same-state comparison budget did not close")
    if any(
        int(row["shadow_search_seed"]) == int(row["main_search_seed"])
        for row in rows
    ):
        failures.append("the two search calls reused one call identity")
    if any(
        row["second_start_sha256"] != row["baseline_output_sha256"]
        for row in rows
    ):
        failures.append("the second search did not start from the first output")
    if any(not bool(row["customer_accounting_pass"]) for row in rows):
        failures.append("customer accounting failed")
    cooperative_rows = [row for row in rows if row["arm"] != "no_cooperation"]
    participation_rows = [
        row for row in rows if row["arm"] in {"full", "carbon_blind"}
    ]
    if any(float(row["same_state_cost_saving_pct"]) < -TOL for row in cooperative_rows):
        failures.append("cooperation lost its same-state fallback")
    if any(
        float(row["minimum_profit_margin"]) < -TOL
        for row in participation_rows
    ):
        failures.append("participation floor failed")
    if any(
        float(row["predicted_charging_saving_kg"]) < -TOL
        for row in rows
    ):
        failures.append("forecast-timed charging increased predicted emissions")
    aware_rows = [row for row in rows if row["charging_strategy"] == "aware"]
    carbon_blind_rows = [row for row in rows if row["arm"] == "carbon_blind"]
    if any(
        int(row["charge_actions_at_earliest"])
        != int(row["eligible_charge_actions"])
        for row in carbon_blind_rows
    ):
        failures.append("carbon-blind arm did not keep immediate charging")
    if any(
        int(row["cross_site_customer_count"]) != 0
        for row in rows
        if row["arm"] == "no_cooperation"
    ):
        failures.append("no-cooperation arm crossed depots")
    if any(
        int(row["stage_new_customer_count"]) > 0
        and int(row["forced_cross_attempt_count"]) <= 0
        for row in cooperative_rows
    ):
        failures.append("a cooperative stage did not exercise the fixed cross-depot check")
    if any(
        int(row["forced_cross_attempt_count"]) != 0
        for row in rows
        if row["arm"] == "no_cooperation"
    ):
        failures.append("no-cooperation arm exercised a cross-depot check")
    if any(
        int(row["existing_cross_scheduled_call_count"])
        != int(row["existing_cross_actual_call_count"])
        or int(row["existing_cross_actual_call_count"])
        != int(row["shadow_existing_cross_actual_call_count"])
        for row in rows
    ):
        failures.append("existing-customer paired call schedule did not close")
    if any(
        int(row["existing_cross_forced_insertion_count"]) != 0
        or bool(row["existing_cross_moved_customer_ids"])
        for row in rows
        if row["arm"] == "no_cooperation"
    ):
        failures.append("no-cooperation arm used an existing-customer cross-depot move")
    if args.require_observable:
        for condition in args.conditions:
            observed = sum(
                int(row["feasible_cross_candidate_count"])
                for row in cooperative_rows
                if row["responsibility_condition"] == condition
            )
            if observed <= 0:
                failures.append(
                    f"no feasible cross-depot candidate was observed for {condition}"
                )
            existing_observed = sum(
                int(row["existing_cross_dynamic_feasible_count"])
                for row in cooperative_rows
                if row["responsibility_condition"] == condition
            )
            if existing_observed <= 0:
                failures.append(
                    "no executable existing-customer cross-depot candidate was "
                    f"observed for {condition}"
                )
    verdict = (
        "E7_FULL_MECHANISM_GATE_PASS"
        if not failures
        else "HALT_E7_FULL_MECHANISM_GATE"
    )
    metadata = {
        "schema": "setp.e7.full_mechanism_gate.v6",
        "contract_id": CONTRACT_ID,
        "base_dynamic_contract_id": base.CONTRACT_ID,
        "source_commit": git_head(),
        "operating_day": OPERATING_DAY.isoformat(),
        "operating_day_reason": (
            "The paper had already designated 2025-11-13 as its reference carbon day; "
            "the date was not selected from this probe's result."
        ),
        "stream_seeds": list(args.streams),
        "responsibility_conditions": list(args.conditions),
        "stages": args.max_stages,
        "evaluations_per_search": args.evaluations,
        "arms": list(ARMS),
        "workers": min(args.workers, len(tasks)),
        "elapsed_seconds": time.perf_counter() - started,
        "protected_file_hashes": protected_hashes,
        "source_file_hashes": {
            str(path.relative_to(ROOT)): sha256(path) for path in SOURCE_FILES
        },
        "scientific_boundary": (
            "This gate checks equal compute, state continuity, participation, and paired "
            "charging settlement. Result direction is not an expansion gate, except that "
            "cooperation retains the same-state no-cooperation fallback."
        ),
    }
    decision = {
        "verdict": verdict,
        "failures": failures,
        "mechanical_checks": {
            "row_count": len(rows),
            "customer_accounting_all_pass": all(
                bool(row["customer_accounting_pass"]) for row in rows
            ),
            "minimum_cooperative_same_state_saving_pct": min(
                float(row["same_state_cost_saving_pct"])
                for row in cooperative_rows
            ),
            "minimum_cooperative_profit_ratio": min(
                float(row["minimum_profit_ratio"]) for row in cooperative_rows
            ),
            "minimum_participation_profit_margin": min(
                float(row["minimum_profit_margin"])
                for row in participation_rows
            ),
            "moved_from_search_schedule_action_count": sum(
                int(row["moved_from_search_schedule_actions"])
                for row in aware_rows
            ),
            "aware_vs_immediate_moved_action_count": sum(
                int(row["aware_vs_immediate_moved_action_count"])
                for row in aware_rows
            ),
            "feasible_cross_candidate_count": sum(
                int(row["feasible_cross_candidate_count"])
                for row in cooperative_rows
            ),
            "existing_cross_scheduled_call_count": sum(
                int(row["existing_cross_scheduled_call_count"])
                for row in rows
            ),
            "existing_cross_dynamic_feasible_count": sum(
                int(row["existing_cross_dynamic_feasible_count"])
                for row in cooperative_rows
            ),
            "existing_cross_accepted_count": sum(
                int(row["existing_cross_accepted_count"])
                for row in cooperative_rows
            ),
            "existing_cross_best_improved_count": sum(
                int(row["existing_cross_best_improved_count"])
                for row in cooperative_rows
            ),
            "forced_cross_attempt_count": sum(
                int(row["forced_cross_attempt_count"])
                for row in cooperative_rows
            ),
            "predicted_charging_saving_kg": sum(
                float(row["predicted_charging_saving_kg"])
                for row in aware_rows
            ),
            "feasible_cross_candidate_count_by_condition": {
                condition: sum(
                    int(row["feasible_cross_candidate_count"])
                    for row in cooperative_rows
                    if row["responsibility_condition"] == condition
                )
                for condition in args.conditions
            },
            "forced_cross_attempt_count_by_condition": {
                condition: sum(
                    int(row["forced_cross_attempt_count"])
                    for row in cooperative_rows
                    if row["responsibility_condition"] == condition
                )
                for condition in args.conditions
            },
            "actual_charging_saving_kg": sum(
                float(row["actual_charging_saving_kg"])
                for row in aware_rows
            ),
        },
        "formal_expansion_allowed": not failures,
    }
    write_json(OUT / "metadata.json", metadata)
    write_json(OUT / "decision.json", decision)
    report = [
        "# E7完整机制运行门",
        "",
        f"判定：`{verdict}`。",
        "",
        f"本次运行使用第1条订单流的前{args.max_stages}次调整。四组在每次调整中均完成两轮、每轮{args.evaluations}次方案比较。第一轮形成从当前状态继续各自经营的保底方案，第二轮仅切换被检验的规则。低碳组按预测碳强度安排充电，并用实际碳强度结算。",
        "",
        f"共得到{len(rows)}行阶段结果；观察到{decision['mechanical_checks']['feasible_cross_candidate_count']}个可执行的跨场候选；按预测安排相对有空即充的预测排放减少{decision['mechanical_checks']['predicted_charging_saving_kg']:.6f} kg，按实际碳强度结算的差值为{decision['mechanical_checks']['actual_charging_saving_kg']:.6f} kg。",
        "",
        f"充电相对搜索初始排班移动{decision['mechanical_checks']['moved_from_search_schedule_action_count']}次；低碳安排相对有空即充实际移动{decision['mechanical_checks']['aware_vs_immediate_moved_action_count']}次。两者必须分开解释。",
        "",
        "本结果只用于决定运行链条是否具备正式扩展条件，不作为论文中的机制效应数字。",
    ]
    if failures:
        report.extend(["", "失败项：" + "；".join(failures)])
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    write_json(OUT / "artifact_hashes.json", _artifact_hashes())
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
