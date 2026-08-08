"""Literature-grounded DCREX route exchange shared by public and Duty search.

The implementation follows Lei, Hao, and Wu (2026), Algorithm 3 and Figure
A1: one main parent, several donor parents, twenty diversity ranges, five
insertion choices, and two discounted-UCB1 controllers with ``gamma=0.99``.
The paper does not publish source code.  The incremental route-pair counts in
this file are therefore an explicit, testable reconstruction of Figure A1,
not a claim of line-for-line reproduction.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, replace
from enum import Enum
from itertools import pairwise
from typing import TypeVar

Node = TypeVar("Node", bound=Hashable)


class InsertionOperator(str, Enum):
    """The five insertion actions used by DCREX."""

    FBI = "FBI"
    IBI = "IBI"
    FRI = "FRI"
    IRI = "IRI"
    RI = "RI"


INSERTION_OPERATORS = tuple(InsertionOperator)
NUM_DIVERSITY_LEVELS = 20
DISCOUNT_FACTOR = 0.99


@dataclass(frozen=True)
class RouteGene:
    """One exchangeable route and the endpoints used to score its edges."""

    route_id: Hashable
    customer_ids: tuple[Node, ...]
    start_depot: Hashable
    end_depot: Hashable
    vehicle_type: Hashable | None = None
    exchangeable: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "customer_ids", tuple(self.customer_ids))
        if len(set(self.customer_ids)) != len(self.customer_ids):
            raise ValueError("one DCREX route cannot repeat a customer")

    @property
    def undirected_edges(self) -> frozenset[frozenset[Hashable]]:
        return _undirected_edges(
            self.start_depot,
            self.customer_ids,
            self.end_depot,
        )


@dataclass(frozen=True)
class RoutePairMetrics:
    """Incremental DCREX score for replacing one current route."""

    introduced_edges: int
    redundant_customers: int
    missing_customers: int
    conflicting_customers: int
    score: int
    diversity_delta: int


@dataclass(frozen=True)
class ExchangeStep:
    donor_parent_index: int
    target_route_id: Hashable
    donor_route_id: Hashable
    metrics: RoutePairMetrics


@dataclass(frozen=True)
class DCREXResult:
    """Raw offspring before the selected insertion operator is applied."""

    routes: tuple[RouteGene, ...]
    main_parent_index: int
    diversity_level: int
    insertion_operator: InsertionOperator
    achieved_diversity: int
    steps: tuple[ExchangeStep, ...]
    redundant_customers: tuple[Node, ...]
    missing_customers: tuple[Node, ...]
    route_pair_scores: int


@dataclass(frozen=True)
class RedundancyRemovalResult:
    routes: tuple[RouteGene, ...]
    removed_customers: tuple[Node, ...]


def remove_redundant_customers(
    routes: Iterable[RouteGene],
    *,
    protected_occurrences: Iterable[tuple[Hashable, int]] = (),
) -> RedundancyRemovalResult:
    """Remove later duplicates as in the ARIX predecessor implementation.

    Dynamic locked occurrences take precedence over route order.  This keeps
    the predecessor's published source behaviour while making the private
    adapter fail closed around committed customers and locked charging trips.
    """

    rows = tuple(routes)
    protected = set(protected_occurrences)
    occurrences: dict[Node, list[tuple[int, int, bool]]] = {}
    for route_index, route in enumerate(rows):
        for position, customer in enumerate(route.customer_ids):
            occurrences.setdefault(customer, []).append(
                (
                    route_index,
                    position,
                    (route.route_id, position) in protected,
                )
            )
    removals: dict[int, set[int]] = {}
    removed: list[Node] = []
    for customer, customer_rows in occurrences.items():
        if len(customer_rows) < 2:
            continue
        protected_rows = [row for row in customer_rows if row[2]]
        if len(protected_rows) > 1:
            raise ValueError(
                f"customer {customer!r} occurs in multiple protected routes"
            )
        keeper = protected_rows[0] if protected_rows else customer_rows[0]
        for route_index, position, _is_protected in customer_rows:
            if (route_index, position) == keeper[:2]:
                continue
            removals.setdefault(route_index, set()).add(position)
            removed.append(customer)
    cleaned = tuple(
        replace(
            route,
            customer_ids=tuple(
                customer
                for position, customer in enumerate(route.customer_ids)
                if position not in removals.get(route_index, set())
            ),
        )
        if route_index in removals
        else route
        for route_index, route in enumerate(rows)
    )
    return RedundancyRemovalResult(cleaned, tuple(removed))


class DiscountedUCB1:
    """Small discounted-UCB1 bandit used by the DCREX controller."""

    def __init__(self, num_actions: int, *, gamma: float = DISCOUNT_FACTOR) -> None:
        if num_actions < 1:
            raise ValueError("discounted UCB1 needs at least one action")
        if not 0.0 < float(gamma) <= 1.0:
            raise ValueError("discount factor must be in (0, 1]")
        self.num_actions = int(num_actions)
        self.gamma = float(gamma)
        self._counts = [0.0] * self.num_actions
        self._rewards = [0.0] * self.num_actions

    @property
    def counts(self) -> tuple[float, ...]:
        return tuple(self._counts)

    @property
    def rewards(self) -> tuple[float, ...]:
        return tuple(self._rewards)

    def select(self, rng: random.Random) -> int:
        untried = [index for index, count in enumerate(self._counts) if count <= 0.0]
        if untried:
            return untried[rng.randrange(len(untried))]
        total = sum(self._counts)
        scores = [
            (self._rewards[index] / self._counts[index])
            + math.sqrt(2.0 * math.log(total) / self._counts[index])
            for index in range(self.num_actions)
        ]
        best = max(scores)
        tied = [
            index
            for index, score in enumerate(scores)
            if math.isclose(score, best, rel_tol=0.0, abs_tol=1e-15)
        ]
        return tied[rng.randrange(len(tied))]

    def update(self, action: int, reward: float) -> None:
        if not 0 <= int(action) < self.num_actions:
            raise IndexError("discounted UCB1 action is out of range")
        if not math.isfinite(float(reward)):
            raise ValueError("discounted UCB1 reward must be finite")
        self._counts = [self.gamma * value for value in self._counts]
        self._rewards = [self.gamma * value for value in self._rewards]
        self._counts[int(action)] += 1.0
        self._rewards[int(action)] += float(reward)


class DCREXController:
    """Selects the DCREX diversity range and insertion operator."""

    def __init__(self, *, gamma: float = DISCOUNT_FACTOR) -> None:
        self.diversity_bandit = DiscountedUCB1(
            NUM_DIVERSITY_LEVELS,
            gamma=gamma,
        )
        self.insertion_bandit = DiscountedUCB1(
            len(INSERTION_OPERATORS),
            gamma=gamma,
        )

    def select(self, rng: random.Random) -> tuple[int, InsertionOperator]:
        return self.select_diversity(rng), self.select_insertion(rng)

    def select_diversity(self, rng: random.Random) -> int:
        return self.diversity_bandit.select(rng)

    def select_insertion(self, rng: random.Random) -> InsertionOperator:
        return INSERTION_OPERATORS[self.insertion_bandit.select(rng)]

    def update(
        self,
        diversity_level: int,
        insertion_operator: InsertionOperator,
        reward: float,
    ) -> None:
        self.update_diversity(diversity_level, reward)
        self.update_insertion(insertion_operator, reward)

    def update_diversity(self, diversity_level: int, reward: float) -> None:
        self.diversity_bandit.update(diversity_level, reward)

    def update_insertion(
        self,
        insertion_operator: InsertionOperator,
        reward: float,
    ) -> None:
        self.insertion_bandit.update(
            INSERTION_OPERATORS.index(InsertionOperator(insertion_operator)),
            reward,
        )


def route_pair_metrics(
    current_routes: Iterable[RouteGene],
    *,
    target_route_id: Hashable,
    donor_route: RouteGene,
    customer_universe: Iterable[Node],
    previously_introduced_customers: Iterable[Node] = (),
    preserve_target_terminals: bool = False,
) -> RoutePairMetrics:
    """Scores one hypothetical replacement using Figure A1's increments.

    ``redundant_customers`` and ``missing_customers`` count only newly created
    defects relative to the current partial offspring.  This is the detail
    needed to reproduce Figure A1's second step, where an existing duplicate
    changes identity without increasing either count.
    """

    routes = tuple(current_routes)
    target = _route_by_id(routes, target_route_id)
    projected = _project_donor(
        donor_route,
        target,
        preserve_target_terminals=preserve_target_terminals,
    )
    remaining = tuple(route for route in routes if route.route_id != target_route_id)
    after = (*remaining, projected)
    before_counts = _customer_counts(routes)
    after_counts = _customer_counts(after)
    universe = set(customer_universe)

    before_redundant = sum(max(0, count - 1) for count in before_counts.values())
    after_redundant = sum(max(0, count - 1) for count in after_counts.values())
    before_missing = len(universe.difference(before_counts))
    after_missing = len(universe.difference(after_counts))
    redundant = max(0, after_redundant - before_redundant)
    missing = max(0, after_missing - before_missing)

    current_edges = set().union(*(route.undirected_edges for route in routes))
    introduced = len(projected.undirected_edges.difference(current_edges))
    conflicts = len(
        set(projected.customer_ids).intersection(previously_introduced_customers)
    )
    score = -introduced + redundant + missing + (10 * conflicts)
    return RoutePairMetrics(
        introduced_edges=introduced,
        redundant_customers=redundant,
        missing_customers=missing,
        conflicting_customers=conflicts,
        score=score,
        diversity_delta=introduced + redundant + missing,
    )


def dcrex_exchange(
    parents: tuple[tuple[RouteGene, ...], ...],
    *,
    customer_universe: Iterable[Node],
    rng: random.Random,
    controller: DCREXController,
    main_parent_index: int | None = None,
    preserve_target_terminals: bool = False,
) -> DCREXResult:
    """Builds one raw multi-parent DCREX offspring."""

    if len(parents) < 2:
        raise ValueError("DCREX requires at least two parents")
    if any(not parent for parent in parents):
        raise ValueError("DCREX parents cannot be empty")
    main_index = (
        rng.randrange(len(parents))
        if main_parent_index is None
        else int(main_parent_index)
    )
    if not 0 <= main_index < len(parents):
        raise IndexError("main parent index is out of range")
    diversity_level, insertion_operator = controller.select(rng)
    universe = tuple(dict.fromkeys(customer_universe))
    current = list(parents[main_index])
    if len({route.route_id for route in current}) != len(current):
        raise ValueError("main-parent route ids must be unique")
    available_target_ids = {route.route_id for route in current if route.exchangeable}

    scale = max(1, len(universe) + len(current))
    lower = diversity_level * scale / NUM_DIVERSITY_LEVELS
    upper = (diversity_level + 1) * scale / NUM_DIVERSITY_LEVELS
    achieved = 0
    introduced_customers: set[Node] = set()
    steps: list[ExchangeStep] = []
    route_pair_scores = 0
    donors = [index for index in range(len(parents)) if index != main_index]
    rng.shuffle(donors)

    for donor_index in donors:
        exchangeable_targets = [
            route
            for route in current
            if route.exchangeable and route.route_id in available_target_ids
        ]
        exchangeable_donors = [
            route for route in parents[donor_index] if route.exchangeable
        ]
        if not exchangeable_targets or not exchangeable_donors:
            continue
        current_counts = _customer_counts(current)
        current_customers = frozenset(current_counts)
        current_unique_customers = frozenset(
            customer for customer, count in current_counts.items() if count == 1
        )
        current_redundant_customers = frozenset(
            customer for customer, count in current_counts.items() if count >= 2
        )
        current_edges = set().union(*(route.undirected_edges for route in current))
        target_customer_sets = {
            target.route_id: frozenset(target.customer_ids)
            for target in exchangeable_targets
        }
        donor_customer_sets = {
            id(donor): frozenset(donor.customer_ids) for donor in exchangeable_donors
        }
        donor_edges = {
            id(donor): donor.undirected_edges for donor in exchangeable_donors
        }
        donor_conflicts = {
            id(donor): len(
                donor_customer_sets[id(donor)].intersection(introduced_customers)
            )
            for donor in exchangeable_donors
        }
        projected_edge_cache: dict[
            tuple[Hashable, Hashable, Hashable],
            frozenset[frozenset[Hashable]],
        ] = {}
        shortlist = []
        for target in exchangeable_targets:
            target_customers = target_customer_sets[target.route_id]
            for donor in exchangeable_donors:
                if _projection_is_identity(
                    donor,
                    target,
                    preserve_target_terminals=preserve_target_terminals,
                ):
                    # An exchange neighbourhood contains only moves that
                    # change the offspring.  Keeping exact identity pairs in
                    # the top-five shortlist can turn a high-diversity DCREX
                    # call into a zero-change generation when parents have
                    # mostly converged.
                    continue
                route_pair_scores += 1
                donor_customers = donor_customer_sets[id(donor)]
                donor_only = donor_customers.difference(target_customers)
                target_only = target_customers.difference(donor_customers)
                redundancy_delta = len(
                    donor_only.intersection(current_customers)
                ) - len(target_only.intersection(current_redundant_customers))
                missing_delta = len(
                    target_only.intersection(current_unique_customers)
                ) - len(donor_only.difference(current_customers))
                if preserve_target_terminals:
                    edge_key = (
                        target.start_depot,
                        target.end_depot,
                        id(donor),
                    )
                    projected_edges = projected_edge_cache.get(edge_key)
                    if projected_edges is None:
                        projected_edges = _undirected_edges(
                            target.start_depot,
                            donor.customer_ids,
                            target.end_depot,
                        )
                        projected_edge_cache[edge_key] = projected_edges
                else:
                    projected_edges = donor_edges[id(donor)]
                introduced = len(projected_edges.difference(current_edges))
                redundant = max(0, redundancy_delta)
                missing = max(0, missing_delta)
                conflicts = donor_conflicts[id(donor)]
                score = -introduced + redundant + missing + (10 * conflicts)
                key = (
                    score,
                    repr(target.route_id),
                    repr(donor.route_id),
                )
                candidate = (
                    key,
                    target,
                    donor,
                    introduced,
                    redundant,
                    missing,
                    conflicts,
                )
                if len(shortlist) < 5:
                    shortlist.append(candidate)
                    shortlist.sort(key=lambda item: item[0])
                elif key < shortlist[-1][0]:
                    shortlist[-1] = candidate
                    shortlist.sort(key=lambda item: item[0])
        if not shortlist:
            continue
        (
            _key,
            target,
            donor,
            introduced,
            redundant,
            missing,
            conflicts,
        ) = shortlist[rng.randrange(len(shortlist))]
        metrics = RoutePairMetrics(
            introduced_edges=introduced,
            redundant_customers=redundant,
            missing_customers=missing,
            conflicting_customers=conflicts,
            score=-introduced + redundant + missing + (10 * conflicts),
            diversity_delta=introduced + redundant + missing,
        )
        projected = _project_donor(
            donor,
            target,
            preserve_target_terminals=preserve_target_terminals,
        )
        current = [
            projected if route.route_id == target.route_id else route
            for route in current
        ]
        available_target_ids.remove(target.route_id)
        introduced_customers.update(projected.customer_ids)
        achieved += metrics.diversity_delta
        steps.append(
            ExchangeStep(
                donor_parent_index=donor_index,
                target_route_id=target.route_id,
                donor_route_id=donor.route_id,
                metrics=metrics,
            )
        )
        if achieved >= upper:
            continue
        if achieved >= lower:
            break

    counts = _customer_counts(current)
    redundant = tuple(
        customer for customer, count in counts.items() for _ in range(max(0, count - 1))
    )
    missing = tuple(customer for customer in universe if counts[customer] == 0)
    return DCREXResult(
        routes=tuple(current),
        main_parent_index=main_index,
        diversity_level=diversity_level,
        insertion_operator=insertion_operator,
        achieved_diversity=achieved,
        steps=tuple(steps),
        redundant_customers=redundant,
        missing_customers=missing,
        route_pair_scores=route_pair_scores,
    )


def percentage_reward(parent_cost: float, child_cost: float) -> float:
    """Algorithm 3 reward: percentage improvement over the main parent."""

    if not math.isfinite(float(parent_cost)) or not math.isfinite(float(child_cost)):
        raise ValueError("DCREX reward costs must be finite")
    if float(parent_cost) <= 0.0:
        raise ValueError("DCREX percentage reward needs a positive parent cost")
    return 100.0 * (float(parent_cost) - float(child_cost)) / float(parent_cost)


def _project_donor(
    donor: RouteGene,
    target: RouteGene,
    *,
    preserve_target_terminals: bool,
) -> RouteGene:
    if preserve_target_terminals:
        return replace(
            target,
            customer_ids=donor.customer_ids,
        )
    return replace(donor, route_id=target.route_id)


def _projection_is_identity(
    donor: RouteGene,
    target: RouteGene,
    *,
    preserve_target_terminals: bool,
) -> bool:
    if preserve_target_terminals:
        return donor.customer_ids == target.customer_ids
    return (
        donor.customer_ids == target.customer_ids
        and donor.start_depot == target.start_depot
        and donor.end_depot == target.end_depot
        and donor.vehicle_type == target.vehicle_type
        and donor.exchangeable == target.exchangeable
    )


def _undirected_edges(
    start_depot: Hashable,
    customer_ids: Iterable[Hashable],
    end_depot: Hashable,
) -> frozenset[frozenset[Hashable]]:
    visits = (start_depot, *customer_ids, end_depot)
    return frozenset(
        frozenset((left, right)) for left, right in pairwise(visits) if left != right
    )


def _route_by_id(
    routes: tuple[RouteGene, ...],
    route_id: Hashable,
) -> RouteGene:
    matches = [route for route in routes if route.route_id == route_id]
    if len(matches) != 1:
        raise ValueError("target route id must identify exactly one current route")
    return matches[0]


def _customer_counts(routes: Iterable[RouteGene]) -> Counter:
    return Counter(customer for route in routes for customer in route.customer_ids)
