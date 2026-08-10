#!/usr/bin/env python3
"""Bounded multi-stage disclosure scout for the independent Problem-HGS.

The existing China81 H0-G2 stream hides 20% of the original orders and then
reveals them during the operating day.  This runner checks that the independent
Problem-HGS can repeatedly cut the released plan, preserve executed history,
and serve newly visible orders.  It is a technical scout, not a formal dynamic
experiment and it does not select the paper's trigger policy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import traceback
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from uuid import uuid4

from run_problem_hgs_private_technical import (
    PROTECTED,
    SEED,
    _build_context,
    _json,
    _parameters,
    _policy,
    _sha256,
    _source_provenance,
    _with_registered_idle_duties,
)
from setp_solver.algorithms.problem_hgs.contracts import SearchAccounting
from setp_solver.algorithms.problem_hgs.dynamic import (
    DutyDynamicState,
    future_individual_from_cut,
    prepare_dynamic_candidate,
)
from setp_solver.algorithms.problem_hgs.evaluation import (
    DutyFullEvaluator,
    FullEvaluation,
)
from setp_solver.algorithms.problem_hgs.initialization import (
    build_dynamic_warm_start_population,
    build_initial_population,
)
from setp_solver.algorithms.problem_hgs.integrated_private import (
    build_integrated_private_hgs,
)
from setp_solver.algorithms.problem_hgs.kernel_proposals import (
    IndependentKernelDutyRouteProposalEngine,
)
from setp_solver.algorithms.problem_hgs.model import DutyIndividual
from setp_solver.algorithms.problem_hgs.population import AdaptivePenaltyManager
from setp_solver.algorithms.problem_hgs.readiness import (
    OBSERVED_MAX_SINGLE_ORDER,
    ReadinessChargeInterval,
    advance_idle_ev_readiness,
    observed_single_order_envelope,
)
from setp_solver.check import (
    STATION_CAPACITY,
    DynamicCheckContext,
    check_solution,
)
from setp_solver.cost import (
    charging_action_electricity_cost,
    charging_action_emissions_kg,
)
from setp_solver.search.dynamic import _subinstance_for_customers
from setp_solver.search.dynamic_multitrip_schedule import (
    DynamicAssetState,
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.solution import (
    ChargingAction,
    Solution,
)

from baselines.china_e3_e7.e7_o1_replanning_20260801.policy import (
    COUNT_POLICIES,
    MASS_POLICIES,
    build_o1_batches,
    build_o1_stream,
    demand_threshold_kg,
)

_ACTIVE_OUTPUT: Path | None = None
_ACTIVE_INVOCATION_ID: str | None = None


@dataclass(frozen=True)
class _MechanicalStageResult:
    best: DutyIndividual
    best_evaluation: FullEvaluation
    iterations: int
    accounting: SearchAccounting
    termination_status: str


def _run_integrated_stage(
    candidates,
    *,
    evaluator,
    policy,
    route_engine,
    parameters,
    stop,
    full_calls_before: int,
    initialization_wall_seconds: float,
    include_mechanism_refinement: bool,
) -> _MechanicalStageResult:
    """Run the same complete-evaluation HGS used by static private search."""

    bundle = build_integrated_private_hgs(
        tuple(candidates),
        evaluator=evaluator,
        charging_policy=policy,
        route_engine=route_engine,
        penalty_parameters=parameters.penalties,
        stagnation_patience=parameters.stagnation_patience,
        include_mechanism_refinement=include_mechanism_refinement,
        stop_requested=lambda: bool(stop(float("inf"))),
    )
    integrated = bundle.algorithm.run(stop)
    best = integrated.best.evaluation
    if best.full is None:
        raise RuntimeError("integrated dynamic HGS found no complete candidate")
    accounting = bundle.accounting.mechanism
    accounting.full_evaluations = evaluator.full_calls - full_calls_before
    accounting.initialization_full_evaluations = (
        evaluator.full_calls - full_calls_before
    )
    accounting.initialization_wall_seconds = initialization_wall_seconds
    accounting.crossover_calls = integrated.accounting.iterations
    accounting.repair_calls = integrated.accounting.repaired
    accounting.restarts = integrated.accounting.restarts
    accounting.run_wall_seconds = integrated.accounting.elapsed_seconds
    return _MechanicalStageResult(
        best=best.individual,
        best_evaluation=best.full,
        iterations=integrated.accounting.iterations,
        accounting=accounting,
        termination_status="INTEGRATED_HGS_STOPPED_BY_CALLER",
    )


def _payload_sha256(payload) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dynamic_provenance(repo: Path, output: Path) -> dict:
    provenance = _source_provenance(
        repo,
        output_path=output,
        stderr_capture_state="caller_not_declared",
    )
    additional = (
        Path(__file__).resolve(),
        repo / "baselines/china_e3_e7/e7_h0_g2_foundation_20260801/stream.py",
        repo / "baselines/china_e3_e7/e7_o1_replanning_20260801/policy.py",
        repo
        / "baselines/china_e3_e7/e7_trigger_policies_20260801/trigger_policies.py",
    )
    manifest = dict(provenance["python_source_files"])
    for path in additional:
        manifest[str(path.relative_to(repo))] = _sha256(path)
    provenance["python_source_files"] = manifest
    provenance["python_source_sha256"] = _payload_sha256(manifest)
    return provenance


def _subset_bundle(bundle, customer_ids: set[str]):
    return replace(
        bundle,
        instance=_subinstance_for_customers(bundle.instance, customer_ids),
        customer_home_depot=MappingProxyType(
            {
                customer_id: depot_id
                for customer_id, depot_id in bundle.customer_home_depot.items()
                if customer_id in customer_ids
            }
        ),
    )


def _compact_attempts(attempts, *, sample_limit: int = 20) -> dict:
    """Keep diagnostic counts and a small reproducible sample, not a huge cache."""

    status_counts = Counter(item.status for item in attempts)
    error_counts = Counter(
        f"{item.error_type}: {item.error}"
        for item in attempts
        if item.error_type is not None
    )
    violation_counts = Counter(
        violation
        for item in attempts
        for violation in item.violation_types
    )
    return {
        "attempt_count": len(attempts),
        "status_counts": dict(sorted(status_counts.items())),
        "error_counts": dict(sorted(error_counts.items())),
        "violation_counts": dict(sorted(violation_counts.items())),
        "total_attempt_wall_seconds": sum(
            float(item.wall_seconds) for item in attempts
        ),
        "max_attempt_wall_seconds": max(
            (float(item.wall_seconds) for item in attempts),
            default=0.0,
        ),
        "sample": [asdict(item) for item in attempts[:sample_limit]],
        "sample_limit": int(sample_limit),
    }


def _solve_initial_visible_plan(
    active_bundle,
    base_context,
    *,
    runtime_seconds: float,
    total_deadline: float,
    stagnation_patience: int,
) -> tuple[DutyIndividual, object, object, dict]:
    """Solve only the initially visible orders, without a full-information route."""

    customer_ids = {
        node.node_id
        for node in active_bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    empty_registered = _with_registered_idle_duties(
        DutyIndividual(
            duties=(),
            unserved_customers=tuple(sorted(customer_ids)),
            source="dynamic-disclosure-initial-visible-orders-only",
        ),
        active_bundle,
    )
    context = replace(
        base_context,
        bundle=active_bundle,
        fairness_enabled=False,
        incremental_full_truth_sentinel_enabled=False,
    )
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator)
    parameters = _parameters(
        stagnation_patience=stagnation_patience,
        population_mode="copied_hgs_defaults",
    )
    route_engine = IndependentKernelDutyRouteProposalEngine(
        context,
        empty_registered,
        random_seed=SEED,
        stream_role="dynamic_initial_visible_route",
    )
    stage_started = perf_counter()
    stage_deadline = min(
        stage_started + float(runtime_seconds),
        float(total_deadline),
    )
    full_calls_before = evaluator.full_calls
    built = build_initial_population(
        empty_registered,
        evaluator=evaluator,
        charging_policy=policy,
        route_engine=route_engine,
        requested_size=2,
        random_seed=SEED,
        max_random_attempts=None,
        require_complete_feasible=True,
        stop_requested=lambda: perf_counter() >= stage_deadline,
    )
    if not any(not candidate.unserved_customers for candidate in built.candidates):
        raise RuntimeError("initial visible-order population has no complete seed")
    result = _run_integrated_stage(
        built.candidates,
        evaluator=evaluator,
        policy=policy,
        route_engine=route_engine,
        parameters=parameters,
        stop=lambda _best: perf_counter() >= stage_deadline,
        full_calls_before=full_calls_before,
        initialization_wall_seconds=built.wall_seconds,
        include_mechanism_refinement=True,
    )
    if not result.best_evaluation.feasible:
        raise RuntimeError(
            "initial visible-order plan is infeasible: "
            + ", ".join(v.type for v in result.best_evaluation.violations)
        )
    served = _completed_customer_ids(
        result.best_evaluation.prepared_solution,
        active_bundle,
    )
    if len(served) != len(set(served)) or set(served) != customer_ids:
        raise RuntimeError("initial visible-order customer service is incomplete")
    diagnostic = {
        "visible_customer_ids": sorted(customer_ids),
        "hidden_customer_ids_used": [],
        "requested_size": built.requested_size,
        "actual_size": built.actual_size,
        "attempts_exhausted": built.attempts_exhausted,
        "population_wall_seconds": built.wall_seconds,
        "search_iterations": result.iterations,
        "search_termination_status": result.termination_status,
        "total_wall_seconds": perf_counter() - stage_started,
        "attempts": _compact_attempts(built.attempts),
    }
    return result.best, result.best_evaluation, context, diagnostic


def _load_initial_visible_plan(
    source_path: Path,
    active_bundle,
    base_context,
    *,
    instance_id: str,
    stream_seed: int,
) -> tuple[DutyIndividual, object, object, dict]:
    """Load a previously saved partial-information plan and verify its scope."""

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    customer_ids = _active_customer_ids(active_bundle)
    if payload.get("instance_id") != instance_id:
        raise ValueError("initial visible plan belongs to another instance")
    if int(payload.get("stream_seed")) != int(stream_seed):
        raise ValueError("initial visible plan belongs to another event stream")
    if payload.get("visible_customer_ids") != sorted(customer_ids):
        raise ValueError("initial visible plan has another information set")
    if payload.get("hidden_customer_ids_used") != []:
        raise ValueError("initial visible plan reports hidden-customer use")
    solution = solution_from_dict(payload["prepared_solution"])
    individual = _with_registered_idle_duties(
        DutyIndividual.from_solution(
            solution,
            customer_node_ids=customer_ids,
            source="dynamic-disclosure-frozen-initial-visible-plan",
        ),
        active_bundle,
    )
    context = replace(
        base_context,
        bundle=active_bundle,
        fairness_enabled=False,
        incremental_full_truth_sentinel_enabled=False,
    )
    evaluator = DutyFullEvaluator(context)
    evaluation = evaluator.evaluate(individual)
    if not evaluation.feasible:
        raise RuntimeError("frozen initial visible plan is infeasible")
    served = _completed_customer_ids(
        evaluation.prepared_solution,
        active_bundle,
    )
    if len(served) != len(set(served)) or set(served) != customer_ids:
        raise RuntimeError("frozen initial visible plan service is incomplete")
    diagnostic = {
        "visible_customer_ids": sorted(customer_ids),
        "hidden_customer_ids_used": [],
        "source": "frozen_partial_information_plan",
        "source_path": str(source_path),
        "source_sha256": _sha256(source_path),
        "cold_recheck_feasible": True,
    }
    return individual, evaluation, context, diagnostic


def _full_asset_registry(initial: DutyIndividual, cut, bundle):
    assets = dict(cut.asset_states)
    synthesized = []
    for duty in initial.duties:
        if duty.physical_vehicle_id in assets:
            continue
        assets[duty.physical_vehicle_id] = DynamicAssetState(
            physical_vehicle_id=duty.physical_vehicle_id,
            vehicle_type=duty.vehicle_type,
            home_depot_id=duty.home_depot_id,
            available_second=float(cut.trigger_second),
            remaining_battery_kwh=(
                float(bundle.prices.initial_ev_battery_kwh)
                if duty.vehicle_type == "ev"
                else 0.0
            ),
            next_trip_index=1,
        )
        synthesized.append(duty.physical_vehicle_id)
    return MappingProxyType(assets), tuple(sorted(synthesized))


def _overlay_readiness_states(cut, advanced_states, idle_asset_ids):
    """Merge elapsed standby charging into assets unused by the prior plan."""

    assets = dict(cut.asset_states)
    for asset_id in sorted(idle_asset_ids):
        if asset_id not in assets:
            raise ValueError("readiness asset disappeared from the certified cut")
        cut_state = assets[asset_id]
        advanced = advanced_states[asset_id]
        if (
            cut_state.vehicle_type != advanced.vehicle_type
            or cut_state.home_depot_id != advanced.home_depot_id
            or cut_state.next_trip_index != advanced.next_trip_index
        ):
            raise ValueError("readiness charging changed a physical asset identity")
        assets[asset_id] = replace(
            cut_state,
            available_second=max(
                float(cut_state.available_second),
                float(advanced.available_second),
            ),
            remaining_battery_kwh=float(advanced.remaining_battery_kwh),
        )
    frozen = MappingProxyType(assets)
    return replace(cut, asset_states=frozen), frozen


def _readiness_costs(intervals, bundle) -> dict[str, float]:
    actions = [interval.as_reserved_action() for interval in intervals]
    electricity = sum(
        charging_action_electricity_cost(
            action,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        for action in actions
    )
    emissions = sum(
        charging_action_emissions_kg(
            action,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        for action in actions
    )
    carbon = emissions * float(bundle.prices.carbon_price)
    return {
        "electricity_kwh": sum(float(action.energy_kwh) for action in actions),
        "cost_electricity": electricity,
        "emissions_kg": emissions,
        "cost_carbon": carbon,
        "cost_total": electricity + carbon,
    }


def _select_routes(solution: Solution, route_ids: set[str]) -> Solution:
    routes = [route for route in solution.routes if route.vehicle_id in route_ids]
    selected_ids = {route.vehicle_id for route in routes}
    actions = [
        action
        for action in solution.charging_actions
        if action.vehicle_id in selected_ids
    ]
    return Solution(routes=routes, charging_actions=actions)


def _advance_prior_history(state: DutyDynamicState) -> Solution:
    """Move the preceding stage's already committed rows into durable history."""

    prior = state.prior_committed_solution or Solution()
    current_ids = {
        *state.cut.completed_route_ids,
        *state.cut.in_progress_route_ids,
    }
    current = _select_routes(state.source_solution, current_ids)
    routes = {route.vehicle_id: route for route in prior.routes}
    for route in current.routes:
        previous = routes.get(route.vehicle_id)
        if previous is not None and previous != route:
            raise ValueError("committed route history changed between triggers")
        routes[route.vehicle_id] = route

    actions: dict[tuple[object, ...], ChargingAction] = {}
    for action in (*prior.charging_actions, *state.cut.locked_charging_actions):
        if action.vehicle_id not in routes:
            continue
        key = (
            action.vehicle_id,
            action.station_id,
            float(action.charge_start_second),
            float(action.energy_kwh),
        )
        previous = actions.get(key)
        if previous is not None and previous != action:
            raise ValueError("committed charging history changed between triggers")
        actions[key] = action
    return Solution(
        routes=[routes[key] for key in sorted(routes)],
        charging_actions=[actions[key] for key in sorted(actions, key=str)],
    )


