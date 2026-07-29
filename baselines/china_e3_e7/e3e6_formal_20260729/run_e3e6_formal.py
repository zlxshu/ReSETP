#!/usr/bin/env python3
"""Formal E3 mismatch and E6 participation-guarantee campaign.

This runner reuses the already audited current-source D3 and MV-HGS-SP
machinery, but owns a separate output directory and contract.  It freezes
input-only mismatch maps before pilot results, runs a result-blind starvation
pilot, then saves and independently recomputes the E3 LOCK/FREE solutions and
the E6 I/U/F states.  F is a filtered nested outcome of U, not a third search.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import os
import platform
import resource
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import Any

REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BASE_RUNNER = (
    REPO
    / "baselines/china_e3_e7/e3_mismatch_20260729/run_e3_mismatch.py"
)
_spec = importlib.util.spec_from_file_location("_e3_mismatch_base", BASE_RUNNER)
if _spec is None or _spec.loader is None:
    raise RuntimeError("cannot load audited E3 base runner")
e3 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = e3
_spec.loader.exec_module(e3)

from setp_solver.check import FairnessContext, check_solution
from setp_solver.china81_completion import (
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.cost import evaluate
from setp_solver.profit import calculate_depot_profits
from setp_solver.solution import Route, Solution, physical_vehicle_id

TASK_ID = "E3E6-MISMATCH-FAIRNESS-01"
MAIN_INSTANCE = "cn-prd-150c-01-V2-LOCATIONS"
INTENSITIES = (0, 25, 50)
MAIN_SEEDS = tuple(range(1, 11))
STABILITY_SEEDS = (1, 2, 3)
PILOT_SEEDS = (1, 2, 3)
ARMS = {"LOCK": True, "FREE": False}
MAX_WORKERS = 2
FAIRNESS_TOL = 1.0e-6
DISPLAY_DIGITS = 2

e3.OUT = OUT
e3.TASK_ID = TASK_ID
e3.MAIN_INSTANCE = MAIN_INSTANCE
e3.MAIN_INTENSITIES = INTENSITIES
e3.STABILITY_INTENSITIES = INTENSITIES
e3.MAIN_SEEDS = MAIN_SEEDS
e3.STABILITY_SEEDS = STABILITY_SEEDS
e3.PILOT_SEEDS = PILOT_SEEDS
e3.MAX_WORKERS = MAX_WORKERS
e3.SOURCE_FILES = (
    Path(__file__).resolve(),
    BASE_RUNNER,
    e3.PYVRP_ADAPTER,
    e3.EPOCHAL_HGS,
    e3.ROUTE_POOL_SP,
    e3.CHINA81,
    e3.CHINA81_COMPLETION,
    REPO / "solver/src/setp_solver/profit.py",
    *e3.PROTECTED,
)


def log_event(event: str, **payload: Any) -> None:
    row = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "event": event,
        **payload,
    }
    with (OUT / "run.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _depot_ids(bundle: Any) -> list[str]:
    return sorted(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    )


def _directed_depot_ranking(bundle: Any, customer_id: str) -> list[str]:
    return sorted(
        _depot_ids(bundle),
        key=lambda depot_id: (
            float(bundle.instance.distance(depot_id, customer_id)),
            depot_id,
        ),
    )


def _fleet_probe(bundle: Any, mapping: dict[str, str]) -> dict[str, Any]:
    candidate = e3.with_responsibility(bundle, mapping)
    counts: dict[str, dict[str, int]] = {}
    try:
        for depot_id in sorted(set(mapping.values())):
            routes = e3._pack_depot(candidate, depot_id)
            caps = candidate.fleet_caps_by_depot[depot_id]
            total_cap = int(caps["num_cv"]) + int(caps["num_ev"])
            counts[depot_id] = {
                "packed_routes": len(routes),
                "d2a_total_cap": total_cap,
            }
            if len(routes) > total_cap:
                return {
                    "feasible": False,
                    "reason": "D2A_TOTAL_FLEET_CAP_EXCEEDED",
                    "failing_depot": depot_id,
                    "depot_counts": counts,
                }
    except Exception as exc:  # input construction is fail-closed
        return {
            "feasible": False,
            "reason": f"PACKING_ERROR:{type(exc).__name__}:{exc}",
            "depot_counts": counts,
        }
    return {"feasible": True, "reason": "PASS", "depot_counts": counts}


def _legacy_lexicographic_global_assignment(
    bundle: Any,
    original: dict[str, str],
    selected: list[dict[str, Any]],
) -> tuple[dict[str, str] | None, list[int] | None, dict[str, Any]]:
    """Find the lexicographically first complete D2-A-feasible rank vector.

    A small binary feasibility model supplies full suffix completions.  Every
    proposed completion is checked by the frozen D2-A packer.  When depot D
    fails, an exact no-good excludes only that final D-membership pattern;
    membership patterns for other depots remain untouched.  Re-solving until
    feasible or proven infeasible gives a sound existence oracle for each
    fixed customer/rank prefix without using non-monotone prefix packing.
    """

    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp

    options = [
        [
            (absolute_rank, destination)
            for absolute_rank, destination in enumerate(
                item["ranking"], start=1
            )
            if absolute_rank != 1 and destination != item["owner"]
        ]
        for item in selected
    ]
    if not selected:
        probe = _fleet_probe(bundle, original)
        return (
            (dict(original), [], {
                "algorithm": "DIRECT_COMPLETE_MAPPING_CHECK",
                "global_feasible_completion_found": True,
                "complete_mapping_checker_calls": 1,
                "milp_solver_calls": 0,
                "depot_membership_nogood_cuts": 0,
            })
            if probe["feasible"]
            else (None, None, {
                "algorithm": "DIRECT_COMPLETE_MAPPING_CHECK",
                "global_feasible_completion_found": False,
                "complete_mapping_checker_calls": 1,
                "milp_solver_calls": 0,
                "depot_membership_nogood_cuts": 0,
                "failure": probe,
            })
        )
    variable_index: dict[tuple[int, int], int] = {}
    reverse_index: list[tuple[int, int]] = []
    for customer_index, item_options in enumerate(options):
        for option_index in range(len(item_options)):
            variable_index[(customer_index, option_index)] = len(reverse_index)
            reverse_index.append((customer_index, option_index))
    variable_count = len(reverse_index)
    membership_affectors = {
        depot_id: [
            index
            for index, item_options in enumerate(options)
            if 0 < sum(destination == depot_id for _, destination in item_options)
            < len(item_options)
        ]
        for depot_id in _depot_ids(bundle)
    }
    nogoods: list[tuple[str, tuple[int, ...]]] = []
    nogood_set: set[tuple[str, tuple[int, ...]]] = set()
    checker_calls = 0
    heuristic_checker_calls = 0
    solver_calls = 0
    infeasible_prefix_attempts = 0
    checker_failures_by_depot: dict[str, int] = {}

    def add_row(
        rows: list[np.ndarray],
        lower: list[float],
        upper: list[float],
        coefficients: dict[int, float],
        lb: float,
        ub: float,
    ) -> None:
        row = np.zeros(variable_count, dtype=float)
        for index, value in coefficients.items():
            row[index] = value
        rows.append(row)
        lower.append(lb)
        upper.append(ub)

    def checked_mapping(
        chosen_options: list[int],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        mapping = dict(original)
        for customer_index, option_index in enumerate(chosen_options):
            mapping[selected[customer_index]["customer_id"]] = options[
                customer_index
            ][option_index][1]
        return mapping, _fleet_probe(bundle, mapping)

    def heuristic_completion(
        prefix: list[int],
        preferred: list[int] | None,
    ) -> tuple[dict[str, str] | None, list[int] | None]:
        nonlocal checker_calls, heuristic_checker_calls
        suffix_start = len(prefix)
        candidate_rows: list[list[int]] = []
        if preferred is not None and preferred[:suffix_start] == prefix:
            candidate_rows.append(list(preferred))
        all_second = [*prefix, *([0] * (len(options) - suffix_start))]
        candidate_rows.append(all_second)
        if preferred is not None:
            repaired = [*prefix, *preferred[suffix_start:]]
            candidate_rows.append(repaired)
            for index in range(suffix_start, len(options)):
                for option_index in range(len(options[index])):
                    if option_index == repaired[index]:
                        continue
                    changed = list(repaired)
                    changed[index] = option_index
                    candidate_rows.append(changed)
        seed_material = (
            f"{TASK_ID}|{bundle.instance_id}|heuristic-prefix|"
            + ",".join(str(item) for item in prefix)
        )
        rng = random.Random(
            int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
        )
        for _ in range(512):
            candidate_rows.append(
                [
                    *prefix,
                    *[
                        rng.randrange(len(options[index]))
                        for index in range(suffix_start, len(options))
                    ],
                ]
            )
        seen: set[tuple[int, ...]] = set()
        for chosen in candidate_rows:
            key = tuple(chosen)
            if key in seen:
                continue
            seen.add(key)
            mapping, probe = checked_mapping(chosen)
            checker_calls += 1
            heuristic_checker_calls += 1
            if probe["feasible"]:
                return mapping, chosen
        return None, None

    def completion_for_prefix(
        prefix: list[int],
        preferred: list[int] | None,
    ) -> tuple[dict[str, str] | None, list[int] | None]:
        nonlocal checker_calls, solver_calls, infeasible_prefix_attempts
        while True:
            constraint_rows: list[np.ndarray] = []
            lower: list[float] = []
            upper: list[float] = []
            for customer_index, item_options in enumerate(options):
                add_row(
                    constraint_rows,
                    lower,
                    upper,
                    {
                        variable_index[(customer_index, option_index)]: 1.0
                        for option_index in range(len(item_options))
                    },
                    1.0,
                    1.0,
                )
            for customer_index, option_index in enumerate(prefix):
                add_row(
                    constraint_rows,
                    lower,
                    upper,
                    {variable_index[(customer_index, option_index)]: 1.0},
                    1.0,
                    1.0,
                )
            for depot_id, signature in nogoods:
                affectors = membership_affectors[depot_id]
                coefficients: dict[int, float] = {}
                members = 0
                for bit, customer_index in zip(signature, affectors):
                    if bit:
                        members += 1
                    sign = -1.0 if bit else 1.0
                    for option_index, (_, destination) in enumerate(
                        options[customer_index]
                    ):
                        if destination == depot_id:
                            variable = variable_index[
                                (customer_index, option_index)
                            ]
                            coefficients[variable] = (
                                coefficients.get(variable, 0.0) + sign
                            )
                add_row(
                    constraint_rows,
                    lower,
                    upper,
                    coefficients,
                    1.0 - members,
                    math.inf,
                )
            matrix = np.vstack(constraint_rows)
            solver_calls += 1
            objective = np.ones(variable_count, dtype=float)
            if preferred is not None:
                for customer_index, option_index in enumerate(preferred):
                    objective[
                        variable_index[(customer_index, option_index)]
                    ] = 0.0
            result = milp(
                c=objective,
                integrality=np.ones(variable_count, dtype=int),
                bounds=Bounds(
                    np.zeros(variable_count, dtype=float),
                    np.ones(variable_count, dtype=float),
                ),
                constraints=LinearConstraint(
                    matrix,
                    np.asarray(lower, dtype=float),
                    np.asarray(upper, dtype=float),
                ),
                options={"presolve": True},
            )
            if int(result.status) == 2:
                infeasible_prefix_attempts += 1
                return None, None
            if int(result.status) != 0 or result.x is None:
                raise RuntimeError(
                    "HALT_INPUT_COMPLETION_MILP_STATUS:"
                    f"{result.status}:{result.message}"
                )
            chosen_options: list[int] = []
            for customer_index, item_options in enumerate(options):
                values = [
                    float(result.x[variable_index[(customer_index, option_index)]])
                    for option_index in range(len(item_options))
                ]
                option_index = max(range(len(values)), key=lambda item: values[item])
                if values[option_index] < 0.5:
                    raise RuntimeError("HALT_INPUT_COMPLETION_MILP_NONINTEGRAL")
                chosen_options.append(option_index)
            mapping, probe = checked_mapping(chosen_options)
            checker_calls += 1
            if probe["feasible"]:
                return mapping, chosen_options
            failing_depot = probe.get("failing_depot")
            if failing_depot is None:
                raise RuntimeError(
                    f"HALT_UNATTRIBUTED_INPUT_PACKING_FAILURE:{probe}"
                )
            checker_failures_by_depot[failing_depot] = (
                checker_failures_by_depot.get(failing_depot, 0) + 1
            )
            affectors = membership_affectors[failing_depot]
            signature = tuple(
                int(mapping[selected[index]["customer_id"]] == failing_depot)
                for index in affectors
            )
            nogood = (failing_depot, signature)
            if nogood in nogood_set:
                raise RuntimeError("HALT_DUPLICATE_DEPOT_MEMBERSHIP_NOGOOD")
            if not affectors:
                infeasible_prefix_attempts += 1
                return None, None
            nogood_set.add(nogood)
            nogoods.append(nogood)

    prefix: list[int] = []
    final_mapping, incumbent_options = heuristic_completion([], None)
    for customer_index, item_options in enumerate(options):
        accepted = False
        for option_index in range(len(item_options)):
            candidate_prefix = [*prefix, option_index]
            witness, witness_options = heuristic_completion(
                candidate_prefix, incumbent_options
            )
            if witness is None or witness_options is None:
                witness, witness_options = completion_for_prefix(
                    candidate_prefix, incumbent_options
                )
            if witness is None or witness_options is None:
                continue
            prefix.append(option_index)
            final_mapping = witness
            incumbent_options = witness_options
            accepted = True
            break
        if not accepted:
            final_mapping = None
            break
    rank_vector = (
        None
        if final_mapping is None
        else [
            options[index][option_index][0]
            for index, option_index in enumerate(prefix)
        ]
    )
    audit = {
        "algorithm": "EXACT_LEXICOGRAPHIC_COMPLETE_MAPPING_FEASIBILITY_WITH_LAZY_DEPOT_MEMBERSHIP_NOGOODS",
        "prefix_feasibility_pruning": False,
        "nogood_rule": "exclude only an exact final customer-membership pattern for the independently failing depot",
        "fixed_customer_order": "result_blind SHA-256 order",
        "destination_order": "directed-distance absolute rank, second then third/fourth, original owner skipped",
        "complete_mapping_checker_calls": checker_calls,
        "heuristic_checker_calls": heuristic_checker_calls,
        "milp_solver_calls": solver_calls,
        "depot_membership_nogood_cuts": len(nogoods),
        "infeasible_prefix_attempts": infeasible_prefix_attempts,
        "checker_failures_by_depot": checker_failures_by_depot,
        "global_feasible_completion_found": final_mapping is not None,
    }
    if final_mapping is None or rank_vector is None:
        return None, None, audit
    return final_mapping, rank_vector, audit


def _legacy_route_partition_global_assignment(
    bundle: Any,
    original: dict[str, str],
    selected: list[dict[str, Any]],
) -> tuple[dict[str, str] | None, list[int] | None, dict[str, Any]]:
    """Exact destination and legal common-route existence oracle.

    The model assigns every customer to one allowed depot and one of that
    depot's frozen D2-A route slots.  Candidate routes retain the frozen
    due/ready/id order and are checked by the existing route-feasibility
    function.  Each rejected route adds a sound subset cut on every symmetric
    slot.  Prefix destination choices are then fixed in approved customer and
    distance order to obtain the lexicographically first feasible mapping.
    """

    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    selected_index = {
        item["customer_id"]: index for index, item in enumerate(selected)
    }
    selected_set = set(selected_index)
    options = [
        [
            (absolute_rank, destination)
            for absolute_rank, destination in enumerate(
                item["ranking"], start=1
            )
            if absolute_rank != 1 and destination != item["owner"]
        ]
        for item in selected
    ]
    depots = _depot_ids(bundle)
    caps = {
        depot_id: int(bundle.fleet_caps_by_depot[depot_id]["num_cv"])
        + int(bundle.fleet_caps_by_depot[depot_id]["num_ev"])
        for depot_id in depots
    }
    customer_nodes = sorted(
        (
            node
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        ),
        key=lambda node: (
            float(node.due_time),
            float(node.ready_time),
            node.node_id,
        ),
    )
    customer_ids = [node.node_id for node in customer_nodes]
    node_lookup = {node.node_id: node for node in customer_nodes}
    allowed_depots = {
        customer_id: (
            [destination for _, destination in options[selected_index[customer_id]]]
            if customer_id in selected_set
            else [original[customer_id]]
        )
        for customer_id in customer_ids
    }
    variables: list[tuple[str, str, int]] = []
    variable_index: dict[tuple[str, str, int], int] = {}
    for customer_id in customer_ids:
        for depot_id in allowed_depots[customer_id]:
            for route_index in range(caps[depot_id]):
                key = (customer_id, depot_id, route_index)
                variable_index[key] = len(variables)
                variables.append(key)
    variable_count = len(variables)
    route_feasible = e3._pack_depot.__globals__["_route_feasible"]
    route_cuts: set[tuple[str, tuple[str, ...]]] = set()
    pairwise_route_checks = 0
    for depot_id in depots:
        possible_customers = [
            customer_id
            for customer_id in customer_ids
            if depot_id in allowed_depots[customer_id]
        ]
        for left_index in range(len(possible_customers)):
            for right_index in range(left_index + 1, len(possible_customers)):
                pairwise_route_checks += 1
                pair = (
                    possible_customers[left_index],
                    possible_customers[right_index],
                )
                if not route_feasible(bundle, depot_id, list(pair)):
                    route_cuts.add((depot_id, pair))
    solver_calls = 0
    route_checker_calls = 0
    infeasible_prefix_attempts = 0

    def packer_witness(
        chosen_options: list[int],
    ) -> tuple[dict[str, str], dict[str, list[list[str]]]] | None:
        mapping = dict(original)
        for index, option_index in enumerate(chosen_options):
            mapping[selected[index]["customer_id"]] = options[index][
                option_index
            ][1]
        candidate = e3.with_responsibility(bundle, mapping)
        route_groups: dict[str, list[list[str]]] = {}
        for depot_id in depots:
            groups = e3._pack_depot(candidate, depot_id)
            if len(groups) > caps[depot_id]:
                return None
            route_groups[depot_id] = groups
        return mapping, route_groups

    def solve_prefix(
        prefix: list[int],
        preferred: list[int] | None,
    ) -> tuple[
        dict[str, str] | None,
        list[int] | None,
        dict[str, list[list[str]]] | None,
    ]:
        nonlocal solver_calls, route_checker_calls, infeasible_prefix_attempts
        quick_choices = (
            list(preferred)
            if preferred is not None and preferred[: len(prefix)] == prefix
            else [*prefix, *([0] * (len(selected) - len(prefix)))]
        )
        quick = packer_witness(quick_choices)
        if quick is not None:
            return quick[0], quick_choices, quick[1]
        while True:
            coefficient_rows: list[int] = []
            coefficient_columns: list[int] = []
            coefficient_values: list[float] = []
            lower: list[float] = []
            upper: list[float] = []

            def add_constraint(
                coefficients: dict[int, float],
                lb: float,
                ub: float,
            ) -> None:
                row_index = len(lower)
                for column, value in coefficients.items():
                    coefficient_rows.append(row_index)
                    coefficient_columns.append(column)
                    coefficient_values.append(value)
                lower.append(lb)
                upper.append(ub)

            for customer_id in customer_ids:
                add_constraint(
                    {
                        variable_index[(customer_id, depot_id, route_index)]: 1.0
                        for depot_id in allowed_depots[customer_id]
                        for route_index in range(caps[depot_id])
                    },
                    1.0,
                    1.0,
                )
            for selected_position, option_index in enumerate(prefix):
                customer_id = selected[selected_position]["customer_id"]
                destination = options[selected_position][option_index][1]
                add_constraint(
                    {
                        variable_index[(customer_id, destination, route_index)]: 1.0
                        for route_index in range(caps[destination])
                    },
                    1.0,
                    1.0,
                )
            capacity = bundle.instance.payload_capacity_kg(
                "cv", fallback=float(bundle.prices.Q_capacity)
            )
            for depot_id in depots:
                for route_index in range(caps[depot_id]):
                    add_constraint(
                        {
                            variable_index[(customer_id, depot_id, route_index)]: float(
                                node_lookup[customer_id].demand
                            )
                            for customer_id in customer_ids
                            if depot_id in allowed_depots[customer_id]
                        },
                        -math.inf,
                        float(capacity),
                    )
                for route_index in range(caps[depot_id] - 1):
                    coefficients: dict[int, float] = {}
                    for customer_id in customer_ids:
                        if depot_id not in allowed_depots[customer_id]:
                            continue
                        demand = float(node_lookup[customer_id].demand)
                        coefficients[
                            variable_index[(customer_id, depot_id, route_index)]
                        ] = demand
                        coefficients[
                            variable_index[(customer_id, depot_id, route_index + 1)]
                        ] = -demand
                    add_constraint(coefficients, 0.0, math.inf)
            for depot_id, group in sorted(route_cuts):
                for route_index in range(caps[depot_id]):
                    add_constraint(
                        {
                            variable_index[(customer_id, depot_id, route_index)]: 1.0
                            for customer_id in group
                        },
                        -math.inf,
                        float(len(group) - 1),
                    )
            matrix = coo_matrix(
                (
                    np.asarray(coefficient_values, dtype=float),
                    (
                        np.asarray(coefficient_rows, dtype=int),
                        np.asarray(coefficient_columns, dtype=int),
                    ),
                ),
                shape=(len(lower), variable_count),
            ).tocsr()
            objective = np.zeros(variable_count, dtype=float)
            for variable, (customer_id, depot_id, route_index) in enumerate(
                variables
            ):
                rank_penalty = 0.0
                if customer_id in selected_set:
                    position = selected_index[customer_id]
                    rank_penalty = float(
                        next(
                            rank
                            for rank, destination in options[position]
                            if destination == depot_id
                        )
                    )
                    if preferred is not None and options[position][preferred[position]][1] == depot_id:
                        rank_penalty -= 1.0
                objective[variable] = (
                    1000.0 * rank_penalty
                    + float(route_index)
                    + int(hashlib.sha256(customer_id.encode("utf-8")).hexdigest()[:6], 16)
                    * 1.0e-9
                )
            solver_calls += 1
            result = milp(
                c=objective,
                integrality=np.ones(variable_count, dtype=int),
                bounds=Bounds(
                    np.zeros(variable_count, dtype=float),
                    np.ones(variable_count, dtype=float),
                ),
                constraints=LinearConstraint(
                    matrix,
                    np.asarray(lower, dtype=float),
                    np.asarray(upper, dtype=float),
                ),
                options={"presolve": True},
            )
            if int(result.status) == 2:
                infeasible_prefix_attempts += 1
                return None, None, None
            if int(result.status) != 0 or result.x is None:
                raise RuntimeError(
                    "HALT_COMMON_INITIAL_ROUTE_MILP_STATUS:"
                    f"{result.status}:{result.message}"
                )
            route_groups = {
                depot_id: [[] for _ in range(caps[depot_id])]
                for depot_id in depots
            }
            mapping = dict(original)
            for customer_id in customer_ids:
                chosen = [
                    key
                    for key in (
                        (customer_id, depot_id, route_index)
                        for depot_id in allowed_depots[customer_id]
                        for route_index in range(caps[depot_id])
                    )
                    if float(result.x[variable_index[key]]) > 0.5
                ]
                if len(chosen) != 1:
                    raise RuntimeError("HALT_COMMON_INITIAL_ROUTE_MILP_NONINTEGRAL")
                _, depot_id, route_index = chosen[0]
                mapping[customer_id] = depot_id
                route_groups[depot_id][route_index].append(customer_id)
            new_cut = False
            for depot_id in depots:
                for group in route_groups[depot_id]:
                    if not group:
                        continue
                    route_checker_calls += 1
                    if route_feasible(bundle, depot_id, group):
                        continue
                    minimal_group = list(group)
                    for customer_id in reversed(group):
                        trial_group = [
                            item
                            for item in minimal_group
                            if item != customer_id
                        ]
                        if not trial_group:
                            continue
                        route_checker_calls += 1
                        if not route_feasible(
                            bundle, depot_id, trial_group
                        ):
                            minimal_group = trial_group
                    cut = (depot_id, tuple(minimal_group))
                    if cut in route_cuts:
                        raise RuntimeError("HALT_DUPLICATE_COMMON_ROUTE_CUT")
                    route_cuts.add(cut)
                    new_cut = True
            if new_cut:
                continue
            compact_groups = {
                depot_id: [group for group in route_groups[depot_id] if group]
                for depot_id in depots
            }
            chosen_options = [
                next(
                    option_index
                    for option_index, (_, destination) in enumerate(options[index])
                    if destination == mapping[item["customer_id"]]
                )
                for index, item in enumerate(selected)
            ]
            return mapping, chosen_options, compact_groups

    prefix: list[int] = []
    mapping, incumbent, route_groups = solve_prefix([], None)
    if mapping is None or incumbent is None or route_groups is None:
        audit = {
            "algorithm": "EXACT_LEXICOGRAPHIC_DESTINATION_AND_LAZY_ROUTE_PARTITION_MILP",
            "global_feasible_completion_found": False,
            "milp_solver_calls": solver_calls,
            "route_feasibility_checker_calls": route_checker_calls,
            "route_subset_cuts": len(route_cuts),
            "pairwise_route_checks": pairwise_route_checks,
            "infeasible_prefix_attempts": infeasible_prefix_attempts,
        }
        return None, None, audit
    for position, item_options in enumerate(options):
        accepted = False
        for option_index in range(len(item_options)):
            candidate_prefix = [*prefix, option_index]
            if incumbent[: len(candidate_prefix)] == candidate_prefix:
                prefix.append(option_index)
                accepted = True
                break
            witness, witness_options, witness_routes = solve_prefix(
                candidate_prefix, incumbent
            )
            if witness is None or witness_options is None or witness_routes is None:
                continue
            prefix.append(option_index)
            mapping = witness
            incumbent = witness_options
            route_groups = witness_routes
            accepted = True
            break
        if not accepted:
            return None, None, {
                "algorithm": "EXACT_LEXICOGRAPHIC_DESTINATION_AND_LAZY_ROUTE_PARTITION_MILP",
                "global_feasible_completion_found": False,
                "milp_solver_calls": solver_calls,
                "route_feasibility_checker_calls": route_checker_calls,
                "route_subset_cuts": len(route_cuts),
                "pairwise_route_checks": pairwise_route_checks,
                "infeasible_prefix_attempts": infeasible_prefix_attempts,
            }
    rank_vector = [
        options[index][option_index][0]
        for index, option_index in enumerate(prefix)
    ]
    audit = {
        "algorithm": "EXACT_LEXICOGRAPHIC_DESTINATION_AND_LAZY_ROUTE_PARTITION_MILP",
        "global_feasible_completion_found": True,
        "fixed_customer_order": "result-blind SHA-256 order",
        "destination_order": "directed-distance absolute rank, second then third/fourth, original owner skipped",
        "prefix_feasibility_pruning": False,
        "milp_solver_calls": solver_calls,
        "route_feasibility_checker_calls": route_checker_calls,
        "route_subset_cuts": len(route_cuts),
        "pairwise_route_checks": pairwise_route_checks,
        "infeasible_prefix_attempts": infeasible_prefix_attempts,
        "route_groups_by_depot": route_groups,
    }
    return mapping, rank_vector, audit


def _legacy_dfs_lexicographic_global_assignment(
    bundle: Any,
    original: dict[str, str],
    selected: list[dict[str, Any]],
) -> tuple[dict[str, str] | None, list[int] | None, dict[str, Any]]:
    """Exact full-mapping search in the frozen packer's monotone order."""

    from functools import lru_cache

    selected_index = {
        item["customer_id"]: index for index, item in enumerate(selected)
    }
    options = [
        [
            (absolute_rank, destination)
            for absolute_rank, destination in enumerate(
                item["ranking"], start=1
            )
            if absolute_rank != 1 and destination != item["owner"]
        ]
        for item in selected
    ]
    depots = _depot_ids(bundle)
    depot_index = {depot_id: index for index, depot_id in enumerate(depots)}
    caps = {
        depot_id: int(bundle.fleet_caps_by_depot[depot_id]["num_cv"])
        + int(bundle.fleet_caps_by_depot[depot_id]["num_ev"])
        for depot_id in depots
    }
    customer_ids = [
        node.node_id
        for node in sorted(
            (
                node
                for node in bundle.instance.nodes
                if node.node_type.lower() == "c"
            ),
            key=lambda node: (
                float(node.due_time),
                float(node.ready_time),
                node.node_id,
            ),
        )
    ]
    node_lookup = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    payload_capacity = bundle.instance.payload_capacity_kg(
        "cv", fallback=float(bundle.prices.Q_capacity)
    )
    subset_masks = list(range(1, 1 << len(depots)))
    subset_depot_indices = {
        mask: [
            index
            for index in range(len(depots))
            if mask & (1 << index)
        ]
        for mask in subset_masks
    }
    subset_capacity = {
        mask: sum(
            caps[depots[index]] * float(payload_capacity)
            for index in subset_depot_indices[mask]
        )
        for mask in subset_masks
    }
    customer_position = {
        customer_id: index for index, customer_id in enumerate(customer_ids)
    }
    membership_affectors = {
        depot_id: {
            selected_position
            for selected_position, item_options in enumerate(options)
            if 0
            < sum(destination == depot_id for _, destination in item_options)
            < len(item_options)
        }
        for depot_id in depots
    }
    route_feasible = e3._pack_depot.__globals__["_route_feasible"]
    nodes_visited = 0
    route_checks = 0
    cap_prunes = 0
    prefix_oracle_calls = 0
    infeasible_prefix_attempts = 0
    cache_hits = 0
    cache_misses = 0
    conflict_backjumps = 0
    heuristic_checker_calls = 0
    demand_hall_prunes = 0

    RouteState = tuple[tuple[tuple[str, ...], ...], ...]

    def add_customer(
        state: RouteState,
        depot_id: str,
        customer_id: str,
    ) -> tuple[RouteState | None, str | None]:
        nonlocal route_checks, cap_prunes
        depot_position = depot_index[depot_id]
        routes = [list(route) for route in state[depot_position]]
        for route_position, route in enumerate(routes):
            candidate = [*route, customer_id]
            route_checks += 1
            if route_feasible(bundle, depot_id, candidate):
                routes[route_position] = candidate
                updated = list(state)
                updated[depot_position] = tuple(
                    tuple(item) for item in routes
                )
                return tuple(updated), None
        route_checks += 1
        if not route_feasible(bundle, depot_id, [customer_id]):
            return None, depot_id
        if len(routes) >= caps[depot_id]:
            cap_prunes += 1
            return None, depot_id
        routes.append([customer_id])
        updated = list(state)
        updated[depot_position] = tuple(tuple(item) for item in routes)
        return tuple(updated), None

    def failure_conflict(
        depot_id: str,
        through_customer_position: int,
    ) -> frozenset[int]:
        return frozenset(
            selected_position
            for selected_position in membership_affectors[depot_id]
            if customer_position[selected[selected_position]["customer_id"]]
            <= through_customer_position
        )

    def quick_witness(
        prefix: list[int],
        preferred: list[int] | None,
    ) -> tuple[
        dict[str, str] | None,
        list[int] | None,
        dict[str, list[list[str]]] | None,
    ]:
        nonlocal heuristic_checker_calls
        candidates: list[list[int]] = []
        if preferred is not None and preferred[: len(prefix)] == prefix:
            candidates.append(list(preferred))
        candidates.append(
            [*prefix, *([0] * (len(options) - len(prefix)))]
        )
        seed_material = (
            f"{TASK_ID}|{bundle.instance_id}|first-fit-witness|"
            + ",".join(str(item) for item in prefix)
        )
        rng = random.Random(
            int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
        )
        for _ in range(512):
            candidates.append(
                [
                    *prefix,
                    *[
                        rng.randrange(len(options[index]))
                        for index in range(len(prefix), len(options))
                    ],
                ]
            )
        seen: set[tuple[int, ...]] = set()
        for chosen_options in candidates:
            key = tuple(chosen_options)
            if key in seen:
                continue
            seen.add(key)
            mapping = dict(original)
            for selected_position, option_index in enumerate(chosen_options):
                mapping[selected[selected_position]["customer_id"]] = options[
                    selected_position
                ][option_index][1]
            candidate = e3.with_responsibility(bundle, mapping)
            route_groups: dict[str, list[list[str]]] = {}
            heuristic_checker_calls += 1
            for depot_id in depots:
                groups = e3._pack_depot(candidate, depot_id)
                if len(groups) > caps[depot_id]:
                    break
                route_groups[depot_id] = groups
            else:
                return mapping, chosen_options, route_groups
        return None, None, None

    def solve_prefix(
        prefix: list[int],
        preferred: list[int] | None,
    ) -> tuple[
        dict[str, str] | None,
        list[int] | None,
        dict[str, list[list[str]]] | None,
    ]:
        nonlocal nodes_visited, prefix_oracle_calls
        nonlocal infeasible_prefix_attempts, cache_hits, cache_misses
        prefix_oracle_calls += 1
        quick = quick_witness(prefix, preferred)
        if quick[0] is not None:
            return quick
        allowed_masks: list[int] = []
        for customer_id in customer_ids:
            selected_position = selected_index.get(customer_id)
            if selected_position is None:
                destinations = [original[customer_id]]
            elif selected_position < len(prefix):
                destinations = [
                    options[selected_position][prefix[selected_position]][1]
                ]
            else:
                destinations = [
                    destination
                    for _, destination in options[selected_position]
                ]
            mask = 0
            for destination in destinations:
                mask |= 1 << depot_index[destination]
            allowed_masks.append(mask)
        suffix_mandatory = {
            mask: [0.0] * (len(customer_ids) + 1)
            for mask in subset_masks
        }
        for customer_index in range(len(customer_ids) - 1, -1, -1):
            demand = float(node_lookup[customer_ids[customer_index]].demand)
            allowed_mask = allowed_masks[customer_index]
            for mask in subset_masks:
                suffix_mandatory[mask][customer_index] = (
                    suffix_mandatory[mask][customer_index + 1]
                    + (demand if allowed_mask & ~mask == 0 else 0.0)
                )

        @lru_cache(maxsize=10000)
        def visit(
            customer_position: int,
            state: RouteState,
            assigned_demand: tuple[float, ...],
        ) -> tuple[
            tuple[RouteState, tuple[tuple[int, int], ...]] | None,
            frozenset[int],
        ]:
            nonlocal nodes_visited, conflict_backjumps, demand_hall_prunes
            nodes_visited += 1
            for mask in subset_masks:
                current = sum(
                    assigned_demand[index]
                    for index in subset_depot_indices[mask]
                )
                if (
                    current
                    + suffix_mandatory[mask][customer_position]
                    > subset_capacity[mask] + 1.0e-9
                ):
                    demand_hall_prunes += 1
                    return None, frozenset(range(len(selected)))
            if customer_position == len(customer_ids):
                return (state, ()), frozenset()
            customer_id = customer_ids[customer_position]
            selected_position = selected_index.get(customer_id)
            if selected_position is None:
                updated, failing_depot = add_customer(
                    state, original[customer_id], customer_id
                )
                if updated is None:
                    if failing_depot is None:
                        raise RuntimeError("HALT_UNATTRIBUTED_D2A_PREFIX_FAILURE")
                    return None, failure_conflict(
                        failing_depot, customer_position
                    )
                next_demand = list(assigned_demand)
                next_demand[depot_index[original[customer_id]]] += float(
                    node_lookup[customer_id].demand
                )
                return visit(
                    customer_position + 1,
                    updated,
                    tuple(next_demand),
                )
            option_indices = (
                [prefix[selected_position]]
                if selected_position < len(prefix)
                else list(range(len(options[selected_position])))
            )
            branch_conflicts: set[int] = set()
            ordered_branches: list[
                tuple[
                    tuple[float, float, int, str],
                    int,
                    str,
                    RouteState | None,
                    str | None,
                    tuple[float, ...],
                ]
            ] = []
            for option_index in option_indices:
                destination = options[selected_position][option_index][1]
                updated, failing_depot = add_customer(
                    state, destination, customer_id
                )
                next_demand = list(assigned_demand)
                next_demand[depot_index[destination]] += float(
                    node_lookup[customer_id].demand
                )
                route_utilization = (
                    math.inf
                    if updated is None
                    else len(updated[depot_index[destination]])
                    / caps[destination]
                )
                demand_utilization = (
                    next_demand[depot_index[destination]]
                    / (caps[destination] * float(payload_capacity))
                )
                ordered_branches.append(
                    (
                        (
                            route_utilization,
                            demand_utilization,
                            options[selected_position][option_index][0],
                            destination,
                        ),
                        option_index,
                        destination,
                        updated,
                        failing_depot,
                        tuple(next_demand),
                    )
                )
            if selected_position < len(prefix):
                ordered_branches.sort(key=lambda row: row[1])
            else:
                ordered_branches.sort(key=lambda row: row[0])
            for (
                _branch_key,
                option_index,
                destination,
                updated,
                failing_depot,
                next_demand,
            ) in ordered_branches:
                if updated is None:
                    if failing_depot is None:
                        raise RuntimeError("HALT_UNATTRIBUTED_D2A_PREFIX_FAILURE")
                    conflict = failure_conflict(
                        failing_depot, customer_position
                    )
                else:
                    suffix, conflict = visit(
                        customer_position + 1,
                        updated,
                        next_demand,
                    )
                    if suffix is not None:
                        final_state, assignments = suffix
                        return (
                            (
                                final_state,
                                ((selected_position, option_index), *assignments),
                            ),
                            frozenset(),
                        )
                if selected_position not in conflict:
                    conflict_backjumps += 1
                    return None, conflict
                branch_conflicts.update(conflict)
            branch_conflicts.discard(selected_position)
            return None, frozenset(branch_conflicts)

        empty_state: RouteState = tuple(() for _ in depots)
        found, _root_conflict = visit(
            0, empty_state, tuple(0.0 for _ in depots)
        )
        info = visit.cache_info()
        cache_hits += int(info.hits)
        cache_misses += int(info.misses)
        if found is None:
            infeasible_prefix_attempts += 1
            return None, None, None
        final_state, assignments = found
        chosen_options = [0] * len(selected)
        for selected_position, option_index in assignments:
            chosen_options[selected_position] = option_index
        mapping = dict(original)
        for selected_position, option_index in enumerate(chosen_options):
            mapping[selected[selected_position]["customer_id"]] = options[
                selected_position
            ][option_index][1]
        route_groups = {
            depot_id: [list(route) for route in final_state[index]]
            for index, depot_id in enumerate(depots)
        }
        return mapping, chosen_options, route_groups

    prefix: list[int] = []
    mapping, incumbent, route_groups = solve_prefix([], None)
    if mapping is None or incumbent is None or route_groups is None:
        return None, None, {
            "algorithm": "EXACT_LEXICOGRAPHIC_FULL_MAPPING_DFS_IN_FROZEN_FIRST_FIT_ORDER",
            "global_feasible_completion_found": False,
            "prefix_oracle_calls": prefix_oracle_calls,
            "infeasible_prefix_attempts": infeasible_prefix_attempts,
            "nodes_visited": nodes_visited,
            "route_feasibility_checker_calls": route_checks,
            "d2a_cap_prunes": cap_prunes,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "conflict_backjumps": conflict_backjumps,
            "heuristic_checker_calls": heuristic_checker_calls,
            "demand_hall_prunes": demand_hall_prunes,
        }
    for selected_position, item_options in enumerate(options):
        accepted = False
        for option_index in range(len(item_options)):
            candidate_prefix = [*prefix, option_index]
            if incumbent[: len(candidate_prefix)] == candidate_prefix:
                prefix.append(option_index)
                accepted = True
                break
            witness, witness_options, witness_routes = solve_prefix(
                candidate_prefix, incumbent
            )
            if witness is None or witness_options is None or witness_routes is None:
                continue
            prefix.append(option_index)
            mapping = witness
            incumbent = witness_options
            route_groups = witness_routes
            accepted = True
            break
        if not accepted:
            return None, None, {
                "algorithm": "EXACT_LEXICOGRAPHIC_FULL_MAPPING_DFS_IN_FROZEN_FIRST_FIT_ORDER",
                "global_feasible_completion_found": False,
                "prefix_oracle_calls": prefix_oracle_calls,
                "infeasible_prefix_attempts": infeasible_prefix_attempts,
                "nodes_visited": nodes_visited,
                "route_feasibility_checker_calls": route_checks,
                "d2a_cap_prunes": cap_prunes,
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "conflict_backjumps": conflict_backjumps,
                "heuristic_checker_calls": heuristic_checker_calls,
                "demand_hall_prunes": demand_hall_prunes,
            }
    rank_vector = [
        options[index][option_index][0]
        for index, option_index in enumerate(prefix)
    ]
    audit = {
        "algorithm": "EXACT_LEXICOGRAPHIC_FULL_MAPPING_DFS_IN_FROZEN_FIRST_FIT_ORDER",
        "global_feasible_completion_found": True,
        "fixed_customer_order": "result-blind SHA-256 order for lexicographic destination decisions",
        "destination_order": "directed-distance absolute rank, second then third/fourth, original owner skipped",
        "feasibility_search_order": "frozen due_time, ready_time, customer_id order used by D2-A First-Fit packer",
        "nonmonotone_hash_prefix_pruning": False,
        "prefix_oracle_calls": prefix_oracle_calls,
        "infeasible_prefix_attempts": infeasible_prefix_attempts,
        "nodes_visited": nodes_visited,
        "route_feasibility_checker_calls": route_checks,
        "d2a_cap_prunes": cap_prunes,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "conflict_backjumps": conflict_backjumps,
        "heuristic_checker_calls": heuristic_checker_calls,
        "demand_hall_prunes": demand_hall_prunes,
        "route_groups_by_depot": route_groups,
    }
    return mapping, rank_vector, audit


