"""Bounded mechanism-priced pair-route resplitting.

This is isolated development code.  It does not call ALNS, HGS, the formal
winner, or the route-search scoring channel.  A shared preparation pass:

1. completes the unchanged customer skeleton once under a four-pattern cap;
2. enumerates one common, bounded set of two-route cuts;
3. computes both distance and ReSETP mechanism scores for every cut.

The two behaviour arms then differ only in which score ranks the common pool.
Both send at most four cuts through the same joint completion.  All limits and
acceptance rules come from
``docs/handoff/mechanism_priced_pair_resplit_contract_20260719.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from itertools import product
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import route_node_schedule  # noqa: E402
from setp_solver.prices import PriceParameters  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.evaluation import (  # noqa: E402
    EvaluationContext,
    cross_depot_violations,
    fairness_context_for_solution,
    model_cost,
)
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
)
from v4_mechanism_alns_solver import RouteVariant, _route_variants  # noqa: E402
from v5_carbon_retiming_solver import (  # noqa: E402
    _depot_action_window,
    _depot_charge_local_objective,
    depot_charge_candidate_starts,
)
from v7_responsibility_solver import annotate_cross_site_services  # noqa: E402


TOL = 1.0e-9
MECHANISM_ARM = "mechanism"
DISTANCE_ARM = "distance"
ALLOWED_ARMS = frozenset({MECHANISM_ARM, DISTANCE_ARM})


@dataclass(frozen=True)
class PairResplitConfig:
    max_route_pairs: int = 3
    max_unique_sequences: int = 8
    max_cut_positions: int = 16
    max_exact_candidates: int = 4
    max_vehicle_patterns: int = 4
    max_charge_actions: int = 8
    max_charge_starts: int = 16
    max_joint_checks: int = 9


@dataclass(frozen=True)
class FrozenCounterfactual:
    source_solution_sha256: str
    context_sha256: str
    solution: Solution
    solution_sha256: str
    source_cost: float
    cost: float
    activity: dict[str, Any]
    record_sha256: str


@dataclass(frozen=True)
class PairResplitCandidate:
    left_route_index: int
    right_route_index: int
    left_customers: tuple[str, ...]
    right_customers: tuple[str, ...]
    distance_score: float
    mechanism_score: float
    candidate_sha256: str
    left_variants: dict[str, RouteVariant] = field(
        repr=False,
        compare=False,
    )
    right_variants: dict[str, RouteVariant] = field(
        repr=False,
        compare=False,
    )

    @property
    def boundary_key(
        self,
    ) -> tuple[int, int, tuple[str, ...], tuple[str, ...]]:
        return (
            self.left_route_index,
            self.right_route_index,
            self.left_customers,
            self.right_customers,
        )


@dataclass(frozen=True)
class PreparedPairResplit:
    source: Solution
    source_sha256: str
    counterfactual: FrozenCounterfactual
    context: EvaluationContext = field(repr=False, compare=False)
    context_sha256: str
    config: PairResplitConfig
    candidates: tuple[PairResplitCandidate, ...]
    candidate_set_sha256: str
    preparation_activity: dict[str, Any]
    integrity_sha256: str


@dataclass(frozen=True)
class PairResplitResult:
    arm: str
    solution: Solution
    cost: float
    source_cost: float
    counterfactual_cost: float
    feasible: bool
    changed: bool
    accepted_candidate_sha256: str | None
    activity: dict[str, Any]
    result_sha256: str


def build_shared_counterfactual(
    source: Solution,
    context: EvaluationContext,
    *,
    config: PairResplitConfig | None = None,
) -> FrozenCounterfactual:
    """Complete one unchanged customer skeleton under the frozen four-pattern cap."""

    frozen = _validated_config(config or PairResplitConfig())
    source_sha = solution_sha256(source)
    source_violations = _context_violations(source, context)
    if source_violations:
        raise ValueError(
            f"pair-resplit source is infeasible: {source_violations[:8]}"
        )
    source_cost = _finite_cost(model_cost(source, context), "source cost")
    route_variants: list[dict[str, RouteVariant]] = []
    current_pattern: list[str] = []
    local_variant_calls = 0
    charge_repair_calls = 0
    proxy_evaluations = 0
    effective_prices = _effective_prices(context)
    for route in source.routes:
        actions = tuple(
            action
            for action in source.charging_actions
            if action.vehicle_id == route.vehicle_id
        )
        variants = _route_variants(
            route,
            current_actions=actions,
            instance=context.instance,
            carbon_profile=context.carbon_profile,
            prices=effective_prices,
        )
        if not variants:
            raise RuntimeError(
                f"counterfactual route {route.vehicle_id} has no variant"
            )
        local_variant_calls += 1
        charge_repair_calls += int(route.vehicle_type.lower() != "ev")
        proxy_evaluations += len(variants)
        route_variants.append(variants)
        current_pattern.append(route.vehicle_type.lower())

    current = tuple(current_pattern)
    cheapest = tuple(
        min(
            variants.values(),
            key=lambda variant: (
                float(variant.proxy_cost),
                variant.vehicle_type,
            ),
        ).vehicle_type
        for variants in route_variants
    )
    current_proxy = sum(
        float(route_variants[index][vehicle_type].proxy_cost)
        for index, vehicle_type in enumerate(current)
    )
    flips: list[tuple[float, int, tuple[str, ...]]] = []
    for index, variants in enumerate(route_variants):
        for vehicle_type, variant in sorted(variants.items()):
            if vehicle_type == current[index]:
                continue
            pattern = list(current)
            pattern[index] = vehicle_type
            delta = (
                float(variant.proxy_cost)
                - float(route_variants[index][current[index]].proxy_cost)
            )
            flips.append((float(delta), index, tuple(pattern)))
    patterns: list[tuple[str, ...]] = []
    seen_patterns: set[tuple[str, ...]] = set()
    for pattern in (
        current,
        cheapest,
        *(item[2] for item in sorted(flips)),
    ):
        if pattern in seen_patterns:
            continue
        seen_patterns.add(pattern)
        patterns.append(pattern)
        if len(patterns) >= frozen.max_vehicle_patterns:
            break

    owners = context.customer_home_depot or infer_customer_home_depots(
        context.instance
    )
    records: list[dict[str, Any]] = []
    best_solution: Solution | None = None
    best_cost = math.inf
    total_joint_checks = 0
    total_generated_starts = 0
    total_retained_starts = 0
    total_local_start_evaluations = 0
    full_replays = 0
    for pattern in patterns:
        assembled = _assemble_global_pattern(
            source,
            route_variants,
            pattern,
            owners,
        )
        completed, retime_activity = _bounded_charge_retime(
            assembled,
            context,
            config=frozen,
            eligible_vehicle_ids=None,
            global_mode=True,
        )
        total_joint_checks += int(retime_activity["joint_feasibility_checks"])
        total_generated_starts += int(
            retime_activity["generated_charge_starts"]
        )
        total_retained_starts += int(
            retime_activity["retained_charge_starts"]
        )
        total_local_start_evaluations += int(
            retime_activity["local_start_evaluations"]
        )
        record = {
            "pattern": list(pattern),
            "proxy_delta": float(
                sum(
                    route_variants[index][vehicle_type].proxy_cost
                    for index, vehicle_type in enumerate(pattern)
                )
                - current_proxy
            ),
            "retime": retime_activity,
            "feasible": completed is not None,
        }
        if completed is not None:
            full_replays += 1
            cost = _finite_cost(
                model_cost(completed, context),
                "counterfactual pattern cost",
            )
            record["complete_cost"] = cost
            record["solution_sha256"] = solution_sha256(completed)
            if (
                cost < best_cost - TOL
                or (
                    abs(cost - best_cost) <= TOL
                    and best_solution is not None
                    and solution_sha256(completed)
                    < solution_sha256(best_solution)
                )
            ):
                best_solution = completed
                best_cost = cost
        records.append(record)
    if best_solution is None:
        raise RuntimeError("shared counterfactual found no feasible pattern")
    independent_cost = _finite_cost(
        model_cost(best_solution, context),
        "counterfactual independent replay",
    )
    if abs(independent_cost - best_cost) > 1.0e-7:
        raise RuntimeError("counterfactual independent replay drifted")
    best_sha = solution_sha256(best_solution)
    activity: dict[str, Any] = {
        "source_feasibility_checks": 1,
        "source_complete_replays": 1,
        "route_variant_calls": local_variant_calls,
        "route_variant_option_counts": [
            len(variants) for variants in route_variants
        ],
        "charge_repair_calls": charge_repair_calls,
        "route_proxy_evaluations": proxy_evaluations,
        "patterns_considered": len(patterns),
        "joint_feasibility_checks": total_joint_checks,
        "generated_charge_starts": total_generated_starts,
        "retained_charge_starts": total_retained_starts,
        "local_start_evaluations": total_local_start_evaluations,
        "joint_complete_replays": full_replays,
        "independent_replays": 1,
        "complete_route_search_evaluations": 0,
        "records": records,
    }
    _assert_counterfactual_caps(activity, frozen)
    record_payload = {
        "source_solution_sha256": source_sha,
        "context_sha256": _context_sha256(context),
        "solution_sha256": best_sha,
        "source_cost": source_cost,
        "cost": independent_cost,
        "activity": activity,
    }
    return FrozenCounterfactual(
        source_solution_sha256=source_sha,
        context_sha256=_context_sha256(context),
        solution=best_solution,
        solution_sha256=best_sha,
        source_cost=source_cost,
        cost=independent_cost,
        activity=activity,
        record_sha256=_json_sha256(record_payload),
    )


def prepare_pair_resplit(
    source: Solution,
    context: EvaluationContext,
    *,
    counterfactual: FrozenCounterfactual | None = None,
    config: PairResplitConfig | None = None,
) -> PreparedPairResplit:
    """Build the one common candidate pool used by both ranking arms."""

    frozen = _validated_config(config or PairResplitConfig())
    source_sha = solution_sha256(source)
    shared = counterfactual or build_shared_counterfactual(
        source,
        context,
        config=frozen,
    )
    _verify_counterfactual(
        shared,
        source,
        context,
        frozen,
    )
    base = shared.solution
    owners = context.customer_home_depot or infer_customer_home_depots(
        context.instance
    )
    pairs = _selected_route_pairs(base, context, frozen.max_route_pairs)
    candidates: list[PairResplitCandidate] = []
    seen_boundaries: set[
        tuple[int, int, tuple[str, ...], tuple[str, ...]]
    ] = set()
    activity: dict[str, Any] = {
        "route_pairs_considered": len(pairs),
        "unique_sequences": 0,
        "cut_positions_considered": 0,
        "common_local_feasibility_checks": 0,
        "common_candidates": 0,
        "route_variant_calls": 0,
        "charge_repair_calls": 0,
        "route_proxy_evaluations": 0,
        "distance_scores": 0,
        "mechanism_scores": 0,
        "complete_route_search_evaluations": 0,
    }
    effective_prices = _effective_prices(context)
    for left_index, right_index in pairs:
        left_route = base.routes[left_index]
        right_route = base.routes[right_index]
        left_source = _route_customers(left_route, context)
        right_source = _route_customers(right_route, context)
        sequences = _unique_sequences(
            left_source,
            right_source,
            frozen.max_unique_sequences,
        )
        activity["unique_sequences"] += len(sequences)
        for sequence in sequences:
            cuts = _bounded_cut_positions(
                len(sequence),
                frozen.max_cut_positions,
            )
            activity["cut_positions_considered"] += len(cuts)
            for cut in cuts:
                left_customers = sequence[:cut]
                right_customers = sequence[cut:]
                boundary = (
                    left_index,
                    right_index,
                    left_customers,
                    right_customers,
                )
                if boundary in seen_boundaries:
                    continue
                seen_boundaries.add(boundary)
                if (
                    left_customers == left_source
                    and right_customers == right_source
                ):
                    continue
                left_feasible = _route_locally_feasible(
                    left_route.home_depot_id,
                    left_customers,
                    context,
                )
                right_feasible = _route_locally_feasible(
                    right_route.home_depot_id,
                    right_customers,
                    context,
                )
                activity["common_local_feasibility_checks"] += 2
                if not left_feasible or not right_feasible:
                    continue
                left_probe = Route(
                    vehicle_id=f"PAIR_PROXY_LEFT_{left_index}",
                    vehicle_type="cv",
                    home_depot_id=left_route.home_depot_id,
                    node_sequence=[
                        left_route.home_depot_id,
                        *left_customers,
                        left_route.home_depot_id,
                    ],
                )
                right_probe = Route(
                    vehicle_id=f"PAIR_PROXY_RIGHT_{right_index}",
                    vehicle_type="cv",
                    home_depot_id=right_route.home_depot_id,
                    node_sequence=[
                        right_route.home_depot_id,
                        *right_customers,
                        right_route.home_depot_id,
                    ],
                )
                left_variants = _route_variants(
                    left_probe,
                    current_actions=(),
                    instance=context.instance,
                    carbon_profile=context.carbon_profile,
                    prices=effective_prices,
                )
                right_variants = _route_variants(
                    right_probe,
                    current_actions=(),
                    instance=context.instance,
                    carbon_profile=context.carbon_profile,
                    prices=effective_prices,
                )
                activity["route_variant_calls"] += 2
                activity["charge_repair_calls"] += 2
                activity["route_proxy_evaluations"] += (
                    len(left_variants) + len(right_variants)
                )
                if "cv" not in left_variants or "cv" not in right_variants:
                    continue
                distance_score = (
                    _route_distance(
                        left_route.home_depot_id,
                        left_customers,
                        context,
                    )
                    + _route_distance(
                        right_route.home_depot_id,
                        right_customers,
                        context,
                    )
                )
                mechanism_score = (
                    min(
                        float(variant.proxy_cost)
                        for variant in left_variants.values()
                    )
                    + min(
                        float(variant.proxy_cost)
                        for variant in right_variants.values()
                    )
                    + _cross_site_proxy(
                        left_route.home_depot_id,
                        left_customers,
                        owners,
                        effective_prices,
                    )
                    + _cross_site_proxy(
                        right_route.home_depot_id,
                        right_customers,
                        owners,
                        effective_prices,
                    )
                )
                activity["distance_scores"] += 1
                activity["mechanism_scores"] += 1
                metadata = {
                    "left_route_index": left_index,
                    "right_route_index": right_index,
                    "left_customers": list(left_customers),
                    "right_customers": list(right_customers),
                    "distance_score": float(distance_score),
                    "mechanism_score": float(mechanism_score),
                    "left_variants": _variant_manifest(left_variants),
                    "right_variants": _variant_manifest(right_variants),
                }
                candidates.append(
                    PairResplitCandidate(
                        left_route_index=left_index,
                        right_route_index=right_index,
                        left_customers=left_customers,
                        right_customers=right_customers,
                        distance_score=_finite_cost(
                            distance_score,
                            "distance score",
                        ),
                        mechanism_score=_finite_cost(
                            mechanism_score,
                            "mechanism score",
                        ),
                        candidate_sha256=_json_sha256(metadata),
                        left_variants=left_variants,
                        right_variants=right_variants,
                    )
                )
    candidates = sorted(candidates, key=lambda item: item.boundary_key)
    activity["common_candidates"] = len(candidates)
    _assert_preparation_caps(activity, frozen, candidates)
    candidate_set_sha = _candidate_set_sha256(candidates)
    prepared_payload = _prepared_integrity_payload(
        source_sha=source_sha,
        context_sha=_context_sha256(context),
        counterfactual=shared,
        config=frozen,
        candidates=candidates,
        candidate_set_sha=candidate_set_sha,
        activity=activity,
    )
    return PreparedPairResplit(
        source=source,
        source_sha256=source_sha,
        counterfactual=shared,
        context=context,
        context_sha256=_context_sha256(context),
        config=frozen,
        candidates=tuple(candidates),
        candidate_set_sha256=candidate_set_sha,
        preparation_activity=activity,
        integrity_sha256=_json_sha256(prepared_payload),
    )


def run_pair_resplit_arm(
    prepared: PreparedPairResplit,
    *,
    arm: str,
    exact_candidate_capacity: int | None = None,
) -> PairResplitResult:
    """Run one ranking arm over an already-shared, integrity-checked pool."""

    verify_prepared_pool(prepared)
    if arm not in ALLOWED_ARMS:
        raise ValueError(f"unknown pair-resplit arm: {arm}")
    capacity = (
        prepared.config.max_exact_candidates
        if exact_candidate_capacity is None
        else _strict_nonnegative_int(
            exact_candidate_capacity,
            "exact_candidate_capacity",
        )
    )
    if capacity > prepared.config.max_exact_candidates:
        raise ValueError(
            "exact_candidate_capacity exceeds the pre-registered cap"
        )
    score_name = (
        "mechanism_score" if arm == MECHANISM_ARM else "distance_score"
    )
    ordered = sorted(
        prepared.candidates,
        key=lambda item: (
            float(getattr(item, score_name)),
            item.boundary_key,
            item.candidate_sha256,
        ),
    )
    selected = ordered[:capacity]
    records: list[dict[str, Any]] = []
    total_patterns = 0
    total_joint_checks = 0
    total_full_replays = 0
    total_generated_starts = 0
    total_retained_starts = 0
    total_local_start_evaluations = 0
    best_solution: Solution | None = None
    best_cost = math.inf
    best_candidate: PairResplitCandidate | None = None
    for rank, candidate in enumerate(selected, start=1):
        completed, completed_cost, completion_activity = _joint_complete_candidate(
            prepared,
            candidate,
        )
        total_patterns += int(completion_activity["vehicle_patterns"])
        total_joint_checks += int(
            completion_activity["joint_feasibility_checks"]
        )
        total_full_replays += int(
            completion_activity["joint_complete_replays"]
        )
        total_generated_starts += int(
            completion_activity["generated_charge_starts"]
        )
        total_retained_starts += int(
            completion_activity["retained_charge_starts"]
        )
        total_local_start_evaluations += int(
            completion_activity["local_start_evaluations"]
        )
        record: dict[str, Any] = {
            "rank": rank,
            "candidate_sha256": candidate.candidate_sha256,
            "left_route_index": candidate.left_route_index,
            "right_route_index": candidate.right_route_index,
            "left_customers": list(candidate.left_customers),
            "right_customers": list(candidate.right_customers),
            "distance_score": float(candidate.distance_score),
            "mechanism_score": float(candidate.mechanism_score),
            "completion": completion_activity,
            "feasible": completed is not None,
        }
        if completed is not None:
            if completed_cost is None:
                raise RuntimeError("completed candidate omitted its cost")
            cost = _finite_cost(completed_cost, "joint candidate cost")
            record["complete_cost"] = cost
            record["solution_sha256"] = solution_sha256(completed)
            if (
                cost < best_cost - TOL
                or (
                    abs(cost - best_cost) <= TOL
                    and best_candidate is not None
                    and candidate.candidate_sha256
                    < best_candidate.candidate_sha256
                )
            ):
                best_solution = completed
                best_cost = cost
                best_candidate = candidate
        records.append(record)
    accepted = (
        best_solution is not None
        and best_candidate is not None
        and best_cost < prepared.counterfactual.source_cost - TOL
        and best_cost < prepared.counterfactual.cost - TOL
        and _pair_boundary_changed(
            prepared.counterfactual.solution,
            best_solution,
            best_candidate,
            prepared.context,
        )
    )
    independent_replays = 0
    independent_feasibility_checks = 0
    if accepted:
        independent_cost = _finite_cost(
            model_cost(best_solution, prepared.context),
            "accepted independent replay",
        )
        independent_replays = 1
        if abs(independent_cost - best_cost) > 1.0e-7:
            raise RuntimeError("accepted candidate independent replay drifted")
        violations = _context_violations(best_solution, prepared.context)
        independent_feasibility_checks = 1
        if violations:
            raise RuntimeError(
                f"accepted pair-resplit candidate is infeasible: {violations[:8]}"
            )
        output = best_solution
        output_cost = independent_cost
        accepted_sha = best_candidate.candidate_sha256
    else:
        output = prepared.source
        output_cost = prepared.counterfactual.source_cost
        accepted_sha = None
    activity: dict[str, Any] = {
        "arm": arm,
        "ranking_score": score_name,
        "candidate_set_sha256": prepared.candidate_set_sha256,
        "prepared_integrity_sha256": prepared.integrity_sha256,
        "exact_candidate_capacity": capacity,
        "exact_candidates_completed": len(selected),
        "vehicle_patterns": total_patterns,
        "joint_feasibility_checks": total_joint_checks,
        "joint_complete_replays": total_full_replays,
        "generated_charge_starts": total_generated_starts,
        "retained_charge_starts": total_retained_starts,
        "local_start_evaluations": total_local_start_evaluations,
        "independent_replays": independent_replays,
        "independent_feasibility_checks": independent_feasibility_checks,
        "accepted_moves": int(accepted),
        "complete_route_search_evaluations": 0,
        "records": records,
    }
    _assert_arm_caps(activity, prepared.config)
    result_payload = _result_payload(
        arm=arm,
        solution=output,
        cost=float(output_cost),
        source_cost=float(prepared.counterfactual.source_cost),
        counterfactual_cost=float(prepared.counterfactual.cost),
        feasible=True,
        changed=bool(accepted),
        accepted_candidate_sha256=accepted_sha,
        activity=activity,
    )
    result = PairResplitResult(
        **result_payload,
        result_sha256=_json_sha256(
            {
                **result_payload,
                "solution": solution_sha256(output),
            }
        ),
    )
    verify_pair_resplit_result(result, prepared)
    return result


def verify_prepared_pool(prepared: PreparedPairResplit) -> None:
    """Reject a changed source, counterfactual, candidate, score, or ledger."""

    frozen = _validated_config(prepared.config)
    if solution_sha256(prepared.source) != prepared.source_sha256:
        raise RuntimeError("prepared source hash drifted")
    if _context_sha256(prepared.context) != prepared.context_sha256:
        raise RuntimeError("prepared context hash drifted")
    _verify_counterfactual(
        prepared.counterfactual,
        prepared.source,
        prepared.context,
        frozen,
    )
    candidates = list(prepared.candidates)
    if _candidate_set_sha256(candidates) != prepared.candidate_set_sha256:
        raise RuntimeError("prepared candidate-set hash drifted")
    _assert_preparation_caps(
        prepared.preparation_activity,
        frozen,
        candidates,
    )
    expected = _json_sha256(
        _prepared_integrity_payload(
            source_sha=prepared.source_sha256,
            context_sha=prepared.context_sha256,
            counterfactual=prepared.counterfactual,
            config=frozen,
            candidates=candidates,
            candidate_set_sha=prepared.candidate_set_sha256,
            activity=prepared.preparation_activity,
        )
    )
    if expected != prepared.integrity_sha256:
        raise RuntimeError("prepared pool integrity hash drifted")


def joint_feasibility_probe(
    solution: Solution,
    context: EvaluationContext,
) -> dict[str, Any]:
    """Expose the authoritative joint check for the frozen negative fixture."""

    violations = _context_violations(solution, context)
    return {
        "feasible": not violations,
        "violation_count": len(violations),
        "violation_types": [violation.type for violation in violations],
        "solution_sha256": solution_sha256(solution),
        "independent_feasibility_checks": 1,
        "complete_route_search_evaluations": 0,
    }


def joint_completion_probe(
    solution: Solution,
    context: EvaluationContext,
    *,
    config: PairResplitConfig | None = None,
) -> dict[str, Any]:
    """Run the same bounded joint-completion path used by pair candidates."""

    frozen = _validated_config(config or PairResplitConfig())
    eligible = frozenset(route.vehicle_id for route in solution.routes)
    completed, activity = _bounded_charge_retime(
        solution,
        context,
        config=frozen,
        eligible_vehicle_ids=eligible,
        global_mode=False,
    )
    checks = _strict_activity(
        activity,
        "joint_feasibility_checks",
        frozen.max_joint_checks,
    )
    return {
        "feasible": completed is not None,
        "input_solution_sha256": solution_sha256(solution),
        "output_solution_sha256": (
            None if completed is None else solution_sha256(completed)
        ),
        "output_charging_actions": (
            []
            if completed is None
            else [asdict(action) for action in completed.charging_actions]
        ),
        "violation_types": list(activity.get("last_violation_types", [])),
        "joint_feasibility_checks": checks,
        "completion_activity": activity,
        "complete_route_search_evaluations": 0,
    }


def solution_sha256(solution: Solution) -> str:
    return _json_sha256(asdict(solution))


def verify_pair_resplit_result(
    result: PairResplitResult,
    prepared: PreparedPairResplit,
) -> None:
    """Reject a changed solution, result field, completion ledger, or signature."""

    verify_prepared_pool(prepared)
    if result.arm not in ALLOWED_ARMS:
        raise RuntimeError("result arm is invalid")
    if result.activity.get("arm") != result.arm:
        raise RuntimeError("result arm/activity drifted")
    expected_score = (
        "mechanism_score"
        if result.arm == MECHANISM_ARM
        else "distance_score"
    )
    if result.activity.get("ranking_score") != expected_score:
        raise RuntimeError("result ranking score drifted")
    if (
        result.activity.get("candidate_set_sha256")
        != prepared.candidate_set_sha256
    ):
        raise RuntimeError("result candidate-set hash drifted")
    if (
        result.activity.get("prepared_integrity_sha256")
        != prepared.integrity_sha256
    ):
        raise RuntimeError("result prepared-integrity hash drifted")
    _assert_arm_caps(result.activity, prepared.config)
    capacity = _strict_activity(
        result.activity,
        "exact_candidate_capacity",
        prepared.config.max_exact_candidates,
    )
    expected_candidates = sorted(
        prepared.candidates,
        key=lambda item: (
            float(getattr(item, expected_score)),
            item.boundary_key,
            item.candidate_sha256,
        ),
    )[:capacity]
    records = result.activity["records"]
    if [record["candidate_sha256"] for record in records] != [
        candidate.candidate_sha256 for candidate in expected_candidates
    ]:
        raise RuntimeError("result completed the wrong ranked candidates")
    if abs(result.source_cost - prepared.counterfactual.source_cost) > TOL:
        raise RuntimeError("result source cost drifted")
    if abs(result.counterfactual_cost - prepared.counterfactual.cost) > TOL:
        raise RuntimeError("result counterfactual cost drifted")
    accepted = _strict_nonnegative_int(
        result.activity["accepted_moves"],
        "accepted_moves",
    )
    feasible_records = [
        record for record in records if record["feasible"]
    ]
    best_record = (
        None
        if not feasible_records
        else min(
            feasible_records,
            key=lambda record: (
                float(record["complete_cost"]),
                record["candidate_sha256"],
            ),
        )
    )
    expected_changed = (
        best_record is not None
        and float(best_record["complete_cost"])
        < prepared.counterfactual.source_cost - TOL
        and float(best_record["complete_cost"])
        < prepared.counterfactual.cost - TOL
    )
    if not isinstance(result.feasible, bool) or not result.feasible:
        raise RuntimeError("result feasibility flag is invalid")
    if (
        not isinstance(result.changed, bool)
        or result.changed != bool(accepted)
        or result.changed != expected_changed
    ):
        raise RuntimeError("result changed flag drifted")
    if result.changed:
        assert best_record is not None
        if (
            result.accepted_candidate_sha256 is None
            or result.accepted_candidate_sha256
            != best_record["candidate_sha256"]
            or best_record["solution_sha256"]
            != solution_sha256(result.solution)
            or abs(float(best_record["complete_cost"]) - result.cost)
            > 1.0e-7
        ):
            raise RuntimeError("result accepted candidate drifted")
        if not (
            result.cost < result.source_cost - TOL
            and result.cost < result.counterfactual_cost - TOL
        ):
            raise RuntimeError("result accepted a non-improving candidate")
    else:
        if result.accepted_candidate_sha256 is not None:
            raise RuntimeError("unchanged result names an accepted candidate")
        if solution_sha256(result.solution) != prepared.source_sha256:
            raise RuntimeError("unchanged result did not return the source")
        if abs(result.cost - result.source_cost) > TOL:
            raise RuntimeError("unchanged result cost drifted")
    expected_hash = _json_sha256(
        {
            **_result_payload(
                arm=result.arm,
                solution=result.solution,
                cost=result.cost,
                source_cost=result.source_cost,
                counterfactual_cost=result.counterfactual_cost,
                feasible=result.feasible,
                changed=result.changed,
                accepted_candidate_sha256=(
                    result.accepted_candidate_sha256
                ),
                activity=result.activity,
            ),
            "solution": solution_sha256(result.solution),
        }
    )
    if result.result_sha256 != expected_hash:
        raise RuntimeError("result signature drifted")


def _result_payload(
    *,
    arm: str,
    solution: Solution,
    cost: float,
    source_cost: float,
    counterfactual_cost: float,
    feasible: bool,
    changed: bool,
    accepted_candidate_sha256: str | None,
    activity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "arm": arm,
        "solution": solution,
        "cost": float(cost),
        "source_cost": float(source_cost),
        "counterfactual_cost": float(counterfactual_cost),
        "feasible": feasible,
        "changed": changed,
        "accepted_candidate_sha256": accepted_candidate_sha256,
        "activity": activity,
    }


def _joint_complete_candidate(
    prepared: PreparedPairResplit,
    candidate: PairResplitCandidate,
) -> tuple[Solution | None, float | None, dict[str, Any]]:
    patterns = tuple(
        product(
            tuple(sorted(candidate.left_variants)),
            tuple(sorted(candidate.right_variants)),
        )
    )[: prepared.config.max_vehicle_patterns]
    owners = (
        prepared.context.customer_home_depot
        or infer_customer_home_depots(prepared.context.instance)
    )
    best: Solution | None = None
    best_cost = math.inf
    records: list[dict[str, Any]] = []
    total_checks = 0
    total_replays = 0
    total_generated_starts = 0
    total_retained_starts = 0
    total_local_start_evaluations = 0
    for pattern in patterns:
        assembled, pair_vehicle_ids, reason = _assemble_pair_pattern(
            prepared.counterfactual.solution,
            candidate,
            pattern,
            prepared.context,
            owners,
        )
        record: dict[str, Any] = {
            "pattern": list(pattern),
            "assembled": assembled is not None,
            "assembly_reason": reason,
            "feasible": False,
        }
        if assembled is None:
            records.append(record)
            continue
        completed, retime = _bounded_charge_retime(
            assembled,
            prepared.context,
            config=prepared.config,
            eligible_vehicle_ids=pair_vehicle_ids,
            global_mode=False,
        )
        total_checks += int(retime["joint_feasibility_checks"])
        total_generated_starts += int(retime["generated_charge_starts"])
        total_retained_starts += int(retime["retained_charge_starts"])
        total_local_start_evaluations += int(
            retime["local_start_evaluations"]
        )
        record["retime"] = retime
        record["feasible"] = completed is not None
        if completed is not None:
            invariants = _candidate_invariants(
                prepared.counterfactual.solution,
                completed,
                candidate,
                prepared.context,
            )
            record["invariants"] = invariants
            if not all(invariants.values()):
                record["feasible"] = False
                records.append(record)
                continue
            total_replays += 1
            cost = _finite_cost(
                model_cost(completed, prepared.context),
                "pair pattern cost",
            )
            record["complete_cost"] = cost
            record["solution_sha256"] = solution_sha256(completed)
            if (
                cost < best_cost - TOL
                or (
                    abs(cost - best_cost) <= TOL
                    and best is not None
                    and solution_sha256(completed) < solution_sha256(best)
                )
            ):
                best = completed
                best_cost = cost
        records.append(record)
    activity = {
        "vehicle_patterns": len(patterns),
        "joint_feasibility_checks": total_checks,
        "joint_complete_replays": total_replays,
        "generated_charge_starts": total_generated_starts,
        "retained_charge_starts": total_retained_starts,
        "local_start_evaluations": total_local_start_evaluations,
        "complete_route_search_evaluations": 0,
        "records": records,
    }
    return best, (None if best is None else float(best_cost)), activity


def _assemble_pair_pattern(
    base: Solution,
    candidate: PairResplitCandidate,
    pattern: tuple[str, str],
    context: EvaluationContext,
    owners: dict[str, str],
) -> tuple[Solution | None, frozenset[str], str]:
    pair_indices = {
        candidate.left_route_index,
        candidate.right_route_index,
    }
    nonpair_routes = [
        route
        for index, route in enumerate(base.routes)
        if index not in pair_indices
    ]
    nonpair_physical_ids = {
        physical_vehicle_id(route.vehicle_id) for route in nonpair_routes
    }
    nonpair_counts = {
        vehicle_type: len(
            {
                physical_vehicle_id(route.vehicle_id)
                for route in nonpair_routes
                if route.vehicle_type.lower() == vehicle_type
            }
        )
        for vehicle_type in ("cv", "ev")
    }
    pair_type_counts = {
        vehicle_type: pattern.count(vehicle_type)
        for vehicle_type in ("cv", "ev")
    }
    for vehicle_type, count in pair_type_counts.items():
        cap = getattr(context.instance, f"num_{vehicle_type}", None)
        if cap is not None and nonpair_counts[vehicle_type] + count > int(cap):
            return None, frozenset(), f"{vehicle_type}_fleet_cap"
    selected_variants = (
        candidate.left_variants[pattern[0]],
        candidate.right_variants[pattern[1]],
    )
    route_indices = (
        candidate.left_route_index,
        candidate.right_route_index,
    )
    pair_routes: dict[int, Route] = {}
    pair_actions: list[ChargingAction] = []
    pair_vehicle_ids: set[str] = set()
    for position, (route_index, variant, vehicle_type) in enumerate(
        zip(route_indices, selected_variants, pattern),
        start=1,
    ):
        base_id = f"PAIR_{vehicle_type.upper()}_{route_index}_{position}"
        while base_id in nonpair_physical_ids or base_id in {
            physical_vehicle_id(vehicle_id)
            for vehicle_id in pair_vehicle_ids
        }:
            base_id = f"{base_id}_X"
        vehicle_id = f"{base_id}#T1"
        pair_vehicle_ids.add(vehicle_id)
        pair_routes[route_index] = replace(
            variant.route,
            vehicle_id=vehicle_id,
        )
        pair_actions.extend(
            replace(action, vehicle_id=vehicle_id)
            for action in variant.actions
        )
    routes = [
        pair_routes.get(index, route)
        for index, route in enumerate(base.routes)
    ]
    pair_original_ids = {
        base.routes[index].vehicle_id for index in pair_indices
    }
    actions = [
        action
        for action in base.charging_actions
        if action.vehicle_id not in pair_original_ids
    ]
    actions.extend(pair_actions)
    assembled = annotate_cross_site_services(
        Solution(
            routes=routes,
            charging_actions=actions,
            cross_site_services=list(base.cross_site_services),
        ),
        owners,
    )
    if len(
        {physical_vehicle_id(vehicle_id) for vehicle_id in pair_vehicle_ids}
    ) != 2:
        return None, frozenset(), "pair_physical_id_reuse"
    if any(
        physical_vehicle_id(vehicle_id) in nonpair_physical_ids
        for vehicle_id in pair_vehicle_ids
    ):
        return None, frozenset(), "nonpair_physical_id_reuse"
    return assembled, frozenset(pair_vehicle_ids), "assembled"


def _assemble_global_pattern(
    source: Solution,
    route_variants: list[dict[str, RouteVariant]],
    pattern: tuple[str, ...],
    owners: dict[str, str],
) -> Solution:
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for index, vehicle_type in enumerate(pattern):
        variant = route_variants[index][vehicle_type]
        original_id = source.routes[index].vehicle_id
        routes.append(replace(variant.route, vehicle_id=original_id))
        actions.extend(
            replace(action, vehicle_id=original_id)
            for action in variant.actions
        )
    return annotate_cross_site_services(
        Solution(
            routes=routes,
            charging_actions=actions,
            cross_site_services=list(source.cross_site_services),
        ),
        owners,
    )


def _bounded_charge_retime(
    solution: Solution,
    context: EvaluationContext,
    *,
    config: PairResplitConfig,
    eligible_vehicle_ids: frozenset[str] | None,
    global_mode: bool,
) -> tuple[Solution | None, dict[str, Any]]:
    routes = {route.vehicle_id: route for route in solution.routes}
    indexed_actions = [
        (index, action)
        for index, action in enumerate(solution.charging_actions)
        if eligible_vehicle_ids is None
        or action.vehicle_id in eligible_vehicle_ids
    ]
    skipped_actions = 0
    if len(indexed_actions) > config.max_charge_actions:
        if not global_mode:
            return None, {
                "stop_reason": "pair_charge_action_cap",
                "charge_actions_seen": len(indexed_actions),
                "charge_actions_selected": 0,
                "charge_actions_skipped": len(indexed_actions),
                "generated_charge_starts": 0,
                "retained_charge_starts": 0,
                "local_start_evaluations": 0,
                "joint_feasibility_checks": 0,
                "last_violation_types": [],
            }
        ranked = sorted(
            indexed_actions,
            key=lambda item: (
                -_rough_carbon_saving(item[1], context),
                item[1].vehicle_id,
                item[1].station_id,
                item[0],
            ),
        )
        indexed_actions = ranked[: config.max_charge_actions]
        skipped_actions = len(ranked) - len(indexed_actions)

    proposals: list[
        tuple[int, ChargingAction, ChargingAction, float, float]
    ] = []
    generated_starts = 0
    retained_starts = 0
    local_evaluations = 0
    for index, action in indexed_actions:
        route = routes.get(action.vehicle_id)
        if route is None:
            continue
        window = _charge_action_window(
            action_index=index,
            action=action,
            route=route,
            solution=solution,
            context=context,
        )
        if window is None:
            continue
        raw_starts = depot_charge_candidate_starts(
            earliest_start=window[0],
            latest_start=window[1],
            occupancy_seconds=float(action.occupancy_minutes) * 60.0,
            current_start=float(action.charge_start_second),
        )
        generated_starts += len(raw_starts)
        starts = _bounded_starts(
            raw_starts,
            current=float(action.charge_start_second),
            limit=config.max_charge_starts,
        )
        retained_starts += len(starts)
        old_local = float(_depot_charge_local_objective(action, context))
        options: list[tuple[float, float, ChargingAction]] = []
        for start in starts:
            changed = replace(action, charge_start_second=float(start))
            objective = float(_depot_charge_local_objective(changed, context))
            local_evaluations += 1
            options.append((objective, float(start), changed))
        if not options:
            continue
        selected_local, _, selected_action = min(options)
        if selected_local < old_local - 1.0e-12:
            proposals.append(
                (
                    index,
                    action,
                    selected_action,
                    old_local,
                    selected_local,
                )
            )
    proposals.sort(
        key=lambda item: (
            float(item[4] - item[3]),
            item[1].vehicle_id,
            item[1].station_id,
            item[0],
        )
    )
    checks = 0
    if not proposals:
        checks += 1
        violations = _context_violations(solution, context)
        feasible = not violations
        return (
            solution if feasible else None,
            {
                "stop_reason": (
                    "no_improving_retime"
                    if feasible
                    else "base_joint_infeasible"
                ),
                "charge_actions_seen": len(indexed_actions) + skipped_actions,
                "charge_actions_selected": len(indexed_actions),
                "charge_actions_skipped": skipped_actions,
                "generated_charge_starts": generated_starts,
                "retained_charge_starts": retained_starts,
                "local_start_evaluations": local_evaluations,
                "joint_feasibility_checks": checks,
                "last_violation_types": [
                    violation.type for violation in violations
                ],
            },
        )

    all_actions = list(solution.charging_actions)
    for index, _, selected_action, _, _ in proposals:
        all_actions[index] = selected_action
    all_best = replace(solution, charging_actions=all_actions)
    checks += 1
    all_best_violations = _context_violations(all_best, context)
    if not all_best_violations:
        return all_best, {
            "stop_reason": "all_local_best_joint_feasible",
            "charge_actions_seen": len(indexed_actions) + skipped_actions,
            "charge_actions_selected": len(indexed_actions),
            "charge_actions_skipped": skipped_actions,
            "generated_charge_starts": generated_starts,
            "retained_charge_starts": retained_starts,
            "local_start_evaluations": local_evaluations,
            "joint_feasibility_checks": checks,
            "last_violation_types": [],
        }

    selected_actions = list(solution.charging_actions)
    current_solution: Solution | None = None
    last_violations = all_best_violations
    checks += 1
    source_violations = _context_violations(solution, context)
    last_violations = source_violations
    if not source_violations:
        current_solution = solution
    for index, _, selected_action, _, _ in proposals:
        if checks >= config.max_joint_checks:
            break
        trial_actions = (
            list(current_solution.charging_actions)
            if current_solution is not None
            else list(selected_actions)
        )
        trial_actions[index] = selected_action
        trial = replace(solution, charging_actions=trial_actions)
        checks += 1
        trial_violations = _context_violations(trial, context)
        last_violations = trial_violations
        if not trial_violations:
            current_solution = trial
            selected_actions = trial_actions
    return current_solution, {
        "stop_reason": (
            "sequential_joint_retime"
            if current_solution is not None
            else "no_joint_feasible_schedule"
        ),
        "charge_actions_seen": len(indexed_actions) + skipped_actions,
        "charge_actions_selected": len(indexed_actions),
        "charge_actions_skipped": skipped_actions,
        "generated_charge_starts": generated_starts,
        "retained_charge_starts": retained_starts,
        "local_start_evaluations": local_evaluations,
        "joint_feasibility_checks": checks,
        "last_violation_types": [
            violation.type for violation in last_violations
        ],
    }


def _charge_action_window(
    *,
    action_index: int,
    action: ChargingAction,
    route: Route,
    solution: Solution,
    context: EvaluationContext,
) -> tuple[float, float] | None:
    """Return a conservative feasible start window for depot or public charge."""

    if int(action.charge_day_offset) != 0:
        return None
    node_lookup = {node.node_id: node for node in context.instance.nodes}
    station = node_lookup.get(action.station_id)
    if station is None:
        return None
    station_type = station.node_type.lower()
    if station_type == "d":
        return _depot_action_window(action, route, context)
    if station_type != "f":
        return None
    occurrences = [
        index
        for index, node_id in enumerate(route.node_sequence)
        if node_id == action.station_id
    ]
    if len(occurrences) != 1:
        return None
    if any(
        index != action_index
        and other.vehicle_id == action.vehicle_id
        and other.station_id == action.station_id
        for index, other in enumerate(solution.charging_actions)
    ):
        return None
    other_actions = [
        other
        for index, other in enumerate(solution.charging_actions)
        if index != action_index
    ]
    base_schedule = route_node_schedule(
        route,
        context.instance,
        context.prices,
        charging_actions=other_actions,
    )
    station_index = occurrences[0]
    if station_index >= len(base_schedule):
        return None
    earliest = max(
        float(base_schedule[station_index].t_arrive),
        float(station.ready_time),
    )
    earliest_action = replace(
        action,
        charge_start_second=float(earliest),
    )
    earliest_actions = list(solution.charging_actions)
    earliest_actions[action_index] = earliest_action
    earliest_schedule = route_node_schedule(
        route,
        context.instance,
        context.prices,
        charging_actions=earliest_actions,
    )
    downstream_slacks = [
        float(node_lookup[row.node_id].due_time) - float(row.t_start)
        for row in earliest_schedule[station_index:]
    ]
    for later_index, row in enumerate(
        earliest_schedule[station_index + 1 :],
        start=station_index + 1,
    ):
        later_node_id = route.node_sequence[later_index]
        fixed_starts = [
            float(other.charge_start_second)
            for index, other in enumerate(solution.charging_actions)
            if index != action_index
            and other.vehicle_id == route.vehicle_id
            and other.station_id == later_node_id
            and int(other.charge_day_offset) == 0
        ]
        if fixed_starts:
            downstream_slacks.append(
                min(fixed_starts) - float(row.t_arrive)
            )
    if not downstream_slacks:
        return None
    slack = min(downstream_slacks)
    if slack < -TOL:
        return None
    latest = float(earliest + max(0.0, slack))
    return float(earliest), latest


def _selected_route_pairs(
    solution: Solution,
    context: EvaluationContext,
    limit: int,
) -> tuple[tuple[int, int], ...]:
    owners = context.customer_home_depot or infer_customer_home_depots(
        context.instance
    )
    actions_by_vehicle = {
        action.vehicle_id for action in solution.charging_actions
    }
    ranked: list[tuple[int, float, int, int]] = []
    for left_index in range(len(solution.routes)):
        left = solution.routes[left_index]
        left_customers = _route_customers(left, context)
        if not left_customers:
            continue
        for right_index in range(left_index + 1, len(solution.routes)):
            right = solution.routes[right_index]
            right_customers = _route_customers(right, context)
            if not right_customers:
                continue
            tension = (
                left.vehicle_type.lower() != right.vehicle_type.lower()
                or left.home_depot_id != right.home_depot_id
                or left.vehicle_id in actions_by_vehicle
                or right.vehicle_id in actions_by_vehicle
                or any(
                    owners.get(customer) not in {None, left.home_depot_id}
                    for customer in left_customers
                )
                or any(
                    owners.get(customer) not in {None, right.home_depot_id}
                    for customer in right_customers
                )
            )
            nearest = min(
                context.instance.distance(left_customer, right_customer)
                for left_customer in left_customers
                for right_customer in right_customers
            )
            ranked.append(
                (
                    0 if tension else 1,
                    float(nearest),
                    left_index,
                    right_index,
                )
            )
    return tuple(
        (left_index, right_index)
        for _, _, left_index, right_index in sorted(ranked)[:limit]
    )


def _unique_sequences(
    left: tuple[str, ...],
    right: tuple[str, ...],
    limit: int,
) -> tuple[tuple[str, ...], ...]:
    sequences: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for first, second in ((left, right), (right, left)):
        for reverse_first in (False, True):
            for reverse_second in (False, True):
                first_part = (
                    tuple(reversed(first)) if reverse_first else first
                )
                second_part = (
                    tuple(reversed(second)) if reverse_second else second
                )
                sequence = (*first_part, *second_part)
                if sequence in seen:
                    continue
                seen.add(sequence)
                sequences.append(sequence)
                if len(sequences) >= limit:
                    return tuple(sequences)
    return tuple(sequences)


def _bounded_cut_positions(
    sequence_length: int,
    limit: int,
) -> tuple[int, ...]:
    available = tuple(range(1, sequence_length))
    if len(available) <= limit:
        return available
    if limit == 0:
        return ()
    if limit == 1:
        return (available[0],)
    selected = {
        available[
            round(position * (len(available) - 1) / (limit - 1))
        ]
        for position in range(limit)
    }
    if len(selected) < limit:
        for value in available:
            selected.add(value)
            if len(selected) >= limit:
                break
    return tuple(sorted(selected))[:limit]


def _bounded_starts(
    starts: Iterable[float],
    *,
    current: float,
    limit: int,
) -> tuple[float, ...]:
    unique = tuple(sorted({float(value) for value in starts}))
    if len(unique) <= limit:
        return unique
    mandatory = {unique[0], unique[-1]}
    if any(abs(value - current) <= 1.0e-9 for value in unique):
        mandatory.add(
            min(unique, key=lambda value: abs(value - current))
        )
    remaining = tuple(value for value in unique if value not in mandatory)
    room = max(0, limit - len(mandatory))
    if room >= len(remaining):
        return tuple(sorted((*mandatory, *remaining)))
    if room == 1:
        sampled = (remaining[len(remaining) // 2],)
    elif room == 0:
        sampled = ()
    else:
        sampled = tuple(
            remaining[
                round(position * (len(remaining) - 1) / (room - 1))
            ]
            for position in range(room)
        )
    return tuple(sorted({*mandatory, *sampled}))[:limit]


def _route_locally_feasible(
    home_depot_id: str,
    customers: tuple[str, ...],
    context: EvaluationContext,
) -> bool:
    if not customers:
        return False
    node_lookup = {node.node_id: node for node in context.instance.nodes}
    if any(
        customer not in node_lookup
        or node_lookup[customer].node_type.lower() != "c"
        for customer in customers
    ):
        return False
    demand = sum(float(node_lookup[customer].demand) for customer in customers)
    if demand > _price(context.prices, "Q_capacity") + TOL:
        return False
    route = Route(
        "PAIR_LOCAL_CV",
        "cv",
        home_depot_id,
        [home_depot_id, *customers, home_depot_id],
    )
    try:
        schedule = route_node_schedule(
            route,
            context.instance,
            context.prices,
        )
    except (KeyError, ValueError):
        return False
    return all(
        row.t_start <= float(node_lookup[row.node_id].due_time) + TOL
        for row in schedule
    )


def _route_customers(
    route: Route,
    context: EvaluationContext,
) -> tuple[str, ...]:
    node_lookup = {node.node_id: node for node in context.instance.nodes}
    return tuple(
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None
        and node_lookup[node_id].node_type.lower() == "c"
    )


def _route_distance(
    home_depot_id: str,
    customers: Iterable[str],
    context: EvaluationContext,
) -> float:
    sequence = (home_depot_id, *customers, home_depot_id)
    return float(
        sum(
            context.instance.distance(left, right)
            for left, right in zip(sequence, sequence[1:])
        )
    )


def _cross_site_proxy(
    home_depot_id: str,
    customers: Iterable[str],
    owners: dict[str, str],
    prices: Any,
) -> float:
    return float(
        sum(
            _price(prices, "cross_site_cost")
            for customer in customers
            if owners.get(customer) is not None
            and owners[customer] != home_depot_id
        )
    )


def _pair_boundary_changed(
    base: Solution,
    candidate_solution: Solution,
    candidate: PairResplitCandidate,
    context: EvaluationContext,
) -> bool:
    return (
        _route_customers(
            base.routes[candidate.left_route_index],
            context,
        )
        != candidate.left_customers
        or _route_customers(
            base.routes[candidate.right_route_index],
            context,
        )
        != candidate.right_customers
    ) and (
        _route_customers(
            candidate_solution.routes[candidate.left_route_index],
            context,
        )
        == candidate.left_customers
        and _route_customers(
            candidate_solution.routes[candidate.right_route_index],
            context,
        )
        == candidate.right_customers
    )


def _candidate_invariants(
    base: Solution,
    candidate_solution: Solution,
    candidate: PairResplitCandidate,
    context: EvaluationContext,
) -> dict[str, bool]:
    pair_indices = {
        candidate.left_route_index,
        candidate.right_route_index,
    }
    route_count_unchanged = len(base.routes) == len(candidate_solution.routes)
    nonpair_routes_unchanged = route_count_unchanged and all(
        base.routes[index] == candidate_solution.routes[index]
        for index in range(len(base.routes))
        if index not in pair_indices
    )
    nonpair_ids = {
        base.routes[index].vehicle_id
        for index in range(len(base.routes))
        if index not in pair_indices
    }
    nonpair_actions = sorted(
        (
            action.vehicle_id,
            action.station_id,
            float(action.energy_kwh),
            float(action.occupancy_minutes),
            float(action.charge_start_second),
            int(action.charge_day_offset),
        )
        for action in base.charging_actions
        if action.vehicle_id in nonpair_ids
    )
    candidate_nonpair_actions = sorted(
        (
            action.vehicle_id,
            action.station_id,
            float(action.energy_kwh),
            float(action.occupancy_minutes),
            float(action.charge_start_second),
            int(action.charge_day_offset),
        )
        for action in candidate_solution.charging_actions
        if action.vehicle_id in nonpair_ids
    )
    pair_physical_ids = (
        {
            physical_vehicle_id(candidate_solution.routes[index].vehicle_id)
            for index in pair_indices
        }
        if route_count_unchanged
        else set()
    )
    nonpair_physical_ids = {
        physical_vehicle_id(base.routes[index].vehicle_id)
        for index in range(len(base.routes))
        if index not in pair_indices
    }
    return {
        "route_count_unchanged": route_count_unchanged,
        "boundary_changed_and_frozen": _pair_boundary_changed(
            base,
            candidate_solution,
            candidate,
            context,
        ),
        "nonpair_routes_unchanged": nonpair_routes_unchanged,
        "nonpair_actions_unchanged": (
            nonpair_actions == candidate_nonpair_actions
        ),
        "pair_physical_ids_unique": len(pair_physical_ids) == 2,
        "pair_physical_ids_not_reused": not (
            pair_physical_ids & nonpair_physical_ids
        ),
    }


def _context_violations(
    solution: Solution,
    context: EvaluationContext,
) -> list[Any]:
    effective_prices = _effective_prices(context)
    violations = check_solution(
        solution,
        context.instance,
        effective_prices,
        fairness_context=fairness_context_for_solution(
            solution,
            context,
            prices=effective_prices,
        ),
        fairness_enabled=context.fairness_enabled,
    )
    violations.extend(cross_depot_violations(solution, context))
    return violations


def _rough_carbon_saving(
    action: ChargingAction,
    context: EvaluationContext,
) -> float:
    if not context.carbon_profile:
        return 0.0
    current = float(
        context.carbon_profile[
            int(float(action.charge_start_second) // 1_800)
            % len(context.carbon_profile)
        ]["actual_gco2_per_kwh"]
    )
    minimum = min(
        float(row["actual_gco2_per_kwh"])
        for row in context.carbon_profile
    )
    return max(0.0, current - minimum) * float(action.energy_kwh)


def _effective_prices(context: EvaluationContext) -> Any:
    if abs(float(context.carbon_weight) - 1.0) <= 1.0e-12:
        return context.prices
    if isinstance(context.prices, PriceParameters):
        return replace(
            context.prices,
            carbon_price=(
                float(context.prices.carbon_price)
                * float(context.carbon_weight)
            ),
        )
    if isinstance(context.prices, dict):
        prices = dict(context.prices)
        prices["carbon_price"] = (
            float(prices["carbon_price"]) * float(context.carbon_weight)
        )
        return prices
    return replace(
        context.prices,
        carbon_price=(
            float(getattr(context.prices, "carbon_price"))
            * float(context.carbon_weight)
        ),
    )


def _validated_config(config: PairResplitConfig) -> PairResplitConfig:
    values = asdict(config)
    for name, value in values.items():
        _strict_nonnegative_int(value, name)
    hard_caps = {
        "max_route_pairs": 3,
        "max_unique_sequences": 8,
        "max_cut_positions": 16,
        "max_exact_candidates": 4,
        "max_vehicle_patterns": 4,
        "max_charge_actions": 8,
        "max_charge_starts": 16,
        "max_joint_checks": 9,
    }
    for name, cap in hard_caps.items():
        if int(values[name]) > cap:
            raise ValueError(f"{name} exceeds pre-registered cap {cap}")
    return config


def _assert_counterfactual_caps(
    activity: dict[str, Any],
    config: PairResplitConfig,
) -> None:
    _strict_exact_activity(activity, "source_feasibility_checks", 1)
    _strict_exact_activity(activity, "source_complete_replays", 1)
    patterns = _strict_activity(
        activity,
        "patterns_considered",
        config.max_vehicle_patterns,
    )
    replays = _strict_activity(
        activity,
        "joint_complete_replays",
        config.max_vehicle_patterns,
    )
    _strict_exact_activity(activity, "independent_replays", 1)
    _strict_activity(activity, "complete_route_search_evaluations", 0)
    checks = _strict_activity(
        activity,
        "joint_feasibility_checks",
        config.max_vehicle_patterns * config.max_joint_checks,
    )
    generated = _strict_nonnegative_int(
        activity.get("generated_charge_starts"),
        "generated_charge_starts",
    )
    retained = _strict_nonnegative_int(
        activity.get("retained_charge_starts"),
        "retained_charge_starts",
    )
    local = _strict_nonnegative_int(
        activity.get("local_start_evaluations"),
        "local_start_evaluations",
    )
    maximum_starts = (
        config.max_vehicle_patterns
        * config.max_charge_actions
        * config.max_charge_starts
    )
    if (
        retained > generated
        or retained > maximum_starts
        or local > retained
    ):
        raise RuntimeError("counterfactual charging-start ledger exceeded cap")
    records = activity.get("records")
    if not isinstance(records, list) or len(records) != patterns:
        raise RuntimeError("counterfactual record count drifted")
    if not records:
        raise RuntimeError("counterfactual omitted all pattern records")
    first_pattern = records[0].get("pattern")
    if not isinstance(first_pattern, list) or not first_pattern:
        raise RuntimeError("counterfactual current pattern is invalid")
    route_count = len(first_pattern)
    _strict_exact_activity(activity, "route_variant_calls", route_count)
    expected_charge_repairs = sum(
        vehicle_type != "ev" for vehicle_type in first_pattern
    )
    _strict_exact_activity(
        activity,
        "charge_repair_calls",
        expected_charge_repairs,
    )
    option_counts = activity.get("route_variant_option_counts")
    if (
        not isinstance(option_counts, list)
        or len(option_counts) != route_count
    ):
        raise RuntimeError("counterfactual route-variant options drifted")
    strict_option_counts = [
        _strict_nonnegative_int(value, "route variant option count")
        for value in option_counts
    ]
    if any(value < 1 or value > 2 for value in strict_option_counts):
        raise RuntimeError("counterfactual route-variant option cap drifted")
    proxy_evaluations = _strict_nonnegative_int(
        activity.get("route_proxy_evaluations"),
        "route_proxy_evaluations",
    )
    if proxy_evaluations != sum(strict_option_counts):
        raise RuntimeError("counterfactual route-proxy ledger drifted")
    sum_checks = 0
    sum_generated = 0
    sum_retained = 0
    sum_local = 0
    feasible_records = 0
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"counterfactual record {index} must be a mapping")
        pattern = record.get("pattern")
        if not isinstance(pattern, list) or len(pattern) != route_count:
            raise RuntimeError("counterfactual pattern record drifted")
        if not isinstance(record.get("feasible"), bool):
            raise ValueError("counterfactual feasible flag must be boolean")
        retime = record.get("retime")
        _assert_retime_activity(
            retime,
            config,
            f"counterfactual record {index}",
        )
        sum_checks += int(retime["joint_feasibility_checks"])
        sum_generated += int(retime["generated_charge_starts"])
        sum_retained += int(retime["retained_charge_starts"])
        sum_local += int(retime["local_start_evaluations"])
        if record["feasible"]:
            feasible_records += 1
            _finite_cost(record.get("complete_cost"), "counterfactual record cost")
            _assert_sha256(
                record.get("solution_sha256"),
                "counterfactual record solution",
            )
        elif "complete_cost" in record or "solution_sha256" in record:
            raise RuntimeError("infeasible counterfactual record contains a replay")
    if (
        feasible_records != replays
        or sum_checks != checks
        or sum_generated != generated
        or sum_retained != retained
        or sum_local != local
    ):
        raise RuntimeError("counterfactual nested ledger does not sum")


def _assert_preparation_caps(
    activity: dict[str, Any],
    config: PairResplitConfig,
    candidates: list[PairResplitCandidate],
) -> None:
    _strict_activity(activity, "route_pairs_considered", config.max_route_pairs)
    _strict_activity(activity, "complete_route_search_evaluations", 0)
    for key in (
        "unique_sequences",
        "cut_positions_considered",
        "common_local_feasibility_checks",
        "common_candidates",
        "route_variant_calls",
        "charge_repair_calls",
        "route_proxy_evaluations",
        "distance_scores",
        "mechanism_scores",
    ):
        _strict_nonnegative_int(activity.get(key), key)
    if activity["common_candidates"] != len(candidates):
        raise RuntimeError("common candidate ledger drifted")
    if activity["distance_scores"] != len(candidates):
        raise RuntimeError("distance score ledger drifted")
    if activity["mechanism_scores"] != len(candidates):
        raise RuntimeError("mechanism score ledger drifted")
    if activity["route_variant_calls"] != 2 * len(candidates):
        raise RuntimeError("route variant-call ledger drifted")
    if activity["charge_repair_calls"] != 2 * len(candidates):
        raise RuntimeError("charge-repair ledger drifted")
    expected_proxy_evaluations = sum(
        len(candidate.left_variants) + len(candidate.right_variants)
        for candidate in candidates
    )
    if activity["route_proxy_evaluations"] != expected_proxy_evaluations:
        raise RuntimeError("route proxy-evaluation ledger drifted")
    if expected_proxy_evaluations > 4 * len(candidates):
        raise RuntimeError("route proxy-evaluation cap exceeded")
    max_sequences = config.max_route_pairs * config.max_unique_sequences
    if activity["unique_sequences"] > max_sequences:
        raise RuntimeError("unique sequence cap exceeded")
    max_cuts = max_sequences * config.max_cut_positions
    if activity["cut_positions_considered"] > max_cuts:
        raise RuntimeError("cut-position cap exceeded")
    local_checks = activity["common_local_feasibility_checks"]
    if local_checks % 2 != 0 or local_checks > 2 * max_cuts:
        raise RuntimeError("common local-feasibility ledger drifted")


def _assert_arm_caps(
    activity: dict[str, Any],
    config: PairResplitConfig,
) -> None:
    exact = _strict_activity(
        activity,
        "exact_candidates_completed",
        config.max_exact_candidates,
    )
    capacity = _strict_activity(
        activity,
        "exact_candidate_capacity",
        config.max_exact_candidates,
    )
    if exact > capacity:
        raise RuntimeError("completed more exact candidates than capacity")
    accepted = _strict_activity(activity, "accepted_moves", 1)
    independent = _strict_activity(activity, "independent_replays", 1)
    feasibility = _strict_activity(
        activity,
        "independent_feasibility_checks",
        1,
    )
    if independent != accepted or feasibility != accepted:
        raise RuntimeError("accepted-move independent ledger drifted")
    _strict_activity(activity, "complete_route_search_evaluations", 0)
    patterns = _strict_activity(
        activity,
        "vehicle_patterns",
        exact * config.max_vehicle_patterns,
    )
    replays = _strict_activity(
        activity,
        "joint_complete_replays",
        exact * config.max_vehicle_patterns,
    )
    checks = _strict_activity(
        activity,
        "joint_feasibility_checks",
        exact * config.max_vehicle_patterns * config.max_joint_checks,
    )
    generated = _strict_nonnegative_int(
        activity.get("generated_charge_starts"),
        "generated_charge_starts",
    )
    retained = _strict_nonnegative_int(
        activity.get("retained_charge_starts"),
        "retained_charge_starts",
    )
    local = _strict_nonnegative_int(
        activity.get("local_start_evaluations"),
        "local_start_evaluations",
    )
    maximum_starts = (
        exact
        * config.max_vehicle_patterns
        * config.max_charge_actions
        * config.max_charge_starts
    )
    if (
        retained > generated
        or retained > maximum_starts
        or local > retained
    ):
        raise RuntimeError("arm charging-start ledger exceeded cap")
    records = activity.get("records")
    if not isinstance(records, list) or len(records) != exact:
        raise RuntimeError("arm completion-record count drifted")
    ranks = [
        _strict_nonnegative_int(
            record.get("rank") if isinstance(record, dict) else None,
            f"arm record {index} rank",
        )
        for index, record in enumerate(records, start=1)
    ]
    if ranks != list(range(1, exact + 1)):
        raise RuntimeError("arm completion ranks drifted")
    candidate_hashes: list[str] = []
    sum_patterns = 0
    sum_checks = 0
    sum_replays = 0
    sum_generated = 0
    sum_retained = 0
    sum_local = 0
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"arm record {index} must be a mapping")
        candidate_hashes.append(
            _assert_sha256(
                record.get("candidate_sha256"),
                f"arm record {index} candidate",
            )
        )
        if not isinstance(record.get("feasible"), bool):
            raise ValueError("arm candidate feasible flag must be boolean")
        completion = record.get("completion")
        _assert_completion_activity(
            completion,
            config,
            f"arm record {index}",
        )
        feasible_patterns = [
            pattern
            for pattern in completion["records"]
            if pattern["feasible"]
        ]
        if record["feasible"] != bool(feasible_patterns):
            raise RuntimeError("arm candidate/completion feasibility drifted")
        sum_patterns += int(completion["vehicle_patterns"])
        sum_checks += int(completion["joint_feasibility_checks"])
        sum_replays += int(completion["joint_complete_replays"])
        sum_generated += int(completion["generated_charge_starts"])
        sum_retained += int(completion["retained_charge_starts"])
        sum_local += int(completion["local_start_evaluations"])
        if record["feasible"]:
            outer_cost = _finite_cost(
                record.get("complete_cost"),
                "arm record cost",
            )
            outer_sha = _assert_sha256(
                record.get("solution_sha256"),
                "arm record solution",
            )
            nested_best = min(
                feasible_patterns,
                key=lambda pattern: (
                    float(pattern["complete_cost"]),
                    pattern["solution_sha256"],
                ),
            )
            if (
                abs(outer_cost - float(nested_best["complete_cost"]))
                > TOL
                or outer_sha != nested_best["solution_sha256"]
            ):
                raise RuntimeError("arm candidate best-completion record drifted")
        elif "complete_cost" in record or "solution_sha256" in record:
            raise RuntimeError("infeasible arm record contains a replay")
    if len(set(candidate_hashes)) != len(candidate_hashes):
        raise RuntimeError("arm repeated an exact candidate")
    if (
        sum_patterns != patterns
        or sum_checks != checks
        or sum_replays != replays
        or sum_generated != generated
        or sum_retained != retained
        or sum_local != local
    ):
        raise RuntimeError("arm nested ledger does not sum")


def _assert_completion_activity(
    activity: Any,
    config: PairResplitConfig,
    label: str,
) -> None:
    if not isinstance(activity, dict):
        raise ValueError(f"{label} completion must be a mapping")
    patterns = _strict_activity(
        activity,
        "vehicle_patterns",
        config.max_vehicle_patterns,
    )
    checks = _strict_activity(
        activity,
        "joint_feasibility_checks",
        patterns * config.max_joint_checks,
    )
    replays = _strict_activity(
        activity,
        "joint_complete_replays",
        patterns,
    )
    _strict_activity(activity, "complete_route_search_evaluations", 0)
    generated = _strict_nonnegative_int(
        activity.get("generated_charge_starts"),
        f"{label} generated_charge_starts",
    )
    retained = _strict_nonnegative_int(
        activity.get("retained_charge_starts"),
        f"{label} retained_charge_starts",
    )
    local = _strict_nonnegative_int(
        activity.get("local_start_evaluations"),
        f"{label} local_start_evaluations",
    )
    records = activity.get("records")
    if not isinstance(records, list) or len(records) != patterns:
        raise RuntimeError(f"{label} pattern-record count drifted")
    sum_checks = 0
    sum_generated = 0
    sum_retained = 0
    sum_local = 0
    feasible_records = 0
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"{label} pattern {index} must be a mapping")
        if not isinstance(record.get("assembled"), bool):
            raise ValueError(f"{label} assembled flag must be boolean")
        if not isinstance(record.get("feasible"), bool):
            raise ValueError(f"{label} feasible flag must be boolean")
        if not record["assembled"]:
            if record["feasible"] or "retime" in record:
                raise RuntimeError(f"{label} unassembled pattern drifted")
            continue
        retime = record.get("retime")
        _assert_retime_activity(retime, config, f"{label} pattern {index}")
        sum_checks += int(retime["joint_feasibility_checks"])
        sum_generated += int(retime["generated_charge_starts"])
        sum_retained += int(retime["retained_charge_starts"])
        sum_local += int(retime["local_start_evaluations"])
        if record["feasible"]:
            feasible_records += 1
            invariants = record.get("invariants")
            if (
                not isinstance(invariants, dict)
                or not invariants
                or not all(
                    isinstance(value, bool) and value
                    for value in invariants.values()
                )
            ):
                raise RuntimeError(f"{label} invariant record drifted")
            _finite_cost(record.get("complete_cost"), f"{label} pattern cost")
            _assert_sha256(
                record.get("solution_sha256"),
                f"{label} pattern solution",
            )
        elif "complete_cost" in record or "solution_sha256" in record:
            raise RuntimeError(f"{label} infeasible pattern contains a replay")
    if (
        feasible_records != replays
        or sum_checks != checks
        or sum_generated != generated
        or sum_retained != retained
        or sum_local != local
    ):
        raise RuntimeError(f"{label} nested completion ledger does not sum")


def _assert_retime_activity(
    activity: Any,
    config: PairResplitConfig,
    label: str,
) -> None:
    if not isinstance(activity, dict):
        raise ValueError(f"{label} retime must be a mapping")
    seen = _strict_nonnegative_int(
        activity.get("charge_actions_seen"),
        f"{label} charge_actions_seen",
    )
    selected = _strict_activity(
        activity,
        "charge_actions_selected",
        config.max_charge_actions,
    )
    skipped = _strict_nonnegative_int(
        activity.get("charge_actions_skipped"),
        f"{label} charge_actions_skipped",
    )
    if seen != selected + skipped:
        raise RuntimeError(f"{label} charge-action ledger drifted")
    generated = _strict_nonnegative_int(
        activity.get("generated_charge_starts"),
        f"{label} generated_charge_starts",
    )
    retained = _strict_nonnegative_int(
        activity.get("retained_charge_starts"),
        f"{label} retained_charge_starts",
    )
    local = _strict_nonnegative_int(
        activity.get("local_start_evaluations"),
        f"{label} local_start_evaluations",
    )
    if (
        retained > generated
        or retained > selected * config.max_charge_starts
        or local > retained
    ):
        raise RuntimeError(f"{label} charging-start ledger exceeded cap")
    _strict_activity(
        activity,
        "joint_feasibility_checks",
        config.max_joint_checks,
    )
    if not isinstance(activity.get("stop_reason"), str):
        raise ValueError(f"{label} stop reason must be text")
    violations = activity.get("last_violation_types")
    if not isinstance(violations, list) or not all(
        isinstance(value, str) for value in violations
    ):
        raise ValueError(f"{label} violation-type ledger must be text list")


def _strict_activity(
    activity: dict[str, Any],
    key: str,
    maximum: int,
) -> int:
    if key not in activity:
        raise RuntimeError(f"activity omitted {key}")
    value = _strict_nonnegative_int(activity[key], key)
    if value > maximum:
        raise RuntimeError(f"{key} exceeded cap: {value} > {maximum}")
    return value


def _strict_exact_activity(
    activity: dict[str, Any],
    key: str,
    expected: int,
) -> int:
    value = _strict_activity(activity, key, expected)
    if value != expected:
        raise RuntimeError(f"{key} drifted: {value} != {expected}")
    return value


def _strict_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _assert_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase sha256")
    return value


def _verify_counterfactual(
    counterfactual: FrozenCounterfactual,
    source: Solution,
    context: EvaluationContext,
    config: PairResplitConfig,
) -> None:
    source_sha = solution_sha256(source)
    if source_sha != counterfactual.source_solution_sha256:
        raise RuntimeError("counterfactual source hash mismatch")
    if _context_sha256(context) != counterfactual.context_sha256:
        raise RuntimeError("counterfactual context hash mismatch")
    if solution_sha256(counterfactual.solution) != counterfactual.solution_sha256:
        raise RuntimeError("counterfactual solution hash drifted")
    payload = {
        "source_solution_sha256": counterfactual.source_solution_sha256,
        "context_sha256": counterfactual.context_sha256,
        "solution_sha256": counterfactual.solution_sha256,
        "source_cost": counterfactual.source_cost,
        "cost": counterfactual.cost,
        "activity": counterfactual.activity,
    }
    if _json_sha256(payload) != counterfactual.record_sha256:
        raise RuntimeError("counterfactual record hash drifted")
    _assert_counterfactual_caps(counterfactual.activity, config)
    feasible_records = [
        record
        for record in counterfactual.activity["records"]
        if record["feasible"]
    ]
    if not feasible_records:
        raise RuntimeError("counterfactual record contains no feasible pattern")
    best_record = min(
        feasible_records,
        key=lambda record: (
            float(record["complete_cost"]),
            record["solution_sha256"],
        ),
    )
    if (
        abs(float(best_record["complete_cost"]) - counterfactual.cost)
        > 1.0e-7
        or best_record["solution_sha256"]
        != counterfactual.solution_sha256
    ):
        raise RuntimeError("counterfactual best-pattern record drifted")


def _prepared_integrity_payload(
    *,
    source_sha: str,
    context_sha: str,
    counterfactual: FrozenCounterfactual,
    config: PairResplitConfig,
    candidates: list[PairResplitCandidate],
    candidate_set_sha: str,
    activity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_sha256": source_sha,
        "context_sha256": context_sha,
        "counterfactual_record_sha256": counterfactual.record_sha256,
        "config": asdict(config),
        "candidate_set_sha256": candidate_set_sha,
        "candidates": [_candidate_manifest(candidate) for candidate in candidates],
        "preparation_activity": activity,
    }


def _candidate_manifest(candidate: PairResplitCandidate) -> dict[str, Any]:
    return {
        "left_route_index": candidate.left_route_index,
        "right_route_index": candidate.right_route_index,
        "left_customers": list(candidate.left_customers),
        "right_customers": list(candidate.right_customers),
        "distance_score": float(candidate.distance_score),
        "mechanism_score": float(candidate.mechanism_score),
        "candidate_sha256": candidate.candidate_sha256,
        "left_variants": _variant_manifest(candidate.left_variants),
        "right_variants": _variant_manifest(candidate.right_variants),
    }


def _variant_manifest(
    variants: dict[str, RouteVariant],
) -> dict[str, Any]:
    return {
        vehicle_type: {
            "route": asdict(variant.route),
            "actions": [asdict(action) for action in variant.actions],
            "proxy_cost": float(variant.proxy_cost),
            "vehicle_type": variant.vehicle_type,
        }
        for vehicle_type, variant in sorted(variants.items())
    }


def _candidate_set_sha256(
    candidates: list[PairResplitCandidate],
) -> str:
    return _json_sha256(
        [_candidate_manifest(candidate) for candidate in candidates]
    )


def _context_sha256(context: EvaluationContext) -> str:
    prices = (
        asdict(context.prices)
        if isinstance(context.prices, PriceParameters)
        else context.prices
        if isinstance(context.prices, dict)
        else {
            key: value
            for key, value in vars(context.prices).items()
            if not key.startswith("_")
        }
    )
    return _json_sha256(
        {
            "instance": asdict(context.instance),
            "carbon_profile": context.carbon_profile,
            "prices": prices,
            "carbon_quota_kg": float(context.carbon_quota_kg),
            "carbon_weight": float(context.carbon_weight),
            "fairness_enabled": bool(context.fairness_enabled),
            "independent_profit": context.independent_profit,
            "fairness_theta": context.fairness_theta,
            "customer_home_depot": context.customer_home_depot,
            "allow_cross_depot": bool(context.allow_cross_depot),
            "repair_delta_mode": context.repair_delta_mode,
        }
    )


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finite_cost(value: Any, label: str) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise RuntimeError(f"{label} is non-finite")
    return out


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
