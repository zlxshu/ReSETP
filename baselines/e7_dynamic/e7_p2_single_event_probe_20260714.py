#!/usr/bin/env python3
"""Blocked-safe skeleton for the E7 P2 one-event/one-trigger probe.

The current file is intentionally unable to start a search.  It freezes the
mechanical P2 input, proves the original whole-trip commitments can be booked
once, and writes a five-file draft that remains HALT until the separate
two-trigger/charger-concurrency gate has passed.  The eventual search budget is
hard-capped at 100 evaluations.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
import hashlib
import inspect
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from baselines.e3_ablation import e3_v3_runner as legacy
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.certificate_execution import build_certificate_execution_ledger
from setp_solver.search.dynamic import DynamicEvent, RollingParameters, _build_trigger_batches
from setp_solver.search.dynamic import _instance_after_events
from setp_solver.search import dynamic_multitrip_schedule as dynamic_schedule
from setp_solver.search.dynamic_multitrip_schedule import (
    cut_certificate_at_trigger,
    prepare_dynamic_multitrip_solution,
)
from setp_solver.search.execution_accounting import ExecutionAccountingLedger
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import MultiTripCertificate, ScheduledTrip
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerOperatorAction,
    WinnerOperatorSet,
    apply_winner_action,
)
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance
from setp_solver.solution import CrossSiteService, Route, Solution


ROOT = Path(__file__).resolve().parents[2]
E3_BUNDLE = (
    ROOT
    / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets"
    / "L-main-threeshift-100c-01/bundle"
)
E6_ROOT = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
CASE = "L-main-threeshift-100c-01__geographic__seed1__no_loss"
EVENT_ROOT = ROOT / "baselines/e7_dynamic/e7_v2_20260714/event_streams"
EVENT_PATH = EVENT_ROOT / "stream_seed1.events.json"
OWNER_PATH = EVENT_ROOT / "stream_seed1.owners.csv"
DEFAULT_OUT = ROOT / "baselines/e7_dynamic/e7_v2_20260714/preflight/p2_single_event_probe"
DEFAULT_CONTINUOUS_GATE = (
    ROOT / "baselines/e7_dynamic/e7_dynamic_continuous_trigger_gate_20260714/decision.json"
)

FORMAL_INSTANCE_SHA256 = "59696be304ad9f3c484820439e1cbdb027945e20ad7ecbdb8542dfde7e0d6225"
MAX_SEARCH_EVALUATIONS = 100
P2_CONTRACT_ID = "E7_P2_SINGLE_EVENT_SINGLE_TRIGGER_ALNS_V2"
CONTINUOUS_GATE_VERDICT = "E7_DYNAMIC_CONTINUOUS_TRIGGER_GATE_PASS"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def display_path(path: Path) -> str:
    """Prefer a repository-relative path without assuming tests live in-repo."""

    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def load_certificate(path: Path) -> MultiTripCertificate:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={str(k): int(v) for k, v in payload["vehicle_counts"].items()},
        trips=tuple(ScheduledTrip(**row) for row in payload["trips"]),
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
        first_trip_charge_day_offset=int(payload.get("first_trip_charge_day_offset", -1)),
    )


def load_owner(customer_id: str) -> str:
    with OWNER_PATH.open(newline="", encoding="utf-8") as handle:
        owners = {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}
    try:
        return owners[customer_id]
    except KeyError as exc:
        raise RuntimeError(f"frozen P2 customer {customer_id} has no owner") from exc


def load_formal_sources() -> dict[str, Any]:
    instance_path = E3_BUNDLE / "instance.json"
    if sha256(instance_path) != FORMAL_INSTANCE_SHA256:
        raise RuntimeError("formal 221-customer instance hash drifted")
    bundle = load_search_bundle(E3_BUNDLE)
    if sum(node.node_type.lower() == "c" for node in bundle.instance.nodes) != 221:
        raise RuntimeError("formal P2 bundle is not the 221-customer network")
    if (bundle.instance.num_cv, bundle.instance.num_ev) != (10, 10):
        raise RuntimeError("formal P2 bundle is not the frozen 10+10 fleet")
    solution_path = E6_ROOT / "solutions" / f"{CASE}.json"
    certificate_path = E6_ROOT / "certificates" / f"{CASE}.json"
    solution = solution_from_dict(json.loads(solution_path.read_text(encoding="utf-8")))
    certificate = load_certificate(certificate_path)
    prices = legacy.prices_for("M1", 0.0)
    clock = build_certificate_execution_ledger(
        solution,
        certificate,
        bundle.instance,
        prices,
    )
    return {
        "bundle": bundle,
        "solution": solution,
        "certificate": certificate,
        "prices": prices,
        "clock": clock,
        "instance_path": instance_path,
        "solution_path": solution_path,
        "certificate_path": certificate_path,
    }


def select_probe_event(sources: dict[str, Any]) -> dict[str, Any]:
    """Select one event by a result-blind mechanical rule.

    Rule fixed before any P2 search: in seed 1, take the earliest add event
    whose trigger has completed, in-progress, and editable trips and has no
    already-started charge attached to an editable trip.  This avoids silently
    dropping electricity that has already been committed.
    """

    events = [
        DynamicEvent(**row)
        for row in json.loads(EVENT_PATH.read_text(encoding="utf-8"))
    ]
    batches = _build_trigger_batches(events, RollingParameters())
    trigger_by_event = {
        event.event_id: float(batch["trigger_time"])
        for batch in batches
        for event in batch["events"]
    }
    for event in sorted(events, key=lambda item: (item.t_appear, item.event_id)):
        if event.event_type != "add":
            continue
        trigger = trigger_by_event[event.event_id]
        cut = cut_certificate_at_trigger(
            sources["solution"],
            sources["certificate"],
            sources["bundle"].instance,
            sources["prices"],
            trigger_second=trigger,
        )
        editable = set(cut.editable_route_ids)
        orphan_started_charges = [
            action.vehicle_id
            for action in cut.locked_charging_actions
            if action.vehicle_id in editable
        ]
        if orphan_started_charges:
            continue
        if not (
            cut.completed_route_ids
            and cut.in_progress_route_ids
            and cut.editable_route_ids
        ):
            continue
        if float(event.new_due_time) <= trigger:
            continue
        return {
            "event": event,
            "trigger_second": trigger,
            "cut": cut,
            "owner_depot_id": load_owner(event.customer_id),
            "orphan_started_charges": orphan_started_charges,
        }
    raise RuntimeError("no seed-1 add event satisfies the frozen P2 mechanical rule")


def historical_commitment_summary(sources: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any]:
    """Book each departed whole trip once as an irreversible commitment.

    This is not a claim that every arc/customer in an in-progress trip has
    already occurred.  The accounting boundary is the operational commitment
    made when the complete trip departed.
    """

    trigger = float(selected["trigger_second"])
    ledger = ExecutionAccountingLedger(
        sources["solution"],
        sources["bundle"].instance,
        sources["bundle"].carbon_profile,
        sources["prices"],
        carbon_quota_kg=0.0,
    )
    added = ledger.register_started_or_completed(sources["clock"], at_second=trigger)
    summary = ledger.summary()
    cut = selected["cut"]
    expected_routes = set(cut.completed_route_ids) | set(cut.in_progress_route_ids)
    if set(added) != expected_routes:
        raise RuntimeError("whole-trip commitment ledger disagrees with the certificate cut")
    if summary.booked_route_count != len(expected_routes):
        raise RuntimeError("whole-trip accounting route count does not close")
    return {
        "contract_id": summary.contract_id,
        "committed_route_count": summary.booked_route_count,
        "committed_customer_count": summary.booked_customer_count,
        "committed_route_ids": sorted(summary.trips),
        "total_cost": summary.system.total_cost,
        "distance_total": summary.system.distance_total,
        "emissions_total": summary.system.E_total,
        "revenue": summary.system.revenue,
        "realized_profit": summary.system.realized_profit,
        "boundary": (
            "whole trip booked once at departure as an irreversible operational commitment; "
            "not a claim that every arc has already physically occurred at the trigger"
        ),
    }


def load_owners() -> dict[str, str]:
    with OWNER_PATH.open(newline="", encoding="utf-8") as handle:
        return {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}


def route_customers(route: Route, instance: Any) -> list[str]:
    lookup = {node.node_id: node for node in instance.nodes}
    return [
        node_id
        for node_id in route.node_sequence
        if node_id in lookup and lookup[node_id].node_type.lower() == "c"
    ]


def annotate_cross_site(
    routes: list[Route],
    instance: Any,
    owners: dict[str, str],
) -> list[CrossSiteService]:
    return sorted(
        [
            CrossSiteService(customer_id, route.home_depot_id)
            for route in routes
            for customer_id in route_customers(route, instance)
            if owners.get(customer_id) not in {None, route.home_depot_id}
        ],
        key=lambda item: (item.customer_id, item.served_by_depot_id),
    )


def build_probe_start(
    sources: dict[str, Any],
    selected: dict[str, Any],
    owners: dict[str, str],
) -> dict[str, Any]:
    event: DynamicEvent = selected["event"]
    cut = selected["cut"]
    trigger = float(selected["trigger_second"])
    locked_route_ids = set(cut.completed_route_ids) | set(cut.in_progress_route_ids)
    locked_customers = {
        customer_id
        for route in sources["solution"].routes
        if route.vehicle_id in locked_route_ids
        for customer_id in route_customers(route, sources["bundle"].instance)
    }
    effective = _instance_after_events(
        sources["bundle"].instance,
        [event],
        trigger,
        locked_customers,
    )
    editable_lookup = {
        route.vehicle_id: route
        for route in sources["solution"].routes
        if route.vehicle_id in set(cut.editable_route_ids)
    }
    routes = [
        replace(
            editable_lookup[route_id],
            vehicle_id=f"P2_OPEN_{index:03d}",
        )
        for index, route_id in enumerate(cut.editable_route_ids, start=1)
    ]
    separate = Route(
        vehicle_id=f"P2_ADD_{event.event_id}",
        vehicle_type="cv",
        home_depot_id=selected["owner_depot_id"],
        node_sequence=[selected["owner_depot_id"], event.customer_id, selected["owner_depot_id"]],
    )
    last_error: ValueError | None = None
    for vehicle_type in ("cv", "ev"):
        candidate_routes = [*routes, replace(separate, vehicle_type=vehicle_type)]
        candidate = Solution(
            routes=candidate_routes,
            charging_actions=[],
            cross_site_services=annotate_cross_site(candidate_routes, effective, owners),
        )
        try:
            prepared, certificate = prepare_dynamic_multitrip_solution(
                candidate,
                effective,
                sources["prices"],
                asset_states=cut.asset_states,
                stage_start_second=trigger,
                locked_charging_actions=cut.locked_charging_actions,
            )
            return {
                "search_solution": candidate,
                "prepared_solution": prepared,
                "certificate": certificate,
                "effective_instance": effective,
                "locked_customers": locked_customers,
                "separate_trip_vehicle_type": vehicle_type,
            }
        except ValueError as exc:
            last_error = exc
    raise RuntimeError(f"single-event starting plan is infeasible: {last_error}")


def exact_future_cost(
    solution: Solution,
    *,
    instance: Any,
    sources: dict[str, Any],
    selected: dict[str, Any],
) -> tuple[Solution, MultiTripCertificate, float]:
    prepared, certificate = prepare_dynamic_multitrip_solution(
        solution,
        instance,
        sources["prices"],
        asset_states=selected["cut"].asset_states,
        stage_start_second=float(selected["trigger_second"]),
        locked_charging_actions=selected["cut"].locked_charging_actions,
    )
    cost = float(
        evaluate(
            prepared,
            instance,
            sources["bundle"].carbon_profile,
            sources["prices"],
            carbon_quota_kg=0.0,
        )["total_cost"]
    )
    return prepared, certificate, cost


def future_only_instance(instance: Instance, locked_customers: set[str]) -> Instance:
    kept_indexes = [
        index
        for index, node in enumerate(instance.nodes)
        if node.node_type.lower() != "c" or node.node_id not in locked_customers
    ]
    return Instance(
        nodes=[instance.nodes[index] for index in kept_indexes],
        distance_matrix=[
            [instance.distance_matrix[row][column] for column in kept_indexes]
            for row in kept_indexes
        ],
        diesel_l_per_meter=instance.diesel_l_per_meter,
        ev_kwh_per_meter=instance.ev_kwh_per_meter,
        unit_distance_cost_per_meter=instance.unit_distance_cost_per_meter,
        num_cv=None,
        num_ev=None,
    )


def run_alns_probe(evaluations: int = MAX_SEARCH_EVALUATIONS) -> dict[str, Any]:
    if not 1 <= int(evaluations) <= MAX_SEARCH_EVALUATIONS:
        raise ValueError(f"probe evaluations must be between 1 and {MAX_SEARCH_EVALUATIONS}")
    sources = load_formal_sources()
    selected = select_probe_event(sources)
    owners = load_owners()
    history = historical_commitment_summary(sources, selected)
    start = build_probe_start(sources, selected, owners)
    effective = start["effective_instance"]
    search_instance = future_only_instance(effective, start["locked_customers"])
    context = EvaluationContext(
        search_instance,
        sources["bundle"].carbon_profile,
        prices=sources["prices"],
        budget=EvalBudget(limit=int(evaluations), target=int(evaluations)),
        customer_home_depot=owners,
        allow_cross_depot=True,
        repair_delta_mode="fast",
    )
    policy = SearchPolicy(
        require_charging_signal=False,
        max_cv=999,
        max_ev=999,
        allow_cross_depot=True,
    )
    operators = WinnerOperatorSet.create(
        include_route_elimination=False,
        allow_cross_depot=True,
    )
    pairs = [
        (destroy_id, repair_id)
        for destroy_id, _ in operators.destroy_ops
        for repair_id, _ in operators.repair_ops
    ]
    weights = np.ones(len(pairs), dtype=float)
    rng = np.random.default_rng(1)
    current = start["search_solution"]
    current_prepared = start["prepared_solution"]
    current_certificate = start["certificate"]
    current_cost = float(
        evaluate(
            current_prepared,
            effective,
            sources["bundle"].carbon_profile,
            sources["prices"],
            carbon_quota_kg=0.0,
        )["total_cost"]
    )
    initial_cost = current_cost
    best = current
    best_prepared = current_prepared
    best_certificate = current_certificate
    best_cost = current_cost
    rows: list[dict[str, Any]] = []
    accepted_count = 0
    dynamically_feasible_count = 0
    changed_count = 0
    for iteration in range(1, int(evaluations) + 1):
        probabilities = weights / weights.sum()
        pair_index = int(rng.choice(len(pairs), p=probabilities))
        destroy_id, repair_id = pairs[pair_index]
        action = WinnerOperatorAction(
            destroy_op_id=destroy_id,
            repair_op_id=repair_id,
            remove_count_q=1 + ((iteration - 1) % 4),
            remove_fraction=None,
            raw_action=(),
        )
        outcome = apply_winner_action(
            current,
            action,
            context,
            rng=rng,
            operator_set=operators,
            policy=policy,
            progress=(iteration - 1) / max(1, int(evaluations)),
        )
        candidate = outcome["candidate_solution"]
        dynamic_feasible = False
        accepted = False
        candidate_cost = math.inf
        improved_best = False
        improves_current = False
        if outcome["changed"]:
            changed_count += 1
            try:
                candidate_prepared, candidate_certificate, candidate_cost = exact_future_cost(
                    candidate,
                    instance=effective,
                    sources=sources,
                    selected=selected,
                )
                dynamic_feasible = True
                dynamically_feasible_count += 1
                temperature = max(1.0, initial_cost * 0.01) * (0.98 ** (iteration - 1))
                delta = candidate_cost - current_cost
                improves_current = delta <= 0.0
                accepted = delta <= 0.0 or rng.random() < math.exp(-delta / max(temperature, 1e-9))
                if accepted:
                    current = candidate
                    current_prepared = candidate_prepared
                    current_certificate = candidate_certificate
                    current_cost = candidate_cost
                    accepted_count += 1
                if candidate_cost < best_cost - 1e-9:
                    best = candidate
                    best_prepared = candidate_prepared
                    best_certificate = candidate_certificate
                    best_cost = candidate_cost
                    improved_best = True
            except ValueError:
                dynamic_feasible = False
        reward = 5.0 if improved_best else 2.0 if accepted and improves_current else 1.0 if accepted else 0.1
        weights[pair_index] = 0.8 * weights[pair_index] + 0.2 * reward
        rows.append(
            {
                "evaluation": iteration,
                "destroy_operator": destroy_id,
                "repair_operator": repair_id,
                "changed": bool(outcome["changed"]),
                "dynamic_feasible": dynamic_feasible,
                "accepted": accepted,
                "candidate_future_cost": "" if not math.isfinite(candidate_cost) else candidate_cost,
                "current_future_cost": current_cost,
                "best_future_cost": best_cost,
            }
        )
    if context.budget is None or context.budget.count != int(evaluations):
        raise RuntimeError("ALNS probe evaluation count did not close")

    expected_customers = {
        node.node_id for node in effective.nodes if node.node_type.lower() == "c"
    }
    future_occurrences = [
        customer_id
        for route in best_prepared.routes
        for customer_id in route_customers(route, effective)
    ]
    if len(future_occurrences) != len(set(future_occurrences)):
        raise RuntimeError("best future plan contains a duplicate customer")
    if start["locked_customers"] | set(future_occurrences) != expected_customers:
        raise RuntimeError("historical commitments and best future plan do not cover all customers")
    if start["locked_customers"] & set(future_occurrences):
        raise RuntimeError("a committed customer reappears in the future plan")
    return {
        "sources": sources,
        "selected": selected,
        "history": history,
        "start": start,
        "rows": rows,
        "initial_future_cost": initial_cost,
        "best_future_cost": best_cost,
        "initial_total_cost": float(history["total_cost"]) + initial_cost,
        "best_total_cost": float(history["total_cost"]) + best_cost,
        "accepted_count": accepted_count,
        "changed_count": changed_count,
        "dynamically_feasible_count": dynamically_feasible_count,
        "best_solution": best,
        "best_prepared_solution": best_prepared,
        "best_certificate": best_certificate,
        "operator_weights": {f"{d}+{r}": float(weights[i]) for i, (d, r) in enumerate(pairs)},
        "evaluations": int(evaluations),
    }


def continuous_gate_status(path: Path) -> dict[str, Any]:
    required_api = {
        "cut_dynamic_certificate_at_trigger": hasattr(
            dynamic_schedule, "cut_dynamic_certificate_at_trigger"
        ),
        "prepare_accepts_locked_charging_actions": (
            "locked_charging_actions"
            in inspect.signature(dynamic_schedule.prepare_dynamic_multitrip_solution).parameters
        ),
    }
    if not path.is_file():
        return {
            "ready": False,
            "gate_path": display_path(path),
            "gate_exists": False,
            "required_api": required_api,
            "reasons": [
                "two-trigger state carry gate is absent",
                "depot charging concurrency gate is absent",
            ],
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    mechanical = {
        "verdict": payload.get("verdict") == CONTINUOUS_GATE_VERDICT,
        "two_trigger_state_carry_pass": payload.get("two_trigger_state_carry_pass") is True,
        "charging_concurrency_pass": payload.get("charging_concurrency_pass") is True,
        "history_immutable_pass": payload.get("history_immutable_pass") is True,
    }
    ready = all(required_api.values()) and all(mechanical.values())
    return {
        "ready": ready,
        "gate_path": display_path(path),
        "gate_exists": True,
        "gate_sha256": sha256(path),
        "required_api": required_api,
        "mechanical": mechanical,
        "reasons": [] if ready else ["continuous dynamic scheduler gate is incomplete"],
    }


def build_draft(output: Path, continuous_gate: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    for old in output.iterdir():
        if old.is_file():
            old.unlink()
    sources = load_formal_sources()
    selected = select_probe_event(sources)
    event: DynamicEvent = selected["event"]
    cut = selected["cut"]
    history = historical_commitment_summary(sources, selected)
    gate = continuous_gate_status(continuous_gate)

    raw_row = {
        "probe_id": "e7_p2_seed1_single_add",
        "seed": 1,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "customer_id": event.customer_id,
        "owner_depot_id": selected["owner_depot_id"],
        "t_appear": event.t_appear,
        "trigger_second": selected["trigger_second"],
        "new_demand": event.new_demand,
        "new_ready_time": event.new_ready_time,
        "new_due_time": event.new_due_time,
        "completed_route_count": len(cut.completed_route_ids),
        "in_progress_route_count": len(cut.in_progress_route_ids),
        "editable_route_count": len(cut.editable_route_ids),
        "inherited_asset_count": len(cut.asset_states),
        "inherited_cv_count": sum(state.vehicle_type == "cv" for state in cut.asset_states.values()),
        "inherited_ev_count": sum(state.vehicle_type == "ev" for state in cut.asset_states.values()),
        "orphan_started_charge_count": len(selected["orphan_started_charges"]),
        "whole_trip_committed_route_count": history["committed_route_count"],
        "whole_trip_committed_customer_count": history["committed_customer_count"],
        "max_search_evaluations": MAX_SEARCH_EVALUATIONS,
        "actual_search_evaluations": 0,
        "search_started": False,
        "continuous_scheduler_ready": gate["ready"],
        "status": "BLOCKED_PENDING_CONTINUOUS_TRIGGER_GATE",
    }
    write_csv(output / "raw_runs.csv", [raw_row])

    metadata = {
        "contract_id": P2_CONTRACT_ID,
        "artifact_status": "DRAFT_BLOCKED",
        "search_started": False,
        "search_evaluations": 0,
        "max_search_evaluations_when_unblocked": MAX_SEARCH_EVALUATIONS,
        "formal_bundle": str(E3_BUNDLE.relative_to(ROOT)),
        "formal_instance_sha256": sha256(sources["instance_path"]),
        "formal_customer_count": 221,
        "formal_fleet": {"cv": 10, "ev": 10},
        "initial_solution": str(sources["solution_path"].relative_to(ROOT)),
        "initial_solution_sha256": sha256(sources["solution_path"]),
        "initial_certificate": str(sources["certificate_path"].relative_to(ROOT)),
        "initial_certificate_file_sha256": sha256(sources["certificate_path"]),
        "initial_certificate_canonical_sha256": sources["clock"].certificate_sha256,
        "frozen_event_stream": str(EVENT_PATH.relative_to(ROOT)),
        "frozen_event_stream_sha256": sha256(EVENT_PATH),
        "frozen_owner_map": str(OWNER_PATH.relative_to(ROOT)),
        "frozen_owner_map_sha256": sha256(OWNER_PATH),
        "selection_rule": (
            "seed1 earliest add whose original stream trigger has completed, in-progress, and editable "
            "trips and no already-started charge attached to an editable trip"
        ),
        "selected_event": asdict(event),
        "selected_trigger_second": selected["trigger_second"],
        "selected_owner_depot_id": selected["owner_depot_id"],
        "certificate_cut": {
            "source_certificate_sha256": cut.source_certificate_sha256,
            "completed_route_ids": list(cut.completed_route_ids),
            "in_progress_route_ids": list(cut.in_progress_route_ids),
            "editable_route_ids": list(cut.editable_route_ids),
            "locked_charging_action_count": len(cut.locked_charging_actions),
            "asset_count": len(cut.asset_states),
        },
        "historical_accounting": history,
        "historical_accounting_interpretation": history["boundary"],
        "continuous_scheduler_gate": gate,
        "required_continuation_api": {
            "cut": (
                "cut_dynamic_certificate_at_trigger(dynamic_solution, dynamic_certificate, instance, prices, "
                "inherited_asset_states=..., previous_stage_start_second=..., trigger_second=..., "
                "inherited_locked_charging_actions=...)"
            ),
            "prepare": (
                "prepare_dynamic_multitrip_solution(..., asset_states=..., stage_start_second=..., "
                "locked_charging_actions=...)"
            ),
        },
        "future_probe_sequence_after_gate": [
            "apply only the frozen selected add event",
            "search at most 100 evaluations; no old rolling runner",
            "schedule only editable routes on the inherited 20 physical assets",
            "validate the returned dynamic certificate and zero day-minus-one charging",
            "book original departed whole trips once and future certified whole trips once",
            "require original 221 plus the added customer to close exactly with no duplicate claim",
        ],
        "explicitly_forbidden": [
            "setp_solver.search.dynamic.run_rolling_reoptimization",
            "reconstructing completed or in-progress trips as depot-customer-depot fragments",
            "inventing a physical vehicle id",
            "dropping already-started charging energy",
            "starting the search before the continuous-trigger and charging-concurrency gate passes",
        ],
    }
    write_json(output / "metadata.json", metadata)

    decision = {
        "verdict": "HALT_E7_P2_PENDING_CONTINUOUS_TRIGGER_GATE",
        "passed": False,
        "ready_for_search": False,
        "search_started": False,
        "search_evaluations": 0,
        "mechanical_input_preflight_passed": True,
        "continuous_scheduler_gate_ready": gate["ready"],
        "blockers": gate["reasons"],
        "boundary": (
            "The source cut and irreversible whole-trip commitment ledger close. "
            "No dynamic continuation or E7 result has been produced."
        ),
    }
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(
        "\n".join(
            [
                "# E7 P2 单事件小探针草案",
                "",
                "判决：`HALT_E7_P2_PENDING_CONTINUOUS_TRIGGER_GATE`。",
                "",
                "本轮只固定了小探针的输入和停止门，没有启动搜索，实际评价次数为 0。"
                f"按跑前写死的机械规则，选中 seed 1 的新增事件 {event.event_id}，"
                f"客户为 {event.customer_id}，原事件流中对应触发时刻为 {selected['trigger_second']:.3f} 秒。",
                "",
                f"该时刻原证书分成 {len(cut.completed_route_ids)} 个已返回车次、"
                f"{len(cut.in_progress_route_ids)} 个执行中车次和 {len(cut.editable_route_ids)} 个尚未发车车次。"
                "20 辆实体车的类型、所属车场、下一可用时刻、电量和下一趟编号都可从封存证书还原。"
                "已发车车次以“不可撤回的整趟运营承诺”口径记账，每趟只记一次；"
                "这不等于声称执行中车次的每一段路都已经实际发生。",
                "",
                "当前不能继续的原因是：连续两次切分后的车辆状态传递和场站同时充电容量尚未通过独立门。"
                "在该门落盘前，运行器不包含任何启动 ALNS 的代码路径，因此不可能偷跑或冒写 PASS。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = []
    for path in sorted(output.iterdir()):
        if not path.is_file() or path.name == "artifact_hashes.json" or path.name.startswith("._"):
            continue
        artifacts.append(
            {
                "path": display_path(path),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    write_json(
        output / "artifact_hashes.json",
        {
            "algorithm": "sha256",
            "excluded": ["artifact_hashes.json", "._*", "__pycache__", ".pytest_cache"],
            "artifacts": artifacts,
        },
    )
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    return decision


def write_probe_artifacts(output: Path, result: dict[str, Any]) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    for old in output.iterdir():
        if old.is_file():
            old.unlink()
    sources = result["sources"]
    selected = result["selected"]
    event: DynamicEvent = selected["event"]
    write_csv(output / "raw_runs.csv", result["rows"])
    write_json(
        output / "best_solution.json",
        {
            "routes": [asdict(route) for route in result["best_prepared_solution"].routes],
            "charging_actions": [
                asdict(action) for action in result["best_prepared_solution"].charging_actions
            ],
            "cross_site_services": [
                asdict(item) for item in result["best_prepared_solution"].cross_site_services
            ],
        },
    )
    write_json(output / "best_certificate.json", result["best_certificate"].as_dict())
    metadata = {
        "contract_id": P2_CONTRACT_ID,
        "artifact_status": "PROBE_COMPLETE",
        "purpose": "one event and one trigger, before the five-stream formal experiment",
        "search_algorithm": "TVCI-ALNS operator set with dynamic exact-asset acceptance",
        "search_evaluations": result["evaluations"],
        "maximum_search_evaluations": MAX_SEARCH_EVALUATIONS,
        "formal_bundle": str(E3_BUNDLE.relative_to(ROOT)),
        "formal_instance_sha256": sha256(sources["instance_path"]),
        "initial_solution": str(sources["solution_path"].relative_to(ROOT)),
        "initial_solution_sha256": sha256(sources["solution_path"]),
        "initial_certificate": str(sources["certificate_path"].relative_to(ROOT)),
        "initial_certificate_sha256": sha256(sources["certificate_path"]),
        "event_stream": str(EVENT_PATH.relative_to(ROOT)),
        "event_stream_sha256": sha256(EVENT_PATH),
        "owner_map": str(OWNER_PATH.relative_to(ROOT)),
        "owner_map_sha256": sha256(OWNER_PATH),
        "selected_event": asdict(event),
        "trigger_second": selected["trigger_second"],
        "starting_separate_trip_vehicle_type": result["start"]["separate_trip_vehicle_type"],
        "historical_accounting": result["history"],
        "initial_future_cost": result["initial_future_cost"],
        "best_future_cost": result["best_future_cost"],
        "initial_total_cost": result["initial_total_cost"],
        "best_total_cost": result["best_total_cost"],
        "accepted_candidate_count": result["accepted_count"],
        "changed_candidate_count": result["changed_count"],
        "dynamically_feasible_candidate_count": result["dynamically_feasible_count"],
        "operator_final_weights": result["operator_weights"],
        "interpretation_limit": (
            "This probe checks one frozen event only. It is not the E7 formal result and cannot support "
            "claims about average dynamic performance."
        ),
    }
    write_json(output / "metadata.json", metadata)
    improvement = 100.0 * (
        result["initial_future_cost"] - result["best_future_cost"]
    ) / result["initial_future_cost"]
    passed = result["changed_count"] > 0 and result["dynamically_feasible_count"] > 0
    decision = {
        "verdict": (
            "E7_P2_SINGLE_EVENT_ALNS_PROBE_PASS"
            if passed
            else "HALT_E7_P2_ALNS_PRODUCED_NO_EXECUTABLE_CHANGE"
        ),
        "passed": passed,
        "search_evaluations": result["evaluations"],
        "best_dynamic_plan_feasible": True,
        "historical_and_future_customer_accounting_closed": True,
        "initial_future_cost": result["initial_future_cost"],
        "best_future_cost": result["best_future_cost"],
        "future_cost_change_percent": improvement,
        "boundary": "one event, one trigger, one seed; formal E7 has not started",
    }
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(
        "\n".join(
            [
                "# E7 单事件小探针",
                "",
                f"判决：`{decision['verdict']}`。",
                "",
                f"在第 {selected['trigger_second']:.3f} 秒加入 1 个新订单。此前已经发车的安排保持不变，"
                "尚未发车的线路交给主算法调整。",
                f"本次只比较 {result['evaluations']} 个候选方案，其中 "
                f"{result['changed_count']} 个改变了原安排，"
                f"{result['dynamically_feasible_count']} 个能够由原有 20 辆车继续执行，"
                f"{result['accepted_count']} 个进入后续调整。",
                f"尚未执行部分的成本由 {result['initial_future_cost']:.6f} 变为 "
                f"{result['best_future_cost']:.6f}，变化 {improvement:.6f}%。",
                "",
                "已发车订单和后续订单合计恰好覆盖变化后的全部客户，没有重复、遗漏或新增车辆。",
                "本结果只说明单次订单变化可以接入主算法，不能代替五条订单流的正式实验。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts = []
    for path in sorted(output.iterdir()):
        if not path.is_file() or path.name == "artifact_hashes.json" or path.name.startswith("._"):
            continue
        artifacts.append(
            {"path": display_path(path), "sha256": sha256(path), "bytes": path.stat().st_size}
        )
    write_json(
        output / "artifact_hashes.json",
        {
            "algorithm": "sha256",
            "excluded": ["artifact_hashes.json", "._*", "__pycache__", ".pytest_cache"],
            "artifacts": artifacts,
        },
    )
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--continuous-gate", type=Path, default=DEFAULT_CONTINUOUS_GATE)
    parser.add_argument("--evaluations", type=int, default=MAX_SEARCH_EVALUATIONS)
    parser.add_argument("--draft-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.draft_only:
        build_draft(args.output, args.continuous_gate)
        return
    result = run_alns_probe(args.evaluations)
    write_probe_artifacts(args.output, result)


if __name__ == "__main__":
    main()
