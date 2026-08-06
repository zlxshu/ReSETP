#!/usr/bin/env python3
"""Build W2's fixed-total China81 fleet authority without route search.

The authority is derived under the active 2026-08-02 contract: physical
vehicles may execute multiple trips, depot charging has no shared concurrency
cap by default, and the fixed cost is billed once per physical vehicle.  Route
sequences are deterministic EDF first-feasible constructions.  For each fixed
route family, the minimum physical-vehicle count is proved by minimum path
cover in a compatibility DAG (n minus a maximum bipartite matching).
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[2]
for entry in (REPO, REPO / "solver/src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.search.multitrip_schedule import (  # noqa: E402
    _curve_for_prices,
    route_timing,
)
from setp_solver.solution import Route  # noqa: E402


AUTHORITY = (
    REPO
    / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
)
DELIVERY = REPO / "baselines/china_e3_e7/fleet_authority_v3_20260802"
STATIC = "data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723"
MATRICES = "data/ChinaInstances/china81_local_directed_matrices_corrected_v10_20260723"
PARAMETERS = "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
X4_FLEET = REPO / "docs/handoff/fleet_sizing_derivation_20260802/fleet_sizing.json"
W1 = REPO / "baselines/china_e3_e7/formula_change_20260802"
LITERATURE = REPO / "docs/handoff/multitrip_fleet_literature_20260802"
APPROVAL = REPO / "docs/handoff/model_change_approval_register_20260718.md"
HISTORICAL_AUTHORITIES = (
    REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723",
    REPO / "data/ChinaInstances/china81_finite_fleet_authority_v2_20260731",
)
LEVELS = (
    ("0", Fraction(0, 1)),
    ("25", Fraction(1, 4)),
    ("50", Fraction(1, 2)),
    ("75", Fraction(3, 4)),
    ("100", Fraction(1, 1)),
)
DEFAULT_LEVEL = "25"
HORIZON_START_SECOND = 6 * 60 * 60
TOL = 1e-6


@dataclass(frozen=True)
class TimedRoute:
    route_id: str
    vehicle_type: str
    customers: tuple[str, ...]
    demand_kg: float
    departure_second: float
    return_second: float
    drive_energy_kwh: float
    initial_charge_seconds: float


@dataclass(frozen=True)
class Cover:
    minimum_vehicles: int
    maximum_matching: int
    compatibility_edges: int
    maximum_simultaneous_trips: int
    chains: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Candidate:
    family: str
    split_index: int
    cv_routes: tuple[TimedRoute, ...]
    ev_routes: tuple[TimedRoute, ...]
    cv_cover: Cover
    ev_cover: Cover

    @property
    def physical_total(self) -> int:
        return self.cv_cover.minimum_vehicles + self.ev_cover.minimum_vehicles


@dataclass
class DepotModel:
    instance_id: str
    depot_id: str
    city: str
    customer_ids: tuple[str, ...]
    total_demand_kg: float
    payload_lower_bound_cv: int
    payload_lower_bound_ev: int
    base_cv: tuple[TimedRoute, ...]
    base_ev: tuple[TimedRoute, ...]
    endpoint_cv_cover: Cover
    endpoint_ev_cover: Cover
    candidates: tuple[Candidate, ...]
    x4_candidate_total: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(REPO))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_catalog() -> list[str]:
    with (REPO / STATIC / "instance_catalog.csv").open(
        newline="", encoding="utf-8-sig"
    ) as handle:
        return sorted(row["instance_id"] for row in csv.DictReader(handle))


def route_payload(bundle: Any, customers: Iterable[str]) -> float:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    return sum(float(nodes[item].demand) for item in customers)


def make_timed_route(
    bundle: Any,
    depot_id: str,
    customers: list[str],
    vehicle_type: str,
    route_id: str,
) -> TimedRoute | None:
    demand = route_payload(bundle, customers)
    capacity = bundle.instance.payload_capacity_kg(
        vehicle_type,
        fallback=float(bundle.prices.Q_capacity),
    )
    if demand > capacity + TOL:
        return None
    route = Route(
        vehicle_id=route_id,
        vehicle_type=vehicle_type,
        home_depot_id=depot_id,
        node_sequence=[depot_id, *customers, depot_id],
    )
    try:
        timing = route_timing(route, bundle.instance, bundle.prices)
    except ValueError:
        return None
    energy = float(timing.drive_energy_kwh)
    initial_charge_seconds = 0.0
    if vehicle_type == "ev":
        battery = bundle.instance.battery_capacity_kwh(
            fallback=float(bundle.prices.B_battery_kwh)
        )
        if energy > battery + TOL:
            return None
        curve = _curve_for_prices(bundle.prices, bundle.instance)
        initial_charge_seconds = curve.duration_seconds(0.0, energy)
        if (
            HORIZON_START_SECOND + initial_charge_seconds
            > float(timing.earliest_departure_second) + TOL
        ):
            return None
    return TimedRoute(
        route_id=route_id,
        vehicle_type=vehicle_type,
        customers=tuple(customers),
        demand_kg=demand,
        departure_second=float(timing.earliest_departure_second),
        return_second=float(timing.return_second),
        drive_energy_kwh=energy,
        initial_charge_seconds=initial_charge_seconds,
    )


def pack(
    bundle: Any,
    depot_id: str,
    customer_ids: Iterable[str],
    vehicle_type: str,
    prefix: str,
) -> tuple[TimedRoute, ...]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    ordered = sorted(
        customer_ids,
        key=lambda item: (
            float(nodes[item].due_time),
            float(nodes[item].ready_time),
            item,
        ),
    )
    groups: list[list[str]] = []
    for customer_id in ordered:
        for index, group in enumerate(groups):
            candidate = make_timed_route(
                bundle,
                depot_id,
                [*group, customer_id],
                vehicle_type,
                f"{prefix}-{index + 1:03d}",
            )
            if candidate is not None:
                group.append(customer_id)
                break
        else:
            if make_timed_route(
                bundle,
                depot_id,
                [customer_id],
                vehicle_type,
                f"{prefix}-{len(groups) + 1:03d}",
            ) is None:
                raise RuntimeError(
                    f"single-customer route infeasible: "
                    f"{bundle.instance_id}/{depot_id}/{customer_id}/{vehicle_type}"
                )
            groups.append([customer_id])
    routes = tuple(
        make_timed_route(
            bundle,
            depot_id,
            group,
            vehicle_type,
            f"{prefix}-{index + 1:03d}",
        )
        for index, group in enumerate(groups)
    )
    if any(route is None for route in routes):
        raise RuntimeError("deterministic packing lost feasibility")
    return tuple(route for route in routes if route is not None)


def maximum_simultaneous(routes: tuple[TimedRoute, ...]) -> int:
    events: list[tuple[float, int]] = []
    for route in routes:
        events.append((route.departure_second, 1))
        events.append((route.return_second, -1))
    active = maximum = 0
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


def minimum_path_cover(
    routes: tuple[TimedRoute, ...],
    bundle: Any,
) -> Cover:
    if not routes:
        return Cover(0, 0, 0, 0, ())
    order = sorted(
        range(len(routes)),
        key=lambda index: (
            routes[index].departure_second,
            routes[index].return_second,
            routes[index].route_id,
        ),
    )
    curve = _curve_for_prices(bundle.prices, bundle.instance)
    adjacency: dict[int, list[int]] = {index: [] for index in order}
    for left_pos, left in enumerate(order):
        for right in order[left_pos + 1 :]:
            recharge = 0.0
            if routes[right].vehicle_type == "ev":
                recharge = curve.duration_seconds(
                    0.0, routes[right].drive_energy_kwh
                )
            if (
                routes[left].return_second + recharge
                <= routes[right].departure_second + TOL
            ):
                adjacency[left].append(right)
    matched_right: dict[int, int] = {}

    def augment(left: int, seen: set[int]) -> bool:
        for right in adjacency[left]:
            if right in seen:
                continue
            seen.add(right)
            if right not in matched_right or augment(matched_right[right], seen):
                matched_right[right] = left
                return True
        return False

    for left in order:
        augment(left, set())
    successor = {left: right for right, left in matched_right.items()}
    starts = [index for index in order if index not in matched_right]
    chains: list[tuple[str, ...]] = []
    for start in starts:
        chain: list[str] = []
        current = start
        while True:
            chain.append(routes[current].route_id)
            if current not in successor:
                break
            current = successor[current]
        chains.append(tuple(chain))
    matching = len(matched_right)
    return Cover(
        minimum_vehicles=len(routes) - matching,
        maximum_matching=matching,
        compatibility_edges=sum(len(value) for value in adjacency.values()),
        maximum_simultaneous_trips=maximum_simultaneous(routes),
        chains=tuple(chains),
    )


def candidate_key(candidate: Candidate) -> tuple[Any, ...]:
    return (
        candidate.physical_total,
        candidate.cv_cover.minimum_vehicles,
        candidate.ev_cover.minimum_vehicles,
        candidate.family,
        candidate.split_index,
        tuple(route.customers for route in candidate.cv_routes),
        tuple(route.customers for route in candidate.ev_routes),
    )


def build_candidates(
    bundle: Any,
    depot_id: str,
    customer_ids: tuple[str, ...],
    base_cv: tuple[TimedRoute, ...],
    base_ev: tuple[TimedRoute, ...],
) -> tuple[Candidate, ...]:
    candidates: list[Candidate] = []
    for family, base, other_type in (
        ("CV_PREFIX_THEN_EV_EDF", base_cv, "ev"),
        ("EV_PREFIX_THEN_CV_EDF", base_ev, "cv"),
    ):
        for split in range(len(base) + 1):
            chosen = base[:split]
            used = {
                customer
                for route in chosen
                for customer in route.customers
            }
            remaining = tuple(
                customer for customer in customer_ids if customer not in used
            )
            other = (
                pack(
                    bundle,
                    depot_id,
                    remaining,
                    other_type,
                    f"W2-{family}-{split:03d}-{other_type.upper()}",
                )
                if remaining
                else ()
            )
            if family.startswith("CV_"):
                cv_routes, ev_routes = chosen, other
            else:
                cv_routes, ev_routes = other, chosen
            candidates.append(
                Candidate(
                    family=family,
                    split_index=split,
                    cv_routes=cv_routes,
                    ev_routes=ev_routes,
                    cv_cover=minimum_path_cover(cv_routes, bundle),
                    ev_cover=minimum_path_cover(ev_routes, bundle),
                )
            )
    unique: dict[tuple[Any, ...], Candidate] = {}
    for candidate in candidates:
        signature = (
            tuple(route.customers for route in candidate.cv_routes),
            tuple(route.customers for route in candidate.ev_routes),
        )
        previous = unique.get(signature)
        if previous is None or candidate_key(candidate) < candidate_key(previous):
            unique[signature] = candidate
    return tuple(sorted(unique.values(), key=candidate_key))


def hamilton(
    depots: list[str], totals: tuple[int, ...], share: Fraction
) -> dict[str, int]:
    exact_total = share * sum(totals)
    target = (exact_total + Fraction(1, 2)).numerator // (
        exact_total + Fraction(1, 2)
    ).denominator
    base = [int(share * total) for total in totals]
    remainders = [share * total - base[index] for index, total in enumerate(totals)]
    left = target - sum(base)
    order = sorted(
        range(len(depots)),
        key=lambda index: (-remainders[index], depots[index]),
    )
    for index in order[:left]:
        base[index] += 1
    if sum(base) != target or any(value < 0 for value in base):
        raise RuntimeError("Hamilton allocation failed to close")
    return dict(zip(depots, base, strict=True))


def best_candidate(
    model: DepotModel, cv_cap: int, ev_cap: int
) -> Candidate | None:
    feasible = [
        candidate
        for candidate in model.candidates
        if candidate.cv_cover.minimum_vehicles <= cv_cap
        and candidate.ev_cover.minimum_vehicles <= ev_cap
    ]
    return min(feasible, key=candidate_key) if feasible else None


def compositions(
    lower: tuple[int, ...], upper: tuple[int, ...]
) -> Iterable[tuple[int, ...]]:
    maximum_extra = sum(upper) - sum(lower)
    for extra_total in range(maximum_extra + 1):
        current = [0] * len(lower)

        def visit(index: int, remaining: int) -> Iterable[tuple[int, ...]]:
            if index == len(lower):
                if remaining == 0:
                    yield tuple(
                        lower[position] + current[position]
                        for position in range(len(lower))
                    )
                return
            maximum = min(upper[index] - lower[index], remaining)
            for extra in range(maximum + 1):
                current[index] = extra
                yield from visit(index + 1, remaining - extra)

        yield from visit(0, extra_total)


def certify_vector(
    models: list[DepotModel], totals: tuple[int, ...]
) -> tuple[bool, dict[str, dict[str, Candidate | None]], list[dict[str, Any]]]:
    depots = [model.depot_id for model in models]
    witnesses: dict[str, dict[str, Candidate | None]] = {}
    violations: list[dict[str, Any]] = []
    for label, share in LEVELS:
        ev_by_depot = hamilton(depots, totals, share)
        witnesses[label] = {}
        for model, total in zip(models, totals, strict=True):
            ev_cap = ev_by_depot[model.depot_id]
            cv_cap = total - ev_cap
            candidate = best_candidate(model, cv_cap, ev_cap)
            witnesses[label][model.depot_id] = candidate
            if candidate is None:
                violations.append(
                    {
                        "level_percent": int(label),
                        "depot_id": model.depot_id,
                        "total_cap": total,
                        "cv_cap": cv_cap,
                        "ev_cap": ev_cap,
                        "minimum_observed_cv": min(
                            row.cv_cover.minimum_vehicles
                            for row in model.candidates
                        ),
                        "minimum_observed_ev": min(
                            row.ev_cover.minimum_vehicles
                            for row in model.candidates
                        ),
                        "violation": "NO_REGISTERED_ZERO_SEARCH_ROUTE_FAMILY_FITS_TYPE_CAPS",
                    }
                )
    return not violations, witnesses, violations


def route_payload_record(route: TimedRoute) -> dict[str, Any]:
    return asdict(route)


def cover_record(cover: Cover) -> dict[str, Any]:
    return asdict(cover)


def build_models(bundle: Any, x4_rows: dict[tuple[str, str], dict[str, Any]]) -> list[DepotModel]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    models: list[DepotModel] = []
    for depot_id in sorted(
        node.node_id for node in bundle.instance.nodes if node.node_type == "d"
    ):
        customer_ids = tuple(
            sorted(
                (
                    node.node_id
                    for node in bundle.instance.nodes
                    if node.node_type == "c"
                    and bundle.customer_home_depot[node.node_id] == depot_id
                ),
                key=lambda item: (
                    float(nodes[item].due_time),
                    float(nodes[item].ready_time),
                    item,
                ),
            )
        )
        base_cv = pack(bundle, depot_id, customer_ids, "cv", "W2-BASE-CV")
        base_ev = pack(bundle, depot_id, customer_ids, "ev", "W2-BASE-EV")
        cv_cover = minimum_path_cover(base_cv, bundle)
        ev_cover = minimum_path_cover(base_ev, bundle)
        total_demand = route_payload(bundle, customer_ids)
        cv_capacity = bundle.instance.payload_capacity_kg(
            "cv", fallback=float(bundle.prices.Q_capacity)
        )
        ev_capacity = bundle.instance.payload_capacity_kg(
            "ev", fallback=float(bundle.prices.Q_capacity)
        )
        candidates = build_candidates(
            bundle, depot_id, customer_ids, base_cv, base_ev
        )
        models.append(
            DepotModel(
                instance_id=bundle.instance_id,
                depot_id=depot_id,
                city=str(nodes[depot_id].city),
                customer_ids=customer_ids,
                total_demand_kg=total_demand,
                payload_lower_bound_cv=-(-int(total_demand) // int(cv_capacity)),
                payload_lower_bound_ev=-(-int(total_demand) // int(ev_capacity)),
                base_cv=base_cv,
                base_ev=base_ev,
                endpoint_cv_cover=cv_cover,
                endpoint_ev_cover=ev_cover,
                candidates=candidates,
                x4_candidate_total=int(
                    x4_rows[(bundle.instance_id, depot_id)]["candidate_total"]
                ),
            )
        )
    return models


def historical_manifest() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for root in HISTORICAL_AUTHORITIES:
        rows[relative(root)] = {
            "retained": root.is_dir(),
            "artifact_hashes_sha256": sha256(root / "artifact_hashes.json"),
            "fleet_caps_sha256": sha256(root / "fleet_caps.csv"),
            "decision_sha256": sha256(root / "decision.json"),
        }
    return rows


def artifact_manifest(root: Path) -> dict[str, Any]:
    artifacts = {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    return {
        "schema": "resetp.artifact-hashes.v1",
        "exclusions": ["artifact_hashes.json", "._*"],
        "artifacts": artifacts,
    }


def compute() -> dict[str, Any]:
    x4 = json.loads(X4_FLEET.read_text(encoding="utf-8"))
    x4_rows = {
        (row["instance_id"], row["depot_id"]): row for row in x4["rows"]
    }
    instance_records: list[dict[str, Any]] = []
    fleet_rows: list[dict[str, Any]] = []
    determinant_rows: list[dict[str, Any]] = []
    certification_rows: list[dict[str, Any]] = []
    witnesses_by_instance: dict[str, dict[str, Any]] = {}
    for instance_id in read_catalog():
        bundle = load_china81_bundle(
            REPO,
            instance_id,
            static_input_authority=STATIC,
            road_matrix_authority=MATRICES,
            runtime_parameter_authority=PARAMETERS,
        )
        models = build_models(bundle, x4_rows)
        lower = tuple(
            max(
                model.endpoint_cv_cover.minimum_vehicles,
                model.endpoint_ev_cover.minimum_vehicles,
            )
            for model in models
        )
        upper = tuple(
            max(model.x4_candidate_total, lower[index])
            for index, model in enumerate(models)
        )
        selected_totals: tuple[int, ...] | None = None
        selected_witnesses: dict[str, dict[str, Candidate | None]] | None = None
        last_violations: list[dict[str, Any]] = []
        vectors_checked = 0
        for totals in compositions(lower, upper):
            vectors_checked += 1
            passed, witnesses, violations = certify_vector(models, totals)
            last_violations = violations
            if passed:
                selected_totals = totals
                selected_witnesses = witnesses
                break
        if selected_totals is None or selected_witnesses is None:
            raise RuntimeError(
                f"no zero-search authority vector for {instance_id}: "
                f"{last_violations}"
            )
        depots = [model.depot_id for model in models]
        level_allocations = {
            label: hamilton(depots, selected_totals, share)
            for label, share in LEVELS
        }
        instance_record = {
            "instance_id": instance_id,
            "lower_vector": dict(zip(depots, lower, strict=True)),
            "selected_vector": dict(zip(depots, selected_totals, strict=True)),
            "upper_vector": dict(zip(depots, upper, strict=True)),
            "vectors_checked": vectors_checked,
            "selected_total": sum(selected_totals),
            "x4_single_trip_total": sum(model.x4_candidate_total for model in models),
            "minimality_scope": (
                "minimum total physical-fleet vector over the registered two "
                "deterministic EDF prefix route families; lower endpoint covers "
                "are exact DAG path-cover minima; ties use depot-id lexicographic order"
            ),
        }
        instance_records.append(instance_record)
        witness_payload: dict[str, Any] = {
            "schema": "resetp.china81-fleet-authority-v3-witness.v1",
            "instance_id": instance_id,
            "selected_totals": instance_record["selected_vector"],
            "levels": {},
        }
        default_ev = level_allocations[DEFAULT_LEVEL]
        for index, model in enumerate(models):
            total = selected_totals[index]
            allocations = {
                label: {
                    "num_ev": level_allocations[label][model.depot_id],
                    "num_cv": total - level_allocations[label][model.depot_id],
                    "total_fleet_cap": total,
                }
                for label, _ in LEVELS
            }
            determinant_rows.append(
                {
                    "instance_id": instance_id,
                    "depot_id": model.depot_id,
                    "city": model.city,
                    "customer_count": len(model.customer_ids),
                    "total_demand_kg": f"{model.total_demand_kg:.9f}",
                    "cv_payload_lower_bound": model.payload_lower_bound_cv,
                    "ev_payload_lower_bound": model.payload_lower_bound_ev,
                    "base_cv_trip_count": len(model.base_cv),
                    "base_ev_trip_count": len(model.base_ev),
                    "endpoint_cv_min_physical": model.endpoint_cv_cover.minimum_vehicles,
                    "endpoint_ev_min_physical": model.endpoint_ev_cover.minimum_vehicles,
                    "endpoint_cv_max_matching": model.endpoint_cv_cover.maximum_matching,
                    "endpoint_ev_max_matching": model.endpoint_ev_cover.maximum_matching,
                    "endpoint_cv_compatibility_edges": model.endpoint_cv_cover.compatibility_edges,
                    "endpoint_ev_compatibility_edges": model.endpoint_ev_cover.compatibility_edges,
                    "endpoint_cv_max_simultaneous": model.endpoint_cv_cover.maximum_simultaneous_trips,
                    "endpoint_ev_max_simultaneous": model.endpoint_ev_cover.maximum_simultaneous_trips,
                    "candidate_route_families": len(model.candidates),
                    "endpoint_lower_Td": lower[index],
                    "selected_Td": total,
                    "x4_single_trip_Td": model.x4_candidate_total,
                    "added_above_endpoint_lower": total - lower[index],
                    "search_evaluations": 0,
                    "route_search_executed": False,
                }
            )
            fleet_rows.append(
                {
                    "instance_id": instance_id,
                    "depot_id": model.depot_id,
                    "city": model.city,
                    "base_all_cv_routes_Rd": len(model.base_cv),
                    "base_all_ev_routes_Re": len(model.base_ev),
                    "num_cv": total - default_ev[model.depot_id],
                    "num_ev": default_ev[model.depot_id],
                    "total_fleet_cap": total,
                    "default_electrification_level_percent": int(DEFAULT_LEVEL),
                    "depot_charger_count": 2,
                    "depot_charge_power_kw": "22.0",
                    "depot_charger_capacity_default": "UNBOUNDED",
                    "fleet_parameter_class": "DERIVED_FIXED_TOTAL_MULTITRIP_ZERO_SEARCH_AUTHORITY",
                    "charger_parameter_class": "UNBOUNDED_DEFAULT__FINITE_2_OPTIONAL_HISTORICAL",
                    "level_allocations_json": json.dumps(
                        allocations,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
        for label, share in LEVELS:
            level_depots: dict[str, Any] = {}
            instance_violations: list[dict[str, Any]] = []
            ev_by_depot = level_allocations[label]
            for index, model in enumerate(models):
                candidate = selected_witnesses[label][model.depot_id]
                if candidate is None:
                    instance_violations.append(
                        {
                            "depot_id": model.depot_id,
                            "violation": "MISSING_SELECTED_WITNESS",
                        }
                    )
                    continue
                total = selected_totals[index]
                level_depots[model.depot_id] = {
                    "total_cap": total,
                    "cv_cap": total - ev_by_depot[model.depot_id],
                    "ev_cap": ev_by_depot[model.depot_id],
                    "witness_family": candidate.family,
                    "split_index": candidate.split_index,
                    "cv_trip_count": len(candidate.cv_routes),
                    "ev_trip_count": len(candidate.ev_routes),
                    "cv_min_physical": candidate.cv_cover.minimum_vehicles,
                    "ev_min_physical": candidate.ev_cover.minimum_vehicles,
                    "cv_cover": cover_record(candidate.cv_cover),
                    "ev_cover": cover_record(candidate.ev_cover),
                    "cv_routes": [route_payload_record(route) for route in candidate.cv_routes],
                    "ev_routes": [route_payload_record(route) for route in candidate.ev_routes],
                }
            status = "CERTIFIED" if not instance_violations else "NOT_CERTIFIED"
            witness_payload["levels"][label] = {
                "target_ev_share": float(share),
                "hamilton_ev_by_depot": ev_by_depot,
                "status": status,
                "violations": instance_violations,
                "depots": level_depots,
            }
            certification_rows.append(
                {
                    "record_type": "fleet_authority_zero_search_certification",
                    "record_id": f"W2/{instance_id}/ev_share_{label}",
                    "instance_id": instance_id,
                    "target_ev_share": f"{float(share):.2f}",
                    "target_ev_percent": int(label),
                    "depot_count": len(models),
                    "total_fleet_cap": sum(selected_totals),
                    "target_ev_available": sum(ev_by_depot.values()),
                    "target_cv_available": sum(selected_totals) - sum(ev_by_depot.values()),
                    "physical_cv_used": sum(
                        level_depots[model.depot_id]["cv_min_physical"]
                        for model in models
                        if model.depot_id in level_depots
                    ),
                    "physical_ev_used": sum(
                        level_depots[model.depot_id]["ev_min_physical"]
                        for model in models
                        if model.depot_id in level_depots
                    ),
                    "violation_count": len(instance_violations),
                    "violations_json": json.dumps(
                        instance_violations,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "status": status,
                    "route_search_executed": False,
                    "search_evaluations": 0,
                }
            )
        witnesses_by_instance[instance_id] = witness_payload
    counts = {
        label: sum(
            row["target_ev_percent"] == int(label) and row["status"] == "CERTIFIED"
            for row in certification_rows
        )
        for label, _ in LEVELS
    }
    if len(certification_rows) != 405 or counts != {label: 81 for label, _ in LEVELS}:
        raise RuntimeError(f"W2 certification coverage failed: rows={len(certification_rows)}, {counts}")
    return {
        "fleet_rows": fleet_rows,
        "determinant_rows": determinant_rows,
        "certification_rows": certification_rows,
        "instance_records": instance_records,
        "witnesses_by_instance": witnesses_by_instance,
        "counts": counts,
        "historical": historical_manifest(),
    }


def materialize(payload: dict[str, Any]) -> None:
    if AUTHORITY.exists() or DELIVERY.exists():
        raise RuntimeError(
            f"refusing to overwrite W2 output: authority={AUTHORITY.exists()}, "
            f"delivery={DELIVERY.exists()}"
        )
    AUTHORITY.mkdir(parents=True)
    DELIVERY.mkdir(parents=True)
    write_csv(AUTHORITY / "fleet_caps.csv", payload["fleet_rows"])
    write_csv(AUTHORITY / "fleet_determinants.csv", payload["determinant_rows"])
    write_csv(
        AUTHORITY / "zero_search_certification.csv",
        payload["certification_rows"],
    )
    for instance_id, witness in payload["witnesses_by_instance"].items():
        write_json(AUTHORITY / "witnesses" / f"{instance_id}.json", witness)
    authority_decision = {
        "schema": "resetp.china81-finite-fleet-authority.v3",
        "verdict": "PASS_FIXED_TOTAL_MULTITRIP_FIVE_LEVEL_ZERO_SEARCH_AUTHORITY",
        "authority_id": "china81_finite_fleet_authority_v3_20260802",
        "default_level_percent": int(DEFAULT_LEVEL),
        "certified_instances_by_level": payload["counts"],
        "instances": 81,
        "depot_rows": len(payload["fleet_rows"]),
        "certification_units": len(payload["certification_rows"]),
        "route_search_executed": False,
        "search_evaluations": 0,
        "formal_search_allowed": False,
        "old_formula_status": "SUPERSEDED_RETAINED_HISTORY_ONLY",
        "old_formula": "num_ev=max(1,ceil(0.25*R_d))",
    }
    write_json(AUTHORITY / "decision.json", authority_decision)
    write_json(
        AUTHORITY / "metadata.json",
        {
            "schema": "resetp.china81-finite-fleet-authority.metadata.v3",
            "builder": relative(Path(__file__)),
            "static_authority": STATIC,
            "matrix_authority": MATRICES,
            "runtime_parameter_authority": PARAMETERS,
            "w1_decision_sha256": sha256(W1 / "decision.json"),
            "literature_artifact_hashes_sha256": sha256(
                LITERATURE / "artifact_hashes.json"
            ),
            "approval_register_sha256": sha256(APPROVAL),
            "historical_authorities": payload["historical"],
            "depot_charger_capacity_default": "UNBOUNDED",
            "physical_vehicle_fixed_cost_cny": 170.0,
            "route_search_executed": False,
            "search_evaluations": 0,
        },
    )
    write_json(
        AUTHORITY / "manifest.json",
        {
            "schema": "resetp.china81-fleet-authority-manifest.v3",
            "authority": relative(AUTHORITY),
            "status": authority_decision["verdict"],
            "default_file": "fleet_caps.csv",
            "determinants_file": "fleet_determinants.csv",
            "certification_file": "zero_search_certification.csv",
            "witness_glob": "witnesses/*.json",
            "historical_authorities_retained": payload["historical"],
        },
    )
    (AUTHORITY / "report.md").write_text(
        "# China81 车队 authority v3（2026-08-02）\n\n"
        "旧 `num_ev=max(1,ceil(0.25*R_d))` 已废止但 v1/v2 与哈希完整保留。"
        "v3 在固定总量、多趟、车场并发默认不设、实体车计费合同下，以确定性 EDF "
        "路线族和兼容 DAG 最小路径覆盖推导实体车数。五档采用 Hamilton 最大余数分配；"
        "81×5=405 个单元全部零搜索认证。这里的最小性严格限于登记的两族确定性路线"
        "见证，不冒充所有可能路径的全局车队最优。\n",
        encoding="utf-8",
    )
    write_json(AUTHORITY / "artifact_hashes.json", artifact_manifest(AUTHORITY))

    write_csv(DELIVERY / "raw_runs.csv", payload["certification_rows"])
    write_json(
        DELIVERY / "metadata.json",
        {
            "schema": "resetp.w2-fleet-authority-v3.metadata.v1",
            "task_id": "W2",
            "builder": relative(Path(__file__)),
            "authority": relative(AUTHORITY),
            "authority_manifest_sha256": sha256(AUTHORITY / "manifest.json"),
            "authority_artifact_hashes_sha256": sha256(
                AUTHORITY / "artifact_hashes.json"
            ),
            "historical_authorities": payload["historical"],
            "route_search_executed": False,
            "search_evaluations": 0,
        },
    )
    write_json(
        DELIVERY / "decision.json",
        {
            "schema": "resetp.w2-fleet-authority-v3.decision.v1",
            "fleet_authority_status": "COMPLETE",
            "certified_instances_by_level": payload["counts"],
            "certification_units": 405,
            "violating_units": 0,
            "authority_depot_rows": len(payload["fleet_rows"]),
            "authority_total_physical_cap": sum(
                int(row["total_fleet_cap"]) for row in payload["fleet_rows"]
            ),
            "x4_single_trip_total": sum(
                int(record["x4_single_trip_total"])
                for record in payload["instance_records"]
            ),
            "route_search_executed": False,
            "search_evaluations": 0,
            "terminal_status_pending_regression": True,
        },
    )
    write_json(
        DELIVERY / "fleet_minimality.json",
        {
            "schema": "resetp.w2-fleet-minimality.v1",
            "instances": payload["instance_records"],
            "depot_rows": payload["determinant_rows"],
        },
    )
    (DELIVERY / "report.md").write_text(
        "# W2 车队 authority v3 执行报告（待回归收口）\n\n"
        "车队 authority 构造已完成：五档为 81/81/81/81/81，405 个单元无"
        "违反项，路径搜索与正式实验均为 0。冻结重锚、旧结果逐包登记和全量回归"
        "将在本目录最终收口前补入。\n",
        encoding="utf-8",
    )
    write_json(
        DELIVERY / "done.json",
        {
            "task_id": "W2",
            "status": "W2_IN_PROGRESS_PENDING_REANCHOR_REGISTER_REGRESSION",
            "fleet_authority_complete": True,
            "route_search_executed": False,
            "search_evaluations": 0,
        },
    )
    write_json(DELIVERY / "artifact_hashes.json", artifact_manifest(DELIVERY))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    payload = compute()
    summary = {
        "certified_instances_by_level": payload["counts"],
        "certification_units": len(payload["certification_rows"]),
        "depot_rows": len(payload["fleet_rows"]),
        "authority_total_physical_cap": sum(
            int(row["total_fleet_cap"]) for row in payload["fleet_rows"]
        ),
        "x4_single_trip_total": sum(
            int(record["x4_single_trip_total"])
            for record in payload["instance_records"]
        ),
        "route_search_executed": False,
        "search_evaluations": 0,
        "audit_only": args.audit_only,
    }
    if not args.audit_only:
        materialize(payload)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
