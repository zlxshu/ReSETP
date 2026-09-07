#!/usr/bin/env python3
"""Run the four registered mixed-fleet levels with the current serial solver."""

from __future__ import annotations

import argparse
import csv
import json
import secrets
import statistics
import sys
import traceback
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from experiment_acceptance import (  # noqa: E402
    NORMAL_PROBLEM_HGS_TERMINATIONS,
    assess_run,
    finalize_run_output,
    result_exit_code,
    row_is_accepted,
)


REPEAT_COUNT = 3
FLEET_PACKAGE = Path(
    "data/ChinaInstances/china81_final_suite_v2_20260815"
)

FLEET_LEVEL_CAPS = {
    "cv18_ev2": {
        "D_OSM_WAY_1003511503": (5, 1),
        "D_OSM_WAY_1071205721": (13, 1),
    },
    "cv13_ev7": {
        "D_OSM_WAY_1003511503": (3, 3),
        "D_OSM_WAY_1071205721": (10, 4),
    },
    "cv7_ev13": {
        "D_OSM_WAY_1003511503": (2, 4),
        "D_OSM_WAY_1071205721": (5, 9),
    },
    "cv2_ev18": {
        "D_OSM_WAY_1003511503": (1, 5),
        "D_OSM_WAY_1071205721": (1, 13),
    },
}


@dataclass(frozen=True)
class ArmDefinition:
    arm: str
    label: str
    cap_mode: str
    initial_witness_level: str
    role: str


ARM_DEFINITIONS: Mapping[str, ArmDefinition] = {
    name: ArmDefinition(
        name,
        name.removeprefix("cv").replace("_ev", " CV / ") + " EV",
        name,
        "native_registered_population",
        "PAPER_FLEET_LEVEL",
    )
    for name in FLEET_LEVEL_CAPS
}


@dataclass(frozen=True)
class _PreparedPopulation:
    candidates: tuple[Any, ...]
    evaluations: tuple[Any, ...]
    full_evaluation_count: int


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _authority_rows(repo: Path) -> dict[str, dict[str, dict[str, str]]]:
    path = repo / FLEET_PACKAGE / "fleet_caps.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows: dict[str, dict[str, dict[str, str]]] = {}
        for row in csv.DictReader(handle):
            rows.setdefault(row["instance_id"], {})[row["depot_id"]] = row
    return rows


def _validate_static_inputs(args: argparse.Namespace, repo: Path) -> dict[str, Any]:
    authorities = _authority_rows(repo)
    missing = [instance for instance in args.instances if instance not in authorities]
    if missing:
        raise ValueError(f"instances absent from fleet authority: {missing}")
    return {"fleet_authority": str(FLEET_PACKAGE / "fleet_caps.csv")}


def _dry_run_payload(
    args: argparse.Namespace,
    repo: Path,
    validated: Mapping[str, Any],
) -> dict[str, Any]:
    fleet_parameter_class_id = _metadata_fleet_parameter_class_id(args.arms)
    return {
        "mode": "DRY_RUN",
        "experiment_id": args.experiment_id,
        "solver_entered": False,
        "output_directory_created": False,
        "serial_execution": True,
        "instances": list(args.instances),
        "repeat_count": REPEAT_COUNT,
        "arms": {
            arm: asdict(ARM_DEFINITIONS[arm]) for arm in args.arms
        },
        "stop_rule": "20,000 consecutive non-improving iterations; no restart",
        "objective_mode": args.objective_mode,
        "charging_curve": args.charging_curve,
        "charge_timing_policy": args.charge_timing_policy,
        "fleet_parameter_class_id": fleet_parameter_class_id,
        "fleet_parameter_class_ids_by_arm": {
            arm: _planned_fleet_parameter_class_id(arm) for arm in args.arms
        },
        "planned_run_count": len(args.instances) * REPEAT_COUNT * len(args.arms),
        "fleet_authority": validated["fleet_authority"],
    }


