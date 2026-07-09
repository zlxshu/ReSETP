"""Reusable LNS policy kernel for diagnostic A13 parity probes.

This module intentionally mirrors the existing LNS policy package from
``metaheuristic_baselines``: scan initialization, vehicle-type mutation,
strong-bridge destroy/repair, fallback order relocation, Metropolis wandering,
and periodic reheating.  It is diagnostic infrastructure, not a new formal
algorithm claim.
"""

from __future__ import annotations

import math
from typing import Any


LNS_DESTROY_OPS = ("random_customer_removal", "shaw_related_removal", "worst_customer_removal")
LNS_REPAIR_OPS = ("greedy_insert_repair", "regret2_insert_repair", "regret3_insert_repair")
LNS_POLICY_MACRO_ACTIONS = (
    "vehicle_type_mutation",
    *tuple(f"strong_bridge_{destroy}_{repair}" for destroy in LNS_DESTROY_OPS for repair in LNS_REPAIR_OPS),
    "fallback_order_relocate",
)


def reheated_temperature(*, current_objective: float, phi: float = 0.05) -> float:
    return max(1e-9, -float(phi) * abs(float(current_objective)) / math.log(0.5))


def run_lns_policy_kernel(session: Any, *, parameter_notes: dict[str, Any] | None = None) -> Any:
    """Run the LNS policy package against a ``metaheuristic_baselines`` session."""

    # Imported lazily to avoid making metaheuristic_baselines depend on this
    # module and to keep this diagnostic kernel isolated from baseline imports.
    from . import metaheuristic_baselines as mb

    params: dict[str, Any] = {
        "max_iter": 1000,
        "epsilon": 0.3,
        "phi": 0.05,
        "mu": 0.95,
        "destroy": "random+shaw",
        "repair": "farthest+regret",
        "policy_kernel": "A13_LNS_POLICY_KERNEL",
    }
    if parameter_notes:
        params.update(parameter_notes)

    scan_solution = mb._order_to_solution(mb._angle_scan_order(session.context.instance), session)
    previous_obj = session.current.objective
    previous_best_obj = session.best.objective
    previous_route_count = len(session.current.solution.routes)
    scored_scan = session.score(scan_solution, operator="lns_scan_initial")
    scan_accepted = False
    if scored_scan is not None and scored_scan.feasible and scored_scan.objective < session.current.objective - 1e-9:
        session.current = scored_scan
        scan_accepted = True
    session.record_lns_trace(
        iteration=0,
        operator="lns_scan_initial",
        trace_path=mb._classify_lns_trace_path("lns_scan_initial", fallback_used=False),
        destroy="",
        repair="",
        fallback_used=False,
        previous_obj=previous_obj,
        previous_best_obj=previous_best_obj,
        previous_route_count=previous_route_count,
        candidate=scan_solution,
        scored=scored_scan,
        accepted=scan_accepted,
        temperature=0.0,
    )

    temperature = reheated_temperature(current_objective=session.current.objective, phi=float(params["phi"]))
    iteration = 0
    while session.can_score():
        iteration += 1
        destroy, repair = mb._lns_operator_pair(session.rng)
        previous_obj = session.current.objective
        previous_best_obj = session.best.objective
        previous_route_count = len(session.current.solution.routes)
        fallback_used = False
        if session.rng.random() < 0.35:
            candidate = mb._vehicle_type_mutation(session.current.solution, session)
            operator = "lns_vehicle_type_mutation"
        else:
            outcome = mb._alns_neighbor(session, session.current.solution, destroy, repair)
            fallback_used = not (outcome.produced and outcome.feasible)
            if fallback_used:
                order = mb._apply_order_move(mb._solution_order(session.current.solution, session.context.instance), session.rng, "relocate")
                candidate = mb._order_to_solution(order, session)
            else:
                candidate = outcome.solution
            operator = f"lns_{destroy}_{repair}"
        scored = session.score(candidate, operator=operator)
        accepted = session.accept_metropolis(scored, temperature)
        session.record_lns_trace(
            iteration=iteration,
            operator=operator,
            trace_path=mb._classify_lns_trace_path(operator, fallback_used=fallback_used),
            destroy=destroy if operator.startswith("lns_") and operator != "lns_vehicle_type_mutation" else "",
            repair=repair if operator.startswith("lns_") and operator != "lns_vehicle_type_mutation" else "",
            fallback_used=fallback_used,
            previous_obj=previous_obj,
            previous_best_obj=previous_best_obj,
            previous_route_count=previous_route_count,
            candidate=candidate,
            scored=scored,
            accepted=accepted,
            temperature=temperature,
        )
        temperature *= float(params["mu"])
        if iteration >= int(params["max_iter"]):
            iteration = 0
            temperature = reheated_temperature(current_objective=session.current.objective, phi=float(params["phi"]))
    return session.finalize(params)


def run_lns_policy_baseline(
    bundle_dir: str,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    initial_solution: Any,
    prices: Any,
    common_flip_preprocess: bool = False,
) -> Any:
    """Construct a baseline session and run the diagnostic policy kernel."""

    from . import metaheuristic_baselines as mb

    bundle = mb.load_search_bundle(bundle_dir)
    session = mb._SearchSession(
        "LNS",
        bundle,
        int(seed),
        int(eval_budget),
        float(max_runtime_seconds),
        initial_solution,
        prices=prices,
        common_flip_preprocess=bool(common_flip_preprocess),
    )
    return run_lns_policy_kernel(session)
