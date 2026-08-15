#!/usr/bin/env python3
"""Build the deterministic 81-instance V3 two-shift construction suite.

This is a construction and structural-health task.  It never enters a search
solver.  New instance data are written under a new authority, while road
matrices remain in the frozen China81 matrix authority and are referenced by
source-instance/source-node identity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver" / "src"))

from setp_solver.charging_curve import (  # noqa: E402
    M17_22KW_NORMAL_PWL,
    M17_FAST_SHAPE_SCALED_60KW_PWL,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.instance_loader import (  # noqa: E402
    Instance,
    Node,
    RoadProfileMatrices,
)
from setp_solver.solution import Route, Solution, route_trip_vehicle_id  # noqa: E402


SOURCE_STATIC = REPO / (
    "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
SOURCE_MATRICES = REPO / (
    "data/ChinaInstances/"
    "china81_local_directed_matrices_corrected_v10_20260723"
)
SOURCE_ORDERS = REPO / (
    "data/ChinaInstances/"
    "china81_order_attributes_gis_v2_20260723/orders.csv"
)
SOURCE_RUNTIME = REPO / (
    "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
DEFAULT_OUTPUT = REPO / (
    "data/ChinaInstances/china81_suite_v3_20260812"
)
DEFAULT_REPORT = REPO / "solver/reports/suite_rebuild_20260812"

PROTECTED = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
)
PARAMETER_AUTHORITIES = (
    Path(
        "data/ChinaInstances/open_sources_20260717/figshare_28113608/"
        "Data%20Description.xlsx"
    ),
    Path("docs/handoff/final_algorithm_and_suite_spec_20260812.md"),
    Path("docs/paper_gci_dmm_vrp_20260804/pending_decisions.md"),
    Path("docs/handoff/instance_rebuild_literature_20260811.md"),
    Path("solver/reports/instance_rebuild_20260811/report.md"),
    Path("solver/reports/depot_power_60kw_20260811/report.md"),
    Path("solver/src/setp_solver/charging_curve.py"),
)

INSTANCE_RE = re.compile(
    r"^cn-(?P<region>cy|jjj|prd)-(?P<size>\d+)c-"
    r"(?P<replicate>\d+)-V2-LOCATIONS$"
)
SHIFT_ROWS = {
    "AM": {"start_minute": 480.0, "end_minute": 660.0},
    "PM": {"start_minute": 780.0, "end_minute": 1140.0},
}
REGION_CITIES = {
    "cy": ("chengdu", "chongqing"),
    "jjj": ("beijing", "tianjin", "shijiazhuang"),
    "prd": ("dongguan", "foshan", "guangzhou", "shenzhen"),
}
CONTEST_THRESHOLDS = (0.20, 0.25, 0.30)
MAIN_CONTEST_THRESHOLD = 0.25
CONTEST_SHARE_LOWER = 0.30
CONTEST_SHARE_UPPER = 0.45
VEHICLE_VOLUME_CAPACITY_M3 = 7.2
VEHICLE_PAYLOAD_CAPACITY_KG = 1735.0
LOADING_HOURS_PER_M3 = 0.1
EV_BATTERY_KWH = 77.28
DEPOT_POWER_KW = 60.0
CV_NON_ENERGY_CNY_PER_KM = 0.7800
EV_NON_ENERGY_CNY_PER_KM = 0.9145
EV_FIXED_PREMIUM_CNY_PER_DAY = 50.0
CV_FIXED_CNY_PER_DAY = 170.0
EV_FIXED_CNY_PER_DAY = 220.0
SCENARIO_MINUTES = {
    "valley": 180,
    "flat": 720,
    "peak": 1110,
}
FLEET_PARAMETER_CLASS_ID = "ENDOGENOUS_RD_RE_NO_ADDITIONAL_TOTAL_CAP"
GEOMETRY_PASS_MIN = 0.30
GEOMETRY_PASS_MAX = 0.45


@dataclass(frozen=True)
class ParsedIdentity:
    source_instance_id: str
    new_instance_id: str
    region: str
    size: int
    replicate: str


@dataclass(frozen=True)
class LocationFact:
    source_node_id: str
    city: str
    nearest_depot: str
    second_depot: str
    nearest_cost_cny: float
    second_cost_cny: float
    relative_gap: float


@dataclass(frozen=True)
class GeometryChoice:
    mode: str
    matrix_source_instance_id: str
    depot_ids: tuple[str, ...]
    customer_source_ids: tuple[str, ...]
    home_depot_by_source_customer: Mapping[str, str]
    attempted_rebuild: bool
    rebuild_succeeded: bool
    reanchored_customer_count: int
    note: str


@dataclass(frozen=True)
class RoutePlan:
    depot_id: str
    shift_id: str
    customers: tuple[str, ...]
    volume_m3: float
    demand_kg: float
    departure_second: float
    return_second: float
    distance_m: float


@dataclass(frozen=True)
class ScheduledPlan:
    plan: RoutePlan
    departure_second: float
    return_second: float


@dataclass(frozen=True)
class BuiltInstance:
    identity: ParsedIdentity
    source_bundle: Any
    instance: Instance
    prices: Any
    time_profile: tuple[dict[str, Any], ...]
    node_rows: tuple[dict[str, Any], ...]
    order_rows: tuple[dict[str, Any], ...]
    source_mapping_rows: tuple[dict[str, Any], ...]
    orders_by_customer: Mapping[str, Mapping[str, Any]]
    customer_home_depot: Mapping[str, str]
    geometry: GeometryChoice
    shift_assignment_flags: tuple[str, ...]


@dataclass(frozen=True)
class WitnessResult:
    status: str
    reason: str
    plans: tuple[RoutePlan, ...]
    solution: Solution | None
    departures: Mapping[str, float]
    scheduled_by_physical: Mapping[str, tuple[ScheduledPlan, ...]]
    violations: tuple[str, ...]
    served_customers: int
    served_demand_kg: float


class SourceBundleCache:
    """Small cache: only current original and three 200-customer pools persist."""

    def __init__(self) -> None:
        self._pool: dict[str, Any] = {}

    def get(self, instance_id: str) -> Any:
        bundle = self._pool.get(instance_id)
        if bundle is None:
            bundle = load_china81_bundle(REPO, instance_id)
            self._pool[instance_id] = bundle
        return bundle

    def retain_only(self, keep: Iterable[str]) -> None:
        keep_set = set(keep)
        self._pool = {
            key: value for key, value in self._pool.items() if key in keep_set
        }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    selected_fields = list(fields or (list(rows[0]) if rows else ()))
    if not selected_fields:
        raise ValueError(f"cannot write a headerless empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=selected_fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_identity(source_instance_id: str) -> ParsedIdentity:
    match = INSTANCE_RE.fullmatch(source_instance_id)
    if match is None:
        raise ValueError(f"unexpected China81 instance id: {source_instance_id}")
    region = match.group("region")
    size = int(match.group("size"))
    replicate = match.group("replicate")
    return ParsedIdentity(
        source_instance_id=source_instance_id,
        new_instance_id=(
            f"cn-{region}-{size}c-{replicate}-V3-TWO-SHIFT-FS"
        ),
        region=region,
        size=size,
        replicate=replicate,
    )


def catalog_identities() -> list[ParsedIdentity]:
    rows = read_csv(SOURCE_STATIC / "instance_catalog.csv")
    identities = [parse_identity(row["instance_id"]) for row in rows]
    if len(identities) != 81 or len({item.source_instance_id for item in identities}) != 81:
        raise RuntimeError("source catalog is not the frozen 81-instance suite")
    observed = Counter((item.region, item.size) for item in identities)
    expected = {
        (region, size): 3
        for region in ("cy", "jjj", "prd")
        for size in (10, 15, 20, 25, 50, 75, 100, 150, 200)
    }
    if observed != expected:
        raise RuntimeError("source catalog region/size/replicate structure changed")
    return sorted(
        identities,
        key=lambda item: (item.region, item.size, item.replicate),
    )


def source_orders_by_instance() -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(SOURCE_ORDERS):
        grouped[row["instance_id"]].append(row)
    return grouped


def closest_facility_pair_by_region() -> dict[str, tuple[str, str]]:
    rows = read_csv(SOURCE_STATIC / "facilities.csv")
    by_city = {row["city"]: row for row in rows}
    result: dict[str, tuple[str, str]] = {}
    for region, cities in REGION_CITIES.items():
        candidates = []
        for index, left_city in enumerate(cities):
            for right_city in cities[index + 1 :]:
                distance = haversine_km(
                    float(by_city[left_city]["depot_lat"]),
                    float(by_city[left_city]["depot_lon"]),
                    float(by_city[right_city]["depot_lat"]),
                    float(by_city[right_city]["depot_lon"]),
                )
                candidates.append((distance, left_city, right_city))
        _, left, right = min(candidates)
        result[region] = tuple(sorted((f"D_{left}", f"D_{right}")))
    return result


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    a1, a2 = math.radians(lat1), math.radians(lat2)
    delta_lat = a2 - a1
    delta_lon = math.radians(lon2 - lon1)
    core = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(a1) * math.cos(a2) * math.sin(delta_lon / 2.0) ** 2
    )
    return radius_km * 2.0 * math.atan2(math.sqrt(core), math.sqrt(1.0 - core))


def new_instance_id(source_instance_id: str) -> str:
    return parse_identity(source_instance_id).new_instance_id


def assign_shift_windows(
    task_rows: Sequence[Mapping[str, str]],
    *,
    travel_seconds_by_customer: Mapping[str, float] | None = None,
) -> dict[str, dict[str, float | str]]:
    """Assign the registered 1:2 shifts after a frozen-road reachability check.

    The original group statistics remain fixed so customers that are already
    reachable retain byte-for-byte identical shifted windows.  A customer
    whose preferred shift cannot be reached from its home depot is placed in
    the other shift.  Its alternative window is delayed only by the minimum
    amount needed to include the direct arrival, while preserving its width.
    If the customer cannot be reached before either shift ends, the preferred
    allocation is retained and explicitly marked.
    """

    ordered = sorted(
        task_rows,
        key=lambda row: (
            float(row["time_window_early_minute"]),
            str(row["customer_id"]),
        ),
    )
    preferred = {
        str(row["customer_id"]): "AM" if index % 3 == 0 else "PM"
        for index, row in enumerate(ordered)
    }
    groups = {
        shift_id: [
            row
            for row in ordered
            if preferred[str(row["customer_id"])] == shift_id
        ]
        for shift_id in SHIFT_ROWS
    }
    group_stats: dict[str, tuple[float, float, float]] = {}
    for shift_id, rows in groups.items():
        if not rows:
            rows = list(ordered)
        source_values = [float(row["time_window_early_minute"]) for row in rows]
        source_min = min(source_values)
        source_max = max(source_values)
        max_width = max(float(row["time_window_width_minute"]) for row in rows)
        group_stats[shift_id] = (source_min, source_max, max_width)

    def shifted_window(
        row: Mapping[str, str], shift_id: str
    ) -> dict[str, float | str]:
        source_min, source_max, max_width = group_stats[shift_id]
        shift_start = SHIFT_ROWS[shift_id]["start_minute"]
        final_early = SHIFT_ROWS[shift_id]["end_minute"] - max_width
        source_early = float(row["time_window_early_minute"])
        fraction = (
            0.0
            if math.isclose(source_min, source_max)
            else (source_early - source_min) / (source_max - source_min)
        )
        fraction = min(1.0, max(0.0, fraction))
        early = shift_start + fraction * (final_early - shift_start)
        width = float(row["time_window_width_minute"])
        return {
            "shift_id": shift_id,
            "early": early,
            "late": early + width,
            "width": width,
            "source_early": source_early,
            "source_late": float(row["time_window_late_minute"]),
        }

    def reachable(customer_id: str, window: Mapping[str, float | str]) -> bool:
        if travel_seconds_by_customer is None:
            return True
        arrival_second = (
            float(SHIFT_ROWS[str(window["shift_id"])]["start_minute"]) * 60.0
            + float(travel_seconds_by_customer[customer_id])
        )
        return arrival_second <= float(window["late"]) * 60.0 + 1.0e-6

    def minimally_delay_to_reachability(
        customer_id: str,
        window: Mapping[str, float | str],
    ) -> dict[str, float | str] | None:
        if travel_seconds_by_customer is None:
            return dict(window)
        shift_id = str(window["shift_id"])
        shift_start = float(SHIFT_ROWS[shift_id]["start_minute"])
        shift_end = float(SHIFT_ROWS[shift_id]["end_minute"])
        arrival_minute = (
            shift_start + float(travel_seconds_by_customer[customer_id]) / 60.0
        )
        width = float(window["width"])
        adjusted_early = arrival_minute - width
        if adjusted_early < shift_start - 1.0e-9 or arrival_minute > shift_end + 1.0e-9:
            return None
        adjusted = dict(window)
        adjusted["early"] = adjusted_early
        adjusted["late"] = arrival_minute
        adjusted["reachability_window_delay_minute"] = (
            adjusted_early - float(window["early"])
        )
        return adjusted

    output: dict[str, dict[str, float | str]] = {}
    for row in ordered:
        customer_id = str(row["customer_id"])
        preferred_shift = preferred[customer_id]
        alternative_shift = "PM" if preferred_shift == "AM" else "AM"
        selected = shifted_window(row, preferred_shift)
        selected["reachability_window_delay_minute"] = 0.0
        preferred_reachable = reachable(customer_id, selected)
        alternative_reachable: bool | None = None
        switched = False
        if not preferred_reachable:
            alternative = shifted_window(row, alternative_shift)
            alternative["reachability_window_delay_minute"] = 0.0
            alternative_reachable = reachable(customer_id, alternative)
            if not alternative_reachable:
                delayed = minimally_delay_to_reachability(
                    customer_id, alternative
                )
                if delayed is not None:
                    alternative = delayed
                    alternative_reachable = True
            if alternative_reachable:
                selected = alternative
                switched = True
        selected.update(
            {
                "preferred_shift_id": preferred_shift,
                "reachability_status": (
                    "SWITCHED_TO_REACHABLE_ALTERNATIVE"
                    if switched
                    else (
                        "PASS_PREFERRED_SHIFT"
                        if preferred_reachable
                        else "FLAG_BOTH_SHIFTS_UNREACHABLE"
                    )
                ),
                "preferred_shift_reachable": int(preferred_reachable),
                "alternative_shift_reachable": (
                    ""
                    if alternative_reachable is None
                    else int(alternative_reachable)
                ),
                "home_to_customer_travel_minute": (
                    ""
                    if travel_seconds_by_customer is None
                    else float(travel_seconds_by_customer[customer_id]) / 60.0
                ),
            }
        )
        output[customer_id] = selected
    if len(output) != len(task_rows):
        raise RuntimeError("deterministic 1:2 shift allocation lost a task")
    return output


def direct_location_facts(
    bundle: Any,
    depot_ids: Sequence[str],
) -> list[LocationFact]:
    if len(depot_ids) < 2:
        return []
    node_by_id = {node.node_id: node for node in bundle.instance.nodes}
    rows: list[LocationFact] = []
    for customer_id in sorted(bundle.customer_home_depot):
        costs: dict[str, float] = {}
        for depot_id in depot_ids:
            route = Route(
                vehicle_id="CV-DIRECT",
                vehicle_type="cv",
                home_depot_id=depot_id,
                node_sequence=[depot_id, customer_id, depot_id],
            )
            breakdown = evaluate(
                Solution(routes=[route]),
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                carbon_quota_kg=0.0,
            )
            costs[depot_id] = float(breakdown["total_cost"]) - float(
                breakdown["cost_fix"]
            )
        nearest, second = sorted(costs, key=lambda depot: (costs[depot], depot))[:2]
        relative = (costs[second] - costs[nearest]) / costs[nearest]
        rows.append(
            LocationFact(
                source_node_id=customer_id,
                city=str(node_by_id[customer_id].city),
                nearest_depot=nearest,
                second_depot=second,
                nearest_cost_cny=costs[nearest],
                second_cost_cny=costs[second],
                relative_gap=relative,
            )
        )
    return rows


def share_in_gate(count: int, total: int) -> bool:
    if total <= 0:
        return False
    share = count / total
    return GEOMETRY_PASS_MIN <= share <= GEOMETRY_PASS_MAX


def select_locations_for_gate(
    facts: Sequence[LocationFact],
    customer_count: int,
) -> tuple[tuple[LocationFact, ...], bool, str]:
    """Select a low-service-cost subset, then minimally enter the fixed gate."""

    if len(facts) < customer_count:
        return (), False, "source point pool is smaller than the instance"
    ranked = sorted(
        facts,
        key=lambda row: (
            row.nearest_cost_cny,
            row.source_node_id,
        ),
    )
    selected = list(ranked[:customer_count])
    unselected = list(ranked[customer_count:])
    lower = math.ceil(CONTEST_SHARE_LOWER * customer_count - 1.0e-12)
    upper = math.floor(CONTEST_SHARE_UPPER * customer_count + 1.0e-12)

    def is_main(row: LocationFact) -> bool:
        return row.relative_gap < MAIN_CONTEST_THRESHOLD

    current = sum(is_main(row) for row in selected)
    if current < lower:
        additions = [row for row in unselected if is_main(row)]
        removals = sorted(
            [row for row in selected if not is_main(row)],
            key=lambda row: (-row.nearest_cost_cny, row.source_node_id),
        )
        needed = lower - current
        if len(additions) < needed or len(removals) < needed:
            return tuple(selected), False, (
                f"25pct pool ceiling {current + len(additions)}/{customer_count} "
                f"is below required {lower}/{customer_count}"
            )
        for remove, add in zip(removals[:needed], additions[:needed], strict=True):
            selected.remove(remove)
            selected.append(add)
    elif current > upper:
        additions = [row for row in unselected if not is_main(row)]
        removals = sorted(
            [row for row in selected if is_main(row)],
            key=lambda row: (-row.nearest_cost_cny, row.source_node_id),
        )
        needed = current - upper
        if len(additions) < needed or len(removals) < needed:
            attainable = current - min(len(additions), len(removals))
            return tuple(selected), False, (
                f"25pct pool floor {attainable}/{customer_count} "
                f"is above allowed {upper}/{customer_count}"
            )
        for remove, add in zip(removals[:needed], additions[:needed], strict=True):
            selected.remove(remove)
            selected.append(add)

    selected = sorted(selected, key=lambda row: row.source_node_id)
    final_count = sum(is_main(row) for row in selected)
    if not (lower <= final_count <= upper):
        return tuple(selected), False, "deterministic gate adjustment did not close"
    return tuple(selected), True, (
        f"25pct deterministic subset {final_count}/{customer_count}"
    )


def original_geometry_choice(
    identity: ParsedIdentity,
    bundle: Any,
) -> GeometryChoice:
    depot_ids = tuple(
        sorted(node.node_id for node in bundle.instance.nodes if node.node_type == "d")
    )
    customers = tuple(sorted(bundle.customer_home_depot))
    return GeometryChoice(
        mode="ORIGINAL_GEOMETRY",
        matrix_source_instance_id=identity.source_instance_id,
        depot_ids=depot_ids,
        customer_source_ids=customers,
        home_depot_by_source_customer=MappingProxyType(
            dict(bundle.customer_home_depot)
        ),
        attempted_rebuild=False,
        rebuild_succeeded=False,
        reanchored_customer_count=0,
        note="original source geometry retained",
    )


def choose_geometry(
    identity: ParsedIdentity,
    original: Any,
    cache: SourceBundleCache,
    closest_pairs: Mapping[str, tuple[str, str]],
) -> GeometryChoice:
    original_choice = original_geometry_choice(identity, original)
    original_facts = direct_location_facts(original, original_choice.depot_ids)
    original_main = sum(
        fact.relative_gap < MAIN_CONTEST_THRESHOLD for fact in original_facts
    )
    expected_pair = closest_pairs[identity.region]
    depot_policy_ok = (
        set(original_choice.depot_ids) == set(expected_pair)
        if identity.size <= 100
        else len(original_choice.depot_ids) >= 2
    )
    if (
        depot_policy_ok
        and len(original_choice.depot_ids) >= 2
        and share_in_gate(original_main, identity.size)
    ):
        return replace(
            original_choice,
            rebuild_succeeded=True,
            note="original geometry already satisfies the registered gate",
        )

    pool_id = (
        f"cn-{identity.region}-200c-{identity.replicate}-V2-LOCATIONS"
    )
    pool = cache.get(pool_id)
    depot_ids = (
        expected_pair
        if identity.size <= 100
        else tuple(
            sorted(
                node.node_id
                for node in pool.instance.nodes
                if node.node_type == "d"
            )
        )
    )
    facts = direct_location_facts(pool, depot_ids)
    if identity.size <= 100:
        pair_cities = {
            depot_id.removeprefix("D_") for depot_id in depot_ids
        }
        facts = [fact for fact in facts if fact.city in pair_cities]
    selected, success, note = select_locations_for_gate(facts, identity.size)
    if not success:
        return replace(
            original_choice,
            attempted_rebuild=True,
            note=(
                f"rebuild attempted against {pool_id}; {note}; original geometry retained"
            ),
        )
    return GeometryChoice(
        mode=(
            "REAL_OSM_CLOSEST_PAIR_REANCHOR"
            if identity.size <= 100
            else "REAL_OSM_MULTICITY_CORRIDOR_REANCHOR"
        ),
        matrix_source_instance_id=pool_id,
        depot_ids=tuple(depot_ids),
        customer_source_ids=tuple(row.source_node_id for row in selected),
        home_depot_by_source_customer=MappingProxyType(
            {row.source_node_id: row.nearest_depot for row in selected}
        ),
        attempted_rebuild=True,
        rebuild_succeeded=True,
        reanchored_customer_count=identity.size,
        note=f"rebuild against {pool_id}; {note}",
    )


def interleave_locations(
    source_ids: Sequence[str],
    home_by_source: Mapping[str, str],
) -> list[str]:
    grouped: dict[str, deque[str]] = defaultdict(deque)
    for source_id in sorted(source_ids):
        grouped[home_by_source[source_id]].append(source_id)
    output: list[str] = []
    keys = sorted(grouped)
    while any(grouped.values()):
        for key in keys:
            if grouped[key]:
                output.append(grouped[key].popleft())
    return output


def build_instance(
    identity: ParsedIdentity,
    task_rows: Sequence[Mapping[str, str]],
    geometry: GeometryChoice,
    cache: SourceBundleCache,
) -> BuiltInstance:
    source = cache.get(geometry.matrix_source_instance_id)
    source_nodes = {node.node_id: node for node in source.instance.nodes}
    source_node_rows = {
        row["node_id"]: row
        for row in read_csv(
            SOURCE_STATIC
            / "instances"
            / geometry.matrix_source_instance_id
            / "nodes.csv"
        )
    }
    tasks = sorted(
        task_rows,
        key=lambda row: (
            float(row["time_window_early_minute"]),
            str(row["customer_id"]),
        ),
    )
    location_order = interleave_locations(
        geometry.customer_source_ids,
        geometry.home_depot_by_source_customer,
    )
    if len(tasks) != len(location_order):
        raise RuntimeError("task/location count mismatch")
    source_for_customer = {
        str(task["customer_id"]): location
        for task, location in zip(tasks, location_order, strict=True)
    }
    customer_for_source = {
        source_id: customer_id
        for customer_id, source_id in source_for_customer.items()
    }
    if len(customer_for_source) != len(source_for_customer):
        raise RuntimeError("a real OSM source point was assigned twice")
    travel_seconds_by_customer = {
        customer_id: source.instance.arc_metrics(
            geometry.home_depot_by_source_customer[source_id],
            source_id,
            "cv",
            fallback_speed_mps=1.0,
        )[1]
        for customer_id, source_id in source_for_customer.items()
    }
    shift_map = assign_shift_windows(
        task_rows,
        travel_seconds_by_customer=travel_seconds_by_customer,
    )

    selected_facility_ids = []
    for depot_id in geometry.depot_ids:
        city = depot_id.removeprefix("D_")
        selected_facility_ids.append(depot_id)
        station_id = f"S_{city}"
        if station_id in source_nodes:
            selected_facility_ids.append(station_id)
    selected_source_ids = [
        *selected_facility_ids,
        *[source_for_customer[str(row["customer_id"])] for row in sorted(task_rows, key=lambda item: item["customer_id"])],
    ]
    if len(selected_source_ids) != len(set(selected_source_ids)):
        raise RuntimeError("selected source-node identities are not unique")

    new_nodes: list[Node] = []
    node_rows: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    order_rows: list[dict[str, Any]] = []
    home_by_customer: dict[str, str] = {}

    for source_id in selected_facility_ids:
        node = source_nodes[source_id]
        adjusted = replace(
            node,
            ready_time=SHIFT_ROWS["AM"]["start_minute"] * 60.0,
            due_time=SHIFT_ROWS["PM"]["end_minute"] * 60.0,
            charge_power_kw=(
                DEPOT_POWER_KW if node.node_type == "d" else node.charge_power_kw
            ),
        )
        new_nodes.append(adjusted)
        raw = source_node_rows[source_id]
        node_rows.append(
            {
                "node_id": source_id,
                "node_type": raw["node_type"],
                "city": raw["city"],
                "latitude": raw["latitude"],
                "longitude": raw["longitude"],
                "source_identity": raw["source_identity"],
            }
        )
        mapping_rows.append(
            {
                "new_node_id": source_id,
                "source_instance_id": geometry.matrix_source_instance_id,
                "source_node_id": source_id,
                "source_city": raw["city"],
                "latitude": raw["latitude"],
                "longitude": raw["longitude"],
                "mapping_class": "IDENTITY_REAL_FACILITY_OR_STATION",
            }
        )

    tasks_by_id = {str(row["customer_id"]): row for row in task_rows}
    for customer_id in sorted(tasks_by_id):
        task = tasks_by_id[customer_id]
        source_id = source_for_customer[customer_id]
        source_node = source_nodes[source_id]
        source_row = source_node_rows[source_id]
        shifted = shift_map[customer_id]
        new_nodes.append(
            Node(
                node_id=customer_id,
                node_type="c",
                x=source_node.x,
                y=source_node.y,
                demand=float(task["demand_kg"]),
                ready_time=float(shifted["early"]) * 60.0,
                due_time=float(shifted["late"]) * 60.0,
                service_time=float(task["service_minutes"]) * 60.0,
                city=source_node.city,
            )
        )
        node_rows.append(
            {
                "node_id": customer_id,
                "node_type": "customer",
                "city": source_row["city"],
                "latitude": source_row["latitude"],
                "longitude": source_row["longitude"],
                "source_identity": source_row["source_identity"],
            }
        )
        mapping_rows.append(
            {
                "new_node_id": customer_id,
                "source_instance_id": geometry.matrix_source_instance_id,
                "source_node_id": source_id,
                "source_city": source_row["city"],
                "latitude": source_row["latitude"],
                "longitude": source_row["longitude"],
                "mapping_class": (
                    "IDENTITY_REAL_OSM_LOCATION"
                    if source_id == customer_id
                    and geometry.matrix_source_instance_id == identity.source_instance_id
                    else "REAL_OSM_LOCATION_REANCHOR_P43_A_B_CLASS"
                ),
            }
        )
        home = geometry.home_depot_by_source_customer[source_id]
        home_by_customer[customer_id] = home
        source_identity = str(source_row["source_identity"])
        osm_type, _, osm_id = source_identity.partition("/")
        order_rows.append(
            {
                **dict(task),
                "instance_id": identity.new_instance_id,
                "region": identity.region,
                "customer_size": identity.size,
                "replicate": identity.replicate,
                "city": source_row["city"],
                "osm_type": osm_type,
                "osm_id": osm_id,
                "latitude": source_row["latitude"],
                "longitude": source_row["longitude"],
                "name": source_identity,
                "time_window_early_minute": f"{float(shifted['early']):.6f}",
                "time_window_late_minute": f"{float(shifted['late']):.6f}",
                "time_window_width_minute": f"{float(shifted['width']):.6f}",
                "window_classification": (
                    "OBSERVED_WIDTH_AND_WITHIN_SHIFT_SHAPE__"
                    "SHIFT_PLACEMENT_EXTRAPOLATED"
                ),
                "shift_id": shifted["shift_id"],
                "preferred_shift_id": shifted["preferred_shift_id"],
                "shift_reachability_status": shifted["reachability_status"],
                "preferred_shift_reachable": shifted[
                    "preferred_shift_reachable"
                ],
                "alternative_shift_reachable": shifted[
                    "alternative_shift_reachable"
                ],
                "home_to_customer_travel_minute": shifted[
                    "home_to_customer_travel_minute"
                ],
                "reachability_window_delay_minute": shifted[
                    "reachability_window_delay_minute"
                ],
                "shift_start_minute": SHIFT_ROWS[str(shifted["shift_id"])]["start_minute"],
                "shift_end_minute": SHIFT_ROWS[str(shifted["shift_id"])]["end_minute"],
                "depot_return_required": 1,
                "home_depot_id": home,
                "source_instance_id_task": identity.source_instance_id,
                "source_customer_id_task": customer_id,
                "source_time_window_early_minute": f"{float(shifted['source_early']):.6f}",
                "source_time_window_late_minute": f"{float(shifted['source_late']):.6f}",
                "source_time_window_width_minute": f"{float(shifted['width']):.6f}",
                "source_instance_id_location": geometry.matrix_source_instance_id,
                "source_customer_id_location": source_id,
                "location_mapping_class": mapping_rows[-1]["mapping_class"],
                "shift_mapping_class": (
                    "DELIVERY_BOTH_SHIFTS_APPROVED_P43_G__ONE_IN_THREE_AM__"
                    "FROZEN_ROAD_REACHABILITY_PREFLIGHT"
                ),
            }
        )

    source_indices = [source.instance.node_index[node_id] for node_id in selected_source_ids]
    profiles: dict[str, RoadProfileMatrices] = {}
    for profile_id, matrices in source.instance.road_profiles.items():
        profiles[profile_id] = RoadProfileMatrices(
            distance_m=tuple(
                tuple(matrices.distance_m[left][right] for right in source_indices)
                for left in source_indices
            ),
            duration_s=tuple(
                tuple(matrices.duration_s[left][right] for right in source_indices)
                for left in source_indices
            ),
            sum_v2d_m3_s2=tuple(
                tuple(matrices.sum_v2d_m3_s2[left][right] for right in source_indices)
                for left in source_indices
            ),
        )
    parameters = dict(source.instance.vehicle_parameters)
    parameters["ev"] = replace(
        parameters["ev"],
        non_energy_distance_cost_per_km=EV_NON_ENERGY_CNY_PER_KM,
        source_ids=tuple(
            dict.fromkeys(
                (
                    *parameters["ev"].source_ids,
                    "BATTERY_DEPRECIATION_CHANGJIANG_2024_"
                    "GOEKE_SCHNEIDER_2015",
                )
            )
        ),
    )
    instance = Instance(
        nodes=new_nodes,
        distance_matrix=[list(row) for row in profiles["cv"].distance_m],
        num_cv=max(1, identity.size),
        num_ev=max(1, identity.size),
        road_profiles=profiles,
        vehicle_parameters=parameters,
        demand_mass_per_unit_kg=1.0,
    )
    curve = M17_FAST_SHAPE_SCALED_60KW_PWL
    prices = replace(
        source.prices,
        depot_charge_power_kw=DEPOT_POWER_KW,
        charging_curve_id=curve.curve_id,
        charging_soc_breakpoints=curve.soc_breakpoints,
        charging_relative_powers=curve.relative_powers,
        depot_charging_curve_id=curve.curve_id,
        depot_charging_soc_breakpoints=curve.soc_breakpoints,
        depot_charging_relative_powers=curve.relative_powers,
    )
    orders_by_customer = MappingProxyType(
        {str(row["customer_id"]): MappingProxyType(dict(row)) for row in order_rows}
    )
    return BuiltInstance(
        identity=identity,
        source_bundle=source,
        instance=instance,
        prices=prices,
        time_profile=tuple(dict(row) for row in source.time_profile),
        node_rows=tuple(node_rows),
        order_rows=tuple(order_rows),
        source_mapping_rows=tuple(mapping_rows),
        orders_by_customer=orders_by_customer,
        customer_home_depot=MappingProxyType(home_by_customer),
        geometry=geometry,
        shift_assignment_flags=tuple(
            f"{row['customer_id']}:both shifts unreachable from "
            f"{row['home_depot_id']}"
            for row in order_rows
            if row["shift_reachability_status"]
            == "FLAG_BOTH_SHIFTS_UNREACHABLE"
        ),
    )


def contestability_rows(built: BuiltInstance) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    depots = built.geometry.depot_ids
    if len(depots) < 2:
        return rows
    for customer_id in sorted(built.orders_by_customer):
        costs: dict[str, float] = {}
        for depot_id in depots:
            route = Route(
                vehicle_id="CV-DIRECT",
                vehicle_type="cv",
                home_depot_id=depot_id,
                node_sequence=[depot_id, customer_id, depot_id],
            )
            breakdown = evaluate(
                Solution(routes=[route]),
                built.instance,
                built.time_profile,
                built.prices,
                carbon_quota_kg=0.0,
            )
            costs[depot_id] = float(breakdown["total_cost"]) - float(
                breakdown["cost_fix"]
            )
        nearest, second = sorted(costs, key=lambda depot: (costs[depot], depot))[:2]
        gap = costs[second] - costs[nearest]
        relative = gap / costs[nearest]
        row: dict[str, Any] = {
            "instance_id": built.identity.new_instance_id,
            "customer_id": customer_id,
            "home_depot_id": built.customer_home_depot[customer_id],
            "nearest_depot": nearest,
            "second_depot": second,
            "nearest_cost_cny": costs[nearest],
            "second_cost_cny": costs[second],
            "absolute_gap_cny": gap,
            "relative_gap": relative,
        }
        for threshold in CONTEST_THRESHOLDS:
            row[f"contestable_at_{int(threshold * 100)}pct"] = int(
                relative < threshold
            )
        rows.append(row)
    return rows


def route_clock_detail(
    built: BuiltInstance,
    depot_id: str,
    shift_id: str,
    customers: Sequence[str],
    *,
    earliest_departure_second: float | None = None,
) -> tuple[bool, float, float, float, str]:
    shift = SHIFT_ROWS[shift_id]
    start = max(
        shift["start_minute"] * 60.0,
        (
            shift["start_minute"] * 60.0
            if earliest_departure_second is None
            else float(earliest_departure_second)
        ),
    )
    end = shift["end_minute"] * 60.0
    node_by_id = {node.node_id: node for node in built.instance.nodes}
    now = start
    distance = 0.0
    left = depot_id
    for right in (*customers, depot_id):
        arc_distance, duration, _ = built.instance.arc_metrics(
            left,
            right,
            "cv",
            fallback_speed_mps=1.0,
        )
        distance += arc_distance
        now += duration
        if right != depot_id:
            node = node_by_id[right]
            now = max(now, float(node.ready_time))
            if now > float(node.due_time) + 1.0e-6:
                return (
                    False,
                    start,
                    now,
                    distance,
                    f"arrival minute {now / 60.0:.3f} exceeds {right} due "
                    f"minute {float(node.due_time) / 60.0:.3f}",
                )
            now += float(node.service_time)
        left = right
    if now > end + 1.0e-6:
        return (
            False,
            start,
            now,
            distance,
            f"return minute {now / 60.0:.3f} exceeds {shift_id} end "
            f"minute {end / 60.0:.3f}",
        )
    return True, start, now, distance, ""


def route_clock(
    built: BuiltInstance,
    depot_id: str,
    shift_id: str,
    customers: Sequence[str],
    *,
    earliest_departure_second: float | None = None,
) -> tuple[bool, float, float, float]:
    feasible, start, end, distance, _ = route_clock_detail(
        built,
        depot_id,
        shift_id,
        customers,
        earliest_departure_second=earliest_departure_second,
    )
    return feasible, start, end, distance


def build_edf_route_plans(
    built: BuiltInstance,
) -> tuple[tuple[RoutePlan, ...], str]:
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for customer_id, row in built.orders_by_customer.items():
        groups[(built.customer_home_depot[customer_id], str(row["shift_id"]))].append(
            customer_id
        )
    plans: list[RoutePlan] = []
    for (depot_id, shift_id), customers in sorted(groups.items()):
        ordered = sorted(
            customers,
            key=lambda customer_id: (
                float(built.orders_by_customer[customer_id]["time_window_late_minute"]),
                customer_id,
            ),
        )
        packed: list[list[str]] = []
        for customer_id in ordered:
            row = built.orders_by_customer[customer_id]
            customer_volume = float(row["source_volume_m3"])
            customer_demand = float(row["demand_kg"])
            placed = False
            for route in packed:
                volume = sum(
                    float(built.orders_by_customer[item]["source_volume_m3"])
                    for item in route
                )
                demand = sum(
                    float(built.orders_by_customer[item]["demand_kg"])
                    for item in route
                )
                if volume + customer_volume > VEHICLE_VOLUME_CAPACITY_M3 + 1.0e-9:
                    continue
                if demand + customer_demand > VEHICLE_PAYLOAD_CAPACITY_KG + 1.0e-9:
                    continue
                feasible, _, _, _ = route_clock(
                    built,
                    depot_id,
                    shift_id,
                    [*route, customer_id],
                )
                if feasible:
                    route.append(customer_id)
                    placed = True
                    break
            if not placed:
                feasible, _, _, _, failure = route_clock_detail(
                    built,
                    depot_id,
                    shift_id,
                    [customer_id],
                )
                if not feasible:
                    return (), (
                        f"{customer_id} alone is infeasible from {depot_id} "
                        f"in {shift_id}: {failure}"
                    )
                packed.append([customer_id])
        for customers_in_route in packed:
            feasible, departed, returned, distance = route_clock(
                built,
                depot_id,
                shift_id,
                customers_in_route,
            )
            if not feasible:
                return (), "final EDF route failed exact replay"
            plans.append(
                RoutePlan(
                    depot_id=depot_id,
                    shift_id=shift_id,
                    customers=tuple(customers_in_route),
                    volume_m3=sum(
                        float(built.orders_by_customer[item]["source_volume_m3"])
                        for item in customers_in_route
                    ),
                    demand_kg=sum(
                        float(built.orders_by_customer[item]["demand_kg"])
                        for item in customers_in_route
                    ),
                    departure_second=departed,
                    return_second=returned,
                    distance_m=distance,
                )
            )
    served = sorted(customer for plan in plans for customer in plan.customers)
    if served != sorted(built.orders_by_customer):
        return (), "EDF route family does not cover every customer exactly once"
    return tuple(plans), ""


def minimum_edf_order_chains(
    built: BuiltInstance,
    plans: Sequence[RoutePlan],
) -> list[list[ScheduledPlan]]:
    """Exact fixed-route chain cover used by the validated pilot witness.

    The future of a same-depot chain depends only on the already-covered route
    set and its current return time.  Retaining the earliest return for every
    subset therefore removes dominated permutations without changing the
    minimum number of physical vehicles.
    """

    if not plans:
        return []
    if len({(plan.depot_id, plan.shift_id) for plan in plans}) != 1:
        raise ValueError("chain construction requires one depot and shift")
    ordered = tuple(sorted(
        plans,
        key=lambda plan: (
            max(
                float(built.orders_by_customer[item]["time_window_late_minute"])
                for item in plan.customers
            ),
            plan.return_second,
            plan.customers,
        ),
    ))
    candidates: dict[
        int,
        tuple[tuple[int, ...], tuple[float, ...], tuple[float, ...]],
    ] = {}

    def extend(
        sequence: tuple[int, ...],
        departures: tuple[float, ...],
        returns: tuple[float, ...],
        remaining: frozenset[int],
    ) -> None:
        mask = sum(1 << index for index in sequence)
        incumbent = candidates.get(mask)
        if incumbent is not None and incumbent[2][-1] <= returns[-1] + 1.0e-9:
            return
        candidates[mask] = (sequence, departures, returns)
        for index in sorted(remaining):
            plan = ordered[index]
            earliest = (
                returns[-1]
                + plan.volume_m3 * LOADING_HOURS_PER_M3 * 3600.0
            )
            feasible, departed, returned, _ = route_clock(
                built,
                plan.depot_id,
                plan.shift_id,
                plan.customers,
                earliest_departure_second=earliest,
            )
            if feasible:
                extend(
                    (*sequence, index),
                    (*departures, departed),
                    (*returns, returned),
                    remaining.difference({index}),
                )

    all_indices = frozenset(range(len(ordered)))
    for index, plan in enumerate(ordered):
        feasible, departed, returned, _ = route_clock(
            built,
            plan.depot_id,
            plan.shift_id,
            plan.customers,
        )
        if not feasible:
            raise RuntimeError("route plan became infeasible before chaining")
        extend(
            (index,),
            (departed,),
            (returned,),
            all_indices.difference({index}),
        )

    by_member: dict[int, list[int]] = {
        index: [] for index in range(len(ordered))
    }
    for mask in candidates:
        for index in range(len(ordered)):
            if mask & (1 << index):
                by_member[index].append(mask)
    for masks in by_member.values():
        masks.sort(key=lambda mask: (-mask.bit_count(), mask))

    full_mask = (1 << len(ordered)) - 1
    memo: dict[int, tuple[int, tuple[int, ...]]] = {}

    def cover(mask: int) -> tuple[int, tuple[int, ...]]:
        if mask == full_mask:
            return 0, ()
        if mask in memo:
            return memo[mask]
        first = next(
            index for index in range(len(ordered)) if not mask & (1 << index)
        )
        best: tuple[int, tuple[int, ...]] | None = None
        for candidate_mask in by_member[first]:
            if candidate_mask & mask:
                continue
            rest_count, rest = cover(mask | candidate_mask)
            trial = (1 + rest_count, (candidate_mask, *rest))
            if best is None or trial < best:
                best = trial
        if best is None:
            raise RuntimeError("fixed routes have no complete shift-chain cover")
        memo[mask] = best
        return best

    _, selected_masks = cover(0)
    chains: list[list[ScheduledPlan]] = []
    for mask in selected_masks:
        sequence, departures, returns = candidates[mask]
        chains.append(
            [
                ScheduledPlan(
                    ordered[index],
                    departures[position],
                    returns[position],
                )
                for position, index in enumerate(sequence)
            ]
        )
    return sorted(
        chains,
        key=lambda chain: (
            chain[0].departure_second,
            chain[0].plan.customers,
        ),
    )


def plans_to_solution(
    built: BuiltInstance,
    plans: Sequence[RoutePlan],
) -> tuple[Solution, dict[str, float], dict[str, tuple[ScheduledPlan, ...]]]:
    routes: list[Route] = []
    departures: dict[str, float] = {}
    scheduled_by_physical: dict[str, tuple[ScheduledPlan, ...]] = {}
    for depot_id in sorted({plan.depot_id for plan in plans}):
        am = [
            [ScheduledPlan(plan, plan.departure_second, plan.return_second)]
            for plan in sorted(
                (
                    item
                    for item in plans
                    if item.depot_id == depot_id and item.shift_id == "AM"
                ),
                key=lambda item: (item.return_second, item.customers),
            )
        ]
        pm = minimum_edf_order_chains(
            built,
            [plan for plan in plans if plan.depot_id == depot_id and plan.shift_id == "PM"],
        )
        physical_count = max(len(am), len(pm))
        for index in range(physical_count):
            physical = f"CV_{depot_id}_{index + 1:03d}"
            scheduled: list[ScheduledPlan] = []
            if index < len(am):
                scheduled.extend(am[index])
            if index < len(pm):
                scheduled.extend(pm[index])
            scheduled.sort(key=lambda item: item.departure_second)
            scheduled_by_physical[physical] = tuple(scheduled)
            for trip_index, item in enumerate(scheduled, start=1):
                vehicle_id = route_trip_vehicle_id(physical, trip_index)
                routes.append(
                    Route(
                        vehicle_id=vehicle_id,
                        vehicle_type="cv",
                        home_depot_id=depot_id,
                        node_sequence=[depot_id, *item.plan.customers, depot_id],
                    )
                )
                departures[vehicle_id] = item.departure_second
    return Solution(routes=routes), departures, scheduled_by_physical


def build_witness(built: BuiltInstance) -> WitnessResult:
    plans, reason = build_edf_route_plans(built)
    if reason:
        return WitnessResult(
            status="FAIL",
            reason=reason,
            plans=(),
            solution=None,
            departures=MappingProxyType({}),
            scheduled_by_physical=MappingProxyType({}),
            violations=(),
            served_customers=0,
            served_demand_kg=0.0,
        )
    solution, departures, scheduled_by_physical = plans_to_solution(built, plans)
    manual_errors = []
    for physical, scheduled in scheduled_by_physical.items():
        for item in scheduled:
            feasible, departed, returned, _ = route_clock(
                built,
                item.plan.depot_id,
                item.plan.shift_id,
                item.plan.customers,
                earliest_departure_second=item.departure_second,
            )
            if (
                not feasible
                or abs(departed - item.departure_second) > 1.0e-6
                or abs(returned - item.return_second) > 1.0e-6
            ):
                manual_errors.append(f"{physical}:{item.plan.customers}")
    violations = check_solution(solution, built.instance, built.prices)
    served = [
        node_id
        for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in built.orders_by_customer
    ]
    served_demand = sum(
        float(built.orders_by_customer[customer]["demand_kg"])
        for customer in served
    )
    violation_text = tuple(
        f"{item.type}:{item.vehicle_id}:{item.location}:{item.detail}"
        for item in violations
    )
    if manual_errors or violation_text or sorted(served) != sorted(built.orders_by_customer):
        reason_parts = []
        if manual_errors:
            reason_parts.append(f"manual shift replay failed {len(manual_errors)} routes")
        if violation_text:
            reason_parts.append(f"full checker reported {len(violation_text)} violations")
        if sorted(served) != sorted(built.orders_by_customer):
            reason_parts.append("customer coverage mismatch")
        return WitnessResult(
            status="FAIL",
            reason="; ".join(reason_parts),
            plans=tuple(plans),
            solution=solution,
            departures=MappingProxyType(departures),
            scheduled_by_physical=MappingProxyType(scheduled_by_physical),
            violations=violation_text,
            served_customers=len(set(served)),
            served_demand_kg=served_demand,
        )
    return WitnessResult(
        status="PASS",
        reason="",
        plans=tuple(plans),
        solution=solution,
        departures=MappingProxyType(departures),
        scheduled_by_physical=MappingProxyType(scheduled_by_physical),
        violations=(),
        served_customers=len(set(served)),
        served_demand_kg=served_demand,
    )


def direct_fallback_solution(built: BuiltInstance, vehicle_type: str) -> Solution:
    prefix = "CV" if vehicle_type == "cv" else "EV"
    routes = []
    for index, customer_id in enumerate(sorted(built.orders_by_customer), start=1):
        depot = built.customer_home_depot[customer_id]
        routes.append(
            Route(
                vehicle_id=f"{prefix}_DIRECT_{index:04d}",
                vehicle_type=vehicle_type,
                home_depot_id=depot,
                node_sequence=[depot, customer_id, depot],
            )
        )
    return Solution(routes=routes)


def as_vehicle_type(solution: Solution, vehicle_type: str) -> Solution:
    prefix = "CV" if vehicle_type == "cv" else "EV"
    physical_map: dict[str, str] = {}
    trip_counts: dict[str, int] = defaultdict(int)
    routes = []
    for route in solution.routes:
        old_physical = route.vehicle_id.split("#T", 1)[0]
        new_physical = physical_map.setdefault(
            old_physical,
            f"{prefix}_{len(physical_map) + 1:04d}",
        )
        trip_counts[new_physical] += 1
        routes.append(
            Route(
                vehicle_id=route_trip_vehicle_id(
                    new_physical,
                    trip_counts[new_physical],
                ),
                vehicle_type=vehicle_type,
                home_depot_id=route.home_depot_id,
                node_sequence=list(route.node_sequence),
            )
        )
    return Solution(routes=routes)


def per_km_health(
    built: BuiltInstance,
    witness: WitnessResult,
) -> dict[str, Any]:
    if witness.solution is not None:
        cv_solution = witness.solution
        basis = "EDF_TWO_SHIFT_WITNESS_ARCS"
    else:
        cv_solution = direct_fallback_solution(built, "cv")
        basis = "DIRECT_ARC_FALLBACK_NO_FEASIBLE_WITNESS"
    ev_solution = as_vehicle_type(cv_solution, "ev")
    cv = evaluate(
        cv_solution,
        built.instance,
        built.time_profile,
        built.prices,
        carbon_quota_kg=0.0,
    )
    ev = evaluate(
        ev_solution,
        built.instance,
        built.time_profile,
        built.prices,
        carbon_quota_kg=0.0,
    )
    cv_distance_km = float(cv["distance_cv"]) / 1000.0
    ev_distance_km = float(ev["distance_ev"]) / 1000.0
    if cv_distance_km <= 0.0 or ev_distance_km <= 0.0:
        raise RuntimeError("per-km replay has zero road distance")
    cv_l_per_km = float(cv["fuel_liters"]) / cv_distance_km
    cv_cost_per_km = CV_NON_ENERGY_CNY_PER_KM + float(cv["cost_fuel"]) / cv_distance_km
    cv_emission_per_km = float(cv["E_cv_direct"]) / cv_distance_km
    ev_kwh_per_km = float(ev["ev_drive_kwh"]) / ev_distance_km

    energy_by_city: dict[str, float] = defaultdict(float)
    for route in ev_solution.routes:
        route_eval = evaluate(
            Solution(routes=[route]),
            built.instance,
            built.time_profile,
            built.prices,
            carbon_quota_kg=0.0,
        )
        depot_node = built.instance.nodes[built.instance.node_index[route.home_depot_id]]
        energy_by_city[str(depot_node.city)] += float(route_eval["ev_drive_kwh"])
    total_weight = sum(energy_by_city.values())
    if total_weight <= 0.0:
        raise RuntimeError("per-km EV replay has zero energy")
    profile = {
        (str(row["city"]), int(round(float(row["horizon_second_start"]) / 60.0))): row
        for row in built.time_profile
    }
    scenarios: dict[str, dict[str, float]] = {}
    for scenario, minute in SCENARIO_MINUTES.items():
        weighted_price = 0.0
        weighted_carbon = 0.0
        for city, energy in energy_by_city.items():
            row = profile[(city, minute)]
            weight = energy / total_weight
            weighted_price += weight * float(row["depot_energy_cny_per_kwh"])
            weighted_carbon += weight * float(row["actual_gco2_per_kwh"]) / 1000.0
        ev_cost = EV_NON_ENERGY_CNY_PER_KM + ev_kwh_per_km * weighted_price
        saving = cv_cost_per_km - ev_cost
        scenarios[scenario] = {
            "price_cny_per_kwh": weighted_price,
            "carbon_kg_per_kwh": weighted_carbon,
            "ev_cost_cny_per_km": ev_cost,
            "ev_emission_kg_per_km": ev_kwh_per_km * weighted_carbon,
            "critical_daily_km": (
                EV_FIXED_PREMIUM_CNY_PER_DAY / saving if saving > 0.0 else math.inf
            ),
        }
    return {
        "basis": basis,
        "cv_fuel_l_per_km": cv_l_per_km,
        "cv_cost_cny_per_km": cv_cost_per_km,
        "cv_emission_kg_per_km": cv_emission_per_km,
        "ev_kwh_per_km": ev_kwh_per_km,
        "scenarios": scenarios,
    }


def witness_distance_health(
    built: BuiltInstance,
    witness: WitnessResult,
    critical_values: Sequence[float],
) -> dict[str, Any]:
    if witness.solution is None or witness.status != "PASS":
        return {
            "daily_distances": [],
            "below": "",
            "within": "",
            "above": "",
            "overlap": "NA_NO_FEASIBLE_WITNESS",
            "two_sides": "NA_NO_FEASIBLE_WITNESS",
        }
    distance_by_physical: dict[str, float] = defaultdict(float)
    for route in witness.solution.routes:
        physical = route.vehicle_id.split("#T", 1)[0]
        distance_by_physical[physical] += sum(
            built.instance.arc_metrics(left, right, "cv", fallback_speed_mps=1.0)[0]
            for left, right in zip(route.node_sequence, route.node_sequence[1:])
        ) / 1000.0
    finite = [value for value in critical_values if math.isfinite(value)]
    if not finite:
        return {
            "daily_distances": sorted(distance_by_physical.values()),
            "below": len(distance_by_physical),
            "within": 0,
            "above": 0,
            "overlap": "NO_FINITE_CRITICAL_BAND",
            "two_sides": "FAIL_NO_FINITE_CRITICAL_BAND",
        }
    lower, upper = min(finite), max(finite)
    values = sorted(distance_by_physical.values())
    below = sum(value < lower for value in values)
    within = sum(lower <= value <= upper for value in values)
    above = sum(value > upper for value in values)
    return {
        "daily_distances": values,
        "below": below,
        "within": within,
        "above": above,
        "overlap": "PASS_OVERLAP" if within > 0 else "NO_OVERLAP",
        "two_sides": (
            "PASS_TWO_SIDES"
            if below > 0 and above > 0
            else (
                "FAIL_NO_BELOW_AND_NO_ABOVE"
                if below == 0 and above == 0
                else "FAIL_NO_BELOW"
                if below == 0
                else "FAIL_NO_ABOVE"
            )
        ),
    }


def lunch_health(
    built: BuiltInstance,
    witness: WitnessResult,
) -> dict[str, Any]:
    if witness.status != "PASS":
        return {
            "rows": [],
            "vehicle_count": "",
            "total_kwh": "",
            "min_kwh": "",
            "median_kwh": "",
            "max_kwh": "",
        }
    curve = M17_FAST_SHAPE_SCALED_60KW_PWL.scale(
        capacity_kwh=EV_BATTERY_KWH,
        reference_power_kw=DEPOT_POWER_KW,
    )
    rows = []
    for physical, scheduled in sorted(witness.scheduled_by_physical.items()):
        am = [item for item in scheduled if item.plan.shift_id == "AM"]
        pm = [item for item in scheduled if item.plan.shift_id == "PM"]
        if not am or not pm:
            continue
        first_pm = min(pm, key=lambda item: item.departure_second)
        loading_hours = first_pm.plan.volume_m3 * LOADING_HOURS_PER_M3
        charge_seconds = max(0.0, 2.0 - loading_hours) * 3600.0
        end_energy = curve.reachable_energy_kwh(0.0, charge_seconds)
        rows.append(
            {
                "instance_id": built.identity.new_instance_id,
                "physical_vehicle_id": physical,
                "depot_id": first_pm.plan.depot_id,
                "first_pm_volume_m3": first_pm.plan.volume_m3,
                "loading_hours": loading_hours,
                "available_charge_hours": charge_seconds / 3600.0,
                "chargeable_kwh_60kw_from_zero": end_energy,
                "curve_id": M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id,
            }
        )
    values = [float(row["chargeable_kwh_60kw_from_zero"]) for row in rows]
    return {
        "rows": rows,
        "vehicle_count": len(rows),
        "total_kwh": sum(values),
        "min_kwh": min(values) if values else 0.0,
        "median_kwh": statistics.median(values) if values else 0.0,
        "max_kwh": max(values) if values else 0.0,
    }


def fleet_health(witness: WitnessResult) -> dict[str, Any]:
    if witness.solution is None or witness.status != "PASS":
        return {
            "trip_count": "",
            "am_trip_count": "",
            "pm_trip_count": "",
            "physical_vehicle_count": "",
            "reduction_count": "",
            "reduction_pct": "",
            "trip_distribution": "",
            "max_trips": "",
        }
    trip_count = len(witness.solution.routes)
    am = sum(plan.shift_id == "AM" for plan in witness.plans)
    pm = sum(plan.shift_id == "PM" for plan in witness.plans)
    physical = len(witness.scheduled_by_physical)
    counts = Counter(len(routes) for routes in witness.scheduled_by_physical.values())
    return {
        "trip_count": trip_count,
        "am_trip_count": am,
        "pm_trip_count": pm,
        "physical_vehicle_count": physical,
        "reduction_count": trip_count - physical,
        "reduction_pct": 100.0 * (trip_count - physical) / trip_count,
        "trip_distribution": json.dumps(
            {str(key): counts[key] for key in sorted(counts)},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "max_trips": max(counts),
    }


def matrix_reference_payload(
    built: BuiltInstance,
    matrix_hashes: Mapping[str, str],
) -> dict[str, Any]:
    source_id = built.geometry.matrix_source_instance_id
    profiles: dict[str, Any] = {}
    for profile in ("cv", "ev"):
        files = {}
        for filename in (
            "road_distance_m.csv",
            "road_duration_s.csv",
            "road_sum_v2d_m3_s2.csv",
        ):
            relative = f"instances/{source_id}/{profile}/{filename}"
            files[filename] = {
                "path": str((SOURCE_MATRICES.relative_to(REPO) / relative).as_posix()),
                "sha256": matrix_hashes[relative],
            }
        profiles[profile] = files
    return {
        "schema": "resetp.china81-suite-matrix-reference.v1",
        "instance_id": built.identity.new_instance_id,
        "source_instance_id": source_id,
        "source_authority": str(SOURCE_MATRICES.relative_to(REPO)),
        "node_mapping_file": "source_mapping.csv",
        "selection_semantics": (
            "matrix rows and columns are selected in nodes.csv order through "
            "new_node_id -> source_node_id; frozen matrices are not copied"
        ),
        "profiles": profiles,
    }


def instance_hash_manifest(instance_root: Path) -> dict[str, str]:
    files = sorted(
        path
        for path in instance_root.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    return {str(path.relative_to(instance_root)): sha256(path) for path in files}


def suite_hash_manifest(root: Path) -> dict[str, str]:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    return {str(path.relative_to(REPO)): sha256(path) for path in files}


def health_row(
    built: BuiltInstance,
    contest: Sequence[Mapping[str, Any]],
    witness: WitnessResult,
    fleet: Mapping[str, Any],
    lunch: Mapping[str, Any],
    per_km: Mapping[str, Any],
    distance: Mapping[str, Any],
    instance_manifest_sha256: str,
) -> dict[str, Any]:
    count = built.identity.size
    contest_counts = {
        threshold: (
            sum(float(row["relative_gap"]) < threshold for row in contest)
            if contest
            else ""
        )
        for threshold in CONTEST_THRESHOLDS
    }
    contest_shares = {
        threshold: (
            float(contest_counts[threshold]) / count
            if contest_counts[threshold] != ""
            else ""
        )
        for threshold in CONTEST_THRESHOLDS
    }
    geometry_pass = (
        contest_shares[MAIN_CONTEST_THRESHOLD] != ""
        and GEOMETRY_PASS_MIN
        <= float(contest_shares[MAIN_CONTEST_THRESHOLD])
        <= GEOMETRY_PASS_MAX
    )
    critical = {
        key: float(per_km["scenarios"][key]["critical_daily_km"])
        for key in ("valley", "flat", "peak")
    }
    flags = []
    if not geometry_pass:
        observed = contest_shares[MAIN_CONTEST_THRESHOLD]
        observed_text = "NA" if observed == "" else f"{float(observed):.3f}"
        flags.append(
            f"GEOMETRY_GATE:25pct share {observed_text} outside 0.30-0.45; "
            f"{built.geometry.note}"
        )
    if witness.status != "PASS":
        flags.append(f"EDF_WITNESS:{witness.reason}")
    if built.shift_assignment_flags:
        flags.append(
            "SHIFT_REACHABILITY:" + "; ".join(built.shift_assignment_flags)
        )
    if distance["two_sides"] != "PASS_TWO_SIDES":
        flags.append(f"MIXED_TWO_SIDES:{distance['two_sides']}")
    scenarios = per_km["scenarios"]
    daily = list(distance["daily_distances"])
    return {
        "evidence_class": "FACT",
        "instance_id": built.identity.new_instance_id,
        "source_instance_id": built.identity.source_instance_id,
        "region": built.identity.region,
        "customer_count": count,
        "replicate": built.identity.replicate,
        "source_catalog_cities": "|".join(
            sorted({str(row["city"]) for row in built.order_rows})
        ),
        "depot_ids": "|".join(built.geometry.depot_ids),
        "geometry_mode": built.geometry.mode,
        "matrix_source_instance_id": built.geometry.matrix_source_instance_id,
        "reanchored_customer_count": built.geometry.reanchored_customer_count,
        "reanchored_customer_share": (
            built.geometry.reanchored_customer_count / count
        ),
        "contestable_count_20pct": contest_counts[0.20],
        "contestable_share_20pct": contest_shares[0.20],
        "contestable_count_25pct": contest_counts[0.25],
        "contestable_share_25pct": contest_shares[0.25],
        "contestable_count_30pct": contest_counts[0.30],
        "contestable_share_30pct": contest_shares[0.30],
        "contestability_gate": "PASS" if geometry_pass else "FAIL",
        "edf_witness_status": witness.status,
        "shift_reachability_switch_count": sum(
            row["shift_reachability_status"]
            == "SWITCHED_TO_REACHABLE_ALTERNATIVE"
            for row in built.order_rows
        ),
        "shift_both_unreachable_count": len(built.shift_assignment_flags),
        "served_customers": witness.served_customers,
        "total_customers": count,
        "served_demand_kg": witness.served_demand_kg,
        "total_demand_kg": sum(
            float(row["demand_kg"]) for row in built.order_rows
        ),
        "trip_count_no_reuse": fleet["trip_count"],
        "trip_count_am": fleet["am_trip_count"],
        "trip_count_pm": fleet["pm_trip_count"],
        "physical_vehicle_count_reuse": fleet["physical_vehicle_count"],
        "fleet_reduction_upper_count_vs_no_reuse": fleet["reduction_count"],
        "fleet_reduction_upper_pct_vs_no_reuse": fleet["reduction_pct"],
        "trips_per_vehicle_distribution": fleet["trip_distribution"],
        "max_trips_per_vehicle": fleet["max_trips"],
        "lunch_reused_vehicle_count": lunch["vehicle_count"],
        "lunch_chargeable_kwh_60kw_total": lunch["total_kwh"],
        "lunch_chargeable_kwh_60kw_min_per_vehicle": lunch["min_kwh"],
        "lunch_chargeable_kwh_60kw_median_per_vehicle": lunch["median_kwh"],
        "lunch_chargeable_kwh_60kw_max_per_vehicle": lunch["max_kwh"],
        "critical_daily_km_valley": critical["valley"],
        "critical_daily_km_flat": critical["flat"],
        "critical_daily_km_peak": critical["peak"],
        "critical_band_min_km": min(critical.values()),
        "critical_band_max_km": max(critical.values()),
        "witness_daily_km_min": min(daily) if daily else "",
        "witness_daily_km_median": statistics.median(daily) if daily else "",
        "witness_daily_km_max": max(daily) if daily else "",
        "critical_band_below_vehicle_count": distance["below"],
        "critical_band_overlap_vehicle_count": distance["within"],
        "critical_band_above_vehicle_count": distance["above"],
        "critical_band_overlap_status": distance["overlap"],
        "mixed_fleet_two_sides_status": distance["two_sides"],
        "per_km_basis": per_km["basis"],
        "cv_fuel_l_per_km": per_km["cv_fuel_l_per_km"],
        "cv_cost_cny_per_km": per_km["cv_cost_cny_per_km"],
        "cv_emission_kgco2e_per_km": per_km["cv_emission_kg_per_km"],
        "ev_drive_kwh_per_km": per_km["ev_kwh_per_km"],
        "ev_cost_cny_per_km_valley": scenarios["valley"]["ev_cost_cny_per_km"],
        "ev_cost_cny_per_km_flat": scenarios["flat"]["ev_cost_cny_per_km"],
        "ev_cost_cny_per_km_peak": scenarios["peak"]["ev_cost_cny_per_km"],
        "ev_emission_kgco2e_per_km_valley": scenarios["valley"]["ev_emission_kg_per_km"],
        "ev_emission_kgco2e_per_km_flat": scenarios["flat"]["ev_emission_kg_per_km"],
        "ev_emission_kgco2e_per_km_peak": scenarios["peak"]["ev_emission_kg_per_km"],
        "fleet_parameter_class_id": FLEET_PARAMETER_CLASS_ID,
        "depot_site_power_kw_shadow": DEPOT_POWER_KW,
        "depot_charging_curve_id": M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id,
        "instance_artifact_manifest_sha256": instance_manifest_sha256,
        "FLAG": " | ".join(flags),
    }


def witness_rows(
    built: BuiltInstance,
    witness: WitnessResult,
) -> list[dict[str, Any]]:
    if witness.solution is None:
        return []
    plan_by_signature = {
        (plan.depot_id, plan.shift_id, plan.customers): plan
        for plan in witness.plans
    }
    rows = []
    for route in sorted(
        witness.solution.routes,
        key=lambda item: (item.vehicle_id.split("#T", 1)[0], item.vehicle_id),
    ):
        shift_id = str(built.orders_by_customer[route.node_sequence[1]]["shift_id"])
        plan = plan_by_signature[
            (route.home_depot_id, shift_id, tuple(route.node_sequence[1:-1]))
        ]
        rows.append(
            {
                "instance_id": built.identity.new_instance_id,
                "witness_status": witness.status,
                "physical_vehicle_id": route.vehicle_id.split("#T", 1)[0],
                "route_vehicle_id": route.vehicle_id,
                "depot_id": route.home_depot_id,
                "shift_id": shift_id,
                "customers": "|".join(plan.customers),
                "customer_count": len(plan.customers),
                "volume_m3": plan.volume_m3,
                "demand_kg": plan.demand_kg,
                "departure_minute": witness.departures[route.vehicle_id] / 60.0,
                "return_minute": next(
                    item.return_second / 60.0
                    for item in witness.scheduled_by_physical[
                        route.vehicle_id.split("#T", 1)[0]
                    ]
                    if item.plan == plan
                ),
                "distance_km": plan.distance_m / 1000.0,
            }
        )
    return rows


def fleet_rows(
    built: BuiltInstance,
    witness: WitnessResult,
) -> list[dict[str, Any]]:
    by_depot: dict[str, int] = Counter(
        physical.removeprefix("CV_").rsplit("_", 1)[0]
        for physical in witness.scheduled_by_physical
    )
    customer_ceiling = Counter(built.customer_home_depot.values())
    rows = []
    facilities = {row["city"]: row for row in read_csv(SOURCE_STATIC / "facilities.csv")}
    for depot_id in built.geometry.depot_ids:
        city = depot_id.removeprefix("D_")
        measured = by_depot.get(depot_id, 0)
        cap = measured if witness.status == "PASS" else max(1, customer_ceiling[depot_id])
        rows.append(
            {
                "instance_id": built.identity.new_instance_id,
                "depot_id": depot_id,
                "city": city,
                "base_all_cv_routes_Rd": cap,
                "base_all_ev_routes_Re": cap,
                "num_cv": cap,
                "num_ev": cap,
                "total_fleet_cap": 2 * cap,
                "default_fleet_electrification_percent_metadata_only": "ENDOGENOUS_NOT_FIXED",
                "configured_depot_gun_count_if_finite": facilities[city]["depot_gun_count"],
                "depot_charge_power_kw": DEPOT_POWER_KW,
                "depot_charger_capacity_default": "UNBOUNDED",
                "fleet_parameter_class": FLEET_PARAMETER_CLASS_ID,
                "fleet_cap_source": (
                    "EDF_TWO_SHIFT_PHYSICAL_WITNESS"
                    if witness.status == "PASS"
                    else "CUSTOMER_COUNT_CONSERVATIVE_CEILING_WITNESS_FAILED"
                ),
                "charger_parameter_class": (
                    "P43_I_CHINA_LOGISTICS_DEPOT_DC_60KW_DEFAULT"
                ),
            }
        )
    return rows


def write_instance_outputs(
    output_root: Path,
    built: BuiltInstance,
    contest: Sequence[Mapping[str, Any]],
    witness: WitnessResult,
    matrix_hashes: Mapping[str, str],
) -> str:
    root = output_root / "instances" / built.identity.new_instance_id
    root.mkdir(parents=True, exist_ok=False)
    write_csv(root / "nodes.csv", built.node_rows)
    write_csv(root / "orders.csv", built.order_rows)
    write_csv(root / "source_mapping.csv", built.source_mapping_rows)
    if contest:
        write_csv(root / "contestability.csv", contest)
    else:
        write_csv(
            root / "contestability.csv",
            [],
            (
                "instance_id",
                "customer_id",
                "home_depot_id",
                "nearest_depot",
                "second_depot",
                "nearest_cost_cny",
                "second_cost_cny",
                "absolute_gap_cny",
                "relative_gap",
                "contestable_at_20pct",
                "contestable_at_25pct",
                "contestable_at_30pct",
            ),
        )
    write_json(
        root / "shift_contract.json",
        {
            "schema": "resetp.private-two-shift-contract.v1",
            "instance_id": built.identity.new_instance_id,
            "attendance": {"start_minute": 480.0, "end_minute": 1140.0},
            "shifts": SHIFT_ROWS,
            "lunch": {
                "start_minute": 660.0,
                "end_minute": 780.0,
                "return_to_depot_required": True,
                "loading_and_charging_sequential": True,
            },
            "order_allocation": {
                "AM": sum(row["shift_id"] == "AM" for row in built.order_rows),
                "PM": sum(row["shift_id"] == "PM" for row in built.order_rows),
                "preferred_rule": "source ready-time rank; each third order to AM",
                "reachability_preflight": (
                    "frozen CV road duration from assigned home depot; "
                    "switch to the other shift when the preferred shifted "
                    "window cannot be reached; minimally delay the alternative "
                    "window within that shift while preserving its width"
                ),
                "switched_customer_count": sum(
                    row["shift_reachability_status"]
                    == "SWITCHED_TO_REACHABLE_ALTERNATIVE"
                    for row in built.order_rows
                ),
                "both_shifts_unreachable_count": len(
                    built.shift_assignment_flags
                ),
            },
            "vehicle_volume_capacity_m3": VEHICLE_VOLUME_CAPACITY_M3,
            "vehicle_payload_capacity_kg": VEHICLE_PAYLOAD_CAPACITY_KG,
            "loading_hours_per_m3": LOADING_HOURS_PER_M3,
        },
    )
    write_json(
        root / "matrix_reference.json",
        matrix_reference_payload(built, matrix_hashes),
    )
    write_json(
        root / "provenance.json",
        {
            "schema": "resetp.china81-suite-instance-provenance.v1",
            "instance_id": built.identity.new_instance_id,
            "source_task_instance_id": built.identity.source_instance_id,
            "matrix_source_instance_id": built.geometry.matrix_source_instance_id,
            "geometry_mode": built.geometry.mode,
            "geometry_note": built.geometry.note,
            "reanchored_customer_count": built.geometry.reanchored_customer_count,
            "source_order_authority": str(SOURCE_ORDERS.relative_to(REPO)),
            "source_static_authority": str(SOURCE_STATIC.relative_to(REPO)),
            "source_matrix_authority": str(SOURCE_MATRICES.relative_to(REPO)),
            "formal_search_evaluations": 0,
            "old_instance_overwritten": False,
            "fleet_parameter_class_id": FLEET_PARAMETER_CLASS_ID,
            "depot_site_power_kw_shadow": DEPOT_POWER_KW,
            "depot_charging_curve_id": M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id,
            "optional_22kw_curve_id": M17_22KW_NORMAL_PWL.curve_id,
            "parameter_authority_hashes": {
                str(path): sha256(REPO / path)
                for path in PARAMETER_AUTHORITIES
            },
        },
    )
    write_json(
        root / "witness_status.json",
        {
            "status": witness.status,
            "reason": witness.reason,
            "served_customers": witness.served_customers,
            "served_demand_kg": witness.served_demand_kg,
            "violation_count": len(witness.violations),
            "violations": list(witness.violations),
            "construction_rule": (
                "home-depot two-shift EDF deterministic first-feasible packing; "
                "one AM route per vehicle; exact minimum feasible PM chain cover; "
                "same-depot cross-shift vehicle reuse"
            ),
            "search_evaluations": 0,
        },
    )
    manifest = instance_hash_manifest(root)
    write_json(root / "artifact_hashes.json", manifest)
    return sha256(root / "artifact_hashes.json")


def render_report(
    identities: Sequence[ParsedIdentity],
    source_catalog: Mapping[str, Mapping[str, str]],
    health_rows: Sequence[Mapping[str, Any]],
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
    output_bytes: int,
) -> str:
    flag_rows = [row for row in health_rows if row["FLAG"]]
    geometry_pass = sum(row["contestability_gate"] == "PASS" for row in health_rows)
    witness_pass = sum(row["edf_witness_status"] == "PASS" for row in health_rows)
    fully_healthy = sum(
        row["contestability_gate"] == "PASS"
        and row["edf_witness_status"] == "PASS"
        and row["mixed_fleet_two_sides_status"] == "PASS_TWO_SIDES"
        for row in health_rows
    )
    lines = [
        "SUITE_DONE",
        "",
        "# China81 V3 两班次套件重建与结构健康报告（2026-08-12）",
        "",
        "## 1. 原 81 个算例的区域 × 规模 × 副本 × 城市结构",
        "",
        "下表每行及其中全部数字均为 `FACT`，逐字来自冻结 `instance_catalog.csv`；副本号由 `instance_id` 解析。",
        "",
        "| 标签 | 原 instance_id | 区域 | 客户数 | 副本 | 城市 | 城市数 |",
        "|---|---|---|---:|---:|---|---:|",
    ]
    for identity in identities:
        row = source_catalog[identity.source_instance_id]
        lines.append(
            f"| FACT | `{identity.source_instance_id}` | {identity.region} | "
            f"{identity.size} | {identity.replicate} | {row['cities']} | "
            f"{row['city_count']} |"
        )
    lines.extend(
        [
            "",
            "`FACT`：目录结构为 3 个区域 × 9 个规模 × 3 个副本 = 81 个算例；规模为 10、15、20、25、50、75、100、150、200 个客户。",
            "",
            "## 2. 本轮完成情况",
            "",
            f"- `FACT`：新 V3 instance_id 共 {len(health_rows)} 个；旧算例覆盖或删除数为 0。",
            f"- `FACT`：25% 可争夺比例落在 30%–45% 的算例为 {geometry_pass}/{len(health_rows)}。",
            f"- `FACT`：两班次 EDF 完整服务见证通过 {witness_pass}/{len(health_rows)}。",
            f"- `FACT`：可争夺、EDF 和临界点两侧有车三项同时通过 {fully_healthy}/{len(health_rows)}。",
            f"- `FACT`：带至少一项 FLAG 的算例为 {len(flag_rows)}/{len(health_rows)}；失败没有被删行或改参数。",
            f"- `FACT`：新增数据与报告合计 {output_bytes} 字节（{output_bytes / 1024 ** 2:.3f} MiB），低于 5 GiB 上限。",
            "- `FACT`：正式求解器实验次数为 0；所有运行均为确定性构造、EDF 见证、完整检查器复核或真实弧成本/排放复算。",
            "",
            "## 3. 构造口径",
            "",
            "- `USER DECISION`：08:00–11:00、11:00–13:00 回场午休、13:00–19:00 两班次；纯送货按原 ready-time 排序，每三单第一单优先进上午，其余优先进下午；分配前用冻结路网检查从归属车场到客户的时窗可达性，不可达时改分另一班次。",
            "- `FACT`：每一单的新时间窗宽度与其原实证宽度逐条相等；建造器同时保存原窗和新窗。",
            "- `USER DECISION`：100 客户以内采用区域内最近真实车场对；150/200 客户允许跨城多车场；25% 主口径验收范围为 30%–45%。",
            "- `FACT`：坐标只来自冻结 `nodes.csv` 中有 source identity 的真实设施/OSM 点；矩阵没有复制，逐例 `matrix_reference.json` 指向冻结矩阵及其 SHA-256。",
            "- `USER DECISION`：CV/EV 固定成本为 170/220 元每车日，EV 非能源里程成本为 0.9145 元/km；默认场站充电为 60 kW 与 `M17_FAST_SHAPE_SCALED_60KW_PWL`，22 kW 曲线保留为可选情景。",
            "- `FACT`：车队身份为 `ENDOGENOUS_RD_RE_NO_ADDITIONAL_TOTAL_CAP`；通过 EDF 的算例按实体车见证登记 Rd/Re，失败算例只登记一客一车的保守供给上限并保留 FLAG。",
            "",
            "## 4. suite_health.csv 读法",
            "",
            "`FACT`：`suite_health.csv` 恰有 81 行。每行同时保存 20%/25%/30% 可争夺比例、客户与需求服务完整性、趟/车与复用缩减、60 kW 午休可充电量、谷/平/峰临界日里程及与见证日里程的交叠、CV/EV 真实弧每公里成本和排放，以及失败原因。",
            "",
            "`FACT`：午休可充电量使用 77.28 kWh 电池、60 kW 登记曲线，从 0 kWh 起按分段曲线积分；每辆车先扣除 `0.1 h/m³ × 首个下午趟实际体积`，再汇总可用充电量。字段名明确保留 `from_zero` 口径的来源含义。",
            "",
            "`FACT`：临界日里程按 `50 元/日 ÷ (CV 每公里成本 − EV 每公里成本)` 逐算例复算；CV 燃油与 EV 驱动能耗来自该算例 EDF 见证的真实定向弧。没有可行见证时，每公里列改用逐客直达真实弧，`per_km_basis` 和 FLAG 明示，不伪装成见证。",
            "",
            "## 5. FLAG 原样汇总",
            "",
        ]
    )
    if not flag_rows:
        lines.append("- `FACT`：无 FLAG。")
    else:
        lines.append("下列每行均为 `FACT`，原因逐字来自本轮结构检查：")
        lines.append("")
        for row in flag_rows:
            lines.append(f"- `FACT` `{row['instance_id']}`：{row['FLAG']}")
    lines.extend(
        [
            "",
            "## 6. 证据与红线",
            "",
            "三个受保护文件任务前后 SHA-256：",
            "",
            "| 标签 | 文件 | 任务前 | 任务后 |",
            "|---|---|---|---|",
        ]
    )
    for path in PROTECTED:
        key = str(path)
        lines.append(
            f"| FACT | `{key}` | `{protected_before[key]}` | `{protected_after[key]}` |"
        )
    lines.extend(
        [
            "",
            "- `FACT`：源静态、订单、道路矩阵和运行日权威只读；新数据只写入 `data/ChinaInstances/china81_suite_v3_20260812/`。",
            "- `FACT`：数据根、报告根和每个实例目录均登记 SHA-256；provenance 保留原始班次文件、规格与用户裁决、几何文献判据、试点报告、60 kW 报告、曲线源码、地点源、矩阵源、映射规则与零搜索身份。",
            "",
            "## 7. 产物",
            "",
            "- `FACT`：`data/ChinaInstances/china81_suite_v3_20260812/` 保存 81 个新实例、合并 catalog/orders/fleet/provenance、矩阵就地引用与哈希。",
            "- `FACT`：`solver/reports/suite_rebuild_20260812/suite_health.csv` 为 81 行总健康表。",
            "- `FACT`：`health_witness_routes.csv`、`lunch_charge_rows.csv`、`raw_runs.csv` 保存逐路、逐午休车辆和逐实例原始结构结果。",
            "",
        ]
    )
    return "\n".join(lines)


def build_suite(output_root: Path, report_root: Path) -> None:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite suite data: {output_root}")
    if report_root.exists():
        raise FileExistsError(f"refusing to overwrite suite report: {report_root}")
    protected_before = {str(path): sha256(REPO / path) for path in PROTECTED}
    identities = catalog_identities()
    source_catalog_rows = read_csv(SOURCE_STATIC / "instance_catalog.csv")
    source_catalog = {row["instance_id"]: row for row in source_catalog_rows}
    tasks_by_instance = source_orders_by_instance()
    closest_pairs = closest_facility_pair_by_region()
    matrix_manifest = json.loads(
        (SOURCE_MATRICES / "artifact_hashes.json").read_text(encoding="utf-8")
    )["sha256"]
    cache = SourceBundleCache()

    output_root.mkdir(parents=True, exist_ok=False)
    report_root.mkdir(parents=True, exist_ok=False)
    write_json(
        output_root / "build_status.json",
        {
            "status": "IN_PROGRESS",
            "completed_instances": 0,
            "total_instances": 81,
            "formal_search_evaluations": 0,
        },
    )

    health_rows: list[dict[str, Any]] = []
    all_orders: list[dict[str, Any]] = []
    all_catalog: list[dict[str, Any]] = []
    all_membership: list[dict[str, Any]] = []
    all_fleet: list[dict[str, Any]] = []
    all_witness: list[dict[str, Any]] = []
    all_lunch: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []

    try:
        for ordinal, identity in enumerate(identities, start=1):
            original = cache.get(identity.source_instance_id)
            geometry = choose_geometry(identity, original, cache, closest_pairs)
            built = build_instance(
                identity,
                tasks_by_instance[identity.source_instance_id],
                geometry,
                cache,
            )
            contest = contestability_rows(built)
            witness = build_witness(built)
            fleet = fleet_health(witness)
            lunch = lunch_health(built, witness)
            per_km = per_km_health(built, witness)
            critical_values = [
                float(per_km["scenarios"][scenario]["critical_daily_km"])
                for scenario in ("valley", "flat", "peak")
            ]
            distance = witness_distance_health(built, witness, critical_values)
            manifest_sha = write_instance_outputs(
                output_root,
                built,
                contest,
                witness,
                matrix_manifest,
            )
            row = health_row(
                built,
                contest,
                witness,
                fleet,
                lunch,
                per_km,
                distance,
                manifest_sha,
            )
            health_rows.append(row)
            all_orders.extend(dict(item) for item in built.order_rows)
            all_fleet.extend(fleet_rows(built, witness))
            all_witness.extend(witness_rows(built, witness))
            all_lunch.extend(dict(item) for item in lunch["rows"])
            all_membership.extend(
                {
                    "instance_id": identity.new_instance_id,
                    "node_id": item["new_node_id"],
                    "declared_city": item["source_city"],
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "gis_status": "PASS_SOURCE_BOUND_REAL_POINT",
                    "source_instance_id": item["source_instance_id"],
                    "source_node_id": item["source_node_id"],
                }
                for item in built.source_mapping_rows
            )
            all_catalog.append(
                {
                    "instance_id": identity.new_instance_id,
                    "source_instance_id": identity.source_instance_id,
                    "region": identity.region,
                    "customer_count": identity.size,
                    "replicate": identity.replicate,
                    "depot_count": len(geometry.depot_ids),
                    "cities": "|".join(sorted({str(item["city"]) for item in built.node_rows})),
                    "node_count": len(built.node_rows),
                    "matrix_source_instance_id": geometry.matrix_source_instance_id,
                    "formal_search_evaluations": 0,
                    "instance_artifact_manifest_sha256": manifest_sha,
                }
            )
            raw_rows.append(
                {
                    "instance_id": identity.new_instance_id,
                    "ordinal": ordinal,
                    "geometry_gate": row["contestability_gate"],
                    "edf_witness_status": row["edf_witness_status"],
                    "critical_band_overlap_status": row["critical_band_overlap_status"],
                    "flag": row["FLAG"],
                    "formal_search_evaluations": 0,
                }
            )
            write_json(
                output_root / "build_status.json",
                {
                    "status": "IN_PROGRESS",
                    "completed_instances": ordinal,
                    "last_instance_id": identity.new_instance_id,
                    "total_instances": 81,
                    "formal_search_evaluations": 0,
                },
            )
            keep = {
                f"cn-{region}-200c-{rep}-V2-LOCATIONS"
                for region in ("cy", "jjj", "prd")
                for rep in ("01", "02", "03")
            }
            keep.add(identity.source_instance_id)
            cache.retain_only(keep)

        if len(health_rows) != 81:
            raise RuntimeError("suite health row count is not 81")
        if len(all_orders) != 5805:
            raise RuntimeError("suite order total is not 5805")

        facilities = read_csv(SOURCE_STATIC / "facilities.csv")
        for row in facilities:
            row["depot_site_power_kw_shadow"] = f"{DEPOT_POWER_KW:.1f}"
            row["depot_parameter_class"] = (
                "P43_I_CHINA_LOGISTICS_DEPOT_DC_60KW_DEFAULT"
            )
        write_csv(output_root / "facilities.csv", facilities)
        write_csv(output_root / "orders.csv", all_orders)
        write_csv(output_root / "instance_catalog.csv", all_catalog)
        write_csv(output_root / "node_city_membership.csv", all_membership)
        write_csv(output_root / "fleet_caps.csv", all_fleet)
        write_json(
            output_root / "vehicle_cost_contract.json",
            {
                "schema": "resetp.vehicle-cost-contract.v3-suite",
                "cv": {
                    "non_energy_cny_per_km": CV_NON_ENERGY_CNY_PER_KM,
                    "daily_fixed_cny": CV_FIXED_CNY_PER_DAY,
                },
                "ev": {
                    "base_non_energy_cny_per_km": 0.6700,
                    "battery_depreciation_cny_per_km": 0.2445,
                    "effective_non_energy_cny_per_km": EV_NON_ENERGY_CNY_PER_KM,
                    "daily_fixed_cny": EV_FIXED_CNY_PER_DAY,
                    "daily_fixed_premium_vs_cv_cny": EV_FIXED_PREMIUM_CNY_PER_DAY,
                },
            },
        )
        write_json(
            output_root / "metadata.json",
            {
                "schema": "resetp.china81-suite-v3-two-shift.v1",
                "created_date": "2026-08-12",
                "instance_count": 81,
                "order_count": 5805,
                "formal_search_allowed": False,
                "formal_search_evaluations": 0,
                "fleet_parameter_class_id": FLEET_PARAMETER_CLASS_ID,
                "default_depot_site_power_kw_shadow": DEPOT_POWER_KW,
                "default_depot_curve_id": M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id,
                "optional_depot_scenario": {
                    "power_kw": 22.0,
                    "curve_id": M17_22KW_NORMAL_PWL.curve_id,
                },
                "source_authority_hashes": {
                    str((SOURCE_STATIC / "artifact_hashes.json").relative_to(REPO)): sha256(
                        SOURCE_STATIC / "artifact_hashes.json"
                    ),
                    str((SOURCE_MATRICES / "artifact_hashes.json").relative_to(REPO)): sha256(
                        SOURCE_MATRICES / "artifact_hashes.json"
                    ),
                    str(
                        (
                            SOURCE_ORDERS.parent / "artifact_hashes.json"
                        ).relative_to(REPO)
                    ): sha256(SOURCE_ORDERS.parent / "artifact_hashes.json"),
                    str((SOURCE_RUNTIME / "artifact_hashes.json").relative_to(REPO)): sha256(
                        SOURCE_RUNTIME / "artifact_hashes.json"
                    ),
                },
                "parameter_authority_hashes": {
                    str(path): sha256(REPO / path)
                    for path in PARAMETER_AUTHORITIES
                },
                "matrix_storage": "REFERENCE_ONLY_NO_MATRIX_COPY",
            },
        )
        write_json(
            output_root / "decision.json",
            {
                "completion": "SUITE_DONE",
                "run_kind": "CONSTRUCTION_AND_STRUCTURAL_HEALTH_NO_FORMAL_EXPERIMENT",
                "formal_experiment_started": False,
                "old_instances_overwritten": False,
                "protected_files_modified": False,
                "flagged_instances_retained": True,
            },
        )
        write_csv(report_root / "suite_health.csv", health_rows)
        if all_witness:
            write_csv(report_root / "health_witness_routes.csv", all_witness)
        else:
            write_csv(
                report_root / "health_witness_routes.csv",
                [],
                ("instance_id", "witness_status"),
            )
        if all_lunch:
            write_csv(report_root / "lunch_charge_rows.csv", all_lunch)
        else:
            write_csv(
                report_root / "lunch_charge_rows.csv",
                [],
                ("instance_id", "physical_vehicle_id"),
            )
        write_csv(report_root / "raw_runs.csv", raw_rows)
        write_json(
            report_root / "metadata.json",
            {
                "run_kind": "deterministic_suite_construction_health_check",
                "instance_count": 81,
                "formal_search_evaluations": 0,
                "matrix_storage": "REFERENCE_ONLY_NO_MATRIX_COPY",
                "protected_hashes_before": protected_before,
                "fleet_parameter_class_id": FLEET_PARAMETER_CLASS_ID,
            },
        )
        write_json(
            report_root / "decision.json",
            {
                "completion": "SUITE_DONE",
                "suite_health_rows": 81,
                "formal_experiment_started": False,
                "flags_preserved": True,
            },
        )
        write_json(
            output_root / "build_status.json",
            {
                "status": "SUITE_DONE",
                "completed_instances": 81,
                "total_instances": 81,
                "formal_search_evaluations": 0,
            },
        )

        protected_after = {str(path): sha256(REPO / path) for path in PROTECTED}
        if protected_before != protected_after:
            raise RuntimeError("a protected evaluator changed during suite construction")
        report_path = report_root / "report.md"
        report_path.write_text(
            render_report(
                identities,
                source_catalog,
                health_rows,
                protected_before,
                protected_after,
                0,
            ),
            encoding="utf-8",
        )
        write_json(output_root / "artifact_hashes.json", suite_hash_manifest(output_root))
        write_json(report_root / "artifact_hashes.json", suite_hash_manifest(report_root))
        for _ in range(4):
            output_bytes = sum(
                path.stat().st_size
                for root in (output_root, report_root)
                for path in root.rglob("*")
                if path.is_file() and not path.name.startswith("._")
            )
            if output_bytes > 5 * 1024**3:
                raise RuntimeError("suite output exceeds the 5 GiB user limit")
            report_path.write_text(
                render_report(
                    identities,
                    source_catalog,
                    health_rows,
                    protected_before,
                    protected_after,
                    output_bytes,
                ),
                encoding="utf-8",
            )
            write_json(
                report_root / "artifact_hashes.json",
                suite_hash_manifest(report_root),
            )
            finalized_bytes = sum(
                path.stat().st_size
                for root in (output_root, report_root)
                for path in root.rglob("*")
                if path.is_file() and not path.name.startswith("._")
            )
            if finalized_bytes == output_bytes:
                break
        else:
            raise RuntimeError("suite byte-size report did not stabilize")
    except Exception as exc:
        write_json(
            output_root / "build_status.json",
            {
                "status": "PARTIAL_FAILURE",
                "completed_instances": len(health_rows),
                "total_instances": 81,
                "formal_search_evaluations": 0,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    build_suite(args.output_root.resolve(), args.report_root.resolve())
    print("SUITE_DONE 81")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
