"""Generation-side multi-depot segment moves for isolated development.

The current winning route search can reject a route-membership move before the
complete ReSETP model sees it because customer choice or insertion positions
are filtered by distance.  This module tests one narrower alternative:

* identify a contiguous segment that is currently served by the wrong depot;
* generate a move back to a route owned by the customers' home depot;
* enumerate every insertion position without a distance veto;
* choose one proposal by affected-route ReSETP cost;
* submit only that complete proposal to the common search scorer.

This is not a new cost model and it is not a formal solver.  Full candidate
scoring remains in the frozen winner loop.  Route-local scores below are an
explicitly counted screening layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from setp_solver.algorithms.resetp_alns.operators.local_search import (
    _candidate_with_route_customers,
    _route_customers,
)
from setp_solver.algorithms.resetp_alns.support.mechanism_prescription import (
    MechanismPrescription,
    MechanismSignal,
)
from setp_solver.solution import Solution
from v5_carbon_retiming_solver import carbon_aware_depot_retime
from v6_monotone_mechanism_solver import exact_joint_fleet_charge_decode
from v7_responsibility_solver import (
    _local_exact_cost,
    _route_distance,
    annotate_cross_site_services,
)


TOL = 1.0e-9
MECHANISM_ID = "responsibility_segment_generation"
Mode = Literal["mechanism", "distance"]


@dataclass(frozen=True)
class SegmentGeneratorConfig:
    """Frozen controls for SEG-GEN-01."""

    mode: Mode = "mechanism"
    min_segment_length: int = 2
    max_segment_length: int = 3
    max_source_segments: int = 10_000
    max_return_segments_per_source: int = 1
    max_completed_candidates: int = 12
    assessment_interval: int = 20
    cooldown_evaluations: int = 100
    apply_route_local_completion: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"mechanism", "distance"}:
            raise ValueError(f"unknown segment generator mode: {self.mode}")
        for name, value in (
            ("max_segment_length", self.max_segment_length),
            ("max_source_segments", self.max_source_segments),
            (
                "max_return_segments_per_source",
                self.max_return_segments_per_source,
            ),
            (
                "max_completed_candidates",
                self.max_completed_candidates,
            ),
            ("assessment_interval", self.assessment_interval),
        ):
            if int(value) < 1:
                raise ValueError(f"{name} must be positive")
        if int(self.min_segment_length) > int(
            self.max_segment_length
        ):
            raise ValueError(
                "min_segment_length exceeds max_segment_length"
            )
        if int(self.cooldown_evaluations) < 0:
            raise ValueError("cooldown_evaluations must be non-negative")


@dataclass(frozen=True)
class SegmentSource:
    source_route_index: int
    target_route_index: int
    start: int
    length: int
    customers: tuple[str, ...]
    responsibility_relief: int


@dataclass(frozen=True)
class SegmentCandidate:
    kind: str
    source: SegmentSource
    target_position: int
    solution: Solution
    distance_delta: float
    local_model_delta: float | None
    return_customers: tuple[str, ...] = ()
    return_start: int | None = None


@dataclass
class SegmentLedger:
    source_segments_scanned: int = 0
    source_segments_eligible: int = 0
    source_segments_shortlisted: int = 0
    insertion_positions_scanned: int = 0
    candidate_build_attempts: int = 0
    feasible_candidates: int = 0
    route_local_exact_evaluations: int = 0
    route_local_completion_calls: int = 0
    completion_candidates_screened: int = 0
    route_proxy_evaluations: int = 0
    route_local_schedule_evaluations: int = 0
    full_feasibility_checks: int = 0
    complete_candidate_evaluations_before_submission: int = 0
    distance_worse_model_better_candidates: int = 0
    reciprocal_pairs_scanned: int = 0
    reciprocal_pairs_shortlisted: int = 0


def has_mechanism_pressure(
    solution: Solution,
    context: Any,
    owners: dict[str, str],
    *,
    max_segment_length: int,
    min_segment_length: int = 1,
) -> tuple[bool, dict[str, Any]]:
    """Cheaply detect a wrong-depot contiguous segment."""

    segments = _source_segments(
        solution,
        context,
        owners,
        max_segment_length=max_segment_length,
        min_segment_length=min_segment_length,
        require_responsibility_relief=True,
    )
    maximum_relief = max(
        (item.responsibility_relief for item in segments),
        default=0,
    )
    return (
        bool(segments),
        {
            "eligible_segment_count": len(segments),
            "maximum_responsibility_relief": int(maximum_relief),
        },
    )


def propose_segment_move(
    solution: Solution,
    context: Any,
    owners: dict[str, str],
    *,
    config: SegmentGeneratorConfig,
) -> tuple[Solution | None, dict[str, Any]]:
    """Generate one route-membership move under the frozen mode."""

    ledger = SegmentLedger()
    source_completion: dict[str, Any] = {}
    if config.apply_route_local_completion:
        solution, source_completion = _complete_without_search(
            solution,
            context,
            ledger,
            label="source",
        )
    # Mechanism mode must be allowed to create a temporary cross-site service
    # when load-dependent fuel, fleet, or charging gains outweigh that charge.
    # Restricting the source to an already-wrong assignment reproduces the
    # responsibility-only blind spot documented in the v7 seed-2 witness.
    require_relief = False
    sources = _source_segments(
        solution,
        context,
        owners,
        max_segment_length=int(config.max_segment_length),
        min_segment_length=int(config.min_segment_length),
        require_responsibility_relief=require_relief,
    )
    ledger.source_segments_scanned = _all_source_segment_count(
        solution,
        context,
        max_segment_length=int(config.max_segment_length),
        min_segment_length=int(config.min_segment_length),
    )
    ledger.source_segments_eligible = len(sources)
    if config.mode == "mechanism":
        sources.sort(
            key=lambda item: (
                -item.responsibility_relief,
                -item.length,
                item.source_route_index,
                item.target_route_index,
                item.start,
                item.customers,
            )
        )
    else:
        sources.sort(
            key=lambda item: (
                item.source_route_index,
                item.target_route_index,
                item.start,
                item.length,
                item.customers,
            )
        )
    sources = sources[: int(config.max_source_segments)]
    ledger.source_segments_shortlisted = len(sources)

    mechanism_candidates: list[SegmentCandidate] = []
    distance_candidates: list[SegmentCandidate] = []
    route_customers = [
        _route_customers(route, context.instance)
        for route in solution.routes
    ]
    before_cost_cache: dict[tuple[int, int], float] = {}
    for source in sources:
        source_customers = route_customers[source.source_route_index]
        target_customers = route_customers[source.target_route_index]
        changed_source = [
            *source_customers[: source.start],
            *source_customers[source.start + source.length :],
        ]
        if not changed_source:
            continue
        source_route = solution.routes[source.source_route_index]
        target_route = solution.routes[source.target_route_index]
        before_distance = _route_distance(
            source_route.home_depot_id,
            source_customers,
            context,
        ) + _route_distance(
            target_route.home_depot_id,
            target_customers,
            context,
        )
        route_pair = (
            source.source_route_index,
            source.target_route_index,
        )
        for target_position in range(len(target_customers) + 1):
            ledger.insertion_positions_scanned += 1
            changed_target = [
                *target_customers[:target_position],
                *source.customers,
                *target_customers[target_position:],
            ]
            after_distance = _route_distance(
                source_route.home_depot_id,
                changed_source,
                context,
            ) + _route_distance(
                target_route.home_depot_id,
                changed_target,
                context,
            )
            distance_delta = float(after_distance - before_distance)

            if config.mode == "distance" and distance_delta >= -TOL:
                continue
            ledger.candidate_build_attempts += 1
            candidate = _candidate_with_route_customers(
                solution,
                context,
                {
                    source.source_route_index: changed_source,
                    source.target_route_index: changed_target,
                },
            )
            ledger.full_feasibility_checks += 1
            if candidate is None:
                continue
            candidate = annotate_cross_site_services(candidate, owners)
            ledger.feasible_candidates += 1

            local_delta: float | None = None
            if config.mode == "mechanism":
                before_local = before_cost_cache.get(route_pair)
                if before_local is None:
                    before_local = _local_exact_cost(
                        solution,
                        route_pair,
                        context,
                        owners,
                    )
                    before_cost_cache[route_pair] = before_local
                    ledger.route_local_exact_evaluations += 1
                after_local = _local_exact_cost(
                    candidate,
                    route_pair,
                    context,
                    owners,
                )
                ledger.route_local_exact_evaluations += 1
                local_delta = float(after_local - before_local)
                if distance_delta > TOL and local_delta < -TOL:
                    ledger.distance_worse_model_better_candidates += 1
                mechanism_candidates.append(
                    SegmentCandidate(
                        kind="relocate_segment",
                        source=source,
                        target_position=target_position,
                        solution=candidate,
                        distance_delta=distance_delta,
                        local_model_delta=local_delta,
                    )
                )
            else:
                distance_candidates.append(
                    SegmentCandidate(
                        kind="relocate_segment",
                        source=source,
                        target_position=target_position,
                        solution=candidate,
                        distance_delta=distance_delta,
                        local_model_delta=None,
                    )
                )

        return_segments = _return_segments(
            solution,
            context,
            owners,
            primary=source,
            max_segment_length=int(config.max_segment_length),
        )
        ledger.reciprocal_pairs_scanned += len(return_segments)
        return_segments = return_segments[
            : int(config.max_return_segments_per_source)
        ]
        ledger.reciprocal_pairs_shortlisted += len(return_segments)
        for return_source in return_segments:
            return_customers = route_customers[
                return_source.source_route_index
            ]
            stripped_source = [
                *source_customers[: source.start],
                *source_customers[
                    source.start + source.length :
                ],
            ]
            stripped_target = [
                *return_customers[: return_source.start],
                *return_customers[
                    return_source.start + return_source.length :
                ],
            ]
            for source_position in range(
                len(stripped_source) + 1
            ):
                for target_position in range(
                    len(stripped_target) + 1
                ):
                    ledger.insertion_positions_scanned += 1
                    changed_source = [
                        *stripped_source[:source_position],
                        *return_source.customers,
                        *stripped_source[source_position:],
                    ]
                    changed_target = [
                        *stripped_target[:target_position],
                        *source.customers,
                        *stripped_target[target_position:],
                    ]
                    after_distance = _route_distance(
                        source_route.home_depot_id,
                        changed_source,
                        context,
                    ) + _route_distance(
                        target_route.home_depot_id,
                        changed_target,
                        context,
                    )
                    distance_delta = float(
                        after_distance - before_distance
                    )
                    if (
                        config.mode == "distance"
                        and distance_delta >= -TOL
                    ):
                        continue
                    ledger.candidate_build_attempts += 1
                    candidate = _candidate_with_route_customers(
                        solution,
                        context,
                        {
                            source.source_route_index: changed_source,
                            source.target_route_index: changed_target,
                        },
                    )
                    ledger.full_feasibility_checks += 1
                    if candidate is None:
                        continue
                    candidate = annotate_cross_site_services(
                        candidate,
                        owners,
                    )
                    ledger.feasible_candidates += 1

                    local_delta = None
                    if config.mode == "mechanism":
                        before_local = before_cost_cache.get(
                            route_pair
                        )
                        if before_local is None:
                            before_local = _local_exact_cost(
                                solution,
                                route_pair,
                                context,
                                owners,
                            )
                            before_cost_cache[route_pair] = (
                                before_local
                            )
                            ledger.route_local_exact_evaluations += 1
                        after_local = _local_exact_cost(
                            candidate,
                            route_pair,
                            context,
                            owners,
                        )
                        ledger.route_local_exact_evaluations += 1
                        local_delta = float(
                            after_local - before_local
                        )
                        if (
                            distance_delta > TOL
                            and local_delta < -TOL
                        ):
                            ledger.distance_worse_model_better_candidates += 1
                        mechanism_candidates.append(
                            SegmentCandidate(
                                kind=(
                                    "reciprocal_segment_exchange"
                                ),
                                source=source,
                                target_position=target_position,
                                solution=candidate,
                                distance_delta=distance_delta,
                                local_model_delta=local_delta,
                                return_customers=(
                                    return_source.customers
                                ),
                                return_start=source_position,
                            )
                        )
                    else:
                        distance_candidates.append(
                            SegmentCandidate(
                                kind=(
                                    "reciprocal_segment_exchange"
                                ),
                                source=source,
                                target_position=target_position,
                                solution=candidate,
                                distance_delta=distance_delta,
                                local_model_delta=None,
                                return_customers=(
                                    return_source.customers
                                ),
                                return_start=source_position,
                            )
                        )

    completion_activity: list[dict[str, Any]] = []
    if (
        config.mode == "mechanism"
        and config.apply_route_local_completion
        and mechanism_candidates
    ):
        mechanism_candidates, completion_activity = (
            _complete_screened_candidates(
                solution,
                context,
                owners,
                mechanism_candidates,
                ledger,
                limit=int(config.max_completed_candidates),
            )
        )

    selected: SegmentCandidate | None
    if config.mode == "mechanism":
        improving = [
            item
            for item in mechanism_candidates
            if item.local_model_delta is not None
            and item.local_model_delta < -TOL
        ]
        selected = min(
            improving,
            key=lambda item: (
                float(item.local_model_delta),
                item.distance_delta,
                item.source.source_route_index,
                item.source.target_route_index,
                item.source.start,
                item.target_position,
            ),
            default=None,
        )
    else:
        selected = min(
            distance_candidates,
            key=lambda item: (
                item.distance_delta,
                item.source.source_route_index,
                item.source.target_route_index,
                item.source.start,
                item.target_position,
            ),
            default=None,
        )

    activity: dict[str, Any] = {
        "mode": config.mode,
        "ledger": asdict(ledger),
        "selected": None,
        "source_completion": source_completion,
    }
    if selected is None:
        activity["stop_reason"] = "no_improving_generated_candidate"
        return None, activity

    proposed = selected.solution
    selected_completion: dict[str, Any] = {}
    if (
        config.mode == "distance"
        and config.apply_route_local_completion
    ):
        proposed, selected_completion = _complete_without_search(
            proposed,
            context,
            ledger,
            label="distance_selected",
        )
    activity["ledger"] = asdict(ledger)
    activity["selected"] = {
        "kind": selected.kind,
        "source_route_index": selected.source.source_route_index,
        "target_route_index": selected.source.target_route_index,
        "segment_start": selected.source.start,
        "segment_length": selected.source.length,
        "customers": list(selected.source.customers),
        "target_position": selected.target_position,
        "return_customers": list(selected.return_customers),
        "return_start": selected.return_start,
        "responsibility_relief": selected.source.responsibility_relief,
        "distance_delta": float(selected.distance_delta),
        "local_model_delta": (
            None
            if selected.local_model_delta is None
            else float(selected.local_model_delta)
        ),
    }
    activity["completion"] = (
        completion_activity
        if config.mode == "mechanism"
        else selected_completion
    )
    activity["stop_reason"] = "proposal_generated"
    return proposed, activity


def _source_segments(
    solution: Solution,
    context: Any,
    owners: dict[str, str],
    *,
    max_segment_length: int,
    min_segment_length: int,
    require_responsibility_relief: bool,
) -> list[SegmentSource]:
    route_customers = [
        _route_customers(route, context.instance)
        for route in solution.routes
    ]
    sources: list[SegmentSource] = []
    for source_index, source_route in enumerate(solution.routes):
        customers = route_customers[source_index]
        if len(customers) <= 1:
            continue
        for target_index, target_route in enumerate(solution.routes):
            if (
                source_index == target_index
                or source_route.home_depot_id
                == target_route.home_depot_id
            ):
                continue
            for start in range(len(customers)):
                for length in range(
                    int(min_segment_length),
                    min(
                        int(max_segment_length),
                        len(customers) - start,
                    )
                    + 1,
                ):
                    if length >= len(customers):
                        continue
                    segment = tuple(customers[start : start + length])
                    before = sum(
                        owners.get(customer_id)
                        != source_route.home_depot_id
                        for customer_id in segment
                    )
                    after = sum(
                        owners.get(customer_id)
                        != target_route.home_depot_id
                        for customer_id in segment
                    )
                    relief = int(before - after)
                    if require_responsibility_relief and relief <= 0:
                        continue
                    sources.append(
                        SegmentSource(
                            source_route_index=source_index,
                            target_route_index=target_index,
                            start=start,
                            length=length,
                            customers=segment,
                            responsibility_relief=relief,
                        )
                    )
    return sources


def _all_source_segment_count(
    solution: Solution,
    context: Any,
    *,
    max_segment_length: int,
    min_segment_length: int,
) -> int:
    return len(
        _source_segments(
            solution,
            context,
            {},
            max_segment_length=max_segment_length,
            min_segment_length=min_segment_length,
            require_responsibility_relief=False,
        )
    )


def _complete_screened_candidates(
    original: Solution,
    context: Any,
    owners: dict[str, str],
    candidates: list[SegmentCandidate],
    ledger: SegmentLedger,
    *,
    limit: int,
) -> tuple[list[SegmentCandidate], list[dict[str, Any]]]:
    """Jointly complete a bounded, mechanism-diverse candidate shortlist."""

    bound = max(1, int(limit))
    by_local = sorted(
        candidates,
        key=lambda item: (
            float(
                item.local_model_delta
                if item.local_model_delta is not None
                else float("inf")
            ),
            item.distance_delta,
            item.source.source_route_index,
            item.source.target_route_index,
            item.source.start,
            item.target_position,
        ),
    )
    by_mechanism_tension = sorted(
        candidates,
        key=lambda item: (
            -item.source.responsibility_relief,
            item.distance_delta <= TOL,
            float(
                item.local_model_delta
                if item.local_model_delta is not None
                else float("inf")
            ),
            item.source.source_route_index,
            item.source.target_route_index,
            item.source.start,
            item.target_position,
        ),
    )
    shortlist: list[SegmentCandidate] = []
    seen: set[tuple[Any, ...]] = set()
    primary_count = max(1, bound // 2)
    for pool, count in (
        (by_local, primary_count),
        (by_mechanism_tension, bound - primary_count),
        (by_local, bound),
    ):
        added = 0
        for item in pool:
            key = (
                item.kind,
                item.source.source_route_index,
                item.source.target_route_index,
                item.source.start,
                item.source.length,
                item.source.customers,
                item.target_position,
                item.return_customers,
                item.return_start,
            )
            if key in seen:
                continue
            seen.add(key)
            shortlist.append(item)
            added += 1
            if len(shortlist) >= bound or added >= count:
                break
        if len(shortlist) >= bound:
            break

    completed: list[SegmentCandidate] = []
    activity: list[dict[str, Any]] = []
    before_cache: dict[tuple[int, int], float] = {}
    ledger.completion_candidates_screened += len(shortlist)
    for index, item in enumerate(shortlist):
        candidate, _, joint = exact_joint_fleet_charge_decode(
            item.solution,
            context,
            incumbent_objective=0.0,
        )
        candidate, _, carbon = carbon_aware_depot_retime(
            candidate,
            context,
            incumbent_objective=0.0,
            consume_complete_evaluation=False,
        )
        ledger.route_local_completion_calls += 1
        ledger.route_proxy_evaluations += int(
            joint.get("route_proxy_evaluations", 0)
        )
        ledger.route_local_schedule_evaluations += int(
            carbon.get("route_local_schedule_evaluations", 0)
        )
        ledger.full_feasibility_checks += int(
            joint.get("feasibility_checks", 0)
        ) + int(carbon.get("feasibility_checks", 0))
        joint_complete = int(joint.get("complete_evaluations", 0))
        carbon_complete = int(carbon.get("complete_evaluations", 0))
        if joint_complete or carbon_complete:
            raise RuntimeError(
                "segment candidate completion consumed hidden complete evaluations"
            )
        route_pair = (
            item.source.source_route_index,
            item.source.target_route_index,
        )
        before = before_cache.get(route_pair)
        if before is None:
            before = _local_exact_cost(
                original,
                route_pair,
                context,
                owners,
            )
            before_cache[route_pair] = before
            ledger.route_local_exact_evaluations += 1
        after = _local_exact_cost(
            candidate,
            route_pair,
            context,
            owners,
        )
        ledger.route_local_exact_evaluations += 1
        completed_delta = float(after - before)
        if (
            item.distance_delta > TOL
            and completed_delta < -TOL
            and (
                item.local_model_delta is None
                or item.local_model_delta >= -TOL
            )
        ):
            ledger.distance_worse_model_better_candidates += 1
        completed.append(
            replace(
                item,
                solution=candidate,
                local_model_delta=completed_delta,
            )
        )
        activity.append(
            {
                "shortlist_index": index,
                "kind": item.kind,
                "customers": list(item.source.customers),
                "return_customers": list(
                    item.return_customers
                ),
                "distance_delta": float(item.distance_delta),
                "precompletion_local_model_delta": (
                    None
                    if item.local_model_delta is None
                    else float(item.local_model_delta)
                ),
                "completed_local_model_delta": completed_delta,
                "joint_updates": int(
                    joint.get("exact_decoder_updates", 0)
                ),
                "carbon_updates": int(
                    carbon.get("exact_decoder_updates", 0)
                ),
            }
        )
    return completed, activity


def _complete_without_search(
    solution: Solution,
    context: Any,
    ledger: SegmentLedger,
    *,
    label: str,
) -> tuple[Solution, dict[str, Any]]:
    """Apply the same zero-search fleet/charge/carbon completion."""

    completed, _, joint = exact_joint_fleet_charge_decode(
        solution,
        context,
        incumbent_objective=0.0,
    )
    completed, _, carbon = carbon_aware_depot_retime(
        completed,
        context,
        incumbent_objective=0.0,
        consume_complete_evaluation=False,
    )
    ledger.route_local_completion_calls += 1
    ledger.route_proxy_evaluations += int(
        joint.get("route_proxy_evaluations", 0)
    )
    ledger.route_local_schedule_evaluations += int(
        carbon.get("route_local_schedule_evaluations", 0)
    )
    ledger.full_feasibility_checks += int(
        joint.get("feasibility_checks", 0)
    ) + int(carbon.get("feasibility_checks", 0))
    joint_complete = int(joint.get("complete_evaluations", 0))
    carbon_complete = int(carbon.get("complete_evaluations", 0))
    if joint_complete or carbon_complete:
        raise RuntimeError(
            f"{label} completion consumed hidden complete evaluations"
        )
    return completed, {
        "label": label,
        "joint_updates": int(
            joint.get("exact_decoder_updates", 0)
        ),
        "carbon_updates": int(
            carbon.get("exact_decoder_updates", 0)
        ),
        "route_proxy_evaluations": int(
            joint.get("route_proxy_evaluations", 0)
        ),
        "route_local_schedule_evaluations": int(
            carbon.get("route_local_schedule_evaluations", 0)
        ),
        "complete_evaluations": 0,
    }


def _return_segments(
    solution: Solution,
    context: Any,
    owners: dict[str, str],
    *,
    primary: SegmentSource,
    max_segment_length: int,
) -> list[SegmentSource]:
    """Return capacity-balancing segments without a geometry ranking."""

    target_route = solution.routes[primary.target_route_index]
    source_route = solution.routes[primary.source_route_index]
    customers = _route_customers(target_route, context.instance)
    primary_demand = _segment_demand(
        primary.customers,
        context,
    )
    rows: list[tuple[float, int, int, int, SegmentSource]] = []
    for start in range(len(customers)):
        for length in range(
            1,
            min(int(max_segment_length), len(customers) - start) + 1,
        ):
            if length >= len(customers):
                continue
            segment = tuple(customers[start : start + length])
            before = sum(
                owners.get(customer_id)
                != target_route.home_depot_id
                for customer_id in segment
            )
            after = sum(
                owners.get(customer_id)
                != source_route.home_depot_id
                for customer_id in segment
            )
            relief = int(before - after)
            if primary.responsibility_relief + relief < 0:
                continue
            demand_gap = abs(
                _segment_demand(segment, context)
                - primary_demand
            )
            item = SegmentSource(
                source_route_index=primary.target_route_index,
                target_route_index=primary.source_route_index,
                start=start,
                length=length,
                customers=segment,
                responsibility_relief=relief,
            )
            rows.append(
                (
                    demand_gap,
                    -relief,
                    start,
                    length,
                    item,
                )
            )
    rows.sort(key=lambda row: row[:-1])
    return [row[-1] for row in rows]


def _segment_demand(
    customers: tuple[str, ...],
    context: Any,
) -> float:
    nodes = {
        node.node_id: node
        for node in context.instance.nodes
    }
    return float(
        sum(
            float(getattr(nodes[customer_id], "demand", 0.0))
            for customer_id in customers
        )
    )


class SegmentGenerationController:
    """Sparse continuous-search controller for the isolated segment move."""

    def __init__(self, config: SegmentGeneratorConfig) -> None:
        self.config = config
        self._next_assessment_eval = 0
        self._last_attempt_eval = -10**18
        self._assessments = 0
        self._eligible = 0
        self._attempts = 0
        self._changed = 0
        self._accepted = 0
        self._best_improved = 0
        self._no_op = 0
        self._complete_candidate_evaluations = 0
        self._events: list[dict[str, Any]] = []

    def choose(
        self,
        solution: Solution,
        context: Any,
        *,
        eval_count: int,
        move_count: int,
        moves_since_best_improvement: int,
    ) -> MechanismPrescription | None:
        del move_count, moves_since_best_improvement
        current_eval = int(eval_count)
        if current_eval < self._next_assessment_eval:
            return None
        self._next_assessment_eval = (
            current_eval + int(self.config.assessment_interval)
        )
        self._assessments += 1
        owners = dict(context.customer_home_depot or {})
        if self.config.mode == "mechanism":
            deficit_present, metrics = has_mechanism_pressure(
                solution,
                context,
                owners,
                min_segment_length=int(
                    self.config.min_segment_length
                ),
                max_segment_length=int(
                    self.config.max_segment_length
                ),
            )
            eligible = _has_cross_depot_route_pair(solution)
            metrics = {
                **metrics,
                "wrong_depot_segment_present": bool(
                    deficit_present
                ),
                "cross_depot_route_pair_present": bool(
                    eligible
                ),
            }
        else:
            eligible = _has_cross_depot_route_pair(solution)
            metrics = {
                "cross_depot_route_pair_present": bool(eligible)
            }
        if eligible:
            self._eligible += 1
        cooldown_ready = (
            current_eval - self._last_attempt_eval
            >= int(self.config.cooldown_evaluations)
        )
        if not eligible or not cooldown_ready:
            return None
        self._last_attempt_eval = current_eval
        self._attempts += 1
        signal = MechanismSignal(
            mechanism_id=MECHANISM_ID,
            eligible=True,
            pressure=1.0,
            threshold=1.0,
            reason=(
                "multi_depot_segment_rebuild_available"
                if self.config.mode == "mechanism"
                else "cross_depot_route_pair"
            ),
            metrics=metrics,
        )
        self._events.append(
            {
                "eval_before": current_eval,
                "mode": self.config.mode,
                "signal_metrics": metrics,
            }
        )
        return MechanismPrescription(
            mechanism_id=MECHANISM_ID,
            pressure=1.0,
            signal=signal,
        )

    def propose(
        self,
        prescription: MechanismPrescription,
        *,
        current_solution: Solution,
        best_solution: Solution,
        current_objective: float,
        best_objective: float,
        context: Any,
    ) -> dict[str, Any]:
        del prescription, best_solution, best_objective
        owners = dict(context.customer_home_depot or {})
        solution, activity = propose_segment_move(
            current_solution,
            context,
            owners,
            config=self.config,
        )
        return {
            "solution": solution,
            "estimated_objective": None,
            "activity": {
                **activity,
                "current_objective": float(current_objective),
            },
        }

    def record_no_candidate(
        self,
        prescription: MechanismPrescription,
        *,
        activity: dict[str, Any],
    ) -> None:
        del prescription
        self._no_op += 1
        self._events[-1].update(
            {
                "proposal_built": False,
                "accepted": False,
                "best_improved": False,
                "evaluations_added": 0,
                "activity": activity,
            }
        )

    def record_outcome(
        self,
        prescription: MechanismPrescription,
        *,
        source_solution: Solution,
        candidate_solution: Solution,
        changed: bool,
        accepted: bool,
        best_improved: bool,
        evaluations_added: int,
        candidate_objective: float,
        previous_objective: float,
        expert_activity: dict[str, Any] | None = None,
    ) -> None:
        del prescription, source_solution, candidate_solution
        self._complete_candidate_evaluations += int(evaluations_added)
        self._changed += int(bool(changed))
        self._accepted += int(bool(accepted))
        self._best_improved += int(bool(best_improved))
        self._no_op += int(not changed)
        self._events[-1].update(
            {
                "proposal_built": True,
                "changed": bool(changed),
                "accepted": bool(accepted),
                "best_improved": bool(best_improved),
                "evaluations_added": int(evaluations_added),
                "candidate_objective": float(candidate_objective),
                "previous_objective": float(previous_objective),
                "objective_delta": float(
                    candidate_objective - previous_objective
                ),
                "activity": dict(expert_activity or {}),
            }
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "controller": "segment_generation_controller_v1",
            "config": asdict(self.config),
            "assessment_count": self._assessments,
            "eligible_observations": {
                MECHANISM_ID: self._eligible
            },
            "attempts": {MECHANISM_ID: self._attempts},
            "changed": {MECHANISM_ID: self._changed},
            "accepted": {MECHANISM_ID: self._accepted},
            "best_improved": {
                MECHANISM_ID: self._best_improved
            },
            "no_op": {MECHANISM_ID: self._no_op},
            "complete_candidate_evaluations": {
                MECHANISM_ID: self._complete_candidate_evaluations
            },
            "scope_violations": {MECHANISM_ID: 0},
            "events": list(self._events),
        }


def _has_cross_depot_route_pair(solution: Solution) -> bool:
    depots = {
        route.home_depot_id
        for route in solution.routes
    }
    return len(depots) >= 2
