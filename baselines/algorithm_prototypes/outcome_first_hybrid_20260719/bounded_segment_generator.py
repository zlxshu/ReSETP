"""Bounded mechanism-aware multi-depot segment generation.

SEG-GEN-01 proved that a two- or three-customer relocation can improve the
complete ReSETP objective even when distance becomes worse.  Its exhaustive
implementation was too slow.  SEG-GEN-02 keeps the same final evaluator but
replaces exhaustive candidate construction and route-local evaluation with
deterministic, multi-view bounded shortlists.

The previous implementation and its evidence are imported as read-only helper
code.  This module does not modify them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
from pathlib import Path
import sys
from typing import Any, Iterable, Literal


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
UNIFIED = (
    REPO
    / "baselines/algorithm_prototypes/unified_mechanism_alns_20260719"
)
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    UNIFIED,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mechanism_segment_generator import (  # noqa: E402
    MECHANISM_ID,
    SegmentCandidate,
    SegmentGenerationController,
    SegmentSource,
    _all_source_segment_count,
    _complete_screened_candidates,
    _complete_without_search,
    _source_segments,
)
from setp_solver.algorithms.resetp_alns.operators.local_search import (  # noqa: E402
    _candidate_with_route_customers,
    _route_customers,
)
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402
from v7_responsibility_solver import (  # noqa: E402
    _local_exact_cost,
    _route_distance,
    annotate_cross_site_services,
)


TOL = 1.0e-9
Mode = Literal["mechanism", "distance"]


@dataclass(frozen=True)
class BoundedSegmentGeneratorConfig:
    """Pre-registered engineering bounds for SEG-GEN-02."""

    mode: Mode = "mechanism"
    min_segment_length: int = 2
    max_segment_length: int = 3
    max_source_segments: int = 64
    max_positions_per_source: int = 6
    max_local_exact_candidates: int = 48
    max_completed_candidates: int = 12
    assessment_interval: int = 20
    cooldown_evaluations: int = 100
    apply_route_local_completion: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"mechanism", "distance"}:
            raise ValueError(f"unknown bounded segment mode: {self.mode}")
        if int(self.min_segment_length) < 1:
            raise ValueError("min_segment_length must be positive")
        if int(self.min_segment_length) > int(
            self.max_segment_length
        ):
            raise ValueError(
                "min_segment_length exceeds max_segment_length"
            )
        for name in (
            "max_source_segments",
            "max_positions_per_source",
            "max_local_exact_candidates",
            "max_completed_candidates",
            "assessment_interval",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")
        if int(self.cooldown_evaluations) < 0:
            raise ValueError(
                "cooldown_evaluations must be non-negative"
            )


@dataclass
class BoundedSegmentLedger:
    """All screening layers are visible and separately counted."""

    source_segments_scanned: int = 0
    source_segments_eligible: int = 0
    source_segments_shortlisted: int = 0
    cheap_source_scores: int = 0
    cheap_position_scores: int = 0
    insertion_positions_scanned: int = 0
    insertion_positions_shortlisted: int = 0
    maximum_positions_for_one_source: int = 0
    candidate_build_attempts: int = 0
    feasible_candidates: int = 0
    exact_candidates_shortlisted: int = 0
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


@dataclass(frozen=True)
class _SourceMetrics:
    source: SegmentSource
    removal_delta: float
    best_combined_distance_delta: float
    target_capacity_gap: float
    source_is_cv: bool
    stable_key: str


@dataclass(frozen=True)
class _CheapCandidate:
    candidate: SegmentCandidate
    removal_delta: float
    target_capacity_gap: float
    source_is_cv: bool
    stable_key: str


def propose_bounded_segment_move(
    solution: Solution,
    context: Any,
    owners: dict[str, str] | None = None,
    *,
    config: BoundedSegmentGeneratorConfig | None = None,
) -> tuple[Solution | None, dict[str, Any]]:
    """Generate one bounded segment relocation without hidden full scoring."""

    cfg = config or BoundedSegmentGeneratorConfig()
    owner_map = (
        dict(owners)
        if owners is not None
        else dict(
            context.customer_home_depot
            or infer_customer_home_depots(context.instance)
        )
    )
    ledger = BoundedSegmentLedger()
    source_completion: dict[str, Any] = {}
    working = solution
    if cfg.apply_route_local_completion:
        working, source_completion = _complete_without_search(
            working,
            context,
            ledger,
            label="seg_gen_02_source",
        )

    all_sources = _source_segments(
        working,
        context,
        owner_map,
        max_segment_length=int(cfg.max_segment_length),
        min_segment_length=int(cfg.min_segment_length),
        require_responsibility_relief=False,
    )
    ledger.source_segments_scanned = _all_source_segment_count(
        working,
        context,
        max_segment_length=int(cfg.max_segment_length),
        min_segment_length=int(cfg.min_segment_length),
    )
    ledger.source_segments_eligible = len(all_sources)
    if not all_sources:
        return None, _activity(
            cfg,
            ledger,
            None,
            source_completion,
            [],
            "no_cross_depot_segment_source",
            {},
        )

    route_customers = [
        _route_customers(route, context.instance)
        for route in working.routes
    ]
    source_metrics = _measure_sources(
        working,
        context,
        all_sources,
        route_customers,
        ledger,
    )
    source_views = _source_views(source_metrics, mode=cfg.mode)
    selected_metrics, source_view_counts = _round_robin_union(
        source_views,
        int(cfg.max_source_segments),
        key=lambda item: _source_key(item.source),
    )
    ledger.source_segments_shortlisted = len(selected_metrics)

    cheap_candidates: list[_CheapCandidate] = []
    position_view_counts: dict[str, int] = {}
    for metrics in selected_metrics:
        source = metrics.source
        source_customers = route_customers[source.source_route_index]
        target_customers = route_customers[source.target_route_index]
        changed_source = [
            *source_customers[: source.start],
            *source_customers[source.start + source.length :],
        ]
        if not changed_source:
            continue
        positions, counts, scanned = _bounded_positions(
            working,
            context,
            source,
            source_customers,
            target_customers,
            mode=cfg.mode,
            limit=int(cfg.max_positions_per_source),
        )
        ledger.cheap_position_scores += scanned
        ledger.insertion_positions_scanned += scanned
        ledger.insertion_positions_shortlisted += len(positions)
        ledger.maximum_positions_for_one_source = max(
            ledger.maximum_positions_for_one_source,
            len(positions),
        )
        for name, value in counts.items():
            position_view_counts[name] = (
                int(position_view_counts.get(name, 0)) + int(value)
            )

        source_route = working.routes[source.source_route_index]
        target_route = working.routes[source.target_route_index]
        before_distance = _route_distance(
            source_route.home_depot_id,
            source_customers,
            context,
        ) + _route_distance(
            target_route.home_depot_id,
            target_customers,
            context,
        )
        for target_position in positions:
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
            if cfg.mode == "distance" and distance_delta >= -TOL:
                continue
            ledger.candidate_build_attempts += 1
            candidate_solution = _candidate_with_route_customers(
                working,
                context,
                {
                    source.source_route_index: changed_source,
                    source.target_route_index: changed_target,
                },
            )
            ledger.full_feasibility_checks += 1
            if candidate_solution is None:
                continue
            candidate_solution = annotate_cross_site_services(
                candidate_solution,
                owner_map,
            )
            ledger.feasible_candidates += 1
            item = SegmentCandidate(
                kind="bounded_relocate_segment",
                source=source,
                target_position=int(target_position),
                solution=candidate_solution,
                distance_delta=distance_delta,
                local_model_delta=None,
            )
            cheap_candidates.append(
                _CheapCandidate(
                    candidate=item,
                    removal_delta=metrics.removal_delta,
                    target_capacity_gap=metrics.target_capacity_gap,
                    source_is_cv=metrics.source_is_cv,
                    stable_key=_candidate_hash(item),
                )
            )

    if not cheap_candidates:
        return None, _activity(
            cfg,
            ledger,
            None,
            source_completion,
            [],
            "no_feasible_bounded_candidate",
            {
                "source": source_view_counts,
                "position": position_view_counts,
            },
        )

    exact_views = _candidate_views(
        cheap_candidates,
        mode=cfg.mode,
    )
    exact_shortlist, exact_view_counts = _round_robin_union(
        exact_views,
        int(cfg.max_local_exact_candidates),
        key=lambda item: _candidate_key(item.candidate),
    )
    ledger.exact_candidates_shortlisted = len(exact_shortlist)

    route_pair_before: dict[tuple[int, int], float] = {}
    locally_evaluated: list[SegmentCandidate] = []
    for cheap in exact_shortlist:
        item = cheap.candidate
        route_pair = (
            item.source.source_route_index,
            item.source.target_route_index,
        )
        before_local = route_pair_before.get(route_pair)
        if before_local is None:
            before_local = _local_exact_cost(
                working,
                route_pair,
                context,
                owner_map,
            )
            route_pair_before[route_pair] = before_local
            ledger.route_local_exact_evaluations += 1
        after_local = _local_exact_cost(
            item.solution,
            route_pair,
            context,
            owner_map,
        )
        ledger.route_local_exact_evaluations += 1
        local_delta = float(after_local - before_local)
        if item.distance_delta > TOL and local_delta < -TOL:
            ledger.distance_worse_model_better_candidates += 1
        locally_evaluated.append(
            replace(item, local_model_delta=local_delta)
        )

    completion_activity: list[dict[str, Any]] = []
    completed = locally_evaluated
    if (
        cfg.mode == "mechanism"
        and cfg.apply_route_local_completion
        and locally_evaluated
    ):
        completed, completion_activity = _complete_screened_candidates(
            working,
            context,
            owner_map,
            locally_evaluated,
            ledger,
            limit=int(cfg.max_completed_candidates),
        )

    selected: SegmentCandidate | None
    if cfg.mode == "mechanism":
        selected = min(
            (
                item
                for item in completed
                if item.local_model_delta is not None
                and item.local_model_delta < -TOL
            ),
            key=_completed_candidate_sort_key,
            default=None,
        )
    else:
        selected = min(
            (item for item in completed if item.distance_delta < -TOL),
            key=lambda item: (
                item.distance_delta,
                *_candidate_key(item),
            ),
            default=None,
        )

    if selected is None:
        return None, _activity(
            cfg,
            ledger,
            None,
            source_completion,
            completion_activity,
            "no_improving_bounded_candidate",
            {
                "source": source_view_counts,
                "position": position_view_counts,
                "exact": exact_view_counts,
            },
        )

    proposed = selected.solution
    selected_completion: dict[str, Any] = {}
    if cfg.mode == "distance" and cfg.apply_route_local_completion:
        proposed, selected_completion = _complete_without_search(
            proposed,
            context,
            ledger,
            label="seg_gen_02_distance_selected",
        )
    selected_payload = {
        "kind": selected.kind,
        "source_route_index": selected.source.source_route_index,
        "target_route_index": selected.source.target_route_index,
        "segment_start": selected.source.start,
        "segment_length": selected.source.length,
        "customers": list(selected.source.customers),
        "target_position": selected.target_position,
        "responsibility_relief": selected.source.responsibility_relief,
        "distance_delta": float(selected.distance_delta),
        "local_model_delta": (
            None
            if selected.local_model_delta is None
            else float(selected.local_model_delta)
        ),
    }
    activity = _activity(
        cfg,
        ledger,
        selected_payload,
        source_completion,
        (
            completion_activity
            if cfg.mode == "mechanism"
            else [selected_completion]
        ),
        "proposal_generated",
        {
            "source": source_view_counts,
            "position": position_view_counts,
            "exact": exact_view_counts,
        },
    )
    return proposed, activity


class BoundedSegmentGenerationController(SegmentGenerationController):
    """Use the existing continuous-search hook with SEG-GEN-02 proposals."""

    def __init__(
        self,
        config: BoundedSegmentGeneratorConfig,
    ) -> None:
        super().__init__(config)  # compatible fields, no legacy proposal call

    def propose(
        self,
        prescription: Any,
        *,
        current_solution: Solution,
        best_solution: Solution,
        current_objective: float,
        best_objective: float,
        context: Any,
    ) -> dict[str, Any]:
        del prescription, best_solution, best_objective
        owners = dict(context.customer_home_depot or {})
        solution, activity = propose_bounded_segment_move(
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

    def diagnostics(self) -> dict[str, Any]:
        payload = super().diagnostics()
        payload["controller"] = "bounded_segment_generation_controller_v2"
        payload["mechanism_id"] = MECHANISM_ID
        payload["config"] = asdict(self.config)
        return payload


def _measure_sources(
    solution: Solution,
    context: Any,
    sources: list[SegmentSource],
    route_customers: list[list[str]],
    ledger: BoundedSegmentLedger,
) -> list[_SourceMetrics]:
    prices = context.prices
    capacity = float(
        prices.get("Q_capacity", 0.0)
        if isinstance(prices, dict)
        else getattr(prices, "Q_capacity", 0.0)
    )
    node_lookup = {
        node.node_id: node
        for node in context.instance.nodes
    }
    rows: list[_SourceMetrics] = []
    for source in sources:
        source_route = solution.routes[source.source_route_index]
        target_route = solution.routes[source.target_route_index]
        source_customers = route_customers[source.source_route_index]
        target_customers = route_customers[source.target_route_index]
        changed_source = [
            *source_customers[: source.start],
            *source_customers[source.start + source.length :],
        ]
        source_before = _route_distance(
            source_route.home_depot_id,
            source_customers,
            context,
        )
        source_after = _route_distance(
            source_route.home_depot_id,
            changed_source,
            context,
        )
        removal_delta = float(source_after - source_before)
        target_before = _route_distance(
            target_route.home_depot_id,
            target_customers,
            context,
        )
        best_combined = float("inf")
        for position in range(len(target_customers) + 1):
            changed_target = [
                *target_customers[:position],
                *source.customers,
                *target_customers[position:],
            ]
            target_after = _route_distance(
                target_route.home_depot_id,
                changed_target,
                context,
            )
            best_combined = min(
                best_combined,
                removal_delta + float(target_after - target_before),
            )
            ledger.cheap_source_scores += 1
        target_load = sum(
            float(getattr(node_lookup[node_id], "demand", 0.0))
            for node_id in target_customers
        )
        segment_load = sum(
            float(getattr(node_lookup[node_id], "demand", 0.0))
            for node_id in source.customers
        )
        capacity_gap = (
            abs(capacity - target_load - segment_load)
            if capacity > 0.0
            else float(target_load + segment_load)
        )
        rows.append(
            _SourceMetrics(
                source=source,
                removal_delta=removal_delta,
                best_combined_distance_delta=best_combined,
                target_capacity_gap=float(capacity_gap),
                source_is_cv=(
                    str(source_route.vehicle_type).lower() == "cv"
                ),
                stable_key=_stable_hash(_source_key(source)),
            )
        )
    return rows


def _source_views(
    rows: list[_SourceMetrics],
    *,
    mode: Mode,
) -> dict[str, list[_SourceMetrics]]:
    distance = sorted(
        rows,
        key=lambda item: (
            item.best_combined_distance_delta,
            item.removal_delta,
            _source_key(item.source),
        ),
    )
    if mode == "distance":
        return {
            "distance": distance,
            "distance_diversity": sorted(
                rows,
                key=lambda item: (
                    item.stable_key,
                    _source_key(item.source),
                ),
            ),
        }
    return {
        "responsibility": sorted(
            rows,
            key=lambda item: (
                -item.source.responsibility_relief,
                item.best_combined_distance_delta,
                _source_key(item.source),
            ),
        ),
        "cv_breakpoint": sorted(
            rows,
            key=lambda item: (
                not item.source_is_cv,
                item.removal_delta,
                item.target_capacity_gap,
                _source_key(item.source),
            ),
        ),
        "geometry": distance,
        "capacity_breakpoint": sorted(
            rows,
            key=lambda item: (
                item.target_capacity_gap,
                not item.source_is_cv,
                item.best_combined_distance_delta,
                _source_key(item.source),
            ),
        ),
        "deterministic_diversity": sorted(
            rows,
            key=lambda item: (
                item.stable_key,
                _source_key(item.source),
            ),
        ),
    }


def _bounded_positions(
    solution: Solution,
    context: Any,
    source: SegmentSource,
    source_customers: list[str],
    target_customers: list[str],
    *,
    mode: Mode,
    limit: int,
) -> tuple[list[int], dict[str, int], int]:
    source_route = solution.routes[source.source_route_index]
    target_route = solution.routes[source.target_route_index]
    changed_source = [
        *source_customers[: source.start],
        *source_customers[source.start + source.length :],
    ]
    before = _route_distance(
        source_route.home_depot_id,
        source_customers,
        context,
    ) + _route_distance(
        target_route.home_depot_id,
        target_customers,
        context,
    )
    distance_rows: list[tuple[float, int]] = []
    endpoint_rows: list[tuple[float, int]] = []
    first = source.customers[0]
    last = source.customers[-1]
    for position in range(len(target_customers) + 1):
        changed_target = [
            *target_customers[:position],
            *source.customers,
            *target_customers[position:],
        ]
        after = _route_distance(
            source_route.home_depot_id,
            changed_source,
            context,
        ) + _route_distance(
            target_route.home_depot_id,
            changed_target,
            context,
        )
        distance_rows.append((float(after - before), position))
        left = (
            target_route.home_depot_id
            if position == 0
            else target_customers[position - 1]
        )
        right = (
            target_route.home_depot_id
            if position == len(target_customers)
            else target_customers[position]
        )
        endpoint_affinity = min(
            float(context.instance.distance(left, first))
            + float(context.instance.distance(last, right)),
            float(context.instance.distance(left, last))
            + float(context.instance.distance(first, right)),
        )
        endpoint_rows.append((endpoint_affinity, position))

    distance_positions = [
        position
        for _, position in sorted(distance_rows)
    ]
    if mode == "distance":
        views: dict[str, list[int]] = {
            "distance": distance_positions,
            "deterministic_diversity": sorted(
                range(len(target_customers) + 1),
                key=lambda position: _stable_hash(
                    (*_source_key(source), position)
                ),
            ),
        }
    else:
        views = {
            "distance": distance_positions,
            "segment_endpoint_affinity": [
                position
                for _, position in sorted(endpoint_rows)
            ],
            "route_boundaries": list(
                dict.fromkeys((0, len(target_customers)))
            ),
            "deterministic_diversity": sorted(
                range(len(target_customers) + 1),
                key=lambda position: _stable_hash(
                    (*_source_key(source), position)
                ),
            ),
        }
    positions, counts = _round_robin_union(
        views,
        int(limit),
        key=int,
    )
    return [int(value) for value in positions], counts, len(distance_rows)


def _candidate_views(
    rows: list[_CheapCandidate],
    *,
    mode: Mode,
) -> dict[str, list[_CheapCandidate]]:
    distance = sorted(
        rows,
        key=lambda item: (
            item.candidate.distance_delta,
            _candidate_key(item.candidate),
        ),
    )
    if mode == "distance":
        return {"distance": distance}
    return {
        "distance": distance,
        "responsibility": sorted(
            rows,
            key=lambda item: (
                -item.candidate.source.responsibility_relief,
                item.candidate.distance_delta,
                _candidate_key(item.candidate),
            ),
        ),
        "cv_breakpoint": sorted(
            rows,
            key=lambda item: (
                not item.source_is_cv,
                item.removal_delta,
                item.target_capacity_gap,
                _candidate_key(item.candidate),
            ),
        ),
        "capacity_breakpoint": sorted(
            rows,
            key=lambda item: (
                item.target_capacity_gap,
                not item.source_is_cv,
                item.candidate.distance_delta,
                _candidate_key(item.candidate),
            ),
        ),
        "deterministic_diversity": sorted(
            rows,
            key=lambda item: (
                item.stable_key,
                _candidate_key(item.candidate),
            ),
        ),
    }


def _round_robin_union(
    views: dict[str, list[Any]],
    limit: int,
    *,
    key: Any,
) -> tuple[list[Any], dict[str, int]]:
    selected: list[Any] = []
    seen: set[Any] = set()
    counts = {name: 0 for name in views}
    indices = {name: 0 for name in views}
    names = list(views)
    while len(selected) < int(limit):
        progress = False
        for name in names:
            pool = views[name]
            index = indices[name]
            while index < len(pool) and key(pool[index]) in seen:
                index += 1
            indices[name] = index
            if index >= len(pool):
                continue
            item = pool[index]
            indices[name] = index + 1
            item_key = key(item)
            if item_key in seen:
                continue
            seen.add(item_key)
            selected.append(item)
            counts[name] += 1
            progress = True
            if len(selected) >= int(limit):
                break
        if not progress:
            break
    return selected, counts


def _activity(
    config: BoundedSegmentGeneratorConfig,
    ledger: BoundedSegmentLedger,
    selected: dict[str, Any] | None,
    source_completion: dict[str, Any],
    completion: list[dict[str, Any]],
    stop_reason: str,
    view_counts: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mode": config.mode,
        "candidate": "SEG-GEN-02",
        "ledger": asdict(ledger),
        "view_selection_counts": view_counts,
        "selected": selected,
        "source_completion": source_completion,
        "completion": completion,
        "stop_reason": stop_reason,
    }


def _source_key(source: SegmentSource) -> tuple[Any, ...]:
    return (
        source.source_route_index,
        source.target_route_index,
        source.start,
        source.length,
        source.customers,
    )


def _candidate_key(item: SegmentCandidate) -> tuple[Any, ...]:
    return (
        *_source_key(item.source),
        item.target_position,
        item.return_customers,
        item.return_start,
    )


def _candidate_hash(item: SegmentCandidate) -> str:
    return _stable_hash(_candidate_key(item))


def _stable_hash(values: Iterable[Any]) -> str:
    payload = "\x1f".join(str(value) for value in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _completed_candidate_sort_key(
    item: SegmentCandidate,
) -> tuple[Any, ...]:
    return (
        float(
            item.local_model_delta
            if item.local_model_delta is not None
            else float("inf")
        ),
        item.distance_delta,
        *_candidate_key(item),
    )
