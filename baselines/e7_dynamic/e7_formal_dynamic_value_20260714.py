#!/usr/bin/env python3
"""Paired dynamic-value experiment on the frozen 221-customer network."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
import csv
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from baselines.e3_ablation import e3_v3_runner as legacy
from baselines.e7_dynamic import e7_dynamic_continuous_trigger_gate_20260714 as gate
from baselines.e7_dynamic import e7_p2_single_event_probe_20260714 as p2
from setp_solver.algorithms.resetp_alns.kernel.alns_core import (
    AlnsState,
    SearchPolicy,
    cross_depot_boundary_removal,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerOperatorAction,
    WinnerOperatorSet,
    apply_winner_action,
)
from setp_solver.algorithms.resetp_alns.operators.feasible_repair import (
    enumerate_feasible_insertions,
    repair_removed_customers,
)
from setp_solver.cost import evaluate
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.dynamic import DynamicEvent, RollingParameters, _build_trigger_batches
from setp_solver.search import dynamic_multitrip_schedule as dynamic_schedule
from setp_solver.search.dynamic_multitrip_schedule import (
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    prepare_dynamic_multitrip_solution,
)
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.search.metaheuristic_baselines import solution_from_dict, solution_to_dict
from setp_solver.solution import ChargingAction, Route, Solution


ROOT = Path(__file__).resolve().parents[2]
BUNDLE_DIR = (
    ROOT
    / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets"
    / "L-main-threeshift-100c-01/bundle"
)
E6_ROOT = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
EVENT_ROOT = ROOT / "baselines/e7_dynamic/e7_v2_20260714/event_streams"
EVENT_INDEX_PATH = EVENT_ROOT / "raw_runs.csv"
DONOR_BUNDLE = (
    ROOT
    / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets"
    / "L-main-threeshift-200c-01/bundle"
)
DEFAULT_OUTPUT = ROOT / "baselines/e7_dynamic/e7_v2_20260714/preflight/paired_two_stage"
INSTANCE_SHA256 = "59696be304ad9f3c484820439e1cbdb027945e20ad7ecbdb8542dfde7e0d6225"
CONTRACT_ID = "E7_PAIRED_DYNAMIC_VALUE_V5_EXISTING_RECIPROCAL_NEIGHBORHOOD"
ROLLING_PARAMETERS = RollingParameters()
EXISTING_CROSS_OPERATOR_ID = "reciprocal_boundary_reinsert_v1"


class NoExecutableContinuation(RuntimeError):
    """A scientifically reportable dynamic arm failure after a closed budget."""

    def __init__(
        self,
        message: str,
        *,
        stage: int | None = None,
        trigger_second: float | None = None,
        completed_stage_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.trigger_second = trigger_second
        self.completed_stage_count = completed_stage_count
EXISTING_CROSS_INTERVAL = 100


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()


def arm_case(arm: str) -> str:
    if arm not in {"cooperative", "independent"}:
        raise ValueError(f"unknown arm {arm}")
    return "L-main-threeshift-100c-01__geographic__seed1__independent"


def load_arm(arm: str) -> dict[str, Any]:
    if arm not in {"cooperative", "independent"}:
        raise ValueError(f"unknown arm {arm}")
    instance_path = BUNDLE_DIR / "instance.json"
    if sha256(instance_path) != INSTANCE_SHA256:
        raise RuntimeError("frozen 221-customer instance changed")
    bundle = load_search_bundle(BUNDLE_DIR)
    case = arm_case(arm)
    solution_path = E6_ROOT / "solutions" / f"{case}.json"
    certificate_path = E6_ROOT / "certificates" / f"{case}.json"
    solution = solution_from_dict(json.loads(solution_path.read_text(encoding="utf-8")))
    certificate = p2.load_certificate(certificate_path)
    return {
        "arm": arm,
        "case": case,
        "bundle": bundle,
        "prices": legacy.prices_for("M1", 0.0),
        "solution": solution,
        "certificate": certificate,
        "solution_path": solution_path,
        "certificate_path": certificate_path,
        "instance_path": instance_path,
    }


def load_stream(seed: int) -> tuple[list[DynamicEvent], dict[str, str], Path, Path]:
    event_path = EVENT_ROOT / f"stream_seed{seed}.events.json"
    owner_path = EVENT_ROOT / f"stream_seed{seed}.owners.csv"
    events = [
        DynamicEvent(**row)
        for row in json.loads(event_path.read_text(encoding="utf-8"))
    ]
    donor_bundle = load_search_bundle(DONOR_BUNDLE)
    donors = {
        node.node_id: node
        for node in donor_bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    for event in events:
        if event.event_type != "add":
            continue
        if event.new_service_time is None or float(event.new_service_time) <= 0.0:
            raise RuntimeError(
                f"formal E7 add event {event.event_id} lacks a positive donor service time"
            )
        donor = donors.get(event.donor_customer_id)
        if donor is None or float(event.new_service_time) != float(donor.service_time):
            raise RuntimeError(
                f"formal E7 add event {event.event_id} service time does not match donor "
                f"{event.donor_customer_id}"
            )
    with owner_path.open(newline="", encoding="utf-8") as handle:
        owners = {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}
    _validate_frozen_trigger_times(seed, events)
    return events, owners, event_path, owner_path


def _validated_trigger_batches(
    seed: int,
    events: Sequence[DynamicEvent],
) -> list[dict[str, Any]]:
    batches = [
        batch
        for batch in _build_trigger_batches(list(events), ROLLING_PARAMETERS)
        if batch["events"]
    ]
    expected = _frozen_trigger_times(seed)
    observed = {
        str(event.event_id): float(batch["trigger_time"])
        for batch in batches
        for event in batch["events"]
    }
    if set(observed) != set(expected):
        raise RuntimeError(
            f"stream {seed} trigger contract event IDs differ: "
            f"missing={sorted(set(expected) - set(observed))}, "
            f"extra={sorted(set(observed) - set(expected))}"
        )
    mismatches = {
        event_id: (observed[event_id], expected[event_id])
        for event_id in expected
        if observed[event_id] != expected[event_id]
    }
    if mismatches:
        raise RuntimeError(f"stream {seed} frozen trigger times differ: {mismatches}")
    return batches


def _frozen_trigger_times(seed: int) -> dict[str, float]:
    expected: dict[str, float] = {}
    with EVENT_INDEX_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["seed"]) != seed:
                continue
            event_id = str(row["event_id"])
            trigger = float(row["trigger_second"])
            previous = expected.get(event_id)
            if previous is not None and previous != trigger:
                raise RuntimeError(
                    f"stream {seed} event {event_id} has conflicting frozen trigger times"
                )
            expected[event_id] = trigger
    if not expected:
        raise RuntimeError(f"stream {seed} has no rows in frozen trigger index")
    return expected


def _validate_frozen_trigger_times(seed: int, events: Sequence[DynamicEvent]) -> None:
    _validated_trigger_batches(seed, events)


def _validate_stage_application(
    construction: gate.StageConstruction,
    stage_events: Sequence[DynamicEvent],
) -> tuple[list[str], list[str], list[str], list[str]]:
    event_ids = [str(event.event_id) for event in stage_events]
    event_types = [str(event.event_type) for event in stage_events]
    applied = [str(event_id) for event_id in construction.applied_event_ids]
    ignored = [str(event_id) for event_id in construction.ignored_locked_event_ids]
    if len(applied) != len(set(applied)) or len(ignored) != len(set(ignored)):
        raise RuntimeError("dynamic event application contains duplicate event IDs")
    if set(applied) & set(ignored):
        raise RuntimeError("a dynamic event cannot be both applied and locked")
    if set(applied) | set(ignored) != set(event_ids):
        raise RuntimeError(
            "applied and locked event IDs do not partition the trigger batch: "
            f"expected={event_ids}, applied={applied}, locked={ignored}"
        )
    type_by_id = {str(event.event_id): str(event.event_type).lower() for event in stage_events}
    invalid_locked = [event_id for event_id in ignored if type_by_id[event_id] == "add"]
    if invalid_locked:
        raise RuntimeError(f"new orders must never be ignored as locked: {invalid_locked}")
    return event_ids, event_types, applied, ignored


def _stage_timing(
    elapsed_seconds: float,
    trigger_second: float,
    next_trigger_second: float | None,
) -> tuple[float | None, bool | None]:
    if next_trigger_second is None:
        return None, None
    available = float(next_trigger_second) - float(trigger_second)
    if available < 0.0:
        raise RuntimeError("next dynamic trigger precedes the current trigger")
    return available, float(elapsed_seconds) <= available


def action_key(action: ChargingAction) -> tuple[Any, ...]:
    return (
        action.vehicle_id,
        action.station_id,
        round(float(action.charge_start_second), 9),
        round(float(action.energy_kwh), 9),
    )


def add_breakdown(total: dict[str, float], part: Mapping[str, Any]) -> None:
    for key, value in part.items():
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            total[key] = total.get(key, 0.0) + float(value)


def evaluate_parts(
    routes: Sequence[Route],
    actions: Sequence[ChargingAction],
    instance: Any,
    sources: Mapping[str, Any],
) -> dict[str, Any]:
    return evaluate(
        Solution(routes=list(routes), charging_actions=list(actions)),
        instance,
        sources["bundle"].carbon_profile,
        sources["prices"],
        carbon_quota_kg=0.0,
    )


def normalized_search_solution(
    prepared: Solution,
    instance: Any,
    owners: dict[str, str],
) -> Solution:
    routes = [
        replace(route, vehicle_id=f"DYN_OPEN_{index:03d}")
        for index, route in enumerate(prepared.routes, start=1)
    ]
    return Solution(
        routes=routes,
        charging_actions=[],
        cross_site_services=p2.annotate_cross_site(routes, instance, owners),
    )


def exact_candidate(
    solution: Solution,
    construction: gate.StageConstruction,
    sources: Mapping[str, Any],
    cut: Any,
    trigger: float,
) -> tuple[Solution, Any, float]:
    prepared, certificate = prepare_dynamic_multitrip_solution(
        solution,
        construction.effective_instance,
        sources["prices"],
        asset_states=cut.asset_states,
        stage_start_second=trigger,
        locked_charging_actions=cut.locked_charging_actions,
    )
    cost = float(
        evaluate_parts(
            prepared.routes,
            prepared.charging_actions,
            construction.effective_instance,
            sources,
        )["total_cost"]
    )
    return prepared, certificate, cost


def common_operator_pairs() -> tuple[tuple[str, str], ...]:
    operators = WinnerOperatorSet.create(
        include_route_elimination=False,
        allow_cross_depot=False,
    )
    return tuple(
        (destroy_id, repair_id)
        for destroy_id, _ in operators.destroy_ops
        for repair_id, _ in operators.repair_ops
    )


def existing_customer_cross_slots(
    evaluations: int,
    stage_new_customer_count: int,
) -> tuple[int, ...]:
    """Return the frozen reciprocal-neighbourhood calls for one E7 stage."""

    if evaluations <= 0:
        return ()
    first = 1 if stage_new_customer_count <= 0 else max(4, stage_new_customer_count) + 1
    if first > evaluations:
        return ()
    return tuple(range(first, evaluations + 1, EXISTING_CROSS_INTERVAL))


def _within_depot_changed_reinsert(
    partial_solution: Solution,
    removed_customers: Sequence[str],
    source_solution: Solution,
    context: EvaluationContext,
    policy: SearchPolicy,
) -> Solution | None:
    """Reinsert the selected pair at their home depots with a real route change."""

    source_hash = canonical_sha256(solution_to_dict(source_solution))
    ordered = tuple(removed_customers)
    for pending in (ordered, tuple(reversed(ordered))):
        first, *remaining = pending
        options = enumerate_feasible_insertions(
            partial_solution,
            first,
            context,
            policy,
            max_route_candidates=max(1, len(partial_solution.routes)),
            max_positions_per_route=2,
            allow_new_route=False,
        )
        for option in options:
            repaired = repair_removed_customers(
                option.solution,
                list(remaining),
                context,
                policy,
                mode="regret2",
                allow_new_route=False,
                defer_complete_check=True,
            )
            if repaired is None:
                continue
            if canonical_sha256(solution_to_dict(repaired)) != source_hash:
                return repaired
    return None


def existing_customer_reciprocal_candidate(
    base_solution: Solution,
    instance: Any,
    owners: Mapping[str, str],
    prices: Any,
    carbon_profile: Sequence[Mapping[str, Any]],
    *,
    stage_new_customer_ids: Sequence[str],
    allow_cross_depot: bool,
    rng: np.random.Generator,
) -> tuple[Solution | None, dict[str, Any]]:
    """Build one route-only reciprocal candidate from not-yet-departed customers.

    This function deliberately performs no complete-solution scoring.  The
    caller must submit any returned candidate to ``exact_candidate`` so current
    vehicle availability, carried battery, and locked charging remain the only
    dynamic feasibility authority.
    """

    excluded = set(stage_new_customer_ids)
    existing_owners = {
        customer_id: depot_id
        for customer_id, depot_id in owners.items()
        if customer_id not in excluded
    }
    operator_context = EvaluationContext(
        instance,
        list(carbon_profile),
        prices=prices,
        customer_home_depot=existing_owners,
        allow_cross_depot=allow_cross_depot,
        repair_delta_mode="fast",
    )
    policy = SearchPolicy(
        require_charging_signal=False,
        allow_cross_depot=allow_cross_depot,
        reciprocal_cross_depot=True,
    )
    source = AlnsState(base_solution, operator_context, policy=policy)
    destroyed = cross_depot_boundary_removal(source, rng)
    removed = tuple(destroyed.removed_customers)
    removed_owners = {
        existing_owners.get(customer_id)
        for customer_id in removed
        if existing_owners.get(customer_id) is not None
    }
    evidence: dict[str, Any] = {
        "operator_id": EXISTING_CROSS_OPERATOR_ID,
        "removed_customer_ids": list(removed),
        "reciprocal_pair_removal_count": int(
            operator_context.score_counts.get(
                "reciprocal_cross_depot_pair_removals",
                0,
            )
        ),
        "forced_insertion_count": 0,
        "within_depot_reinserted": False,
        "candidate_built": False,
        "candidate_changed": False,
    }
    # The E7 treatment is a complete two-way exchange.  Do not fall through to
    # the legacy one-customer move if one side has no eligible existing customer.
    if len(removed) != 2 or len(removed_owners) != 2:
        return None, evidence
    if allow_cross_depot:
        repaired = repair_removed_customers(
            destroyed.solution,
            list(removed),
            operator_context,
            policy,
            mode="cross_depot",
            allow_new_route=False,
            defer_complete_check=True,
        )
    else:
        repaired = _within_depot_changed_reinsert(
            destroyed.solution,
            removed,
            base_solution,
            operator_context,
            policy,
        )
        evidence["within_depot_reinserted"] = repaired is not None
    evidence["forced_insertion_count"] = int(
        operator_context.score_counts.get("cross_depot_forced_insertions", 0)
    )
    if repaired is None:
        return None, evidence
    candidate = replace(
        repaired,
        charging_actions=[],
        cross_site_services=p2.annotate_cross_site(
            repaired.routes,
            instance,
            owners,
        ),
    )
    evidence["candidate_built"] = True
    evidence["candidate_changed"] = canonical_sha256(
        solution_to_dict(candidate)
    ) != canonical_sha256(solution_to_dict(base_solution))
    return candidate, evidence


def event_insertion_candidate(
    construction: gate.StageConstruction,
    owners: dict[str, str],
    prices: Any,
    base_solution: Solution,
    preserve_event_types: bool,
    *,
    stage_new_customer_ids: Sequence[str] | None = None,
    allow_cross_depot: bool,
    rng: np.random.Generator,
    force_cross_depot: bool = False,
    deterministic_choice_index: int | None = None,
) -> Solution | None:
    """Reinsert the current event customers into existing open routes."""

    if stage_new_customer_ids is None:
        event_routes = [
            route
            for route in construction.solution.routes
            if "_ADD_" in route.vehicle_id
        ]
        pending = [
            customer_id
            for route in event_routes
            for customer_id in p2.route_customers(
                route, construction.effective_instance
            )
        ]
    else:
        pending = list(stage_new_customer_ids)
    if not pending:
        return None
    if len(pending) != len(set(pending)):
        raise RuntimeError("stage new-customer identities are not unique")
    route_ids = [route.vehicle_id for route in base_solution.routes]
    if len(set(route_ids)) != len(route_ids):
        raise RuntimeError("dynamic search base route ids are not unique")
    event_route_by_customer = {}
    routes = []
    pending_set = set(pending)
    for route in base_solution.routes:
        customers = p2.route_customers(route, construction.effective_instance)
        for customer_id in pending_set.intersection(customers):
            event_route_by_customer[customer_id] = route
        sequence = [node_id for node_id in route.node_sequence if node_id not in pending_set]
        candidate = replace(route, node_sequence=sequence)
        if p2.route_customers(candidate, construction.effective_instance):
            routes.append(candidate)
    if set(event_route_by_customer) != pending_set:
        return None
    pending = [pending[index] for index in rng.permutation(len(pending))]
    for customer_id in pending:
        options: list[tuple[float, int, int, Route]] = []
        for route_index, route in enumerate(routes):
            if not allow_cross_depot and route.home_depot_id != owners[customer_id]:
                continue
            if force_cross_depot and route.home_depot_id == owners[customer_id]:
                continue
            for insert_at in range(1, len(route.node_sequence)):
                sequence = list(route.node_sequence)
                sequence.insert(insert_at, customer_id)
                candidate = replace(route, node_sequence=sequence)
                if (
                    gate._route_load(candidate, construction.effective_instance)
                    > float(prices.Q_capacity) + 1e-6
                ):
                    continue
                try:
                    gate.route_timing(
                        candidate,
                        construction.effective_instance,
                        prices,
                    )
                except ValueError:
                    continue
                options.append(
                    (
                        gate._incremental_distance(
                            route,
                            insert_at,
                            customer_id,
                            construction.effective_instance,
                        ),
                        route_index,
                        insert_at,
                        candidate,
                    )
                )
        if force_cross_depot and not options:
            return None
        if not options or (
            deterministic_choice_index is None and rng.random() < 0.5
        ):
            source = event_route_by_customer[customer_id]
            used_route_ids = {route.vehicle_id for route in routes}
            singleton_id = f"DYN_EVENT_{customer_id}"
            suffix = 1
            while singleton_id in used_route_ids:
                suffix += 1
                singleton_id = f"DYN_EVENT_{customer_id}_{suffix}"
            routes.append(
                replace(
                    source,
                    vehicle_id=singleton_id,
                    node_sequence=[source.home_depot_id, customer_id, source.home_depot_id],
                    vehicle_type=(
                        source.vehicle_type
                        if preserve_event_types
                        else ("ev" if rng.random() < 0.5 else "cv")
                    ),
                )
            )
            continue
        options.sort(key=lambda item: (item[0], item[1], item[2]))
        choice_pool = options[: min(20, len(options))]
        if deterministic_choice_index is None:
            choice = int(rng.integers(0, len(choice_pool)))
        else:
            choice = int(deterministic_choice_index) % len(choice_pool)
        _, selected_index, _, selected = choice_pool[choice]
        routes[selected_index] = selected
    if not preserve_event_types and routes:
        flip_count = min(len(routes), 1 + int(rng.integers(0, 8)))
        flip_indexes = set(int(value) for value in rng.choice(len(routes), size=flip_count, replace=False))
        routes = [
            replace(
                route,
                vehicle_type=(
                    "ev" if route.vehicle_type.lower() == "cv" else "cv"
                ),
            )
            if index in flip_indexes
            else route
            for index, route in enumerate(routes)
        ]
    return Solution(
        routes=routes,
        charging_actions=[],
        cross_site_services=p2.annotate_cross_site(
            routes,
            construction.effective_instance,
            owners,
        ),
    )


def _project_asset_chain(
    routes: Sequence[Route],
    asset_state: Any,
    instance: Any,
    prices: Any,
    stage_start_second: float,
) -> tuple[float, float] | None:
    """Project one proposed route chain on one inherited vehicle.

    This is a construction check only.  It does not score a complete solution
    and it does not replace the exact inherited-fleet check performed once the
    complete candidate has been built.
    """

    working = dynamic_schedule._WorkingAsset(
        state=asset_state,
        available_second=float(asset_state.available_second),
        battery_kwh=float(asset_state.remaining_battery_kwh),
        next_trip_index=int(asset_state.next_trip_index),
    )
    power = float(prices.depot_charge_power_kw)
    battery_cap = float(prices.B_battery_kwh)
    try:
        charging_curve = dynamic_schedule.curve_from_parameters(
            prices,
            capacity_kwh=battery_cap,
            reference_power_kw=power,
        )
    except dynamic_schedule.ChargingCurveError:
        return None
    minimum_slack = math.inf
    for route in routes:
        try:
            profile = dynamic_schedule._route_profile(route, instance, prices)
        except ValueError:
            return None
        candidates = dynamic_schedule._dynamic_assignment_candidates(
            profile,
            {asset_state.physical_vehicle_id: working},
            instance,
            prices,
            float(stage_start_second),
            charging_curve,
        )
        if not candidates:
            return None
        returned, departure, _ = candidates[0]
        minimum_slack = min(
            minimum_slack,
            float(profile.latest_departure_second) - float(departure),
        )
        working.available_second = float(returned)
        working.next_trip_index += 1
        if route.vehicle_type.lower() == "ev":
            departure_battery = max(
                float(working.battery_kwh),
                float(profile.drive_energy_kwh),
            )
            working.battery_kwh = departure_battery - float(profile.drive_energy_kwh)
    return minimum_slack, float(working.available_second)


def asset_aware_future_repack_candidate(
    construction: gate.StageConstruction,
    owners: Mapping[str, str],
    prices: Any,
    *,
    asset_states: Mapping[str, Any],
    stage_start_second: float,
    allow_cross_depot: bool,
    failure_diagnostics: dict[str, Any] | None = None,
) -> Solution | None:
    """Deterministically rebuild current future work around inherited vehicles.

    Only customers present in the current open fragment are used.  The function
    has no event-stream input and therefore cannot inspect a later trigger.
    """

    instance = construction.effective_instance
    node_by_id = {node.node_id: node for node in instance.nodes}
    customers = sorted(
        {
            customer_id
            for route in construction.solution.routes
            for customer_id in p2.route_customers(route, instance)
        },
        key=lambda customer_id: (
            float(node_by_id[customer_id].due_time),
            float(node_by_id[customer_id].ready_time),
            -float(node_by_id[customer_id].demand),
            customer_id,
        ),
    )
    if not customers:
        if failure_diagnostics is not None:
            failure_diagnostics.update({"reason": "no_open_customers"})
        return None
    ordered_assets = sorted(asset_states.items())
    if not ordered_assets:
        if failure_diagnostics is not None:
            failure_diagnostics.update({"reason": "no_inherited_assets"})
        return None
    asset_rank = {asset_id: index for index, (asset_id, _) in enumerate(ordered_assets)}
    chains: dict[str, list[Route]] = {asset_id: [] for asset_id, _ in ordered_assets}

    for customer_id in customers:
        owner = owners.get(customer_id)
        if owner is None:
            if failure_diagnostics is not None:
                failure_diagnostics.update(
                    {
                        "reason": "missing_customer_owner",
                        "customer_id": customer_id,
                    }
                )
            return None
        options: list[
            tuple[tuple[float, float, int, float, str, int, int], str, list[Route]]
        ] = []
        for asset_id, state in ordered_assets:
            if not allow_cross_depot and state.home_depot_id != owner:
                continue
            current_chain = chains[asset_id]
            placements: list[tuple[int, int, Route, float, int]] = []
            for route_index, route in enumerate(current_chain):
                for insert_at in range(1, len(route.node_sequence)):
                    sequence = list(route.node_sequence)
                    sequence.insert(insert_at, customer_id)
                    candidate_route = replace(route, node_sequence=sequence)
                    if (
                        gate._route_load(candidate_route, instance)
                        > float(prices.Q_capacity) + 1e-6
                    ):
                        continue
                    try:
                        gate.route_timing(candidate_route, instance, prices)
                    except ValueError:
                        continue
                    placements.append(
                        (
                            route_index,
                            insert_at,
                            candidate_route,
                            gate._incremental_distance(
                                route,
                                insert_at,
                                customer_id,
                                instance,
                            ),
                            0,
                        )
                    )
            new_route = Route(
                vehicle_id=(
                    f"AWARE_{asset_rank[asset_id] + 1:02d}_"
                    f"{len(current_chain) + 1:03d}"
                ),
                vehicle_type=state.vehicle_type,
                home_depot_id=state.home_depot_id,
                node_sequence=[state.home_depot_id, customer_id, state.home_depot_id],
            )
            try:
                gate.route_timing(new_route, instance, prices)
            except ValueError:
                pass
            else:
                new_distance = (
                    instance.distance(state.home_depot_id, customer_id)
                    + instance.distance(customer_id, state.home_depot_id)
                )
                placements.append(
                    (len(current_chain), 1, new_route, float(new_distance), 1)
                )

            for route_index, insert_at, candidate_route, extra_distance, new_trip in placements:
                proposed = list(current_chain)
                if new_trip:
                    proposed.append(candidate_route)
                else:
                    proposed[route_index] = candidate_route
                projection = _project_asset_chain(
                    proposed,
                    state,
                    instance,
                    prices,
                    stage_start_second,
                )
                if projection is None:
                    continue
                minimum_slack, finish_second = projection
                rank = (
                    -float(minimum_slack),
                    float(extra_distance),
                    int(new_trip),
                    float(finish_second),
                    asset_id,
                    int(route_index),
                    int(insert_at),
                )
                options.append((rank, asset_id, proposed))
        if not options:
            if failure_diagnostics is not None:
                eligible_assets = [
                    asset_id
                    for asset_id, state in ordered_assets
                    if allow_cross_depot or state.home_depot_id == owner
                ]
                failure_diagnostics.update(
                    {
                        "reason": "greedy_customer_has_no_asset_placement",
                        "customer_id": customer_id,
                        "customer_owner": owner,
                        "stage_start_second": float(stage_start_second),
                        "allow_cross_depot": bool(allow_cross_depot),
                        "processed_customer_count": sum(
                            len(
                                {
                                    item
                                    for route in chain
                                    for item in p2.route_customers(route, instance)
                                }
                            )
                            for chain in chains.values()
                        ),
                        "total_customer_count": len(customers),
                        "eligible_asset_ids": eligible_assets,
                        "chain_route_counts": {
                            asset_id: len(chains[asset_id]) for asset_id in eligible_assets
                        },
                        "chain_customer_counts": {
                            asset_id: sum(
                                len(p2.route_customers(route, instance))
                                for route in chains[asset_id]
                            )
                            for asset_id in eligible_assets
                        },
                    }
                )
            return None
        _, selected_asset_id, selected_chain = min(options, key=lambda item: item[0])
        chains[selected_asset_id] = selected_chain

    routes = [route for asset_id, _ in ordered_assets for route in chains[asset_id]]
    return Solution(
        routes=routes,
        charging_actions=[],
        cross_site_services=p2.annotate_cross_site(routes, instance, owners),
    )


def _evaluate_specialist_candidate_once(
    context: EvaluationContext,
    candidate_solution: Solution | None,
    exact_evaluator: Callable[[Solution], tuple[Solution, Any, float]],
) -> tuple[tuple[Solution, Any, float] | None, ValueError | None]:
    """Count and exactly check one complete specialist candidate at most once."""

    assert context.budget is not None
    context.budget.record()
    context.score_counts["candidate"] = int(context.score_counts.get("candidate", 0)) + 1
    if candidate_solution is None:
        return None, None
    try:
        return exact_evaluator(candidate_solution), None
    except ValueError as exc:
        return None, exc


def future_repack_candidate(
    construction: gate.StageConstruction,
    owners: Mapping[str, str],
    prices: Any,
    *,
    allow_cross_depot: bool,
    rng: np.random.Generator,
) -> Solution | None:
    """Repack only the not-yet-departed customers when local repair cannot continue."""

    instance = construction.effective_instance
    customers = sorted(
        {
            customer_id
            for route in construction.solution.routes
            for customer_id in p2.route_customers(route, instance)
        }
    )
    if not customers:
        return None
    customers = [customers[index] for index in rng.permutation(len(customers))]
    depot_ids = sorted(
        node.node_id for node in instance.nodes if node.node_type.lower() == "d"
    )
    routes: list[Route] = []
    for customer_id in customers:
        allowed_depots = depot_ids if allow_cross_depot else [owners[customer_id]]
        insertion_options: list[tuple[float, int, int, Route]] = []
        for route_index, route in enumerate(routes):
            if route.home_depot_id not in allowed_depots:
                continue
            for insert_at in range(1, len(route.node_sequence)):
                sequence = list(route.node_sequence)
                sequence.insert(insert_at, customer_id)
                candidate = replace(route, node_sequence=sequence)
                if gate._route_load(candidate, instance) > float(prices.Q_capacity) + 1e-6:
                    continue
                try:
                    gate.route_timing(candidate, instance, prices)
                except ValueError:
                    continue
                insertion_options.append(
                    (
                        gate._incremental_distance(route, insert_at, customer_id, instance),
                        route_index,
                        insert_at,
                        candidate,
                    )
                )
        # A little randomness avoids rebuilding the same packing on every try,
        # while still favouring short insertions.
        if insertion_options and rng.random() < 0.85:
            insertion_options.sort(key=lambda item: (item[0], item[1], item[2]))
            pool = insertion_options[: min(30, len(insertion_options))]
            _, route_index, _, candidate = pool[int(rng.integers(0, len(pool)))]
            routes[route_index] = candidate
            continue
        new_options: list[Route] = []
        for depot_id in allowed_depots:
            for vehicle_type in ("cv", "ev"):
                candidate = Route(
                    vehicle_id=f"REPACK_{len(routes) + 1:03d}",
                    vehicle_type=vehicle_type,
                    home_depot_id=depot_id,
                    node_sequence=[depot_id, customer_id, depot_id],
                )
                try:
                    gate.route_timing(candidate, instance, prices)
                except ValueError:
                    continue
                new_options.append(candidate)
        if not new_options:
            return None
        routes.append(new_options[int(rng.integers(0, len(new_options)))])

    routes = [
        replace(route, vehicle_type=("ev" if rng.random() < 0.5 else "cv"))
        for route in routes
    ]
    return Solution(
        routes=routes,
        charging_actions=[],
        cross_site_services=p2.annotate_cross_site(routes, instance, owners),
    )


def search_stage(
    construction: gate.StageConstruction,
    sources: Mapping[str, Any],
    cut: Any,
    owners: dict[str, str],
    committed_customers: set[str],
    *,
    trigger: float,
    seed: int,
    evaluations: int,
    allow_cross_depot: bool,
    stage_new_customer_ids: Sequence[str] | None = None,
    candidate_best_gate: Callable[[Solution, Any, float], bool] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    current = construction.solution
    current_prepared = None
    current_certificate = None
    current_cost = math.inf
    initial_feasible = False
    type_trials = 0
    try:
        prepared, certificate, type_trials = gate.prepare_stage_with_singleton_type_choices(
            construction,
            sources["prices"],
            asset_states=cut.asset_states,
            stage_start_second=trigger,
            locked_charging_actions=cut.locked_charging_actions,
        )
        current = normalized_search_solution(
            prepared,
            construction.effective_instance,
            owners,
        )
        current_prepared = prepared
        current_certificate = certificate
        current_cost = float(
            evaluate_parts(
                prepared.routes,
                prepared.charging_actions,
                construction.effective_instance,
                sources,
            )["total_cost"]
        )
        initial_feasible = True
    except RuntimeError:
        pass

    initial_structure = current if initial_feasible else None
    initial_prepared = current_prepared
    initial_certificate = current_certificate
    initial_cost = current_cost

    search_instance = p2.future_only_instance(
        construction.effective_instance,
        committed_customers,
    )
    context = EvaluationContext(
        search_instance,
        sources["bundle"].carbon_profile,
        prices=sources["prices"],
        budget=EvalBudget(limit=evaluations, target=evaluations),
        customer_home_depot=owners,
        allow_cross_depot=allow_cross_depot,
        repair_delta_mode="fast",
    )
    policy = SearchPolicy(
        require_charging_signal=False,
        max_cv=999,
        max_ev=999,
        allow_cross_depot=allow_cross_depot,
    )
    operators = WinnerOperatorSet.create(
        include_route_elimination=False,
        # Both arms must use the same operator menu.  The treatment is carried
        # only by EvaluationContext/SearchPolicy and the dynamic specialist
        # insertion rules below.
        allow_cross_depot=False,
    )
    pairs = list(common_operator_pairs())
    weights = np.ones(len(pairs), dtype=float)
    rng = np.random.default_rng(seed)
    best_structure = current
    best_prepared = current_prepared
    best_certificate = current_certificate
    best_cost = current_cost
    changed_count = feasible_count = accepted_count = exact_check_count = 0
    feasible_cross_candidate_count = 0
    best_gate_rejection_count = 0
    dynamic_rejections: Counter[str] = Counter()
    forced_cross_attempt_count = 0
    if stage_new_customer_ids is None:
        active_stage_new_customer_ids = tuple(
            customer_id
            for route in construction.solution.routes
            if "_ADD_" in route.vehicle_id
            for customer_id in p2.route_customers(
                route, construction.effective_instance
            )
        )
    else:
        active_stage_new_customer_ids = tuple(stage_new_customer_ids)
    if len(active_stage_new_customer_ids) != len(set(active_stage_new_customer_ids)):
        raise RuntimeError("stage new-customer identities are not unique")
    planned_customers = {
        customer_id
        for route in construction.solution.routes
        for customer_id in p2.route_customers(route, construction.effective_instance)
    }
    missing_stage_customers = sorted(
        set(active_stage_new_customer_ids) - planned_customers
    )
    if missing_stage_customers:
        raise RuntimeError(
            "stage new-customer identities are absent from the search start: "
            f"{missing_stage_customers}"
        )
    has_isolated_event = bool(active_stage_new_customer_ids)
    existing_cross_slots = existing_customer_cross_slots(
        evaluations,
        len(active_stage_new_customer_ids),
    )
    existing_cross_slot_set = set(existing_cross_slots)
    existing_cross_actual_call_count = 0
    existing_cross_pair_removal_count = 0
    existing_cross_forced_insertion_count = 0
    existing_cross_within_depot_reinsert_count = 0
    existing_cross_candidate_build_count = 0
    existing_cross_changed_candidate_count = 0
    existing_cross_dynamic_feasible_count = 0
    existing_cross_gate_rejection_count = 0
    existing_cross_accepted_count = 0
    existing_cross_best_improved_count = 0
    existing_cross_moved_customer_ids: set[str] = set()
    existing_cross_rejections: Counter[str] = Counter()
    for iteration in range(1, evaluations + 1):
        specialist_result = None
        specialist_error = None
        existing_cross_evidence: dict[str, Any] = {}
        existing_cross_removed_ids: set[str] = set()
        pair_index = int(rng.choice(len(pairs), p=weights / weights.sum()))
        destroy_id, repair_id = pairs[pair_index]
        local_repair_limit = min(400, max(50, evaluations // 2))
        existing_cross_used = iteration in existing_cross_slot_set
        event_specialist_used = has_isolated_event and (
            iteration <= local_repair_limit or not initial_feasible
        )
        specialist_used = existing_cross_used or event_specialist_used
        if existing_cross_used:
            existing_cross_actual_call_count += 1
            candidate_solution, existing_cross_evidence = (
                existing_customer_reciprocal_candidate(
                    current,
                    search_instance,
                    owners,
                    sources["prices"],
                    sources["bundle"].carbon_profile,
                    stage_new_customer_ids=active_stage_new_customer_ids,
                    allow_cross_depot=allow_cross_depot,
                    rng=rng,
                )
            )
            existing_cross_removed_ids = set(
                existing_cross_evidence.get("removed_customer_ids", [])
            )
            existing_cross_pair_removal_count += int(
                existing_cross_evidence.get("reciprocal_pair_removal_count", 0)
            )
            existing_cross_forced_insertion_count += int(
                existing_cross_evidence.get("forced_insertion_count", 0)
            )
            existing_cross_within_depot_reinsert_count += int(
                bool(existing_cross_evidence.get("within_depot_reinserted", False))
            )
            existing_cross_candidate_build_count += int(candidate_solution is not None)
            existing_cross_changed_candidate_count += int(
                bool(existing_cross_evidence.get("candidate_changed", False))
            )
            specialist_result, specialist_error = _evaluate_specialist_candidate_once(
                context,
                candidate_solution,
                lambda candidate: exact_candidate(
                    candidate,
                    construction,
                    sources,
                    cut,
                    trigger,
                ),
            )
            changed = bool(existing_cross_evidence.get("candidate_changed", False))
            if candidate_solution is not None:
                exact_check_count += 1
            if specialist_result is not None:
                existing_cross_dynamic_feasible_count += 1
                existing_cross_moved_customer_ids.update(
                    set(
                        _cross_site_ids_for_routes(
                            specialist_result[0].routes,
                            construction.effective_instance,
                            owners,
                        )
                    )
                    & existing_cross_removed_ids
                )
            elif specialist_error is not None:
                existing_cross_rejections[str(specialist_error)] += 1
        elif event_specialist_used:
            forced_cross_event = (
                allow_cross_depot
                and bool(active_stage_new_customer_ids)
                and iteration <= min(evaluations, max(4, len(active_stage_new_customer_ids)))
            )
            if forced_cross_event:
                selected_customer = active_stage_new_customer_ids[
                    (iteration - 1) % len(active_stage_new_customer_ids)
                ]
                selected_rank = (iteration - 1) // len(active_stage_new_customer_ids)
                candidate_solution = event_insertion_candidate(
                    construction,
                    owners,
                    sources["prices"],
                    current,
                    True,
                    stage_new_customer_ids=(selected_customer,),
                    allow_cross_depot=True,
                    rng=rng,
                    force_cross_depot=True,
                    deterministic_choice_index=selected_rank,
                )
                forced_cross_attempt_count += 1
            elif not initial_feasible and iteration == 1:
                candidate_solution = asset_aware_future_repack_candidate(
                    construction,
                    owners,
                    sources["prices"],
                    asset_states=cut.asset_states,
                    stage_start_second=trigger,
                    allow_cross_depot=allow_cross_depot,
                )
            elif not initial_feasible and iteration <= local_repair_limit and iteration % 2 == 0:
                candidate_solution = future_repack_candidate(
                    construction,
                    owners,
                    sources["prices"],
                    allow_cross_depot=allow_cross_depot,
                    rng=rng,
                )
            else:
                candidate_solution = event_insertion_candidate(
                    construction,
                    owners,
                    sources["prices"],
                    current,
                    initial_feasible,
                    stage_new_customer_ids=active_stage_new_customer_ids,
                    allow_cross_depot=allow_cross_depot,
                    rng=rng,
                )
            specialist_result, specialist_error = _evaluate_specialist_candidate_once(
                context,
                candidate_solution,
                lambda candidate: exact_candidate(
                    candidate,
                    construction,
                    sources,
                    cut,
                    trigger,
                ),
            )
            changed = candidate_solution is not None
            if changed:
                exact_check_count += 1
        else:
            outcome = apply_winner_action(
                current,
                WinnerOperatorAction(
                    destroy_op_id=destroy_id,
                    repair_op_id=repair_id,
                    remove_count_q=1 + ((iteration - 1) % 4),
                ),
                context,
                rng=rng,
                operator_set=operators,
                policy=policy,
                progress=(iteration - 1) / max(1, evaluations),
            )
            candidate_solution = outcome["candidate_solution"]
            changed = bool(outcome["changed"])
        accepted = improved_best = improves_current = False
        candidate_cost = math.inf
        if changed and candidate_solution is not None:
            changed_count += 1
            try:
                if specialist_used:
                    if specialist_error is not None:
                        raise specialist_error
                    if specialist_result is None:
                        raise RuntimeError("counted specialist candidate was not evaluated")
                    candidate_prepared, candidate_certificate, candidate_cost = specialist_result
                else:
                    exact_check_count += 1
                    candidate_prepared, candidate_certificate, candidate_cost = exact_candidate(
                        candidate_solution,
                        construction,
                        sources,
                        cut,
                        trigger,
                    )
                candidate_structure = normalized_search_solution(
                    candidate_prepared,
                    construction.effective_instance,
                    owners,
                )
                feasible_count += 1
                if _cross_site_ids_for_routes(
                    candidate_prepared.routes,
                    construction.effective_instance,
                    owners,
                ):
                    feasible_cross_candidate_count += 1
                eligible_for_best = (
                    True
                    if candidate_best_gate is None
                    else bool(
                        candidate_best_gate(
                            candidate_prepared,
                            candidate_certificate,
                            candidate_cost,
                        )
                    )
                )
                if not eligible_for_best:
                    best_gate_rejection_count += 1
                    if existing_cross_used:
                        existing_cross_gate_rejection_count += 1
                improves_current = candidate_cost <= current_cost
                temperature = max(1.0, (best_cost if math.isfinite(best_cost) else 1000.0) * 0.01)
                temperature *= 0.98 ** (iteration - 1)
                delta = candidate_cost - current_cost
                accepted = not math.isfinite(current_cost) or delta <= 0.0 or (
                    rng.random() < math.exp(-delta / max(temperature, 1e-9))
                )
                if accepted:
                    current = candidate_structure
                    current_prepared = candidate_prepared
                    current_certificate = candidate_certificate
                    current_cost = candidate_cost
                    accepted_count += 1
                    if existing_cross_used:
                        existing_cross_accepted_count += 1
                if eligible_for_best and candidate_cost < best_cost - 1e-9:
                    best_structure = candidate_structure
                    best_prepared = candidate_prepared
                    best_certificate = candidate_certificate
                    best_cost = candidate_cost
                    improved_best = True
                    if existing_cross_used:
                        existing_cross_best_improved_count += 1
            except ValueError as exc:
                dynamic_rejections[str(exc)] += 1
        reward = 5.0 if improved_best else 2.0 if accepted and improves_current else 1.0 if accepted else 0.1
        if not specialist_used:
            weights[pair_index] = 0.8 * weights[pair_index] + 0.2 * reward
    if context.budget is None or context.budget.count != evaluations:
        raise RuntimeError("stage evaluation count did not close")
    if existing_cross_actual_call_count != len(existing_cross_slots):
        raise RuntimeError("existing-customer reciprocal call schedule did not close")
    if best_prepared is None or best_certificate is None or not math.isfinite(best_cost):
        raise NoExecutableContinuation(
            "stage search found no executable continuation "
            f"(initial_feasible={initial_feasible}, changed={changed_count}, "
            f"executable={feasible_count}, accepted={accepted_count}, "
            f"top_rejections={dynamic_rejections.most_common(3)})"
        )
    return {
        "initial_solution": initial_prepared,
        "initial_certificate": initial_certificate,
        "initial_search_structure": initial_structure,
        "initial_cost": initial_cost,
        "solution": best_prepared,
        "certificate": best_certificate,
        "search_structure": best_structure,
        "future_cost": best_cost,
        "initial_feasible": initial_feasible,
        "type_trials": type_trials,
        "changed_count": changed_count,
        "feasible_count": feasible_count,
        "feasible_cross_candidate_count": feasible_cross_candidate_count,
        "forced_cross_attempt_count": forced_cross_attempt_count,
        "accepted_count": accepted_count,
        "best_gate_rejection_count": best_gate_rejection_count,
        "existing_cross_operator_id": EXISTING_CROSS_OPERATOR_ID,
        "existing_cross_scheduled_slots": list(existing_cross_slots),
        "existing_cross_scheduled_call_count": len(existing_cross_slots),
        "existing_cross_actual_call_count": existing_cross_actual_call_count,
        "existing_cross_pair_removal_count": existing_cross_pair_removal_count,
        "existing_cross_forced_insertion_count": existing_cross_forced_insertion_count,
        "existing_cross_within_depot_reinsert_count": (
            existing_cross_within_depot_reinsert_count
        ),
        "existing_cross_candidate_build_count": existing_cross_candidate_build_count,
        "existing_cross_changed_candidate_count": existing_cross_changed_candidate_count,
        "existing_cross_dynamic_feasible_count": existing_cross_dynamic_feasible_count,
        "existing_cross_gate_rejection_count": existing_cross_gate_rejection_count,
        "existing_cross_accepted_count": existing_cross_accepted_count,
        "existing_cross_best_improved_count": existing_cross_best_improved_count,
        "existing_cross_moved_customer_ids": sorted(existing_cross_moved_customer_ids),
        "existing_cross_rejections": dict(existing_cross_rejections),
        "exact_check_count": exact_check_count,
        "dynamic_rejections": dict(dynamic_rejections),
        "evaluations": evaluations,
        "elapsed_seconds": time.perf_counter() - started,
        "operator_pairs": [f"{destroy_id}+{repair_id}" for destroy_id, repair_id in pairs],
        "search_seed": seed,
    }


def _cross_site_ids_for_routes(
    routes: Sequence[Route],
    instance: Any,
    owners: Mapping[str, str],
) -> list[str]:
    return sorted(
        customer_id
        for route in routes
        for customer_id in p2.route_customers(route, instance)
        if owners.get(customer_id) != route.home_depot_id
    )


def _stage_evidence_payload(
    *,
    arm: str,
    stream_seed: int,
    stage_index: int,
    trigger: float,
    cut: Any,
    locked_routes: Sequence[Route],
    committed_customers: set[str],
    future_customers: Sequence[str],
    active_customers: set[str],
    solution: Solution,
    certificate: Any,
    cost_parts: Mapping[str, Any],
    dynamic_added_customer_ids: set[str],
    dynamic_added_cross_site_ids: set[str],
) -> dict[str, Any]:
    asset_states = {
        asset_id: asdict(state) for asset_id, state in sorted(cut.asset_states.items())
    }
    locked_route_payload = [asdict(route) for route in locked_routes]
    locked_action_payload = [asdict(action) for action in cut.locked_charging_actions]
    solution_payload = solution_to_dict(solution)
    certificate_payload = certificate.as_dict()
    committed_ids = sorted(committed_customers)
    future_ids = sorted(future_customers)
    active_ids = sorted(active_customers)
    return {
        "arm": arm,
        "stream_seed": stream_seed,
        "stage": stage_index,
        "trigger_second": trigger,
        "asset_states": asset_states,
        "asset_states_sha256": canonical_sha256(asset_states),
        "completed_route_ids": list(cut.completed_route_ids),
        "in_progress_route_ids": list(cut.in_progress_route_ids),
        "editable_route_ids": list(cut.editable_route_ids),
        "locked_routes": locked_route_payload,
        "locked_routes_sha256": canonical_sha256(locked_route_payload),
        "locked_charging_actions": locked_action_payload,
        "locked_charging_actions_sha256": canonical_sha256(locked_action_payload),
        "active_customer_ids": active_ids,
        "active_customer_ids_sha256": canonical_sha256(active_ids),
        "committed_customer_ids": committed_ids,
        "committed_customer_ids_sha256": canonical_sha256(committed_ids),
        "future_customer_ids": future_ids,
        "future_customer_ids_sha256": canonical_sha256(future_ids),
        "dynamic_added_customer_ids": sorted(dynamic_added_customer_ids),
        "dynamic_added_cross_site_customer_ids": sorted(dynamic_added_cross_site_ids),
        "solution": solution_payload,
        "solution_sha256": canonical_sha256(solution_payload),
        "certificate": certificate_payload,
        "certificate_sha256": canonical_sha256(certificate_payload),
        "certificate_status": certificate_payload.get("status"),
        "certificate_vehicle_counts": certificate_payload.get("vehicle_counts"),
        "cost_breakdown": {
            key: value
            for key, value in cost_parts.items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        },
    }


def run_session(
    arm: str,
    stream_seed: int,
    *,
    evaluations: int,
    max_stages: int | None,
    trigger_mode: str = "batched",
    stage_callback: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    sources = load_arm(arm)
    events, owners, event_path, owner_path = load_stream(stream_seed)
    if trigger_mode == "event":
        all_batches = [
            {
                "trigger_time": float(event.t_appear),
                "trigger_reason": "event",
                "events": [event],
            }
            for event in sorted(events, key=lambda item: (float(item.t_appear), str(item.event_id)))
        ]
    elif trigger_mode == "batched":
        all_batches = _validated_trigger_batches(stream_seed, events)
    else:
        raise ValueError(f"unknown trigger mode {trigger_mode}")
    batches = all_batches
    if max_stages is not None:
        batches = all_batches[:max_stages]
    current_solution = sources["solution"]
    current_certificate = sources["certificate"]
    current_instance = sources["bundle"].instance
    initial_parts = evaluate_parts(
        current_solution.routes,
        current_solution.charging_actions,
        current_instance,
        sources,
    )
    inherited_states = None
    inherited_locked_actions: Sequence[ChargingAction] = ()
    previous_stage_start = None
    committed_customers: set[str] = set()
    booked_route_ids: set[str] = set()
    booked_action_keys: set[tuple[Any, ...]] = set()
    committed = {}
    dynamic_added_customer_ids: set[str] = set()
    committed_dynamic_added_cross_site_ids: set[str] = set()
    stage_rows: list[dict[str, Any]] = []
    stage_evidence: list[dict[str, Any]] = []
    for stage_index, batch in enumerate(batches, start=1):
        stage_started = time.perf_counter()
        trigger = float(batch["trigger_time"])
        next_trigger = (
            float(all_batches[stage_index]["trigger_time"])
            if stage_index < len(all_batches)
            else None
        )
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
        locked_routes = gate._cut_routes(current_solution, locked_ids)
        new_routes = [route for route in locked_routes if route.vehicle_id not in booked_route_ids]
        add_breakdown(committed, evaluate_parts(new_routes, [], current_instance, sources))
        booked_route_ids.update(route.vehicle_id for route in new_routes)
        for route in new_routes:
            committed_customers.update(p2.route_customers(route, current_instance))
        committed_dynamic_added_cross_site_ids.update(
            set(_cross_site_ids_for_routes(new_routes, current_instance, owners))
            & dynamic_added_customer_ids
        )
        new_actions = [
            action
            for action in cut.locked_charging_actions
            if action_key(action) not in booked_action_keys
        ]
        add_breakdown(committed, evaluate_parts([], new_actions, current_instance, sources))
        booked_action_keys.update(action_key(action) for action in new_actions)

        construction = gate.build_open_stage(
            gate._cut_routes(current_solution, cut.editable_route_ids),
            current_instance,
            batch["events"],
            trigger,
            committed_customers,
            owners,
            sources["prices"],
            stage_index=stage_index,
            isolate_changed_customers=True,
        )
        event_ids, event_types, applied_event_ids, ignored_locked_event_ids = (
            _validate_stage_application(construction, batch["events"])
        )
        applied_set = set(applied_event_ids)
        dynamic_added_customer_ids.update(
            str(event.customer_id)
            for event in batch["events"]
            if str(event.event_id) in applied_set and str(event.event_type).lower() == "add"
        )
        result = search_stage(
            construction,
            sources,
            cut,
            owners,
            committed_customers,
            trigger=trigger,
            seed=stream_seed * 1000 + stage_index,
            evaluations=evaluations,
            allow_cross_depot=arm == "cooperative",
        )
        future_customers = [
            customer_id
            for route in result["solution"].routes
            for customer_id in p2.route_customers(route, construction.effective_instance)
        ]
        if len(future_customers) != len(set(future_customers)):
            raise RuntimeError("future plan contains a duplicate customer")
        active_customers = {
            node.node_id
            for node in construction.effective_instance.nodes
            if node.node_type.lower() == "c"
        }
        if committed_customers & set(future_customers):
            raise RuntimeError("a committed customer was planned again")
        if committed_customers | set(future_customers) != active_customers:
            raise RuntimeError("customer accounting did not close")
        if arm == "independent" and result["solution"].cross_site_services:
            raise RuntimeError("independent arm served a customer from the other depot")
        future_cross_site_ids = set(
            _cross_site_ids_for_routes(
                result["solution"].routes,
                construction.effective_instance,
                owners,
            )
        )
        stage_dynamic_added_cross_site_ids = (
            committed_dynamic_added_cross_site_ids
            | (future_cross_site_ids & dynamic_added_customer_ids)
        )
        future_parts = evaluate_parts(
            result["solution"].routes,
            result["solution"].charging_actions,
            construction.effective_instance,
            sources,
        )
        running_parts = dict(committed)
        add_breakdown(running_parts, future_parts)
        evidence = _stage_evidence_payload(
            arm=arm,
            stream_seed=stream_seed,
            stage_index=stage_index,
            trigger=trigger,
            cut=cut,
            locked_routes=locked_routes,
            committed_customers=committed_customers,
            future_customers=future_customers,
            active_customers=active_customers,
            solution=result["solution"],
            certificate=result["certificate"],
            cost_parts=running_parts,
            dynamic_added_customer_ids=dynamic_added_customer_ids,
            dynamic_added_cross_site_ids=stage_dynamic_added_cross_site_ids,
        )
        stage_evidence.append(evidence)
        elapsed_seconds = time.perf_counter() - stage_started
        available_compute_seconds, completed_before_next_trigger = _stage_timing(
            elapsed_seconds, trigger, next_trigger
        )
        stage_rows.append(
            {
                "arm": arm,
                "stream_seed": stream_seed,
                "stage": stage_index,
                "trigger_second": trigger,
                "trigger_reason": batch["trigger_reason"],
                "event_ids": ";".join(event_ids),
                "event_types": ";".join(event_types),
                "applied_event_ids": ";".join(applied_event_ids),
                "ignored_locked_event_ids": ";".join(ignored_locked_event_ids),
                "event_count": len(batch["events"]),
                "next_trigger_second": next_trigger,
                "available_compute_seconds": available_compute_seconds,
                "committed_route_count": len(booked_route_ids),
                "future_route_count": len(result["solution"].routes),
                "future_cost": result["future_cost"],
                "running_total_cost": committed.get("total_cost", 0.0) + result["future_cost"],
                "cross_site_customer_count": len(result["solution"].cross_site_services),
                "dynamic_added_customer_count": len(dynamic_added_customer_ids),
                "dynamic_added_cross_site_customer_count": len(
                    stage_dynamic_added_cross_site_ids
                ),
                "dynamic_added_cross_site_customer_ids": ";".join(
                    sorted(stage_dynamic_added_cross_site_ids)
                ),
                "active_customer_count": len(active_customers),
                "committed_customer_count": len(committed_customers),
                "future_customer_count": len(future_customers),
                "asset_state_count": len(cut.asset_states),
                "asset_states_sha256": evidence["asset_states_sha256"],
                "locked_routes_sha256": evidence["locked_routes_sha256"],
                "locked_charging_actions_sha256": evidence[
                    "locked_charging_actions_sha256"
                ],
                "active_customer_ids_sha256": evidence["active_customer_ids_sha256"],
                "committed_customer_ids_sha256": evidence[
                    "committed_customer_ids_sha256"
                ],
                "future_customer_ids_sha256": evidence["future_customer_ids_sha256"],
                "stage_solution_sha256": evidence["solution_sha256"],
                "stage_certificate_sha256": evidence["certificate_sha256"],
                "stage_certificate_status": evidence["certificate_status"],
                "initial_continuation_feasible": result["initial_feasible"],
                "initial_type_trial_count": result["type_trials"],
                "changed_candidate_count": result["changed_count"],
                "search_exact_check_count": result["exact_check_count"],
                "executable_candidate_count": result["feasible_count"],
                "feasible_cross_candidate_count": result[
                    "feasible_cross_candidate_count"
                ],
                "forced_new_customer_cross_attempt_count": result[
                    "forced_cross_attempt_count"
                ],
                "accepted_candidate_count": result["accepted_count"],
                "best_gate_rejection_count": result["best_gate_rejection_count"],
                "existing_cross_operator_id": result["existing_cross_operator_id"],
                "existing_cross_scheduled_slots": ";".join(
                    str(value) for value in result["existing_cross_scheduled_slots"]
                ),
                "existing_cross_scheduled_call_count": result[
                    "existing_cross_scheduled_call_count"
                ],
                "existing_cross_actual_call_count": result[
                    "existing_cross_actual_call_count"
                ],
                "existing_cross_pair_removal_count": result[
                    "existing_cross_pair_removal_count"
                ],
                "existing_cross_forced_insertion_count": result[
                    "existing_cross_forced_insertion_count"
                ],
                "existing_cross_within_depot_reinsert_count": result[
                    "existing_cross_within_depot_reinsert_count"
                ],
                "existing_cross_candidate_build_count": result[
                    "existing_cross_candidate_build_count"
                ],
                "existing_cross_changed_candidate_count": result[
                    "existing_cross_changed_candidate_count"
                ],
                "existing_cross_dynamic_feasible_count": result[
                    "existing_cross_dynamic_feasible_count"
                ],
                "existing_cross_gate_rejection_count": result[
                    "existing_cross_gate_rejection_count"
                ],
                "existing_cross_accepted_count": result[
                    "existing_cross_accepted_count"
                ],
                "existing_cross_best_improved_count": result[
                    "existing_cross_best_improved_count"
                ],
                "existing_cross_moved_customer_ids": ";".join(
                    result["existing_cross_moved_customer_ids"]
                ),
                "existing_cross_rejection_counts_json": json.dumps(
                    result["existing_cross_rejections"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "search_rejection_counts_json": json.dumps(
                    result["dynamic_rejections"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "evaluations": result["evaluations"],
                "stage_search_seed": result["search_seed"],
                "operator_pairs": ";".join(result["operator_pairs"]),
                "elapsed_seconds": elapsed_seconds,
                "completed_before_next_trigger": completed_before_next_trigger,
                "customer_accounting_pass": True,
            }
        )
        if stage_callback is not None:
            stage_callback(dict(stage_rows[-1]))
        if completed_before_next_trigger is False:
            raise RuntimeError(
                f"stage {stage_index} did not finish before the next trigger: "
                f"elapsed={elapsed_seconds}, available={available_compute_seconds}"
            )
        inherited_states = cut.asset_states
        inherited_locked_actions = cut.locked_charging_actions
        previous_stage_start = trigger
        current_solution = result["solution"]
        current_certificate = result["certificate"]
        current_instance = construction.effective_instance

    remaining_actions = [
        action
        for action in current_solution.charging_actions
        if action_key(action) not in booked_action_keys
    ]
    remaining = evaluate_parts(
        current_solution.routes,
        remaining_actions,
        current_instance,
        sources,
    )
    final = dict(committed)
    add_breakdown(final, remaining)
    final_dynamic_added_cross_site_ids = committed_dynamic_added_cross_site_ids | (
        set(_cross_site_ids_for_routes(current_solution.routes, current_instance, owners))
        & dynamic_added_customer_ids
    )
    return {
        "arm": arm,
        "stream_seed": stream_seed,
        "stages": len(stage_rows),
        "evaluations_per_stage": evaluations,
        "total_evaluations": evaluations * len(stage_rows),
        "final_total_cost": final.get("total_cost", 0.0),
        "final_total_emissions": final.get("E_total", 0.0),
        "final_cross_site_customer_count": len(current_solution.cross_site_services),
        "final_dynamic_added_cross_site_customer_count": len(
            final_dynamic_added_cross_site_ids
        ),
        "final_dynamic_added_cross_site_customer_ids": ";".join(
            sorted(final_dynamic_added_cross_site_ids)
        ),
        "customer_accounting_pass": True,
        "event_path": str(event_path.relative_to(ROOT)),
        "event_sha256": sha256(event_path),
        "owner_path": str(owner_path.relative_to(ROOT)),
        "owner_sha256": sha256(owner_path),
        "initial_solution_path": str(sources["solution_path"].relative_to(ROOT)),
        "initial_solution_sha256": sha256(sources["solution_path"]),
        "initial_certificate_path": str(sources["certificate_path"].relative_to(ROOT)),
        "initial_certificate_sha256": sha256(sources["certificate_path"]),
        "initial_total_cost": float(initial_parts["total_cost"]),
        "initial_total_emissions": float(initial_parts["E_total"]),
        "initial_route_count": len(sources["solution"].routes),
        "initial_charging_action_count": len(sources["solution"].charging_actions),
        "initial_cross_site_customer_count": len(sources["solution"].cross_site_services),
        "stage_rows": stage_rows,
        "stage_evidence": stage_evidence,
        "final_solution": solution_to_dict(current_solution),
        "final_certificate": current_certificate.as_dict(),
        "trigger_mode": trigger_mode,
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    fieldnames: Sequence[str] | None = None,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        columns = list(fieldnames or (list(rows[0]) if rows else ["status"]))
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def paired_contract_matches(
    cooperative: Mapping[str, Any],
    independent: Mapping[str, Any],
    cooperative_stages: Sequence[Mapping[str, Any]],
    independent_stages: Sequence[Mapping[str, Any]],
) -> bool:
    return (
        cooperative["initial_solution_sha256"]
        == independent["initial_solution_sha256"]
        and cooperative["initial_certificate_sha256"]
        == independent["initial_certificate_sha256"]
        and cooperative["event_sha256"] == independent["event_sha256"]
        and cooperative["owner_sha256"] == independent["owner_sha256"]
        and [
            (
                row["stage"],
                row["stage_search_seed"],
                row["evaluations"],
                row["operator_pairs"],
                row.get("existing_cross_operator_id", EXISTING_CROSS_OPERATOR_ID),
                row.get("existing_cross_scheduled_slots", ""),
                row.get("existing_cross_scheduled_call_count", 0),
                row.get("existing_cross_actual_call_count", 0),
            )
            for row in cooperative_stages
        ]
        == [
            (
                row["stage"],
                row["stage_search_seed"],
                row["evaluations"],
                row["operator_pairs"],
                row.get("existing_cross_operator_id", EXISTING_CROSS_OPERATOR_ID),
                row.get("existing_cross_scheduled_slots", ""),
                row.get("existing_cross_scheduled_call_count", 0),
                row.get("existing_cross_actual_call_count", 0),
            )
            for row in independent_stages
        ]
    )


def write_artifacts(
    output: Path,
    sessions: list[dict[str, Any]],
    args: argparse.Namespace,
    *,
    failures: Sequence[Mapping[str, Any]] = (),
    partial_stage_rows: Sequence[Mapping[str, Any]] = (),
    run_start_commit: str,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for old in output.iterdir():
        if old.is_file():
            old.unlink()
    stage_rows = [
        *[row for session in sessions for row in session["stage_rows"]],
        *partial_stage_rows,
    ]
    solution_dir = output / "solutions"
    certificate_dir = output / "certificates"
    evidence_dir = output / "stage_evidence"
    for directory in (solution_dir, certificate_dir, evidence_dir):
        directory.mkdir(parents=True, exist_ok=True)
        for old in directory.iterdir():
            if old.is_file():
                old.unlink()
    summary_rows = []
    for session in sessions:
        stem = f"stream{session['stream_seed']}__{session['arm']}"
        solution_path = solution_dir / f"{stem}.json"
        certificate_path = certificate_dir / f"{stem}.json"
        evidence_path = evidence_dir / f"{stem}.json"
        write_json(solution_path, session["final_solution"])
        write_json(certificate_path, session["final_certificate"])
        write_json(evidence_path, session["stage_evidence"])
        excluded = {"stage_rows", "stage_evidence", "final_solution", "final_certificate"}
        row = {key: value for key, value in session.items() if key not in excluded}
        row.update(
            {
                "final_solution_path": str(solution_path.relative_to(ROOT)),
                "final_solution_sha256": sha256(solution_path),
                "final_certificate_path": str(certificate_path.relative_to(ROOT)),
                "final_certificate_sha256": sha256(certificate_path),
                "stage_evidence_path": str(evidence_path.relative_to(ROOT)),
                "stage_evidence_sha256": sha256(evidence_path),
            }
        )
        summary_rows.append(row)
    write_csv(output / "raw_runs.csv", stage_rows)
    write_csv(output / "session_summary.csv", summary_rows)
    recorded_failures = [dict(row) for row in failures]
    pairs: list[dict[str, Any]] = []
    by_seed = {(row["stream_seed"], row["arm"]): row for row in summary_rows}
    for seed in sorted({row["stream_seed"] for row in summary_rows}):
        cooperative = by_seed.get((seed, "cooperative"))
        independent = by_seed.get((seed, "independent"))
        if not cooperative or not independent:
            continue
        cooperative_stages = sorted(
            (
                row
                for row in stage_rows
                if row["stream_seed"] == seed and row["arm"] == "cooperative"
            ),
            key=lambda row: row["stage"],
        )
        independent_stages = sorted(
            (
                row
                for row in stage_rows
                if row["stream_seed"] == seed and row["arm"] == "independent"
            ),
            key=lambda row: row["stage"],
        )
        paired_contract = paired_contract_matches(
            cooperative,
            independent,
            cooperative_stages,
            independent_stages,
        )
        if not paired_contract:
            recorded_failures.append(
                {
                    "stream_seed": seed,
                    "arm": "paired_contract",
                    "completed_stage_count": min(
                        len(cooperative_stages), len(independent_stages)
                    ),
                    "error_type": "PairedContractMismatch",
                    "error": "shared start, frozen inputs, stage seeds, budgets, operator menus, or fixed call schedules differ",
                }
            )
            continue
        saving = 100.0 * (
            independent["final_total_cost"] - cooperative["final_total_cost"]
        ) / independent["final_total_cost"]
        pairs.append(
            {
                "stream_seed": seed,
                "cooperative_total_cost": cooperative["final_total_cost"],
                "independent_total_cost": independent["final_total_cost"],
                "cooperative_saving_percent": saving,
                "cooperative_total_emissions": cooperative["final_total_emissions"],
                "independent_total_emissions": independent["final_total_emissions"],
            }
        )
    write_csv(output / "paired_summary.csv", pairs)
    if recorded_failures:
        write_csv(output / "failures.csv", recorded_failures)
    timing_pass = all(
        row.get("completed_before_next_trigger") is True
        for row in stage_rows
        if row.get("next_trigger_second") not in (None, "")
    )
    passed = (
        not recorded_failures
        and len(summary_rows) == 2 * len(args.streams)
        and all(row["customer_accounting_pass"] for row in summary_rows)
        and timing_pass
    )
    formal_scope = (
        args.all_stages
        and set(args.streams) == {1, 2, 3, 4, 5}
        and args.trigger_mode == "batched"
    )
    verdict = (
        "E7_PAIRED_FORMAL_PASS"
        if passed and formal_scope
        else "E7_PAIRED_PREFLIGHT_PASS"
        if passed
        else "HALT_E7_PAIRED_DYNAMIC_VALUE"
    )
    metadata = {
        "contract_id": CONTRACT_ID,
        "scope": "formal" if formal_scope else "preflight",
        "network": "L-main-threeshift-100c-01",
        "customer_count": 221,
        "fleet": {"cv": 10, "ev": 10},
        "arms": ["cooperative", "independent"],
        "streams": args.streams,
        "evaluations_per_stage": args.evaluations,
        "maximum_stages": None if args.all_stages else args.max_stages,
        "trigger_mode": args.trigger_mode,
        "q_bar": ROLLING_PARAMETERS.q_bar,
        "delta_t": ROLLING_PARAMETERS.delta_t_seconds,
        "delta_t_seconds": ROLLING_PARAMETERS.delta_t_seconds,
        "workers": args.workers,
        "run_start_commit": run_start_commit,
        "artifact_write_commit": source_commit(),
        "source_commit": run_start_commit,
        "shared_initial_plan": True,
        "treatment_difference": "cross-depot service permission only",
        "existing_customer_neighborhood": {
            "operator_id": EXISTING_CROSS_OPERATOR_ID,
            "interval_evaluations": EXISTING_CROSS_INTERVAL,
            "cooperative_action": "reciprocal cross-depot reinsert",
            "independent_action": "changed within-depot reinsert",
            "stage_new_customers_excluded": True,
            "complete_candidate_checker": "dynamic inherited-asset scheduler",
        },
        "result_direction_used_to_continue": False,
        "failure_count": len(recorded_failures),
        "interpretation_limit": (
            "Formal conclusions use all frozen stages of all five streams."
            if formal_scope
            else "This is a partial preflight. Formal conclusions require all frozen stages of all five streams."
        ),
    }
    write_json(output / "metadata.json", metadata)
    decision = {
        "verdict": verdict,
        "passed": passed,
        "session_count": len(summary_rows),
        "paired_stream_count": len(pairs),
        "failure_count": len(recorded_failures),
        "zero_customer_loss": all(row["customer_accounting_pass"] for row in summary_rows),
        "applied_event_count": sum(
            len([value for value in str(row.get("applied_event_ids", "")).split(";") if value])
            for row in stage_rows
        ),
        "locked_late_event_count": sum(
            len([value for value in str(row.get("ignored_locked_event_ids", "")).split(";") if value])
            for row in stage_rows
        ),
        "all_stages_completed_before_next_trigger": timing_pass,
        "boundary": metadata["interpretation_limit"],
    }
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(
        "\n".join(
            [
                "# E7 两种经营方式的动态短检查",
                "",
                f"判决：`{verdict}`。",
                "",
                f"本轮运行订单流 {args.streams} 的"
                f"{'全部调整批次' if args.all_stages else f'前 {args.max_stages} 批事件'}，"
                f"每次调整各比较 {args.evaluations} 个方案。合作经营与各自经营使用相同订单流和相同次数。",
                "",
                "已发车安排不撤回，车辆可用时刻、电量和已开始充电均向后继承；"
                "每批事件调整后，已执行与待执行客户合计恰好覆盖当时有效订单。",
                (
                    "本轮覆盖五条冻结订单流的全部调整批次，机械检查通过后方可作为正式动态证据。"
                    if formal_scope
                    else "本轮只决定能否进入完整五条订单流，不形成论文结论。"
                ),
                *( ["", f"中途停止 {len(recorded_failures)} 组，原因见 failures.csv；停止前已经完成的阶段保留在 raw_runs.csv。"] if recorded_failures else [] ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts = [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    ]
    write_json(
        output / "artifact_hashes.json",
        {"algorithm": "sha256", "excluded": ["artifact_hashes.json", "._*"], "artifacts": artifacts},
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--streams", type=int, nargs="+", default=[1])
    parser.add_argument("--evaluations", type=int, default=100)
    parser.add_argument("--max-stages", type=int, default=2)
    parser.add_argument("--all-stages", action="store_true")
    parser.add_argument("--trigger-mode", choices=("event", "batched"), default="batched")
    parser.add_argument("--workers", type=int, choices=tuple(range(1, 9)), default=2)
    return parser.parse_args()


def run_session_captured(task: tuple[str, int, int, int | None, str]) -> dict[str, Any]:
    arm, seed, evaluations, max_stages, trigger_mode = task
    progress: list[dict[str, Any]] = []
    try:
        session = run_session(
            arm,
            seed,
            evaluations=evaluations,
            max_stages=max_stages,
            trigger_mode=trigger_mode,
            stage_callback=progress.append,
        )
        return {"session": session, "failure": None, "partial": []}
    except Exception as exc:
        return {
            "session": None,
            "failure": {
                "stream_seed": seed,
                "arm": arm,
                "completed_stage_count": len(progress),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
            "partial": progress,
        }


def main() -> None:
    args = parse_args()
    run_start_commit = source_commit()
    tasks = [
        (
            arm,
            seed,
            args.evaluations,
            None if args.all_stages else args.max_stages,
            args.trigger_mode,
        )
        for seed in args.streams
        for arm in ("cooperative", "independent")
    ]
    if args.workers == 1:
        captured = [run_session_captured(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            captured = list(executor.map(run_session_captured, tasks))
    sessions = [row["session"] for row in captured if row["session"] is not None]
    failures = [row["failure"] for row in captured if row["failure"] is not None]
    partial_rows = [stage for row in captured for stage in row["partial"]]
    write_artifacts(
        args.output.resolve(),
        sessions,
        args,
        failures=failures,
        partial_stage_rows=partial_rows,
        run_start_commit=run_start_commit,
    )


if __name__ == "__main__":
    main()
