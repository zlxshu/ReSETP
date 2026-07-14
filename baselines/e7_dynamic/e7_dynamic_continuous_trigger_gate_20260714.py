#!/usr/bin/env python3
"""Zero-search two-trigger gate for the E7 exact-asset continuation.

The gate uses the first two non-empty trigger batches from the frozen seed-1
event stream.  It never calls ALNS or any other route search.  New or changed
customers start as separate trips, and a bounded check chooses only the trip's
vehicle type.  The exact inherited-asset scheduler either certifies both
continuations or the gate records a halt.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, replace
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from baselines.e3_ablation import e3_v3_runner as legacy
from setp_solver.instance_loader import Instance, Node
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.certificate_execution import build_certificate_execution_ledger
from setp_solver.search.dynamic import (
    DynamicEvent,
    RollingParameters,
    _build_trigger_batches,
    _instance_after_events,
)
from setp_solver.search.dynamic_multitrip_schedule import (
    CertificateCut,
    DynamicAssetState,
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    prepare_dynamic_multitrip_solution,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import (
    MultiTripCertificate,
    ScheduledTrip,
    route_timing,
)
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


ROOT = Path(__file__).resolve().parents[2]
FORMAL_BUNDLE = (
    ROOT
    / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets"
    / "L-main-threeshift-100c-01/bundle"
)
E6_ROOT = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
CASE = "L-main-threeshift-100c-01__geographic__seed1__no_loss"
EVENT_ROOT = ROOT / "baselines/e7_dynamic/e7_v2_20260714/event_streams"
EVENT_PATH = EVENT_ROOT / "stream_seed1.events.json"
OWNER_PATH = EVENT_ROOT / "stream_seed1.owners.csv"
EVENT_DECISION_PATH = EVENT_ROOT / "decision.json"
DEFAULT_OUTPUT = ROOT / "baselines/e7_dynamic/e7_dynamic_continuous_trigger_gate_20260714"

CONTRACT_ID = "E7_DYNAMIC_CONTINUOUS_TRIGGER_GATE_V1"
PASS_VERDICT = "E7_DYNAMIC_CONTINUOUS_TRIGGER_GATE_PASS"
HALT_VERDICT = "HALT_E7_DYNAMIC_CONTINUOUS_TRIGGER_GATE"
FORMAL_INSTANCE_SHA256 = "59696be304ad9f3c484820439e1cbdb027945e20ad7ecbdb8542dfde7e0d6225"
FORMAL_SOLUTION_SHA256 = "eff30569aea5953b8b9b52707e6f15bb7c1f44f3b17f3bea7bda334e389e62af"
FORMAL_CERTIFICATE_SHA256 = "7127dada4e9942a303155429fb42f83cc6c6952a344d4c8a5d9c4727f5e919d0"
REJECTED_OLD_EVENT_STREAM_SHA256 = "bbc2a6fe2cdff9871848e744c88f71d4d1f3edbae13d35b7f759c282dfb2896b"
DEPARTURE_MARGIN_SECONDS = 60.0
SEARCH_EVALUATIONS = 0
_TOL = 1e-6


@dataclass(frozen=True)
class StageConstruction:
    solution: Solution
    effective_instance: Instance
    applied_event_ids: tuple[str, ...]
    ignored_locked_event_ids: tuple[str, ...]
    feasibility_check_count: int


def prepare_stage_with_singleton_type_choices(
    construction: StageConstruction,
    prices: Any,
    *,
    asset_states: Mapping[str, DynamicAssetState],
    stage_start_second: float,
    locked_charging_actions: Sequence[ChargingAction],
) -> tuple[Solution, MultiTripCertificate, int]:
    """Choose a feasible vehicle type for separate event trips, without scoring plans."""

    singleton_ids = sorted(
        route.vehicle_id
        for route in construction.solution.routes
        if "_ADD_" in route.vehicle_id
    )
    choices = list(itertools.product(("cv", "ev"), repeat=len(singleton_ids)))
    choices.sort(key=lambda item: (item.count("ev"), item))
    if len(choices) > 4096:
        raise RuntimeError("too many separate event trips for the bounded feasibility check")
    last_error: ValueError | None = None
    for attempt, vehicle_types in enumerate(choices, start=1):
        selected = dict(zip(singleton_ids, vehicle_types, strict=True))
        candidate = replace(
            construction.solution,
            routes=[
                replace(route, vehicle_type=selected.get(route.vehicle_id, route.vehicle_type))
                for route in construction.solution.routes
            ],
        )
        try:
            plan, certificate = prepare_dynamic_multitrip_solution(
                candidate,
                construction.effective_instance,
                prices,
                asset_states=asset_states,
                stage_start_second=stage_start_second,
                locked_charging_actions=locked_charging_actions,
            )
            return plan, certificate, attempt
        except ValueError as exc:
            last_error = exc
    raise RuntimeError(f"no feasible vehicle type assignment for separate event trips: {last_error}")


@dataclass(frozen=True)
class HistorySnapshot:
    source_stage: int
    route_id: str
    signature: str
    customer_ids: tuple[str, ...]
    route: Route


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def route_signature(route: Route) -> str:
    return canonical_sha256(
        {
            "route_id": route.vehicle_id,
            "vehicle_type": route.vehicle_type.lower(),
            "home_depot_id": route.home_depot_id,
            "node_sequence": list(route.node_sequence),
        }
    )


def action_signature(action: ChargingAction) -> str:
    return canonical_sha256(asdict(action))


def load_certificate(path: Path) -> MultiTripCertificate:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={str(key): int(value) for key, value in payload["vehicle_counts"].items()},
        trips=tuple(ScheduledTrip(**row) for row in payload["trips"]),
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
        first_trip_charge_day_offset=int(payload.get("first_trip_charge_day_offset", -1)),
    )


def load_owners() -> dict[str, str]:
    with OWNER_PATH.open(newline="", encoding="utf-8") as handle:
        return {
            str(row["customer_id"]): str(row["owner_depot_id"])
            for row in csv.DictReader(handle)
        }


def _departure_gate_from_stream_decision() -> dict[str, Any]:
    payload = json.loads(EVENT_DECISION_PATH.read_text(encoding="utf-8"))
    boolean_checks = {
        "all_existing_events_modifiable_in_both_fixed_seed1_plans": payload.get(
            "all_existing_events_modifiable_in_both_fixed_seed1_plans"
        )
    }
    margin_checks = {
        "minimum_existing_event_uncommitted_margin_seconds": float(
            payload.get("minimum_existing_event_uncommitted_margin_seconds", 0.0)
        )
    }
    if not boolean_checks or not all(boolean_checks.values()):
        raise RuntimeError("event stream has no passing route-departure gate")
    if not margin_checks or min(margin_checks.values()) < DEPARTURE_MARGIN_SECONDS - _TOL:
        raise RuntimeError("event stream route-departure margin is below 60 seconds")
    return {
        "decision": payload,
        "boolean_checks": boolean_checks,
        "margin_checks": margin_checks,
    }


def load_sources() -> dict[str, Any]:
    instance_path = FORMAL_BUNDLE / "instance.json"
    solution_path = E6_ROOT / "solutions" / f"{CASE}.json"
    certificate_path = E6_ROOT / "certificates" / f"{CASE}.json"
    expected_hashes = {
        instance_path: FORMAL_INSTANCE_SHA256,
        solution_path: FORMAL_SOLUTION_SHA256,
        certificate_path: FORMAL_CERTIFICATE_SHA256,
    }
    for path, expected in expected_hashes.items():
        observed = sha256(path)
        if observed != expected:
            raise RuntimeError(f"frozen input hash drifted: {path}; {observed} != {expected}")
    event_sha = sha256(EVENT_PATH)
    if event_sha == REJECTED_OLD_EVENT_STREAM_SHA256:
        raise RuntimeError("refusing the superseded event stream that did not lock route departures")
    departure_gate = _departure_gate_from_stream_decision()

    bundle = load_search_bundle(FORMAL_BUNDLE)
    if sum(node.node_type.lower() == "c" for node in bundle.instance.nodes) != 221:
        raise RuntimeError("formal gate input is not the frozen 221-customer network")
    if (bundle.instance.num_cv, bundle.instance.num_ev) != (10, 10):
        raise RuntimeError("formal gate input is not the frozen 10+10 fleet")
    solution = solution_from_dict(json.loads(solution_path.read_text(encoding="utf-8")))
    certificate = load_certificate(certificate_path)
    prices = legacy.prices_for("M1", 0.0)
    ledger = build_certificate_execution_ledger(
        solution,
        certificate,
        bundle.instance,
        prices,
    )
    if len(ledger.assets) != 20:
        raise RuntimeError("the frozen certificate does not expose all 20 physical assets")

    events = [
        DynamicEvent(**row)
        for row in json.loads(EVENT_PATH.read_text(encoding="utf-8"))
    ]
    batches = [
        batch
        for batch in _build_trigger_batches(events, RollingParameters())
        if batch["events"]
    ]
    if len(batches) < 2:
        raise RuntimeError("seed-1 event stream has fewer than two real trigger batches")
    if not float(batches[0]["trigger_time"]) < float(batches[1]["trigger_time"]):
        raise RuntimeError("the first two real triggers are not strictly ordered")
    return {
        "bundle": bundle,
        "solution": solution,
        "certificate": certificate,
        "prices": prices,
        "ledger": ledger,
        "owners": load_owners(),
        "events": events,
        "batches": batches[:2],
        "departure_gate": departure_gate,
        "paths": {
            "instance": instance_path,
            "solution": solution_path,
            "certificate": certificate_path,
            "events": EVENT_PATH,
            "owners": OWNER_PATH,
            "event_decision": EVENT_DECISION_PATH,
        },
    }


def customer_ids(route: Route, instance: Instance) -> tuple[str, ...]:
    lookup = {node.node_id: node for node in instance.nodes}
    return tuple(
        node_id
        for node_id in route.node_sequence
        if node_id in lookup and lookup[node_id].node_type.lower() == "c"
    )


def active_customer_ids(instance: Instance) -> set[str]:
    return {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() == "c" and float(node.demand) > _TOL
    }


def history_customer_ids(history: Sequence[HistorySnapshot]) -> set[str]:
    return {customer_id for snapshot in history for customer_id in snapshot.customer_ids}


def add_history_routes(
    history: list[HistorySnapshot],
    routes: Iterable[Route],
    instance: Instance,
    *,
    source_stage: int,
) -> None:
    existing = {(item.source_stage, item.route_id) for item in history}
    for route in routes:
        key = (source_stage, route.vehicle_id)
        if key in existing:
            continue
        history.append(
            HistorySnapshot(
                source_stage=source_stage,
                route_id=route.vehicle_id,
                signature=route_signature(route),
                customer_ids=customer_ids(route, instance),
                route=route,
            )
        )
        existing.add(key)


def history_is_immutable(history: Sequence[HistorySnapshot]) -> bool:
    return all(route_signature(item.route) == item.signature for item in history)


def _route_load(route: Route, instance: Instance) -> float:
    lookup = {node.node_id: node for node in instance.nodes}
    return sum(
        float(lookup[node_id].demand)
        for node_id in route.node_sequence
        if node_id in lookup and lookup[node_id].node_type.lower() == "c"
    )


def _incremental_distance(
    route: Route,
    insert_at: int,
    customer_id: str,
    instance: Instance,
) -> float:
    before = route.node_sequence[insert_at - 1]
    after = route.node_sequence[insert_at]
    return (
        instance.distance(before, customer_id)
        + instance.distance(customer_id, after)
        - instance.distance(before, after)
    )


def _insert_added_customer(
    routes: list[Route],
    event: DynamicEvent,
    instance: Instance,
    prices: Any,
    owner_depot_id: str,
    *,
    stage_index: int,
    try_existing_routes: bool = True,
) -> tuple[list[Route], int]:
    candidates: list[tuple[float, str, int, Route]] = []
    checks = 0
    for route_index, route in enumerate(routes if try_existing_routes else []):
        if route.home_depot_id != owner_depot_id:
            continue
        for insert_at in range(1, len(route.node_sequence)):
            checks += 1
            sequence = list(route.node_sequence)
            sequence.insert(insert_at, event.customer_id)
            candidate = replace(route, node_sequence=sequence)
            if _route_load(candidate, instance) > float(prices.Q_capacity) + _TOL:
                continue
            try:
                route_timing(candidate, instance, prices)
            except ValueError:
                continue
            candidates.append(
                (
                    _incremental_distance(route, insert_at, event.customer_id, instance),
                    route.vehicle_id,
                    insert_at,
                    candidate,
                )
            )
    if candidates:
        _, selected_id, _, selected = min(
            candidates,
            key=lambda item: (item[0], item[1], item[2]),
        )
        return [selected if route.vehicle_id == selected_id else route for route in routes], checks

    # Frozen fallback: one new CV trip at the event's preassigned owner depot.
    # The exact-asset scheduler may reject it; no second fallback is attempted.
    singleton = Route(
        vehicle_id=f"S{stage_index}_ADD_{event.event_id}",
        vehicle_type="cv",
        home_depot_id=owner_depot_id,
        node_sequence=[owner_depot_id, event.customer_id, owner_depot_id],
    )
    checks += 1
    if _route_load(singleton, instance) > float(prices.Q_capacity) + _TOL:
        raise RuntimeError(f"added customer {event.customer_id} exceeds vehicle capacity")
    route_timing(singleton, instance, prices)
    return [*routes, singleton], checks


def build_open_stage(
    source_routes: Sequence[Route],
    source_instance: Instance,
    stage_events: Sequence[DynamicEvent],
    trigger_second: float,
    locked_customers: set[str],
    owners: Mapping[str, str],
    prices: Any,
    *,
    stage_index: int,
    isolate_changed_customers: bool = False,
) -> StageConstruction:
    effective = _instance_after_events(
        source_instance,
        list(stage_events),
        trigger_second,
        set(locked_customers),
    )
    routes = [
        replace(
            route,
            vehicle_id=f"S{stage_index}_OPEN_{index:03d}",
            node_sequence=list(route.node_sequence),
        )
        for index, route in enumerate(source_routes, start=1)
    ]
    applied: list[str] = []
    ignored: list[str] = []
    checks = 0
    for event in sorted(stage_events, key=lambda item: (float(item.t_appear), str(item.event_id))):
        event_type = event.event_type.lower()
        if event_type == "add":
            if event.customer_id not in owners:
                raise RuntimeError(f"added customer {event.customer_id} has no frozen owner")
            routes, used = _insert_added_customer(
                routes,
                event,
                effective,
                prices,
                owners[event.customer_id],
                stage_index=stage_index,
                # This gate checks whether the inherited vehicle states remain
                # usable.  Merging a new order into an existing electric trip
                # is left to the later paired search, where the battery effect
                # is evaluated together with the whole remaining plan.
                try_existing_routes=False,
            )
            checks += used
            applied.append(event.event_id)
            continue

        matching = [
            route for route in routes if event.customer_id in route.node_sequence
        ]
        if not matching:
            if event.customer_id in locked_customers:
                ignored.append(event.event_id)
                continue
            raise RuntimeError(
                f"event {event.event_id} targets neither an open nor a locked customer"
            )
        if len(matching) != 1:
            raise RuntimeError(f"event {event.event_id} target is duplicated before update")
        if event_type == "cancel":
            routes = [
                replace(
                    route,
                    node_sequence=[
                        node_id for node_id in route.node_sequence if node_id != event.customer_id
                    ],
                )
                if route.vehicle_id == matching[0].vehicle_id
                else route
                for route in routes
            ]
        elif event_type in {"demand_change", "change", "time_window_change"}:
            affected = matching[0]
            try:
                if isolate_changed_customers:
                    raise ValueError("changed customer starts a separate trip at this gate")
                if _route_load(affected, effective) > float(prices.Q_capacity) + _TOL:
                    raise ValueError("updated route exceeds capacity")
                route_timing(affected, effective, prices)
            except ValueError:
                # The event is known at this trigger, so remove the changed
                # customer from its now-infeasible open route and place it
                # again using the same deterministic rule.  Keep the current
                # serving depot fixed in this zero-search gate; cooperation is
                # tested later by the paired search arms.
                routes = [
                    replace(
                        route,
                        node_sequence=[
                            node_id
                            for node_id in route.node_sequence
                            if node_id != event.customer_id
                        ],
                    )
                    if route.vehicle_id == affected.vehicle_id
                    else route
                    for route in routes
                ]
                routes, used = _insert_added_customer(
                    routes,
                    event,
                    effective,
                    prices,
                    affected.home_depot_id,
                    stage_index=stage_index,
                    try_existing_routes=False,
                )
                checks += used
        else:
            raise RuntimeError(f"unsupported event type {event.event_type!r}")
        applied.append(event.event_id)

    lookup = {node.node_id: node for node in effective.nodes}
    routes = [
        route
        for route in routes
        if any(
            node_id in lookup and lookup[node_id].node_type.lower() == "c"
            for node_id in route.node_sequence
        )
    ]
    cross_site: list[CrossSiteService] = []
    for route in routes:
        for customer_id in customer_ids(route, effective):
            owner = owners.get(customer_id)
            if owner is not None and owner != route.home_depot_id:
                cross_site.append(CrossSiteService(customer_id, route.home_depot_id))
    return StageConstruction(
        solution=Solution(
            routes=routes,
            charging_actions=[],
            cross_site_services=sorted(
                cross_site,
                key=lambda item: (item.customer_id, item.served_by_depot_id),
            ),
        ),
        effective_instance=effective,
        applied_event_ids=tuple(applied),
        ignored_locked_event_ids=tuple(ignored),
        feasibility_check_count=checks,
    )


def assert_customer_conservation(
    history: Sequence[HistorySnapshot],
    future: Solution,
    instance: Instance,
) -> dict[str, Any]:
    occurrences: dict[str, list[str]] = {}
    for item in history:
        for customer_id in item.customer_ids:
            occurrences.setdefault(customer_id, []).append(
                f"history:{item.source_stage}:{item.route_id}"
            )
    for route in future.routes:
        for customer_id in customer_ids(route, instance):
            occurrences.setdefault(customer_id, []).append(f"future:{route.vehicle_id}")
    expected = active_customer_ids(instance)
    observed = set(occurrences)
    duplicates = {
        customer_id: labels
        for customer_id, labels in occurrences.items()
        if len(labels) != 1
    }
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    if duplicates or missing or extra:
        raise RuntimeError(
            f"customer ledger does not close; duplicates={duplicates}, missing={missing}, extra={extra}"
        )
    return {
        "expected_customer_count": len(expected),
        "history_customer_count": len(history_customer_ids(history)),
        "future_customer_count": sum(len(customer_ids(route, instance)) for route in future.routes),
        "duplicate_customer_count": 0,
        "missing_customer_count": 0,
        "extra_customer_count": 0,
    }


def state_carry_pass(
    previous: Mapping[str, DynamicAssetState],
    current: Mapping[str, DynamicAssetState],
    trigger_second: float,
    battery_cap: float,
) -> bool:
    if set(previous) != set(current) or len(current) != 20:
        return False
    for asset_id, state in current.items():
        before = previous[asset_id]
        if state.vehicle_type != before.vehicle_type or state.home_depot_id != before.home_depot_id:
            return False
        if state.next_trip_index < before.next_trip_index:
            return False
        if state.available_second < trigger_second - _TOL:
            return False
        if state.vehicle_type == "ev" and not (-_TOL <= state.remaining_battery_kwh <= battery_cap + _TOL):
            return False
    return True


def charging_history_preserved(
    previous_locked: Sequence[ChargingAction],
    current_cut: CertificateCut,
    previous_plan: Solution,
) -> bool:
    previous = {action_signature(action) for action in previous_locked}
    expected_new = {
        action_signature(action)
        for action in previous_plan.charging_actions
        if float(action.charge_start_second)
        + int(action.charge_day_offset) * 86_400.0
        <= current_cut.trigger_second
    }
    current = {action_signature(action) for action in current_cut.locked_charging_actions}
    return previous | expected_new <= current


def charger_overlap_counterexample_rejected(prices: Any) -> bool:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=30_000.0, station_chargers=1),
            Node("C1", "c", 1.0, 0.0, demand=1.0, ready_time=10_000.0, due_time=12_000.0),
        ],
        distance_matrix=[[0.0, 1_000.0], [1_000.0, 0.0]],
        num_cv=0,
        num_ev=2,
    )
    local_prices = replace(
        prices,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
    )
    locked_energy = 20.0
    locked_duration = locked_energy / 22.0 * 3_600.0
    states = {
        "EV_D0_1": DynamicAssetState("EV_D0_1", "ev", "D0", 0.0, 0.0, 1),
        "EV_D0_2": DynamicAssetState(
            "EV_D0_2",
            "ev",
            "D0",
            9_000.0 + locked_duration,
            locked_energy,
            1,
        ),
    }
    locked = ChargingAction(
        "EV_D0_2#T1",
        "D0",
        locked_energy,
        locked_duration / 60.0,
        9_000.0,
    )
    try:
        prepare_dynamic_multitrip_solution(
            Solution(routes=[Route("open", "ev", "D0", ["D0", "C1", "D0"])]),
            instance,
            local_prices,
            asset_states=states,
            stage_start_second=0.0,
            locked_charging_actions=(locked,),
        )
    except ValueError as exc:
        return "charger capacity exceeded" in str(exc)
    return False


def _cut_routes(solution: Solution, route_ids: Sequence[str]) -> list[Route]:
    lookup = {route.vehicle_id: route for route in solution.routes}
    missing = sorted(set(route_ids) - set(lookup))
    if missing:
        raise RuntimeError(f"certificate cut references missing routes: {missing}")
    return [lookup[route_id] for route_id in route_ids]


def run_gate() -> dict[str, Any]:
    sources = load_sources()
    bundle = sources["bundle"]
    prices = sources["prices"]
    first_batch, second_batch = sources["batches"]
    trigger_1 = float(first_batch["trigger_time"])
    trigger_2 = float(second_batch["trigger_time"])

    cut_1 = cut_certificate_at_trigger(
        sources["solution"],
        sources["certificate"],
        bundle.instance,
        prices,
        trigger_second=trigger_1,
    )
    if set(cut_1.asset_states) != set(sources["ledger"].assets) or len(cut_1.asset_states) != 20:
        raise RuntimeError("first trigger lost a frozen physical asset")
    history: list[HistorySnapshot] = []
    first_locked_routes = _cut_routes(
        sources["solution"],
        [*cut_1.completed_route_ids, *cut_1.in_progress_route_ids],
    )
    add_history_routes(history, first_locked_routes, bundle.instance, source_stage=0)
    for route in first_locked_routes:
        if route_signature(route) != sources["ledger"].routes[route.vehicle_id].route_signature:
            raise RuntimeError(f"initial history signature drifted for {route.vehicle_id}")

    construction_1 = build_open_stage(
        _cut_routes(sources["solution"], cut_1.editable_route_ids),
        bundle.instance,
        first_batch["events"],
        trigger_1,
        history_customer_ids(history),
        sources["owners"],
        prices,
        stage_index=1,
        isolate_changed_customers=True,
    )
    plan_1, certificate_1, type_trials_1 = prepare_stage_with_singleton_type_choices(
        construction_1,
        prices,
        asset_states=cut_1.asset_states,
        stage_start_second=trigger_1,
        locked_charging_actions=cut_1.locked_charging_actions,
    )
    conservation_1 = assert_customer_conservation(
        history,
        plan_1,
        construction_1.effective_instance,
    )

    cut_2 = cut_dynamic_certificate_at_trigger(
        plan_1,
        certificate_1,
        construction_1.effective_instance,
        prices,
        inherited_asset_states=cut_1.asset_states,
        previous_stage_start_second=trigger_1,
        trigger_second=trigger_2,
        inherited_locked_charging_actions=cut_1.locked_charging_actions,
    )
    two_trigger_state_carry = state_carry_pass(
        cut_1.asset_states,
        cut_2.asset_states,
        trigger_2,
        float(prices.B_battery_kwh),
    )
    if not two_trigger_state_carry:
        raise RuntimeError("second trigger did not preserve the full inherited asset state")
    started_charging_preserved = charging_history_preserved(
        cut_1.locked_charging_actions,
        cut_2,
        plan_1,
    )
    if not started_charging_preserved:
        raise RuntimeError("second trigger dropped an already-started charge")

    second_locked_routes = _cut_routes(
        plan_1,
        [*cut_2.completed_route_ids, *cut_2.in_progress_route_ids],
    )
    add_history_routes(
        history,
        second_locked_routes,
        construction_1.effective_instance,
        source_stage=1,
    )
    history_before_second_repair = {
        (item.source_stage, item.route_id): item.signature for item in history
    }
    construction_2 = build_open_stage(
        _cut_routes(plan_1, cut_2.editable_route_ids),
        construction_1.effective_instance,
        second_batch["events"],
        trigger_2,
        history_customer_ids(history),
        sources["owners"],
        prices,
        stage_index=2,
        isolate_changed_customers=True,
    )
    plan_2, certificate_2, type_trials_2 = prepare_stage_with_singleton_type_choices(
        construction_2,
        prices,
        asset_states=cut_2.asset_states,
        stage_start_second=trigger_2,
        locked_charging_actions=cut_2.locked_charging_actions,
    )
    conservation_2 = assert_customer_conservation(
        history,
        plan_2,
        construction_2.effective_instance,
    )
    history_immutable = history_is_immutable(history) and history_before_second_repair == {
        (item.source_stage, item.route_id): route_signature(item.route) for item in history
    }
    if not history_immutable:
        raise RuntimeError("completed or in-progress history changed during continuation")

    charging_concurrency = charger_overlap_counterexample_rejected(prices)
    if not charging_concurrency:
        raise RuntimeError("one-charger/two-vehicle overlap counterexample was not rejected")
    all_customer_conservation = all(
        row["duplicate_customer_count"] == 0
        and row["missing_customer_count"] == 0
        and row["extra_customer_count"] == 0
        for row in (conservation_1, conservation_2)
    )
    asset_preservation = len(cut_1.asset_states) == len(cut_2.asset_states) == 20

    rows = [
        {
            "record_type": "trigger",
            "stage": 1,
            "trigger_second": trigger_1,
            "event_ids": ";".join(event.event_id for event in first_batch["events"]),
            "applied_event_ids": ";".join(construction_1.applied_event_ids),
            "ignored_locked_event_ids": ";".join(construction_1.ignored_locked_event_ids),
            "completed_route_count": len(cut_1.completed_route_ids),
            "in_progress_route_count": len(cut_1.in_progress_route_ids),
            "editable_route_count": len(cut_1.editable_route_ids),
            "future_route_count": len(plan_1.routes),
            "asset_count": len(cut_1.asset_states),
            "locked_charge_count": len(cut_1.locked_charging_actions),
            "active_customer_count": conservation_1["expected_customer_count"],
            "history_customer_count": conservation_1["history_customer_count"],
            "future_customer_count": conservation_1["future_customer_count"],
            "construction_feasibility_checks": construction_1.feasibility_check_count,
            "search_evaluations": SEARCH_EVALUATIONS,
            "status": "PASS",
        },
        {
            "record_type": "trigger",
            "stage": 2,
            "trigger_second": trigger_2,
            "event_ids": ";".join(event.event_id for event in second_batch["events"]),
            "applied_event_ids": ";".join(construction_2.applied_event_ids),
            "ignored_locked_event_ids": ";".join(construction_2.ignored_locked_event_ids),
            "completed_route_count": len(cut_2.completed_route_ids),
            "in_progress_route_count": len(cut_2.in_progress_route_ids),
            "editable_route_count": len(cut_2.editable_route_ids),
            "future_route_count": len(plan_2.routes),
            "asset_count": len(cut_2.asset_states),
            "locked_charge_count": len(cut_2.locked_charging_actions),
            "active_customer_count": conservation_2["expected_customer_count"],
            "history_customer_count": conservation_2["history_customer_count"],
            "future_customer_count": conservation_2["future_customer_count"],
            "construction_feasibility_checks": construction_2.feasibility_check_count,
            "search_evaluations": SEARCH_EVALUATIONS,
            "status": "PASS",
        },
        {
            "record_type": "counterexample",
            "stage": 0,
            "trigger_second": 0.0,
            "event_ids": "",
            "applied_event_ids": "",
            "ignored_locked_event_ids": "",
            "completed_route_count": 0,
            "in_progress_route_count": 0,
            "editable_route_count": 0,
            "future_route_count": 0,
            "asset_count": 2,
            "locked_charge_count": 1,
            "active_customer_count": 1,
            "history_customer_count": 0,
            "future_customer_count": 1,
            "construction_feasibility_checks": 0,
            "search_evaluations": SEARCH_EVALUATIONS,
            "status": "PASS_REJECTED_ONE_CHARGER_TWO_VEHICLES",
        },
    ]
    decision = {
        "verdict": PASS_VERDICT,
        "passed": True,
        "two_trigger_state_carry_pass": two_trigger_state_carry,
        "charging_concurrency_pass": charging_concurrency,
        "history_immutable_pass": history_immutable,
        "customer_conservation_pass": all_customer_conservation,
        "twenty_asset_preservation_pass": asset_preservation,
        "started_charging_preserved_pass": started_charging_preserved,
        "search_evaluations": SEARCH_EVALUATIONS,
        "boundary": (
            "This gate proves only two zero-search certificate continuations and their execution ledger. "
            "It is not an E7 cost, carbon, fairness, or algorithm-effect result."
        ),
    }
    if not all(
        value is True
        for key, value in decision.items()
        if key.endswith("_pass")
    ):
        raise RuntimeError("one or more continuous-trigger decision checks failed")

    metadata = {
        "contract_id": CONTRACT_ID,
        "status": "PASS",
        "search_evaluations": SEARCH_EVALUATIONS,
        "formal_case": CASE,
        "formal_customer_count": 221,
        "formal_fleet": {"cv": 10, "ev": 10},
        "input_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in sources["paths"].values()
        },
        "event_departure_gate": sources["departure_gate"],
        "trigger_rule": "first two non-empty batches from _build_trigger_batches with frozen defaults",
        "triggers": [trigger_1, trigger_2],
        "event_batches": [
            [asdict(event) for event in first_batch["events"]],
            [asdict(event) for event in second_batch["events"]],
        ],
        "construction_rule": (
            "event order; update only editable customers; each add uses its frozen owner and the first "
            "route-local feasible insertion after sorting by incremental distance, route id, and position; "
            "if no insertion exists, create one CV singleton; no alternative is attempted after exact-asset failure"
        ),
        "construction_feasibility_checks": {
            "stage_1": construction_1.feasibility_check_count,
            "stage_2": construction_2.feasibility_check_count,
            "not_search_evaluations": True,
        },
        "separate_trip_vehicle_type_trials": {
            "stage_1": type_trials_1,
            "stage_2": type_trials_2,
        },
        "stage_1": {
            "cut": _cut_payload(cut_1),
            "construction": _construction_payload(construction_1),
            "certificate": certificate_1.as_dict(),
            "customer_conservation": conservation_1,
        },
        "stage_2": {
            "cut": _cut_payload(cut_2),
            "construction": _construction_payload(construction_2),
            "certificate": certificate_2.as_dict(),
            "customer_conservation": conservation_2,
        },
        "history": [
            {
                "source_stage": item.source_stage,
                "route_id": item.route_id,
                "route_signature": item.signature,
                "customer_ids": list(item.customer_ids),
            }
            for item in history
        ],
        "one_charger_counterexample": {
            "station_chargers": 1,
            "simultaneous_vehicle_count": 2,
            "rejected": charging_concurrency,
        },
        "source_code_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (
                Path(__file__).resolve(),
                ROOT / "solver/src/setp_solver/search/dynamic_multitrip_schedule.py",
                ROOT / "solver/src/setp_solver/search/certificate_execution.py",
                ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
                ROOT / "solver/src/setp_solver/search/dynamic.py",
            )
        },
        "git_head": _git_head(),
        "explicitly_not_done": [
            "no ALNS or other route search",
            "no cost/carbon/fairness comparison",
            "no E7 formal matrix",
            "no change to the frozen E3/E6 inputs",
        ],
    }
    return {"rows": rows, "metadata": metadata, "decision": decision}


def _cut_payload(cut: CertificateCut) -> dict[str, Any]:
    return {
        "trigger_second": cut.trigger_second,
        "source_certificate_sha256": cut.source_certificate_sha256,
        "completed_route_ids": list(cut.completed_route_ids),
        "in_progress_route_ids": list(cut.in_progress_route_ids),
        "editable_route_ids": list(cut.editable_route_ids),
        "locked_charging_actions": [asdict(action) for action in cut.locked_charging_actions],
        "asset_states": {
            asset_id: asdict(state) for asset_id, state in sorted(cut.asset_states.items())
        },
    }


def _construction_payload(construction: StageConstruction) -> dict[str, Any]:
    return {
        "applied_event_ids": list(construction.applied_event_ids),
        "ignored_locked_event_ids": list(construction.ignored_locked_event_ids),
        "feasibility_check_count": construction.feasibility_check_count,
        "route_signatures": {
            route.vehicle_id: route_signature(route) for route in construction.solution.routes
        },
    }


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_artifacts(output: Path, result: Mapping[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for path in list(output.iterdir()):
        if path.is_file():
            path.unlink()
    write_csv(output / "raw_runs.csv", result["rows"])
    write_json(output / "metadata.json", result["metadata"])
    write_json(output / "decision.json", result["decision"])
    triggers = result["metadata"]["triggers"]
    rows = result["rows"]
    (output / "report.md").write_text(
        "\n".join(
            [
                "# E7 连续触发零搜索门",
                "",
                f"判决：`{result['decision']['verdict']}`。",
                "",
                f"本门使用 seed 1 事件流的前两个真实触发时点：{triggers[0]:.3f} 秒和 {triggers[1]:.3f} 秒。",
                "第一轮只修改尚未发车的客户并续排；第二轮不是回到原方案重来，而是从第一轮动态证书继续切分。",
                f"两轮分别保留 {rows[0]['asset_count']} 和 {rows[1]['asset_count']} 辆原有实体车，搜索评价次数始终为 0。",
                "",
                "已完成和执行中的车次未被改写；客户在历史承诺与未来方案之间恰好出现一次；"
                "已经开始的充电没有丢失，后续充电与其共同接受车场接口容量检查。",
                "另用一个只有 1 个接口、2 辆车同时充电的反例复核，验证器按预期拒绝。",
                "",
                "证据边界：这只证明连续两次动态接续的机械账闭合。它没有运行搜索，"
                "也没有证明动态方案更省钱、更低碳或更公平，不能据此宣称 E7 正式实验完成。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for sidecar in output.glob("._*"):
        sidecar.unlink()
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
        {
            "algorithm": "sha256",
            "excluded": ["artifact_hashes.json", "._*", "__pycache__", ".pytest_cache"],
            "artifacts": artifacts,
        },
    )


def write_halt_artifacts(output: Path, error: Exception) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for path in list(output.iterdir()):
        if path.is_file():
            path.unlink()
    message = str(error)
    write_csv(
        output / "raw_runs.csv",
        [
            {
                "status": "HALT",
                "search_evaluations": 0,
                "failure": message,
            }
        ],
    )
    write_json(
        output / "metadata.json",
        {
            "contract_id": CONTRACT_ID,
            "search_evaluations": 0,
            "scope": "seed 1, first two non-empty trigger batches",
            "failure": message,
        },
    )
    write_json(
        output / "decision.json",
        {
            "verdict": HALT_VERDICT,
            "passed": False,
            "search_started": False,
            "search_evaluations": 0,
            "reason": message,
            "boundary": (
                "The zero-search construction did not survive two triggers. "
                "This does not invalidate the frozen event stream or earlier experiments."
            ),
        },
    )
    (output / "report.md").write_text(
        "\n".join(
            [
                "# E7 连续两次订单变化的零搜索检查",
                "",
                f"判决：`{HALT_VERDICT}`。",
                "",
                "没有运行路线搜索，实际评价次数为 0。第一轮订单变化可以接续排班，"
                "但第二轮仅靠拆出单独车次和更换车辆类型仍无法排开。",
                "",
                f"停止原因：{message}",
                "",
                "该结果说明简单接续办法不足，不能据此声称动态实验已经通过。"
                "事件流、原始排班和此前实验均未改动。",
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
        {
            "algorithm": "sha256",
            "excluded": ["artifact_hashes.json", "._*"],
            "artifacts": artifacts,
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    try:
        result = run_gate()
    except (RuntimeError, ValueError) as exc:
        write_halt_artifacts(output, exc)
        raise SystemExit(2) from exc
    write_artifacts(output, result)


if __name__ == "__main__":
    main()