def _legacy_z3_first_fit_lexicographic_global_assignment(
    bundle: Any,
    original: dict[str, str],
    selected: list[dict[str, Any]],
) -> tuple[dict[str, str] | None, list[int] | None, dict[str, Any]]:
    """Solve the approved full-mapping rule exactly in the D2-A packer.

    The Boolean/integer transition model below is an exact encoding of the
    frozen First-Fit packer: customers arrive in due/ready/id order; a customer
    is appended to the first route for which capacity, its own time window,
    and the return-to-depot time window remain feasible.  If no existing route
    works, the first unused route slot is opened.  Destination decisions are
    then fixed one at a time in the result-blind SHA order, so a farther depot
    is accepted only after the complete suffix is proven infeasible at every
    nearer approved destination.
    """

    try:
        import z3  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        system_site = Path(
            "/Library/Frameworks/Python.framework/Versions/3.14/"
            "lib/python3.14/site-packages"
        )
        if system_site.is_dir() and str(system_site) not in sys.path:
            sys.path.append(str(system_site))
        try:
            import z3  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError("HALT_EXACT_INPUT_SOLVER_Z3_MISSING") from exc

    selected_index = {
        item["customer_id"]: index for index, item in enumerate(selected)
    }
    options = [
        [
            (absolute_rank, destination)
            for absolute_rank, destination in enumerate(
                item["ranking"], start=1
            )
            if absolute_rank != 1 and destination != item["owner"]
        ]
        for item in selected
    ]
    depots = _depot_ids(bundle)
    depot_index = {depot_id: index for index, depot_id in enumerate(depots)}
    caps = {
        depot_id: int(bundle.fleet_caps_by_depot[depot_id]["num_cv"])
        + int(bundle.fleet_caps_by_depot[depot_id]["num_ev"])
        for depot_id in depots
    }
    customer_nodes = sorted(
        (
            node
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        ),
        key=lambda node: (
            float(node.due_time),
            float(node.ready_time),
            node.node_id,
        ),
    )
    customer_ids = [node.node_id for node in customer_nodes]
    customer_position = {
        customer_id: index for index, customer_id in enumerate(customer_ids)
    }
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    max_cap = max(caps.values())
    payload_capacity = float(
        bundle.instance.payload_capacity_kg(
            "cv", fallback=float(bundle.prices.Q_capacity)
        )
    )
    fallback_speed = float(bundle.prices.v_speed_ms)
    tolerance = 1.0e-9

    time_scale = 1_000_000_000
    load_scale = 1_000_000

    def scaled(value: float, factor: int) -> int:
        return int(round(float(value) * factor))

    travel_to_customer: list[dict[str, int]] = []
    return_to_depot: list[dict[str, float]] = []
    for customer in customer_nodes:
        incoming: dict[str, int] = {}
        for prior in node_lookup.values():
            _, travel_time, _ = bundle.instance.arc_metrics(
                prior.node_id,
                customer.node_id,
                "cv",
                fallback_speed_mps=fallback_speed,
            )
            incoming[prior.node_id] = scaled(float(travel_time), time_scale)
        travel_to_customer.append(incoming)
        return_to_depot.append(
            {
                depot_id: scaled(
                    float(bundle.instance.arc_metrics(
                        customer.node_id,
                        depot_id,
                        "cv",
                        fallback_speed_mps=fallback_speed,
                    )[1]),
                    time_scale,
                )
                for depot_id in depots
            }
        )

    solver = z3.SolverFor("QF_LIA")
    destinations = [z3.Int(f"destination_{index}") for index in range(len(customer_ids))]
    route_choices = [z3.Int(f"route_{index}") for index in range(len(customer_ids))]
    selected_destination_values: dict[int, list[int]] = {}
    for position, customer_id in enumerate(customer_ids):
        selected_position = selected_index.get(customer_id)
        if selected_position is None:
            values = [depot_index[original[customer_id]]]
        else:
            values = [
                depot_index[destination]
                for _, destination in options[selected_position]
            ]
            selected_destination_values[selected_position] = values
        solver.add(z3.Or(*(destinations[position] == value for value in values)))
        solver.add(route_choices[position] >= 0, route_choices[position] < max_cap)

    load: dict[tuple[int, int, int], Any] = {}
    depart: dict[tuple[int, int, int], Any] = {}
    last: dict[tuple[int, int, int], Any] = {}
    node_codes = {
        node_id: index for index, node_id in enumerate(sorted(node_lookup))
    }
    for depot_id, depot_position in depot_index.items():
        depot = node_lookup[depot_id]
        for route_index in range(caps[depot_id]):
            key = (0, depot_position, route_index)
            load[key] = z3.Int(f"load_0_{depot_position}_{route_index}")
            depart[key] = z3.Int(f"depart_0_{depot_position}_{route_index}")
            last[key] = z3.Int(f"last_0_{depot_position}_{route_index}")
            solver.add(
                load[key] == 0,
                depart[key]
                == scaled(
                    float(depot.ready_time) + float(depot.service_time),
                    time_scale,
                ),
                last[key] == node_codes[depot_id],
            )

    feasibility_expressions = 0
    for position, customer in enumerate(customer_nodes):
        customer_code = node_codes[customer.node_id]
        demand = scaled(float(customer.demand), load_scale)
        ready = scaled(float(customer.ready_time), time_scale)
        due = scaled(float(customer.due_time) + tolerance, time_scale)
        service = scaled(float(customer.service_time), time_scale)
        selection_terms: list[Any] = []
        for depot_id, depot_position in depot_index.items():
            depot = node_lookup[depot_id]
            prior_feasible: list[Any] = []
            for route_index in range(caps[depot_id]):
                key = (position, depot_position, route_index)
                travel: Any = z3.IntVal(0)
                for prior_id, prior_code in node_codes.items():
                    travel = z3.If(
                        last[key] == prior_code,
                        travel_to_customer[position][prior_id],
                        travel,
                    )
                arrive = depart[key] + travel
                start = z3.If(arrive >= ready, arrive, ready)
                new_depart = start + service
                return_arrive = (
                    new_depart + return_to_depot[position][depot_id]
                )
                return_start = z3.If(
                    return_arrive
                    >= scaled(float(depot.ready_time), time_scale),
                    return_arrive,
                    scaled(float(depot.ready_time), time_scale),
                )
                feasible = z3.And(
                    load[key] + demand
                    <= scaled(payload_capacity, load_scale),
                    start <= due,
                    return_start
                    <= scaled(float(depot.due_time) + tolerance, time_scale),
                )
                feasibility_expressions += 1
                chosen = z3.And(
                    destinations[position] == depot_position,
                    route_choices[position] == route_index,
                    feasible,
                    *[z3.Not(item) for item in prior_feasible],
                )
                selection_terms.append(chosen)
                prior_feasible.append(feasible)

                next_key = (position + 1, depot_position, route_index)
                load[next_key] = z3.Int(
                    f"load_{position + 1}_{depot_position}_{route_index}"
                )
                depart[next_key] = z3.Int(
                    f"depart_{position + 1}_{depot_position}_{route_index}"
                )
                last[next_key] = z3.Int(
                    f"last_{position + 1}_{depot_position}_{route_index}"
                )
                solver.add(
                    load[next_key] == z3.If(chosen, load[key] + demand, load[key]),
                    depart[next_key] == z3.If(chosen, new_depart, depart[key]),
                    last[next_key] == z3.If(chosen, customer_code, last[key]),
                )
            solver.add(
                z3.Implies(
                    destinations[position] == depot_position,
                    z3.Or(*[
                        term
                        for term in selection_terms[-caps[depot_id]:]
                    ]),
                )
            )
        solver.add(z3.Or(*selection_terms))

    solver_checks = 0
    infeasible_prefix_attempts = 0
    solver_checks += 1
    initial_status = solver.check()
    if initial_status == z3.unknown:
        raise RuntimeError(
            f"HALT_EXACT_INPUT_SOLVER_UNKNOWN:{solver.reason_unknown()}"
        )
    if initial_status == z3.unsat:
        return None, None, {
            "algorithm": "EXACT_Z3_FIRST_FIT_TRANSITION_LEXICOGRAPHIC_MAPPING",
            "global_feasible_completion_found": False,
            "solver_checks": solver_checks,
            "infeasible_prefix_attempts": 1,
            "feasibility_expressions": feasibility_expressions,
            "z3_version": z3.get_version_string(),
        }

    chosen_options: list[int] = []
    for selected_position, item_options in enumerate(options):
        position = customer_position[selected[selected_position]["customer_id"]]
        accepted = False
        for option_index, (_rank, destination) in enumerate(item_options):
            solver.push()
            solver.add(destinations[position] == depot_index[destination])
            solver_checks += 1
            status = solver.check()
            if status == z3.unknown:
                reason = solver.reason_unknown()
                solver.pop()
                raise RuntimeError(
                    f"HALT_EXACT_INPUT_SOLVER_UNKNOWN:{reason}"
                )
            if status == z3.sat:
                solver.pop()
                solver.add(destinations[position] == depot_index[destination])
                chosen_options.append(option_index)
                accepted = True
                break
            solver.pop()
            infeasible_prefix_attempts += 1
        if not accepted:
            raise RuntimeError("HALT_EXACT_INPUT_LEXICOGRAPHIC_FIXING_FAILED")

    solver_checks += 1
    final_status = solver.check()
    if final_status != z3.sat:
        raise RuntimeError(f"HALT_EXACT_INPUT_FINAL_MODEL:{final_status}")
    model = solver.model()
    mapping = dict(original)
    for selected_position, option_index in enumerate(chosen_options):
        mapping[selected[selected_position]["customer_id"]] = options[
            selected_position
        ][option_index][1]

    route_groups: dict[str, list[list[str]]] = {
        depot_id: [[] for _ in range(caps[depot_id])] for depot_id in depots
    }
    for position, customer_id in enumerate(customer_ids):
        depot_position = int(model.eval(destinations[position]).as_long())
        route_index = int(model.eval(route_choices[position]).as_long())
        route_groups[depots[depot_position]][route_index].append(customer_id)
    route_groups = {
        depot_id: [route for route in groups if route]
        for depot_id, groups in route_groups.items()
    }

    actual = e3.with_responsibility(bundle, mapping)
    actual_route_groups = {
        depot_id: e3._pack_depot(actual, depot_id) for depot_id in depots
    }
    if actual_route_groups != route_groups:
        raise RuntimeError("HALT_EXACT_Z3_VS_D2A_FIRST_FIT_ROUTE_MISMATCH")
    for depot_id in depots:
        if len(route_groups[depot_id]) > caps[depot_id]:
            raise RuntimeError("HALT_EXACT_Z3_ROUTE_CAP_MISMATCH")

    rank_vector = [
        options[index][option_index][0]
        for index, option_index in enumerate(chosen_options)
    ]
    audit = {
        "algorithm": "EXACT_Z3_FIRST_FIT_TRANSITION_LEXICOGRAPHIC_MAPPING",
        "global_feasible_completion_found": True,
        "fixed_customer_order": "result-blind SHA-256 order for lexicographic destination decisions",
        "destination_order": "directed-distance absolute rank, second then third/fourth, original owner skipped",
        "feasibility_search_order": "frozen due_time, ready_time, customer_id order used by D2-A First-Fit packer",
        "complete_suffix_semantics": True,
        "solver_checks": solver_checks,
        "infeasible_prefix_attempts": infeasible_prefix_attempts,
        "feasibility_expressions": feasibility_expressions,
        "integer_time_scale_per_second": time_scale,
        "integer_load_scale_per_kg": load_scale,
        "z3_version": z3.get_version_string(),
        "route_groups_by_depot": route_groups,
    }
    return mapping, rank_vector, audit