def _planned_fleet_parameter_class_id(arm: str) -> str:
    return ARM_DEFINITIONS[arm].cap_mode


def _metadata_fleet_parameter_class_id(arms: Sequence[str]) -> str | list[str]:
    class_ids = list(
        dict.fromkeys(_planned_fleet_parameter_class_id(arm) for arm in arms)
    )
    return class_ids[0] if len(class_ids) == 1 else class_ids


def _arm_setup(
    repo: Path,
    instance_id: str,
    arm: str,
    charging_curve: str,
) -> tuple[Any, Any, Any]:
    from run_problem_hgs_private_technical import _build_context
    from setp_solver.algorithms.problem_hgs.fleet_registry import (
        register_all_vehicle_slots,
    )
    from setp_solver.algorithms.problem_hgs.model import DutyIndividual
    from setp_solver.charging_curve import (
        L100_CONTROL,
        M17_FAST_SHAPE_SCALED_60KW_PWL,
    )
    from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS

    base, _old_initial, _neutral, context = _build_context(
        repo,
        instance_id,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    requested = FLEET_LEVEL_CAPS[arm]
    if set(requested) != set(base.fleet_caps_by_depot):
        raise ValueError("registered fleet level does not cover both depots")
    caps = MappingProxyType(
        {
            depot_id: MappingProxyType(
                {"num_cv": cv, "num_ev": ev, "total_fleet_cap": cv + ev}
            )
            for depot_id, (cv, ev) in requested.items()
        }
    )
    bundle = replace(
        base,
        instance=replace(
            base.instance,
            num_cv=sum(cv for cv, _ev in requested.values()),
            num_ev=sum(ev for _cv, ev in requested.values()),
        ),
        fleet_caps_by_depot=caps,
        fleet_parameter_class_id=ARM_DEFINITIONS[arm].cap_mode,
        has_additional_total_fleet_cap=True,
    )
    curve = {
        "linear": L100_CONTROL,
        "literature_pwl": M17_FAST_SHAPE_SCALED_60KW_PWL,
    }[charging_curve]
    prices = replace(
        bundle.prices,
        charging_curve_id=curve.curve_id,
        charging_soc_breakpoints=curve.soc_breakpoints,
        charging_relative_powers=curve.relative_powers,
        depot_charging_curve_id=curve.curve_id,
        depot_charging_soc_breakpoints=curve.soc_breakpoints,
        depot_charging_relative_powers=curve.relative_powers,
        public_charging_curve_id=curve.curve_id,
        public_charging_soc_breakpoints=curve.soc_breakpoints,
        public_charging_relative_powers=curve.relative_powers,
    )
    bundle = replace(bundle, prices=prices)
    customers = tuple(
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"
    )
    initial = register_all_vehicle_slots(
        DutyIndividual(
            duties=(),
            unserved_customers=customers,
            source=f"mixed-fleet-native-initial/{arm}",
        ),
        bundle,
    )
    context = replace(context, bundle=bundle, fairness_enabled=False, theta=0.0)
    return bundle, initial, context


def _prepare_population(
    initial: Any,
    context: Any,
    *,
    random_source: int,
    objective_mode: str,
    population_mode: str,
    charge_timing_policy: str,
) -> tuple[Any, float]:
    from run_problem_hgs_private_technical import (
        _parameters,
        _policy,
        _prepare_population as _prepare_reference_population,
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
    policy = _policy(evaluator, charge_timing_policy=charge_timing_policy)
    parameters = _parameters(
        population_mode=population_mode,
        objective_mode=objective_mode,
    )
    full_calls_before = evaluator.full_calls
    if population_mode == "technical_two_parent":
        candidates, _initial_evaluation, evaluations = _prepare_reference_population(
            initial,
            evaluator,
            policy,
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
            stream_role="main2_initialization",
            depot_assignment_operator_enabled=True,
            rebuilt_volume_capacity_enabled=True,
            rebuilt_shift_neighbours_only=True,
            shift_aware_ev_unit_cost_enabled=True,
        )
        population = build_initial_population(
            initial,
            evaluator=evaluator,
            charging_policy=policy,
            route_engine=route_engine,
            requested_size=parameters.population.min_pop_size,
            max_random_attempts=None,
            include_reference_candidate=False,
            stop_requested=lambda: False,
        )
        built = _PreparedPopulation(
            candidates=tuple(population.candidates),
            evaluations=tuple(population.evaluations),
            full_evaluation_count=evaluator.full_calls - full_calls_before,
        )
    if len(built.candidates) < 4:
        raise RuntimeError("initial population construction returned fewer than four candidates")
    return built, perf_counter() - started


def _service_fields(individual: Any, bundle: Any) -> dict[str, float | int]:
    served = {
        customer
        for duty in individual.duties
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
        "customer_completion_ratio": (
            len(served) / len(customer_nodes) if customer_nodes else 1.0
        ),
        "demand_served": served_demand,
        "demand_total": total_demand,
        "demand_completion_ratio": (
            served_demand / total_demand if total_demand else 1.0
        ),
    }


def _fleet_fields(individual: Any) -> dict[str, int]:
    used = [duty for duty in individual.duties if duty.trips]
    return {
        "used_cv_vehicles": sum(duty.vehicle_type == "cv" for duty in used),
        "used_ev_vehicles": sum(duty.vehicle_type == "ev" for duty in used),
        "used_total_vehicles": len(used),
        "cv_trips": sum(
            len(duty.trips) for duty in used if duty.vehicle_type == "cv"
        ),
        "ev_trips": sum(
            len(duty.trips) for duty in used if duty.vehicle_type == "ev"
        ),
        "total_trips": sum(len(duty.trips) for duty in used),
    }


def _fleet_use_by_depot(individual: Any, bundle: Any) -> dict[str, dict[str, int]]:
    rows = {}
    for depot_id, caps in sorted(bundle.fleet_caps_by_depot.items()):
        duties = [
            duty
            for duty in individual.duties
            if duty.home_depot_id == depot_id and duty.trips
        ]
        used_cv = sum(duty.vehicle_type == "cv" for duty in duties)
        used_ev = sum(duty.vehicle_type == "ev" for duty in duties)
        cv_trips = sum(
            len(duty.trips) for duty in duties if duty.vehicle_type == "cv"
        )
        ev_trips = sum(
            len(duty.trips) for duty in duties if duty.vehicle_type == "ev"
        )
        rows[depot_id] = {
            "cv_cap": int(caps["num_cv"]),
            "ev_cap": int(caps["num_ev"]),
            "total_cap": int(caps["total_fleet_cap"]),
            "used_cv": used_cv,
            "used_ev": used_ev,
            "used_total": used_cv + used_ev,
            "cv_trips": cv_trips,
            "ev_trips": ev_trips,
            "total_trips": cv_trips + ev_trips,
            "cv_cap_slack": int(caps["num_cv"]) - used_cv,
            "ev_cap_slack": int(caps["num_ev"]) - used_ev,
            "total_cap_slack": int(caps["total_fleet_cap"])
            - used_cv
            - used_ev,
        }
    return rows


def _run_one(
    *,
    repo: Path,
    instance_id: str,
    arm: str,
    repeat_index: int,
    objective_mode: str,
    population_mode: str,
    charging_curve: str,
    charge_timing_policy: str,
    run_dir: Path,
) -> dict[str, Any]:
    from run_problem_hgs_private_technical import _parameters, _policy
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
    from setp_solver.algorithms.problem_hgs.kernel_proposals import (
        IndependentKernelDutyRouteProposalEngine,
    )
    from setp_solver.algorithms.problem_hgs.runner import run_integrated_problem_hgs

    random_source = secrets.randbelow(2**31)
    bundle, initial, context = _arm_setup(
        repo,
        instance_id,
        arm,
        charging_curve,
    )
    built, initialization_wall_seconds = _prepare_population(
        initial,
        context,
        random_source=random_source,
        objective_mode=objective_mode,
        population_mode=population_mode,
        charge_timing_policy=charge_timing_policy,
    )
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator, charge_timing_policy=charge_timing_policy)
    parameters = _parameters(
        population_mode=population_mode,
        objective_mode=objective_mode,
    )
    route_engine = IndependentKernelDutyRouteProposalEngine(
        context,
        initial,
        stream_role="main2_main_route",
        depot_assignment_operator_enabled=True,
        rebuilt_volume_capacity_enabled=True,
        rebuilt_shift_neighbours_only=True,
        shift_aware_ev_unit_cost_enabled=True,
    )
    result = run_integrated_problem_hgs(
        built.candidates,
        evaluator=evaluator,
        charging_policy=policy,
        parameters=parameters,
        stop=lambda state: (
            state.iterations_without_improvement
            >= parameters.stagnation_patience
        ),
        arm=arm,
        route_engine=route_engine,
        trajectory_sink=lambda _rows: None,
        retain_trajectory=False,
        initial_evaluations=built.evaluations,
        initialization_full_evaluation_count=built.full_evaluation_count,
        initialization_wall_seconds=initialization_wall_seconds,
    )
    selected_individual = result.best
    selected_evaluation = result.best_evaluation
    accounting = result.accounting.to_dict()
    row: dict[str, Any] = {
        "instance_id": instance_id,
        "repeat_index": int(repeat_index),
        "arm": arm,
        "arm_label": ARM_DEFINITIONS[arm].label,
        "arm_role": ARM_DEFINITIONS[arm].role,
        "run_status": result.termination_status,
        "objective_mode": objective_mode,
        "charging_curve": charging_curve,
        "charge_timing_policy": charge_timing_policy,
        "fleet_parameter_class_id": bundle.fleet_parameter_class_id,
        "total_cost_cny": float(selected_evaluation.total_cost),
        "direct_emissions_kg": float(
            selected_evaluation.breakdown["E_cv_direct"]
        ),
        "indirect_emissions_kg": float(
            selected_evaluation.breakdown["E_ev_indirect"]
        ),
        "total_emissions_kg": float(selected_evaluation.breakdown["E_total"]),
        "feasible": bool(selected_evaluation.feasible),
        "violation_count": len(selected_evaluation.violations),
        "completed_generations": int(result.iterations),
        "initialization_wall_seconds": float(
            accounting["initialization_wall_seconds"]
        ),
        "search_wall_seconds": float(accounting["run_wall_seconds"]),
        "total_algorithm_wall_seconds": float(
            accounting["total_algorithm_wall_seconds"]
        ),
        "fleet_caps_by_depot_json": json.dumps(
            {key: dict(value) for key, value in bundle.fleet_caps_by_depot.items()},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "error_type": result.termination_error_type,
        "error": result.termination_error,
    }
    row.update(_service_fields(selected_individual, bundle))
    row.update(_fleet_fields(selected_individual))
    row["fleet_use_by_depot_json"] = json.dumps(
        _fleet_use_by_depot(selected_individual, bundle),
        ensure_ascii=False,
        sort_keys=True,
    )
    for key, value in sorted(selected_evaluation.breakdown.items()):
        row[f"breakdown__{key}"] = value

    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "result.json",
        {
            "row": row,
            "selected_solution": asdict(selected_individual),
            "selected_evaluation": {
                "breakdown": dict(selected_evaluation.breakdown),
                "feasible": selected_evaluation.feasible,
                "violations": [asdict(item) for item in selected_evaluation.violations],
            },
            "accounting": accounting,
        },
    )
    return row


def _failure_row(
    *,
    instance_id: str,
    arm: str,
    repeat_index: int,
    objective_mode: str,
    error: Exception,
) -> dict[str, Any]:
    row = {
        "instance_id": instance_id,
        "repeat_index": repeat_index,
        "arm": arm,
        "arm_label": ARM_DEFINITIONS[arm].label,
        "arm_role": ARM_DEFINITIONS[arm].role,
        "run_status": "FAILED",
        "objective_mode": objective_mode,
        "fleet_parameter_class_id": _planned_fleet_parameter_class_id(arm),
        "error_type": type(error).__name__,
        "error": str(error),
        "traceback": traceback.format_exc(),
    }
    row.update(_assess_row(row).row_fields())
    return row


def _ordered_fields(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    preferred = [
        "instance_id",
        "repeat_index",
        "arm",
        "arm_label",
        "arm_role",
        "run_status",
        "objective_mode",
        "fleet_parameter_class_id",
        "total_cost_cny",
        "direct_emissions_kg",
        "indirect_emissions_kg",
        "total_emissions_kg",
        "customers_served",
        "customers_total",
        "customer_completion_ratio",
        "demand_served",
        "demand_total",
        "demand_completion_ratio",
        "used_cv_vehicles",
        "used_ev_vehicles",
        "used_total_vehicles",
        "cv_trips",
        "ev_trips",
        "total_trips",
        "fleet_use_by_depot_json",
    ]
    available = set().union(*(row.keys() for row in rows)) if rows else set()
    return [*preferred, *sorted(available.difference(preferred))]


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = _ordered_fields(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _assess_row(row: Mapping[str, Any]):
    return assess_run(
        termination_ok=(
            row.get("run_status") in NORMAL_PROBLEM_HGS_TERMINATIONS
        ),
        feasible_ok=(
            row.get("feasible") is True
            and row.get("violation_count") == 0
        ),
        customers_complete=(
            row.get("customers_served") is not None
            and row.get("customers_served") == row.get("customers_total")
        ),
        demand_complete=(
            row.get("demand_served") is not None
            and row.get("demand_served") == row.get("demand_total")
        ),
        extra_failure_reasons=(
            f"{row.get('error_type')}: {row.get('error')}"
            if row.get("error_type") or row.get("error")
            else ""
        ,),
        success_verdict="MIXED_FLEET_RUN_COMPLETE",
        failure_verdict="MIXED_FLEET_RUN_FAILED",
    )


def _successful(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if row_is_accepted(row)]


def render_report(rows: Sequence[Mapping[str, Any]]) -> str:
    successful = _successful(rows)
    arms = [
        arm for arm in ARM_DEFINITIONS if any(row.get("arm") == arm for row in rows)
    ]
    lines = [
        "# MAIN-2 混合车队实验运行报告",
        "",
        "四个车队水平各独立运行 3 次，只按连续 20,000 次完整迭代无改善停止且不重启。每次运行自行产生内部随机性，不指定也不记录随机轨迹。",
        "",
        "## 各臂 Best / Avg",
        "",
        "| 实验臂 | 完成运行 | Best 成本 | Avg 成本 | Avg 总排放 | Avg 油/电车 | Avg 油/电趟 | Avg 服务客户 | Avg 需求完成度 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in arms:
        arm_rows = [row for row in successful if row["arm"] == arm]
        if not arm_rows:
            lines.append(f"| {arm} | 0 | — | — | — | — | — | — | — |")
            continue
        lines.append(
            "| {arm} | {count} | {best:.6f} | {avg:.6f} | {emissions:.6f} | "
            "{cv:.3f}/{ev:.3f} | {cvt:.3f}/{evt:.3f} | {customers:.3f} | "
            "{demand:.6%} |".format(
                arm=arm,
                count=len(arm_rows),
                best=min(float(row["total_cost_cny"]) for row in arm_rows),
                avg=statistics.mean(float(row["total_cost_cny"]) for row in arm_rows),
                emissions=statistics.mean(
                    float(row["total_emissions_kg"]) for row in arm_rows
                ),
                cv=statistics.mean(float(row["used_cv_vehicles"]) for row in arm_rows),
                ev=statistics.mean(float(row["used_ev_vehicles"]) for row in arm_rows),
                cvt=statistics.mean(float(row["cv_trips"]) for row in arm_rows),
                evt=statistics.mean(float(row["ev_trips"]) for row in arm_rows),
                customers=statistics.mean(
                    float(row["customers_served"]) for row in arm_rows
                ),
                demand=statistics.mean(
                    float(row["demand_completion_ratio"]) for row in arm_rows
                ),
            )
        )
    lines.extend(
        [
            "",
            "## 同次重复的水平差",
            "",
            "下表只汇总两个车队水平都完成的同一算例、同一重复序号；差值为前者减后者。服务量差同时保留，不能用少服务解释降本或减排。",
            "",
            "| 配对 | 对数 | Avg 成本差 | Avg 总排放差 | Avg 服务客户差 | Avg 需求完成度差 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    by_key = {
        (
            str(row["instance_id"]),
            int(row["repeat_index"]),
            str(row["arm"]),
        ): row
        for row in successful
    }
    comparisons = (
        ("cv18_ev2", "cv13_ev7"),
        ("cv13_ev7", "cv7_ev13"),
        ("cv7_ev13", "cv2_ev18"),
    )
    for left, right in comparisons:
        if left not in arms or right not in arms:
            continue
        pairs = []
        for instance_id, repeat_index, arm in sorted(by_key):
            if arm != left:
                continue
            right_row = by_key.get((instance_id, repeat_index, right))
            if right_row is not None:
                pairs.append(
                    (by_key[(instance_id, repeat_index, left)], right_row)
                )
        if not pairs:
            lines.append(f"| {left} − {right} | 0 | — | — | — | — |")
            continue
        lines.append(
            f"| {left} − {right} | {len(pairs)} | "
            f"{statistics.mean(float(a['total_cost_cny']) - float(b['total_cost_cny']) for a, b in pairs):.6f} | "
            f"{statistics.mean(float(a['total_emissions_kg']) - float(b['total_emissions_kg']) for a, b in pairs):.6f} | "
            f"{statistics.mean(float(a['customers_served']) - float(b['customers_served']) for a, b in pairs):.6f} | "
            f"{statistics.mean(float(a['demand_completion_ratio']) - float(b['demand_completion_ratio']) for a, b in pairs):.6%} |"
        )
    failed = [row for row in rows if not row_is_accepted(row)]
    lines.extend(["", "## 完整性", ""])
    lines.append(
        f"验收通过 {len(successful)} 次，拒绝 {len(failed)} 次。"
        "失败原文保留在 `raw_runs.csv`。"
    )
    return "\n".join(lines) + "\n"

def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--data-repo-root", type=Path)
    parser.add_argument("--instances", nargs="+", required=True)
    parser.add_argument(
        "--arms",
        nargs="+",
        choices=tuple(ARM_DEFINITIONS),
    )
    parser.add_argument(
        "--experiment-id",
        choices=("MIXED_FLEET", "NONLINEAR_CHARGING", "TIME_VARYING_CARBON"),
        default="MIXED_FLEET",
    )
    parser.add_argument(
        "--charging-curve",
        choices=("linear", "literature_pwl"),
        default="literature_pwl",
    )
    parser.add_argument(
        "--charge-timing-policy",
        choices=("asap", "cost_plus_carbon"),
        default="cost_plus_carbon",
    )
    parser.add_argument(
        "--objective-mode",
        choices=("single_objective",),
        default="single_objective",
    )
    parser.add_argument(
        "--population-mode",
        choices=("technical_two_parent", "copied_hgs_defaults"),
        default="copied_hgs_defaults",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.arms is None:
        args.arms = list(ARM_DEFINITIONS)
    for label, values in (
        ("--instances", args.instances),
        ("--arms", args.arms),
    ):
        if len(set(values)) != len(values):
            parser.error(f"{label} cannot contain duplicates")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    code_repo = Path(__file__).resolve().parents[2]
    data_repo = (
        code_repo
        if args.data_repo_root is None
        else args.data_repo_root.resolve()
    )
    validated = _validate_static_inputs(args, data_repo)
    if args.dry_run:
        print(
            json.dumps(
                _dry_run_payload(args, data_repo, validated),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        )
        return 0

    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    from run_problem_hgs_private_technical import (
        _effective_population_metadata,
        _parameters,
    )

    rows: list[dict[str, Any]] = []
    metadata = {
        "status": "RUNNING",
        "experiment_id": args.experiment_id,
        "instances": list(args.instances),
        "arms": list(args.arms),
        "arm_definitions": {
            arm: asdict(ARM_DEFINITIONS[arm]) for arm in args.arms
        },
        "repeat_count": REPEAT_COUNT,
        "stop_rule": "20,000 consecutive non-improving iterations; no restart",
        "objective_mode": args.objective_mode,
        "charging_curve": args.charging_curve,
        "charge_timing_policy": args.charge_timing_policy,
        "effective_population": _effective_population_metadata(
            args.population_mode,
            _parameters(
                population_mode=args.population_mode,
                objective_mode=args.objective_mode,
            ).population,
        ),
        "fleet_parameter_class_id": _metadata_fleet_parameter_class_id(args.arms),
        "fleet_parameter_class_ids_by_arm": {
            arm: _planned_fleet_parameter_class_id(arm) for arm in args.arms
        },
        "serial_execution": True,
        "fleet_authority": validated["fleet_authority"],
        "command_argv": list(sys.argv if argv is None else argv),
    }
    _write_json(output / "metadata.json", metadata)
    for instance_id in args.instances:
        for repeat_index in range(1, REPEAT_COUNT + 1):
            for arm in args.arms:
                run_dir = (
                    output
                    / "runs"
                    / instance_id
                    / arm
                    / f"repeat_{repeat_index}"
                )
                try:
                    row = _run_one(
                        repo=data_repo,
                        instance_id=instance_id,
                        arm=arm,
                        repeat_index=repeat_index,
                        objective_mode=args.objective_mode,
                        population_mode=args.population_mode,
                        charging_curve=args.charging_curve,
                        charge_timing_policy=args.charge_timing_policy,
                        run_dir=run_dir,
                    )
                except Exception as error:  # Preserve exact per-run failure.
                    row = _failure_row(
                        instance_id=instance_id,
                        arm=arm,
                        repeat_index=repeat_index,
                        objective_mode=args.objective_mode,
                        error=error,
                    )
                    run_dir.mkdir(parents=True, exist_ok=True)
                    _write_json(run_dir / "failure.json", row)
                if "acceptance_passed" not in row:
                    row.update(_assess_row(row).row_fields())
                rows.append(row)

    _write_csv(output / "raw_runs.csv", rows)
    metadata.update(
        {
            "planned_run_count": len(args.instances)
            * REPEAT_COUNT
            * len(args.arms),
            "recorded_run_count": len(rows),
        }
    )
    accepted_rows = _successful(rows)
    overall = assess_run(
        termination_ok=len(accepted_rows) == len(rows),
        feasible_ok=all(row.get("feasible") is True for row in rows),
        customers_complete=all(
            row.get("customers_served") == row.get("customers_total")
            for row in rows
        ),
        demand_complete=all(
            row.get("demand_served") == row.get("demand_total")
            for row in rows
        ),
        extra_failure_reasons=tuple(
            f"{row.get('instance_id')} repeat={row.get('repeat_index')} arm={row.get('arm')}: "
            f"{row.get('acceptance_failure_reasons')}"
            for row in rows
            if not row_is_accepted(row)
        ),
        success_verdict="MIXED_FLEET_BATCH_COMPLETE",
        failure_verdict="MIXED_FLEET_BATCH_FAILED",
    )
    decision = {
        "planned_run_count": len(rows),
        "accepted_run_count": len(accepted_rows),
        "rejected_run_count": len(rows) - len(accepted_rows),
    }
    finalize_run_output(
        output,
        acceptance=overall,
        metadata=metadata,
        decision=decision,
        report_text=render_report(rows),
        complete_status="COMPLETED",
    )
    return result_exit_code(overall)


if __name__ == "__main__":
    raise SystemExit(main())