def _committed_payload(state: DutyDynamicState, full_solution: Solution) -> dict:
    route_ids = {
        route.vehicle_id
        for route in (state.prior_committed_solution or Solution()).routes
    }
    route_ids.update(state.cut.completed_route_ids)
    route_ids.update(state.cut.in_progress_route_ids)
    locked = {
        (
            action.vehicle_id,
            action.station_id,
            float(action.charge_start_second),
            float(action.energy_kwh),
        )
        for action in (
            *(state.prior_committed_solution or Solution()).charging_actions,
            *state.cut.locked_charging_actions,
        )
    }
    return {
        "routes": sorted(
            (
                asdict(route)
                for route in full_solution.routes
                if route.vehicle_id in route_ids
            ),
            key=lambda row: row["vehicle_id"],
        ),
        "charging_actions": sorted(
            (
                asdict(action)
                for action in full_solution.charging_actions
                if (
                    action.vehicle_id,
                    action.station_id,
                    float(action.charge_start_second),
                    float(action.energy_kwh),
                )
                in locked
            ),
            key=lambda row: (
                row["vehicle_id"],
                row["station_id"],
                float(row["charge_start_second"]),
            ),
        ),
    }


def _active_customer_ids(bundle) -> set[str]:
    return {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }


def _completed_customer_ids(solution: Solution, bundle) -> list[str]:
    customers = _active_customer_ids(bundle)
    return [
        node_id
        for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in customers
    ]


