"""Isolated collaboration/fairness micro-prototype under EA-001.

This module is deliberately self-contained.  It does not import the formal
ReSETP solver and is not imported by any formal runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable


DEPOTS = ("A", "B", "C")


@dataclass(frozen=True)
class Customer:
    customer_id: str
    x: float
    y: float
    revenue: float
    service_cost: dict[str, float]


@dataclass(frozen=True)
class MicroProblem:
    depots_xy: dict[str, tuple[float, float]]
    customers: tuple[Customer, ...]
    initial_assignment: dict[str, str]
    standalone_profit: dict[str, float]
    theta: float

    @property
    def customer_by_id(self) -> dict[str, Customer]:
        return {customer.customer_id: customer for customer in self.customers}


@dataclass(frozen=True)
class Evaluation:
    assignment: dict[str, str]
    total_cost: float
    profit: dict[str, float]
    deficit: dict[str, float]
    total_deficit: float
    feasible: bool


@dataclass(frozen=True)
class Arm:
    arm_id: str
    proximity_removal: bool
    fairness_modified_insertion: bool


ARMS = (
    Arm("BASE", False, False),
    Arm("PROX_ONLY", True, False),
    Arm("FAIR_ONLY", False, True),
    Arm("PROX_FAIR", True, True),
)


class EvaluationBudget:
    """Counts complete assignment evaluations and rejects overshoot."""

    def __init__(self, limit: int) -> None:
        if limit not in {0, 1, 2, 5}:
            raise ValueError("Only the preregistered budgets 0/1/2/5 are allowed.")
        self.limit = limit
        self.used = 0

    def consume(self) -> None:
        if self.used >= self.limit:
            raise RuntimeError("complete evaluation budget exhausted")
        self.used += 1


def build_micro_problem() -> MicroProblem:
    """Returns a fixed artificial case, not a China or formal benchmark case."""

    return MicroProblem(
        depots_xy={"A": (0.0, 0.0), "B": (10.0, 0.0), "C": (5.0, 8.0)},
        customers=(
            Customer("c1", 2.0, 0.0, 12.0, {"A": 1.0, "B": 7.0, "C": 5.0}),
            Customer("c2", 3.0, 1.0, 12.0, {"A": 2.0, "B": 6.0, "C": 5.5}),
            Customer("c3", 5.5, 1.0, 12.0, {"A": 3.0, "B": 4.0, "C": 4.5}),
            Customer("c4", 5.0, 7.0, 12.0, {"A": 7.0, "B": 7.0, "C": 1.0}),
        ),
        initial_assignment={"c1": "A", "c2": "A", "c3": "A", "c4": "C"},
        standalone_profit={"A": 20.0, "B": 20.0, "C": 20.0},
        theta=0.8,
    )


def evaluate_assignment(
    problem: MicroProblem,
    assignment: dict[str, str],
) -> Evaluation:
    """Complete evaluator used by the prototype search."""

    expected = set(problem.customer_by_id)
    feasible = set(assignment) == expected and all(
        depot in DEPOTS for depot in assignment.values()
    )
    if not feasible:
        return Evaluation(dict(assignment), float("inf"), {}, {}, float("inf"), False)

    profit = {depot: 0.0 for depot in DEPOTS}
    total_cost = 0.0
    for customer_id, depot in assignment.items():
        customer = problem.customer_by_id[customer_id]
        cost = customer.service_cost[depot]
        total_cost += cost
        profit[depot] += customer.revenue - cost

    deficit = {
        depot: max(
            0.0,
            problem.theta * problem.standalone_profit[depot] - profit[depot],
        )
        for depot in DEPOTS
    }
    return Evaluation(
        assignment=dict(assignment),
        total_cost=total_cost,
        profit=profit,
        deficit=deficit,
        total_deficit=sum(deficit.values()),
        feasible=True,
    )


def normalized_deficit(
    depot: str,
    deficit: dict[str, float],
    standalone_profit: dict[str, float],
) -> float:
    denominator = standalone_profit[depot]
    if denominator <= 0:
        raise ValueError("standalone profit must be positive in this micro-probe")
    return deficit[depot] / denominator


def fairness_modified_insertion_score(
    *,
    base_cost_delta: float,
    recipient_profit_gain: float,
    recipient: str,
    deficit: dict[str, float],
    standalone_profit: dict[str, float],
) -> float:
    """Soriano-style direction term, independently reimplemented.

    The exact score is a transparent probe construction rather than a claim
    that this is the paper's literal coefficient formula.
    """

    direction = normalized_deficit(recipient, deficit, standalone_profit)
    return base_cost_delta - direction * max(0.0, recipient_profit_gain)


def proximity_removal_order(
    problem: MicroProblem,
    assignment: dict[str, str],
) -> list[str]:
    """Ranks customers by distance to their nearest alternative depot."""

    ranked: list[tuple[float, str]] = []
    for customer in problem.customers:
        home = assignment[customer.customer_id]
        alternative_distance = min(
            hypot(customer.x - problem.depots_xy[depot][0], customer.y - problem.depots_xy[depot][1])
            for depot in DEPOTS
            if depot != home
        )
        ranked.append((alternative_distance, customer.customer_id))
    return [customer_id for _, customer_id in sorted(ranked)]


def base_removal_order(problem: MicroProblem) -> list[str]:
    return sorted(problem.customer_by_id)


def insertion_order(
    problem: MicroProblem,
    current: Evaluation,
    customer_id: str,
    fairness_modified: bool,
) -> list[str]:
    customer = problem.customer_by_id[customer_id]
    source = current.assignment[customer_id]
    choices: list[tuple[float, str]] = []
    source_cost = customer.service_cost[source]
    for recipient in DEPOTS:
        if recipient == source:
            continue
        base_delta = customer.service_cost[recipient] - source_cost
        recipient_gain = customer.revenue - customer.service_cost[recipient]
        score = base_delta
        if fairness_modified:
            score = fairness_modified_insertion_score(
                base_cost_delta=base_delta,
                recipient_profit_gain=recipient_gain,
                recipient=recipient,
                deficit=current.deficit,
                standalone_profit=problem.standalone_profit,
            )
        choices.append((score, recipient))
    return [recipient for _, recipient in sorted(choices)]


def candidate_assignments(
    problem: MicroProblem,
    arm: Arm,
) -> Iterable[tuple[str, str, dict[str, str]]]:
    current = evaluate_assignment(problem, problem.initial_assignment)
    removals = (
        proximity_removal_order(problem, current.assignment)
        if arm.proximity_removal
        else base_removal_order(problem)
    )
    for customer_id in removals:
        for recipient in insertion_order(
            problem,
            current,
            customer_id,
            arm.fairness_modified_insertion,
        ):
            candidate = dict(current.assignment)
            candidate[customer_id] = recipient
            yield customer_id, recipient, candidate


def evaluation_key(evaluation: Evaluation) -> tuple[float, float, tuple[tuple[str, str], ...]]:
    return (
        evaluation.total_deficit,
        evaluation.total_cost,
        tuple(sorted(evaluation.assignment.items())),
    )


def run_arm(problem: MicroProblem, arm: Arm, budget_limit: int) -> dict[str, object]:
    """Runs one arm without exceeding the complete evaluation budget."""

    initial = evaluate_assignment(problem, problem.initial_assignment)
    budget = EvaluationBudget(budget_limit)
    evaluated: list[Evaluation] = []
    moves: list[str] = []
    for customer_id, recipient, assignment in candidate_assignments(problem, arm):
        if budget.used >= budget.limit:
            break
        budget.consume()
        evaluated.append(evaluate_assignment(problem, assignment))
        moves.append(f"{customer_id}->{recipient}")

    best = min((initial, *evaluated), key=evaluation_key)
    base_first = next(candidate_assignments(problem, ARMS[0]), None)
    arm_first = next(candidate_assignments(problem, arm), None)
    return {
        "arm_id": arm.arm_id,
        "budget_limit": budget.limit,
        "complete_evaluations": budget.used,
        "budget_respected": budget.used <= budget.limit,
        "candidate_count": len(evaluated),
        "moves": moves,
        "initial_total_cost": initial.total_cost,
        "initial_total_deficit": initial.total_deficit,
        "best_total_cost": best.total_cost,
        "best_total_deficit": best.total_deficit,
        "best_assignment": best.assignment,
        "best_profit": best.profit,
        "best_deficit": best.deficit,
        "proximity_operator_enabled": arm.proximity_removal,
        "fairness_operator_enabled": arm.fairness_modified_insertion,
        "first_candidate_differs_from_base": (
            arm_first is not None
            and base_first is not None
            and arm_first[:2] != base_first[:2]
        ),
    }


def deficit_magnitude_witness() -> dict[str, str]:
    """Shows that changing only deficit magnitudes changes recipient choice."""

    standalone = {"A": 20.0, "B": 20.0, "C": 20.0}

    def choose(deficit: dict[str, float]) -> str:
        scores = {
            depot: fairness_modified_insertion_score(
                base_cost_delta=4.0,
                recipient_profit_gain=6.0,
                recipient=depot,
                deficit=deficit,
                standalone_profit=standalone,
            )
            for depot in ("B", "C")
        }
        return min(scores, key=lambda depot: (scores[depot], depot))

    return {
        "larger_B_deficit_choice": choose({"A": 0.0, "B": 16.0, "C": 4.0}),
        "larger_C_deficit_choice": choose({"A": 0.0, "B": 4.0, "C": 16.0}),
    }
