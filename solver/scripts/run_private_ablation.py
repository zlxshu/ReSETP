#!/usr/bin/env python3
"""Run paired private-algorithm ablations under one wall-clock budget.

Each instance/seed pair freezes one initial population and one evaluation
context before any arm starts.  Arms then run serially with fresh runtime
objects; only the declared treatment switches may differ.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from experiment_acceptance import (  # noqa: E402
    NORMAL_PROBLEM_HGS_TERMINATIONS,
    RunAcceptance,
    assess_run,
    finalize_five_file_package,
    package_exit_code,
    row_is_accepted,
)

PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)

FLEET_PARAMETER_CLASS_IDS = {
    "fixed25": "DERIVED_FIXED_TOTAL_MULTITRIP_ZERO_SEARCH_AUTHORITY",
    "endogenous": "ENDOGENOUS_RD_RE_NO_ADDITIONAL_TOTAL_CAP",
}


@dataclass(frozen=True)
class TreatmentSwitches:
    schedule_cross_repair_fallback: bool = False
    schedule_all_changed_move_evaluation: bool = False
    fleet_activation_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            self.schedule_all_changed_move_evaluation
            and not self.schedule_cross_repair_fallback
        ):
            raise ValueError("all-move DSS requires crossover DSS fallback")
        if self.fleet_activation_enabled and not (
            self.schedule_all_changed_move_evaluation
        ):
            raise ValueError("endogenous fleet treatment requires all-move DSS")


@dataclass(frozen=True)
class _PreparedPopulation:
    candidates: tuple[Any, ...]
    evaluations: tuple[Any, ...]
    full_evaluation_count: int


@dataclass(frozen=True)
class ArmDefinition:
    arm: str
    label: str
    treatment: TreatmentSwitches
    include_propulsion_proxy: bool = False

    @property
    def participating_components(self) -> tuple[str, ...]:
        components = [
            "independent_route_kernel",
            "route_level_trip_assignment_crossover",
            "deterministic_charging_completion",
        ]
        if self.include_propulsion_proxy:
            components.append("half_load_propulsion_proxy")
        if self.treatment.schedule_cross_repair_fallback:
            components.append("dss_crossover_repair_fallback")
        if self.treatment.schedule_all_changed_move_evaluation:
            components.append("dss_all_changed_duty_move_evaluation")
        if self.treatment.fleet_activation_enabled:
            components.append("registered_empty_duty_activation_clearing")
        return tuple(components)


ARM_DEFINITIONS: Mapping[str, ArmDefinition] = {
    "A0": ArmDefinition(
        "A0",
        "只看路线基线（独立路线内核＋确定性补全）",
        TreatmentSwitches(),
        include_propulsion_proxy=False,
    ),
}


@dataclass(frozen=True)
class PairIdentity:
    arm: str
    instance_id: str
    seed: int
    initial_population_sha256: str
    main_rng_seed: int
    evaluation_context_sha256: str
    wall_clock_budget_seconds: float
    fleet_parameter_class_id: str = FLEET_PARAMETER_CLASS_IDS["fixed25"]


PAIR_FIELDS = (
    "instance_id",
    "seed",
    "initial_population_sha256",
    "main_rng_seed",
    "evaluation_context_sha256",
    "wall_clock_budget_seconds",
    "fleet_parameter_class_id",
)


class PairingMismatchError(RuntimeError):
    """Explain every field that differs inside a requested paired group."""


def validate_pairing(identities: Sequence[PairIdentity]) -> None:
    if not identities:
        raise ValueError("paired validation requires at least one arm")
    reference = identities[0]
    differences: dict[str, dict[str, dict[str, Any]]] = {}
    for identity in identities[1:]:
        arm_differences = {}
        for field in PAIR_FIELDS:
            expected = getattr(reference, field)
            actual = getattr(identity, field)
            if actual != expected:
                arm_differences[field] = {
                    "expected_from_arm": reference.arm,
                    "expected": expected,
                    "actual": actual,
                }
        if arm_differences:
            differences[identity.arm] = arm_differences
    if differences:
        raise PairingMismatchError(
            "paired ablation inputs differ; refusing to run: "
            + json.dumps(differences, ensure_ascii=False, sort_keys=True)
        )


REQUIRED_RAW_FIELDS = (
    "instance_id",
    "seed",
    "arm",
    "run_status",
    "wall_clock_budget_seconds",
    "initial_population_sha256",
    "main_rng_seed",
    "evaluation_context_sha256",
    "fleet_parameter_class_id",
    "total_cost",
    "total_emissions_kg",
    "full_evaluation_feasible",
    "hard_violation_count",
    "hard_violations_json",
    "customers_served",
    "customers_total",
    "demand_served",
    "demand_total",
    "demand_completion_ratio",
    "completed_generations",
    "time_to_best_seconds",
    "total_algorithm_wall_seconds",
    "dss_calls",
    "dss_feasible",
    "dss_infeasible",
    "dss_search_exhausted",
    "dss_wall_seconds_p50",
    "dss_wall_seconds_p95",
    "dss_wall_seconds_p99",
)


@dataclass
class _BestClock:
    wall_clock_budget_seconds: float
    best_cost: float | None = None
    time_to_best_seconds: float | None = None

    def stop(self, state: Any) -> bool:
        if state.best_cost is not None and (
            self.best_cost is None or float(state.best_cost) < self.best_cost
        ):
            self.best_cost = float(state.best_cost)
            self.time_to_best_seconds = float(state.elapsed_seconds)
        return float(state.elapsed_seconds) >= self.wall_clock_budget_seconds


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _pair_identities(
    arms: Sequence[str],
    *,
    instance_id: str,
    seed: int,
    initial_population_sha256: str,
    evaluation_context_sha256: str,
    wall_clock_budget_seconds: float,
    fleet_parameter_class_id: str,
) -> tuple[PairIdentity, ...]:
    return tuple(
        PairIdentity(
            arm=arm,
            instance_id=instance_id,
            seed=int(seed),
            initial_population_sha256=initial_population_sha256,
            main_rng_seed=int(seed),
            evaluation_context_sha256=evaluation_context_sha256,
            wall_clock_budget_seconds=float(wall_clock_budget_seconds),
            fleet_parameter_class_id=str(fleet_parameter_class_id),
        )
        for arm in arms
    )


def _prepare_shared_population(
    initial,
    context,
    *,
    seed: int,
    wall_clock_budget_seconds: float,
    population_mode: str = "copied_hgs_defaults",
) -> tuple[Any, float]:
    from run_problem_hgs_private_technical import (
        _parameters,
        _policy,
        _prepare_population,
    )
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
    from setp_solver.algorithms.problem_hgs.initialization import (
        build_initial_population,
    )
    from setp_solver.algorithms.problem_hgs.kernel_proposals import (
        IndependentKernelDutyRouteProposalEngine,
    )

    started = perf_counter()
    evaluator = DutyFullEvaluator(context)
    charging_policy = _policy(evaluator)
    parameters = _parameters(
        random_seed=seed,
        population_mode=population_mode,
        crossover_mode="fast_only",
    )
    full_calls_before = evaluator.full_calls
    if population_mode == "technical_two_parent":
        (
            candidates,
            _initial_evaluation,
            _reverse,
            _attempts,
            _selected,
            evaluations,
        ) = _prepare_population(
            initial,
            evaluator,
            charging_policy,
            parameters,
            require_distinct_selection=False,
        )
        built = _PreparedPopulation(
            candidates=tuple(candidates),
            evaluations=tuple(evaluations),
            full_evaluation_count=evaluator.full_calls - full_calls_before,
        )
    else:
        route_engine = IndependentKernelDutyRouteProposalEngine(
            context,
            initial,
            random_seed=seed,
            stream_role="private_ablation_initialization",
        )
        population = build_initial_population(
            initial,
            evaluator=evaluator,
            charging_policy=charging_policy,
            route_engine=route_engine,
            requested_size=parameters.population.min_pop_size,
            random_seed=seed,
            max_random_attempts=None,
            stop_requested=lambda: (
                perf_counter() - started >= wall_clock_budget_seconds
            ),
        )
        built = _PreparedPopulation(
            candidates=tuple(population.candidates),
            evaluations=tuple(population.evaluations),
            full_evaluation_count=evaluator.full_calls - full_calls_before,
        )
    if not built.candidates:
        raise RuntimeError("initial population construction returned no candidate")
    return built, perf_counter() - started


def runtime_treatment_for_arm(arm: str, treatment_type=TreatmentSwitches):
    """Bind one declared arm to the runtime treatment object."""

    definition = ARM_DEFINITIONS[arm]
    return treatment_type(**asdict(definition.treatment))


def _service_fields(result, bundle) -> dict[str, float | int]:
    served = {
        customer
        for duty in result.best.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    customer_nodes = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served_demand = sum(float(customer_nodes[item].demand) for item in served)
    total_demand = sum(float(node.demand) for node in customer_nodes.values())
    return {
        "customers_served": len(served),
        "customers_total": len(customer_nodes),
        "demand_served": served_demand,
        "demand_total": total_demand,
        "demand_completion_ratio": (
            served_demand / total_demand if total_demand else 1.0
        ),
    }


def _run_one_arm(
    *,
    arm: str,
    seed: int,
    wall_clock_budget_seconds: float,
    context,
    bundle,
    initial,
    built: Any,
    initialization_wall_seconds: float,
    expected_identity: PairIdentity,
    population_mode: str,
) -> dict[str, Any]:
    from run_problem_hgs_private_technical import _parameters, _policy
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
    from setp_solver.algorithms.problem_hgs.kernel_proposals import (
        IndependentKernelDutyRouteProposalEngine,
    )
    from setp_solver.algorithms.problem_hgs.proposals import (
        SequentialProposalEngine,
    )
    from setp_solver.algorithms.problem_hgs.runner import (
        FrozenPopulationIdentity,
        PrivateAblationTreatment,
        population_sha256,
        run_integrated_problem_hgs,
    )

    definition = ARM_DEFINITIONS[arm]
    runtime_setup_started = perf_counter()
    evaluator = DutyFullEvaluator(context)
    charging_policy = _policy(evaluator)
    parameters = _parameters(
        random_seed=seed,
        population_mode=population_mode,
        crossover_mode="fast_only",
    )
    route_engine = IndependentKernelDutyRouteProposalEngine(
        context,
        initial,
        random_seed=seed,
        stream_role="main_route",
        include_propulsion_proxy=definition.include_propulsion_proxy,
    )
    proposal_engine = SequentialProposalEngine(
        (route_engine,),
        source_id="private-ablation-route-only-v1",
    )
    budgeted_initialization_wall_seconds = (
        float(initialization_wall_seconds)
        + perf_counter()
        - runtime_setup_started
    )
    identity = FrozenPopulationIdentity(
        source_id=f"private-ablation-shared-seed-{seed}",
        value_sha256=population_sha256(built.candidates),
    )
    runtime_identity = PairIdentity(
        arm=arm,
        instance_id=bundle.instance_id,
        seed=int(parameters.random_seed),
        initial_population_sha256=identity.value_sha256,
        main_rng_seed=int(seed),
        evaluation_context_sha256=evaluator.context_sha256,
        wall_clock_budget_seconds=float(wall_clock_budget_seconds),
        fleet_parameter_class_id=bundle.fleet_parameter_class_id,
    )
    validate_pairing((expected_identity, runtime_identity))
    clock = _BestClock(float(wall_clock_budget_seconds))
    result = run_integrated_problem_hgs(
        built.candidates,
        evaluator=evaluator,
        charging_policy=charging_policy,
        parameters=parameters,
        initial_population_identity=identity,
        stop=clock.stop,
        arm=arm,
        route_engine=route_engine,
        proposal_engine=proposal_engine,
        trajectory_sink=lambda _rows: None,
        retain_trajectory=False,
        initial_evaluations=built.evaluations,
        initialization_full_evaluation_count=built.full_evaluation_count,
        initialization_wall_seconds=budgeted_initialization_wall_seconds,
        treatment=runtime_treatment_for_arm(arm, PrivateAblationTreatment),
    )
    accounting = result.accounting.to_dict()
    total_wall = float(accounting["total_algorithm_wall_seconds"])
    final_cost = float(result.best_evaluation.total_cost)
    if clock.best_cost is None or final_cost < clock.best_cost:
        clock.best_cost = final_cost
        clock.time_to_best_seconds = total_wall
    dss_statuses = accounting["schedule_oracle_statuses"]
    dss_wall = accounting["schedule_oracle_wall_seconds"]
    row: dict[str, Any] = {
        "instance_id": bundle.instance_id,
        "seed": int(seed),
        "arm": arm,
        "arm_label": definition.label,
        "participating_components": json.dumps(
            definition.participating_components,
            ensure_ascii=False,
        ),
        "run_status": result.termination_status,
        "wall_clock_budget_seconds": float(wall_clock_budget_seconds),
        "initial_population_sha256": identity.value_sha256,
        "main_rng_seed": int(seed),
        "evaluation_context_sha256": evaluator.context_sha256,
        "fleet_parameter_class_id": bundle.fleet_parameter_class_id,
        "search_configuration_sha256": (
            result.provenance.search_configuration_sha256
        ),
        "total_cost": final_cost,
        "total_emissions_kg": float(
            result.best_evaluation.breakdown.get("E_total", 0.0)
        ),
        "full_evaluation_feasible": bool(result.best_evaluation.feasible),
        "hard_violation_count": len(result.best_evaluation.violations),
        "hard_violations_json": json.dumps(
            [asdict(item) for item in result.best_evaluation.violations],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "completed_generations": int(result.iterations),
        "time_to_best_seconds": clock.time_to_best_seconds,
        "initialization_wall_seconds": float(
            accounting["initialization_wall_seconds"]
        ),
        "search_wall_seconds": float(accounting["run_wall_seconds"]),
        "total_algorithm_wall_seconds": total_wall,
        "dss_calls": int(accounting["schedule_oracle_calls"]),
        "dss_feasible": int(dss_statuses.get("FEASIBLE", 0)),
        "dss_infeasible": int(dss_statuses.get("INFEASIBLE", 0)),
        "dss_search_exhausted": int(
            dss_statuses.get("SEARCH_EXHAUSTED", 0)
        ),
        "dss_wall_seconds_p50": dss_wall["p50"],
        "dss_wall_seconds_p95": dss_wall["p95"],
        "dss_wall_seconds_p99": dss_wall["p99"],
        "dss_coordinator_calls": int(accounting["schedule_coordinator_calls"]),
        "dss_coordinator_statuses": json.dumps(
            accounting["schedule_coordinator_statuses"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "dss_rescued_by_channel": json.dumps(
            accounting["schedule_rescued_candidates_by_channel"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "cost_breakdown_json": json.dumps(
            dict(result.best_evaluation.breakdown),
            ensure_ascii=False,
            sort_keys=True,
        ),
        "error_type": result.termination_error_type,
        "error": result.termination_error,
    }
    row.update(_service_fields(result, bundle))
    for key, value in sorted(result.best_evaluation.breakdown.items()):
        row[f"breakdown__{key}"] = value
    return row


def _failure_row(identity: PairIdentity, error: Exception) -> dict[str, Any]:
    definition = ARM_DEFINITIONS[identity.arm]
    row = {field: None for field in REQUIRED_RAW_FIELDS}
    row.update(
        {
            "instance_id": identity.instance_id,
            "seed": identity.seed,
            "arm": identity.arm,
            "arm_label": definition.label,
            "participating_components": json.dumps(
                definition.participating_components,
                ensure_ascii=False,
            ),
            "run_status": "FAILED",
            "wall_clock_budget_seconds": identity.wall_clock_budget_seconds,
            "initial_population_sha256": identity.initial_population_sha256,
            "main_rng_seed": identity.main_rng_seed,
            "evaluation_context_sha256": identity.evaluation_context_sha256,
            "fleet_parameter_class_id": identity.fleet_parameter_class_id,
            "error_type": type(error).__name__,
            "error": str(error),
            "traceback": traceback.format_exc(),
        }
    )
    return row


def _ordered_fields(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    extras = sorted(
        set().union(*(row.keys() for row in rows)).difference(REQUIRED_RAW_FIELDS)
    )
    return [*REQUIRED_RAW_FIELDS, *extras]


def _assess_row(
    row: Mapping[str, Any],
    *,
    audit_ok: bool = True,
) -> RunAcceptance:
    return assess_run(
        termination_ok=(
            row.get("run_status") in NORMAL_PROBLEM_HGS_TERMINATIONS
        ),
        feasible_ok=(
            row.get("full_evaluation_feasible") is True
            and row.get("hard_violation_count") == 0
        ),
        customers_complete=(
            row.get("customers_served") is not None
            and row.get("customers_served") == row.get("customers_total")
        ),
        demand_complete=(
            row.get("demand_served") is not None
            and row.get("demand_served") == row.get("demand_total")
        ),
        audit_ok=audit_ok,
        extra_failure_reasons=(
            f"{row.get('error_type')}: {row.get('error')}"
            if row.get("error_type") or row.get("error")
            else "",
        ),
        success_verdict="PRIVATE_ABLATION_RUN_COMPLETE",
        failure_verdict="PRIVATE_ABLATION_RUN_FAILED",
    )


def _successful_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if row_is_accepted(row)]


def render_report(rows: Sequence[Mapping[str, Any]]) -> str:
    successful = _successful_rows(rows)
    arms = [arm for arm in ARM_DEFINITIONS if any(row["arm"] == arm for row in rows)]
    lines = [
        "# 私有算法配对消融报告",
        "",
        "所有运行按请求顺序串行执行。每个算例—种子组在开跑前核对算例、初始种群哈希、主 RNG 种子、评价上下文哈希和墙钟预算；这些字段相同后才允许各臂运行。",
        "",
        "## 各臂 Best / Avg",
        "",
        "| 臂 | 完成数 | Best 完整成本 | Avg 完整成本 | Avg 排放(kg) | Avg 服务客户 | Avg 需求完成度 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in arms:
        arm_rows = [row for row in successful if row["arm"] == arm]
        if not arm_rows:
            lines.append(f"| {arm} | 0 | — | — | — | — | — |")
            continue
        lines.append(
            "| {arm} | {count} | {best:.6f} | {avg:.6f} | {emissions:.6f} | "
            "{customers:.3f} | {completion:.6%} |".format(
                arm=arm,
                count=len(arm_rows),
                best=min(float(row["total_cost"]) for row in arm_rows),
                avg=statistics.mean(float(row["total_cost"]) for row in arm_rows),
                emissions=statistics.mean(
                    float(row["total_emissions_kg"]) for row in arm_rows
                ),
                customers=statistics.mean(
                    float(row["customers_served"]) for row in arm_rows
                ),
                completion=statistics.mean(
                    float(row["demand_completion_ratio"]) for row in arm_rows
                ),
            )
        )

    lines.extend(
        [
            "",
            "## 同种子配对差",
            "",
            "配对差按“后臂减前臂”计算；负的成本差表示后臂成本更低。只使用两臂都完成的同一算例、同一种子。",
            "",
            "| 配对 | 对数 | Avg 成本差 | Avg 成本差(%) | Avg 排放差(kg) | Avg 服务客户差 | Avg 需求完成度差 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    by_key = {
        (str(row["instance_id"]), int(row["seed"]), str(row["arm"])): row
        for row in successful
    }
    for left_index, left in enumerate(arms):
        for right in arms[left_index + 1 :]:
            pairs = []
            for instance_id, seed, arm in sorted(by_key):
                if arm != left:
                    continue
                left_row = by_key[(instance_id, seed, left)]
                right_row = by_key.get((instance_id, seed, right))
                if right_row is not None:
                    pairs.append((left_row, right_row))
            if not pairs:
                lines.append(f"| {right} − {left} | 0 | — | — | — | — | — |")
                continue
            cost_diffs = [
                float(right_row["total_cost"]) - float(left_row["total_cost"])
                for left_row, right_row in pairs
            ]
            cost_pcts = [
                diff / float(left_row["total_cost"]) * 100.0
                for diff, (left_row, _right_row) in zip(cost_diffs, pairs, strict=True)
            ]
            emissions = [
                float(right_row["total_emissions_kg"])
                - float(left_row["total_emissions_kg"])
                for left_row, right_row in pairs
            ]
            customers = [
                float(right_row["customers_served"])
                - float(left_row["customers_served"])
                for left_row, right_row in pairs
            ]
            completion = [
                float(right_row["demand_completion_ratio"])
                - float(left_row["demand_completion_ratio"])
                for left_row, right_row in pairs
            ]
            lines.append(
                f"| {right} − {left} | {len(pairs)} | "
                f"{statistics.mean(cost_diffs):.6f} | "
                f"{statistics.mean(cost_pcts):.6f}% | "
                f"{statistics.mean(emissions):.6f} | "
                f"{statistics.mean(customers):.6f} | "
                f"{statistics.mean(completion):.6%} |"
            )

    failed = [row for row in rows if not row_is_accepted(row)]
    lines.extend(["", "## 运行完整性", ""])
    if failed:
        lines.append(f"失败 {len(failed)} 次；错误原文保留在 `raw_runs.csv`。")
    else:
        lines.append("没有运行失败。")
    lines.append(
        "每行同时保存服务客户数和需求完成度；成本或排放读数不与少服务混在一起解释。"
    )
    return "\n".join(lines) + "\n"


def write_result_package(
    output: Path,
    rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    acceptance: RunAcceptance,
) -> None:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    fields = _ordered_fields(rows)
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    decision = {
        "planned_run_count": len(rows),
        "accepted_run_count": sum(row_is_accepted(row) for row in rows),
        "rejected_run_count": sum(not row_is_accepted(row) for row in rows),
    }
    finalize_five_file_package(
        output,
        acceptance=acceptance,
        metadata=metadata,
        decision=decision,
        report_text=render_report(rows),
        complete_status="COMPLETED",
    )


def _dry_run_payload(args, repo: Path) -> dict[str, Any]:
    fleet_parameter_class_id = FLEET_PARAMETER_CLASS_IDS[args.fleet_parameters]
    groups = []
    for seed in args.seeds:
        initial_sha = hashlib.sha256(
            (
                f"PRIVATE_ABLATION_SHARED_POPULATION_V1\n"
                f"{args.instance_id}\n{int(seed)}"
            ).encode("utf-8")
        ).hexdigest()
        context_sha = hashlib.sha256(
            (
                f"PRIVATE_ABLATION_SHARED_EVALUATION_CONTEXT_V1\n"
                f"{args.instance_id}\n{fleet_parameter_class_id}"
            ).encode("utf-8")
        ).hexdigest()
        identities = _pair_identities(
            args.arms,
            instance_id=args.instance_id,
            seed=seed,
            initial_population_sha256=initial_sha,
            evaluation_context_sha256=context_sha,
            wall_clock_budget_seconds=args.wall_clock_seconds,
            fleet_parameter_class_id=fleet_parameter_class_id,
        )
        validate_pairing(identities)
        groups.append([asdict(identity) for identity in identities])
    return {
        "mode": "DRY_RUN",
        "solver_entered": False,
        "serial_execution": True,
        "output_directory_created": False,
        "instance_id": args.instance_id,
        "seeds": list(args.seeds),
        "wall_clock_budget_seconds": args.wall_clock_seconds,
        "fleet_parameter_class_id": fleet_parameter_class_id,
        "arms": {
            arm: {
                "label": ARM_DEFINITIONS[arm].label,
                "participating_components": (
                    ARM_DEFINITIONS[arm].participating_components
                ),
                "treatment": asdict(ARM_DEFINITIONS[arm].treatment),
                "include_propulsion_proxy": (
                    ARM_DEFINITIONS[arm].include_propulsion_proxy
                ),
            }
            for arm in args.arms
        },
        "pair_validation": "PASSED",
        "pair_groups": groups,
        "dry_run_identity_scope": (
            "planned shared identities; actual population and context hashes are recomputed and revalidated before any non-dry arm starts"
        ),
    }


def _parse_args(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--wall-clock-seconds", type=float, required=True)
    parser.add_argument(
        "--fleet-parameters",
        choices=tuple(FLEET_PARAMETER_CLASS_IDS),
        default="fixed25",
    )
    parser.add_argument(
        "--arms",
        nargs="+",
        choices=tuple(ARM_DEFINITIONS),
        required=True,
    )
    parser.add_argument(
        "--population-mode",
        choices=("technical_two_parent", "copied_hgs_defaults"),
        default="copied_hgs_defaults",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.wall_clock_seconds <= 0.0:
        parser.error("--wall-clock-seconds must be positive")
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("--seeds cannot contain duplicates")
    if len(set(args.arms)) != len(args.arms):
        parser.error("--arms cannot contain duplicates")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    if args.dry_run:
        print(
            json.dumps(
                _dry_run_payload(args, repo),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        )
        return 0

    from run_public_v2_28_clean_ruler import _prepare_independent_imports

    _prepare_independent_imports()
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    from run_problem_hgs_private_technical import (
        _build_context,
        _effective_population_metadata,
        _parameters,
    )
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
    from setp_solver.algorithms.problem_hgs.runner import population_sha256
    from setp_solver.china81 import (
        ENDOGENOUS_FLEET_PARAMETERS,
        FIXED_25_PERCENT_FLEET_PARAMETERS,
    )

    fleet_parameters = {
        "fixed25": FIXED_25_PERCENT_FLEET_PARAMETERS,
        "endogenous": ENDOGENOUS_FLEET_PARAMETERS,
    }[args.fleet_parameters]

    bundle, initial, _pi0, context = _build_context(
        repo,
        args.instance_id,
        fleet_parameters=fleet_parameters,
    )
    rows: list[dict[str, Any]] = []
    pair_groups = []
    for seed in args.seeds:
        built, initialization_wall_seconds = _prepare_shared_population(
            initial,
            context,
            seed=seed,
            wall_clock_budget_seconds=args.wall_clock_seconds,
            population_mode=args.population_mode,
        )
        initial_sha = population_sha256(built.candidates)
        context_sha = DutyFullEvaluator(context).context_sha256
        identities = _pair_identities(
            args.arms,
            instance_id=bundle.instance_id,
            seed=seed,
            initial_population_sha256=initial_sha,
            evaluation_context_sha256=context_sha,
            wall_clock_budget_seconds=args.wall_clock_seconds,
            fleet_parameter_class_id=bundle.fleet_parameter_class_id,
        )
        validate_pairing(identities)
        pair_groups.append([asdict(identity) for identity in identities])
        by_arm = {identity.arm: identity for identity in identities}
        for arm in args.arms:
            try:
                row = _run_one_arm(
                    arm=arm,
                    seed=seed,
                    wall_clock_budget_seconds=args.wall_clock_seconds,
                    context=context,
                    bundle=bundle,
                    initial=initial,
                    built=built,
                    initialization_wall_seconds=initialization_wall_seconds,
                    expected_identity=by_arm[arm],
                    population_mode=args.population_mode,
                )
            except Exception as error:  # Preserve one arm's exact failure.
                row = _failure_row(by_arm[arm], error)
            row.update(_assess_row(row).row_fields())
            rows.append(row)

    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    protected_ok = protected_after == protected_before
    if not protected_ok:
        for row in rows:
            row.update(_assess_row(row, audit_ok=False).row_fields())
    metadata = {
        "instance_id": bundle.instance_id,
        "seeds": list(args.seeds),
        "arms": list(args.arms),
        "arm_definitions": {
            arm: {
                "label": definition.label,
                "participating_components": definition.participating_components,
                "treatment": asdict(definition.treatment),
                "include_propulsion_proxy": definition.include_propulsion_proxy,
            }
            for arm, definition in ARM_DEFINITIONS.items()
            if arm in args.arms
        },
        "wall_clock_budget_seconds": args.wall_clock_seconds,
        "budget_semantics": "initialization plus search wall clock",
        "effective_population": _effective_population_metadata(
            args.population_mode,
            _parameters(population_mode=args.population_mode).population,
        ),
        "serial_execution": True,
        "pair_validation": "PASSED",
        "pair_fields": PAIR_FIELDS,
        "pair_groups": pair_groups,
        "fleet_parameter_class_id": bundle.fleet_parameter_class_id,
        "fleet_registry_semantics": (
            "A0 keeps the registered physical assets for safe decoding; "
            "empty-duty activation and clearing are disabled"
        ),
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "command_argv": list(sys.argv if argv is None else argv),
    }
    accepted_rows = _successful_rows(rows)
    overall = assess_run(
        termination_ok=len(accepted_rows) == len(rows),
        feasible_ok=all(row.get("full_evaluation_feasible") is True for row in rows),
        customers_complete=all(
            row.get("customers_served") == row.get("customers_total")
            for row in rows
        ),
        demand_complete=all(
            row.get("demand_served") == row.get("demand_total")
            for row in rows
        ),
        audit_ok=protected_ok,
        extra_failure_reasons=tuple(
            f"{row.get('instance_id')} seed={row.get('seed')} arm={row.get('arm')}: "
            f"{row.get('acceptance_failure_reasons')}"
            for row in rows
            if not row_is_accepted(row)
        ),
        success_verdict="PRIVATE_ABLATION_BATCH_COMPLETE",
        failure_verdict="PRIVATE_ABLATION_BATCH_FAILED",
    )
    write_result_package(output, rows, metadata, overall)
    return package_exit_code(overall)


if __name__ == "__main__":
    raise SystemExit(main())
