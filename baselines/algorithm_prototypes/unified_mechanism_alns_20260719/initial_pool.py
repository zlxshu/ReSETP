"""Result-blind diverse initial-solution pool for the isolated ALNS prototype.

The module deliberately does not run ALNS or a mechanism expert.  It only
constructs genuinely different complete starts, checks them, and accounts the
K-1 selectable complete-solution scores required by the G0 budget contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Iterable

from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (
    score_reference_solution,
    score_search_candidate,
)
from setp_solver.algorithms.resetp_alns.support.fleet import (
    infer_fleet_limits,
    normalize_solution_vehicle_trips,
)
from setp_solver.algorithms.resetp_alns.support.order_decoder import (
    OrderDecodeContext,
    order_to_solution,
)
from setp_solver.check import check_solution
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import SearchBundle, load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Solution


TOL = 1.0e-9
POOL_SIZE = 12


@dataclass(frozen=True)
class StartBlueprint:
    """One predeclared construction recipe."""

    label: str
    family: str
    order: tuple[str, ...] | None
    type_mode: str
    ev_threshold: float = 0.82


@dataclass
class InitialPoolEntry:
    """One checked and budget-accounted complete start."""

    label: str
    family: str
    type_mode: str
    solution: Solution
    objective: float
    raw_cost: float
    feasible: bool
    violation_count: int
    full_signature: str
    route_signature: str


@dataclass
class InitialPoolResult:
    """Scored pool plus the explicit G0 ledgers."""

    entries: list[InitialPoolEntry]
    archive: list[InitialPoolEntry]
    best: InitialPoolEntry
    anchor: InitialPoolEntry
    candidate_evaluations: int
    reference_replays: int
    construction_attempts: int
    construction_failures: list[dict[str, str]]
    score_counts: dict[str, int]


def build_and_score_initial_pool(
    bundle_dir: str | Path,
    *,
    seed: int,
    prices: Any = DEFAULT_PRICES,
    archive_capacity: int = 6,
) -> InitialPoolResult:
    """Build the frozen twelve-start menu and account exactly eleven choices."""

    bundle = load_search_bundle(bundle_dir)
    blueprints = build_blueprints(bundle, seed=seed, prices=prices)
    if len(blueprints) != POOL_SIZE:
        raise RuntimeError(f"frozen blueprint count drifted: {len(blueprints)} != {POOL_SIZE}")

    solutions: list[tuple[StartBlueprint, Solution]] = []
    failures: list[dict[str, str]] = []
    for index, blueprint in enumerate(blueprints):
        try:
            solution = materialize_blueprint(
                blueprint,
                bundle,
                seed=seed + 104_729 * index,
                prices=prices,
            )
            _assert_exact_customer_cover(solution, bundle.instance)
            violations = check_solution(solution, bundle.instance, prices)
            if violations:
                detail = "; ".join(
                    f"{item.type}:{item.vehicle_id}:{item.location}:{item.detail}"
                    for item in violations[:8]
                )
                raise ValueError(f"infeasible construction: {detail}")
            solutions.append((blueprint, solution))
        except Exception as exc:  # the gate records all frozen-menu failures
            failures.append({"label": blueprint.label, "error": f"{type(exc).__name__}: {exc}"})

    if failures:
        detail = "; ".join(f"{item['label']}={item['error']}" for item in failures)
        raise RuntimeError(f"frozen initial menu did not produce twelve feasible starts: {detail}")
    if len(solutions) != POOL_SIZE:
        raise RuntimeError(f"constructed {len(solutions)} starts, expected {POOL_SIZE}")

    owners = _nearest_depot_owners(bundle.instance)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=POOL_SIZE - 1, target=POOL_SIZE - 1),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    entries: list[InitialPoolEntry] = []
    for index, (blueprint, solution) in enumerate(solutions):
        if index == 0:
            prepared, objective = score_reference_solution(
                solution,
                context,
                phase="initial_pool_anchor",
            )
        else:
            prepared, objective = score_search_candidate(
                solution,
                context,
                channel="initial_pool_choice",
            )
        breakdown = context.score_breakdowns.get(id(prepared))
        if breakdown is None:
            raise RuntimeError(f"missing score breakdown for {blueprint.label}")
        entries.append(
            InitialPoolEntry(
                label=blueprint.label,
                family=blueprint.family,
                type_mode=blueprint.type_mode,
                solution=prepared,
                objective=float(objective),
                raw_cost=float(breakdown["raw_cost"]),
                feasible=bool(breakdown["feasible"]),
                violation_count=int(breakdown["violation_count"]),
                full_signature=solution_signature_hash(prepared),
                route_signature=route_structure_hash(prepared, bundle.instance),
            )
        )

    budget = context.budget
    if budget is None or budget.count != POOL_SIZE - 1:
        raise RuntimeError(
            "initial-pool candidate ledger did not close: "
            f"{getattr(budget, 'count', None)} != {POOL_SIZE - 1}"
        )
    if any(not item.feasible or item.violation_count for item in entries):
        raise RuntimeError("a prepared initial-pool entry failed the complete feasibility score")

    best = min(entries, key=_quality_key)
    archive = select_quality_diverse_archive(
        entries,
        instance=bundle.instance,
        capacity=archive_capacity,
    )
    return InitialPoolResult(
        entries=entries,
        archive=archive,
        best=best,
        anchor=entries[0],
        candidate_evaluations=int(budget.count),
        reference_replays=int(context.score_counts.get("reference", 0)),
        construction_attempts=len(blueprints),
        construction_failures=failures,
        score_counts={str(key): int(value) for key, value in context.score_counts.items()},
    )


def build_blueprints(
    bundle: SearchBundle,
    *,
    seed: int,
    prices: Any = DEFAULT_PRICES,
) -> list[StartBlueprint]:
    """Return the result-blind twelve-recipe menu in its frozen order."""

    instance = bundle.instance
    due = tuple(_due_order(instance))
    ready = tuple(_ready_order(instance))
    sweep_cw = tuple(_sweep_order(instance, reverse=False, rotation_fraction=0.0))
    sweep_ccw = tuple(_sweep_order(instance, reverse=True, rotation_fraction=0.0))
    sweep_cw_rot = tuple(_sweep_order(instance, reverse=False, rotation_fraction=1.0 / 3.0))
    sweep_ccw_rot = tuple(_sweep_order(instance, reverse=True, rotation_fraction=1.0 / 3.0))
    nearest = tuple(_nearest_neighbour_order(instance))
    grasp_a = tuple(_grasp_order(instance, random.Random(seed + 7_919), rcl_fraction=0.20))
    grasp_b = tuple(_grasp_order(instance, random.Random(seed + 15_841), rcl_fraction=0.35))
    customer_count = len(_customers(instance))
    expected = set(_customer_ids(instance))
    orders = (due, ready, sweep_cw, sweep_ccw, sweep_cw_rot, sweep_ccw_rot, nearest, grasp_a, grasp_b)
    for order in orders:
        if len(order) != customer_count or set(order) != expected:
            raise RuntimeError("a frozen constructor did not return an exact customer permutation")

    return [
        StartBlueprint("default_regret2", "default", None, "default"),
        StartBlueprint("due_time_all_cv", "time_window", due, "all_cv"),
        StartBlueprint("ready_time_all_cv", "time_window", ready, "all_cv"),
        StartBlueprint("sweep_cw_all_cv", "sweep", sweep_cw, "all_cv"),
        StartBlueprint("sweep_ccw_all_cv", "sweep", sweep_ccw, "all_cv"),
        StartBlueprint("sweep_cw_rotated_all_cv", "sweep", sweep_cw_rot, "all_cv"),
        StartBlueprint("sweep_ccw_rotated_all_cv", "sweep", sweep_ccw_rot, "all_cv"),
        StartBlueprint("nearest_neighbour_all_cv", "nearest_neighbour", nearest, "all_cv"),
        StartBlueprint("grasp_a_all_cv", "grasp", grasp_a, "all_cv"),
        StartBlueprint("grasp_b_all_cv", "grasp", grasp_b, "all_cv"),
        StartBlueprint("due_time_remote_ev", "mechanism_aware", due, "remote_ev", 0.50),
        StartBlueprint("sweep_remote_ev", "mechanism_aware", sweep_cw_rot, "remote_ev", 0.50),
    ]


def materialize_blueprint(
    blueprint: StartBlueprint,
    bundle: SearchBundle,
    *,
    seed: int,
    prices: Any = DEFAULT_PRICES,
) -> Solution:
    """Decode one recipe and enforce the frozen fleet and feasibility shell."""

    if blueprint.order is None:
        return make_shared_initial_solution(bundle, prices=prices)

    order = list(blueprint.order)
    _assert_exact_order(order, bundle.instance)
    context = OrderDecodeContext(
        bundle.instance,
        prices=prices,
        carbon_profile=bundle.carbon_profile,
        rng=random.Random(seed),
    )
    if blueprint.type_mode == "all_cv":
        hints = {customer_id: 0.05 for customer_id in order}
    elif blueprint.type_mode == "remote_ev":
        hints = _remote_ev_hints(bundle.instance)
    else:
        raise ValueError(f"unknown type mode: {blueprint.type_mode}")
    decoded = order_to_solution(
        order,
        context,
        type_hints=hints,
        ev_threshold=float(blueprint.ev_threshold),
    )
    limits = infer_fleet_limits(bundle.bundle_dir)
    normalized = normalize_solution_vehicle_trips(
        decoded,
        bundle.instance,
        max_cv=limits.cv,
        max_ev=limits.ev,
    )
    return normalized


def select_quality_diverse_archive(
    entries: Iterable[InitialPoolEntry],
    *,
    instance: Instance,
    capacity: int,
) -> list[InitialPoolEntry]:
    """Keep the best start, then add maximally different good starts."""

    ordered = sorted(entries, key=_quality_key)
    if capacity <= 0 or not ordered:
        return []
    selected = [ordered[0]]
    remaining = list(ordered[1:])
    while remaining and len(selected) < int(capacity):
        best_index = max(
            range(len(remaining)),
            key=lambda index: (
                min(
                    edge_distance(
                        remaining[index].solution,
                        chosen.solution,
                        instance,
                    )
                    for chosen in selected
                ),
                -remaining[index].objective,
                remaining[index].full_signature,
            ),
        )
        selected.append(remaining.pop(best_index))
    return selected


def edge_distance(left: Solution, right: Solution, instance: Instance) -> float:
    """Return directed-arc Jaccard distance in [0, 1]."""

    left_edges = _route_edges(left, instance)
    right_edges = _route_edges(right, instance)
    union = left_edges | right_edges
    if not union:
        return 0.0
    return 1.0 - len(left_edges & right_edges) / len(union)


def solution_signature_hash(solution: Solution) -> str:
    payload = {
        "routes": sorted(
            (
                route.vehicle_id,
                route.vehicle_type.lower(),
                route.home_depot_id,
                tuple(route.node_sequence),
            )
            for route in solution.routes
        ),
        "charging_actions": sorted(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.energy_kwh), 9),
                round(float(action.occupancy_minutes), 9),
                round(float(action.charge_start_second), 6),
                int(action.charge_day_offset),
            )
            for action in solution.charging_actions
        ),
        "cross_site_services": sorted(
            (item.customer_id, item.served_by_depot_id)
            for item in solution.cross_site_services
        ),
    }
    return _sha_json(payload)


def route_structure_hash(solution: Solution, instance: Instance) -> str:
    node_types = {node.node_id: node.node_type.lower() for node in instance.nodes}
    payload = sorted(
        (
            route.vehicle_type.lower(),
            route.home_depot_id,
            tuple(
                node_id
                for node_id in route.node_sequence
                if node_types.get(node_id) == "c"
            ),
        )
        for route in solution.routes
    )
    return _sha_json(payload)


def result_rows(result: InitialPoolResult) -> list[dict[str, Any]]:
    archive_labels = {item.label for item in result.archive}
    return [
        {
            "label": item.label,
            "family": item.family,
            "type_mode": item.type_mode,
            "objective": item.objective,
            "raw_cost": item.raw_cost,
            "feasible": item.feasible,
            "violation_count": item.violation_count,
            "route_count": len(item.solution.routes),
            "ev_route_count": sum(
                route.vehicle_type.lower() == "ev"
                for route in item.solution.routes
            ),
            "charging_action_count": len(item.solution.charging_actions),
            "full_signature": item.full_signature,
            "route_signature": item.route_signature,
            "in_archive": item.label in archive_labels,
            "is_anchor": item.label == result.anchor.label,
            "is_best": item.label == result.best.label,
        }
        for item in result.entries
    ]


def solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [
            asdict(service) for service in solution.cross_site_services
        ],
    }


def _due_order(instance: Instance) -> list[str]:
    return [
        item.node_id
        for item in sorted(
            _customers(instance),
            key=lambda item: (
                float(item.due_time),
                float(item.ready_time),
                -float(item.demand),
                item.node_id,
            ),
        )
    ]


def _ready_order(instance: Instance) -> list[str]:
    return [
        item.node_id
        for item in sorted(
            _customers(instance),
            key=lambda item: (
                float(item.ready_time),
                float(item.due_time),
                -float(item.demand),
                item.node_id,
            ),
        )
    ]


def _sweep_order(
    instance: Instance,
    *,
    reverse: bool,
    rotation_fraction: float,
) -> list[str]:
    depots = _depots(instance)
    if depots:
        centre_x = sum(float(item.x) for item in depots) / len(depots)
        centre_y = sum(float(item.y) for item in depots) / len(depots)
    else:
        centre_x = centre_y = 0.0
    ordered = sorted(
        _customers(instance),
        key=lambda item: (
            math.atan2(float(item.y) - centre_y, float(item.x) - centre_x),
            float(item.due_time),
            item.node_id,
        ),
        reverse=bool(reverse),
    )
    if not ordered:
        return []
    offset = int(math.floor(len(ordered) * float(rotation_fraction))) % len(ordered)
    rotated = [*ordered[offset:], *ordered[:offset]]
    return [item.node_id for item in rotated]


def _nearest_neighbour_order(instance: Instance) -> list[str]:
    groups = _nearest_depot_groups(instance)
    ordered: list[str] = []
    for depot in _depots(instance):
        remaining = {item.node_id for item in groups.get(depot.node_id, [])}
        current = depot.node_id
        while remaining:
            chosen = min(
                remaining,
                key=lambda customer_id: (
                    float(instance.distance(current, customer_id)),
                    float(_node_lookup(instance)[customer_id].due_time),
                    customer_id,
                ),
            )
            ordered.append(chosen)
            remaining.remove(chosen)
            current = chosen
    return ordered


def _grasp_order(
    instance: Instance,
    rng: random.Random,
    *,
    rcl_fraction: float,
) -> list[str]:
    """Reimplement a small GRASP-style restricted-candidate constructor."""

    groups = _nearest_depot_groups(instance)
    lookup = _node_lookup(instance)
    ordered: list[str] = []
    for depot in _depots(instance):
        remaining = {item.node_id for item in groups.get(depot.node_id, [])}
        current = depot.node_id
        while remaining:
            ranked = sorted(
                remaining,
                key=lambda customer_id: (
                    float(instance.distance(current, customer_id)),
                    float(lookup[customer_id].due_time),
                    customer_id,
                ),
            )
            width = max(1, min(len(ranked), int(math.ceil(len(ranked) * float(rcl_fraction)))))
            chosen = ranked[rng.randrange(width)]
            ordered.append(chosen)
            remaining.remove(chosen)
            current = chosen
    return ordered


def _remote_ev_hints(instance: Instance) -> dict[str, float]:
    depots = _depots(instance)
    rows = [
        (
            min(float(instance.distance(depot.node_id, customer.node_id)) for depot in depots),
            customer.node_id,
        )
        for customer in _customers(instance)
    ]
    rows.sort()
    split = len(rows) // 2
    remote = {customer_id for _, customer_id in rows[split:]}
    return {
        customer_id: 0.95 if customer_id in remote else 0.05
        for _, customer_id in rows
    }


def _nearest_depot_groups(instance: Instance) -> dict[str, list[Node]]:
    depots = _depots(instance)
    groups = {depot.node_id: [] for depot in depots}
    for customer in _customers(instance):
        depot = min(
            depots,
            key=lambda item: (
                float(instance.distance(item.node_id, customer.node_id)),
                item.node_id,
            ),
        )
        groups[depot.node_id].append(customer)
    return groups


def _nearest_depot_owners(instance: Instance) -> dict[str, str]:
    return {
        customer.node_id: min(
            _depots(instance),
            key=lambda depot: (
                float(instance.distance(depot.node_id, customer.node_id)),
                depot.node_id,
            ),
        ).node_id
        for customer in _customers(instance)
    }


def _assert_exact_order(order: list[str], instance: Instance) -> None:
    expected = _customer_ids(instance)
    if len(order) != len(expected):
        raise ValueError(f"order length {len(order)} != customer count {len(expected)}")
    if set(order) != set(expected):
        missing = sorted(set(expected) - set(order))
        extra = sorted(set(order) - set(expected))
        raise ValueError(f"order is not an exact customer permutation: missing={missing}, extra={extra}")


def _assert_exact_customer_cover(solution: Solution, instance: Instance) -> None:
    customer_set = set(_customer_ids(instance))
    visits = [
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_id in customer_set
    ]
    if len(visits) != len(customer_set) or set(visits) != customer_set:
        missing = sorted(customer_set - set(visits))
        duplicates = sorted(
            customer_id
            for customer_id in customer_set
            if visits.count(customer_id) != 1
        )
        raise ValueError(f"invalid customer cover: missing={missing}, nonunit={duplicates}")


def _route_edges(solution: Solution, instance: Instance) -> set[tuple[str, str, str]]:
    node_set = set(instance.node_index)
    return {
        (route.home_depot_id, left, right)
        for route in solution.routes
        for left, right in zip(route.node_sequence, route.node_sequence[1:])
        if left in node_set and right in node_set
    }


def _quality_key(item: InitialPoolEntry) -> tuple[float, str]:
    return float(item.objective), item.full_signature


def _customers(instance: Instance) -> list[Node]:
    return [item for item in instance.nodes if item.node_type.lower() == "c"]


def _customer_ids(instance: Instance) -> list[str]:
    return [item.node_id for item in _customers(instance)]


def _depots(instance: Instance) -> list[Node]:
    depots = sorted(
        (item for item in instance.nodes if item.node_type.lower() == "d"),
        key=lambda item: item.node_id,
    )
    if not depots:
        raise ValueError("instance has no depot")
    return depots


def _node_lookup(instance: Instance) -> dict[str, Node]:
    return {item.node_id: item for item in instance.nodes}


def _sha_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
