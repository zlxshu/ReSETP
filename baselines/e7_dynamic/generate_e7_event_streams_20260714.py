#!/usr/bin/env python3
"""Freeze the five zero-search E7 event streams on the formal 221-customer asset.

This program only constructs exogenous events and verifies their provenance.
It does not call a route search, inspect later E7 results, or modify the frozen
E3/E6 inputs.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, fields
import hashlib
import json
from pathlib import Path
import random
import subprocess
from typing import Any

from baselines.e3_ablation import e3_v3_runner as legacy
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.certificate_execution import build_certificate_execution_ledger
from setp_solver.search.dynamic import DynamicEvent, RollingParameters, _build_trigger_batches
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import MultiTripCertificate, ScheduledTrip


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "baselines/e7_dynamic/e7_v2_20260714/event_streams"
FORMAL_BUNDLE = (
    ROOT
    / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets"
    / "L-main-threeshift-100c-01/bundle"
)
DONOR_BUNDLE = (
    ROOT
    / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets"
    / "L-main-threeshift-200c-01/bundle"
)
DONOR_SCENARIO_ID = "L-main-threeshift-200c-01"
ACTIVE_REJECTED_INSTANCE = (
    ROOT / "models/data_bundle/generated_instances/L-main/L-main-threeshift-100c-01/instance.json"
)
GEOGRAPHIC_OWNERS = (
    ROOT
    / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713/ownership_maps"
    / "L-main-threeshift-100c-01__geographic.csv"
)
E6_ROOT = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"

SEEDS = (1, 2, 3, 4, 5)
COUNTS = {"add": 22, "cancel": 11, "demand_change": 22}
PARAMS = RollingParameters()
HORIZON_SECONDS = PARAMS.delta_t_seconds * PARAMS.stages
ACTION_MARGIN_SECONDS = 60.0
CONTRACT_ID = "E7_EVENT_STREAM_FREEZE_V3_SERVICE_TIME"
EVENT_IDENTITY_SHA256 = "cb81442db4225fa5f38562372a019afac1f481fa195f6256069681b821b8d391"
FORMAL_REFERENCE_LABELS = ("no_loss_seed1", "independent_seed1")
SUPERSEDED_DECISION_SHA256 = "ad186d8e08b17a10bf4da1bc4b9ae644893e0dd9eaf1f6b995d678f016897867"
SUPERSEDED_METADATA_SHA256 = "5210f4970d11893a4dd98552ef9ccb73eb2764d6680352798c943bc0bba11077"
SUPERSEDED_V2_DECISION_SHA256 = "bf60dbd789b15b9905aab30eecbd347036d1d60ddc6821d1d281d3dab4eb0ce2"
SUPERSEDED_V2_METADATA_SHA256 = "87646a9da4b2a0d30391e60b33fa4703a46ebccdc55f46b4c1eb355fd9d6440b"


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


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
    *,
    delimiter: str = ",",
    lineterminator: str = "\r\n",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter=delimiter,
            lineterminator=lineterminator,
        )
        writer.writeheader()
        writer.writerows(rows)


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


def reference_departure_times(instance: Any, prices: Any) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
    """Return customer trip-departure clocks from the six sealed certificates.

    Only the fixed seed-1 no-loss and independent plans are formal E7 starting
    points.  The other four plans remain in the ledger solely to explain why
    the superseded six-plan draft was structurally too restrictive.
    """

    customer_ids = {
        node.node_id for node in instance.nodes if node.node_type.lower() == "c"
    }
    by_customer: dict[str, dict[str, float]] = {customer_id: {} for customer_id in customer_ids}
    sources: list[dict[str, Any]] = []
    for arm in ("no_loss", "independent"):
        for seed in (1, 2, 3):
            label = f"{arm}_seed{seed}"
            stem = f"L-main-threeshift-100c-01__geographic__seed{seed}__{arm}"
            solution_path = E6_ROOT / "solutions" / f"{stem}.json"
            certificate_path = E6_ROOT / "certificates" / f"{stem}.json"
            solution = solution_from_dict(json.loads(solution_path.read_text(encoding="utf-8")))
            certificate = load_certificate(certificate_path)
            ledger = build_certificate_execution_ledger(solution, certificate, instance, prices)
            observed: dict[str, float] = {}
            for trip in ledger.routes.values():
                for node in trip.nodes:
                    if node.node_id in customer_ids:
                        if node.node_id in observed:
                            raise RuntimeError(f"{label} serves {node.node_id} more than once")
                        observed[node.node_id] = float(trip.departure_second)
            if set(observed) != customer_ids:
                raise RuntimeError(f"{label} customer coverage does not close")
            for customer_id, departure_second in observed.items():
                by_customer[customer_id][label] = departure_second
            sources.append(
                {
                    "label": label,
                    "arm": arm,
                    "seed": seed,
                    "solution_path": str(solution_path.relative_to(ROOT)),
                    "solution_sha256": sha256(solution_path),
                    "certificate_path": str(certificate_path.relative_to(ROOT)),
                    "certificate_file_sha256": sha256(certificate_path),
                    "certificate_canonical_sha256": ledger.certificate_sha256,
                    "route_count": len(ledger.routes),
                    "customer_count": len(observed),
                    "e7_role": (
                        "formal_fixed_initial_plan"
                        if label in FORMAL_REFERENCE_LABELS
                        else "superseded_six_plan_audit_only"
                    ),
                }
            )
    return by_customer, sources


def load_geographic_owners() -> dict[str, str]:
    with GEOGRAPHIC_OWNERS.open(newline="", encoding="utf-8") as handle:
        return {str(row["customer_id"]): str(row["owner_depot_id"]) for row in csv.DictReader(handle)}


def nearest_owner(node: Any, depots: list[Any]) -> str:
    return min(
        depots,
        key=lambda depot: (
            (float(node.x) - float(depot.x)) ** 2 + (float(node.y) - float(depot.y)) ** 2,
            str(depot.node_id),
        ),
    ).node_id


def donor_is_directly_actionable(donor: Any, trigger_second: float, depots: list[Any], prices: Any, service: float) -> bool:
    speed = float(prices.v_speed_ms)
    for depot in depots:
        distance = ((float(donor.x) - float(depot.x)) ** 2 + (float(donor.y) - float(depot.y)) ** 2) ** 0.5
        travel = distance / speed
        arrival = float(trigger_second) + travel
        start = max(arrival, float(donor.ready_time))
        finish = start + service + travel
        if start <= float(donor.due_time) + 1e-9 and finish <= float(depot.due_time) + 1e-9:
            return True
    return False


def trigger_by_event_id(times: list[float]) -> dict[str, float]:
    dummy = [
        DynamicEvent(
            event_id=str(index),
            event_type="add",
            t_appear=float(second),
            customer_id=f"DUMMY{index}",
            old_demand=0.0,
            new_demand=1.0,
        )
        for index, second in enumerate(times, start=1)
    ]
    batches = _build_trigger_batches(dummy, PARAMS)
    mapping = {
        event.event_id: float(batch["trigger_time"])
        for batch in batches
        for event in batch["events"]
    }
    if len(mapping) != len(times):
        raise RuntimeError("trigger batching lost an event")
    return mapping


def generate_stream(
    seed: int,
    base: Any,
    donor_instance: Any,
    prices: Any,
    owners: dict[str, str],
    departure_times: dict[str, dict[str, float]],
) -> tuple[list[DynamicEvent], dict[str, str], list[dict[str, Any]]]:
    rng = random.Random(seed)
    labels = [event_type for event_type, count in COUNTS.items() for _ in range(count)]
    rng.shuffle(labels)
    times = sorted(rng.uniform(0.05 * HORIZON_SECONDS, 0.95 * HORIZON_SECONDS) for _ in labels)
    triggers = trigger_by_event_id(times)

    base_customers = {
        node.node_id: node for node in base.nodes if node.node_type.lower() == "c"
    }
    depots = sorted(
        (node for node in base.nodes if node.node_type.lower() == "d"),
        key=lambda node: node.node_id,
    )
    base_coordinates = {
        (round(float(node.x), 3), round(float(node.y), 3)) for node in base_customers.values()
    }
    donor_pool = [
        node
        for node in donor_instance.nodes
        if node.node_type.lower() == "c"
        and (round(float(node.x), 3), round(float(node.y), 3)) not in base_coordinates
    ]
    donor_pool.sort(key=lambda node: node.node_id)
    runtime_service = sum(float(node.service_time) for node in base_customers.values()) / len(base_customers)

    used_existing: set[str] = set()
    used_donors: set[tuple[str, float, float, float, float]] = set()
    stream_owners = dict(owners)
    events: list[DynamicEvent] = []
    audit_rows: list[dict[str, Any]] = []
    plan_labels = FORMAL_REFERENCE_LABELS

    # Allocate existing-customer targets from the latest trigger backwards.
    # Late triggers have the fewest trips that are still legally reversible;
    # assigning early events first can consume those scarce targets and create
    # an avoidable shortage.  This order is fixed before any E7 search result.
    existing_target_by_event_id: dict[str, str] = {}
    existing_slots = [
        (str(index), event_type, float(appearance), float(triggers[str(index)]))
        for index, (event_type, appearance) in enumerate(zip(labels, times), start=1)
        if event_type != "add"
    ]
    for event_id, event_type, _appearance, trigger in sorted(
        existing_slots,
        key=lambda row: (row[3], int(row[0])),
        reverse=True,
    ):
        eligible = [
            customer_id
            for customer_id in sorted(base_customers)
            if customer_id not in used_existing
            and all(
                departure_times[customer_id][label] > trigger + ACTION_MARGIN_SECONDS
                for label in plan_labels
            )
        ]
        if not eligible:
            raise RuntimeError(
                f"seed {seed} cannot place event {event_id} ({event_type}) before trip departure "
                f"at trigger {trigger:.3f} in both fixed seed-1 starting plans"
            )
        customer_id = rng.choice(eligible)
        existing_target_by_event_id[event_id] = customer_id
        used_existing.add(customer_id)

    for index, (event_type, appearance) in enumerate(zip(labels, times), start=1):
        event_id = str(index)
        trigger = triggers[event_id]
        if event_type == "add":
            candidates = [
                node
                for node in donor_pool
                if (
                    str(node.node_id),
                    float(node.x),
                    float(node.y),
                    float(node.ready_time),
                    float(node.due_time),
                )
                not in used_donors
                and donor_is_directly_actionable(node, trigger, depots, prices, runtime_service)
            ]
            if not candidates:
                raise RuntimeError(f"seed {seed} has no exact-window donor for trigger {trigger:.3f}")
            donor = rng.choice(candidates)
            donor_key = (
                str(donor.node_id),
                float(donor.x),
                float(donor.y),
                float(donor.ready_time),
                float(donor.due_time),
            )
            used_donors.add(donor_key)
            customer_id = f"N_S{seed}_{len(used_donors):03d}"
            owner = nearest_owner(donor, depots)
            stream_owners[customer_id] = owner
            event = DynamicEvent(
                event_id=event_id,
                event_type="add",
                t_appear=float(appearance),
                customer_id=customer_id,
                old_demand=0.0,
                new_demand=float(donor.demand),
                x=float(donor.x),
                y=float(donor.y),
                delta_demand=float(donor.demand),
                old_ready_time=float(donor.ready_time),
                old_due_time=float(donor.due_time),
                new_ready_time=float(donor.ready_time),
                new_due_time=float(donor.due_time),
                demand_source="frozen_sister_bundle_exact",
                time_window_source="frozen_sister_bundle_exact",
                donor_instance_id=DONOR_SCENARIO_ID,
                donor_customer_id=str(donor.node_id),
                new_service_time=float(donor.service_time),
                service_time_source="frozen_sister_bundle_exact",
                source="frozen_e3_sister_bundle_overlay",
                seed=seed,
            )
            min_service = ""
            margin = ""
            donor_service = float(donor.service_time)
            actionable = donor_is_directly_actionable(
                donor,
                trigger,
                depots,
                prices,
                donor_service,
            )
            donor_exact = True
            old_customer_owner = ""
        else:
            customer_id = existing_target_by_event_id[event_id]
            node = base_customers[customer_id]
            old_demand = float(node.demand)
            new_demand = 0.0 if event_type == "cancel" else old_demand * rng.uniform(0.85, 1.15)
            event = DynamicEvent(
                event_id=event_id,
                event_type=event_type,
                t_appear=float(appearance),
                customer_id=customer_id,
                old_demand=old_demand,
                new_demand=float(new_demand),
                x=float(node.x),
                y=float(node.y),
                delta_demand=float(new_demand - old_demand),
                old_ready_time=float(node.ready_time),
                old_due_time=float(node.due_time),
                new_ready_time=float(node.ready_time),
                new_due_time=float(node.due_time),
                demand_source="frozen_base_customer",
                time_window_source="frozen_base_customer",
                source="frozen_e3_base_overlay",
                service_time_source="existing_customer",
                seed=seed,
            )
            min_departure_value = min(
                departure_times[customer_id][label] for label in plan_labels
            )
            min_service = float(min_departure_value)
            margin = float(min_departure_value - trigger)
            actionable = all(
                departure_times[customer_id][label] > trigger + ACTION_MARGIN_SECONDS
                for label in plan_labels
            )
            donor_exact = ""
            owner = owners[customer_id]
            old_customer_owner = owner
            donor_service = ""
        events.append(event)
        audit_rows.append(
            {
                "stream_id": f"stream_seed{seed}",
                "seed": seed,
                "event_id": event_id,
                "event_type": event.event_type,
                "t_appear": event.t_appear,
                "trigger_second": trigger,
                "customer_id": event.customer_id,
                "owner_depot_id": owner,
                "old_customer_owner": old_customer_owner,
                "old_demand": event.old_demand,
                "new_demand": event.new_demand,
                "x": event.x,
                "y": event.y,
                "old_ready_time": event.old_ready_time,
                "old_due_time": event.old_due_time,
                "new_ready_time": event.new_ready_time,
                "new_due_time": event.new_due_time,
                "donor_instance_id": event.donor_instance_id,
                "donor_customer_id": event.donor_customer_id,
                "donor_service_time": donor_service,
                "new_service_time": event.new_service_time if event.event_type == "add" else "",
                "service_time_source": event.service_time_source,
                "minimum_formal_trip_departure_second": min_service,
                "minimum_uncommitted_margin_seconds": margin,
                "modifiable_in_both_fixed_seed1_plans": actionable,
                "donor_fields_inherited_exactly": donor_exact,
                "owner_rule_verified": True,
                "search_evaluations": 0,
                "status": "PASS" if actionable else "HALT",
            }
        )

    events.sort(key=lambda event: (event.t_appear, event.event_id))
    return events, stream_owners, audit_rows


def verify_stream(
    seed: int,
    events: list[DynamicEvent],
    owners: dict[str, str],
    base: Any,
    donor_instance: Any,
    departure_times: dict[str, dict[str, float]],
    prices: Any,
) -> dict[str, Any]:
    counts = {key: sum(event.event_type == key for event in events) for key in COUNTS}
    if counts != COUNTS or len(events) != 55:
        raise RuntimeError(f"seed {seed} event composition drifted: {counts}")
    if len({event.event_id for event in events}) != len(events):
        raise RuntimeError(f"seed {seed} has duplicate event ids")
    if len({event.customer_id for event in events}) != len(events):
        raise RuntimeError(f"seed {seed} reuses an event target")

    base_customers = {node.node_id: node for node in base.nodes if node.node_type.lower() == "c"}
    donor_customers = {node.node_id: node for node in donor_instance.nodes if node.node_type.lower() == "c"}
    depots = [node for node in base.nodes if node.node_type.lower() == "d"]
    triggers = trigger_by_event_id([event.t_appear for event in events])
    action_margins: list[float] = []
    add_ids: set[str] = set()
    for event in events:
        trigger = triggers[event.event_id]
        if event.event_type == "add":
            if event.customer_id in base_customers or event.customer_id in add_ids:
                raise RuntimeError(f"seed {seed} add id collision: {event.customer_id}")
            add_ids.add(event.customer_id)
            donor = donor_customers[event.donor_customer_id]
            exact = (
                event.x == float(donor.x)
                and event.y == float(donor.y)
                and event.new_demand == float(donor.demand)
                and event.new_ready_time == float(donor.ready_time)
                and event.new_due_time == float(donor.due_time)
                and event.new_service_time == float(donor.service_time)
            )
            if not exact:
                raise RuntimeError(f"seed {seed} donor inheritance drifted for {event.customer_id}")
            if owners[event.customer_id] != nearest_owner(donor, depots):
                raise RuntimeError(f"seed {seed} owner rule drifted for {event.customer_id}")
        else:
            if event.customer_id not in base_customers:
                raise RuntimeError(f"seed {seed} existing event points outside base: {event.customer_id}")
            if event.old_demand != float(base_customers[event.customer_id].demand):
                raise RuntimeError(f"seed {seed} old demand drifted for {event.customer_id}")
            margin = min(
                departure_times[event.customer_id][label]
                for label in FORMAL_REFERENCE_LABELS
            ) - trigger
            action_margins.append(float(margin))
            if margin <= ACTION_MARGIN_SECONDS:
                raise RuntimeError(
                    f"seed {seed} changes {event.customer_id} after its trip departed in a formal plan"
                )
    return {
        "stream_id": f"stream_seed{seed}",
        "seed": seed,
        "event_count": len(events),
        "add_count": counts["add"],
        "cancel_count": counts["cancel"],
        "demand_change_count": counts["demand_change"],
        "unique_target_count": len({event.customer_id for event in events}),
        "minimum_existing_event_uncommitted_margin_seconds": min(action_margins),
        "maximum_trigger_second": max(triggers.values()),
        "owner_count": len(owners),
        "search_evaluations": 0,
        "status": "PASS",
    }


def write_stream(seed: int, events: list[DynamicEvent], owners: dict[str, str]) -> dict[str, Any]:
    stem = f"stream_seed{seed}"
    event_rows = [asdict(event) for event in events]
    event_fields = [field.name for field in fields(DynamicEvent)]
    json_path = OUTPUT_ROOT / f"{stem}.events.json"
    csv_path = OUTPUT_ROOT / f"{stem}.events.csv"
    tsv_path = OUTPUT_ROOT / f"{stem}.dynamic_events.tsv"
    owner_path = OUTPUT_ROOT / f"{stem}.owners.csv"
    write_json(json_path, event_rows)
    write_csv(csv_path, event_rows, event_fields, lineterminator="\n")
    write_csv(tsv_path, event_rows, event_fields, delimiter="\t", lineterminator="\n")
    owner_rows = [
        {"customer_id": customer_id, "owner_depot_id": owners[customer_id]}
        for customer_id in sorted(owners)
    ]
    write_csv(owner_path, owner_rows, ["customer_id", "owner_depot_id"])
    return {
        "stream_id": stem,
        "seed": seed,
        "events_json": str(json_path.relative_to(ROOT)),
        "events_json_sha256": sha256(json_path),
        "events_csv": str(csv_path.relative_to(ROOT)),
        "events_csv_sha256": sha256(csv_path),
        "dynamic_events_tsv": str(tsv_path.relative_to(ROOT)),
        "dynamic_events_tsv_sha256": sha256(tsv_path),
        "owners_csv": str(owner_path.relative_to(ROOT)),
        "owners_csv_sha256": sha256(owner_path),
    }


def event_identity_sha256(streams: list[list[DynamicEvent]]) -> str:
    """Hash the original V2 event identity while excluding V3-only fields."""

    excluded = {"new_service_time", "service_time_source"}
    rows = [
        {key: value for key, value in asdict(event).items() if key not in excluded}
        for events in streams
        for event in events
    ]
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for old in OUTPUT_ROOT.iterdir():
        if old.is_file():
            old.unlink()

    formal = load_search_bundle(FORMAL_BUNDLE)
    donor = load_search_bundle(DONOR_BUNDLE)
    prices = legacy.prices_for("M1", 0.0)
    formal_instance_path = FORMAL_BUNDLE / "instance.json"
    formal_payload = json.loads(formal_instance_path.read_text(encoding="utf-8"))
    active_payload = json.loads(ACTIVE_REJECTED_INSTANCE.read_text(encoding="utf-8"))
    formal_customers = [node for node in formal.instance.nodes if node.node_type.lower() == "c"]
    if len(formal_customers) != 221:
        raise RuntimeError(f"formal bundle has {len(formal_customers)} customers, expected 221")
    formal_fleet = (
        int(formal_payload["metadata"]["num_cv"]),
        int(formal_payload["metadata"]["num_ev"]),
    )
    active_fleet = (
        int(active_payload["metadata"]["num_cv"]),
        int(active_payload["metadata"]["num_ev"]),
    )
    if formal_fleet != (10, 10) or active_fleet != (7, 7):
        raise RuntimeError(f"formal/active fleet distinction drifted: {formal_fleet}/{active_fleet}")

    base_owners = load_geographic_owners()
    if set(base_owners) != {node.node_id for node in formal_customers}:
        raise RuntimeError("geographic owner map does not cover the formal 221 customers exactly")
    departure_times, reference_sources = reference_departure_times(formal.instance, prices)
    departure_fields = [
        "customer_id",
        *sorted(next(iter(departure_times.values()))),
        "minimum_formal_seed1_departure_second",
        "minimum_all_six_departure_second",
    ]
    departure_rows = [
        {
            "customer_id": customer_id,
            **departure_times[customer_id],
            "minimum_formal_seed1_departure_second": min(
                departure_times[customer_id][label] for label in FORMAL_REFERENCE_LABELS
            ),
            "minimum_all_six_departure_second": min(departure_times[customer_id].values()),
        }
        for customer_id in sorted(departure_times)
    ]
    write_csv(
        OUTPUT_ROOT / "reference_trip_departure_times.csv",
        departure_rows,
        departure_fields,
    )

    all_audit_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    stream_files: list[dict[str, Any]] = []
    generated_streams: list[list[DynamicEvent]] = []
    for seed in SEEDS:
        events, stream_owners, audit_rows = generate_stream(
            seed,
            formal.instance,
            donor.instance,
            prices,
            base_owners,
            departure_times,
        )
        summary = verify_stream(
            seed,
            events,
            stream_owners,
            formal.instance,
            donor.instance,
            departure_times,
            prices,
        )
        stream_files.append(write_stream(seed, events, stream_owners))
        generated_streams.append(events)
        summaries.append(summary)
        all_audit_rows.extend(audit_rows)

    audit_fields = list(all_audit_rows[0])
    write_csv(OUTPUT_ROOT / "raw_runs.csv", all_audit_rows, audit_fields, lineterminator="\n")
    write_csv(OUTPUT_ROOT / "stream_summary.csv", summaries, list(summaries[0]))
    identity_sha256 = event_identity_sha256(generated_streams)
    if identity_sha256 != EVENT_IDENTITY_SHA256:
        raise RuntimeError(
            f"event identity drifted: {identity_sha256}, expected {EVENT_IDENTITY_SHA256}"
        )
    write_json(
        OUTPUT_ROOT / "manifest.json",
        {
            "contract_id": CONTRACT_ID,
            "schema_source": "setp_solver.search.dynamic.DynamicEvent",
            "event_identity_sha256_excluding_v3_fields": identity_sha256,
            "supersedes_contract_id": "E7_EVENT_STREAM_FREEZE_V2_DEPARTURE_LOCK",
            "supersession_reason": "V2 omitted donor service time",
            "streams": stream_files,
        },
    )

    metadata = {
        "contract_id": CONTRACT_ID,
        "status": "FROZEN",
        "supersedes": {
            "contract_id": "E7_EVENT_STREAM_FREEZE_V2_DEPARTURE_LOCK",
            "decision_sha256": SUPERSEDED_V2_DECISION_SHA256,
            "metadata_sha256": SUPERSEDED_V2_METADATA_SHA256,
            "reason": (
                "V2 omitted donor service time and runtime silently substituted the base-customer mean"
            ),
        },
        "generation_date": "2026-07-14",
        "git_head_before_event_stream_commit": git_head(),
        "generator_script": str(Path(__file__).resolve().relative_to(ROOT)),
        "generator_script_sha256": sha256(Path(__file__).resolve()),
        "dynamic_schema_source": "solver/src/setp_solver/search/dynamic.py",
        "dynamic_schema_source_sha256": sha256(ROOT / "solver/src/setp_solver/search/dynamic.py"),
        "certificate_clock_source": "solver/src/setp_solver/search/certificate_execution.py",
        "certificate_clock_source_sha256": sha256(
            ROOT / "solver/src/setp_solver/search/certificate_execution.py"
        ),
        "search_evaluations": 0,
        "result_blind_generation": True,
        "formal_instance": "L-main-threeshift-100c-01",
        "formal_bundle": str(FORMAL_BUNDLE.relative_to(ROOT)),
        "formal_instance_sha256": sha256(formal_instance_path),
        "formal_customer_count": len(formal_customers),
        "formal_num_cv": formal_fleet[0],
        "formal_num_ev": formal_fleet[1],
        "rejected_active_instance": str(ACTIVE_REJECTED_INSTANCE.relative_to(ROOT)),
        "rejected_active_instance_sha256": sha256(ACTIVE_REJECTED_INSTANCE),
        "rejected_active_num_cv": active_fleet[0],
        "rejected_active_num_ev": active_fleet[1],
        "active_instance_rejection_reason": (
            "The active generated instance has the same 221 node geometry but only a 7+7 fleet; "
            "the E3/E6 formal solutions and certificates were built under the frozen 10+10 envelope."
        ),
        "donor_bundle": str(DONOR_BUNDLE.relative_to(ROOT)),
        "donor_instance_sha256": sha256(DONOR_BUNDLE / "instance.json"),
        "donor_rule": (
            "exact coordinate, demand, ready time, due time, and service time inherited from an unused customer "
            "in the frozen E3 200c sister bundle; no field is clamped"
        ),
        "event_identity_sha256_excluding_v3_fields": identity_sha256,
        "event_identity_sha256_expected": EVENT_IDENTITY_SHA256,
        "base_ownership_map": str(GEOGRAPHIC_OWNERS.relative_to(ROOT)),
        "base_ownership_sha256": sha256(GEOGRAPHIC_OWNERS),
        "new_customer_owner_rule": "nearest D0/D1 by Euclidean squared distance; depot id breaks an exact tie",
        "seeds": list(SEEDS),
        "events_per_stream": sum(COUNTS.values()),
        "event_counts": COUNTS,
        "ratio_source": {
            "add_ratio": PARAMS.add_ratio,
            "cancel_ratio": PARAMS.cancel_ratio,
            "demand_change_ratio": PARAMS.demand_change_ratio,
            "base_customer_count": 221,
            "rounding": "Python round; gives 22/11/22",
        },
        "rolling_parameters_used_only_for_trigger_times": asdict(PARAMS),
        "appearance_time_rule": "one seed-fixed uniform draw per event over 5%-95% of the 43200s event horizon",
        "event_type_order_rule": "the exact 22/11/22 label multiset is shuffled once per seed before time sorting",
        "formal_initial_plan_rule": (
            "all five event streams use fixed geographic seed1 initial plans: no_loss seed1 for cooperation "
            "and independent seed1 for cooperation disabled; event stream is the statistical unit and the "
            "search random seed remains paired to the stream seed"
        ),
        "formal_initial_plan_labels": list(FORMAL_REFERENCE_LABELS),
        "other_four_reference_plan_role": (
            "audit of the superseded six-plan draft only; they are not formal E7 starting points or target filters"
        ),
        "existing_target_rule": (
            "without replacement; at the corresponding q_bar/delta_t batch trigger, the complete trip carrying "
            "the customer must not yet have departed in either fixed seed1 initial plan, with a strict 60s margin"
        ),
        "existing_target_assignment_order": (
            "after labels and appearance times are drawn once, assign existing targets from latest trigger to "
            "earliest trigger so early events cannot consume the scarce late-trigger reversible trips"
        ),
        "reference_plans": reference_sources,
        "runtime_add_service_time_note": (
            "V3 stores each selected donor's exact service time. Runtime uses it when present; old event "
            "formats remain readable and fall back to the formal-instance customer mean."
        ),
        "no_post_result_selection": True,
        "not_a_dynamic_result": True,
    }
    write_json(OUTPUT_ROOT / "metadata.json", metadata)

    passed = (
        len(summaries) == 5
        and all(row["status"] == "PASS" for row in summaries)
        and len(all_audit_rows) == 275
        and all(row["status"] == "PASS" for row in all_audit_rows)
    )
    decision = {
        "verdict": "E7_EVENT_STREAMS_FROZEN" if passed else "HALT_E7_EVENT_STREAM_FREEZE",
        "passed": passed,
        "search_evaluations": 0,
        "stream_count": len(summaries),
        "events_per_stream": 55,
        "total_events": len(all_audit_rows),
        "event_counts_per_stream": COUNTS,
        "all_existing_events_modifiable_in_both_fixed_seed1_plans": all(
            row["modifiable_in_both_fixed_seed1_plans"] is True
            for row in all_audit_rows
            if row["event_type"] != "add"
        ),
        "all_donor_fields_exact": all(
            row["donor_fields_inherited_exactly"] is True
            for row in all_audit_rows
            if row["event_type"] == "add"
        ),
        "all_add_service_times_present_positive_and_donor_exact": all(
            float(row["new_service_time"]) > 0.0
            and float(row["new_service_time"]) == float(row["donor_service_time"])
            for row in all_audit_rows
            if row["event_type"] == "add"
        ),
        "all_adds_directly_actionable_with_exact_service_time": all(
            row["modifiable_in_both_fixed_seed1_plans"] is True
            for row in all_audit_rows
            if row["event_type"] == "add"
        ),
        "event_identity_sha256_excluding_v3_fields": identity_sha256,
        "all_owner_rules_verified": all(row["owner_rule_verified"] is True for row in all_audit_rows),
        "minimum_existing_event_uncommitted_margin_seconds": min(
            float(row["minimum_uncommitted_margin_seconds"])
            for row in all_audit_rows
            if row["event_type"] != "add"
        ),
        "formal_instance_sha256": sha256(formal_instance_path),
        "formal_fleet": {"cv": formal_fleet[0], "ev": formal_fleet[1]},
        "boundary": (
            "This verdict freezes exogenous inputs only. It does not establish rolling feasibility, "
            "cost, carbon, cooperation, or fairness effects."
        ),
        "supersedes_decision_sha256": SUPERSEDED_V2_DECISION_SHA256,
        "supersession_reason": (
            "V2 omitted the selected donor's service time and therefore changed runtime semantics"
        ),
    }
    write_json(OUTPUT_ROOT / "decision.json", decision)

    report_lines = [
        "# E7 五条动态事件流冻结报告",
        "",
        f"判决：`{decision['verdict']}`。本批只生成外生事件，搜索评价次数为 0。",
        "",
        "## 冻结内容",
        "",
        "seed 1--5 各对应一条事件流。每条流 55 个事件：新增 22、取消 11、需求变化 22。"
        "这恰好是 221 个客户乘代码最初默认比例 10%/5%/10% 后的四舍五入计数，没有为后续结果改配比。",
        "",
        "正式基础是 E3 封存的 221 客户、10 辆油车+10 辆电车算例，"
        f"`instance.json` 指纹为 `{decision['formal_instance_sha256']}`。"
        "仓库活动算例虽有相同客户几何，但只有 7+7 车队，与 E3/E6 的封存方案和证书不匹配，因此明确拒用。",
        "",
        "## 机械检查",
        "",
        "本版撤销并取代 V2 的服务时长口径。V2 的事件身份和整趟发车检查没有改变，"
        "但新增订单运行时误用了原算例客户的平均停留时长。V3 为同一批已选订单补回捐赠客户原值。",
        "",
        f"275 个事件全部通过。取消和需求变化共 165 个事件，在对应重规划触发时点，"
        "其完整车次在固定的 seed1 合作起点和 seed1 各自经营起点中都尚未出发。"
        f"最小出发余量为 {decision['minimum_existing_event_uncommitted_margin_seconds']:.1f} 秒，"
        "已高于跑前写死的 60 秒门槛。",
        "",
        "五条事件流统一使用这两份 seed1 静态起点，事件流本身才是五个统计单位；"
        "搜索随机种子仍与事件流种子一一配对。其余四份旧参考方案只用于说明旧草案，"
        "不再充当正式筛选条件。客户目标在时间标签固定后按触发时刻从晚到早一次抽取，"
        "避免早期事件误占晚期仅有的可撤回车次。",
        "",
        "110 个新增事件的坐标、需求、时间窗和服务时长逐字继承自同一 E3 封存体系的 200c 姐妹算例，"
        "没有截断或人工改窗。新客户归属按到 D0/D1 的欧氏距离就近确定，若精确同距则按车场编号。",
        f"排除 V3 新增字段后，275 个事件的身份指纹仍为 `{identity_sha256}`，"
        "说明本次没有重抽事件、客户、出现时刻或归属。",
        "",
        "## 边界",
        "",
        "这一批只证明事件流的数量、来源、归属和“事件发生时整趟车尚未出发”条件闭合。"
        "它不证明动态重规划一定可行，也不证明合作、公平或择时充电一定带来改善。",
    ]
    (OUTPUT_ROOT / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    hash_rows = []
    for path in sorted(OUTPUT_ROOT.iterdir()):
        if not path.is_file() or path.name == "artifact_hashes.json" or path.name.startswith("._"):
            continue
        hash_rows.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    write_json(
        OUTPUT_ROOT / "artifact_hashes.json",
        {
            "algorithm": "sha256",
            "excluded": ["artifact_hashes.json", "._*", "__pycache__", ".pytest_cache"],
            "artifacts": hash_rows,
        },
    )
    # exFAT/macOS can materialize AppleDouble sidecars while the batch is
    # running.  They are not evidence and must not survive the freeze.
    for sidecar in OUTPUT_ROOT.glob("._*"):
        sidecar.unlink()
    if not passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
