#!/usr/bin/env python3
"""Forced one-trigger behaviour probe for MPILS-MVNS-C2-R1."""

from __future__ import annotations

from dataclasses import replace
import inspect
import json
import math
from typing import Any

import pyvrp
from pyvrp import (
    Model,
    PenaltyManager,
    RandomNumberGenerator,
    Route,
    Solution,
    SolveParams,
)
from pyvrp.search import PerturbationParams
from pyvrp.stop import MaxIterations

from c2_core import (
    BoundedCrossDepotSegmentOperator,
    C2EventController,
    MECHANISM_ORDER,
    NOT_APPLICABLE,
    MechanismContext,
    ReplacementSearchMethod,
    canonical_signature,
)
from event_driven_ils import EventDrivenIteratedLocalSearch
from run_g0_worker import build_local_search, route_payload


def make_fixture() -> pyvrp.ProblemData:
    model = Model()
    depots = [
        model.add_depot(0, 0, name="D0"),
        model.add_depot(100, 0, name="D1"),
    ]
    coordinates = [(5, 0), (95, 0), (94, 2), (96, -2)]
    clients = [
        model.add_client(
            x,
            y,
            delivery=1,
            tw_early=0,
            tw_late=10_000,
            name=f"C{index}",
        )
        for index, (x, y) in enumerate(coordinates)
    ]
    for depot in depots:
        model.add_vehicle_type(
            num_available=3,
            capacity=5,
            start_depot=depot,
            end_depot=depot,
        )
    locations = [*depots, *clients]
    for source in locations:
        for target in locations:
            distance = int(
                round(
                    math.hypot(
                        float(source.x - target.x),
                        float(source.y - target.y),
                    )
                    * 10
                )
            )
            model.add_edge(
                source,
                target,
                distance=distance,
                duration=distance,
            )
    return model.data()


def assignments(solution: Solution) -> dict[int, int]:
    return {
        int(client): int(route.start_depot())
        for route in solution.routes()
        for client in route.visits()
    }


def main() -> int:
    data = make_fixture()
    initial = Solution(
        data,
        [
            Route(data, [2, 4, 5], 0),
            Route(data, [3], 1),
        ],
    )
    if not initial.is_complete() or not initial.is_feasible():
        raise RuntimeError("invalid behaviour fixture")

    params = SolveParams()
    mother_rng = RandomNumberGenerator(seed=17)
    native_search = build_local_search(data, mother_rng, params)
    expert_rng = RandomNumberGenerator(seed=1_000_020)
    zero_search = build_local_search(
        data,
        expert_rng,
        params,
        perturbation=PerturbationParams(0, 0),
    )
    operator = BoundedCrossDepotSegmentOperator(data, seed=2_000_020)
    replacement = ReplacementSearchMethod(
        native_search,
        zero_search,
        operator,
    )
    context = MechanismContext.from_public_v13(data)
    controller = C2EventController(
        context,
        allow_replacement=True,
        trigger_after=0,
        cooldown=128,
        force_first_replacement=True,
    )
    penalties = PenaltyManager.init_from(data, params.penalty)
    ils_params = replace(params.ils, exhaustive_on_best=False)
    result = EventDrivenIteratedLocalSearch(
        data,
        penalties,
        mother_rng,
        replacement,
        initial,
        ils_params,
        event_hooks=controller,
    ).run(
        MaxIterations(1),
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )

    before = assignments(initial)
    after = assignments(result.best)
    search_diag = replacement.diagnostics()
    operator_diag = search_diag["operator"]
    controller_diag = controller.diagnostics()
    missing_mechanisms = [
        mechanism
        for mechanism in MECHANISM_ORDER
        if mechanism != "multidepot_responsibility"
    ]
    checks = {
        "input_complete_feasible": (
            initial.is_complete() and initial.is_feasible()
        ),
        "output_complete_feasible": (
            result.best.is_complete() and result.best.is_feasible()
        ),
        "solution_changed": (
            canonical_signature(initial)
            != canonical_signature(result.best)
        ),
        "wrong_depot_segment_reassigned": (
            before[4] == 0
            and before[5] == 0
            and after[4] == 1
            and after[5] == 1
        ),
        "ordinary_native_call_replaced": (
            search_diag["native_calls"] == 0
        ),
        "one_zero_perturbation_refinement": (
            search_diag["zero_search_calls"] == 1
        ),
        "one_replacement_success": (
            search_diag["replacement_attempts"] == 1
            and search_diag["replacement_successes"] == 1
        ),
        "source_cap_respected": (
            operator_diag["source_segments_considered"] <= 64
        ),
        "per_source_position_cap_declared": (
            operator_diag["max_positions_per_source"] == 6
        ),
        "route_evaluation_cap_respected": (
            operator_diag["route_evaluations"] <= 48
        ),
        "full_evaluation_cap_respected": (
            operator_diag["full_evaluations"] <= 12
        ),
        "public_semantics_only": (
            operator_diag["public_semantics"]
            == "DEPOT_DISTANCE_LOAD_VEHICLE_TIME_WINDOW_ONLY"
        ),
        "distance_not_primary_veto": (
            operator_diag["proxy_policy"]
            == (
                "DEPOT_ACCESS_RELIEF_PRIMARY_"
                "DISTANCE_DELTA_SECONDARY"
            )
        ),
        "all_mechanisms_resident": (
            tuple(
                controller_diag["mechanisms"]["mechanism_order"]
            )
            == MECHANISM_ORDER
        ),
        "missing_mechanisms_naturally_inapplicable": all(
            controller_diag["mechanisms"]["status_counts"][
                mechanism
            ][NOT_APPLICABLE]
            == controller_diag["mechanisms"]["consultations"][
                mechanism
            ]
            for mechanism in missing_mechanisms
        ),
        "no_mechanism_disable_constructor_switch": all(
            forbidden
            not in inspect.signature(C2EventController).parameters
            for forbidden in (
                "disable_mechanisms",
                "mechanisms_enabled",
                "mechanism_switch",
            )
        ),
    }
    payload: dict[str, Any] = {
        "schema": "resetp.mpils-mvns-c2-behaviour.v1",
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "input_assignments": before,
        "output_assignments": after,
        "input_distance": int(initial.distance()),
        "output_distance": int(result.best.distance()),
        "routes": [
            route_payload(route) for route in result.best.routes()
        ],
        "search": search_diag,
        "controller": controller_diag,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