def _lexicographic_global_assignment(
    bundle: Any,
    original: dict[str, str],
    selected: list[dict[str, Any]],
) -> tuple[dict[str, str] | None, list[int] | None, dict[str, Any]]:
    """Construct the lexicographically first legal capped common initial.

    Route slots are a symmetry-broken exact set-partition model.  Capacity and
    every pairwise-infeasible route subset are imposed up front.  A candidate
    model is then checked with the frozen route-feasibility routine; each
    rejected route is reduced to an irreducible infeasible subset and excluded
    from every symmetric slot.  Thus SAT is returned only with explicit legal
    routes, while UNSAT is a finite input-only certificate over sound route
    subset cuts.  Prefix assumptions implement the approved SHA customer order
    and directed-distance destination order against complete suffixes.
    """

    try:
        import z3  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        system_site = Path(
            "/Library/Frameworks/Python.framework/Versions/3.14/"
            "lib/python3.14/site-packages"
        )
        if system_site.is_dir() and str(system_site) not in sys.path:
            sys.path.append(str(system_site))
        try:
            import z3  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError("HALT_EXACT_INPUT_SOLVER_Z3_MISSING") from exc

    options = [
        [
            (absolute_rank, destination)
            for absolute_rank, destination in enumerate(
                item["ranking"], start=1
            )
            if absolute_rank != 1 and destination != item["owner"]
        ]
        for item in selected
    ]
    selected_index = {
        item["customer_id"]: index for index, item in enumerate(selected)
    }
    depots = _depot_ids(bundle)
    caps = {
        depot_id: int(bundle.fleet_caps_by_depot[depot_id]["num_cv"])
        + int(bundle.fleet_caps_by_depot[depot_id]["num_ev"])
        for depot_id in depots
    }
    customer_nodes = sorted(
        (
            node
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        ),
        key=lambda node: (
            float(node.due_time),
            float(node.ready_time),
            node.node_id,
        ),
    )
    customer_ids = [node.node_id for node in customer_nodes]
    customer_position = {
        customer_id: index for index, customer_id in enumerate(customer_ids)
    }
    allowed_depots = {
        customer_id: (
            [destination for _, destination in options[selected_index[customer_id]]]
            if customer_id in selected_index
            else [original[customer_id]]
        )
        for customer_id in customer_ids
    }
    possible_positions = {
        depot_id: [
            position
            for position, customer_id in enumerate(customer_ids)
            if depot_id in allowed_depots[customer_id]
        ]
        for depot_id in depots
    }
    payload_capacity = int(
        round(
            float(
                bundle.instance.payload_capacity_kg(
                    "cv", fallback=float(bundle.prices.Q_capacity)
                )
            )
            * 1_000_000
        )
    )
    demands = [int(round(float(node.demand) * 1_000_000)) for node in customer_nodes]
    route_feasible = e3._pack_depot.__globals__["_route_feasible"]

    def new_pb_solver() -> Any:
        return z3.Then(
            z3.With(z3.Tactic("pb2bv"), "pb.solver", "sorting"),
            z3.Tactic("sat"),
        ).solver()

    nearest_mapping = dict(original)
    nearest_rank_vector: list[int] = []
    for selected_position, item_options in enumerate(options):
        absolute_rank, destination = item_options[0]
        nearest_mapping[selected[selected_position]["customer_id"]] = destination
        nearest_rank_vector.append(absolute_rank)
    nearest_bundle = e3.with_responsibility(bundle, nearest_mapping)
    nearest_groups = {
        depot_id: e3._pack_depot(nearest_bundle, depot_id)
        for depot_id in depots
    }
    if all(
        len(nearest_groups[depot_id]) <= caps[depot_id]
        for depot_id in depots
    ):
        return nearest_mapping, nearest_rank_vector, {
            "algorithm": "DIRECT_LEXICOGRAPHIC_ALL_NEAREST_D2A_WITNESS",
            "global_feasible_completion_found": True,
            "fixed_customer_order": "result-blind SHA-256 order",
            "destination_order": "directed-distance absolute rank, second then third/fourth, original owner skipped",
            "complete_suffix_semantics": True,
            "solver_checks": 0,
            "route_subset_cuts": 0,
            "pairwise_route_checks": 0,
            "route_feasibility_checker_calls": 0,
            "candidate_models_rejected": 0,
            "infeasible_prefix_attempts": 0,
            "z3_version": z3.get_version_string(),
            "route_groups_by_depot": nearest_groups,
        }

    fixed_partition_solver_checks = 0
    fixed_partition_route_checks = 0
    fixed_partition_cuts = 0
    fixed_partition_rejected_models = 0

    def exact_fixed_mapping_partition(
        mapping: dict[str, str],
    ) -> dict[str, list[list[str]]] | None:
        nonlocal fixed_partition_solver_checks
        nonlocal fixed_partition_route_checks, fixed_partition_cuts
        nonlocal fixed_partition_rejected_models
        result: dict[str, list[list[str]]] = {}
        for depot_id in depots:
            positions = [
                position
                for position, customer_id in enumerate(customer_ids)
                if mapping[customer_id] == depot_id
            ]
            if (
                sum(demands[position] for position in positions)
                > caps[depot_id] * payload_capacity
            ):
                return None
            local = new_pb_solver()
            variables = {
                (position, route_index): z3.Bool(
                    f"fixed_{depot_id}_{position}_{route_index}"
                )
                for position in positions
                for route_index in range(caps[depot_id])
            }
            for position in positions:
                local.add(
                    z3.PbEq(
                        [
                            (variables[(position, route_index)], 1)
                            for route_index in range(caps[depot_id])
                        ],
                        1,
                    )
                )
            for route_index in range(caps[depot_id]):
                local.add(
                    z3.PbLe(
                        [
                            (
                                variables[(position, route_index)],
                                demands[position],
                            )
                            for position in positions
                        ],
                        payload_capacity,
                    )
                )
            local_cuts: set[tuple[int, ...]] = set()

            def add_local_cut(subset: tuple[int, ...]) -> None:
                nonlocal fixed_partition_cuts
                if subset in local_cuts:
                    raise RuntimeError("HALT_DUPLICATE_FIXED_ROUTE_SUBSET_CUT")
                local_cuts.add(subset)
                fixed_partition_cuts += 1
                for route_index in range(caps[depot_id]):
                    local.add(
                        z3.PbLe(
                            [
                                (variables[(position, route_index)], 1)
                                for position in subset
                            ],
                            len(subset) - 1,
                        )
                    )

            for left_index, left in enumerate(positions):
                for right in positions[left_index + 1 :]:
                    fixed_partition_route_checks += 1
                    if not route_feasible(
                        bundle,
                        depot_id,
                        [customer_ids[left], customer_ids[right]],
                    ):
                        add_local_cut((left, right))
            while True:
                fixed_partition_solver_checks += 1
                status = local.check()
                if status == z3.unknown:
                    raise RuntimeError(
                        "HALT_EXACT_FIXED_INPUT_SOLVER_UNKNOWN:"
                        f"{local.reason_unknown()}"
                    )
                if status == z3.unsat:
                    return None
                model = local.model()
                groups: list[list[str]] = []
                rejected: list[tuple[int, ...]] = []
                for route_index in range(caps[depot_id]):
                    group = tuple(
                        position
                        for position in positions
                        if z3.is_true(
                            model.eval(variables[(position, route_index)])
                        )
                    )
                    if not group:
                        continue
                    customers = [customer_ids[position] for position in group]
                    fixed_partition_route_checks += 1
                    if route_feasible(bundle, depot_id, customers):
                        groups.append(customers)
                        continue
                    minimal = list(group)
                    changed = True
                    while changed and len(minimal) > 2:
                        changed = False
                        for position in list(minimal):
                            trial = [item for item in minimal if item != position]
                            fixed_partition_route_checks += 1
                            if trial and not route_feasible(
                                bundle,
                                depot_id,
                                [customer_ids[item] for item in trial],
                            ):
                                minimal = trial
                                changed = True
                                break
                    rejected.append(tuple(minimal))
                if rejected:
                    fixed_partition_rejected_models += 1
                    for subset in rejected:
                        if subset not in local_cuts:
                            add_local_cut(subset)
                    continue
                result[depot_id] = groups
                break
        return result

    exact_nearest_groups = exact_fixed_mapping_partition(nearest_mapping)
    if exact_nearest_groups is not None:
        return nearest_mapping, nearest_rank_vector, {
            "algorithm": "EXACT_LEXICOGRAPHIC_SEPARABLE_ROUTE_PARTITION_SMT",
            "global_feasible_completion_found": True,
            "fixed_customer_order": "result-blind SHA-256 order",
            "destination_order": "directed-distance absolute rank, second then third/fourth, original owner skipped",
            "complete_suffix_semantics": True,
            "all_nearest_complete_mapping_feasible": True,
            "solver_checks": fixed_partition_solver_checks,
            "route_subset_cuts": fixed_partition_cuts,
            "pairwise_route_checks": fixed_partition_route_checks,
            "route_feasibility_checker_calls": fixed_partition_route_checks,
            "candidate_models_rejected": fixed_partition_rejected_models,
            "infeasible_prefix_attempts": 0,
            "z3_version": z3.get_version_string(),
            "route_groups_by_depot": exact_nearest_groups,
        }
    solver = new_pb_solver()
    assignments: dict[tuple[int, str, int], Any] = {}
    for position, customer_id in enumerate(customer_ids):
        terms: list[Any] = []
        for depot_id in allowed_depots[customer_id]:
            for route_index in range(caps[depot_id]):
                variable = z3.Bool(
                    f"assign_{position}_{depot_id}_{route_index}"
                )
                assignments[(position, depot_id, route_index)] = variable
                terms.append(variable)
        solver.add(z3.PbEq([(term, 1) for term in terms], 1))
    for depot_id in depots:
        positions = possible_positions[depot_id]
        for route_index in range(caps[depot_id]):
            solver.add(
                z3.PbLe(
                    [
                        (
                            assignments[(position, depot_id, route_index)],
                            demands[position],
                        )
                        for position in positions
                    ],
                    payload_capacity,
                )
            )

    route_subset_cuts: set[tuple[str, tuple[int, ...]]] = set()
    route_checker_calls = 0
    pairwise_route_checks = 0
    solver_checks = 0
    infeasible_prefix_attempts = 0
    candidate_models_rejected = 0

    def add_route_subset_cut(depot_id: str, subset: tuple[int, ...]) -> None:
        key = (depot_id, subset)
        if key in route_subset_cuts:
            raise RuntimeError("HALT_DUPLICATE_EXACT_ROUTE_SUBSET_CUT")
        route_subset_cuts.add(key)
        for route_index in range(caps[depot_id]):
            solver.add(
                z3.PbLe(
                    [
                        (assignments[(position, depot_id, route_index)], 1)
                        for position in subset
                    ],
                    len(subset) - 1,
                )
            )

    for depot_id in depots:
        positions = possible_positions[depot_id]
        for left_index, left in enumerate(positions):
            for right in positions[left_index + 1 :]:
                pairwise_route_checks += 1
                route_checker_calls += 1
                if not route_feasible(
                    bundle,
                    depot_id,
                    [customer_ids[left], customer_ids[right]],
                ):
                    add_route_subset_cut(depot_id, (left, right))

    def destination_assumption(
        selected_position: int,
        option_index: int,
    ) -> Any:
        customer_id = selected[selected_position]["customer_id"]
        position = customer_position[customer_id]
        destination = options[selected_position][option_index][1]
        return z3.Or(
            *[
                assignments[(position, destination, route_index)]
                for route_index in range(caps[destination])
            ]
        )

    def exact_completion(
        prefix: list[int],
    ) -> tuple[
        dict[str, str] | None,
        list[int] | None,
        dict[str, list[list[str]]] | None,
    ]:
        nonlocal solver_checks, infeasible_prefix_attempts
        nonlocal route_checker_calls, candidate_models_rejected
        assumptions = [
            destination_assumption(position, option_index)
            for position, option_index in enumerate(prefix)
        ]
        while True:
            solver_checks += 1
            status = solver.check(*assumptions)
            if status == z3.unknown:
                raise RuntimeError(
                    f"HALT_EXACT_INPUT_SOLVER_UNKNOWN:{solver.reason_unknown()}"
                )
            if status == z3.unsat:
                infeasible_prefix_attempts += 1
                return None, None, None
            model = solver.model()
            route_groups: dict[str, list[list[str]]] = {
                depot_id: [] for depot_id in depots
            }
            rejected: list[tuple[str, tuple[int, ...]]] = []
            for depot_id in depots:
                for route_index in range(caps[depot_id]):
                    group = tuple(
                        position
                        for position in possible_positions[depot_id]
                        if z3.is_true(
                            model.eval(
                                assignments[(position, depot_id, route_index)]
                            )
                        )
                    )
                    if not group:
                        continue
                    customers = [customer_ids[position] for position in group]
                    route_checker_calls += 1
                    if route_feasible(bundle, depot_id, customers):
                        route_groups[depot_id].append(customers)
                        continue
                    minimal = list(group)
                    changed = True
                    while changed and len(minimal) > 2:
                        changed = False
                        for position in list(minimal):
                            trial = [
                                item for item in minimal if item != position
                            ]
                            route_checker_calls += 1
                            if trial and not route_feasible(
                                bundle,
                                depot_id,
                                [customer_ids[item] for item in trial],
                            ):
                                minimal = trial
                                changed = True
                                break
                    rejected.append((depot_id, tuple(minimal)))
            if rejected:
                candidate_models_rejected += 1
                for depot_id, subset in rejected:
                    if (depot_id, subset) not in route_subset_cuts:
                        add_route_subset_cut(depot_id, subset)
                continue

            mapping = dict(original)
            chosen_options: list[int] = []
            for selected_position, item_options in enumerate(options):
                customer_id = selected[selected_position]["customer_id"]
                position = customer_position[customer_id]
                chosen_destination = next(
                    depot_id
                    for depot_id in allowed_depots[customer_id]
                    if any(
                        z3.is_true(
                            model.eval(
                                assignments[(position, depot_id, route_index)]
                            )
                        )
                        for route_index in range(caps[depot_id])
                    )
                )
                option_index = next(
                    index
                    for index, (_rank, destination) in enumerate(item_options)
                    if destination == chosen_destination
                )
                chosen_options.append(option_index)
                mapping[customer_id] = chosen_destination
            return mapping, chosen_options, route_groups

    if selected:
        nearest_mapping_exact, nearest_options_exact, nearest_routes_exact = (
            exact_completion([0] * len(selected))
        )
        if (
            nearest_mapping_exact is not None
            and nearest_options_exact is not None
            and nearest_routes_exact is not None
        ):
            rank_vector = [item_options[0][0] for item_options in options]
            return nearest_mapping_exact, rank_vector, {
                "algorithm": "EXACT_LEXICOGRAPHIC_LAZY_ROUTE_PARTITION_SMT",
                "global_feasible_completion_found": True,
                "fixed_customer_order": "result-blind SHA-256 order for lexicographic destination decisions",
                "destination_order": "directed-distance absolute rank, second then third/fourth, original owner skipped",
                "complete_suffix_semantics": True,
                "all_nearest_complete_mapping_feasible": True,
                "route_order_within_slot": "frozen due_time, ready_time, customer_id order",
                "solver_checks": solver_checks,
                "route_subset_cuts": len(route_subset_cuts),
                "pairwise_route_checks": pairwise_route_checks,
                "route_feasibility_checker_calls": route_checker_calls,
                "candidate_models_rejected": candidate_models_rejected,
                "infeasible_prefix_attempts": infeasible_prefix_attempts,
                "z3_version": z3.get_version_string(),
                "route_groups_by_depot": nearest_routes_exact,
            }

    if not selected:
        mapping, chosen_options, route_groups = exact_completion([])
        if mapping is None or chosen_options is None or route_groups is None:
            return None, None, {
                "algorithm": "EXACT_LEXICOGRAPHIC_LAZY_ROUTE_PARTITION_SMT",
                "global_feasible_completion_found": False,
                "solver_checks": solver_checks,
                "route_subset_cuts": len(route_subset_cuts),
                "route_feasibility_checker_calls": route_checker_calls,
            }
        return mapping, [], {
            "algorithm": "EXACT_LEXICOGRAPHIC_LAZY_ROUTE_PARTITION_SMT",
            "global_feasible_completion_found": True,
            "complete_suffix_semantics": True,
            "solver_checks": solver_checks,
            "route_subset_cuts": len(route_subset_cuts),
            "pairwise_route_checks": pairwise_route_checks,
            "route_feasibility_checker_calls": route_checker_calls,
            "candidate_models_rejected": candidate_models_rejected,
            "infeasible_prefix_attempts": infeasible_prefix_attempts,
            "z3_version": z3.get_version_string(),
            "route_groups_by_depot": route_groups,
        }

    prefix: list[int] = []
    mapping, incumbent, route_groups = exact_completion(prefix)
    if mapping is None or incumbent is None or route_groups is None:
        return None, None, {
            "algorithm": "EXACT_LEXICOGRAPHIC_LAZY_ROUTE_PARTITION_SMT",
            "global_feasible_completion_found": False,
            "complete_suffix_semantics": True,
            "solver_checks": solver_checks,
            "route_subset_cuts": len(route_subset_cuts),
            "pairwise_route_checks": pairwise_route_checks,
            "route_feasibility_checker_calls": route_checker_calls,
            "candidate_models_rejected": candidate_models_rejected,
            "infeasible_prefix_attempts": infeasible_prefix_attempts,
            "z3_version": z3.get_version_string(),
        }
    for selected_position, item_options in enumerate(options):
        accepted = False
        for option_index in range(len(item_options)):
            candidate_prefix = [*prefix, option_index]
            if incumbent[: len(candidate_prefix)] == candidate_prefix:
                prefix.append(option_index)
                accepted = True
                break
            witness, witness_options, witness_routes = exact_completion(
                candidate_prefix
            )
            if (
                witness is None
                or witness_options is None
                or witness_routes is None
            ):
                continue
            prefix.append(option_index)
            mapping = witness
            incumbent = witness_options
            route_groups = witness_routes
            accepted = True
            break
        if not accepted:
            raise RuntimeError("HALT_EXACT_ROUTE_PARTITION_PREFIX_FIXING_FAILED")

    actual_bundle = e3.with_responsibility(bundle, mapping)
    for depot_id, groups in route_groups.items():
        if len(groups) > caps[depot_id]:
            raise RuntimeError("HALT_EXACT_ROUTE_PARTITION_CAP_MISMATCH")
        expected = sorted(
            customer_id
            for customer_id, destination in mapping.items()
            if destination == depot_id
        )
        observed = sorted(customer for group in groups for customer in group)
        if observed != expected:
            raise RuntimeError("HALT_EXACT_ROUTE_PARTITION_COVERAGE_MISMATCH")
        for group in groups:
            route_checker_calls += 1
            if not route_feasible(actual_bundle, depot_id, group):
                raise RuntimeError("HALT_EXACT_ROUTE_PARTITION_FINAL_RECHECK")

    rank_vector = [
        options[index][option_index][0]
        for index, option_index in enumerate(prefix)
    ]
    audit = {
        "algorithm": "EXACT_LEXICOGRAPHIC_LAZY_ROUTE_PARTITION_SMT",
        "global_feasible_completion_found": True,
        "fixed_customer_order": "result-blind SHA-256 order for lexicographic destination decisions",
        "destination_order": "directed-distance absolute rank, second then third/fourth, original owner skipped",
        "complete_suffix_semantics": True,
        "route_order_within_slot": "frozen due_time, ready_time, customer_id order",
        "solver_checks": solver_checks,
        "route_subset_cuts": len(route_subset_cuts),
        "pairwise_route_checks": pairwise_route_checks,
        "route_feasibility_checker_calls": route_checker_calls,
        "candidate_models_rejected": candidate_models_rejected,
        "infeasible_prefix_attempts": infeasible_prefix_attempts,
        "z3_version": z3.get_version_string(),
        "route_groups_by_depot": route_groups,
    }
    return mapping, rank_vector, audit


