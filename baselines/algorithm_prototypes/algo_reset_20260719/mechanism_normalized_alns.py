"""ALNS whose accepted states are normalised by ReSETP mechanism experts.

The prototype temporarily replaces only the isolated ALNS loop used by the
winner kernel. It does not edit the formal solver. Each repaired candidate is
first scored under the normal complete-evaluation budget, then its fixed route
skeleton is passed through the exact fleet/charging and carbon-time experts
before acceptance. Cross-depot responsibility remains a final bounded expert.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import sys
import time
from typing import Any, Iterator

import numpy as np


HERE = Path(__file__).resolve().parent
MECHANISM_DIR = HERE.parent / "mechanism_hgs_alns_20260718"
if str(MECHANISM_DIR) not in sys.path:
    sys.path.insert(0, str(MECHANISM_DIR))

from mechanism_route_pool_fusion import apply_mechanism_experts  # noqa: E402
from prototype import ArmResult  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel import alns_core  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    run_winner_kernel,
)
from setp_solver.algorithms.resetp_alns.operators import (  # noqa: E402
    local_search,
    true_swapstar,
)
from setp_solver.algorithms.resetp_alns.operators.local_search import (  # noqa: E402
    improve_solution_locally,
)
from setp_solver.algorithms.resetp_alns.support import (  # noqa: E402
    fleet_charge_corepair,
    global_order_repack,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402
from v5_carbon_retiming_solver import carbon_aware_depot_retime  # noqa: E402
from v6_monotone_mechanism_solver import (  # noqa: E402
    exact_joint_fleet_charge_decode,
)


TOL = 1.0e-9


def _mechanism_normalize_state(
    state: alns_core.AlnsState,
    activity: dict[str, int],
) -> alns_core.AlnsState:
    before = float(state.objective())
    solution, objective, joint = exact_joint_fleet_charge_decode(
        state.solution,
        state.context,
        incumbent_objective=before,
    )
    solution, objective, carbon = carbon_aware_depot_retime(
        solution,
        state.context,
        incumbent_objective=objective,
        consume_complete_evaluation=False,
    )
    activity["normalizer_calls"] += 1
    activity["joint_updates"] += int(joint.get("exact_decoder_updates", 0))
    activity["carbon_updates"] += int(carbon.get("exact_decoder_updates", 0))
    activity["route_proxy_evaluations"] += int(
        joint.get("route_proxy_evaluations", 0)
    )
    activity["carbon_route_local_evaluations"] += int(
        carbon.get("route_local_schedule_evaluations", 0)
    )
    activity["mechanism_feasibility_checks"] += int(
        joint.get("feasibility_checks", 0)
    ) + int(carbon.get("feasibility_checks", 0))
    if objective < before - TOL:
        activity["normalizer_improvements"] += 1
    return replace(
        state,
        solution=solution,
        objective_value=float(objective),
    )


def _normalize_scored_solution(
    solution: Solution,
    objective: float,
    context: Any,
    activity: dict[str, int],
) -> tuple[Solution, float]:
    if check_solution(solution, context.instance, context.prices):
        return solution, float(objective)
    state = alns_core.AlnsState(
        solution=solution,
        context=context,
        objective_value=float(objective),
    )
    normalized = _mechanism_normalize_state(state, activity)
    return normalized.solution, normalized.objective()


def _mechanism_normalized_loop(
    initial_state: alns_core.AlnsState,
    *,
    seed: int,
    iterations: int | None,
    eval_budget: int | None,
    max_runtime_seconds: float,
    activity: dict[str, int],
) -> dict[str, Any]:
    """Mirror the project ALNS loop with pre-acceptance mechanism decoding."""

    rng = np.random.default_rng(seed)
    destroy_ops = [
        ("random_customer_removal", alns_core.random_customer_removal),
        ("worst_customer_removal", alns_core.worst_customer_removal),
        ("shaw_related_removal", alns_core.shaw_related_removal),
        ("whole_route_removal", alns_core.whole_route_removal),
        ("route_segment_removal", alns_core.route_segment_removal),
        ("vehicle_type_swap", alns_core.vehicle_type_swap_destroy),
    ]
    if alns_core._flag_enabled("SETP_ALNS_CRUSH_ROUTE_ELIMINATION"):
        destroy_ops.insert(
            4,
            ("route_elimination_removal", alns_core.route_elimination_removal),
        )
    repair_ops = [
        ("greedy_insert_repair", alns_core.greedy_insert_repair),
        ("regret2_insert_repair", alns_core.regret2_insert_repair),
        ("regret3_insert_repair", alns_core.regret3_insert_repair),
    ]
    selector = alns_core._make_operator_selector(
        len(destroy_ops),
        len(repair_ops),
    )
    current = best = _mechanism_normalize_state(initial_state, activity)
    acceptance = alns_core._make_acceptance_criterion(
        current,
        alns_core._target_iterations(iterations, eval_budget),
    )
    destroy_counts = {name: [0, 0, 0, 0] for name, _ in destroy_ops}
    repair_counts = {name: [0, 0, 0, 0] for name, _ in repair_ops}
    target = int(eval_budget) if eval_budget is not None else int(iterations or 1)
    started = time.perf_counter()
    moves = 0
    while True:
        if iterations is not None and moves >= int(iterations):
            break
        budget = initial_state.context.budget
        if budget is not None and budget.reached_target:
            break
        if eval_budget is not None and budget is not None and budget.count >= target:
            break
        if time.perf_counter() - started >= float(max_runtime_seconds):
            break
        moves += 1
        progress = min(1.0, moves / max(1, target))
        destroy_idx, repair_idx = selector(rng, best, current)
        destroy_name, destroy_op = destroy_ops[int(destroy_idx)]
        repair_name, repair_op = repair_ops[int(repair_idx)]
        previous_obj = current.objective()
        previous_best_obj = best.objective()
        candidate = repair_op(
            destroy_op(current, rng, progress=progress),
            rng,
        )
        valid_changed = (
            not candidate.removed_customers
            and not alns_core._hard_violations(
                candidate.solution,
                candidate.context,
            )
            and alns_core._solution_changed(
                current.solution,
                candidate.solution,
            )
        )
        if valid_changed:
            improved_solution, improved_objective = improve_solution_locally(
                candidate.solution,
                candidate.context,
                incumbent_objective=candidate.objective(),
            )
            candidate = replace(
                candidate,
                solution=improved_solution,
                objective_value=improved_objective,
            )
            candidate = _mechanism_normalize_state(candidate, activity)
        if destroy_name == "route_elimination_removal" and (
            len(candidate.solution.routes) >= len(current.solution.routes)
            or candidate.objective() >= previous_obj - TOL
        ):
            candidate = current
        if (
            candidate.removed_customers
            or alns_core._hard_violations(
                candidate.solution,
                candidate.context,
            )
            or not alns_core._solution_changed(
                current.solution,
                candidate.solution,
            )
        ):
            candidate = current
        candidate_obj = candidate.objective()
        changed = alns_core._solution_changed(
            current.solution,
            candidate.solution,
        )
        accepted = changed and bool(
            acceptance(rng, best, current, candidate)
        )
        best_improved = (
            accepted
            and candidate_obj < previous_best_obj - TOL
            and not alns_core._hard_violations(
                candidate.solution,
                candidate.context,
            )
        )
        better_current = accepted and candidate_obj < previous_obj - TOL
        outcome_idx = 3
        if accepted:
            current = candidate
            outcome_idx = 2
            if better_current:
                outcome_idx = 1
            if best_improved:
                best = candidate
                outcome_idx = 0
        destroy_counts[destroy_name][outcome_idx] += 1
        repair_counts[repair_name][outcome_idx] += 1
        selector.update(
            candidate,
            int(destroy_idx),
            int(repair_idx),
            outcome_idx,
        )
    return {
        "best_state": best,
        "current_state": current,
        "destroy_counts": destroy_counts,
        "repair_counts": repair_counts,
        "destroy_weights": {},
        "repair_weights": {},
        "moves": moves,
    }


@contextmanager
def _patched_loop(activity: dict[str, int]) -> Iterator[None]:
    original = alns_core._run_adaptive_sa_alns

    def patched(
        initial_state: alns_core.AlnsState,
        *,
        seed: int,
        iterations: int | None,
        eval_budget: int | None,
        max_runtime_seconds: float,
    ) -> dict[str, Any]:
        return _mechanism_normalized_loop(
            initial_state,
            seed=seed,
            iterations=iterations,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            activity=activity,
        )

    alns_core._run_adaptive_sa_alns = patched
    try:
        yield
    finally:
        alns_core._run_adaptive_sa_alns = original


@contextmanager
def _patched_candidate_scorers(
    activity: dict[str, int],
) -> Iterator[None]:
    """Normalise every complete candidate exactly where its budget is charged."""

    modules = (
        alns_core,
        local_search,
        true_swapstar,
        fleet_charge_corepair,
        global_order_repack,
    )
    from setp_solver.algorithms.resetp_alns.kernel import winner

    modules = (*modules, winner)
    originals: list[tuple[Any, str, Any]] = []
    for module in modules:
        if not hasattr(module, "score_search_candidate"):
            continue
        original = getattr(module, "score_search_candidate")

        def candidate_wrapper(
            solution: Solution,
            context: Any,
            *args: Any,
            _original: Any = original,
            **kwargs: Any,
        ) -> tuple[Solution, float]:
            scored, objective = _original(
                solution,
                context,
                *args,
                **kwargs,
            )
            return _normalize_scored_solution(
                scored,
                objective,
                context,
                activity,
            )

        originals.append((module, "score_search_candidate", original))
        setattr(module, "score_search_candidate", candidate_wrapper)

    for module in (alns_core, winner):
        if not hasattr(module, "score_reference_solution"):
            continue
        original = getattr(module, "score_reference_solution")

        def reference_wrapper(
            solution: Solution,
            context: Any,
            *args: Any,
            _original: Any = original,
            **kwargs: Any,
        ) -> tuple[Solution, float]:
            scored, objective = _original(
                solution,
                context,
                *args,
                **kwargs,
            )
            return _normalize_scored_solution(
                scored,
                objective,
                context,
                activity,
            )

        originals.append((module, "score_reference_solution", original))
        setattr(module, "score_reference_solution", reference_wrapper)
    try:
        yield
    finally:
        for module, name, original in reversed(originals):
            setattr(module, name, original)


def run_mechanism_normalized_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    """Run the winner kernel with mechanism-normalised ALNS acceptance."""

    started = time.perf_counter()
    activity = {
        "normalizer_calls": 0,
        "normalizer_improvements": 0,
        "joint_updates": 0,
        "carbon_updates": 0,
        "route_proxy_evaluations": 0,
        "carbon_route_local_evaluations": 0,
        "mechanism_feasibility_checks": 0,
    }
    with _patched_candidate_scorers(activity):
        result = run_winner_kernel(
            bundle_dir,
            config=WinnerKernelConfig(
                seed=seed,
                eval_budget=int(eval_budget),
                max_runtime_seconds=3600.0,
                require_charging_signal=False,
            ),
            initial_solution=initial_solution,
            prices=prices,
        )
    final = apply_mechanism_experts(
        bundle_dir,
        result["best_solution"],
        prices=prices,
    )
    bundle = alns_core._load_search_bundle(bundle_dir)
    violations = check_solution(final.solution, bundle.instance, prices)
    return ArmResult(
        algorithm="mechanism_normalized_alns",
        best_solution=final.solution,
        best_cost=float(final.objective),
        evaluations=int(result["evaluations"]),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(final.solution.routes),
        feasible=not violations,
        mechanism_activity={
            **activity,
            "final_experts": final.activity,
            "independent_final_replays": 1,
        },
    )
