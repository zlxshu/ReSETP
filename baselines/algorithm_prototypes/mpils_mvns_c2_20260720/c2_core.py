"""Core components for the MPILS-MVNS-C2-R1 engineering gate."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import random
import time
from typing import Any, Iterable

import pyvrp
from pyvrp import Route, Solution

from event_driven_ils import (
    IterationEvent,
    SearchDirective,
)


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

ACTION_AVAILABLE = "APPLICABLE_ACTION_AVAILABLE"
NO_ACTION = "APPLICABLE_NO_ACTION"
NOT_APPLICABLE = "NOT_APPLICABLE_MISSING_INSTANCE_SEMANTICS"


@dataclass(frozen=True)
class MechanismContext:
    """Instance semantics visible to the resident mechanism registry."""

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
            source="ORIGINAL_V13_SCHEMA_NO_SYNTHETIC_MECHANISMS",
        )

    def applicable(self, mechanism_id: str) -> bool:
        return bool(getattr(self, mechanism_id))


class EventMechanismLedger:
    """Sparse consultations: once at startup and once per C2 trigger."""

    def __init__(self) -> None:
        self.consultations = Counter(
            {mechanism: 0 for mechanism in MECHANISM_ORDER}
        )
        self.statuses = {
            mechanism: Counter(
                {
                    ACTION_AVAILABLE: 0,
                    NO_ACTION: 0,
                    NOT_APPLICABLE: 0,
                }
            )
            for mechanism in MECHANISM_ORDER
        }

    def consult(
        self,
        context: MechanismContext,
        *,
        action_mechanism: str | None,
    ) -> None:
        if (
            action_mechanism is not None
            and not context.applicable(action_mechanism)
        ):
            raise ValueError("action mechanism is not applicable")
        for mechanism in MECHANISM_ORDER:
            self.consultations[mechanism] += 1
            if not context.applicable(mechanism):
                self.statuses[mechanism][NOT_APPLICABLE] += 1
            elif mechanism == action_mechanism:
                self.statuses[mechanism][ACTION_AVAILABLE] += 1
            else:
                self.statuses[mechanism][NO_ACTION] += 1

    def diagnostics(self, context: MechanismContext) -> dict[str, Any]:
        return {
            "policy": (
                "ALWAYS_RESIDENT_EVENT_DRIVEN_SEMANTIC_DISPATCH"
            ),
            "context_source": context.source,
            "mechanism_order": list(MECHANISM_ORDER),
            "consultations": dict(self.consultations),
            "status_counts": {
                mechanism: dict(counts)
                for mechanism, counts in self.statuses.items()
            },
        }


def route_records(
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
    return tuple(sorted(route_records(solution)))


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


def normalised_edge_distance(left: Solution, right: Solution) -> float:
    left_edges = edge_signature(left)
    right_edges = edge_signature(right)
    denominator = max(1, len(left_edges | right_edges))
    return len(left_edges ^ right_edges) / denominator


def complete_feasible(solution: Solution) -> bool:
    return (
        solution.is_complete()
        and solution.is_feasible()
        and solution.num_missing_clients() == 0
    )


@dataclass(frozen=True)
class EliteEntry:
    solution: Solution
    objective: int
    signature: tuple[tuple[int, tuple[int, ...]], ...]
    depot_signature: tuple[tuple[int, int], ...]
    edges: frozenset[tuple[int, int]]
    reason: str


class SharedEliteBank:
    """One small bank, exposed through three lazy selection views."""

    def __init__(self, limit: int = 8) -> None:
        if limit <= 0:
            raise ValueError("elite-bank limit must be positive")
        self.limit = int(limit)
        self.entries: list[EliteEntry] = []
        self.remember_calls = 0
        self.unique_insertions = 0
        self.reasons: Counter[str] = Counter()

    def _entry(
        self,
        solution: Solution,
        cost_evaluator: Any,
        reason: str,
    ) -> EliteEntry:
        return EliteEntry(
            solution=solution,
            objective=int(cost_evaluator.penalised_cost(solution)),
            signature=canonical_signature(solution),
            depot_signature=depot_signature(solution),
            edges=edge_signature(solution),
            reason=reason,
        )

    def _trim(self) -> None:
        if len(self.entries) <= self.limit:
            return

        by_quality = sorted(
            self.entries,
            key=lambda entry: (entry.objective, entry.signature),
        )
        selected: dict[
            tuple[tuple[int, tuple[int, ...]], ...],
            EliteEntry,
        ] = {entry.signature: entry for entry in by_quality[:2]}

        by_depot: dict[
            tuple[tuple[int, int], ...],
            EliteEntry,
        ] = {}
        for entry in by_quality:
            by_depot.setdefault(entry.depot_signature, entry)
        for entry in by_depot.values():
            if len(selected) >= self.limit:
                break
            selected.setdefault(entry.signature, entry)

        reference = by_quality[0].edges
        by_diversity = sorted(
            self.entries,
            key=lambda entry: (
                -len(reference ^ entry.edges),
                entry.objective,
                entry.signature,
            ),
        )
        for entry in by_diversity:
            if len(selected) >= self.limit:
                break
            selected.setdefault(entry.signature, entry)

        for entry in by_quality:
            if len(selected) >= self.limit:
                break
            selected.setdefault(entry.signature, entry)
        self.entries = list(selected.values())

    def remember(
        self,
        solution: Solution,
        cost_evaluator: Any,
        *,
        reason: str,
    ) -> bool:
        self.remember_calls += 1
        self.reasons[reason] += 1
        if not complete_feasible(solution):
            return False

        entry = self._entry(solution, cost_evaluator, reason)
        for index, previous in enumerate(self.entries):
            if previous.signature != entry.signature:
                continue
            if entry.objective < previous.objective:
                self.entries[index] = entry
            return False

        self.entries.append(entry)
        self.unique_insertions += 1
        self._trim()
        return True

    def diagnostics(self) -> dict[str, Any]:
        if not self.entries:
            view_sizes = {"quality": 0, "depot": 0, "edge": 0}
        else:
            depot_views = {
                entry.depot_signature for entry in self.entries
            }
            reference = min(
                self.entries,
                key=lambda entry: entry.objective,
            ).edges
            edge_views = {
                len(reference ^ entry.edges) for entry in self.entries
            }
            view_sizes = {
                "quality": len(self.entries),
                "depot": len(depot_views),
                "edge": len(edge_views),
            }
        return {
            "policy": "ONE_BANK_THREE_LAZY_VIEWS",
            "limit": self.limit,
            "size": len(self.entries),
            "remember_calls": self.remember_calls,
            "unique_insertions": self.unique_insertions,
            "reasons": dict(self.reasons),
            "view_sizes": view_sizes,
            "best_objective": (
                min(entry.objective for entry in self.entries)
                if self.entries
                else None
            ),
        }


def within_vehicle_limits(
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


@dataclass(frozen=True)
class PositionProposal:
    source_index: int
    source_start: int
    segment_length: int
    target_index: int
    target_position: int
    ordered_segment: tuple[int, ...]
    access_relief: int
    distance_delta: int
    tie_breaker: int

    @property
    def rank_key(self) -> tuple[int, int, int]:
        return (
            -self.access_relief,
            self.distance_delta,
            self.tie_breaker,
        )


class BoundedCrossDepotSegmentOperator:
    """Public V13 operator using only native depot/TW/load/distance data."""

    def __init__(
        self,
        data: pyvrp.ProblemData,
        *,
        seed: int,
        max_source_segments: int = 64,
        max_positions_per_source: int = 6,
        max_route_evaluations: int = 48,
        max_full_evaluations: int = 12,
    ) -> None:
        self.data = data
        self.random = random.Random(seed)
        self.max_source_segments = int(max_source_segments)
        self.max_positions_per_source = int(max_positions_per_source)
        self.max_route_evaluations = int(max_route_evaluations)
        self.max_full_evaluations = int(max_full_evaluations)
        self.calls = 0
        self.source_segments_considered = 0
        self.positions_shortlisted = 0
        self.route_evaluations = 0
        self.full_evaluations = 0
        self.feasible_candidates = 0
        self.segment_moves_applied = 0

    def _path_distance(
        self,
        profile: int,
        path: list[int],
    ) -> int:
        matrix = self.data.distance_matrix(profile)
        return sum(
            int(matrix[left, right])
            for left, right in zip(path, path[1:], strict=False)
        )

    def _source_rank(
        self,
        route: Route,
        start: int,
        length: int,
    ) -> tuple[int, int, int, int]:
        visits = [int(client) for client in route.visits()]
        segment = visits[start : start + length]
        vehicle = self.data.vehicle_type(route.vehicle_type())
        matrix = self.data.distance_matrix(vehicle.profile)
        source_depot = int(route.start_depot())
        access_relief = 0
        for client in segment:
            alternatives = [
                int(matrix[depot, client])
                for depot in range(self.data.num_depots)
                if depot != source_depot
            ]
            if alternatives:
                access_relief += (
                    int(matrix[source_depot, client])
                    - min(alternatives)
                )
        window_width = sum(
            int(
                self.data.location(client).tw_late
                - self.data.location(client).tw_early
            )
            for client in segment
        )
        return (
            int(access_relief > 0),
            access_relief,
            -window_width,
            -start,
        )

    def _position_proposals(
        self,
        routes: list[Route],
        *,
        source_index: int,
        source_start: int,
        segment_length: int,
    ) -> list[PositionProposal]:
        source = routes[source_index]
        source_visits = [int(client) for client in source.visits()]
        segment = tuple(
            source_visits[
                source_start : source_start + segment_length
            ]
        )
        source_vehicle = self.data.vehicle_type(
            source.vehicle_type()
        )
        source_profile = int(source_vehicle.profile)
        source_left = (
            int(source.start_depot())
            if source_start == 0
            else source_visits[source_start - 1]
        )
        source_end = source_start + segment_length
        source_right = (
            int(source.end_depot())
            if source_end == len(source_visits)
            else source_visits[source_end]
        )
        removed_path = [source_left, *segment, source_right]
        removal_saving = (
            self._path_distance(source_profile, removed_path)
            - self._path_distance(
                source_profile,
                [source_left, source_right],
            )
        )

        proposals: list[PositionProposal] = []
        for target_index, target in enumerate(routes):
            if (
                target_index == source_index
                or int(target.start_depot())
                == int(source.start_depot())
            ):
                continue
            target_visits = [int(client) for client in target.visits()]
            target_vehicle = self.data.vehicle_type(
                target.vehicle_type()
            )
            target_profile = int(target_vehicle.profile)
            source_matrix = self.data.distance_matrix(source_profile)
            target_matrix = self.data.distance_matrix(target_profile)
            access_relief = sum(
                int(source_matrix[source.start_depot(), client])
                - int(target_matrix[target.start_depot(), client])
                for client in segment
            )
            for ordered in (segment, tuple(reversed(segment))):
                for position in range(len(target_visits) + 1):
                    left = (
                        int(target.start_depot())
                        if position == 0
                        else target_visits[position - 1]
                    )
                    right = (
                        int(target.end_depot())
                        if position == len(target_visits)
                        else target_visits[position]
                    )
                    insertion_delta = (
                        self._path_distance(
                            target_profile,
                            [left, *ordered, right],
                        )
                        - self._path_distance(
                            target_profile,
                            [left, right],
                        )
                    )
                    proposals.append(
                        PositionProposal(
                            source_index=source_index,
                            source_start=source_start,
                            segment_length=segment_length,
                            target_index=target_index,
                            target_position=position,
                            ordered_segment=ordered,
                            access_relief=access_relief,
                            distance_delta=(
                                insertion_delta - removal_saving
                            ),
                            tie_breaker=self.random.getrandbits(31),
                        )
                    )
        proposals.sort(key=lambda proposal: proposal.rank_key)
        return proposals[: self.max_positions_per_source]

    def _propose_one(
        self,
        solution: Solution,
        cost_evaluator: Any,
        *,
        segment_length: int,
        source_budget: int,
        route_budget: int,
        full_budget: int,
    ) -> Solution | None:
        routes = list(solution.routes())
        sources: list[
            tuple[tuple[int, int, int, int], int, int]
        ] = []
        for route_index, route in enumerate(routes):
            visits = list(route.visits())
            for start in range(
                max(0, len(visits) - segment_length + 1)
            ):
                sources.append(
                    (
                        self._source_rank(
                            route,
                            start,
                            segment_length,
                        ),
                        route_index,
                        start,
                    )
                )
        sources.sort(reverse=True)
        sources = sources[:source_budget]
        self.source_segments_considered += len(sources)

        proposals: list[PositionProposal] = []
        for _, source_index, source_start in sources:
            shortlisted = self._position_proposals(
                routes,
                source_index=source_index,
                source_start=source_start,
                segment_length=segment_length,
            )
            self.positions_shortlisted += len(shortlisted)
            proposals.extend(shortlisted)
        proposals.sort(key=lambda proposal: proposal.rank_key)

        best: Solution | None = None
        best_cost: int | None = None
        for proposal in proposals[:route_budget]:
            self.route_evaluations += 1
            source = routes[proposal.source_index]
            target = routes[proposal.target_index]
            source_visits = [int(client) for client in source.visits()]
            target_visits = [int(client) for client in target.visits()]
            source_end = (
                proposal.source_start + proposal.segment_length
            )
            remaining = (
                source_visits[: proposal.source_start]
                + source_visits[source_end:]
            )
            new_target_visits = (
                target_visits[: proposal.target_position]
                + list(proposal.ordered_segment)
                + target_visits[proposal.target_position :]
            )

            new_source = None
            if remaining:
                new_source = Route(
                    self.data,
                    remaining,
                    source.vehicle_type(),
                )
                if not new_source.is_feasible():
                    continue
            new_target = Route(
                self.data,
                new_target_visits,
                target.vehicle_type(),
            )
            if not new_target.is_feasible():
                continue

            candidate_routes: list[Route] = []
            for index, route in enumerate(routes):
                if index == proposal.source_index:
                    if new_source is not None:
                        candidate_routes.append(new_source)
                elif index == proposal.target_index:
                    candidate_routes.append(new_target)
                else:
                    candidate_routes.append(route)
            if not within_vehicle_limits(self.data, candidate_routes):
                continue
            if full_budget <= 0:
                break
            self.full_evaluations += 1
            full_budget -= 1
            candidate = Solution(self.data, candidate_routes)
            if not complete_feasible(candidate):
                continue
            self.feasible_candidates += 1
            candidate_cost = int(
                cost_evaluator.penalised_cost(candidate)
            )
            if best_cost is None or candidate_cost < best_cost:
                best = candidate
                best_cost = candidate_cost
        return best

    def propose(
        self,
        solution: Solution,
        cost_evaluator: Any,
        *,
        strength: int,
    ) -> Solution | None:
        self.calls += 1
        strength = min(3, max(1, int(strength)))
        source_per_step = max(
            1,
            self.max_source_segments // strength,
        )
        route_per_step = max(
            1,
            self.max_route_evaluations // strength,
        )
        full_per_step = max(
            1,
            self.max_full_evaluations // strength,
        )
        current = solution
        changed = False
        initial_full = self.full_evaluations
        for step in range(strength):
            remaining_full = (
                self.max_full_evaluations
                - (self.full_evaluations - initial_full)
            )
            if remaining_full <= 0:
                break
            candidate = self._propose_one(
                current,
                cost_evaluator,
                segment_length=2 if step == 0 else 3,
                source_budget=source_per_step,
                route_budget=route_per_step,
                full_budget=min(full_per_step, remaining_full),
            )
            if candidate is None:
                break
            current = candidate
            changed = True
            self.segment_moves_applied += 1
        return current if changed else None

    def diagnostics(self) -> dict[str, int]:
        return {
            "public_semantics": (
                "DEPOT_DISTANCE_LOAD_VEHICLE_TIME_WINDOW_ONLY"
            ),
            "proxy_policy": (
                "DEPOT_ACCESS_RELIEF_PRIMARY_DISTANCE_DELTA_SECONDARY"
            ),
            "calls": self.calls,
            "source_segments_considered": (
                self.source_segments_considered
            ),
            "positions_shortlisted": self.positions_shortlisted,
            "route_evaluations": self.route_evaluations,
            "full_evaluations": self.full_evaluations,
            "feasible_candidates": self.feasible_candidates,
            "segment_moves_applied": self.segment_moves_applied,
            "max_source_segments_per_trigger": (
                self.max_source_segments
            ),
            "max_positions_per_source": (
                self.max_positions_per_source
            ),
            "max_route_evaluations_per_trigger": (
                self.max_route_evaluations
            ),
            "max_full_evaluations_per_trigger": (
                self.max_full_evaluations
            ),
        }


class ReplacementSearchMethod:
    """Native search normally; bounded mechanism move replaces one call."""

    def __init__(
        self,
        native_search: Any,
        zero_perturbation_search: Any,
        operator: BoundedCrossDepotSegmentOperator,
    ) -> None:
        self.native_search = native_search
        self.zero_search = zero_perturbation_search
        self.operator = operator
        self.native_calls = 0
        self.zero_search_calls = 0
        self.replacement_attempts = 0
        self.replacement_successes = 0
        self.fallback_native_calls = 0
        self.last_used_replacement = False

    def __call__(
        self,
        solution: Solution,
        cost_evaluator: Any,
        exhaustive: bool = False,
    ) -> Solution:
        self.last_used_replacement = False
        self.native_calls += 1
        return self.native_search(
            solution,
            cost_evaluator,
            exhaustive=exhaustive,
        )

    def search_with_directive(
        self,
        solution: Solution,
        cost_evaluator: Any,
        *,
        exhaustive: bool,
        directive: SearchDirective,
    ) -> Solution:
        if exhaustive or not directive.use_replacement:
            return self(
                solution,
                cost_evaluator,
                exhaustive=exhaustive,
            )

        self.last_used_replacement = False
        self.replacement_attempts += 1
        proposed = self.operator.propose(
            solution,
            cost_evaluator,
            strength=directive.strength,
        )
        if proposed is None:
            self.fallback_native_calls += 1
            return self(
                solution,
                cost_evaluator,
                exhaustive=False,
            )

        self.last_used_replacement = True
        self.replacement_successes += 1
        self.zero_search_calls += 1
        return self.zero_search(
            proposed,
            cost_evaluator,
            exhaustive=False,
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "policy": "REPLACE_ONE_NATIVE_PERTURBATION_NOT_APPEND",
            "native_calls": self.native_calls,
            "zero_search_calls": self.zero_search_calls,
            "replacement_attempts": self.replacement_attempts,
            "replacement_successes": self.replacement_successes,
            "fallback_native_calls": self.fallback_native_calls,
            "operator": self.operator.diagnostics(),
        }


class C2EventController:
    """Sparse event memory plus feedback-controlled perturbation strength."""

    def __init__(
        self,
        context: MechanismContext,
        *,
        allow_replacement: bool,
        trigger_after: int = 128,
        cooldown: int = 128,
        target_edge_distance: tuple[float, float] = (0.15, 0.35),
        elite_limit: int = 8,
        force_first_replacement: bool = False,
    ) -> None:
        if trigger_after < 0 or cooldown < 0:
            raise ValueError("trigger and cooldown must be non-negative")
        lower, upper = target_edge_distance
        if not 0 <= lower <= upper <= 2:
            raise ValueError("invalid edge-distance target band")
        self.context = context
        self.allow_replacement = bool(allow_replacement)
        self.trigger_after = int(trigger_after)
        self.cooldown = int(cooldown)
        self.target_edge_distance = (float(lower), float(upper))
        self.force_first_replacement = bool(force_first_replacement)
        self.ledger = EventMechanismLedger()
        self.bank = SharedEliteBank(elite_limit)
        self.ledger.consult(context, action_mechanism=None)
        self.next_allowed_iteration = 1
        self.strength = 1
        self.triggers = 0
        self.replacement_events = 0
        self.accepted_replacements = 0
        self.best_replacements = 0
        self.edge_distances: list[float] = []
        self.hook_seconds = 0.0
        self.bank_seconds = 0.0

    def before_search(
        self,
        *,
        iteration: int,
        iterations_without_improvement: int,
        current: Solution,
        best: Solution,
        cost_evaluator: Any,
    ) -> SearchDirective:
        started = time.perf_counter()
        forced = self.force_first_replacement and self.triggers == 0
        eligible = (
            self.allow_replacement
            and self.context.multidepot_responsibility
            and iteration >= self.next_allowed_iteration
            and (
                forced
                or iterations_without_improvement >= self.trigger_after
            )
        )
        if eligible:
            self.triggers += 1
        self.hook_seconds += time.perf_counter() - started
        return SearchDirective(
            use_replacement=eligible,
            strength=self.strength,
        )

    def _remember(
        self,
        solution: Solution,
        cost_evaluator: Any,
        *,
        reason: str,
    ) -> None:
        started = time.perf_counter()
        self.bank.remember(
            solution,
            cost_evaluator,
            reason=reason,
        )
        elapsed = time.perf_counter() - started
        self.bank_seconds += elapsed

    def after_iteration(self, event: IterationEvent) -> None:
        started = time.perf_counter()
        if event.best_improved:
            self._remember(
                event.best,
                event.cost_evaluator,
                reason="GLOBAL_BEST",
            )

        if event.used_replacement:
            self.replacement_events += 1
            if event.candidate_accepted:
                self.accepted_replacements += 1
                self._remember(
                    event.current,
                    event.cost_evaluator,
                    reason="ACCEPTED_REPLACEMENT",
                )
            if event.best_improved:
                self.best_replacements += 1

            distance = normalised_edge_distance(
                event.previous_current,
                event.candidate,
            )
            self.edge_distances.append(distance)
            lower, upper = self.target_edge_distance
            if distance < lower:
                self.strength = min(3, self.strength + 1)
            elif distance > upper or not event.candidate.is_feasible():
                self.strength = max(1, self.strength - 1)
            elif event.best_improved:
                self.strength = 1
            self.next_allowed_iteration = (
                event.iteration + self.cooldown
            )
            self.ledger.consult(
                self.context,
                action_mechanism=RESPONSIBILITY,
            )
        elif self.triggers > self.replacement_events:
            self.next_allowed_iteration = (
                event.iteration + self.cooldown
            )
            self.ledger.consult(
                self.context,
                action_mechanism=None,
            )
            self.replacement_events += 1
        self.hook_seconds += time.perf_counter() - started

    def diagnostics(self) -> dict[str, Any]:
        return {
            "policy": (
                "EVENT_DRIVEN_FEEDBACK_STRENGTH_PROJECT_RULE"
            ),
            "ails_ii_boundary": (
                "feedback-control idea cited; exact rule is ReSETP design"
            ),
            "allow_replacement": self.allow_replacement,
            "trigger_after": self.trigger_after,
            "cooldown": self.cooldown,
            "target_edge_distance": list(
                self.target_edge_distance
            ),
            "final_strength": self.strength,
            "triggers": self.triggers,
            "replacement_events": self.replacement_events,
            "accepted_replacements": self.accepted_replacements,
            "best_replacements": self.best_replacements,
            "edge_distances": list(self.edge_distances),
            "hook_seconds": self.hook_seconds,
            "bank_seconds": self.bank_seconds,
            "mechanisms": self.ledger.diagnostics(self.context),
            "elite_bank": self.bank.diagnostics(),
        }
