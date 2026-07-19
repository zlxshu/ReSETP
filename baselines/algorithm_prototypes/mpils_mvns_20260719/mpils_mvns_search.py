"""MPILS-MVNS shared-loop search for the V13 development gates.

The implementation keeps PyVRP 0.13.4 ILS as the only mother trajectory.
All ReSETP mechanisms are resident and consulted on every call.  A mechanism
that is absent from an original public instance records a semantic no-op; it
is never disabled through an algorithm switch.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import time
from typing import Any, Iterable

import pyvrp
from pyvrp import Route, Solution


RESPONSIBILITY = "multidepot_responsibility"
FLEET_CHARGE = "fleet_charge"
CARBON_TIME = "carbon_tariff_timing"
FAIRNESS = "profit_fairness"
DYNAMIC = "dynamic_replanning"
MECHANISM_ORDER = (
    RESPONSIBILITY,
    FLEET_CHARGE,
    CARBON_TIME,
    FAIRNESS,
    DYNAMIC,
)

APPLICABLE_ACTION_AVAILABLE = "APPLICABLE_ACTION_AVAILABLE"
APPLICABLE_NO_ACTION = "APPLICABLE_NO_ACTION"
NOT_APPLICABLE = "NOT_APPLICABLE_MISSING_INSTANCE_SEMANTICS"


@dataclass(frozen=True)
class MechanismContext:
    """Instance semantics visible to the always-resident mechanism registry."""

    multidepot_responsibility: bool
    fleet_charge: bool
    carbon_tariff_timing: bool
    profit_fairness: bool
    dynamic_replanning: bool
    source: str

    @classmethod
    def from_public_v13(
        cls,
        data: pyvrp.ProblemData,
    ) -> "MechanismContext":
        return cls(
            multidepot_responsibility=data.num_depots > 1,
            fleet_charge=False,
            carbon_tariff_timing=False,
            profit_fairness=False,
            dynamic_replanning=False,
            source="ORIGINAL_V13_SCHEMA",
        )

    def applicable(self, mechanism_id: str) -> bool:
        return bool(getattr(self, mechanism_id))


class MechanismLedger:
    """Counts every mechanism consultation and its semantic outcome."""

    def __init__(self) -> None:
        self._consultations = Counter({key: 0 for key in MECHANISM_ORDER})
        self._statuses = {
            key: Counter(
                {
                    APPLICABLE_ACTION_AVAILABLE: 0,
                    APPLICABLE_NO_ACTION: 0,
                    NOT_APPLICABLE: 0,
                }
            )
            for key in MECHANISM_ORDER
        }
        self._applicable_this_call: tuple[str, ...] = ()
        self._open_call = False

    def begin_call(self, context: MechanismContext) -> None:
        if self._open_call:
            raise RuntimeError("mechanism consultation call already open")
        applicable: list[str] = []
        for mechanism_id in MECHANISM_ORDER:
            self._consultations[mechanism_id] += 1
            if context.applicable(mechanism_id):
                applicable.append(mechanism_id)
            else:
                self._statuses[mechanism_id][NOT_APPLICABLE] += 1
        self._applicable_this_call = tuple(applicable)
        self._open_call = True

    def finish_call(self, action_mechanism: str | None = None) -> None:
        if not self._open_call:
            raise RuntimeError("no open mechanism consultation call")
        if (
            action_mechanism is not None
            and action_mechanism not in self._applicable_this_call
        ):
            raise ValueError(
                f"action mechanism was not applicable: {action_mechanism}"
            )
        for mechanism_id in self._applicable_this_call:
            status = (
                APPLICABLE_ACTION_AVAILABLE
                if mechanism_id == action_mechanism
                else APPLICABLE_NO_ACTION
            )
            self._statuses[mechanism_id][status] += 1
        self._applicable_this_call = ()
        self._open_call = False

    def diagnostics(self, context: MechanismContext) -> dict[str, Any]:
        if self._open_call:
            raise RuntimeError("cannot report an unfinished mechanism call")
        return {
            "registry_policy": (
                "ALWAYS_RESIDENT_SEMANTIC_DISPATCH_NO_DISABLE_SWITCH"
            ),
            "context_source": context.source,
            "mechanism_order": list(MECHANISM_ORDER),
            "consultations": dict(self._consultations),
            "status_counts": {
                key: dict(value)
                for key, value in self._statuses.items()
            },
        }


def _route_records(
    solution: Solution,
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    return tuple(
        (
            int(route.vehicle_type()),
            tuple(int(client) for client in route.visits()),
        )
        for route in solution.routes()
    )


def canonical_signature(
    solution: Solution,
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    return tuple(sorted(_route_records(solution)))


def depot_signature(solution: Solution) -> tuple[tuple[int, int], ...]:
    counts: Counter[int] = Counter(
        int(route.start_depot()) for route in solution.routes()
    )
    return tuple(sorted(counts.items()))


def _edge(left: int, right: int) -> tuple[int, int]:
    return (left, right) if left <= right else (right, left)


def edge_signature(solution: Solution) -> frozenset[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for route in solution.routes():
        path = [
            int(route.start_depot()),
            *[int(client) for client in route.visits()],
            int(route.end_depot()),
        ]
        edges.update(
            _edge(left, right)
            for left, right in zip(path, path[1:], strict=False)
        )
    return frozenset(edges)


def _complete_feasible(solution: Solution) -> bool:
    return (
        solution.is_complete()
        and solution.is_feasible()
        and solution.num_missing_clients() == 0
    )


@dataclass(frozen=True)
class PopulationEntry:
    solution: Solution
    distance: int
    signature: tuple[tuple[int, tuple[int, ...]], ...]
    depot_signature: tuple[tuple[int, int], ...]
    edges: frozenset[tuple[int, int]]


class MultiPopulationArchive:
    """Three small populations with distinct, auditable selection roles."""

    def __init__(self, per_population_limit: int = 4) -> None:
        if per_population_limit <= 0:
            raise ValueError("per_population_limit must be positive")
        self.limit = int(per_population_limit)
        self.quality: list[PopulationEntry] = []
        self.depot: list[PopulationEntry] = []
        self.diversity: list[PopulationEntry] = []
        self.remember_calls = 0
        self.unique_insertions = 0

    @staticmethod
    def _entry(solution: Solution) -> PopulationEntry:
        return PopulationEntry(
            solution=solution,
            distance=int(solution.distance()),
            signature=canonical_signature(solution),
            depot_signature=depot_signature(solution),
            edges=edge_signature(solution),
        )

    @staticmethod
    def _deduplicate(
        entries: Iterable[PopulationEntry],
    ) -> list[PopulationEntry]:
        best: dict[
            tuple[tuple[int, tuple[int, ...]], ...],
            PopulationEntry,
        ] = {}
        for entry in entries:
            previous = best.get(entry.signature)
            if previous is None or entry.distance < previous.distance:
                best[entry.signature] = entry
        return list(best.values())

    def remember(self, solution: Solution) -> bool:
        self.remember_calls += 1
        if not _complete_feasible(solution):
            return False
        entry = self._entry(solution)
        known = {
            item.signature
            for item in [*self.quality, *self.depot, *self.diversity]
        }
        inserted = entry.signature not in known
        if inserted:
            self.unique_insertions += 1

        quality = self._deduplicate([*self.quality, entry])
        self.quality = sorted(
            quality,
            key=lambda item: (item.distance, item.signature),
        )[: self.limit]

        by_depot: dict[tuple[tuple[int, int], ...], PopulationEntry] = {
            item.depot_signature: item for item in self.depot
        }
        previous = by_depot.get(entry.depot_signature)
        if previous is None or entry.distance < previous.distance:
            by_depot[entry.depot_signature] = entry
        self.depot = sorted(
            by_depot.values(),
            key=lambda item: (item.distance, item.depot_signature),
        )[: self.limit]

        diversity = self._deduplicate([*self.diversity, entry])
        reference = self.quality[0].edges
        self.diversity = sorted(
            diversity,
            key=lambda item: (
                -len(reference.symmetric_difference(item.edges)),
                item.distance,
                item.signature,
            ),
        )[: self.limit]
        return inserted

    def donor(
        self,
        current: Solution,
    ) -> PopulationEntry | None:
        current_edges = edge_signature(current)
        current_signature = canonical_signature(current)
        candidates = self._deduplicate(
            [*self.quality, *self.depot, *self.diversity]
        )
        candidates = [
            item for item in candidates
            if item.signature != current_signature
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                len(current_edges.symmetric_difference(item.edges)),
                -item.distance,
            ),
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "policy": "QUALITY_DEPOT_CONFIGURATION_EDGE_DIVERSITY",
            "per_population_limit": self.limit,
            "remember_calls": self.remember_calls,
            "unique_insertions": self.unique_insertions,
            "sizes": {
                "quality": len(self.quality),
                "depot": len(self.depot),
                "diversity": len(self.diversity),
            },
            "best_distances": {
                "quality": (
                    min(item.distance for item in self.quality)
                    if self.quality else None
                ),
                "depot": (
                    min(item.distance for item in self.depot)
                    if self.depot else None
                ),
                "diversity": (
                    min(item.distance for item in self.diversity)
                    if self.diversity else None
                ),
            },
        }


def _within_vehicle_limits(
    data: pyvrp.ProblemData,
    routes: Iterable[Route],
) -> bool:
    counts: Counter[int] = Counter(
        int(route.vehicle_type()) for route in routes
    )
    return all(
        count <= data.vehicle_type(vehicle_type).num_available
        for vehicle_type, count in counts.items()
    )


class ResponsibilitySegmentExpert:
    """Bounded two/three-client cross-depot segment relocation."""

    def __init__(
        self,
        data: pyvrp.ProblemData,
        *,
        max_source_segments: int = 12,
        max_target_routes: int = 3,
    ) -> None:
        self.data = data
        self.max_source_segments = int(max_source_segments)
        self.max_target_routes = int(max_target_routes)
        self.calls = 0
        self.source_segments_considered = 0
        self.candidate_checks = 0
        self.feasible_candidates = 0

    def _segment_rank(
        self,
        route: Route,
        start: int,
        length: int,
    ) -> tuple[int, int, int, int, int]:
        visits = list(route.visits())
        segment = visits[start : start + length]
        vehicle = self.data.vehicle_type(route.vehicle_type())
        distances = self.data.distance_matrix(vehicle.profile)
        source_depot = int(route.start_depot())
        relief = 0
        window_width = 0
        for client in segment:
            source_distance = int(distances[source_depot, client])
            nearest_other = min(
                int(distances[depot, client])
                for depot in range(self.data.num_depots)
                if depot != source_depot
            )
            relief += source_distance - nearest_other
            location = self.data.location(client)
            window_width += int(location.tw_late - location.tw_early)
        return (
            int(relief > 0),
            relief,
            -window_width,
            int(route.distance()),
            -start,
        )

    def propose(
        self,
        solution: Solution,
        cost_evaluator: Any,
        *,
        segment_length: int,
    ) -> Solution | None:
        self.calls += 1
        routes = list(solution.routes())
        ranked_segments: list[
            tuple[tuple[int, int, int, int, int], int, int]
        ] = []
        for route_index, route in enumerate(routes):
            visits = list(route.visits())
            for start in range(max(0, len(visits) - segment_length + 1)):
                ranked_segments.append(
                    (
                        self._segment_rank(
                            route,
                            start,
                            segment_length,
                        ),
                        route_index,
                        start,
                    )
                )
        ranked_segments.sort(reverse=True)
        ranked_segments = ranked_segments[: self.max_source_segments]
        self.source_segments_considered += len(ranked_segments)

        best: Solution | None = None
        best_cost: float | None = None
        for _, source_index, start in ranked_segments:
            source = routes[source_index]
            source_visits = list(source.visits())
            segment = source_visits[
                start : start + segment_length
            ]
            remaining = (
                source_visits[:start]
                + source_visits[start + segment_length :]
            )
            source_depot = int(source.start_depot())

            target_indices = [
                index for index, route in enumerate(routes)
                if (
                    index != source_index
                    and int(route.start_depot()) != source_depot
                )
            ]
            target_indices.sort(
                key=lambda index: (
                    sum(
                        int(
                            self.data.distance_matrix(
                                self.data.vehicle_type(
                                    routes[index].vehicle_type()
                                ).profile
                            )[routes[index].start_depot(), client]
                        )
                        for client in segment
                    ),
                    int(routes[index].distance()),
                    index,
                )
            )

            for target_index in target_indices[: self.max_target_routes]:
                target = routes[target_index]
                target_visits = list(target.visits())
                for ordered_segment in (
                    segment,
                    list(reversed(segment)),
                ):
                    for position in range(len(target_visits) + 1):
                        self.candidate_checks += 1
                        new_target = Route(
                            self.data,
                            [
                                *target_visits[:position],
                                *ordered_segment,
                                *target_visits[position:],
                            ],
                            target.vehicle_type(),
                        )
                        if not new_target.is_feasible():
                            continue
                        new_source = None
                        if remaining:
                            new_source = Route(
                                self.data,
                                remaining,
                                source.vehicle_type(),
                            )
                            if not new_source.is_feasible():
                                continue

                        candidate_routes: list[Route] = []
                        for index, route in enumerate(routes):
                            if index == source_index:
                                if new_source is not None:
                                    candidate_routes.append(new_source)
                            elif index == target_index:
                                candidate_routes.append(new_target)
                            else:
                                candidate_routes.append(route)
                        if not _within_vehicle_limits(
                            self.data,
                            candidate_routes,
                        ):
                            continue
                        candidate = Solution(
                            self.data,
                            candidate_routes,
                        )
                        if not _complete_feasible(candidate):
                            continue
                        self.feasible_candidates += 1
                        candidate_cost = float(
                            cost_evaluator.cost(candidate)
                        )
                        if (
                            best_cost is None
                            or candidate_cost < best_cost
                        ):
                            best = candidate
                            best_cost = candidate_cost
        return best

    def diagnostics(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "source_segments_considered": (
                self.source_segments_considered
            ),
            "candidate_checks": self.candidate_checks,
            "feasible_candidates": self.feasible_candidates,
            "max_source_segments": self.max_source_segments,
            "max_target_routes": self.max_target_routes,
        }


class EliteRouteExpert:
    """Imports one novel feasible route from a different population."""

    def __init__(
        self,
        data: pyvrp.ProblemData,
        *,
        max_donor_routes: int = 4,
    ) -> None:
        self.data = data
        self.max_donor_routes = int(max_donor_routes)
        self.calls = 0
        self.candidate_checks = 0
        self.feasible_candidates = 0

    @staticmethod
    def _route_edges(
        route: Route,
    ) -> frozenset[tuple[int, int]]:
        path = [
            int(route.start_depot()),
            *[int(client) for client in route.visits()],
            int(route.end_depot()),
        ]
        return frozenset(
            _edge(left, right)
            for left, right in zip(path, path[1:], strict=False)
        )

    def propose(
        self,
        current: Solution,
        donor: PopulationEntry,
        cost_evaluator: Any,
    ) -> Solution | None:
        self.calls += 1
        current_routes = list(current.routes())
        current_edges = edge_signature(current)
        donor_routes = list(donor.solution.routes())
        donor_routes.sort(
            key=lambda route: (
                -len(self._route_edges(route) - current_edges),
                int(route.distance()),
                int(route.vehicle_type()),
                tuple(route.visits()),
            )
        )

        best: Solution | None = None
        best_cost: float | None = None
        for donor_route in donor_routes[: self.max_donor_routes]:
            self.candidate_checks += 1
            donor_clients = set(int(x) for x in donor_route.visits())
            candidate_routes: list[Route] = []
            valid = True
            for route in current_routes:
                remaining = [
                    int(client) for client in route.visits()
                    if int(client) not in donor_clients
                ]
                if not remaining:
                    continue
                rebuilt = Route(
                    self.data,
                    remaining,
                    route.vehicle_type(),
                )
                if not rebuilt.is_feasible():
                    valid = False
                    break
                candidate_routes.append(rebuilt)
            if not valid:
                continue
            imported = Route(
                self.data,
                list(donor_route.visits()),
                donor_route.vehicle_type(),
            )
            if not imported.is_feasible():
                continue
            candidate_routes.append(imported)
            if not _within_vehicle_limits(self.data, candidate_routes):
                continue
            candidate = Solution(self.data, candidate_routes)
            if (
                not _complete_feasible(candidate)
                or canonical_signature(candidate)
                == canonical_signature(current)
            ):
                continue
            self.feasible_candidates += 1
            candidate_cost = float(cost_evaluator.cost(candidate))
            if best_cost is None or candidate_cost < best_cost:
                best = candidate
                best_cost = candidate_cost
        return best

    def diagnostics(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "candidate_checks": self.candidate_checks,
            "feasible_candidates": self.feasible_candidates,
            "max_donor_routes": self.max_donor_routes,
        }


class MPILSMVNSSearch:
    """PyVRP local search plus sparse, shared-state mechanism VNS."""

    def __init__(
        self,
        base_search: Any,
        expert_search: Any,
        *,
        data: pyvrp.ProblemData,
        context: MechanismContext,
        initial_solution: Solution | None = None,
        stagnation_threshold: int = 128,
        population_limit: int = 4,
    ) -> None:
        if stagnation_threshold <= 0:
            raise ValueError("stagnation_threshold must be positive")
        self.base_search = base_search
        self.expert_search = expert_search
        self.data = data
        self.context = context
        self.stagnation_threshold = int(stagnation_threshold)
        self.archive = MultiPopulationArchive(population_limit)
        self.ledger = MechanismLedger()
        self.segment_expert = ResponsibilitySegmentExpert(data)
        self.route_expert = EliteRouteExpert(data)
        self.calls = 0
        self.stagnation = 0
        self.triggers = 0
        self.accepted = 0
        self.best_observed_cost: float | None = None
        self.expert_seconds = 0.0
        self.neighbourhood_calls = Counter(
            {
                "ordinary_pyvrp_local_search": 0,
                "responsibility_segment": 0,
                "elite_route_recombination": 0,
            }
        )
        if initial_solution is not None:
            self.archive.remember(initial_solution)

    def __call__(
        self,
        solution: Solution,
        cost_evaluator: Any,
        exhaustive: bool = False,
    ) -> Solution:
        self.calls += 1
        self.ledger.begin_call(self.context)
        action_mechanism: str | None = None
        try:
            ordinary = self.base_search(
                solution,
                cost_evaluator,
                exhaustive=exhaustive,
            )
            self.neighbourhood_calls[
                "ordinary_pyvrp_local_search"
            ] += 1
            self.archive.remember(ordinary)

            ordinary_cost = float(
                cost_evaluator.penalised_cost(ordinary)
            )
            if (
                self.best_observed_cost is None
                or ordinary_cost < self.best_observed_cost
            ):
                self.best_observed_cost = ordinary_cost
                self.stagnation = 0
            else:
                self.stagnation += 1

            trigger_due = (
                self.context.multidepot_responsibility
                and self.stagnation >= self.stagnation_threshold
                and (
                    self.stagnation - self.stagnation_threshold
                ) % self.stagnation_threshold
                == 0
            )
            if not trigger_due:
                return ordinary

            started = time.perf_counter()
            self.triggers += 1
            candidate: Solution | None = None
            mechanism_base = ordinary
            if (
                not _complete_feasible(mechanism_base)
                and self.archive.quality
            ):
                mechanism_base = self.archive.quality[0].solution
            use_segment = self.triggers % 2 == 1
            if use_segment:
                self.neighbourhood_calls[
                    "responsibility_segment"
                ] += 1
                candidate = self.segment_expert.propose(
                    mechanism_base,
                    cost_evaluator,
                    segment_length=(
                        2 if self.triggers % 4 in {1, 2} else 3
                    ),
                )
            else:
                donor = self.archive.donor(mechanism_base)
                if donor is not None:
                    self.neighbourhood_calls[
                        "elite_route_recombination"
                    ] += 1
                    candidate = self.route_expert.propose(
                        mechanism_base,
                        donor,
                        cost_evaluator,
                    )
                if candidate is None:
                    self.neighbourhood_calls[
                        "responsibility_segment"
                    ] += 1
                    candidate = self.segment_expert.propose(
                        mechanism_base,
                        cost_evaluator,
                        segment_length=3,
                    )

            if candidate is None:
                self.expert_seconds += (
                    time.perf_counter() - started
                )
                return ordinary

            action_mechanism = RESPONSIBILITY
            refined = self.expert_search(
                candidate,
                cost_evaluator,
                exhaustive=True,
            )
            self.archive.remember(refined)
            refined_cost = float(
                cost_evaluator.penalised_cost(refined)
            )
            if (
                _complete_feasible(refined)
                and refined_cost < ordinary_cost
            ):
                self.accepted += 1
                self.stagnation = 0
                self.best_observed_cost = min(
                    refined_cost,
                    self.best_observed_cost,
                )
                self.expert_seconds += (
                    time.perf_counter() - started
                )
                return refined

            self.expert_seconds += time.perf_counter() - started
            return ordinary
        finally:
            self.ledger.finish_call(action_mechanism)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "algorithm": "MPILS-MVNS",
            "shared_loop": True,
            "mother": "PyVRP-0.13.4-ILS",
            "calls": self.calls,
            "stagnation_threshold": self.stagnation_threshold,
            "final_stagnation": self.stagnation,
            "expert_triggers": self.triggers,
            "expert_accepted": self.accepted,
            "expert_seconds": self.expert_seconds,
            "neighbourhood_calls": dict(self.neighbourhood_calls),
            "mechanisms": self.ledger.diagnostics(self.context),
            "populations": self.archive.diagnostics(),
            "responsibility_segment": (
                self.segment_expert.diagnostics()
            ),
            "elite_route": self.route_expert.diagnostics(),
        }
