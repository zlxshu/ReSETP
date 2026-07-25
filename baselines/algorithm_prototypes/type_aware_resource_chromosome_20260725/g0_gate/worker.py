"""Import-stable worker for the frozen TARC G0 tasks."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
SOLVER_SRC = REPO_ROOT / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from setp_solver.algorithms.resetp_alns.support.charging import (  # noqa: E402
    repair_route_charging,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)

from baselines.algorithm_prototypes.type_aware_resource_chromosome_20260725.t0_engineering_gate.run_t0 import (  # noqa: E402
    TypedSequence,
    typed_split,
)


V7_ROOT = (
    REPO_ROOT
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724/"
    "full_gate"
)
V7_TASKS = V7_ROOT / "tasks"
PARENT_SEEDS = (3, 4)
ARM = "HGS-M"
NUM_CANDIDATES = 32
SAFETY_SECONDS = 90.0
TOL = 1e-9


def _task_dir(instance_id: str, seed: int) -> Path:
    return V7_TASKS / f"D6-E2-STAGED__{instance_id}__seed{seed}"


def _load_witness(instance_id: str, seed: int) -> dict[str, Any]:
    path = _task_dir(instance_id, seed) / "solution_witnesses.json"
    return json.loads(path.read_text(encoding="utf-8"))[ARM]


def _load_parent_costs(instance_id: str) -> dict[int, float]:
    with (V7_ROOT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["instance_id"] == instance_id
            and int(row["seed"]) in PARENT_SEEDS
        ]
    if len(rows) != 2:
        raise RuntimeError(f"{instance_id}: expected two frozen parent rows")
    return {int(row["seed"]): float(row["HGS-M_cost"]) for row in rows}


def _solution_from_witness(witness: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(route["vehicle_id"]),
                vehicle_type=str(route["vehicle_type"]),
                home_depot_id=str(route["home_depot_id"]),
                node_sequence=[str(node) for node in route["node_sequence"]],
            )
            for route in witness["routes"]
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(action["vehicle_id"]),
                station_id=str(action["station_id"]),
                charge_start_second=float(action["charge_start_second"]),
                occupancy_minutes=float(action["occupancy_minutes"]),
                energy_kwh=float(action["energy_kwh"]),
                charge_day_offset=int(action.get("charge_day_offset", 0)),
                start_energy_kwh=float(action.get("start_energy_kwh", 0.0)),
                end_energy_kwh=float(
                    action.get("end_energy_kwh", action["energy_kwh"])
                ),
                charging_curve_id=str(
                    action.get("charging_curve_id", "NL90_mild")
                ),
            )
            for action in witness.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(item["customer_id"]),
                served_by_depot_id=str(item["served_by_depot_id"]),
            )
            for item in witness.get("cross_site_services", [])
        ],
    )


def _parent_order_and_labels(
    witness: dict[str, Any],
) -> tuple[tuple[str, ...], dict[str, tuple[str, str]]]:
    order: list[str] = []
    labels: dict[str, tuple[str, str]] = {}
    for route in witness["routes"]:
        depot = str(route["home_depot_id"])
        powertrain = str(route["vehicle_type"]).lower()
        for customer in route["node_sequence"][1:-1]:
            customer = str(customer)
            if customer in labels:
                raise RuntimeError(f"duplicate parent customer {customer}")
            order.append(customer)
            labels[customer] = (depot, powertrain)
    return tuple(order), labels


def _candidate_masks(instance_id: str, n: int) -> tuple[tuple[int, int], ...]:
    pairs = [
        (begin, end)
        for begin in range(n - 1)
        for end in range(begin + 1, n)
    ]
    ranked = sorted(
        pairs,
        key=lambda pair: hashlib.sha256(
            f"E2-TARC-001|{instance_id}|{pair[0]}|{pair[1]}".encode()
        ).hexdigest(),
    )
    return tuple(ranked[:NUM_CANDIDATES])


def _order_crossover(
    first: tuple[str, ...],
    second: tuple[str, ...],
    begin: int,
    end: int,
) -> tuple[tuple[str, ...], set[str]]:
    if set(first) != set(second) or len(first) != len(second):
        raise RuntimeError("parent customer sets differ")
    segment = first[begin:end]
    segment_set = set(segment)
    fillers = [customer for customer in second if customer not in segment_set]
    child = [*fillers[:begin], *segment, *fillers[begin:]]
    if len(child) != len(first) or len(set(child)) != len(child):
        raise RuntimeError("order crossover produced invalid child")
    return tuple(child), segment_set


def _typed_sequences(
    order: tuple[str, ...],
    labels: dict[str, tuple[str, str]],
) -> tuple[TypedSequence, ...]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for customer in order:
        grouped.setdefault(labels[customer], []).append(customer)
    return tuple(
        TypedSequence(
            depot_id=depot,
            powertrain=powertrain,
            customers=tuple(customers),
            original_route_lengths=(),
        )
        for (depot, powertrain), customers in sorted(grouped.items())
    )


def _decode_routes(
    *,
    bundle: Any,
    order: tuple[str, ...],
    labels: dict[str, tuple[str, str]],
) -> list[Route]:
    routes: list[Route] = []
    for encoded in _typed_sequences(order, labels):
        split = typed_split(bundle=bundle, encoded=encoded)
        begin = 0
        for end in split.cuts:
            customers = encoded.customers[begin:end]
            routes.append(
                Route(
                    vehicle_id=f"TARC-{len(routes) + 1:04d}",
                    vehicle_type=encoded.powertrain,
                    home_depot_id=encoded.depot_id,
                    node_sequence=[
                        encoded.depot_id,
                        *customers,
                        encoded.depot_id,
                    ],
                )
            )
            begin = end
    return routes


def _complete_forced_types(
    routes: list[Route],
    bundle: Any,
) -> tuple[Solution, int]:
    completed_routes: list[Route] = []
    actions: list[ChargingAction] = []
    repair_failures = 0
    for route in routes:
        if route.vehicle_type.lower() != "ev":
            completed_routes.append(route)
            continue
        try:
            repaired, route_actions = repair_route_charging(
                route,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                strategy="integrated",
                carbon_weight=1.0,
                depot_charge_window_mode="same_day_predeparture",
            )
            completed_routes.append(repaired)
            actions.extend(route_actions)
        except (TypeError, ValueError):
            # Preserve the forced EV type and let the exact checker expose the
            # infeasibility. This still consumes one full candidate evaluation.
            completed_routes.append(route)
            repair_failures += 1
    return (
        annotate_cross_site_services(
            Solution(routes=completed_routes, charging_actions=actions),
            bundle.customer_home_depot,
        ),
        repair_failures,
    )


def _label_signature(
    labels: dict[str, tuple[str, str]],
) -> str:
    payload = "|".join(
        f"{customer}:{depot}:{powertrain}"
        for customer, (depot, powertrain) in sorted(labels.items())
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    instance_id = str(task["instance_id"])
    arm = str(task["arm"])
    if arm not in {"ORDER_ONLY", "ORDER_PLUS_TYPE"}:
        raise ValueError(f"unknown G0 arm {arm}")
    bundle = load_china81_bundle(REPO_ROOT, instance_id)
    parent_costs = _load_parent_costs(instance_id)
    stronger_seed = min(parent_costs, key=lambda seed: (parent_costs[seed], seed))
    weaker_seed = next(seed for seed in PARENT_SEEDS if seed != stronger_seed)
    stronger_witness = _load_witness(instance_id, stronger_seed)
    weaker_witness = _load_witness(instance_id, weaker_seed)

    stronger_solution = _solution_from_witness(stronger_witness)
    parent_exact, _, parent_violations = exact_china81_score(
        stronger_solution,
        bundle,
    )
    if parent_violations:
        raise RuntimeError(f"{instance_id}: stronger parent is infeasible")
    if not math.isclose(
        parent_exact,
        parent_costs[stronger_seed],
        rel_tol=1e-9,
        abs_tol=1e-7,
    ):
        raise RuntimeError(f"{instance_id}: stronger parent cost mismatch")

    first_order, first_labels = _parent_order_and_labels(stronger_witness)
    second_order, second_labels = _parent_order_and_labels(weaker_witness)
    masks = _candidate_masks(instance_id, len(first_order))
    candidate_rows: list[dict[str, Any]] = []
    for candidate_index, (begin, end) in enumerate(masks):
        if time.perf_counter() - started > SAFETY_SECONDS:
            raise TimeoutError(
                f"{instance_id}/{arm}: exceeded {SAFETY_SECONDS}s safety limit"
            )
        child_order, first_segment = _order_crossover(
            first_order,
            second_order,
            begin,
            end,
        )
        if arm == "ORDER_ONLY":
            child_labels = dict(first_labels)
        else:
            child_labels = {
                customer: (
                    first_labels[customer]
                    if customer in first_segment
                    else second_labels[customer]
                )
                for customer in child_order
            }
        decoded_routes = _decode_routes(
            bundle=bundle,
            order=child_order,
            labels=child_labels,
        )
        candidate, repair_failures = _complete_forced_types(
            decoded_routes,
            bundle,
        )
        objective, _, violations = exact_china81_score(candidate, bundle)
        independent_violations = check_solution(
            candidate,
            bundle.instance,
            bundle.prices,
        )
        independent_objective = float(
            evaluate(
                candidate,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
            )["total_cost"]
        )
        if not math.isclose(
            objective,
            independent_objective,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise RuntimeError("exact and independent objective mismatch")
        if [str(item) for item in violations] != [
            str(item) for item in independent_violations
        ]:
            raise RuntimeError("exact and independent violation mismatch")
        feasible = not violations
        candidate_rows.append(
            {
                "instance_id": instance_id,
                "arm": arm,
                "candidate_index": candidate_index,
                "mask_begin": begin,
                "mask_end": end,
                "stronger_parent_seed": stronger_seed,
                "weaker_parent_seed": weaker_seed,
                "parent_objective": parent_exact,
                "objective": objective,
                "feasible": feasible,
                "violation_count": len(violations),
                "repair_failures": repair_failures,
                "route_count": len(candidate.routes),
                "ev_route_count": sum(
                    route.vehicle_type.lower() == "ev"
                    for route in candidate.routes
                ),
                "charging_action_count": len(candidate.charging_actions),
                "label_signature": _label_signature(child_labels),
                "labels_differ_from_stronger_parent": (
                    child_labels != first_labels
                ),
                "strictly_improves_parent": (
                    feasible and objective < parent_exact - TOL
                ),
                "worker_pid": os.getpid(),
                "worker_module": __name__,
                "worker_file": str(Path(__file__).resolve()),
            }
        )

    feasible_rows = [row for row in candidate_rows if row["feasible"]]
    elapsed = time.perf_counter() - started
    if elapsed > SAFETY_SECONDS:
        raise TimeoutError(
            f"{instance_id}/{arm}: completed in "
            f"{elapsed:.6f}s>{SAFETY_SECONDS}s"
        )
    best = min(
        feasible_rows,
        key=lambda row: (float(row["objective"]), int(row["candidate_index"])),
        default=None,
    )
    return {
        "instance_id": instance_id,
        "arm": arm,
        "status": "PASS_TASK_COMPLETE",
        "wall_seconds": elapsed,
        "candidate_rows": candidate_rows,
        "candidate_attempts": len(candidate_rows),
        "complete_evaluations": len(candidate_rows),
        "feasible_candidates": len(feasible_rows),
        "best_objective": None if best is None else best["objective"],
        "best_candidate_index": (
            None if best is None else best["candidate_index"]
        ),
        "parent_objective": parent_exact,
        "strictly_improves_parent": bool(
            best is not None and best["strictly_improves_parent"]
        ),
        "worker_pid": os.getpid(),
        "worker_module": __name__,
        "worker_file": str(Path(__file__).resolve()),
    }
