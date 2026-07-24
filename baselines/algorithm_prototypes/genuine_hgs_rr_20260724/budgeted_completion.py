"""Budget-visible China81 skeleton completion for new A/B/A+B gates.

This mirrors the frozen monotone completion logic without changing the shared
module used by the running E2 v7 campaign.  Every whole-solution score is
routed through ``BudgetedCompleteEvaluator``; route-local ranking remains a
cheap delta calculation and is reported separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.check import FLEET_SIZE
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    RouteCompletionVariant,
    _canonical_all_cv_solution,
    _depot_ev_route_count,
    _replace_route_variant,
    _require_finite_depot_fleet,
    _single_route_cost,
    _violation_summary,
)
from setp_solver.solution import Route, Solution

from contracts import CandidateSource
from evaluation import BudgetedCompleteEvaluator, ScoredCandidate


TOL = 1.0e-9


@dataclass(frozen=True)
class BudgetedCompletionResult:
    completion: China81CompletionResult
    complete_evaluations_used: int
    route_local_rankings: int
    stopped_on_budget: bool


def complete_skeleton_with_visible_budget(
    skeleton: Solution,
    bundle: China81Bundle,
    *,
    evaluator: BudgetedCompleteEvaluator,
    source: CandidateSource,
    source_metadata: dict[str, Any] | None = None,
) -> BudgetedCompletionResult:
    """Complete one skeleton while exposing every whole-solution score."""

    before = evaluator.ledger.consumed
    baseline = _canonical_all_cv_solution(skeleton, bundle)
    baseline_scored = evaluator.score(
        baseline,
        source=source,
        metadata={
            **dict(source_metadata or {}),
            "completion_stage": "all_cv_baseline",
        },
    )
    baseline_nonfleet = [
        violation
        for violation in baseline_scored.violations
        if violation.type != FLEET_SIZE
    ]
    if baseline_nonfleet:
        raise ValueError(
            "China81 route skeleton has no feasible all-CV completion: "
            + _violation_summary(list(baseline_nonfleet))
        )

    variants, generation_failures, route_local_rankings = (
        _generate_route_variants(baseline, bundle)
    )
    ranked = sorted(
        variants,
        key=lambda item: (
            -item.saving_from_cv,
            item.route_index,
            item.route_cost,
            item.label,
        ),
    )

    current = baseline
    current_scored = baseline_scored
    accepted_route_indices: set[int] = set()
    attempted = 0
    rejected_infeasible = 0
    rejected_non_improving = 0
    mandatory_assignments: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    stopped_on_budget = False

    routes_by_depot: dict[str, list[int]] = {}
    for route_index, route in enumerate(current.routes):
        routes_by_depot.setdefault(
            route.home_depot_id,
            [],
        ).append(route_index)
    for depot_id in sorted(routes_by_depot):
        try:
            caps = bundle.fleet_caps_by_depot[depot_id]
        except KeyError as exc:
            raise ValueError(
                f"China81 completion has no finite fleet for {depot_id!r}"
            ) from exc
        route_count = len(routes_by_depot[depot_id])
        cv_cap = int(caps["num_cv"])
        ev_cap = int(caps["num_ev"])
        required_ev = max(0, route_count - cv_cap)
        if route_count > cv_cap + ev_cap:
            raise ValueError(
                "China81 route skeleton exceeds registered total fleet: "
                f"{depot_id}: routes={route_count}, "
                f"num_cv={cv_cap}, num_ev={ev_cap}"
            )
        while _depot_ev_route_count(current, depot_id) < required_ev:
            assigned = False
            for variant in ranked:
                route = current.routes[variant.route_index]
                if (
                    route.home_depot_id != depot_id
                    or variant.route_index in accepted_route_indices
                ):
                    continue
                if evaluator.ledger.remaining <= 0:
                    raise RuntimeError(
                        "complete-evaluation budget ended before mandatory "
                        f"fleet assignment at {depot_id}"
                    )
                attempted += 1
                candidate = _replace_route_variant(
                    current,
                    route_index=variant.route_index,
                    route=variant.route,
                    actions=variant.actions,
                    customer_home_depot=bundle.customer_home_depot,
                )
                scored = evaluator.score(
                    candidate,
                    source=source,
                    metadata={
                        **dict(source_metadata or {}),
                        "completion_stage": (
                            "mandatory_fleet_assignment"
                        ),
                        "route_index": variant.route_index,
                        "variant_label": variant.label,
                    },
                )
                nonfleet = [
                    violation
                    for violation in scored.violations
                    if violation.type != FLEET_SIZE
                ]
                if nonfleet:
                    rejected_infeasible += 1
                    continue
                mandatory_assignments.append(
                    {
                        "depot_id": depot_id,
                        "route_index": variant.route_index,
                        "label": variant.label,
                        "before_cost": current_scored.objective,
                        "after_cost": scored.objective,
                        "cost_change": (
                            scored.objective
                            - current_scored.objective
                        ),
                        "complete_evaluation_index": (
                            scored.record.index
                        ),
                    }
                )
                current = candidate
                current_scored = scored
                accepted_route_indices.add(variant.route_index)
                assigned = True
                break
            if not assigned:
                raise ValueError(
                    "China81 route skeleton cannot satisfy registered CV "
                    f"cap at {depot_id}: required_ev={required_ev}"
                )

    if current_scored.violations:
        raise RuntimeError(
            "mandatory finite-fleet completion did not reach feasibility: "
            + _violation_summary(list(current_scored.violations))
        )
    finite_fleet_reference = current_scored

    for variant in ranked:
        if variant.route_index in accepted_route_indices:
            continue
        depot_id = current.routes[
            variant.route_index
        ].home_depot_id
        ev_cap = int(
            bundle.fleet_caps_by_depot[depot_id]["num_ev"]
        )
        if _depot_ev_route_count(current, depot_id) >= ev_cap:
            continue
        if evaluator.ledger.remaining <= 0:
            stopped_on_budget = True
            break
        attempted += 1
        candidate = _replace_route_variant(
            current,
            route_index=variant.route_index,
            route=variant.route,
            actions=variant.actions,
            customer_home_depot=bundle.customer_home_depot,
        )
        scored = evaluator.score(
            candidate,
            source=source,
            metadata={
                **dict(source_metadata or {}),
                "completion_stage": "optional_ev_variant",
                "route_index": variant.route_index,
                "variant_label": variant.label,
            },
        )
        if scored.violations:
            rejected_infeasible += 1
            continue
        if scored.objective >= current_scored.objective - TOL:
            rejected_non_improving += 1
            continue
        accepted.append(
            {
                "route_index": variant.route_index,
                "label": variant.label,
                "before_cost": current_scored.objective,
                "after_cost": scored.objective,
                "improvement": (
                    current_scored.objective - scored.objective
                ),
                "complete_evaluation_index": scored.record.index,
            }
        )
        current = candidate
        current_scored = scored
        accepted_route_indices.add(variant.route_index)

    if current_scored.violations:
        raise RuntimeError(
            "budgeted China81 completion returned infeasible solution: "
            + _violation_summary(list(current_scored.violations))
        )
    _require_finite_depot_fleet(current, bundle)
    if (
        current_scored.objective
        > finite_fleet_reference.objective + TOL
    ):
        raise RuntimeError(
            "budgeted completion violated post-fleet monotone protection"
        )

    activity: dict[str, Any] = {
        "schema_version": (
            "resetp.coop-hgs-rr-budgeted-completion.v1"
        ),
        "baseline_all_cv_cost": baseline_scored.objective,
        "finite_fleet_reference_cost": (
            finite_fleet_reference.objective
        ),
        "final_cost": current_scored.objective,
        "complete_evaluations_used": (
            evaluator.ledger.consumed - before
        ),
        "route_local_rankings": route_local_rankings,
        "stopped_on_budget": stopped_on_budget,
        "variant_count": len(variants),
        "variant_attempts": attempted,
        "variant_generation_failures": generation_failures,
        "mandatory_fleet_assignments": mandatory_assignments,
        "rejected_infeasible": rejected_infeasible,
        "rejected_non_improving": rejected_non_improving,
        "accepted_variants": accepted,
        "final_complete_evaluation_index": (
            current_scored.record.index
        ),
    }
    completion = China81CompletionResult(
        solution=current,
        objective=current_scored.objective,
        breakdown=current_scored.breakdown,
        activity=activity,
    )
    return BudgetedCompletionResult(
        completion=completion,
        complete_evaluations_used=(
            evaluator.ledger.consumed - before
        ),
        route_local_rankings=route_local_rankings,
        stopped_on_budget=stopped_on_budget,
    )


def _generate_route_variants(
    baseline: Solution,
    bundle: China81Bundle,
) -> tuple[
    list[RouteCompletionVariant],
    list[dict[str, Any]],
    int,
]:
    variants: list[RouteCompletionVariant] = []
    failures: list[dict[str, Any]] = []
    route_local_rankings = 0
    for route_index, route in enumerate(baseline.routes):
        cv_cost = _single_route_cost(route, (), bundle)
        route_local_rankings += 1
        for label, strategy, carbon_weight in (
            ("ev_integrated", "integrated", 1.0),
            ("ev_low_carbon", "legacy", 1.0),
            ("ev_immediate", "integrated", 0.0),
        ):
            ev_route = Route(
                vehicle_id=route.vehicle_id,
                vehicle_type="ev",
                home_depot_id=route.home_depot_id,
                node_sequence=list(route.node_sequence),
            )
            try:
                repaired, actions = repair_route_charging(
                    ev_route,
                    bundle.instance,
                    bundle.time_profile,
                    bundle.prices,
                    strategy=strategy,
                    carbon_weight=carbon_weight,
                    depot_charge_window_mode=(
                        "same_day_predeparture"
                    ),
                )
                route_cost = _single_route_cost(
                    repaired,
                    tuple(actions),
                    bundle,
                )
                route_local_rankings += 1
            except (TypeError, ValueError) as exc:
                failures.append(
                    {
                        "route_index": route_index,
                        "label": label,
                        "reason": str(exc),
                    }
                )
                continue
            variants.append(
                RouteCompletionVariant(
                    route_index=route_index,
                    label=label,
                    route=repaired,
                    actions=tuple(actions),
                    route_cost=route_cost,
                    saving_from_cv=float(cv_cost - route_cost),
                )
            )
    return variants, failures, route_local_rankings