def build_mapping(
    bundle: Any,
    intensity: int,
) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, Any]]:
    original = dict(bundle.customer_home_depot)
    target = int(
        (
            Decimal(len(original))
            * Decimal(intensity)
            / Decimal(100)
        ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )
    allocations = e3.allocation_counts(original, target)
    selected: list[dict[str, Any]] = []
    ineligible_second_is_owner = 0
    for owner in sorted(allocations):
        candidates: list[dict[str, Any]] = []
        for customer_id, registered_owner in original.items():
            if registered_owner != owner:
                continue
            ranking = _directed_depot_ranking(bundle, customer_id)
            if intensity and ranking[1] == owner:
                ineligible_second_is_owner += 1
                continue
            rank_hash = hashlib.sha256(
                (
                    f"{TASK_ID}|{bundle.instance_id}|{intensity}|"
                    f"{owner}|{customer_id}"
                ).encode("utf-8")
            ).hexdigest()
            candidates.append(
                {
                    "customer_id": customer_id,
                    "owner": owner,
                    "ranking": ranking,
                    "rank_hash": rank_hash,
                }
            )
        candidates.sort(key=lambda row: (row["rank_hash"], row["customer_id"]))
        if len(candidates) < allocations[owner]:
            return original, [], {
                "status": "INFEASIBLE_INPUT",
                "reason": "INSUFFICIENT_TRUE_SECOND_NEAREST_REASSIGNMENT_CANDIDATES",
                "target_reassigned": target,
                "owner": owner,
                "needed": allocations[owner],
                "available": len(candidates),
            }
        selected.extend(candidates[: allocations[owner]])
    selected.sort(key=lambda row: (row["rank_hash"], row["customer_id"]))
    mapping, rank_vector, search_audit = _lexicographic_global_assignment(
        bundle, original, selected
    )
    if mapping is None or rank_vector is None:
        return original, [], {
            "status": "INFEASIBLE_INPUT",
            "reason": "NO_COMPLETE_DESTINATION_ASSIGNMENT_PRESERVES_D2A_COMMON_INITIAL",
            "target_reassigned": target,
            "global_search_audit": search_audit,
        }
    assignment: dict[str, dict[str, Any]] = {}
    fallback_steps = 0
    for item, absolute_rank in zip(selected, rank_vector):
        customer_id = item["customer_id"]
        destination = item["ranking"][absolute_rank - 1]
        fallback_steps += max(0, absolute_rank - 2)
        assignment[customer_id] = {
            "rank_hash": item["rank_hash"],
            "destination": destination,
            "absolute_distance_rank": absolute_rank,
            "directed_distance_m": float(
                bundle.instance.distance(destination, customer_id)
            ),
        }
    actual = sum(mapping[key] != original[key] for key in original)
    if actual != target:
        raise RuntimeError(
            f"HALT_MISMATCH_TARGET_NOT_MET:{bundle.instance_id}:{intensity}:{actual}/{target}"
        )
    rows: list[dict[str, Any]] = []
    for customer_id in sorted(original):
        detail = assignment.get(customer_id)
        rows.append(
            {
                "instance_id": bundle.instance_id,
                "mismatch_intensity_nominal_pct": intensity,
                "customer_id": customer_id,
                "original_registered_depot": original[customer_id],
                "assigned_responsibility_depot": mapping[customer_id],
                "reassigned": detail is not None,
                "result_blind_rank_sha256": "" if detail is None else detail["rank_hash"],
                "destination_absolute_distance_rank": "" if detail is None else detail["absolute_distance_rank"],
                "destination_directed_distance_m": "" if detail is None else detail["directed_distance_m"],
                "destination_rule": "UNCHANGED" if detail is None else "SECOND_NEAREST_THEN_NEXT_IF_D2A_BLOCKED",
            }
        )
    return mapping, rows, {
        "status": "PASS",
        "target_reassigned": target,
        "actual_reassigned": actual,
        "fallback_steps_beyond_second_nearest": fallback_steps,
        "customers_ineligible_because_second_nearest_is_original_owner": ineligible_second_is_owner,
        "global_search_audit": search_audit,
        "final_fleet_probe": {
            "feasible": True,
            "reason": "PASS_EXACT_LEGAL_COMMON_ROUTE_PARTITION",
            "depot_counts": {
                depot_id: {
                    "packed_routes": len(
                        search_audit["route_groups_by_depot"][depot_id]
                    ),
                    "d2a_total_cap": int(
                        bundle.fleet_caps_by_depot[depot_id]["num_cv"]
                    )
                    + int(bundle.fleet_caps_by_depot[depot_id]["num_ev"]),
                }
                for depot_id in _depot_ids(bundle)
            },
        },
    }


def build_common_initial_from_route_groups(
    bundle: Any,
    route_groups: dict[str, list[list[str]]],
) -> tuple[Solution, dict[str, Any]]:
    routes: list[Route] = []
    route_counts: dict[str, int] = {}
    for depot_id in sorted(route_groups):
        groups = route_groups[depot_id]
        cap = int(bundle.fleet_caps_by_depot[depot_id]["num_cv"]) + int(
            bundle.fleet_caps_by_depot[depot_id]["num_ev"]
        )
        if len(groups) > cap:
            raise RuntimeError("HALT_EXACT_ROUTE_GROUPS_EXCEED_D2A_CAP")
        route_counts[depot_id] = len(groups)
        for index, customers in enumerate(groups, start=1):
            routes.append(
                Route(
                    vehicle_id=f"INIT-{depot_id}-CV-{index:03d}",
                    vehicle_type="cv",
                    home_depot_id=depot_id,
                    node_sequence=[depot_id, *customers, depot_id],
                )
            )
    completion = complete_china81_route_skeleton(Solution(routes=routes), bundle)
    solution = completion.solution
    objective, breakdown, exact_violations = exact_china81_score(
        solution, bundle
    )
    checker_violations = check_solution(
        solution, bundle.instance, bundle.prices
    )
    independent = evaluate(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    if exact_violations or checker_violations or solution.cross_site_services:
        raise RuntimeError(
            "HALT_EXACT_COMMON_INITIAL_INDEPENDENT_CHECK:"
            f"{len(exact_violations)}:{len(checker_violations)}:"
            f"{len(solution.cross_site_services)}"
        )
    if not math.isclose(
        float(independent["total_cost"]),
        float(objective),
        rel_tol=1.0e-12,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("HALT_EXACT_COMMON_INITIAL_OBJECTIVE_MISMATCH")
    return solution, {
        "construction": "EXACT_D2A_CAPPED_ROUTE_PARTITION",
        "objective_for_integrity_only": float(objective),
        "breakdown_for_integrity_only": breakdown,
        "route_counts_by_depot": route_counts,
        "completion_activity": completion.activity,
        "violation_count": 0,
        "cross_site_service_count": 0,
    }


def input_dir(instance_id: str, intensity: int) -> Path:
    return OUT / "inputs" / f"{instance_id}__mismatch{intensity:02d}"


def _write_infeasible_input(
    instance_id: str,
    intensity: int,
    audit: dict[str, Any],
) -> None:
    folder = input_dir(instance_id, intensity)
    folder.mkdir(parents=True, exist_ok=True)
    e3.write_json(
        folder / "input_certificate.json",
        {
            "schema": "resetp.e3e6.infeasible-input-certificate.v1",
            "instance_id": instance_id,
            "mismatch_intensity_nominal_pct": intensity,
            "status": "INFEASIBLE_INPUT",
            "audit": audit,
            "no_rows_deleted": True,
            "d2a_not_expanded": True,
            "unserved_customers_not_allowed": True,
        },
    )


def build_preregistration() -> dict[str, Any]:
    prereg_path = OUT / "pre_registration.json"
    if prereg_path.is_file():
        e3.require_source_lock()
        return e3.read_json(prereg_path)
    gate_decision_path = OUT / "gate2_d3/decision.json"
    gate_metadata_path = OUT / "gate2_d3/metadata.json"
    gate: dict[str, Any]
    if gate_decision_path.is_file() and gate_metadata_path.is_file():
        existing_gate = e3.read_json(gate_decision_path)
        previous_hashes = e3.read_json(gate_metadata_path).get(
            "source_hashes", {}
        )
        current_hashes = e3.source_hashes()
        changed = {
            key
            for key in set(previous_hashes) | set(current_hashes)
            if previous_hashes.get(key) != current_hashes.get(key)
        }
        wrapper_key = e3.relative(Path(__file__).resolve())
        if (
            existing_gate.get("verdict")
            == "PASS_D3_MULTI_DEPOT_CURRENT_SOURCE"
            and changed <= {wrapper_key}
        ):
            gate = existing_gate
            log_event(
                "REUSED_COMPLETED_D3_AFTER_INPUT_BUILDER_ONLY_FIX",
                changed_source_keys=sorted(changed),
            )
        else:
            gate = e3.gate2_replay()
    else:
        gate = e3.gate2_replay()
    if gate["verdict"] != "PASS_D3_MULTI_DEPOT_CURRENT_SOURCE":
        raise RuntimeError("HALT_UPSTREAM_GATE2")
    eligible = [
        row["instance_id"]
        for row in e3.read_csv(OUT / "gate2_d3/eligible_multi_depot_instances.csv")
    ]
    if MAIN_INSTANCE not in eligible:
        raise RuntimeError("HALT_MAIN_EXHIBIT_NOT_IN_MULTI_DEPOT_DOMAIN")
    assignment_rows: list[dict[str, Any]] = []
    input_rows: list[dict[str, Any]] = []
    feasible_cells: set[tuple[str, int]] = set()
    for instance_id in eligible:
        base = e3.load_bundle(instance_id)
        for intensity in INTENSITIES:
            mapping, rows, map_audit = build_mapping(base, intensity)
            if map_audit["status"] != "PASS":
                if instance_id == MAIN_INSTANCE:
                    raise RuntimeError(
                        f"HALT_MAIN_EXHIBIT_INPUT:{intensity}:{map_audit}"
                    )
                _write_infeasible_input(instance_id, intensity, map_audit)
                input_rows.append(
                    {
                        "instance_id": instance_id,
                        "mismatch_intensity_nominal_pct": intensity,
                        "customer_count": len(base.customer_home_depot),
                        "reassigned_customer_count": "",
                        "actual_reassigned_pct": "",
                        "fallback_steps_beyond_second_nearest": "",
                        "responsibility_map_sha256": "",
                        "initial_solution_sha256": "",
                        "status": "INFEASIBLE_INPUT",
                        "reason": map_audit["reason"],
                    }
                )
                continue
            bundle = e3.with_responsibility(base, mapping)
            try:
                initial, initial_audit = build_common_initial_from_route_groups(
                    bundle,
                    map_audit["global_search_audit"][
                        "route_groups_by_depot"
                    ],
                )
            except Exception as exc:
                audit = {
                    **map_audit,
                    "status": "INFEASIBLE_INPUT",
                    "reason": f"COMMON_INITIAL_FAILURE:{type(exc).__name__}:{exc}",
                }
                if instance_id == MAIN_INSTANCE:
                    raise RuntimeError(
                        f"HALT_MAIN_EXHIBIT_COMMON_INITIAL:{intensity}:{audit}"
                    ) from exc
                _write_infeasible_input(instance_id, intensity, audit)
                input_rows.append(
                    {
                        "instance_id": instance_id,
                        "mismatch_intensity_nominal_pct": intensity,
                        "customer_count": len(base.customer_home_depot),
                        "reassigned_customer_count": map_audit["actual_reassigned"],
                        "actual_reassigned_pct": 100.0 * map_audit["actual_reassigned"] / len(base.customer_home_depot),
                        "fallback_steps_beyond_second_nearest": map_audit["fallback_steps_beyond_second_nearest"],
                        "responsibility_map_sha256": "",
                        "initial_solution_sha256": "",
                        "status": "INFEASIBLE_INPUT",
                        "reason": audit["reason"],
                    }
                )
                continue
            responsibility_payload = {
                "schema": "resetp.e3e6.responsibility-map.v1",
                "task_id": TASK_ID,
                "instance_id": instance_id,
                "mismatch_intensity_nominal_pct": intensity,
                "mapping": mapping,
                "mapping_sha256": e3.canonical_sha256(mapping),
                "selection_rule": "proportional largest-remainder allocation within original owner strata; frozen SHA-256 rank",
                "destination_rule": "absolute second-nearest depot by directed depot-to-customer road distance; advance to third/fourth when D2-A common-initial construction fails; never return to original owner",
                "map_audit": map_audit,
            }
            initial_payload = e3.solution_payload(initial)
            folder = input_dir(instance_id, intensity)
            folder.mkdir(parents=True, exist_ok=True)
            e3.write_json(folder / "responsibility_map.json", responsibility_payload)
            e3.write_json(folder / "initial_solution.json", initial_payload)
            e3.write_json(
                folder / "input_certificate.json",
                {
                    "schema": "resetp.e3e6.input-certificate.v1",
                    "status": "PASS",
                    "responsibility_map_sha256": e3.canonical_sha256(responsibility_payload),
                    "initial_solution_sha256": e3.canonical_sha256(initial_payload),
                    "independent_initial_audit": initial_audit,
                    "shared_by_all_seeds_and_e3_e6_arms": True,
                },
            )
            assignment_rows.extend(rows)
            feasible_cells.add((instance_id, intensity))
            input_rows.append(
                {
                    "instance_id": instance_id,
                    "mismatch_intensity_nominal_pct": intensity,
                    "customer_count": len(base.customer_home_depot),
                    "reassigned_customer_count": map_audit["actual_reassigned"],
                    "actual_reassigned_pct": 100.0 * map_audit["actual_reassigned"] / len(base.customer_home_depot),
                    "fallback_steps_beyond_second_nearest": map_audit["fallback_steps_beyond_second_nearest"],
                    "responsibility_map_sha256": e3.canonical_sha256(responsibility_payload),
                    "initial_solution_sha256": e3.canonical_sha256(initial_payload),
                    "status": "PASS",
                    "reason": "",
                }
            )
    if not assignment_rows:
        raise RuntimeError("HALT_NO_FEASIBLE_MISMATCH_ASSIGNMENTS")
    e3.write_csv(OUT / "mismatch_assignment.csv", assignment_rows)
    e3.write_csv(OUT / "input_manifest.csv", input_rows)
    assignment_sha = e3.sha256(OUT / "mismatch_assignment.csv")
    e3.write_json(
        OUT / "mismatch_assignment_hash_lock.json",
        {
            "schema": "resetp.e3e6.assignment-lock.v1",
            "sha256": assignment_sha,
            "rows": len(assignment_rows),
            "generated_before_pilot_or_formal_results": True,
            "all_seeds_share_maps": True,
            "result_dependent_adjustment_forbidden": True,
        },
    )
    task_specs: dict[str, dict[str, Any]] = {}
    for instance_id, intensity in sorted(feasible_cells):
        seeds = MAIN_SEEDS if instance_id == MAIN_INSTANCE else STABILITY_SEEDS
        for seed in seeds:
            for arm in ARMS:
                task_id = f"{instance_id}__m{intensity:02d}__seed{seed:02d}__{arm}"
                task_specs[task_id] = {
                    "task_id": task_id,
                    "instance_id": instance_id,
                    "mismatch_intensity_nominal_pct": intensity,
                    "seed": seed,
                    "arm": arm,
                    "primary_exhibit": instance_id == MAIN_INSTANCE,
                    "stability_panel": seed in STABILITY_SEEDS,
                    "e6_state_source": instance_id == MAIN_INSTANCE,
                }
    task_rows = sorted(task_specs.values(), key=lambda row: row["task_id"])
    e3.write_csv(OUT / "task_manifest.csv", task_rows)
    infeasible_cells = [row for row in input_rows if row["status"] == "INFEASIBLE_INPUT"]
    prereg = {
        "schema": "resetp.e3e6-mismatch-fairness.preregistration.v1",
        "task_id": TASK_ID,
        "user_approval": "APPROVED_BY_USER_20260729_TASK_PROMPT",
        "registered_at_utc": datetime.now(UTC).isoformat(),
        "registered_before_pilot_and_formal_cost_results": True,
        "primary_exhibit": MAIN_INSTANCE,
        "intensities_pct": list(INTENSITIES),
        "main_seeds": list(MAIN_SEEDS),
        "stability_seeds": list(STABILITY_SEEDS),
        "e3_arms": ["LOCK", "FREE"],
        "e6_states": ["I", "U", "F"],
        "e6_nested_candidate_rule": "F is the minimum-system-cost participation-feasible candidate within the U run's independently checked nested candidates plus the I fallback; candidates are not independent samples",
        "budget_pilot": {
            "result_blind": True,
            "tiers": [32, 56, 80, "160,240,..."],
            "starved_if_L_over_S_gt": 0.5,
            "arm_fails_if_starved_fraction_gt": 0.20,
            "selection": "smallest tier passing both LOCK/I and FREE/U; F inherits U because it is not a separate search",
        },
        "stability": {
            "multi_depot_instances": len(eligible),
            "cells_total": len(eligible) * len(INTENSITIES),
            "infeasible_input_cells": len(infeasible_cells),
            "infeasible_cells_retained": True,
            "no_d2a_expansion": True,
            "no_unserved_customers": True,
        },
        "mismatch_assignment_csv_sha256": assignment_sha,
        "formal_unique_task_count": len(task_rows),
        "max_workers": MAX_WORKERS,
        "source_hashes": e3.source_hashes(),
        "protected_files": [e3.relative(path) for path in e3.PROTECTED],
        "result_blind_writing": {
            "positive": "report effect size and tier trend",
            "near_zero_e3": "within this mismatch-intensity interval cross-depot cooperation adds no additional benefit",
            "near_zero_e6": "the participation guarantee does not bind under this member structure",
            "negative": "report honestly and analyse",
        },
    }
    e3.write_json(prereg_path, prereg)
    log_event(
        "PREREGISTERED",
        feasible_cells=len(feasible_cells),
        infeasible_input_cells=len(infeasible_cells),
        formal_unique_tasks=len(task_rows),
    )
    e3.write_stage_hashes(OUT / "gate2_d3")
    return prereg


def load_frozen_input(instance_id: str, intensity: int) -> tuple[Any, Solution, dict[str, Any]]:
    folder = input_dir(instance_id, intensity)
    certificate = e3.read_json(folder / "input_certificate.json")
    if certificate.get("status") != "PASS":
        raise RuntimeError(f"INFEASIBLE_INPUT:{instance_id}:{intensity}")
    responsibility = e3.read_json(folder / "responsibility_map.json")
    initial_payload = e3.read_json(folder / "initial_solution.json")
    if e3.canonical_sha256(responsibility) != certificate["responsibility_map_sha256"]:
        raise RuntimeError("HALT_RESPONSIBILITY_INPUT_HASH_DRIFT")
    if e3.canonical_sha256(initial_payload) != certificate["initial_solution_sha256"]:
        raise RuntimeError("HALT_INITIAL_INPUT_HASH_DRIFT")
    bundle = e3.with_responsibility(
        e3.load_bundle(instance_id), responsibility["mapping"]
    )
    return bundle, e3.solution_from_payload(initial_payload), certificate


def pilot_worker(args: tuple[int, int, str, int]) -> dict[str, Any]:
    budget, intensity, arm, seed = args
    e3.require_thread_lock()
    e3.require_source_lock()
    bundle, initial, certificate = load_frozen_input(MAIN_INSTANCE, intensity)
    run, wall, cpu_user, cpu_system = e3.run_search(
        bundle,
        initial,
        seed=seed,
        hard_lock=ARMS[arm],
        budget=budget,
    )
    last = int(run.stats["last_strict_improvement_evaluation"])
    total = int(run.stats["complete_candidate_evaluation_attempts"])
    fraction = last / total
    return {
        "record_type": "result_blind_budget_pilot",
        "budget": budget,
        "instance_id": MAIN_INSTANCE,
        "mismatch_intensity_nominal_pct": intensity,
        "seed": seed,
        "arm": arm,
        "last_strict_improvement_evaluation_L": last,
        "total_complete_evaluations_S": total,
        "last_improvement_fraction_L_over_S": fraction,
        "starved_L_over_S_gt_0_5": fraction > 0.5,
        "wallclock_seconds": wall,
        "cpu_user_seconds": cpu_user,
        "cpu_system_seconds": cpu_system,
        "cpu_total_seconds": cpu_user + cpu_system,
        "initial_solution_sha256": certificate["initial_solution_sha256"],
        "objective_values_recorded": False,
        "arm_cost_difference_computed": False,
        "status": "PASS",
    }


def run_pilot(workers: int) -> dict[str, Any]:
    build_preregistration()
    e3.require_thread_lock()
    e3.require_source_lock()
    if workers != MAX_WORKERS:
        raise ValueError(f"this contract requires exactly {MAX_WORKERS} workers")
    stage = OUT / "pilot"
    decision_path = stage / "decision.json"
    if decision_path.is_file():
        decision = e3.read_json(decision_path)
        if decision.get("verdict") != "PASS_RESULT_BLIND_NON_STARVED_BUDGET":
            raise RuntimeError("existing pilot is not PASS")
        return decision
    stage.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    budget = 32
    while True:
        tasks = [
            (budget, intensity, arm, seed)
            for intensity in INTENSITIES
            for seed in PILOT_SEEDS
            for arm in ARMS
        ]
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            futures = {executor.submit(pilot_worker, task): task for task in tasks}
            tier_rows = [future.result() for future in as_completed(futures)]
        tier_rows.sort(key=lambda row: (row["mismatch_intensity_nominal_pct"], row["seed"], row["arm"]))
        all_rows.extend(tier_rows)
        e3.write_csv(stage / "raw_runs.csv", all_rows)
        arm_summary: dict[str, Any] = {}
        for arm in ARMS:
            selected = [row for row in tier_rows if row["arm"] == arm]
            starved = sum(bool(row["starved_L_over_S_gt_0_5"]) for row in selected)
            fraction = starved / len(selected)
            passes = fraction <= 0.20
            arm_summary[arm] = {
                "units": len(selected),
                "starved_units": starved,
                "starved_fraction": fraction,
                "passes": passes,
            }
            summary_rows.append(
                {
                    "budget": budget,
                    "arm": arm,
                    "units": len(selected),
                    "starved_units": starved,
                    "starved_fraction": fraction,
                    "passes": passes,
                }
            )
        e3.write_csv(stage / "budget_summary.csv", summary_rows)
        e3.write_json(
            stage / "progress.json",
            {
                "latest_budget": budget,
                "arm_summary": arm_summary,
                "objective_values_recorded": False,
                "arm_cost_difference_computed": False,
            },
        )
        log_event("PILOT_TIER_COMPLETE", budget=budget, arm_summary=arm_summary)
        if all(item["passes"] for item in arm_summary.values()):
            break
        budget = {32: 56, 56: 80}.get(budget, budget + 80)
    decision = {
        "schema": "resetp.e3e6.pilot.decision.v1",
        "verdict": "PASS_RESULT_BLIND_NON_STARVED_BUDGET",
        "selected_complete_candidate_budget": budget,
        "selected_arm_summary": arm_summary,
        "tiers_run": sorted({int(row["budget"]) for row in all_rows}),
        "selection_used_only": ["L", "S", "L/S", "wallclock safety", "task completion"],
        "objective_values_recorded": False,
        "arm_cost_difference_computed": False,
        "same_budget_for_e3_and_e6": True,
        "e6_f_inherits_u_budget_without_independent_search": True,
    }
    e3.write_json(decision_path, decision)
    e3.write_json(
        stage / "metadata.json",
        {
            "schema": "resetp.e3e6.pilot.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "worker_count": workers,
            "single_thread_per_task": True,
            "source_hashes": e3.source_hashes(),
        },
    )
    (stage / "report.md").write_text(
        "# E3/E6 结果盲防饥饿 pilot\n\n"
        f"最终选择 {budget} 次完整候选评价。选择器只读取 L、S、L/S、完成和墙钟熔断状态，没有序列化任何目标值或计算臂间成本差。E6 I/U 复用 LOCK/FREE 选档；F 是 U 内嵌套筛选，没有第三条搜索轨迹。\n",
        encoding="utf-8",
    )
    e3.write_json(stage / "done.json", {"status": "complete", "verdict": decision["verdict"], "selected_budget": budget})
    e3.write_stage_hashes(stage)
    return decision


def state_audit(solution: Solution, bundle: Any) -> dict[str, Any]:
    """Independently re-score one complete state and close its economic book."""

    annotated = annotate_cross_site_services(
        solution, bundle.customer_home_depot
    )
    objective, breakdown, exact_violations = exact_china81_score(
        annotated, bundle
    )
    checker_violations = check_solution(
        annotated, bundle.instance, bundle.prices
    )
    independent = evaluate(
        annotated,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    if exact_violations or checker_violations:
        raise RuntimeError(
            "HALT_INDEPENDENT_CHECKER_VIOLATION:"
            f"exact={len(exact_violations)}:checker={len(checker_violations)}"
        )
    if not math.isclose(
        float(independent["total_cost"]),
        float(objective),
        rel_tol=1.0e-12,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("HALT_INDEPENDENT_OBJECTIVE_MISMATCH")
    customer_ids = set(bundle.customer_home_depot)
    served = [
        node_id
        for route in annotated.routes
        for node_id in route.node_sequence
        if node_id in customer_ids
    ]
    if len(served) != len(customer_ids) or set(served) != customer_ids:
        raise RuntimeError("HALT_SERVICE_COMPLETION_MISMATCH")
    profit = calculate_depot_profits(
        annotated,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        customer_home_depot=dict(bundle.customer_home_depot),
    )
    profit_rows = {
        depot_id: row.to_dict() for depot_id, row in profit.items()
    }
    revenue = sum(float(row["revenue"]) for row in profit_rows.values())
    allocated_cost = sum(
        float(row["cost_total"]) for row in profit_rows.values()
    )
    profit_sum = sum(
        float(row["profit"]) for row in profit_rows.values()
    )
    cost_residual = allocated_cost - float(objective)
    accounting_residual = profit_sum - (revenue - float(objective))
    if abs(cost_residual) > FAIRNESS_TOL or abs(accounting_residual) > FAIRNESS_TOL:
        raise RuntimeError(
            "HALT_MEMBER_SYSTEM_ACCOUNTING_NOT_CLOSED:"
            f"cost={cost_residual}:profit={accounting_residual}"
        )
    payload = e3.solution_payload(annotated)
    physical_vehicle_count = len(
        {
            physical_vehicle_id(route.vehicle_id)
            for route in annotated.routes
        }
    )
    independent_payload = {
        "objective": float(independent["total_cost"]),
        "breakdown": independent,
        "exact_violation_count": len(exact_violations),
        "checker_violation_count": len(checker_violations),
        "served_customer_count": len(served),
        "unique_served_customer_count": len(set(served)),
        "profit_sum": profit_sum,
        "revenue_sum": revenue,
        "allocated_cost_sum": allocated_cost,
        "member_system_accounting_residual": accounting_residual,
    }
    return {
        "solution": annotated,
        "solution_payload": payload,
        "solution_sha256": e3.canonical_sha256(payload),
        "objective": float(objective),
        "breakdown": breakdown,
        "independent": independent_payload,
        "independent_recompute_sha256": e3.canonical_sha256(
            independent_payload
        ),
        "profits": profit_rows,
        "profit_values": {
            depot_id: float(row["profit"])
            for depot_id, row in profit_rows.items()
        },
        "revenue_sum": revenue,
        "profit_sum": profit_sum,
        "accounting_residual": accounting_residual,
        "served_customer_count": len(served),
        "cross_site_service_count": len(annotated.cross_site_services),
        "physical_vehicle_count": physical_vehicle_count,
    }


def _candidate_completions(
    run: Any,
    initial: Solution,
) -> list[tuple[str, Solution]]:
    candidates: list[tuple[str, Solution]] = [
        ("shared_common_initial", initial),
        ("u_selected_final", run.solution),
        ("u_best_exact_parent", run.parent_completion.solution),
    ]
    for mode, epoch in sorted(run.view_epochs.items()):
        archive = (
            epoch.archive_completions
            if epoch.archive_completions
            else epoch.elite_completions
        )
        for index, completion in enumerate(archive, start=1):
            candidates.append(
                (f"u_{mode}_nested_candidate_{index:03d}", completion.solution)
            )
    return candidates


def build_fair_state(
    run: Any,
    initial: Solution,
    independent_state: dict[str, Any],
    bundle: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Select F from U's nested candidates plus the I fallback."""

    baseline_profit = independent_state["profit_values"]
    candidates = _candidate_completions(run, initial)
    candidates.append(("independent_I_fallback", independent_state["solution"]))
    unique: dict[str, dict[str, Any]] = {}
    for source, solution in candidates:
        audit = state_audit(solution, bundle)
        digest = audit["solution_sha256"]
        if digest in unique:
            unique[digest]["sources"].append(source)
            continue
        benefits = {
            depot_id: audit["profit_values"][depot_id] - baseline
            for depot_id, baseline in baseline_profit.items()
        }
        system_saving = independent_state["objective"] - audit["objective"]
        benefit_sum = sum(benefits.values())
        closure_residual = benefit_sum - system_saving
        if abs(closure_residual) > FAIRNESS_TOL:
            raise RuntimeError("HALT_MEMBER_BENEFIT_SYSTEM_SAVING_NOT_CLOSED")
        unique[digest] = {
            "sources": [source],
            "audit": audit,
            "benefits": benefits,
            "system_saving": system_saving,
            "benefit_sum": benefit_sum,
            "closure_residual": closure_residual,
            "participation_feasible": min(benefits.values()) >= -FAIRNESS_TOL,
        }
    feasible = [row for row in unique.values() if row["participation_feasible"]]
    if not feasible:
        raise RuntimeError("HALT_NO_PARTICIPATION_FEASIBLE_NESTED_CANDIDATE")
    selected = min(
        feasible,
        key=lambda row: (
            float(row["audit"]["objective"]),
            row["audit"]["solution_sha256"],
        ),
    )
    fairness_context = FairnessContext(
        depot_profit=selected["audit"]["profit_values"],
        independent_profit=baseline_profit,
        theta=1.0,
    )
    fairness_violations = check_solution(
        selected["audit"]["solution"],
        bundle.instance,
        bundle.prices,
        fairness_context=fairness_context,
        fairness_enabled=True,
    )
    if fairness_violations:
        raise RuntimeError("HALT_SELECTED_F_FAILS_INDEPENDENT_FAIRNESS_CHECK")
    pool_rows: list[dict[str, Any]] = []
    for index, row in enumerate(
        sorted(
            unique.values(),
            key=lambda item: (
                float(item["audit"]["objective"]),
                item["audit"]["solution_sha256"],
            ),
        ),
        start=1,
    ):
        pool_rows.append(
            {
                "candidate_rank_by_cost": index,
                "candidate_sources": "|".join(sorted(row["sources"])),
                "solution_sha256": row["audit"]["solution_sha256"],
                "total_cost": row["audit"]["objective"],
                "cross_site_service_count": row["audit"]["cross_site_service_count"],
                "minimum_member_benefit": min(row["benefits"].values()),
                "member_benefit_sum": row["benefit_sum"],
                "system_saving_vs_I": row["system_saving"],
                "member_system_closure_residual": row["closure_residual"],
                "participation_feasible": row["participation_feasible"],
                "selected_as_F": row is selected,
                "independent_checker_pass": True,
            }
        )
    member_rows = [
        {
            "depot_id": depot_id,
            "i_profit": baseline_profit[depot_id],
            "f_profit": selected["audit"]["profit_values"][depot_id],
            "member_benefit_F_minus_I": selected["benefits"][depot_id],
            "participation_constraint_satisfied": selected["benefits"][depot_id]
            >= -FAIRNESS_TOL,
        }
        for depot_id in sorted(baseline_profit)
    ]
    selection = {
        "nested_candidates_are_not_independent_samples": True,
        "candidate_source_scope": "U run nested exact candidates plus shared common initial and I fallback",
        "unique_candidate_count": len(unique),
        "participation_feasible_candidate_count": len(feasible),
        "selected_solution_sha256": selected["audit"]["solution_sha256"],
        "selected_sources": sorted(selected["sources"]),
        "fairness_checker_violation_count": 0,
    }
    return selected["audit"], pool_rows, member_rows, selection


def formal_worker(args: dict[str, Any]) -> dict[str, Any]:
    e3.require_thread_lock()
    hashes = e3.require_source_lock()
    budget = int(
        e3.read_json(OUT / "pilot/decision.json")[
            "selected_complete_candidate_budget"
        ]
    )
    task_id = args["task_id"]
    task_dir = OUT / "tasks" / task_id
    decision_path = task_dir / "decision.json"
    if decision_path.is_file():
        decision = e3.read_json(decision_path)
        if decision.get("verdict") != "PASS_E3E6_FORMAL_TASK":
            raise RuntimeError(f"HALT_EXISTING_TASK_NOT_PASS:{task_id}")
        if e3.read_json(task_dir / "metadata.json")["source_hashes"] != hashes:
            raise RuntimeError(f"HALT_TASK_SOURCE_HASH_DRIFT:{task_id}")
        return decision["raw_row"]
    if task_dir.exists():
        raise RuntimeError(f"HALT_INCOMPLETE_TASK_DIRECTORY:{task_id}")
    bundle, initial, input_certificate = load_frozen_input(
        args["instance_id"], int(args["mismatch_intensity_nominal_pct"])
    )
    hard_lock = ARMS[args["arm"]]
    run, wall, cpu_user, cpu_system = e3.run_search(
        bundle,
        initial,
        seed=int(args["seed"]),
        hard_lock=hard_lock,
        budget=budget,
    )
    audit = state_audit(run.solution, bundle)
    if hard_lock and audit["cross_site_service_count"]:
        raise RuntimeError(f"HALT_LOCK_CROSS_SITE_CERTIFICATE:{task_id}")
    row = {
        "record_type": "formal_run",
        "task_id": task_id,
        "instance_id": args["instance_id"],
        "region": bundle.region,
        "customer_count": len(bundle.customer_home_depot),
        "mismatch_intensity_nominal_pct": int(args["mismatch_intensity_nominal_pct"]),
        "seed": int(args["seed"]),
        "arm": args["arm"],
        "hard_home_depot_lock": hard_lock,
        "primary_exhibit": bool(args["primary_exhibit"]),
        "stability_panel": bool(args["stability_panel"]),
        "complete_candidate_budget": budget,
        "complete_candidate_attempts": int(run.stats["complete_candidate_evaluation_attempts"]),
        "last_strict_improvement_evaluation_L": int(run.stats["last_strict_improvement_evaluation"]),
        "total_complete_evaluations_S": int(run.stats["complete_candidate_evaluation_attempts"]),
        "last_improvement_fraction_L_over_S": float(run.stats["last_strict_improvement_fraction"]),
        "wallclock_seconds": wall,
        "cpu_user_seconds": cpu_user,
        "cpu_system_seconds": cpu_system,
        "cpu_total_seconds": cpu_user + cpu_system,
        "total_cost": audit["objective"],
        "cross_site_service_count": audit["cross_site_service_count"],
        "service_completion_rate_pct": 100.0,
        "total_emissions_kg": float(audit["breakdown"]["E_total"]),
        "minimum_physical_vehicle_count": audit["physical_vehicle_count"],
        "route_count": len(audit["solution"].routes),
        "violation_count": 0,
        "initial_solution_sha256": input_certificate["initial_solution_sha256"],
        "responsibility_map_sha256": input_certificate["responsibility_map_sha256"],
        "solution_sha256": audit["solution_sha256"],
        "independent_recompute_sha256": audit["independent_recompute_sha256"],
        "member_system_accounting_residual": audit["accounting_residual"],
        "source_hash": e3.canonical_sha256(hashes),
        "status": "PASS",
    }
    certificate: dict[str, Any] = {
        "schema": "resetp.e3e6.task-certificate.v1",
        "task_id": task_id,
        "source_hashes": hashes,
        "input_certificate": input_certificate,
        "run_stats": run.stats,
        "independent_recompute": audit["independent"],
        "depot_profit_accounting": audit["profits"],
        "raw_row": row,
    }
    fair_audit: dict[str, Any] | None = None
    pool_rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    if bool(args["primary_exhibit"]) and args["arm"] == "FREE":
        lock_task_id = task_id.rsplit("__", 1)[0] + "__LOCK"
        lock_dir = OUT / "tasks" / lock_task_id
        if not (lock_dir / "decision.json").is_file():
            raise RuntimeError(f"HALT_E6_I_STATE_NOT_READY:{lock_task_id}")
        lock_solution = e3.solution_from_payload(
            e3.read_json(lock_dir / "solution_witness.json")
        )
        independent_state = state_audit(lock_solution, bundle)
        fair_audit, pool_rows, member_rows, selection = build_fair_state(
            run, initial, independent_state, bundle
        )
        u_benefits = {
            depot_id: audit["profit_values"][depot_id] - independent_state["profit_values"][depot_id]
            for depot_id in independent_state["profit_values"]
        }
        u_system_saving = independent_state["objective"] - audit["objective"]
        u_closure = sum(u_benefits.values()) - u_system_saving
        f_system_saving = independent_state["objective"] - fair_audit["objective"]
        f_benefits = {
            row_item["depot_id"]: row_item["member_benefit_F_minus_I"]
            for row_item in member_rows
        }
        f_closure = sum(f_benefits.values()) - f_system_saving
        if abs(u_closure) > FAIRNESS_TOL or abs(f_closure) > FAIRNESS_TOL:
            raise RuntimeError("HALT_E6_MEMBER_SYSTEM_CLOSURE")
        certificate["e6"] = {
            "states": {
                "I": {
                    "total_cost": independent_state["objective"],
                    "profit": independent_state["profit_values"],
                    "solution_sha256": independent_state["solution_sha256"],
                },
                "U": {
                    "total_cost": audit["objective"],
                    "profit": audit["profit_values"],
                    "member_benefit_vs_I": u_benefits,
                    "minimum_member_benefit": min(u_benefits.values()),
                    "system_saving_vs_I": u_system_saving,
                    "member_system_closure_residual": u_closure,
                    "participation_constraint_would_bind": min(u_benefits.values()) < -FAIRNESS_TOL,
                    "solution_sha256": audit["solution_sha256"],
                },
                "F": {
                    "total_cost": fair_audit["objective"],
                    "profit": fair_audit["profit_values"],
                    "member_benefit_vs_I": f_benefits,
                    "minimum_member_benefit": min(f_benefits.values()),
                    "system_saving_vs_I": f_system_saving,
                    "member_system_closure_residual": f_closure,
                    "fairness_premium_cost_F_minus_U": fair_audit["objective"] - audit["objective"],
                    "fairness_premium_pct_of_U_cost": 100.0 * (fair_audit["objective"] - audit["objective"]) / audit["objective"],
                    "solution_sha256": fair_audit["solution_sha256"],
                },
            },
            "participation_activation": min(u_benefits.values()) < -FAIRNESS_TOL,
            "nested_candidate_selection": selection,
        }
    tmp_dir = OUT / "tasks" / f".{task_id}.tmp-{os.getpid()}"
    if tmp_dir.exists():
        raise RuntimeError(f"HALT_TASK_TEMP_DIRECTORY_EXISTS:{tmp_dir.name}")
    tmp_dir.mkdir(parents=True)
    e3.write_json(tmp_dir / "solution_witness.json", audit["solution_payload"])
    if fair_audit is not None:
        e3.write_json(tmp_dir / "fair_solution_witness.json", fair_audit["solution_payload"])
        e3.write_csv(tmp_dir / "candidate_pool.csv", pool_rows)
        e3.write_csv(tmp_dir / "member_economics.csv", member_rows)
    e3.write_json(tmp_dir / "certificate.json", certificate)
    e3.write_csv(tmp_dir / "raw_runs.csv", [row])
    e3.write_json(
        tmp_dir / "metadata.json",
        {
            "schema": "resetp.e3e6.task-metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "source_hashes": hashes,
            "single_thread": True,
        },
    )
    decision = {
        "schema": "resetp.e3e6.task-decision.v1",
        "verdict": "PASS_E3E6_FORMAL_TASK",
        "raw_row": row,
    }
    e3.write_json(tmp_dir / "decision.json", decision)
    e3.write_stage_hashes(tmp_dir)
    os.replace(tmp_dir, task_dir)
    return row


def completed_formal_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tasks_root = OUT / "tasks"
    if not tasks_root.is_dir():
        return rows
    for decision_path in sorted(tasks_root.glob("*/decision.json")):
        decision = e3.read_json(decision_path)
        if decision.get("verdict") != "PASS_E3E6_FORMAL_TASK":
            raise RuntimeError(f"HALT_NONPASS_TASK:{decision_path.parent.name}")
        rows.append(decision["raw_row"])
    return rows


def _typed_task_rows() -> list[dict[str, Any]]:
    rows = e3.read_csv(OUT / "task_manifest.csv")
    for row in rows:
        row["mismatch_intensity_nominal_pct"] = int(row["mismatch_intensity_nominal_pct"])
        row["seed"] = int(row["seed"])
        row["primary_exhibit"] = row["primary_exhibit"] == "True"
        row["stability_panel"] = row["stability_panel"] == "True"
    return rows


def run_formal(workers: int) -> None:
    build_preregistration()
    pilot = run_pilot(workers)
    e3.require_thread_lock()
    e3.require_source_lock()
    if workers != MAX_WORKERS:
        raise ValueError(f"this contract requires exactly {MAX_WORKERS} workers")
    task_rows = _typed_task_rows()
    existing = {row["task_id"]: row for row in completed_formal_rows()}
    pending = [row for row in task_rows if row["task_id"] not in existing]
    phases = (
        ("primary_LOCK", [row for row in pending if row["primary_exhibit"] and row["arm"] == "LOCK"]),
        ("primary_FREE_and_E6", [row for row in pending if row["primary_exhibit"] and row["arm"] == "FREE"]),
        ("stability_LOCK", [row for row in pending if not row["primary_exhibit"] and row["arm"] == "LOCK"]),
        ("stability_FREE", [row for row in pending if not row["primary_exhibit"] and row["arm"] == "FREE"]),
    )
    total = len(task_rows)
    context = mp.get_context("spawn")
    for phase, phase_rows in phases:
        phase_rows.sort(key=lambda row: row["task_id"])
        if not phase_rows:
            continue
        if phase == "primary_FREE_and_E6":
            lock_count = sum(
                row["primary_exhibit"] and row["arm"] == "LOCK"
                for row in existing.values()
            )
            if lock_count != len(INTENSITIES) * len(MAIN_SEEDS):
                raise RuntimeError("HALT_E6_BEFORE_ALL_I_STATES_COMPLETE")
        e3.write_json(
            OUT / "progress.json",
            {
                "status": "RUNNING",
                "phase": phase,
                "completed_unique_tasks": len(existing),
                "total_unique_tasks": total,
                "remaining_unique_tasks": total - len(existing),
                "selected_complete_candidate_budget": pilot["selected_complete_candidate_budget"],
            },
        )
        log_event("FORMAL_PHASE_START", phase=phase, tasks=len(phase_rows))
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            futures = {
                executor.submit(formal_worker, row): row
                for row in phase_rows
            }
            for future in as_completed(futures):
                row = future.result()
                existing[row["task_id"]] = row
                current = sorted(existing.values(), key=lambda item: item["task_id"])
                e3.write_csv(OUT / "raw_runs.csv", current)
                e3.write_json(
                    OUT / "progress.json",
                    {
                        "status": "RUNNING",
                        "phase": phase,
                        "completed_unique_tasks": len(current),
                        "total_unique_tasks": total,
                        "remaining_unique_tasks": total - len(current),
                        "primary_exhibit_completed": sum(bool(item["primary_exhibit"]) for item in current),
                        "primary_exhibit_total": len(INTENSITIES) * len(MAIN_SEEDS) * 2,
                    },
                )
        log_event("FORMAL_PHASE_COMPLETE", phase=phase)
    finalize()


def classify_effect(value: float) -> str:
    displayed = round(float(value), DISPLAY_DIGITS)
    if displayed > 0:
        return "POSITIVE"
    if displayed < 0:
        return "NEGATIVE"
    return "NEAR_ZERO"


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean of empty collection")
    return sum(values) / len(values)


def pair_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        key = (row["instance_id"], int(row["mismatch_intensity_nominal_pct"]), int(row["seed"]))
        grouped.setdefault(key, {})[row["arm"]] = row
    paired: list[dict[str, Any]] = []
    for (instance_id, intensity, seed), arms in sorted(grouped.items()):
        if set(arms) != set(ARMS):
            raise RuntimeError(f"HALT_MISSING_E3_PAIR:{instance_id}:{intensity}:{seed}")
        lock, free = arms["LOCK"], arms["FREE"]
        relative = 100.0 * (float(free["total_cost"]) - float(lock["total_cost"])) / float(lock["total_cost"])
        reduction = -relative
        paired.append(
            {
                "instance_id": instance_id,
                "region": lock["region"],
                "customer_count": int(lock["customer_count"]),
                "mismatch_intensity_nominal_pct": intensity,
                "seed": seed,
                "primary_exhibit": bool(lock["primary_exhibit"]),
                "stability_panel": bool(lock["stability_panel"]),
                "lock_total_cost": float(lock["total_cost"]),
                "free_total_cost": float(free["total_cost"]),
                "free_relative_to_lock_cost_pct": relative,
                "cost_reduction_pct_positive_is_benefit": reduction,
                "effect_direction": classify_effect(reduction),
                "lock_cross_site_service_count": int(lock["cross_site_service_count"]),
                "free_cross_site_service_count": int(free["cross_site_service_count"]),
                "lock_service_completion_rate_pct": float(lock["service_completion_rate_pct"]),
                "free_service_completion_rate_pct": float(free["service_completion_rate_pct"]),
                "lock_total_emissions_kg": float(lock["total_emissions_kg"]),
                "free_total_emissions_kg": float(free["total_emissions_kg"]),
                "lock_minimum_physical_vehicle_count": int(lock["minimum_physical_vehicle_count"]),
                "free_minimum_physical_vehicle_count": int(free["minimum_physical_vehicle_count"]),
                "status": "PASS",
            }
        )
    return paired


def _load_e6_rows(main_pairs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    state_rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    for pair in sorted(main_pairs, key=lambda row: (row["mismatch_intensity_nominal_pct"], row["seed"])):
        prefix = f"{pair['instance_id']}__m{int(pair['mismatch_intensity_nominal_pct']):02d}__seed{int(pair['seed']):02d}"
        certificate = e3.read_json(OUT / "tasks" / f"{prefix}__FREE" / "certificate.json")
        e6 = certificate["e6"]
        states = e6["states"]
        for state_name in ("I", "U", "F"):
            state = states[state_name]
            state_rows.append(
                {
                    "instance_id": pair["instance_id"],
                    "mismatch_intensity_nominal_pct": pair["mismatch_intensity_nominal_pct"],
                    "seed": pair["seed"],
                    "state": state_name,
                    "total_cost": state["total_cost"],
                    "system_saving_vs_I": 0.0 if state_name == "I" else state["system_saving_vs_I"],
                    "minimum_member_benefit": 0.0 if state_name == "I" else state["minimum_member_benefit"],
                    "participation_activation": e6["participation_activation"],
                    "fairness_premium_cost_F_minus_U": states["F"]["fairness_premium_cost_F_minus_U"] if state_name == "F" else "",
                    "fairness_premium_pct_of_U_cost": states["F"]["fairness_premium_pct_of_U_cost"] if state_name == "F" else "",
                    "member_system_closure_residual": 0.0 if state_name == "I" else state["member_system_closure_residual"],
                    "solution_sha256": state["solution_sha256"],
                    "nested_candidates_are_not_independent_samples": True,
                    "status": "PASS",
                }
            )
        depot_ids = sorted(states["I"]["profit"])
        for depot_id in depot_ids:
            i_profit = float(states["I"]["profit"][depot_id])
            for state_name in ("I", "U", "F"):
                value = float(states[state_name]["profit"][depot_id])
                member_rows.append(
                    {
                        "instance_id": pair["instance_id"],
                        "mismatch_intensity_nominal_pct": pair["mismatch_intensity_nominal_pct"],
                        "seed": pair["seed"],
                        "depot_id": depot_id,
                        "state": state_name,
                        "profit": value,
                        "benefit_vs_I": value - i_profit,
                        "participation_constraint_satisfied": value - i_profit >= -FAIRNESS_TOL,
                    }
                )
    return state_rows, member_rows


def _write_figures(main_summary: list[dict[str, Any]], e6_summary: list[dict[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures = OUT / "figures"
    figures.mkdir(exist_ok=True)
    x = [int(row["mismatch_intensity_nominal_pct"]) for row in main_summary]
    y = [float(row["mean_cost_reduction_pct_positive_is_benefit"]) for row in main_summary]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.plot(x, y, marker="o", color="#1f77b4")
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set(xlabel="Mismatch intensity (%)", ylabel="FREE cost reduction vs LOCK (%)", title="E3 primary exhibit")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(figures / "e3_main_effect.png", dpi=180)
    plt.close(fig)
    premium = [float(row["mean_fairness_premium_pct_of_U_cost"]) for row in e6_summary]
    activation = [100.0 * float(row["participation_activation_rate"]) for row in e6_summary]
    fig, ax1 = plt.subplots(figsize=(6.4, 4.0))
    ax1.bar(x, premium, width=8, color="#ff7f0e", alpha=0.75)
    ax1.set(xlabel="Mismatch intensity (%)", ylabel="F fairness premium vs U (%)", title="E6 participation guarantee")
    ax2 = ax1.twinx()
    ax2.plot(x, activation, marker="o", color="#2ca02c")
    ax2.set_ylabel("Participation activation rate (%)")
    fig.tight_layout()
    fig.savefig(figures / "e6_fairness.png", dpi=180)
    plt.close(fig)


def finalize() -> dict[str, Any]:
    prereg = build_preregistration()
    hashes = e3.require_source_lock()
    manifest = e3.read_csv(OUT / "task_manifest.csv")
    rows = completed_formal_rows()
    if len(rows) != len(manifest):
        raise RuntimeError(f"HALT_FORMAL_INCOMPLETE:{len(rows)}/{len(manifest)}")
    rows.sort(key=lambda row: row["task_id"])
    e3.write_csv(OUT / "raw_runs.csv", rows)
    paired = pair_rows(rows)
    e3.write_csv(OUT / "paired_results.csv", paired)
    main_pairs = [row for row in paired if row["primary_exhibit"]]
    main_summary: list[dict[str, Any]] = []
    for intensity in INTENSITIES:
        selected = [row for row in main_pairs if int(row["mismatch_intensity_nominal_pct"]) == intensity]
        if len(selected) != len(MAIN_SEEDS):
            raise RuntimeError(f"HALT_MAIN_PAIR_COUNT:{intensity}:{len(selected)}")
        reductions = [float(row["cost_reduction_pct_positive_is_benefit"]) for row in selected]
        main_summary.append(
            {
                "mismatch_intensity_nominal_pct": intensity,
                "paired_seeds": len(selected),
                "mean_lock_total_cost": mean([float(row["lock_total_cost"]) for row in selected]),
                "mean_free_total_cost": mean([float(row["free_total_cost"]) for row in selected]),
                "mean_free_relative_to_lock_cost_pct": mean([float(row["free_relative_to_lock_cost_pct"]) for row in selected]),
                "mean_cost_reduction_pct_positive_is_benefit": mean(reductions),
                "effect_direction": classify_effect(mean(reductions)),
                "mean_lock_cross_site_service_count": mean([float(row["lock_cross_site_service_count"]) for row in selected]),
                "mean_free_cross_site_service_count": mean([float(row["free_cross_site_service_count"]) for row in selected]),
                "service_completion_rate_pct_both_arms": 100.0,
                "mean_lock_total_emissions_kg": mean([float(row["lock_total_emissions_kg"]) for row in selected]),
                "mean_free_total_emissions_kg": mean([float(row["free_total_emissions_kg"]) for row in selected]),
                "mean_lock_minimum_physical_vehicle_count": mean([float(row["lock_minimum_physical_vehicle_count"]) for row in selected]),
                "mean_free_minimum_physical_vehicle_count": mean([float(row["free_minimum_physical_vehicle_count"]) for row in selected]),
            }
        )
    e3.write_csv(OUT / "main_exhibit_summary.csv", main_summary)
    input_manifest = e3.read_csv(OUT / "input_manifest.csv")
    infeasible_inputs = [row for row in input_manifest if row["status"] == "INFEASIBLE_INPUT"]
    stability_groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in paired:
        if row["stability_panel"]:
            stability_groups.setdefault((row["instance_id"], int(row["mismatch_intensity_nominal_pct"])), []).append(row)
    main_direction = {int(row["mismatch_intensity_nominal_pct"]): row["effect_direction"] for row in main_summary}
    stability_cells: list[dict[str, Any]] = []
    for input_row in input_manifest:
        key = (input_row["instance_id"], int(input_row["mismatch_intensity_nominal_pct"]))
        if input_row["status"] == "INFEASIBLE_INPUT":
            stability_cells.append(
                {
                    "instance_id": key[0],
                    "mismatch_intensity_nominal_pct": key[1],
                    "paired_seeds": 0,
                    "mean_cost_reduction_pct_positive_is_benefit": "",
                    "effect_direction": "INFEASIBLE_INPUT",
                    "matches_main_exhibit_direction": "",
                    "status": "INFEASIBLE_INPUT",
                    "reason": input_row["reason"],
                }
            )
            continue
        selected = stability_groups.get(key, [])
        if len(selected) != len(STABILITY_SEEDS):
            raise RuntimeError(f"HALT_STABILITY_SEED_COUNT:{key}:{len(selected)}")
        reduction = mean([float(row["cost_reduction_pct_positive_is_benefit"]) for row in selected])
        direction = classify_effect(reduction)
        stability_cells.append(
            {
                "instance_id": key[0],
                "mismatch_intensity_nominal_pct": key[1],
                "paired_seeds": len(selected),
                "mean_cost_reduction_pct_positive_is_benefit": reduction,
                "effect_direction": direction,
                "matches_main_exhibit_direction": direction == main_direction[key[1]],
                "status": "PASS",
                "reason": "",
            }
        )
    e3.write_csv(OUT / "stability_direction_cells.csv", stability_cells)
    stability_summary: list[dict[str, Any]] = []
    for intensity in INTENSITIES:
        selected = [row for row in stability_cells if int(row["mismatch_intensity_nominal_pct"]) == intensity]
        feasible = [row for row in selected if row["status"] == "PASS"]
        stability_summary.append(
            {
                "mismatch_intensity_nominal_pct": intensity,
                "registered_multi_depot_cells": len(selected),
                "feasible_cells": len(feasible),
                "infeasible_input_cells": len(selected) - len(feasible),
                "main_exhibit_direction": main_direction[intensity],
                "positive_cells": sum(row["effect_direction"] == "POSITIVE" for row in feasible),
                "near_zero_cells": sum(row["effect_direction"] == "NEAR_ZERO" for row in feasible),
                "negative_cells": sum(row["effect_direction"] == "NEGATIVE" for row in feasible),
                "direction_matches_main_count": sum(row["matches_main_exhibit_direction"] is True for row in feasible),
                "reporting_scope": "DIRECTION_CONSISTENCY_ONLY",
            }
        )
    e3.write_csv(OUT / "stability_direction_summary.csv", stability_summary)
    e6_states, e6_members = _load_e6_rows(main_pairs)
    e3.write_csv(OUT / "e6_states.csv", e6_states)
    e3.write_csv(OUT / "e6_member_economics.csv", e6_members)
    e6_summary: list[dict[str, Any]] = []
    for intensity in INTENSITIES:
        f_rows = [row for row in e6_states if int(row["mismatch_intensity_nominal_pct"]) == intensity and row["state"] == "F"]
        u_rows = [row for row in e6_states if int(row["mismatch_intensity_nominal_pct"]) == intensity and row["state"] == "U"]
        e6_summary.append(
            {
                "mismatch_intensity_nominal_pct": intensity,
                "seeds": len(f_rows),
                "participation_activation_rate": mean([1.0 if row["participation_activation"] else 0.0 for row in f_rows]),
                "mean_U_minimum_member_benefit": mean([float(row["minimum_member_benefit"]) for row in u_rows]),
                "worst_U_minimum_member_benefit": min(float(row["minimum_member_benefit"]) for row in u_rows),
                "mean_F_minimum_member_benefit": mean([float(row["minimum_member_benefit"]) for row in f_rows]),
                "worst_F_minimum_member_benefit": min(float(row["minimum_member_benefit"]) for row in f_rows),
                "mean_U_system_saving_vs_I": mean([float(row["system_saving_vs_I"]) for row in u_rows]),
                "mean_F_system_saving_vs_I": mean([float(row["system_saving_vs_I"]) for row in f_rows]),
                "mean_fairness_premium_cost_F_minus_U": mean([float(row["fairness_premium_cost_F_minus_U"]) for row in f_rows]),
                "mean_fairness_premium_pct_of_U_cost": mean([float(row["fairness_premium_pct_of_U_cost"]) for row in f_rows]),
                "max_abs_member_system_closure_residual": max(abs(float(row["member_system_closure_residual"])) for row in f_rows + u_rows),
                "nested_candidates_are_not_independent_samples": True,
            }
        )
    e3.write_csv(OUT / "e6_summary.csv", e6_summary)
    verification_rows: list[dict[str, Any]] = []
    for row in rows:
        verification_rows.append(
            {
                "task_id": row["task_id"],
                "state": "I" if row["arm"] == "LOCK" and row["primary_exhibit"] else ("U" if row["arm"] == "FREE" and row["primary_exhibit"] else row["arm"]),
                "solution_sha256": row["solution_sha256"],
                "independent_recompute_sha256": row["independent_recompute_sha256"],
                "objective_matches": True,
                "violation_count": int(row["violation_count"]),
                "member_system_accounting_residual": row["member_system_accounting_residual"],
                "status": "PASS",
            }
        )
    for state in e6_states:
        if state["state"] == "F":
            verification_rows.append(
                {
                    "task_id": f"{state['instance_id']}__m{int(state['mismatch_intensity_nominal_pct']):02d}__seed{int(state['seed']):02d}__F",
                    "state": "F",
                    "solution_sha256": state["solution_sha256"],
                    "independent_recompute_sha256": "RECORDED_IN_FREE_TASK_CERTIFICATE",
                    "objective_matches": True,
                    "violation_count": 0,
                    "member_system_accounting_residual": state["member_system_closure_residual"],
                    "status": "PASS",
                }
            )
    e3.write_csv(OUT / "independent_verification.csv", verification_rows)
    _write_figures(main_summary, e6_summary)
    overall_reduction = mean([float(row["cost_reduction_pct_positive_is_benefit"]) for row in main_pairs])
    overall_direction = classify_effect(overall_reduction)
    e6_overall_premium = mean([float(row["fairness_premium_pct_of_U_cost"]) for row in e6_states if row["state"] == "F"])
    e6_direction = classify_effect(e6_overall_premium)
    decision = {
        "schema": "resetp.e3e6.decision.v1",
        "task_id": TASK_ID,
        "verdict": f"PASS_COMPLETE_E3_{overall_direction}_E6_PREMIUM_{e6_direction}",
        "selected_complete_candidate_budget": e3.read_json(OUT / "pilot/decision.json")["selected_complete_candidate_budget"],
        "formal_unique_tasks": len(rows),
        "primary_exhibit_pairs": len(main_pairs),
        "stability_registered_cells": len(stability_cells),
        "stability_infeasible_input_cells": len(infeasible_inputs),
        "overall_primary_exhibit_cost_reduction_pct": overall_reduction,
        "overall_fairness_premium_pct_of_U_cost": e6_overall_premium,
        "all_solutions_independently_recomputed": True,
        "all_violation_counts_zero": all(int(row["violation_count"]) == 0 for row in verification_rows),
        "member_system_economics_closed": all(abs(float(row["member_system_accounting_residual"])) <= FAIRNESS_TOL for row in verification_rows),
        "no_rows_deleted": True,
        "no_subset_selected_by_result": True,
        "nested_candidates_are_not_independent_samples": True,
        "protected_file_hashes": {e3.relative(path): e3.sha256(path) for path in e3.PROTECTED},
        "statistical_tests": "NONE_DESCRIPTIVE_ONLY",
    }
    e3.write_json(OUT / "decision.json", decision)
    e3.write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.e3e6.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "source_hashes": hashes,
            "mismatch_assignment_csv_sha256": prereg["mismatch_assignment_csv_sha256"],
            "worker_limit": MAX_WORKERS,
            "single_thread_per_task": True,
            "wallclock_role": "SAFETY_FUSE_ONLY",
            "scientific_terminal_files": ["done.json", "metadata.json", "raw_runs.csv", "decision.json", "artifact_hashes.json", "report.md"],
        },
    )
    pilot_decision = e3.read_json(OUT / "pilot/decision.json")
    pilot_summary = e3.read_csv(OUT / "pilot/budget_summary.csv")
    lines = [
        "# E3/E6 责任错配、公平参与与跨场协同正式实验",
        "",
        f"**结论：{decision['verdict']}。** 主展品固定为 `{MAIN_INSTANCE}`；正式批次共完成 {len(rows)} 条唯一搜索任务，未删除结果或按结果挑选子集。",
        "",
        "## 结果盲 pilot 与评价预算",
        "",
        "pilot 未序列化目标值，也未计算臂间成本差；只读取 L、S、L/S、完成状态和墙钟熔断状态。逐档判定如下：",
        "",
        "|预算|臂|单元数|L/S>0.5 单元|占比|通过|",
        "|---:|:--:|---:|---:|---:|:--:|",
    ]
    for row in pilot_summary:
        lines.append(f"|{row['budget']}|{row['arm']}|{row['units']}|{row['starved_units']}|{100.0 * float(row['starved_fraction']):.2f}%|{row['passes']}|")
    lines.extend([
        "",
        f"按预注册规则采用满足判据的最小共同档位 **{pilot_decision['selected_complete_candidate_budget']} 次完整候选评价**；E6 的 F 为 U 内嵌套筛选，不另占搜索预算。",
        "",
        "## E3 主展品",
        "",
        "主要终点为 FREE 相对 LOCK 的成本变化；下表用正值表示 FREE 降本。服务完成率两臂均为 100%。",
        "",
        "|错配强度|LOCK均值成本|FREE均值成本|FREE降本|FREE跨场客户|LOCK/FREE排放(kg)|LOCK/FREE最少车辆|方向|",
        "|---:|---:|---:|---:|---:|---:|---:|:--:|",
    ])
    for row in main_summary:
        lines.append(
            f"|{row['mismatch_intensity_nominal_pct']}%|{row['mean_lock_total_cost']:.3f}|{row['mean_free_total_cost']:.3f}|{row['mean_cost_reduction_pct_positive_is_benefit']:.4f}%|{row['mean_free_cross_site_service_count']:.2f}|{row['mean_lock_total_emissions_kg']:.3f}/{row['mean_free_total_emissions_kg']:.3f}|{row['mean_lock_minimum_physical_vehicle_count']:.2f}/{row['mean_free_minimum_physical_vehicle_count']:.2f}|{row['effect_direction']}|"
        )
    lines.extend(["", "## E6 三状态与参与保障", "", "I=独立经营（LOCK），U=无保障协同（FREE），F=从同一 U 运行的嵌套候选加 I 回退中选择的最低成本参与可行解。嵌套候选不是独立样本。", "", "|错配强度|参与激活率|U最低成员收益均值/最差|F最低成员收益均值/最差|U系统节省|F系统节省|公平溢价(F-U)|", "|---:|---:|---:|---:|---:|---:|---:|"])
    for row in e6_summary:
        lines.append(
            f"|{row['mismatch_intensity_nominal_pct']}%|{100.0 * row['participation_activation_rate']:.2f}%|{row['mean_U_minimum_member_benefit']:.3f}/{row['worst_U_minimum_member_benefit']:.3f}|{row['mean_F_minimum_member_benefit']:.3f}/{row['worst_F_minimum_member_benefit']:.3f}|{row['mean_U_system_saving_vs_I']:.3f}|{row['mean_F_system_saving_vs_I']:.3f}|{row['mean_fairness_premium_cost_F_minus_U']:.3f} ({row['mean_fairness_premium_pct_of_U_cost']:.4f}%)|"
        )
    lines.extend(["", f"成员收益之和与系统节省逐种子闭合；最大绝对残差为 {max(float(row['max_abs_member_system_closure_residual']) for row in e6_summary):.3e}。逐成员账见 `e6_member_economics.csv`，逐状态账见 `e6_states.csv`。"])
    if e6_direction == "NEAR_ZERO":
        lines.append("按跑前有效区间边界写法：参与保障在该成员结构下不绑定。")
    elif e6_direction == "NEGATIVE":
        lines.append("F 的系统成本低于 U；这是如实保留的负向公平溢价，并不把嵌套候选当作独立重复。")
    else:
        lines.append("参与保障产生正向系统成本代价；效应量按固定口径完整报告。")
    lines.extend(["", "## 稳定性面板与输入不可行", "", f"稳定性面板预注册 {len(stability_cells)} 个实例—档位单元，其中 {len(infeasible_inputs)} 个登记为 `INFEASIBLE_INPUT`；这些单元保留在 `stability_direction_cells.csv`，未扩大 D2-A 上限、未允许未服务客户、未挑选可行子集。其余单元每格使用种子 1--3，仅作方向一致性描述。", "", "## 独立复算", "", f"`independent_verification.csv` 共 {len(verification_rows)} 行，全部由独立检查器复算，目标一致、违约数为 0，成员经济账闭合。受保护文件哈希记录于 `decision.json`，本任务没有修改它们。", "", "## 结果盲预登记结论", ""])
    if overall_direction == "NEAR_ZERO":
        lines.append("在该错配强度区间内跨场协同无额外收益；三档、全部种子和稳定性单元均完整保留。")
    elif overall_direction == "NEGATIVE":
        lines.append("FREE 的主终点为负向结果；本报告如实保留，并结合跨场服务、排放和车辆数描述权衡。")
    else:
        lines.append("FREE 的主终点为正向结果；效应量与 0%/25%/50% 分档趋势均按固定口径报告。")
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    e3.write_json(OUT / "progress.json", {"status": "COMPLETE", "completed_unique_tasks": len(rows), "total_unique_tasks": len(rows), "remaining_unique_tasks": 0})
    done_payload = {
        "schema": "resetp.e3e6.done.v1",
        "status": "complete",
        "verdict": decision["verdict"],
        "formal_unique_tasks": len(rows),
        "scientific_terminal": True,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    tmp_done = OUT / "done.json.tmp"
    e3.write_json(tmp_done, done_payload)
    e3.write_stage_hashes(OUT)
    artifact_manifest = e3.read_json(OUT / "artifact_hashes.json")
    artifact_manifest["artifacts"]["done.json"] = e3.sha256(tmp_done)
    artifact_manifest["artifacts"] = dict(sorted(artifact_manifest["artifacts"].items()))
    e3.write_json(OUT / "artifact_hashes.json", artifact_manifest)
    os.replace(tmp_done, OUT / "done.json")
    log_event("SCIENTIFIC_TERMINAL", verdict=decision["verdict"], tasks=len(rows))
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preregister")
    pilot_parser = subparsers.add_parser("pilot")
    pilot_parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    formal_parser = subparsers.add_parser("formal")
    formal_parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    subparsers.add_parser("finalize")
    args = parser.parse_args()
    if args.command == "preregister":
        result = build_preregistration()
    elif args.command == "pilot":
        result = run_pilot(args.workers)
    elif args.command == "formal":
        run_formal(args.workers)
        result = e3.read_json(OUT / "decision.json")
    elif args.command == "finalize":
        result = finalize()
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
