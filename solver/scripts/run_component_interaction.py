#!/usr/bin/env python3
"""Run a paired full-factorial interaction test for private HGS components.

The harness is deliberately serial.  For each instance/seed pair it freezes one
initial population and one complete-evaluation context, then runs every one of
the ``2^k`` component combinations with the same wall-clock budget.  Positive
gain means lower cost (or lower emissions).  For any combination S with at
least two components, the reported interaction is

    gain(S) - sum(gain({component}) for component in S).

No significance threshold is embedded.  The report gives the paired mean,
sample standard deviation, and standard error and leaves scientific judgement
to the approved experiment protocol.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
import traceback
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence


PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)

# This first executable matrix intentionally contains only components that can
# be independently isolated without changing the active core solver files.
EXECUTABLE_COMPONENTS = (
    "route_local_search",
    "charging_timing",
    "vehicle_type_exchange",
)

COMPONENT_LABELS = {
    "route_local_search": "路线内核局部搜索",
    "charging_timing": "充电修复后的充电择时候选",
    "vehicle_type_exchange": "同车场整 Duty 车型换型",
}

FLEET_PARAMETER_CLASS_IDS = {
    "fixed25": "DERIVED_FIXED_TOTAL_MULTITRIP_ZERO_SEARCH_AUTHORITY",
    "endogenous": "ENDOGENOUS_RD_RE_NO_ADDITIONAL_TOTAL_CAP",
}

CHANNEL_COMPONENT = {
    "route_kernel": "route_local_search",
    "time_varying_carbon_charge": "charging_timing",
    "whole_duty_type_exchange": "vehicle_type_exchange",
}

PAIR_FIELDS = (
    "instance_id",
    "seed",
    "initial_population_sha256",
    "main_rng_seed",
    "evaluation_context_sha256",
    "wall_clock_budget_seconds",
    "fleet_parameter_class_id",
)

REQUIRED_RAW_FIELDS = (
    "instance_id",
    "seed",
    "arm_id",
    "component_bitmask",
    "enabled_components",
    "run_status",
    "wall_clock_budget_seconds",
    "initial_population_sha256",
    "main_rng_seed",
    "evaluation_context_sha256",
    "fleet_parameter_class_id",
    "search_configuration_sha256",
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
    "active_vehicle_count",
    "active_cv_count",
    "active_ev_count",
    "vehicle_daily_distance_json",
    "completed_generations",
    "best_cost_iteration_10",
    "best_cost_iteration_50",
    "best_cost_iteration_100",
    "best_cost_iteration_200",
    "last_improvement_iteration",
    "iterations_since_last_improvement",
    "time_to_best_seconds",
    "total_algorithm_wall_seconds",
    "best_solution_fingerprint",
    "charging_action_count",
    "contains_charging_actions",
    "baseline_total_cost",
    "cost_gain",
    "sum_single_cost_gains",
    "cost_interaction",
    "baseline_total_emissions_kg",
    "emissions_gain_kg",
    "sum_single_emissions_gains_kg",
    "emissions_interaction_kg",
    "interaction_service_comparable",
    "interaction_input_arms",
    "proposal_rows_by_component",
    "accepted_rows_by_component",
    "background_trip_assignment_crossover_calls",
    "error_type",
    "error",
)


@dataclass(frozen=True)
class FactorialArm:
    arm_id: str
    bitmask: str
    enabled_components: tuple[str, ...]

    @property
    def runtime_switches(self) -> dict[str, Any]:
        return {
            "proposal_components": self.enabled_components,
            "route_local_search_enabled": (
                "route_local_search" in self.enabled_components
            ),
            "charging_timing_enabled": (
                "charging_timing" in self.enabled_components
            ),
            "vehicle_type_exchange_enabled": (
                "vehicle_type_exchange" in self.enabled_components
            ),
            # These are deliberately common background conditions in the first
            # matrix, not factors whose effects are estimated here.
            "trip_assignment_crossover_background": True,
            "registered_empty_duty_activation_background": True,
            "population_objective_background": "single_objective",
        }


@dataclass(frozen=True)
class PairIdentity:
    arm_id: str
    instance_id: str
    seed: int
    initial_population_sha256: str
    main_rng_seed: int
    evaluation_context_sha256: str
    wall_clock_budget_seconds: float
    fleet_parameter_class_id: str


class PairingMismatchError(RuntimeError):
    """Identify every differing field within one requested paired group."""


@dataclass
class _BestClock:
    wall_clock_budget_seconds: float
    best_cost: float | None = None
    time_to_best_seconds: float | None = None
    last_improvement_iteration: int | None = None
    best_cost_by_iteration: dict[int, float] = field(default_factory=dict)

    def observe(self, state: Any) -> None:
        iteration = int(state.iterations)
        if state.best_cost is None:
            return
        current = float(state.best_cost)
        self.best_cost_by_iteration[iteration] = current
        if self.best_cost is None or current < self.best_cost:
            self.best_cost = current
            self.time_to_best_seconds = float(state.elapsed_seconds)
            self.last_improvement_iteration = iteration

    def stop(self, state: Any) -> bool:
        self.observe(state)
        return float(state.elapsed_seconds) >= self.wall_clock_budget_seconds

    def cost_at(self, iteration: int) -> float | None:
        eligible = [
            key for key in self.best_cost_by_iteration if key <= int(iteration)
        ]
        if not eligible or max(self.best_cost_by_iteration) < int(iteration):
            return None
        return self.best_cost_by_iteration[max(eligible)]


def build_factorial_arms(components: Sequence[str]) -> tuple[FactorialArm, ...]:
    """Return all 2^k arms in stable bit-mask order."""

    ordered = tuple(str(item) for item in components)
    if not ordered:
        raise ValueError("at least one component is required")
    if len(set(ordered)) != len(ordered):
        raise ValueError("components cannot contain duplicates")
    unknown = sorted(set(ordered).difference(EXECUTABLE_COMPONENTS))
    if unknown:
        raise ValueError("unsupported executable components: " + ", ".join(unknown))
    width = len(ordered)
    arms = []
    for mask in range(1 << width):
        bitmask = format(mask, f"0{width}b")
        enabled = tuple(
            component
            for index, component in enumerate(ordered)
            if mask & (1 << index)
        )
        arms.append(FactorialArm(f"F{bitmask}", bitmask, enabled))
    return tuple(arms)


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
                    "expected_from_arm": reference.arm_id,
                    "expected": expected,
                    "actual": actual,
                }
        if arm_differences:
            differences[identity.arm_id] = arm_differences
    if differences:
        raise PairingMismatchError(
            "paired component inputs differ; refusing to run: "
            + json.dumps(differences, ensure_ascii=False, sort_keys=True)
        )


def select_component_moves(
    enabled_components: Iterable[str],
    route_moves: Iterable[Any],
    mechanism_moves: Iterable[Any],
) -> tuple[Any, ...]:
    """Filter the actual proposal streams using the declared component set."""

    enabled = frozenset(enabled_components)
    selected = []
    if "route_local_search" in enabled:
        selected.extend(route_moves)
    selected.extend(
        move
        for move in mechanism_moves
        if CHANNEL_COMPONENT.get(str(move.channel)) in enabled
    )
    return tuple(selected)


class ComponentProposalEngine:
    """One serial proposal stream whose membership is controlled by an arm."""

    def __init__(
        self,
        route_engine: Any,
        mechanism_engine: Any,
        enabled_components: Iterable[str],
    ) -> None:
        self._route_engine = route_engine
        self._mechanism_engine = mechanism_engine
        self._enabled = tuple(sorted(set(enabled_components)))
        self.source_id = "component-interaction-v1:" + "+".join(self._enabled)
        payload = {
            "source_id": self.source_id,
            "enabled_components": self._enabled,
            "route_engine": getattr(route_engine, "identity_sha256", "unknown"),
            "mechanism_engine": getattr(
                mechanism_engine, "identity_sha256", "unknown"
            ),
        }
        self.identity_sha256 = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def propose(
        self,
        individual: Any,
        evaluation: Any,
        instance: Any,
        *,
        include_whole_duty_type_exchange: bool,
    ) -> Iterable[Any]:
        def selected_moves() -> Iterable[Any]:
            if "route_local_search" in self._enabled:
                yield from self._route_engine.propose(
                    individual,
                    evaluation,
                    instance,
                    include_whole_duty_type_exchange=(
                        include_whole_duty_type_exchange
                    ),
                )
            if {"charging_timing", "vehicle_type_exchange"}.intersection(
                self._enabled
            ):
                for move in self._mechanism_engine.propose(
                    individual,
                    evaluation,
                    instance,
                    include_whole_duty_type_exchange=(
                        include_whole_duty_type_exchange
                    ),
                ):
                    if CHANNEL_COMPONENT.get(str(move.channel)) in self._enabled:
                        yield move

        return selected_moves()


def _proposal_engine_for_arm(
    route_engine: Any,
    mechanism_engine: Any,
    enabled_components: Iterable[str],
) -> Any | None:
    enabled = frozenset(enabled_components)
    if enabled == frozenset(EXECUTABLE_COMPONENTS):
        # None selects the same split route-then-mechanism system path used by
        # run_problem_hgs_private_technical.py --proposal-mode system.
        return None
    return ComponentProposalEngine(route_engine, mechanism_engine, enabled)


def _component_tuple(row: Mapping[str, Any]) -> tuple[str, ...]:
    raw = row.get("enabled_components", ())
    if isinstance(raw, str):
        loaded = json.loads(raw)
        return tuple(str(item) for item in loaded)
    return tuple(str(item) for item in raw)


def _successful(row: Mapping[str, Any]) -> bool:
    return row.get("total_cost") not in (None, "") and row.get("run_status") != "FAILED"


def _service_identity(row: Mapping[str, Any]) -> tuple[float, ...]:
    return (
        float(row["customers_served"]),
        float(row["customers_total"]),
        float(row["demand_served"]),
        float(row["demand_total"]),
    )


def annotate_interactions(rows: Sequence[dict[str, Any]]) -> None:
    """Add per-seed gains and additive interaction terms to raw run rows."""

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["instance_id"]), int(row["seed"])), []).append(row)

    for group in grouped.values():
        successful = [row for row in group if _successful(row)]
        by_components = {
            frozenset(_component_tuple(row)): row for row in successful
        }
        baseline = by_components.get(frozenset())
        for row in group:
            row.update(
                {
                    "baseline_total_cost": None,
                    "cost_gain": None,
                    "sum_single_cost_gains": None,
                    "cost_interaction": None,
                    "baseline_total_emissions_kg": None,
                    "emissions_gain_kg": None,
                    "sum_single_emissions_gains_kg": None,
                    "emissions_interaction_kg": None,
                    "interaction_service_comparable": None,
                    "interaction_input_arms": None,
                }
            )
            if baseline is None or not _successful(row):
                continue
            enabled = frozenset(_component_tuple(row))
            singleton_rows = [
                by_components.get(frozenset({component}))
                for component in sorted(enabled)
            ]
            if any(item is None for item in singleton_rows):
                continue
            inputs = [baseline, *singleton_rows, row]
            baseline_cost = float(baseline["total_cost"])
            baseline_emissions = float(baseline["total_emissions_kg"])
            cost_gain = baseline_cost - float(row["total_cost"])
            emissions_gain = baseline_emissions - float(row["total_emissions_kg"])
            single_cost_sum = sum(
                baseline_cost - float(item["total_cost"])
                for item in singleton_rows
            )
            single_emissions_sum = sum(
                baseline_emissions - float(item["total_emissions_kg"])
                for item in singleton_rows
            )
            row.update(
                {
                    "baseline_total_cost": baseline_cost,
                    "cost_gain": cost_gain,
                    "sum_single_cost_gains": single_cost_sum,
                    "cost_interaction": (
                        cost_gain - single_cost_sum if len(enabled) >= 2 else None
                    ),
                    "baseline_total_emissions_kg": baseline_emissions,
                    "emissions_gain_kg": emissions_gain,
                    "sum_single_emissions_gains_kg": single_emissions_sum,
                    "emissions_interaction_kg": (
                        emissions_gain - single_emissions_sum
                        if len(enabled) >= 2
                        else None
                    ),
                    "interaction_service_comparable": (
                        len({_service_identity(item) for item in inputs}) == 1
                    ),
                    "interaction_input_arms": json.dumps(
                        [str(item["arm_id"]) for item in inputs],
                        ensure_ascii=False,
                    ),
                }
            )


def _mean_se(values: Sequence[float]) -> tuple[int, float | None, float | None, float | None]:
    if not values:
        return 0, None, None, None
    mean = statistics.mean(values)
    if len(values) < 2:
        return len(values), mean, None, None
    sample_sd = statistics.stdev(values)
    return len(values), mean, sample_sd, sample_sd / math.sqrt(len(values))


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.9f}"


def render_report(
    rows: Sequence[Mapping[str, Any]],
    component_order: Sequence[str],
) -> str:
    """Render estimates without converting any number into a pass threshold."""

    successful = [row for row in rows if _successful(row)]
    lines = [
        "# 零件交互配对因子测试报告",
        "",
        "本包按算例—种子冻结初始种群、主随机种子、完整评价上下文和墙钟预算；各组合串行运行。正增益表示成本或排放下降。交互项按“组合增益减去各单件增益之和”逐种子计算。",
        "",
        "本报告只给配对均值、样本标准差和标准误差，不内置显著性阈值，也不把正负方向自动写成科研结论。",
        "",
        "## 因子",
        "",
    ]
    for component in component_order:
        lines.append(f"- `{component}`：{COMPONENT_LABELS[component]}")
    lines.extend(
        [
            "",
            "共同背景保持开启：整趟指派遗传交叉、注册表内空 Duty 激活许可、完整评价器；种群目标保持单目标成本。它们不是本包估计的因子。",
            "",
            "## 单件增益",
            "",
            "| 零件 | 有效配对数 | 成本增益均值 | 样本标准差 | 标准误差 | 排放增益均值(kg) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for component in component_order:
        arm_rows = [
            row
            for row in successful
            if frozenset(_component_tuple(row)) == frozenset({component})
            and row.get("cost_gain") is not None
            and bool(row.get("interaction_service_comparable"))
        ]
        n, mean, sd, se = _mean_se([float(row["cost_gain"]) for row in arm_rows])
        _ne, emissions_mean, _sde, _see = _mean_se(
            [float(row["emissions_gain_kg"]) for row in arm_rows]
        )
        lines.append(
            f"| {component} | {n} | {_fmt(mean)} | {_fmt(sd)} | {_fmt(se)} | {_fmt(emissions_mean)} |"
        )

    lines.extend(
        [
            "",
            "## 组合交互项",
            "",
            "| 组合 | 有效配对数 | 成本交互均值 | 样本标准差 | 标准误差 | 排放交互均值(kg) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    seen_sets = sorted(
        {
            frozenset(_component_tuple(row))
            for row in successful
            if len(_component_tuple(row)) >= 2
        },
        key=lambda item: (len(item), tuple(sorted(item))),
    )
    for enabled in seen_sets:
        arm_rows = [
            row
            for row in successful
            if frozenset(_component_tuple(row)) == enabled
            and row.get("cost_interaction") is not None
            and bool(row.get("interaction_service_comparable"))
        ]
        n, mean, sd, se = _mean_se(
            [float(row["cost_interaction"]) for row in arm_rows]
        )
        _ne, emissions_mean, _sde, _see = _mean_se(
            [float(row["emissions_interaction_kg"]) for row in arm_rows]
        )
        lines.append(
            f"| {' + '.join(sorted(enabled))} | {n} | {_fmt(mean)} | {_fmt(sd)} | {_fmt(se)} | {_fmt(emissions_mean)} |"
        )

    failures = [row for row in rows if row.get("run_status") == "FAILED"]
    service_mismatches = [
        row
        for row in successful
        if len(_component_tuple(row)) >= 1
        and row.get("interaction_service_comparable") is False
    ]
    lines.extend(
        [
            "",
            "## 噪声与配对口径",
            "",
            "既有 PRD50 静态同配置三种子成本相对样本标准差为 1.659387%。本台架不拿这个数设门槛，而是通过同种子、同初始种群、同评价上下文和同墙钟预算配对消去共同的算例与种子难度。若两臂读数正相关，配对差方差为 Var(A)+Var(B)-2Cov(A,B)，会小于把两臂当独立样本时的方差；实际能缩小多少，以本包交互项的样本标准差和标准误差为准。",
            "",
            "## 完整性",
            "",
            f"- 完成并保存读数：{len(successful)} 行；失败：{len(failures)} 行。",
            f"- 服务量不一致、因此不进入交互汇总：{len(service_mismatches)} 行。",
            "- 每行保存完成客户数和完成需求量；失败原文保留在 `raw_runs.csv`。",
        ]
    )
    return "\n".join(lines) + "\n"


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


def _ordered_fields(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    extras = sorted(
        set().union(*(row.keys() for row in rows)).difference(REQUIRED_RAW_FIELDS)
    )
    return (*REQUIRED_RAW_FIELDS, *extras)


def write_result_package(
    output: Path,
    rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    component_order: Sequence[str],
) -> None:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=_ordered_fields(rows),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    _write_json(output / "metadata.json", dict(metadata))
    (output / "report.md").write_text(
        render_report(rows, component_order), encoding="utf-8"
    )
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    _write_json(output / "artifact_hashes.json", hashes)


def _pair_identities(
    arms: Sequence[FactorialArm],
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
            arm_id=arm.arm_id,
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


def _service_fields(result: Any, bundle: Any) -> dict[str, float | int]:
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


def _fleet_fields(result: Any, bundle: Any) -> dict[str, Any]:
    """Persist the active fleet and exact road-profile distance per duty."""

    vehicles = []
    for duty in result.best.duties:
        if not duty.trips:
            continue
        distance_m = 0.0
        for trip in duty.trips:
            sequence = (
                duty.home_depot_id,
                *trip.effective_route_visits,
                duty.home_depot_id,
            )
            distance_m += sum(
                float(
                    bundle.instance.arc_metrics(
                        left,
                        right,
                        duty.vehicle_type,
                        fallback_speed_mps=1.0,
                    )[0]
                )
                for left, right in zip(sequence, sequence[1:])
            )
        vehicles.append(
            {
                "physical_vehicle_id": duty.physical_vehicle_id,
                "vehicle_type": duty.vehicle_type,
                "home_depot_id": duty.home_depot_id,
                "trip_count": len(duty.trips),
                "daily_distance_km": distance_m / 1000.0,
            }
        )
    vehicles.sort(key=lambda item: str(item["physical_vehicle_id"]))
    cv_count = sum(item["vehicle_type"] == "cv" for item in vehicles)
    ev_count = sum(item["vehicle_type"] == "ev" for item in vehicles)
    return {
        "active_vehicle_count": len(vehicles),
        "active_cv_count": cv_count,
        "active_ev_count": ev_count,
        "vehicle_daily_distance_json": json.dumps(
            vehicles,
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def _run_one_arm(
    *,
    arm: FactorialArm,
    seed: int,
    wall_clock_budget_seconds: float,
    context: Any,
    bundle: Any,
    initial: Any,
    built: Any,
    initialization_wall_seconds: float,
    expected_identity: PairIdentity,
    population_mode: str,
) -> dict[str, Any]:
    # Heavy solver imports are intentionally kept outside module import and
    # dry-run so wiring validation remains a sub-second, solver-free operation.
    from run_problem_hgs_private_technical import _parameters, _policy
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
    from setp_solver.algorithms.problem_hgs.kernel_proposals import (
        IndependentKernelDutyRouteProposalEngine,
    )
    from setp_solver.algorithms.problem_hgs.proposals import MechanismProposalEngine
    from setp_solver.algorithms.problem_hgs.runner import (
        FrozenPopulationIdentity,
        population_sha256,
        run_integrated_problem_hgs,
    )

    runtime_setup_started = perf_counter()
    evaluator = DutyFullEvaluator(context)
    charging_policy = _policy(evaluator)
    parameters = replace(
        _parameters(
            random_seed=seed,
            population_mode=population_mode,
            crossover_mode="fast_only",
        ),
        include_whole_duty_type_exchange=(
            "vehicle_type_exchange" in arm.enabled_components
        ),
    )
    route_engine = IndependentKernelDutyRouteProposalEngine(
        context,
        initial,
        random_seed=seed,
        stream_role=f"component_interaction_{arm.arm_id}",
    )
    mechanism_engine = MechanismProposalEngine(
        context,
        charging_policy,
        include_charging_candidates=(
            "charging_timing" in arm.enabled_components
        ),
        include_non_charging_candidates=(
            "vehicle_type_exchange" in arm.enabled_components
        ),
        source_id=f"component-interaction-mechanism:{arm.arm_id}",
    )
    proposal_engine = _proposal_engine_for_arm(
        route_engine,
        mechanism_engine,
        arm.enabled_components,
    )
    identity = FrozenPopulationIdentity(
        source_id=f"component-interaction-shared-seed-{seed}",
        value_sha256=population_sha256(built.candidates),
    )
    runtime_identity = PairIdentity(
        arm_id=arm.arm_id,
        instance_id=bundle.instance_id,
        seed=int(parameters.random_seed),
        initial_population_sha256=identity.value_sha256,
        main_rng_seed=int(seed),
        evaluation_context_sha256=evaluator.context_sha256,
        wall_clock_budget_seconds=float(wall_clock_budget_seconds),
        fleet_parameter_class_id=bundle.fleet_parameter_class_id,
    )
    validate_pairing((expected_identity, runtime_identity))

    proposed = {component: 0 for component in EXECUTABLE_COMPONENTS}
    accepted = {component: 0 for component in EXECUTABLE_COMPONENTS}

    def trajectory_sink(rows: Iterable[Any]) -> None:
        for item in rows:
            component = CHANNEL_COMPONENT.get(str(item.channel))
            if component is None:
                continue
            proposed[component] += 1
            if bool(item.accepted):
                accepted[component] += 1

    budgeted_initialization_wall_seconds = (
        float(initialization_wall_seconds)
        + perf_counter()
        - runtime_setup_started
    )
    clock = _BestClock(float(wall_clock_budget_seconds))
    result = run_integrated_problem_hgs(
        built.candidates,
        evaluator=evaluator,
        charging_policy=charging_policy,
        parameters=parameters,
        initial_population_identity=identity,
        stop=clock.stop,
        arm=arm.arm_id,
        route_engine=route_engine,
        trajectory_sink=trajectory_sink,
        retain_trajectory=False,
        proposal_engine=proposal_engine,
        initial_evaluations=built.evaluations,
        initialization_full_evaluation_count=built.full_evaluation_count,
        initialization_wall_seconds=budgeted_initialization_wall_seconds,
    )
    accounting = result.accounting.to_dict()
    final_cost = float(result.best_evaluation.total_cost)
    total_wall = float(accounting["total_algorithm_wall_seconds"])
    clock.observe(
        type(
            "FinalSearchState",
            (),
            {
                "iterations": int(result.iterations),
                "best_cost": final_cost,
                "elapsed_seconds": total_wall,
            },
        )()
    )
    charging_action_count = sum(
        len(duty.charging_sessions) for duty in result.best.duties
    )
    row: dict[str, Any] = {
        "instance_id": bundle.instance_id,
        "seed": int(seed),
        "arm_id": arm.arm_id,
        "component_bitmask": arm.bitmask,
        "enabled_components": json.dumps(
            arm.enabled_components, ensure_ascii=False
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
            result.best_evaluation.breakdown["E_total"]
        ),
        "full_evaluation_feasible": bool(result.best_evaluation.feasible),
        "hard_violation_count": len(result.best_evaluation.violations),
        "hard_violations_json": json.dumps(
            [asdict(item) for item in result.best_evaluation.violations],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "completed_generations": int(result.iterations),
        "best_cost_iteration_10": clock.cost_at(10),
        "best_cost_iteration_50": clock.cost_at(50),
        "best_cost_iteration_100": clock.cost_at(100),
        "best_cost_iteration_200": clock.cost_at(200),
        "last_improvement_iteration": clock.last_improvement_iteration,
        "iterations_since_last_improvement": (
            None
            if clock.last_improvement_iteration is None
            else int(result.iterations) - clock.last_improvement_iteration
        ),
        "time_to_best_seconds": clock.time_to_best_seconds,
        "total_algorithm_wall_seconds": total_wall,
        "best_solution_fingerprint": result.best.fingerprint,
        "charging_action_count": charging_action_count,
        "contains_charging_actions": charging_action_count > 0,
        "proposal_rows_by_component": json.dumps(proposed, sort_keys=True),
        "accepted_rows_by_component": json.dumps(accepted, sort_keys=True),
        "background_trip_assignment_crossover_calls": int(
            result.accounting.crossover_calls
        ),
        "error_type": result.termination_error_type,
        "error": result.termination_error,
    }
    row.update(_service_fields(result, bundle))
    row.update(_fleet_fields(result, bundle))
    for key, value in sorted(result.best_evaluation.breakdown.items()):
        row[f"breakdown__{key}"] = value
    return row


def _failure_row(
    identity: PairIdentity,
    arm: FactorialArm,
    error: Exception,
) -> dict[str, Any]:
    row = {field: None for field in REQUIRED_RAW_FIELDS}
    row.update(
        {
            "instance_id": identity.instance_id,
            "seed": identity.seed,
            "arm_id": arm.arm_id,
            "component_bitmask": arm.bitmask,
            "enabled_components": json.dumps(
                arm.enabled_components, ensure_ascii=False
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


def _dry_run_payload(args: argparse.Namespace, arms: Sequence[FactorialArm]) -> dict[str, Any]:
    fleet_parameter_class_id = FLEET_PARAMETER_CLASS_IDS[args.fleet_parameters]
    pair_groups = []
    for seed in args.seeds:
        population_sha = hashlib.sha256(
            (
                "COMPONENT_INTERACTION_PLANNED_POPULATION_V1\n"
                f"{args.instance_id}\n{int(seed)}"
            ).encode("utf-8")
        ).hexdigest()
        context_sha = hashlib.sha256(
            (
                "COMPONENT_INTERACTION_PLANNED_CONTEXT_V1\n"
                f"{args.instance_id}\n{fleet_parameter_class_id}"
            ).encode("utf-8")
        ).hexdigest()
        identities = _pair_identities(
            arms,
            instance_id=args.instance_id,
            seed=seed,
            initial_population_sha256=population_sha,
            evaluation_context_sha256=context_sha,
            wall_clock_budget_seconds=args.wall_clock_seconds,
            fleet_parameter_class_id=fleet_parameter_class_id,
        )
        validate_pairing(identities)
        pair_groups.append([asdict(identity) for identity in identities])
    return {
        "mode": "DRY_RUN",
        "solver_entered": False,
        "output_directory_created": False,
        "serial_execution": True,
        "instance_id": args.instance_id,
        "components": list(args.components),
        "factor_count": len(args.components),
        "arm_count": len(arms),
        "seeds": list(args.seeds),
        "wall_clock_budget_seconds_per_arm": args.wall_clock_seconds,
        "fleet_parameter_class_id": fleet_parameter_class_id,
        "output_dir": str(args.output_dir),
        "arms": [
            {
                "arm_id": arm.arm_id,
                "component_bitmask": arm.bitmask,
                "enabled_components": arm.enabled_components,
                "runtime_switches": arm.runtime_switches,
            }
            for arm in arms
        ],
        "pair_validation": "PASSED",
        "pair_fields": PAIR_FIELDS,
        "pair_groups": pair_groups,
        "identity_scope": (
            "planned identities only; a real run recomputes and revalidates "
            "the population and evaluation-context hashes before every arm"
        ),
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", required=True)
    parser.add_argument(
        "--components",
        nargs="+",
        choices=EXECUTABLE_COMPONENTS,
        required=True,
    )
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--wall-clock-seconds", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--arms",
        nargs="+",
        help="optional subset of generated arm IDs, kept in factorial order",
    )
    parser.add_argument(
        "--fleet-parameters",
        choices=tuple(FLEET_PARAMETER_CLASS_IDS),
        default="fixed25",
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
    if len(set(args.components)) != len(args.components):
        parser.error("--components cannot contain duplicates")
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("--seeds cannot contain duplicates")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    arms = build_factorial_arms(args.components)
    if args.arms:
        requested = set(args.arms)
        known = {arm.arm_id for arm in arms}
        unknown = sorted(requested.difference(known))
        if unknown:
            raise ValueError("unknown requested arm IDs: " + ", ".join(unknown))
        arms = tuple(arm for arm in arms if arm.arm_id in requested)
    if args.dry_run:
        print(
            json.dumps(
                _dry_run_payload(args, arms),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        )
        return 0

    from run_public_v2_28_clean_ruler import _prepare_independent_imports

    _prepare_independent_imports()
    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    protected_before = {path: _sha256(repo / path) for path in PROTECTED}

    from run_private_ablation import _prepare_shared_population
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
        identities = _pair_identities(
            arms,
            instance_id=bundle.instance_id,
            seed=seed,
            initial_population_sha256=population_sha256(built.candidates),
            evaluation_context_sha256=DutyFullEvaluator(context).context_sha256,
            wall_clock_budget_seconds=args.wall_clock_seconds,
            fleet_parameter_class_id=bundle.fleet_parameter_class_id,
        )
        validate_pairing(identities)
        pair_groups.append([asdict(identity) for identity in identities])
        by_arm = {identity.arm_id: identity for identity in identities}
        for arm in arms:
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
                    expected_identity=by_arm[arm.arm_id],
                    population_mode=args.population_mode,
                )
            except Exception as error:  # Preserve the exact failed arm.
                row = _failure_row(by_arm[arm.arm_id], arm, error)
            rows.append(row)

    annotate_interactions(rows)
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    if protected_after != protected_before:
        raise RuntimeError("a protected evaluator file changed during the run")
    metadata = {
        "status": (
            "COMPLETED_WITH_FAILURES"
            if any(row.get("run_status") == "FAILED" for row in rows)
            else "COMPLETED"
        ),
        "purpose": "paired full-factorial component interaction measurement",
        "instance_id": bundle.instance_id,
        "components": list(args.components),
        "component_labels": {
            key: COMPONENT_LABELS[key] for key in args.components
        },
        "factor_count": len(args.components),
        "arm_count": len(arms),
        "arms": [asdict(arm) for arm in arms],
        "seeds": list(args.seeds),
        "wall_clock_budget_seconds_per_arm": args.wall_clock_seconds,
        "budget_semantics": "shared initialization plus per-arm setup and search wall clock",
        "effective_population": _effective_population_metadata(
            args.population_mode,
            _parameters(population_mode=args.population_mode).population,
        ),
        "serial_execution": True,
        "pair_validation": "PASSED",
        "pair_fields": PAIR_FIELDS,
        "pair_groups": pair_groups,
        "interaction_formula": "combination_gain - sum(single_component_gains)",
        "gain_direction": "positive means lower cost or lower emissions",
        "significance_rule": None,
        "reported_uncertainty": "paired sample standard deviation and standard error",
        "background_components_held_on": [
            "trip_assignment_crossover",
            "registered_empty_duty_activation",
            "complete_evaluation",
            "single_objective_population",
        ],
        "shared_initialization_scope": (
            "factor switches apply after one common population construction "
            "for each instance/seed pair"
        ),
        "fleet_parameter_class_id": bundle.fleet_parameter_class_id,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "command_argv": list(sys.argv if argv is None else argv),
    }
    write_result_package(output, rows, metadata, args.components)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
