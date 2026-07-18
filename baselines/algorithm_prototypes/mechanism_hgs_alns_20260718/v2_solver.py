"""Official-HGS-backed, mechanism-educated ALNS development solver.

This module keeps four identities separate:

* pinned official HGS-CVRP plus a neutral ReSETP translation layer;
* upstream N-Wouda ALNS 7.0.0 control loop plus generic ReSETP operators;
* the current project ALNS;
* the new candidate: official-HGS route skeletons, project ALNS education,
  then eligible ReSETP mechanism experts under one complete-evaluation budget.

It is isolated development code and is not imported by the formal solver.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Iterator

import numpy as np


REPO = Path(__file__).resolve().parents[3]
REFERENCE_ALNS = REPO / "Reference Algorithm" / "ALNS-7.0.0@N-Wouda"
if str(REFERENCE_ALNS) not in sys.path:
    sys.path.insert(0, str(REFERENCE_ALNS))

from alns import ALNS  # noqa: E402
from alns.accept import RecordToRecordTravel  # noqa: E402
from alns.select import RouletteWheel  # noqa: E402

from official_hgs_resetp_adapter import (  # noqa: E402
    HGSAdapterConfig,
    OfficialHGSLibrary,
    decode_official_hgs_order,
    official_hgs_order,
)
from prototype import (  # noqa: E402
    ArmResult,
    cross_depot_swapstar_intensify,
    independent_cost,
    run_pure_alns,
)
from setp_solver.algorithms.resetp_alns.kernel.alns_core import (  # noqa: E402
    AlnsState,
    SearchPolicy,
    greedy_insert_repair,
    random_customer_removal,
    regret2_insert_repair,
    regret3_insert_repair,
    route_segment_removal,
    shaw_related_removal,
    whole_route_removal,
    worst_customer_removal,
)
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (  # noqa: E402
    score_reference_solution,
    score_search_candidate,
)
from setp_solver.algorithms.resetp_alns.support.fleet_charge_corepair import (  # noqa: E402
    propose_fleet_charge_corepair,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.candidates import make_shared_initial_solution  # noqa: E402
from setp_solver.search.evaluation import EvalBudget, EvaluationContext  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402


ORIGINAL_ALNS_COMMIT = "4962d91385990033d9bce81d1407cf846d4fb70c"


def _raw_cost(
    solution: Solution,
    *,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: Any,
) -> float:
    return float(evaluate(solution, instance, carbon_profile, prices)["total_cost"])


def _is_feasible(solution: Solution, *, instance: Any, prices: Any) -> bool:
    return not check_solution(solution, instance, prices)


def run_official_hgs_neutral(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
    no_improvement_iterations: int = 100,
) -> ArmResult:
    """Run the unmodified official HGS core through the neutral adapter."""

    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = initial_solution or make_shared_initial_solution(bundle, prices=prices)
    warm_cost = _raw_cost(
        warm,
        instance=bundle.instance,
        carbon_profile=bundle.carbon_profile,
        prices=prices,
    )
    total = max(0, int(eval_budget))
    budget = EvalBudget(limit=total, target=total)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=budget,
    )
    engine = OfficialHGSLibrary()
    best_solution = warm
    best_cost = warm_cost
    hgs_calls = 0
    hgs_native_cpu_seconds = 0.0
    hgs_wall_seconds = 0.0
    hgs_improvements = 0
    invalid_decodes = 0
    unique_orders: set[tuple[str, ...]] = set()

    for candidate_index in range(total):
        hgs_result = official_hgs_order(
            instance=bundle.instance,
            initial_solution=warm,
            capacity=float(
                prices["Q_capacity"]
                if isinstance(prices, dict)
                else getattr(prices, "Q_capacity")
            ),
            speed_m_per_second=float(
                prices["v_speed_ms"]
                if isinstance(prices, dict)
                else getattr(prices, "v_speed_ms")
            ),
            config=HGSAdapterConfig(
                seed=int(seed) * 1_000_003 + candidate_index,
                no_improvement_iterations=no_improvement_iterations,
            ),
            library=engine,
        )
        hgs_calls += int(hgs_result.native_calls)
        hgs_native_cpu_seconds += float(hgs_result.native_cpu_seconds)
        hgs_wall_seconds += float(hgs_result.wall_seconds)
        unique_orders.add(tuple(hgs_result.order))
        candidate = decode_official_hgs_order(
            hgs_result,
            instance=bundle.instance,
            carbon_profile=bundle.carbon_profile,
            prices=prices,
            initial_solution=warm,
            rng=random.Random(int(seed) * 1_000_003 + candidate_index),
        )
        candidate, objective = score_search_candidate(
            candidate,
            context,
            channel="official_hgs_neutral_adapter",
        )
        feasible = _is_feasible(
            candidate,
            instance=bundle.instance,
            prices=prices,
        )
        if not feasible:
            invalid_decodes += 1
        elif objective < best_cost - 1.0e-9:
            best_solution = candidate
            best_cost = float(objective)
            hgs_improvements += 1

    return ArmResult(
        algorithm="official_vidal_hgs_neutral_resetp_adapter",
        best_solution=best_solution,
        best_cost=float(best_cost),
        evaluations=budget.count,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(best_solution.routes),
        feasible=_is_feasible(
            best_solution,
            instance=bundle.instance,
            prices=prices,
        ),
        mechanism_activity={
            "official_hgs_commit": "1a927955cd2861a29d978f0d359d6e647db9319c",
            "hgs_candidate_decodes": total,
            "hgs_native_calls": hgs_calls,
            "hgs_native_cpu_milliseconds": round(
                1_000.0 * hgs_native_cpu_seconds, 6
            ),
            "hgs_adapter_wall_milliseconds": round(
                1_000.0 * hgs_wall_seconds, 6
            ),
            "unique_hgs_orders": len(unique_orders),
            "hgs_improvements": hgs_improvements,
            "invalid_decodes": invalid_decodes,
        },
    )


class _BudgetStop:
    def __init__(self, budget: EvalBudget) -> None:
        self._budget = budget

    def __call__(self, rng: Any, best: Any, current: Any) -> bool:
        _ = rng, best, current
        return self._budget.reached_target


@contextmanager
def _neutral_original_alns_environment() -> Iterator[None]:
    frozen = {
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "0",
        "SETP_E3_STRICT_MULTITRIP": "0",
    }
    previous = {name: os.environ.get(name) for name in frozen}
    os.environ.update(frozen)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def run_original_n_wouda_alns_neutral(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    """Run the pinned upstream ALNS engine with generic ReSETP operators only.

    The selector scores, decay, and record-to-record acceptance follow the
    upstream 7.0.0 CVRP example.  The upstream package is a framework rather
    than a ReSETP solver, so neutral problem-specific destroy/repair adapters
    are unavoidable and explicitly reported.
    """

    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = initial_solution or make_shared_initial_solution(bundle, prices=prices)
    total = max(0, int(eval_budget))
    budget = EvalBudget(limit=total, target=total)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=budget,
    )
    warm, warm_cost = score_reference_solution(
        warm,
        context,
        phase="original_n_wouda_initial",
    )
    initial_state = AlnsState(
        warm,
        context,
        objective_value=warm_cost,
        policy=SearchPolicy(
            require_charging_signal=False,
            allow_cross_depot=True,
            enable_cross_depot_operator=False,
        ),
    )
    engine = ALNS(np.random.default_rng(int(seed)))
    destroy_operators = (
        random_customer_removal,
        worst_customer_removal,
        shaw_related_removal,
        whole_route_removal,
        route_segment_removal,
    )
    repair_operators = (
        greedy_insert_repair,
        regret2_insert_repair,
        regret3_insert_repair,
    )
    for operator in destroy_operators:
        engine.add_destroy_operator(operator)
    for operator in repair_operators:
        engine.add_repair_operator(operator)
    selector = RouletteWheel(
        [25.0, 5.0, 1.0, 0.0],
        0.8,
        len(destroy_operators),
        len(repair_operators),
    )
    acceptance = RecordToRecordTravel.autofit(
        float(warm_cost),
        0.02,
        0.0,
        max(1, total),
    )
    with _neutral_original_alns_environment():
        result = engine.iterate(
            initial_state,
            selector,
            acceptance,
            _BudgetStop(budget),
        )
    best = result.best_state
    statistics = result.statistics
    return ArmResult(
        algorithm="original_n_wouda_alns_7_0_0_neutral_resetp_adapter",
        best_solution=best.solution,
        best_cost=float(best.objective()),
        evaluations=budget.count,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(best.solution.routes),
        feasible=_is_feasible(
            best.solution,
            instance=bundle.instance,
            prices=prices,
        ),
        mechanism_activity={
            "upstream_alns_commit": ORIGINAL_ALNS_COMMIT,
            "destroy_operators": len(destroy_operators),
            "repair_operators": len(repair_operators),
            "candidate_scores": int(context.score_counts.get("candidate", 0)),
            "repair_delta_scores": int(
                context.score_counts.get("repair_delta", 0)
            ),
            "iterations": max(0, len(statistics.objectives) - 1),
        },
    )


def _apply_mechanism_experts(
    *,
    solution: Solution,
    objective: float,
    context: EvaluationContext,
) -> tuple[Solution, float, dict[str, Any]]:
    """Apply eligible experts without a user-facing scenario switch."""

    counters: dict[str, Any] = {
        "depot_expert_eligible": 0,
        "depot_expert_evaluations": 0,
        "depot_expert_improvements": 0,
        "fleet_charge_expert_eligible": 0,
        "fleet_charge_expert_evaluations": 0,
        "fleet_charge_expert_improvements": 0,
    }
    remaining = max(
        0,
        int(context.budget.target_count - context.budget.count)
        if context.budget is not None
        else 0,
    )
    depot_count = len(
        {
            node.node_id
            for node in context.instance.nodes
            if node.node_type.lower() == "d"
        }
    )
    if remaining > 0 and depot_count >= 2:
        counters["depot_expert_eligible"] = 1
        depot_limit = min(remaining, max(1, remaining // 3))
        before = int(context.budget.count)
        changed, changed_objective, detail = cross_depot_swapstar_intensify(
            solution,
            context,
            incumbent_objective=objective,
            max_evaluations=depot_limit,
        )
        used = int(context.budget.count) - before
        counters["depot_expert_evaluations"] = used
        counters.update(
            {
                f"depot_{key}": value
                for key, value in detail.items()
                if key != "cross_depot_rejection_examples"
            }
        )
        if changed_objective < objective - 1.0e-9:
            solution = changed
            objective = float(changed_objective)
            counters["depot_expert_improvements"] += 1

    remaining = max(
        0,
        int(context.budget.target_count - context.budget.count)
        if context.budget is not None
        else 0,
    )
    if remaining > 0 and solution.routes:
        counters["fleet_charge_expert_eligible"] = 1
        while remaining > 0:
            before = int(context.budget.count)
            outcome = propose_fleet_charge_corepair(
                solution,
                context,
                max_attempts=min(len(solution.routes), remaining),
                current_objective=objective,
            )
            used = int(context.budget.count) - before
            counters["fleet_charge_expert_evaluations"] += used
            if (
                outcome.solution is None
                or outcome.objective is None
                or outcome.objective >= objective - 1.0e-9
            ):
                break
            solution = outcome.solution
            objective = float(outcome.objective)
            counters["fleet_charge_expert_improvements"] += 1
            remaining = max(
                0,
                int(context.budget.target_count - context.budget.count)
                if context.budget is not None
                else 0,
            )
            if used == 0:
                break
    return solution, objective, counters


def _run_mechanism_hgs_alns_v2(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    hgs_share: float = 0.08,
    mechanism_share: float = 0.12,
    use_official_hgs: bool,
    use_mechanism_experts: bool,
    algorithm_label: str,
) -> ArmResult:
    """Run the candidate or one development-only component ablation."""

    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, prices=prices)
    warm_cost = independent_cost(bundle_dir, warm, prices)
    total = max(0, int(eval_budget))
    if total == 0:
        return ArmResult(
            algorithm=algorithm_label,
            best_solution=warm,
            best_cost=independent_cost(bundle_dir, warm, prices),
            evaluations=0,
            elapsed_seconds=time.perf_counter() - started,
            route_count=len(warm.routes),
            feasible=_is_feasible(
                warm,
                instance=bundle.instance,
                prices=prices,
            ),
            mechanism_activity={},
        )

    hgs_budget = (
        max(1, int(round(total * max(0.0, float(hgs_share)))))
        if use_official_hgs
        else 0
    )
    mechanism_room = max(
        1, int(round(total * max(0.0, float(mechanism_share))))
    )
    if hgs_budget + mechanism_room > total:
        mechanism_room = max(0, total - hgs_budget)
    education_budget = max(0, total - hgs_budget - mechanism_room)

    if use_official_hgs:
        skeleton = run_official_hgs_neutral(
            bundle_dir,
            seed=seed,
            eval_budget=hgs_budget,
            prices=prices,
            initial_solution=warm,
        )
        skeleton_solution = skeleton.best_solution
        skeleton_cost = float(skeleton.best_cost)
        skeleton_evaluations = skeleton.evaluations
        hgs_activity = dict(skeleton.mechanism_activity)
    else:
        skeleton = None
        skeleton_solution = warm
        skeleton_cost = float(warm_cost)
        skeleton_evaluations = 0
        hgs_activity = {
            "development_ablation": "official_hgs_removed",
            "hgs_native_calls": 0,
        }
    if education_budget:
        educated = run_pure_alns(
            bundle_dir,
            seed=seed,
            eval_budget=education_budget,
            prices=prices,
            initial_solution=skeleton_solution,
        )
        solution = educated.best_solution
        objective = educated.best_cost
        educated_cost = float(educated.best_cost)
        education_activity = dict(educated.mechanism_activity)
    else:
        educated = None
        solution = skeleton_solution
        objective = skeleton_cost
        educated_cost = skeleton_cost
        education_activity = {}

    expert_limit = mechanism_room if use_mechanism_experts else 0
    expert_budget = EvalBudget(limit=expert_limit, target=expert_limit)
    expert_context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=expert_budget,
    )
    if use_mechanism_experts:
        solution, objective, expert_activity = _apply_mechanism_experts(
            solution=solution,
            objective=objective,
            context=expert_context,
        )
    else:
        expert_activity = {
            "development_ablation": "mechanism_experts_removed",
            "depot_expert_eligible": 0,
            "depot_expert_evaluations": 0,
            "depot_expert_improvements": 0,
            "fleet_charge_expert_eligible": 0,
            "fleet_charge_expert_evaluations": 0,
            "fleet_charge_expert_improvements": 0,
        }
    post_expert_cost = float(objective)
    filler = mechanism_room - expert_budget.count
    filler_activity: dict[str, Any] = {}
    if filler:
        continuation = run_pure_alns(
            bundle_dir,
            seed=seed + 9_999_991,
            eval_budget=filler,
            prices=prices,
            initial_solution=solution,
        )
        filler_activity = dict(continuation.mechanism_activity)
        if continuation.best_cost < objective - 1.0e-9:
            solution = continuation.best_solution
            objective = continuation.best_cost

    evaluations = (
        skeleton_evaluations
        + (educated.evaluations if educated is not None else 0)
        + expert_budget.count
        + filler
    )
    return ArmResult(
        algorithm=algorithm_label,
        best_solution=solution,
        best_cost=float(objective),
        evaluations=evaluations,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(solution.routes),
        feasible=_is_feasible(
            solution,
            instance=bundle.instance,
            prices=prices,
        ),
        mechanism_activity={
            "warm_cost": float(warm_cost),
            "skeleton_cost": skeleton_cost,
            "educated_cost": educated_cost,
            "post_expert_cost": post_expert_cost,
            "final_cost": float(objective),
            "development_use_official_hgs": bool(use_official_hgs),
            "development_use_mechanism_experts": bool(
                use_mechanism_experts
            ),
            "hgs_evaluations": skeleton_evaluations,
            "alns_education_evaluations": (
                educated.evaluations if educated is not None else 0
            ),
            "expert_evaluations": expert_budget.count,
            "filler_alns_evaluations": filler,
            "hgs_activity": hgs_activity,
            "education_activity": education_activity,
            "expert_activity": expert_activity,
            "filler_activity": filler_activity,
        },
    )


def run_mechanism_hgs_alns_v2(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    hgs_share: float = 0.08,
    mechanism_share: float = 0.12,
) -> ArmResult:
    """Run official HGS skeletons, ALNS education, and eligible experts."""

    return _run_mechanism_hgs_alns_v2(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        hgs_share=hgs_share,
        mechanism_share=mechanism_share,
        use_official_hgs=True,
        use_mechanism_experts=True,
        algorithm_label="mechanism_hgs_alns_v2",
    )


def run_mechanism_hgs_alns_v2_without_hgs(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    hgs_share: float = 0.08,
    mechanism_share: float = 0.12,
) -> ArmResult:
    """Development-only ablation that removes official HGS."""

    return _run_mechanism_hgs_alns_v2(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        hgs_share=hgs_share,
        mechanism_share=mechanism_share,
        use_official_hgs=False,
        use_mechanism_experts=True,
        algorithm_label="mechanism_hgs_alns_v2_without_hgs_ablation",
    )


def run_mechanism_hgs_alns_v2_without_experts(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    hgs_share: float = 0.08,
    mechanism_share: float = 0.12,
) -> ArmResult:
    """Development-only ablation that removes both mechanism experts."""

    return _run_mechanism_hgs_alns_v2(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        hgs_share=hgs_share,
        mechanism_share=mechanism_share,
        use_official_hgs=True,
        use_mechanism_experts=False,
        algorithm_label="mechanism_hgs_alns_v2_without_experts_ablation",
    )
