#!/usr/bin/env python3
"""Paired dynamic-value experiment on the frozen 221-customer network."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
import csv
from dataclasses import replace
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
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerOperatorAction,
    WinnerOperatorSet,
    apply_winner_action,
)
from setp_solver.cost import evaluate
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.dynamic import DynamicEvent, RollingParameters, _build_trigger_batches
from setp_solver.search.dynamic_multitrip_schedule import (
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    prepare_dynamic_multitrip_solution,
)
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.search.metaheuristic_baselines import solution_from_dict
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
CONTRACT_ID = "E7_PAIRED_DYNAMIC_VALUE_V2_BATCHED"
ROLLING_PARAMETERS = RollingParameters()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()


def arm_case(arm: str) -> str:
    suffix = "no_loss" if arm == "cooperative" else "independent"
    return f"L-main-threeshift-100c-01__geographic__seed1__{suffix}"


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


def event_insertion_candidate(
    construction: gate.StageConstruction,
    owners: dict[str, str],
    prices: Any,
    base_solution: Solution,
    preserve_event_types: bool,
    *,
    allow_cross_depot: bool,
    rng: np.random.Generator,
) -> Solution | None:
    """Reinsert the current event customers into existing open routes."""

    event_routes = [
        route for route in construction.solution.routes if "_ADD_" in route.vehicle_id
    ]
    pending = [
        customer_id
        for route in event_routes
        for customer_id in p2.route_customers(route, construction.effective_instance)
    ]
    if not pending:
        return None
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
        options: list[tuple[float, str, int, Route]] = []
        for route in routes:
            if not allow_cross_depot and route.home_depot_id != owners[customer_id]:
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
                        route.vehicle_id,
                        insert_at,
                        candidate,
                    )
                )
        if not options or rng.random() < 0.5:
            source = event_route_by_customer[customer_id]
            routes.append(
                replace(
                    source,
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
        selected = choice_pool[int(rng.integers(0, len(choice_pool)))][3]
        routes = [
            selected if route.vehicle_id == selected.vehicle_id else route
            for route in routes
        ]
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
        allow_cross_depot=allow_cross_depot,
    )
    pairs = [
        (destroy_id, repair_id)
        for destroy_id, _ in operators.destroy_ops
        for repair_id, _ in operators.repair_ops
    ]
    weights = np.ones(len(pairs), dtype=float)
    rng = np.random.default_rng(seed)
    best_structure = current
    best_prepared = current_prepared
    best_certificate = current_certificate
    best_cost = current_cost
    changed_count = feasible_count = accepted_count = 0
    dynamic_rejections: Counter[str] = Counter()
    for iteration in range(1, evaluations + 1):
        pair_index = int(rng.choice(len(pairs), p=weights / weights.sum()))
        destroy_id, repair_id = pairs[pair_index]
        local_repair_limit = min(400, max(50, evaluations // 2))
        has_isolated_event = any(
            "_ADD_" in route.vehicle_id for route in construction.solution.routes
        )
        specialist_used = has_isolated_event and (
            iteration <= local_repair_limit or not initial_feasible
        )
        if specialist_used:
            if not initial_feasible and iteration <= local_repair_limit and iteration % 2 == 0:
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
                    allow_cross_depot=allow_cross_depot,
                    rng=rng,
                )
            assert context.budget is not None
            context.budget.record()
            context.score_counts["candidate"] = int(context.score_counts.get("candidate", 0)) + 1
            changed = candidate_solution is not None
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
                candidate_prepared, candidate_certificate, candidate_cost = exact_candidate(
                    candidate_solution,
                    construction,
                    sources,
                    cut,
                    trigger,
                )
                feasible_count += 1
                improves_current = candidate_cost <= current_cost
                temperature = max(1.0, (best_cost if math.isfinite(best_cost) else 1000.0) * 0.01)
                temperature *= 0.98 ** (iteration - 1)
                delta = candidate_cost - current_cost
                accepted = not math.isfinite(current_cost) or delta <= 0.0 or (
                    rng.random() < math.exp(-delta / max(temperature, 1e-9))
                )
                if accepted:
                    current = candidate_solution
                    current_prepared = candidate_prepared
                    current_certificate = candidate_certificate
                    current_cost = candidate_cost
                    accepted_count += 1
                if candidate_cost < best_cost - 1e-9:
                    best_structure = candidate_solution
                    best_prepared = candidate_prepared
                    best_certificate = candidate_certificate
                    best_cost = candidate_cost
                    improved_best = True
            except ValueError as exc:
                dynamic_rejections[str(exc)] += 1
        reward = 5.0 if improved_best else 2.0 if accepted and improves_current else 1.0 if accepted else 0.1
        if not specialist_used:
            weights[pair_index] = 0.8 * weights[pair_index] + 0.2 * reward
    if context.budget is None or context.budget.count != evaluations:
        raise RuntimeError("stage evaluation count did not close")
    if best_prepared is None or best_certificate is None or not math.isfinite(best_cost):
        raise RuntimeError(
            "stage search found no executable continuation "
            f"(initial_feasible={initial_feasible}, changed={changed_count}, "
            f"executable={feasible_count}, accepted={accepted_count}, "
            f"top_rejections={dynamic_rejections.most_common(3)})"
        )
    return {
        "solution": best_prepared,
        "certificate": best_certificate,
        "search_structure": best_structure,
        "future_cost": best_cost,
        "initial_feasible": initial_feasible,
        "type_trials": type_trials,
        "changed_count": changed_count,
        "feasible_count": feasible_count,
        "accepted_count": accepted_count,
        "dynamic_rejections": dict(dynamic_rejections),
        "evaluations": evaluations,
        "elapsed_seconds": time.perf_counter() - started,
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
    inherited_states = None
    inherited_locked_actions: Sequence[ChargingAction] = ()
    previous_stage_start = None
    committed_customers: set[str] = set()
    booked_route_ids: set[str] = set()
    booked_action_keys: set[tuple[Any, ...]] = set()
    committed = {}
    stage_rows: list[dict[str, Any]] = []
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
                "initial_continuation_feasible": result["initial_feasible"],
                "changed_candidate_count": result["changed_count"],
                "executable_candidate_count": result["feasible_count"],
                "accepted_candidate_count": result["accepted_count"],
                "evaluations": result["evaluations"],
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
    return {
        "arm": arm,
        "stream_seed": stream_seed,
        "stages": len(stage_rows),
        "evaluations_per_stage": evaluations,
        "total_evaluations": evaluations * len(stage_rows),
        "final_total_cost": final.get("total_cost", 0.0),
        "final_total_emissions": final.get("E_total", 0.0),
        "final_cross_site_customer_count": len(current_solution.cross_site_services),
        "customer_accounting_pass": True,
        "event_path": str(event_path.relative_to(ROOT)),
        "event_sha256": sha256(event_path),
        "owner_path": str(owner_path.relative_to(ROOT)),
        "owner_sha256": sha256(owner_path),
        "initial_solution_path": str(sources["solution_path"].relative_to(ROOT)),
        "initial_solution_sha256": sha256(sources["solution_path"]),
        "initial_certificate_path": str(sources["certificate_path"].relative_to(ROOT)),
        "initial_certificate_sha256": sha256(sources["certificate_path"]),
        "stage_rows": stage_rows,
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


def write_artifacts(
    output: Path,
    sessions: list[dict[str, Any]],
    args: argparse.Namespace,
    *,
    failures: Sequence[Mapping[str, Any]] = (),
    partial_stage_rows: Sequence[Mapping[str, Any]] = (),
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for old in output.iterdir():
        if old.is_file():
            old.unlink()
    stage_rows = [
        *[row for session in sessions for row in session["stage_rows"]],
        *partial_stage_rows,
    ]
    summary_rows = [
        {key: value for key, value in session.items() if key != "stage_rows"}
        for session in sessions
    ]
    write_csv(output / "raw_runs.csv", stage_rows)
    write_csv(output / "session_summary.csv", summary_rows)
    if failures:
        write_csv(output / "failures.csv", failures)
    pairs: list[dict[str, Any]] = []
    by_seed = {(row["stream_seed"], row["arm"]): row for row in summary_rows}
    for seed in sorted({row["stream_seed"] for row in summary_rows}):
        cooperative = by_seed.get((seed, "cooperative"))
        independent = by_seed.get((seed, "independent"))
        if not cooperative or not independent:
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
    timing_pass = all(
        row.get("completed_before_next_trigger") is True
        for row in stage_rows
        if row.get("next_trigger_second") not in (None, "")
    )
    passed = (
        not failures
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
        "source_commit": source_commit(),
        "result_direction_used_to_continue": False,
        "failure_count": len(failures),
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
        "failure_count": len(failures),
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
                *( ["", f"中途停止 {len(failures)} 组，原因见 failures.csv；停止前已经完成的阶段保留在 raw_runs.csv。"] if failures else [] ),
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
        for path in sorted(output.iterdir())
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
    )


if __name__ == "__main__":
    main()