def _write_failure(output: Path, invocation_id: str, error: Exception) -> None:
    metadata_path = output / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("invocation_id") != invocation_id:
            return
    else:
        metadata = {
            "status": "RUNNING",
            "invocation_id": invocation_id,
            "purpose": "multi-stage dynamic disclosure technical scout",
            "failure_before_provenance_completed": True,
        }
    metadata["status"] = "FAILED"
    _json(metadata_path, metadata)
    failure_csv = output / "failure.csv"
    with failure_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("verdict", "error_type", "error"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(
            {
                "verdict": "TECHNICAL_SCOUT_FAILED",
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
    raw_path = output / "raw_runs.csv"
    if not raw_path.exists():
        raw_path.write_bytes(failure_csv.read_bytes())
    _json(
        output / "decision.json",
        {
            "verdict": "TECHNICAL_SCOUT_FAILED",
            "failure_reasons": [f"{type(error).__name__}: {error}"],
            "traceback": traceback.format_exc(),
            "user_decision_changed": False,
        },
    )
    (output / "report.md").write_text(
        "# 动态订单连续技术试跑\n\n"
        f"本次试跑失败，错误为：{type(error).__name__}: {error}。"
        "完整调用栈保存在 decision.json，失败没有改写成完成。\n\n"
        "## 交付前九条自检\n\n"
        "1. 每个事实是否有出处？——错误和调用栈来自本次运行并保存在 decision.json。\n"
        "2. 有没有把建议或担忧写成已决？——没有。\n"
        "3. 是否超出任务范围？——没有，只做连续动态接线试跑。\n"
        "4. 是否碰受保护文件？——没有。\n"
        "5. 是否擅自替用户拍板？——没有。\n"
        "6. 是否使用自造术语？——没有。\n"
        "7. 失败是否如实保留？——是，原样保留。\n"
        "8. 四件套是否齐全？——齐全。\n"
        "9. 交接是否同步？——在算法施工收口时统一同步。\n",
        encoding="utf-8",
    )
    _write_hashes(output)


def _write_rows_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_hashes(output: Path) -> None:
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    _json(
        output / "artifact_hashes.json",
        {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        },
    )


def main() -> int:
    global _ACTIVE_INVOCATION_ID, _ACTIVE_OUTPUT

    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--instance-id",
        default="cn-prd-50c-01-V2-LOCATIONS",
    )
    parser.add_argument("--stream-seed", type=int, default=1)
    parser.add_argument("--search-seed", type=int, default=SEED)
    parser.add_argument(
        "--trigger-policy",
        choices=tuple(dict.fromkeys((*MASS_POLICIES, *COUNT_POLICIES))),
        default="fixed_30_minutes",
    )
    parser.add_argument("--stage-runtime-seconds", type=float, default=30.0)
    parser.add_argument("--total-runtime-seconds", type=float, default=600.0)
    parser.add_argument(
        "--stage-stop-mode",
        choices=("wall_clock", "stagnation"),
        default="wall_clock",
        help=(
            "wall_clock uses the technical per-stage seconds; stagnation lets "
            "the existing no-improvement counter stop each stage while the "
            "total runtime remains the hard ceiling"
        ),
    )
    parser.add_argument("--stagnation-patience", type=int, default=500)
    parser.add_argument("--source-initial-visible-solution", type=Path)
    parser.add_argument(
        "--route-only-dynamic-ablation",
        action="store_true",
        help="technical ablation: omit the exact future-Duty neighbourhood",
    )
    parser.add_argument(
        "--mechanical-insertion-control",
        action="store_true",
        help=(
            "technical control: insert each newly visible batch by exact "
            "regret-2 only, without population search"
        ),
    )
    parser.add_argument(
        "--idle-ev-readiness-mode",
        choices=("none", OBSERVED_MAX_SINGLE_ORDER),
        default="none",
        help=(
            "technical trial only: charge an otherwise idle EV toward the "
            "largest one-order energy envelope observed at its depot"
        ),
    )
    args = parser.parse_args()
    if not 0.0 < args.stage_runtime_seconds <= 1200.0:
        raise ValueError("stage runtime must be in (0, 1200] seconds")
    if not 0.0 < args.total_runtime_seconds <= 1200.0:
        raise ValueError("total runtime must be in (0, 1200] seconds")
    if args.stagnation_patience < 1:
        raise ValueError("stagnation patience must be positive")
    if args.route_only_dynamic_ablation and args.mechanical_insertion_control:
        raise ValueError(
            "route-only ablation and mechanical insertion control are exclusive"
        )

    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    invocation_id = uuid4().hex
    _ACTIVE_OUTPUT = output
    _ACTIVE_INVOCATION_ID = invocation_id
    provenance = _dynamic_provenance(repo, output)
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "invocation_id": invocation_id,
            "purpose": "multi-stage dynamic disclosure technical scout",
            "instance_id": args.instance_id,
            "stream_seed": args.stream_seed,
            "search_seed": args.search_seed,
            "trigger_policy": args.trigger_policy,
            "trigger_policy_formally_selected": False,
            "stage_runtime_seconds": args.stage_runtime_seconds,
            "stage_stop_mode": args.stage_stop_mode,
            "total_runtime_seconds": args.total_runtime_seconds,
            "stagnation_patience": args.stagnation_patience,
            "population_construction": (
                "current-plan-exact-regret2-insertion-then-total-wall-clock-"
                "bounded-copied-hgs-random-skeleton-until-one-feasible"
            ),
            "exact_dynamic_suffix_neighbourhood_enabled": (
                not args.route_only_dynamic_ablation
                and not args.mechanical_insertion_control
            ),
            "mechanical_insertion_control": args.mechanical_insertion_control,
            "idle_ev_readiness_mode": args.idle_ev_readiness_mode,
            "idle_ev_readiness_formally_selected": False,
            "code_provenance": provenance,
        },
    )

    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    full_bundle, _registered, _pi0, base_context = _build_context(
        repo,
        args.instance_id,
    )
    stream = build_o1_stream(
        full_bundle.instance,
        instance_id=args.instance_id,
        stream_seed=args.stream_seed,
    )
    threshold = (
        demand_threshold_kg(full_bundle.instance)
        if args.trigger_policy == "hybrid_two_mean_orders_or_30_minutes"
        else None
    )
    batches = build_o1_batches(
        stream.events,
        args.trigger_policy,
        threshold_kg=threshold,
    )
    _write_rows_csv(
        output / "event_stream.csv",
        [asdict(event) for event in stream.events],
    )
    active = set(stream.initial_customer_ids)
    active_bundle = _subset_bundle(full_bundle, active)
    total_started = perf_counter()
    source_initial_path = None
    if args.source_initial_visible_solution is None:
        registered_initial, static_evaluation, _, initial_diagnostic = (
            _solve_initial_visible_plan(
                active_bundle,
                base_context,
                runtime_seconds=args.stage_runtime_seconds,
                total_deadline=total_started + args.total_runtime_seconds,
                stagnation_patience=args.stagnation_patience,
            )
        )
    else:
        source_initial_path = (
            args.source_initial_visible_solution
            if args.source_initial_visible_solution.is_absolute()
            else repo / args.source_initial_visible_solution
        ).resolve()
        registered_initial, static_evaluation, _, initial_diagnostic = (
            _load_initial_visible_plan(
                source_initial_path,
                active_bundle,
                base_context,
                instance_id=args.instance_id,
                stream_seed=args.stream_seed,
            )
        )
    _json(output / "initial_visible_plan_diagnostic.json", initial_diagnostic)
    _json(
        output / "initial_visible_solution.json",
        {
            "instance_id": args.instance_id,
            "stream_seed": args.stream_seed,
            "visible_customer_ids": sorted(active),
            "hidden_customer_ids_used": [],
            "individual_fingerprint": registered_initial.fingerprint,
            "total_cost": static_evaluation.total_cost,
            "breakdown": dict(static_evaluation.breakdown),
            "prepared_solution": asdict(static_evaluation.prepared_solution),
        },
    )
    current_solution = static_evaluation.prepared_solution
    current_certificate = static_evaluation.certificate
    current_state: DutyDynamicState | None = None
    current_future = None
    appearances = {customer_id: 0.0 for customer_id in active}
    stage_rows: list[dict] = []
    synthesized_idle: tuple[str, ...] = ()
    final_result = None
    final_context = None
    pending_readiness_idle_assets: tuple[str, ...] = ()
    pending_readiness_targets: Mapping[str, float] = MappingProxyType({})
    readiness_intervals: list[ReadinessChargeInterval] = []
    readiness_envelope_limitations: list[dict[str, object]] = []

    for stage_index, batch in enumerate(batches, start=1):
        if perf_counter() - total_started >= args.total_runtime_seconds:
            raise TimeoutError("dynamic disclosure scout reached its total runtime ceiling")
        trigger = float(batch.trigger_second)
        for event_id, customer_id in zip(batch.event_ids, batch.customer_ids):
            event = next(item for item in stream.events if item.event_id == event_id)
            active.add(customer_id)
            appearances[customer_id] = float(event.appearance_second)
        new_bundle = _subset_bundle(full_bundle, active)
        stage_readiness_intervals: tuple[ReadinessChargeInterval, ...] = ()

        if current_state is None:
            cut = cut_certificate_at_trigger(
                current_solution,
                current_certificate,
                active_bundle.instance,
                active_bundle.prices,
                trigger_second=trigger,
            )
            assets, synthesized_idle = _full_asset_registry(
                registered_initial,
                cut,
                active_bundle,
            )
            prior = Solution()
            source_solution = current_solution
            source_certificate = current_certificate
            certified_dynamic_history = frozenset()
        else:
            assert current_future is not None
            cut = cut_dynamic_certificate_at_trigger(
                current_future.future_solution,
                current_future.future_certificate,
                active_bundle.instance,
                active_bundle.prices,
                inherited_asset_states=current_state.asset_states,
                previous_stage_start_second=current_state.cut.trigger_second,
                trigger_second=trigger,
                inherited_locked_charging_actions=(
                    current_state.cut.locked_charging_actions
                ),
            )
            assets = MappingProxyType(dict(cut.asset_states))
            prior = _advance_prior_history(current_state)
            source_solution = current_future.future_solution
            source_certificate = current_future.future_certificate
            certified_dynamic_history = frozenset(
                {
                    *current_state.certified_dynamic_route_ids,
                    *cut.completed_route_ids,
                    *cut.in_progress_route_ids,
                }
            )

            if args.idle_ev_readiness_mode == OBSERVED_MAX_SINGLE_ORDER:
                advanced, stage_readiness_intervals = advance_idle_ev_readiness(
                    current_state.asset_states,
                    idle_asset_ids=pending_readiness_idle_assets,
                    target_by_depot_kwh=pending_readiness_targets,
                    interval_start_second=current_state.cut.trigger_second,
                    interval_end_second=trigger,
                    instance=active_bundle.instance,
                    prices=active_bundle.prices,
                )
                cut, assets = _overlay_readiness_states(
                    cut,
                    advanced,
                    pending_readiness_idle_assets,
                )
                readiness_intervals.extend(stage_readiness_intervals)

        current_committed_ids = {
            *cut.completed_route_ids,
            *cut.in_progress_route_ids,
        }
        committed_customers = {
            node_id
            for route in (
                *prior.routes,
                *(
                    route
                    for route in source_solution.routes
                    if route.vehicle_id in current_committed_ids
                ),
            )
            for node_id in route.node_sequence[1:-1]
            if node_id in active
        }
        state = DutyDynamicState(
            source_solution=source_solution,
            cut=cut,
            asset_states=assets,
            future_customer_ids=frozenset(active.difference(committed_customers)),
            customer_appearance_second={
                customer_id: appearances[customer_id]
                for customer_id in sorted(active)
            },
            charging_strategy="aware",
            charging_intensity_field="forecast_gco2_per_kwh",
            prior_committed_solution=prior,
            certified_dynamic_route_ids=certified_dynamic_history,
        )
        initial_future = future_individual_from_cut(
            state,
            source_certificate,
            new_bundle.instance,
        )
        context = replace(
            base_context,
            bundle=new_bundle,
            fairness_enabled=False,
            incremental_full_truth_sentinel_enabled=False,
            dynamic_state=state,
        )
        evaluator = DutyFullEvaluator(context)
        policy = _policy(evaluator)
        parameters = _parameters(
            stagnation_patience=args.stagnation_patience,
            population_mode="copied_hgs_defaults",
        )
        parameters = replace(parameters, random_seed=args.search_seed)
        route_engine = IndependentKernelDutyRouteProposalEngine(
            context,
            initial_future,
            random_seed=args.search_seed,
            stream_role=f"dynamic_stage_{stage_index}_route",
        )
        stage_started = perf_counter()
        stage_deadline = min(
            stage_started + args.stage_runtime_seconds,
            total_started + args.total_runtime_seconds,
        )
        if args.stage_stop_mode == "stagnation":
            initialization_stop_requested = lambda: (
                perf_counter() - total_started >= args.total_runtime_seconds
            )
        else:
            initialization_stop_requested = lambda deadline=stage_deadline: (
                perf_counter() >= deadline
            )
        full_calls_before = evaluator.full_calls
        warm_penalties = AdaptivePenaltyManager(parameters.penalties)
        built = build_dynamic_warm_start_population(
            initial_future,
            evaluator=evaluator,
            charging_policy=policy,
            penalized_cost=warm_penalties.cost,
            requested_size=(
                2
                if args.mechanical_insertion_control
                else parameters.population.min_pop_size
            ),
            stop_requested=initialization_stop_requested,
        )
        initialization_mode = "current-plan-exact-regret2-insertion"
        built_has_complete_feasible = any(
            evaluation.feasible and not candidate.unserved_customers
            for candidate, evaluation in zip(
                built.candidates,
                built.evaluations,
                strict=True,
            )
        )
        if (
            not args.mechanical_insertion_control
            and (
                built.actual_size < parameters.population.min_pop_size
                or not built_has_complete_feasible
            )
            and not initialization_stop_requested()
        ):
            random_built = build_initial_population(
                initial_future,
                evaluator=evaluator,
                charging_policy=policy,
                route_engine=route_engine,
                requested_size=parameters.population.generation_size,
                random_seed=args.search_seed,
                max_random_attempts=None,
                require_complete_feasible=True,
                stop_requested=initialization_stop_requested,
            )
            combined_candidates = list(built.candidates)
            combined_evaluations = list(built.evaluations)
            for candidate, evaluation in zip(
                random_built.candidates,
                random_built.evaluations,
                strict=True,
            ):
                if len(combined_candidates) < parameters.population.min_pop_size:
                    combined_candidates.append(candidate)
                    combined_evaluations.append(evaluation)
                    if evaluation.feasible and not candidate.unserved_customers:
                        built_has_complete_feasible = True
                elif (
                    not built_has_complete_feasible
                    and evaluation.feasible
                    and not candidate.unserved_customers
                ):
                    combined_candidates[-1] = candidate
                    combined_evaluations[-1] = evaluation
                    built_has_complete_feasible = True
                if (
                    len(combined_candidates) >= parameters.population.min_pop_size
                    and built_has_complete_feasible
                ):
                    break
            combined_has_complete_feasible = any(
                evaluation.feasible and not candidate.unserved_customers
                for candidate, evaluation in zip(
                    combined_candidates,
                    combined_evaluations,
                    strict=True,
                )
            )
            built = replace(
                built,
                candidates=tuple(combined_candidates),
                evaluations=tuple(combined_evaluations),
                attempts=(*built.attempts, *random_built.attempts),
                actual_size=len(combined_candidates),
                attempts_exhausted=(
                    (
                        len(combined_candidates)
                        < parameters.population.min_pop_size
                        or not combined_has_complete_feasible
                    )
                    and not initialization_stop_requested()
                ),
                full_evaluation_count=(
                    built.full_evaluation_count
                    + random_built.full_evaluation_count
                ),
                wall_seconds=built.wall_seconds + random_built.wall_seconds,
            )
            initialization_mode = (
                "current-plan-exact-regret2-insertion-then-random-skeleton-fill"
            )
        population_diagnostic = {
            "stage": stage_index,
            "trigger_second": trigger,
            "active_customers": len(active),
            "future_customers": len(state.future_customer_ids),
            "requested_size": built.requested_size,
            "actual_size": built.actual_size,
            "initialization_mode": initialization_mode,
            "attempts_exhausted": built.attempts_exhausted,
            "complete_feasible_candidates": sum(
                evaluation.feasible and not candidate.unserved_customers
                for candidate, evaluation in zip(
                    built.candidates,
                    built.evaluations,
                    strict=True,
                )
            ),
            "wall_seconds": built.wall_seconds,
            "attempts": _compact_attempts(built.attempts),
            "asset_states": {
                asset_id: asdict(asset)
                for asset_id, asset in sorted(state.asset_states.items())
            },
            "unserved_customers": list(initial_future.unserved_customers),
            "readiness_progress": [
                asdict(interval) for interval in stage_readiness_intervals
            ],
        }
        _json(
            output / f"stage_{stage_index:02d}_population_diagnostic.json",
            population_diagnostic,
        )
        if args.mechanical_insertion_control:
            feasible_pairs = [
                (candidate, evaluation)
                for candidate, evaluation in zip(
                    built.candidates,
                    built.evaluations,
                    strict=True,
                )
                if evaluation.feasible and not candidate.unserved_customers
            ]
            if not feasible_pairs:
                raise RuntimeError(
                    f"stage {stage_index} mechanical insertion found no "
                    "complete feasible candidate"
                )
            best_candidate, best_evaluation = min(
                feasible_pairs,
                key=lambda item: item[1].total_cost,
            )
            accounting = SearchAccounting(
                full_evaluations=(evaluator.full_calls - full_calls_before),
                initialization_full_evaluations=(
                    evaluator.full_calls - full_calls_before
                ),
                initialization_wall_seconds=built.wall_seconds,
            )
            result = _MechanicalStageResult(
                best=best_candidate,
                best_evaluation=best_evaluation,
                iterations=0,
                accounting=accounting,
                termination_status="MECHANICAL_REGRET2_INSERTION",
            )
            proposal_payload = {
                "source_id": "mechanical-regret2-insertion-control",
                "identity_sha256": None,
                "providers": [],
            }
        else:
            if not any(
                evaluation.feasible and not candidate.unserved_customers
                for candidate, evaluation in zip(
                    built.candidates,
                    built.evaluations,
                    strict=True,
                )
            ):
                raise RuntimeError(
                    f"stage {stage_index} population construction found no "
                    "complete feasible candidate"
                )
            if args.stage_stop_mode == "stagnation":
                stop = lambda _best: (
                    perf_counter() - total_started
                    >= args.total_runtime_seconds
                )
            else:
                stop = (
                    lambda _best, deadline=stage_deadline: (
                        perf_counter() >= deadline
                    )
                )
            result = _run_integrated_stage(
                built.candidates,
                evaluator=evaluator,
                policy=policy,
                route_engine=route_engine,
                parameters=parameters,
                stop=stop,
                full_calls_before=full_calls_before,
                initialization_wall_seconds=built.wall_seconds,
                include_mechanism_refinement=(
                    not args.route_only_dynamic_ablation
                ),
            )
            proposal_payload = {
                "source_id": "integrated-private-hgs-dynamic",
                "identity_sha256": route_engine.identity_sha256,
                "providers": [
                    {
                        "source_id": route_engine.source_id,
                        "identity_sha256": route_engine.identity_sha256,
                    }
                ],
            }
        population_diagnostic["search_accounting"] = result.accounting.to_dict()
        population_diagnostic["proposal_engine"] = proposal_payload
        _json(
            output / f"stage_{stage_index:02d}_population_diagnostic.json",
            population_diagnostic,
        )
        if not result.best_evaluation.feasible:
            raise RuntimeError(
                f"stage {stage_index} has no feasible full execution: "
                + ", ".join(v.type for v in result.best_evaluation.violations)
            )
        history_before = _payload_sha256(
            _committed_payload(state, result.best_evaluation.prepared_solution)
        )
        # Reprepare independently so the continuation passed to the next cut
        # is the exact future certificate, not the merged full-day solution.
        prepared_future = prepare_dynamic_candidate(result.best, state, new_bundle)
        history_after = _payload_sha256(
            _committed_payload(state, prepared_future.full_execution_solution)
        )
        if history_before != history_after:
            raise RuntimeError(f"stage {stage_index} changed committed history")
        completed = _completed_customer_ids(
            result.best_evaluation.prepared_solution,
            new_bundle,
        )
        if len(completed) != len(set(completed)) or set(completed) != active:
            raise RuntimeError(f"stage {stage_index} customer service is incomplete")
        stage_rows.append(
            {
                "stage": stage_index,
                "trigger_second": trigger,
                "trigger_cause": batch.cause,
                "revealed_in_batch": len(batch.customer_ids),
                "active_customers": len(active),
                "committed_customers": len(committed_customers),
                "future_customers": len(state.future_customer_ids),
                "iterations": result.iterations,
                "runtime_seconds": perf_counter() - stage_started,
                "population_size": built.actual_size,
                "initial_feasible_candidates": sum(
                    evaluation.feasible for evaluation in built.evaluations
                ),
                "best_cost": result.best_evaluation.total_cost,
                "best_emissions_kg": result.best_evaluation.breakdown.get("E_total"),
                "history_preserved": True,
                "completed_customers": len(set(completed)),
                "total_active_customers": len(active),
                "termination_status": result.termination_status,
                "readiness_charging_kwh_cumulative": sum(
                    interval.energy_kwh for interval in readiness_intervals
                ),
            }
        )
        _write_rows_csv(output / "raw_runs.csv", stage_rows)
        if args.idle_ev_readiness_mode == OBSERVED_MAX_SINGLE_ORDER:
            pending_readiness_idle_assets = tuple(
                sorted(
                    duty.physical_vehicle_id
                    for duty in result.best.duties
                    if duty.vehicle_type == "ev" and not duty.trips
                )
            )
            envelope = observed_single_order_envelope(
                new_bundle,
                active,
            )
            pending_readiness_targets = envelope.target_by_depot_kwh
            if envelope.over_capacity_customer_ids_by_depot:
                readiness_envelope_limitations.append(
                    {
                        "stage": stage_index,
                        "scope": "customer_home_depot_only",
                        "over_capacity_customer_ids_by_depot": dict(
                            envelope.over_capacity_customer_ids_by_depot
                        ),
                    }
                )
        else:
            pending_readiness_idle_assets = ()
            pending_readiness_targets = MappingProxyType({})
        current_state = state
        current_future = prepared_future
        current_solution = prepared_future.future_solution
        current_certificate = prepared_future.future_certificate
        active_bundle = new_bundle
        final_result = result
        final_context = context

    if final_result is None or final_context is None or current_state is None:
        raise RuntimeError("dynamic stream produced no trigger stages")
    if active != _active_customer_ids(full_bundle):
        raise RuntimeError("dynamic stream did not reveal the full customer set")
    fairness_evaluator = DutyFullEvaluator(
        replace(final_context, fairness_enabled=True)
    )
    final_fairness_evaluation = fairness_evaluator.evaluate(final_result.best)
    readiness_reserved_actions = tuple(
        interval.as_reserved_action() for interval in readiness_intervals
    )
    capacity_violations = tuple(
        violation
        for violation in check_solution(
            final_result.best_evaluation.prepared_solution,
            full_bundle.instance,
            full_bundle.prices,
            dynamic_context=DynamicCheckContext(
                reserved_charging_actions=readiness_reserved_actions,
            ),
        )
        if violation.type == STATION_CAPACITY
    )
    if capacity_violations:
        raise RuntimeError(
            "readiness charging violates station capacity: "
            + "; ".join(violation.detail for violation in capacity_violations)
        )
    readiness_costs = _readiness_costs(readiness_intervals, full_bundle)
    adjusted_total_cost = (
        float(final_result.best_evaluation.total_cost)
        + float(readiness_costs["cost_total"])
    )
    adjusted_total_emissions = (
        float(final_result.best_evaluation.breakdown.get("E_total", 0.0))
        + float(readiness_costs["emissions_kg"])
    )
    adjusted_breakdown = dict(final_result.best_evaluation.breakdown)
    adjusted_breakdown["total_cost"] = adjusted_total_cost
    adjusted_breakdown["cost_elec"] = (
        float(adjusted_breakdown.get("cost_elec", 0.0))
        + float(readiness_costs["cost_electricity"])
    )
    adjusted_breakdown["cost_carbon"] = (
        float(adjusted_breakdown.get("cost_carbon", 0.0))
        + float(readiness_costs["cost_carbon"])
    )
    adjusted_breakdown["E_total"] = adjusted_total_emissions
    adjusted_breakdown["E_ev_indirect"] = (
        float(adjusted_breakdown.get("E_ev_indirect", 0.0))
        + float(readiness_costs["emissions_kg"])
    )
    adjusted_breakdown["electricity_kwh"] = (
        float(adjusted_breakdown.get("electricity_kwh", 0.0))
        + float(readiness_costs["electricity_kwh"])
    )
    adjusted_breakdown["depot_charging_kwh"] = (
        float(adjusted_breakdown.get("depot_charging_kwh", 0.0))
        + float(readiness_costs["electricity_kwh"])
    )
    adjusted_breakdown["readiness_charging_kwh"] = float(
        readiness_costs["electricity_kwh"]
    )
    adjusted_breakdown["readiness_cost_total"] = float(
        readiness_costs["cost_total"]
    )
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    if protected_before != protected_after:
        raise RuntimeError("a protected evaluator file changed")

    total_demand = sum(
        float(node.demand)
        for node in full_bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    completed_ids = _completed_customer_ids(
        final_result.best_evaluation.prepared_solution,
        full_bundle,
    )
    demand_by_customer = {
        node.node_id: float(node.demand)
        for node in full_bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    completed_demand = sum(demand_by_customer[item] for item in set(completed_ids))
    verdict = "TECHNICAL_SCOUT_COMPLETE"
    metadata = {
        "status": "COMPLETE",
        "invocation_id": invocation_id,
        "purpose": "multi-stage dynamic disclosure technical scout",
        "code_provenance": provenance,
        "instance_id": args.instance_id,
        "instance_formally_selected": False,
        "stream_seed": args.stream_seed,
        "search_seed": args.search_seed,
        "dynamic_order_share": len(stream.events) / len(_active_customer_ids(full_bundle)),
        "initial_customer_count": len(stream.initial_customer_ids),
        "dynamic_event_count": len(stream.events),
        "trigger_policy": args.trigger_policy,
        "trigger_policy_formally_selected": False,
        "trigger_count": len(batches),
        "stage_runtime_seconds": args.stage_runtime_seconds,
        "stage_stop_mode": args.stage_stop_mode,
        "total_runtime_seconds": args.total_runtime_seconds,
        "actual_total_wall_seconds": perf_counter() - total_started,
        "stagnation_patience": args.stagnation_patience,
        "initial_plan_information_scope": "initial_visible_customers_only",
        "initial_plan_hidden_customer_ids_used": [],
        "initial_plan_source_mode": (
            "generated_from_visible_orders"
            if source_initial_path is None
            else "frozen_partial_information_plan"
        ),
        "source_initial_visible_solution_path": (
            None if source_initial_path is None else str(source_initial_path)
        ),
        "source_initial_visible_solution_sha256": (
            None if source_initial_path is None else _sha256(source_initial_path)
        ),
        "initial_plan_diagnostic_sha256": _sha256(
            output / "initial_visible_plan_diagnostic.json"
        ),
        "initial_visible_solution_sha256": _sha256(
            output / "initial_visible_solution.json"
        ),
        "intermediate_fairness_enabled": False,
        "intermediate_fairness_reason": (
            "partial-information stages do not compare 40-to-49 revealed orders "
            "against the frozen full-day 50-order independent-profit baseline"
        ),
        "final_information_stage_fairness_enabled": False,
        "dynamic_fairness_search_semantics_selected": False,
        "exact_dynamic_suffix_neighbourhood_enabled": (
            not args.route_only_dynamic_ablation
            and not args.mechanical_insertion_control
        ),
        "mechanical_insertion_control": args.mechanical_insertion_control,
        "idle_ev_readiness_mode": args.idle_ev_readiness_mode,
        "idle_ev_readiness_formally_selected": False,
        "idle_ev_readiness_information_scope": (
            "currently_visible_customer_ids_only"
            if args.idle_ev_readiness_mode != "none"
            else "disabled"
        ),
        "idle_ev_readiness_intervals": [
            asdict(interval) for interval in readiness_intervals
        ],
        "idle_ev_readiness_reserved_charging_actions": [
            asdict(action) for action in readiness_reserved_actions
        ],
        "idle_ev_readiness_envelope_limitations": (
            readiness_envelope_limitations
        ),
        "idle_ev_readiness_scope": (
            "visible_customers_grouped_by_home_depot; not a cross-depot guarantee"
        ),
        "idle_ev_readiness_costs": readiness_costs,
        "idle_ev_readiness_station_capacity_violations": [],
        "route_plan_total_cost_before_readiness_accounting": (
            final_result.best_evaluation.total_cost
        ),
        "total_cost_with_readiness_accounting": adjusted_total_cost,
        "route_plan_emissions_before_readiness_accounting": (
            final_result.best_evaluation.breakdown.get("E_total")
        ),
        "emissions_with_readiness_accounting": adjusted_total_emissions,
        "final_fairness_cold_recheck_enabled": True,
        "final_fairness_cold_recheck_is_nonformal_diagnostic": True,
        "final_fairness_cold_recheck_includes_readiness_cost": False,
        "final_fairness_feasible": final_fairness_evaluation.feasible,
        "final_fairness_violations": [
            asdict(item) for item in final_fairness_evaluation.violations
        ],
        "synthesized_idle_asset_ids": synthesized_idle,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    _json(output / "metadata.json", metadata)
    _write_rows_csv(output / "raw_runs.csv", stage_rows)
    _json(
        output / "decision.json",
        {
            "verdict": verdict,
            "failure_reasons": [],
            "what_this_answers": [
                "whether the independent Problem-HGS can consume all ten hidden-order disclosures across repeated certified cuts",
                "whether every intermediate full execution serves every currently visible customer exactly once",
                "whether earlier committed route and charging history remains unchanged",
                "whether the technical observed-demand idle-EV readiness option prevents a later physical dead end without reading hidden customer ids",
            ],
            "what_this_does_not_decide": [
                "formal trigger policy",
                "formal dynamic baseline",
                "dynamic-demand effect size",
                "formal representative instance",
                "stage-wise independent-profit semantics",
                "whether full-day settlement or stage-wise participation should govern dynamic replanning",
                "whether observed-max readiness should become the formal dynamic policy",
            ],
            "user_decision_changed": False,
        },
    )
    _json(
        output / "best_solution.json",
        {
            "individual": asdict(final_result.best),
            "evaluation": {
                "total_cost": final_result.best_evaluation.total_cost,
                "total_cost_with_readiness_accounting": adjusted_total_cost,
                "breakdown": dict(final_result.best_evaluation.breakdown),
                "breakdown_with_readiness_accounting": adjusted_breakdown,
                "emissions_with_readiness_accounting": adjusted_total_emissions,
                "readiness_costs": readiness_costs,
                "readiness_intervals": [
                    asdict(interval) for interval in readiness_intervals
                ],
                "readiness_reserved_charging_actions": [
                    asdict(action) for action in readiness_reserved_actions
                ],
                "readiness_envelope_limitations": (
                    readiness_envelope_limitations
                ),
                "readiness_station_capacity_violations": [],
                "feasible": final_result.best_evaluation.feasible,
                "violations": [
                    asdict(item) for item in final_result.best_evaluation.violations
                ],
                "prepared_solution": asdict(
                    final_result.best_evaluation.prepared_solution
                ),
            },
            "final_fairness_evaluation": {
                "feasible": final_fairness_evaluation.feasible,
                "violations": [
                    asdict(item) for item in final_fairness_evaluation.violations
                ],
                "participation_margin": dict(
                    final_fairness_evaluation.participation_margin
                ),
            },
        },
    )
    (output / "report.md").write_text(
        f"""# 动态订单连续技术试跑

本轮判定为 `{verdict}`。{len(stream.events)} 个原始订单先隐藏、再按现有 H0-G2 事件流分批出现；自研算法连续处理了 {len(batches)} 次触发。最终完成 {len(set(completed_ids))}/{len(_active_customer_ids(full_bundle))} 个客户和 {completed_demand:.6f}/{total_demand:.6f} 单位需求。各阶段都保持已经执行的路线和锁定充电不变。

本轮使用 `{args.trigger_policy}` 只为检查连续接线，不代表已经选择正式触发政策。空闲电车待命充电口径为 `{args.idle_ev_readiness_mode}`，只使用当时已经出现的客户，不读取后续隐藏订单；它仍是技术候选，不代表正式政策已经选定。待命充电累计 {readiness_costs['electricity_kwh']:.6f} kWh，计入后总成本为 {adjusted_total_cost:.6f}、总排放为 {adjusted_total_emissions:.6f} kg。

动态搜索各阶段均不启用利润参与约束，因为部分信息阶段与完整 50 单独立经营利润的关系尚未由用户确定；最后只做一次不参与搜索、不改变判定的冷复核，结果为 `{final_fairness_evaluation.feasible}`。该冷复核尚未把独立待命充电费用分摊到车场利润，因此只保留为诊断，不用它判断公平机制。

## 交付前九条自检

1. 每个事实是否有出处？——数字来自同包 metadata.json、raw_runs.csv、event_stream.csv 和 best_solution.json。
2. 有没有把建议或担忧写成已决？——没有；正式触发政策、公平阶段口径和动态基线仍未替用户决定。
3. 改动范围有没有超出任务文本？——没有，只补齐动态连续执行和技术试跑。
4. 有没有碰受保护文件？——未碰，前后哈希见 metadata.json。
5. 待决事项是否转成具体候选并写清代价？——本轮不新增选择题，待顾问技术论证后统一提交。
6. 有没有用自造词或内部任务号跟用户说话？——没有。
7. 失败、跳过、超时、异常结果有没有如实保留？——本轮没有隐藏失败；最终公平复核结果原样保存。
8. 四件套齐了吗？——metadata.json、raw_runs.csv、decision.json、artifact_hashes.json、report.md 齐全，另附 event_stream.csv 和 best_solution.json。
9. HANDOFF 和记忆同步了吗？——算法施工收口时统一同步。
""",
        encoding="utf-8",
    )
    _write_hashes(output)
    print(json.dumps({"verdict": verdict, **metadata}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        if _ACTIVE_OUTPUT is not None and _ACTIVE_INVOCATION_ID is not None:
            _write_failure(_ACTIVE_OUTPUT, _ACTIVE_INVOCATION_ID, exc)
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise
