"""Isolated HGS-style outer search with the frozen ReSETP ALNS as educator.

This file is development-only.  It does not modify the formal solver entry
point.  All complete candidate scores pass through EvalBudget.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import time
from pathlib import Path
from typing import Any

from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_winner_kernel
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import score_search_candidate
from setp_solver.algorithms.resetp_alns.support.order_decoder import (
    OrderDecodeContext,
    order_to_solution,
    route_type_hints,
    solution_order,
)
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, score_reference
from setp_solver.solution import Solution


@dataclass
class Individual:
    order: list[str]
    solution: Solution
    objective: float


@dataclass
class ArmResult:
    algorithm: str
    best_solution: Solution
    best_cost: float
    evaluations: int
    elapsed_seconds: float
    route_count: int
    feasible: bool
    mechanism_activity: dict[str, int]


def ordered_crossover(left: list[str], right: list[str], rng: random.Random) -> list[str]:
    """Order crossover: keep one block from left, fill remaining from right."""

    if len(left) < 2:
        return list(left)
    a = rng.randrange(0, len(left) - 1)
    b = rng.randrange(a + 1, len(left))
    block = left[a : b + 1]
    remainder = [item for item in right if item not in set(block)]
    return [*remainder[:a], *block, *remainder[a:]]


def mutate_order(order: list[str], rng: random.Random) -> list[str]:
    changed = list(order)
    if len(changed) < 4:
        changed.reverse()
        return changed
    mode = rng.randrange(3)
    a, b = sorted(rng.sample(range(len(changed)), 2))
    if mode == 0:
        changed[a], changed[b] = changed[b], changed[a]
    elif mode == 1:
        changed[a : b + 1] = reversed(changed[a : b + 1])
    else:
        item = changed.pop(b)
        changed.insert(a, item)
    return changed


def order_distance(left: list[str], right: list[str]) -> float:
    if not left:
        return 0.0
    position = {item: idx for idx, item in enumerate(right)}
    return sum(abs(idx - position.get(item, idx)) for idx, item in enumerate(left)) / max(1, len(left) ** 2)


def _select_parents(population: list[Individual], rng: random.Random) -> tuple[Individual, Individual]:
    ranked = sorted(population, key=lambda item: item.objective)
    first = ranked[rng.randrange(min(4, len(ranked)))]
    candidates = sorted(
        (item for item in population if item is not first),
        key=lambda item: (-order_distance(first.order, item.order), item.objective),
    )
    second = candidates[0] if candidates else first
    return first, second


def run_outer_search(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    """Run the population/recombination part without ALNS education."""

    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = initial_solution or make_shared_initial_solution(bundle, prices=prices)
    rng = random.Random(seed)
    budget = EvalBudget(limit=max(0, int(eval_budget)), target=max(0, int(eval_budget)))
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=budget,
    )
    warm_cost = score_reference(warm, context)
    warm_order = solution_order(warm, bundle.instance)
    decode = OrderDecodeContext(bundle.instance, prices, bundle.carbon_profile, rng)
    hints = route_type_hints(warm, bundle.instance)
    population = [Individual(warm_order, warm, warm_cost)]
    best = population[0]
    activity = {
        "outer_candidates": 0,
        "ordered_crossovers": 0,
        "order_mutations": 0,
        "diversity_rejections": 0,
        "improvements": 0,
    }

    while budget.count < budget.target_count:
        if len(population) == 1:
            child_order = mutate_order(warm_order, rng)
            activity["order_mutations"] += 1
        else:
            left, right = _select_parents(population, rng)
            child_order = ordered_crossover(left.order, right.order, rng)
            activity["ordered_crossovers"] += 1
            if rng.random() < 0.35:
                child_order = mutate_order(child_order, rng)
                activity["order_mutations"] += 1
        if any(order_distance(child_order, item.order) < 1e-12 for item in population):
            child_order = mutate_order(child_order, rng)
            activity["diversity_rejections"] += 1
            activity["order_mutations"] += 1
        candidate = order_to_solution(
            child_order,
            decode,
            current_solution=best.solution,
            type_hints=hints,
        )
        candidate, objective = score_search_candidate(
            candidate,
            context,
            channel="isolated_hgs_outer",
        )
        activity["outer_candidates"] += 1
        individual = Individual(child_order, candidate, objective)
        population.append(individual)
        population = sorted(population, key=lambda item: item.objective)[:8]
        if objective < best.objective - 1e-9:
            best = individual
            activity["improvements"] += 1

    violations = check_solution(best.solution, bundle.instance, prices)
    return ArmResult(
        algorithm="pure_hgs_style_outer",
        best_solution=best.solution,
        best_cost=float(best.objective),
        evaluations=budget.count,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(best.solution.routes),
        feasible=not violations,
        mechanism_activity=activity,
    )


def run_pure_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    started = time.perf_counter()
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
    return ArmResult(
        algorithm="pure_alns",
        best_solution=result["best_solution"],
        best_cost=float(result["best_cost"]),
        evaluations=int(result["evaluations"]),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(result["best_solution"].routes),
        feasible=bool(result["feasible"]),
        mechanism_activity={"alns_actual_moves": int(result.get("actual_moves", 0))},
    )


def run_combined(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    outer_share: float = 0.25,
    inner_basins: int = 1,
    prices: Any = DEFAULT_PRICES,
) -> ArmResult:
    """Spend one global budget: outer exploration first, ALNS education second."""

    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, prices=prices)
    total = max(0, int(eval_budget))
    outer_budget = min(total, max(0, int(round(total * float(outer_share)))))
    inner_budget = total - outer_budget
    outer = run_outer_search(
        bundle_dir,
        seed=seed,
        eval_budget=outer_budget,
        prices=prices,
        initial_solution=warm,
    )
    if inner_budget:
        basin_count = max(1, min(int(inner_basins), inner_budget))
        allocations = [inner_budget // basin_count] * basin_count
        for index in range(inner_budget % basin_count):
            allocations[index] += 1
        starts = [outer.best_solution]
        if basin_count > 1:
            starts = [warm, outer.best_solution]
            while len(starts) < basin_count:
                starts.append(outer.best_solution)
        inner_runs = [
            run_pure_alns(
                bundle_dir,
                seed=seed + 1009 * index,
                eval_budget=allocation,
                prices=prices,
                initial_solution=starts[index],
            )
            for index, allocation in enumerate(allocations)
        ]
        candidates = [outer, *inner_runs]
        winner = min(candidates, key=lambda item: item.best_cost)
        best_solution = winner.best_solution
        best_cost = winner.best_cost
        feasible = all(item.feasible for item in candidates)
        inner_activity = {
            "alns_actual_moves": sum(item.mechanism_activity.get("alns_actual_moves", 0) for item in inner_runs),
            "educated_basins": basin_count,
        }
    else:
        best_solution = outer.best_solution
        best_cost = outer.best_cost
        feasible = outer.feasible
        inner_activity = {"alns_actual_moves": 0}
    return ArmResult(
        algorithm="mechanism_hgs_alns_skeleton",
        best_solution=best_solution,
        best_cost=float(best_cost),
        evaluations=outer.evaluations + inner_budget,
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(best_solution.routes),
        feasible=feasible,
        mechanism_activity={
            **outer.mechanism_activity,
            **inner_activity,
            "outer_budget": outer_budget,
            "inner_budget": inner_budget,
        },
    )


def independent_cost(bundle_dir: str | Path, solution: Solution, prices: Any = DEFAULT_PRICES) -> float:
    bundle = load_search_bundle(bundle_dir)
    return float(
        evaluate(
            solution,
            bundle.instance,
            bundle.carbon_profile,
            prices,
        )["total_cost"]
    )
