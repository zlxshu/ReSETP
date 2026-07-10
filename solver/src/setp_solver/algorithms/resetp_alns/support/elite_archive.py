"""Small elite-solution archive used by diagnostic restart probes."""

from __future__ import annotations

from dataclasses import dataclass, replace
import random

from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution


@dataclass(frozen=True)
class EliteItem:
    solution: Solution
    objective: float
    signature: tuple[tuple[str, ...], ...]


class EliteArchive:
    """Keep a compact diverse set of complete feasible solutions."""

    def __init__(self, *, max_size: int = 16, diversity_min: float = 0.10) -> None:
        self.max_size = max(1, int(max_size))
        self.diversity_min = max(0.0, float(diversity_min))
        self.items: list[EliteItem] = []

    def maybe_add(self, solution: Solution, *, objective: float) -> bool:
        signature = _solution_signature(solution)
        if any(_signature_distance(signature, item.signature) < self.diversity_min for item in self.items):
            return False
        self.items.append(EliteItem(_clone_solution(solution), float(objective), signature))
        self.items.sort(key=lambda item: item.objective)
        if len(self.items) > self.max_size:
            self.items = self.items[: self.max_size]
        return True

    def propose_restart(self, rng: random.Random) -> Solution | None:
        if not self.items:
            return None
        index = rng.randrange(len(self.items))
        return _clone_solution(self.items[index].solution)


def _clone_solution(solution: Solution) -> Solution:
    return Solution(
        routes=[replace(route, node_sequence=list(route.node_sequence)) for route in solution.routes],
        charging_actions=[replace(action) for action in solution.charging_actions],
        cross_site_services=[replace(service) for service in solution.cross_site_services],
    )


def _solution_signature(solution: Solution) -> tuple[tuple[str, ...], ...]:
    return tuple(
        sorted(
            tuple(node for node in route.node_sequence if str(node).upper().startswith("C"))
            for route in solution.routes
        )
    )


def _signature_distance(left: tuple[tuple[str, ...], ...], right: tuple[tuple[str, ...], ...]) -> float:
    left_routes = {frozenset(route) for route in left}
    right_routes = {frozenset(route) for route in right}
    if not left_routes and not right_routes:
        return 0.0
    union = left_routes | right_routes
    intersection = left_routes & right_routes
    return 1.0 - (len(intersection) / max(1, len(union)))
