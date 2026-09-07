"""Typed search outcomes and transparent accounting.

v1 2026-08-07: separate candidate construction failures, complete-model
rejections, accepted moves, evaluation kinds, and wall-clock observation.
These are records, not scientific gates.

v2 2026-08-07: record genuine no-op actions separately from interface failures.

v3 2026-08-07: disclose cache construction and candidate assembly work instead
of allowing an "incremental" label to hide full preparation overhead.

v4 2026-08-10: aggregate the observed effect of each accepted serial action on
complete cost, carbon cost, emissions, EV assignment, and participation margin.
These are causal diagnostics of executed moves, not extra objectives or gates.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .model import DutyIndividual

if TYPE_CHECKING:
    from .evaluation import FullEvaluation


class CandidateStatus(StrEnum):
    EVALUATED = "EVALUATED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED_INTERFACE = "REJECTED_INTERFACE"
    REJECTED_CHARGING = "REJECTED_CHARGING"
    REJECTED_LOCK = "REJECTED_LOCK"
    REJECTED_REGISTRY = "REJECTED_REGISTRY"
    REPAIR_INCOMPLETE = "REPAIR_INCOMPLETE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NO_FEASIBLE_SOLUTION = "NO_FEASIBLE_SOLUTION"


class ChargingCandidateStatus(StrEnum):
    """Charging-subproblem state, separate from complete feasibility."""

    READY = "READY"
    REJECTED_INTERFACE = "REJECTED_INTERFACE"
    REJECTED_CHARGING = "REJECTED_CHARGING"


@dataclass(frozen=True)
class ChargingRepairOutcome:
    """Typed repair return that never fabricates an unsafe candidate."""

    status: ChargingCandidateStatus
    candidate: DutyIndividual | None
    reason_code: str | None = None
    affected_duty_ids: tuple[str, ...] = ()
    error: Exception | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        status = ChargingCandidateStatus(self.status)
        affected = tuple(sorted(str(value) for value in self.affected_duty_ids))
        if status == ChargingCandidateStatus.READY:
            if self.candidate is None:
                raise ValueError("READY requires a candidate")
        elif self.candidate is not None:
            raise ValueError("a rejected charging outcome cannot carry a candidate")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "affected_duty_ids", affected)

    @property
    def fingerprint(self) -> str | None:
        return None if self.candidate is None else self.candidate.fingerprint


@dataclass(frozen=True)
class CandidateOutcome:
    action_id: str
    channel: str
    status: CandidateStatus
    changed_duty_ids: frozenset[str]
    candidate: DutyIndividual | None = None
    evaluation: FullEvaluation | None = None
    error_type: str | None = None
    error: str | None = None
    charging_rejection_reason: str | None = None
    wall_seconds: float = 0.0
    work_accounting: Mapping[str, int] = field(default_factory=dict)
    charging_candidate_status: ChargingCandidateStatus | None = None

    def __post_init__(self) -> None:
        evaluation = self.evaluation
        status = self.charging_candidate_status
        if evaluation is not None:
            status = status or getattr(
                evaluation,
                "charging_candidate_status",
                None,
            )
        if status is not None:
            status = ChargingCandidateStatus(status)
        object.__setattr__(self, "charging_candidate_status", status)

    @property
    def evaluated(self) -> bool:
        return self.status == CandidateStatus.EVALUATED

    @property
    def no_change(self) -> bool:
        return self.status == CandidateStatus.NO_CHANGE


@dataclass
class SearchAccounting:
    """Counts observed work without declaring any result successful."""

    proposed_actions: Counter[str] = field(default_factory=Counter)
    evaluated_actions: Counter[str] = field(default_factory=Counter)
    accepted_actions: Counter[str] = field(default_factory=Counter)
    accepted_cost_reduction: Counter[str] = field(default_factory=Counter)
    accepted_carbon_cost_reduction: Counter[str] = field(default_factory=Counter)
    accepted_emissions_reduction: Counter[str] = field(default_factory=Counter)
    accepted_ev_customer_delta: Counter[str] = field(default_factory=Counter)
    accepted_minimum_margin_delta: Counter[str] = field(default_factory=Counter)
    rejected_actions: Counter[str] = field(default_factory=Counter)
    charging_rejection_reasons: Counter[str] = field(default_factory=Counter)
    charging_candidate_statuses: Counter[str] = field(default_factory=Counter)
    no_change_actions: Counter[str] = field(default_factory=Counter)
    full_evaluations: int = 0
    initialization_full_evaluations: int = 0
    incremental_evaluations: int = 0
    cache_seedings: int = 0
    duty_slice_preparations: int = 0
    candidate_assemblies: int = 0
    crossover_calls: int = 0
    crossover_actions: Counter[str] = field(default_factory=Counter)
    crossover_work_units: Counter[str] = field(default_factory=Counter)
    repair_calls: int = 0
    outer_refinement_calls: int = 0
    education_rounds: int = 0
    education_depth_cap_triggers: int = 0
    education_depth_cap_triggers_while_improving: int = 0
    education_cache_hits: int = 0
    education_cache_misses: int = 0
    charging_repair_cache_hits: int = 0
    charging_repair_cache_misses: int = 0
    population_admission_attempts: int = 0
    population_admissions: int = 0
    # 历史误名＝rounds：kernel_native 路径下这个数是外层轮数，不是遗传算法
    # 的内部重启次数（内核以 num_iters_no_improvement=10**9 构建，从不重启）。
    # 名字保留给已有的下游读者，同一个数另以 ``rounds`` 发布。
    restarts: int = 0
    # 外层轮数的诚实命名。只有 kernel_native 路径赋值，其余路径保持 0。
    rounds: int = 0
    # 下面四项只由 kernel_native 路径记录（2026-09-05 新增）。
    # ``None``／空列表一律读作"这条路径没有记录"，不是"记录下来的值为假／为空"：
    # 整合路径（run_integrated_problem_hgs）确实采用外层 stop 回调的返回值，
    # 若把默认值写成 False，就等于替它作了一个它从未作过的断言。
    stop_semantics_actual: str | None = None
    outer_stop_callback_effective: bool | None = None
    # 内核每次刷新轮内最优时的一条记录：{round, iteration, kernel_best_cost}。
    improvement_events: list[dict[str, float | int]] = field(default_factory=list)
    # 每个外层轮一条：{round, iterations, runtime_seconds, improvements,
    # kernel_best_cost}；该轮内核最优若始终是不可行哨兵，最后一项为 None。
    kernel_round_summaries: list[dict[str, float | int | None]] = field(
        default_factory=list
    )
    # Reload-gap proxy (fleet-composition experiment): the between-trip
    # charging seconds the kernel reserved in each search round.
    reload_gap_seconds_by_round: list[float] = field(default_factory=list)
    # 每个外层轮一条（2026-09-05 新增，只有 kernel_native 路径记录）：投影进
    # 内核的种子数，以及其中被内核判为不可行的份数。计数在随机补员之前，
    # 所以它说的是"上一轮的精确解在本轮模型里还站不站得住"，不掺随机个体。
    kernel_seed_infeasible_by_round: list[int] = field(default_factory=list)
    kernel_seed_count_by_round: list[int] = field(default_factory=list)
    # 每个外层轮一条（2026-09-05 新增，只有 kernel_native 路径记录）：这一轮
    # 实际交给内核 NoImprovement 的耐心值。第 1 轮恒为 stagnation_patience；
    # 后续轮在 ``adaptive`` 模式下由本次跑自己的改善间隔标定。
    round_patience_by_round: list[int] = field(default_factory=list)
    # "fixed"＝每轮都用 stagnation_patience（2026-09-05 前的历史行为）；
    # "adaptive"＝后续轮按实测改善间隔定。None＝这条搜索路径没有记录。
    round_patience_mode: str | None = None
    # 第 1 轮里相邻两次内核改善之间等得最久的那一段，按内核圈数计；后续轮耐心
    # 值的标定量。None＝没有记录；0 是合法值（该轮只有播种那一个事件）。
    round1_max_improvement_gap: int | None = None
    # 每个外层轮一条（2026-09-05 新增，只有 kernel_native 路径记录）：这一轮
    # 有没有把精确最优往下压。停机规则读的就是这串标记的尾巴。
    round_improved_by_round: list[bool] = field(default_factory=list)
    # 每被推迟一次记一个轮号（2026-09-05 新增，只有 kernel_native 路径记录）：
    # 该轮结束时精确最优不用电，但到那时为止还没有任何一轮压过见证解，于是
    # "不用电"这个提前出口没有生效。空列表＝从未推迟（绝大多数跑）。
    no_electricity_exit_deferred_rounds: list[int] = field(default_factory=list)
    # 连续多少轮无改善才停（2026-09-05 新增）。1＝2026-09-05 之前的"任一轮无
    # 改善即停"。None＝这条搜索路径没有记录（整合路径没有外层轮）。
    stop_after_nonimproving_rounds: int | None = None
    # 外层轮数硬上限。None＝没有记录。改动前确认轮分支根本没有上限。
    max_outer_rounds: int | None = None
    # 第 1 轮独立起跑几次（2026-09-08 新增，只有 kernel_native 路径记录）。
    # 1＝2026-09-08 之前的行为：一次运算只有一个起点。None＝没有记录。
    round_one_starts: int | None = None
    # 第 1 轮每个起点一条：{start, iterations, runtime_seconds, improvements,
    # kernel_best_cost, selected}。``kernel_best_cost`` 是内核自己的代理最优
    # （轮内可行最优，单位 1/100 000 元），也是起点之间取优所用的判据——它每
    # 轮本来就在记，按它选起点不额外付一次完整精确评价。起点数为 1 时这个列表
    # 仍然记一条，读者不必分两种情形处理。
    round_one_start_summaries: list[dict[str, float | int | bool | None]] = field(
        default_factory=list
    )
    # 两个路由代理锚点被冻结成的值（2026-09-08 新增）。None＝没有冻结，即按
    # 原行为每轮重估／每跑各估各的。冻结时这两个数在整次运算的每一轮相同，
    # 也在同一批的每一次运算之间相同。
    frozen_reload_gap_seconds: float | None = None
    frozen_first_trip_window_open_second: float | None = None
    wall_seconds: float = 0.0
    run_wall_seconds: float = 0.0
    initialization_wall_seconds: float = 0.0
    schedule_oracle_calls: int = 0
    schedule_oracle_cache_hits: int = 0
    schedule_oracle_cache_misses: int = 0
    schedule_oracle_statuses: Counter[str] = field(default_factory=Counter)
    schedule_oracle_failure_reasons: Counter[str] = field(default_factory=Counter)
    schedule_oracle_wall_seconds_samples: list[float] = field(default_factory=list)
    schedule_oracle_cache_hit_wall_seconds_samples: list[float] = field(default_factory=list)
    schedule_oracle_cache_miss_wall_seconds_samples: list[float] = field(default_factory=list)
    schedule_oracle_event_counts: list[int] = field(default_factory=list)
    schedule_oracle_labels_generated: int = 0
    schedule_oracle_labels_pruned: int = 0
    schedule_oracle_slot_pricing_calls: int = 0
    schedule_oracle_curve_transitions: int = 0
    schedule_oracle_pricing_mismatches: int = 0
    schedule_oracle_frontier_sizes: list[int] = field(default_factory=list)
    schedule_oracle_frontier_cache_bytes: int = 0
    scheduled_changed_duty_counts: Counter[int] = field(default_factory=Counter)
    schedule_coordinator_calls: int = 0
    schedule_coordinator_cache_hits: int = 0
    schedule_coordinator_cache_misses: int = 0
    schedule_coordinator_combinations_attempted: int = 0
    schedule_coordinator_capacity_prunes: int = 0
    schedule_coordinator_full_candidates: int = 0
    schedule_coordinator_statuses: Counter[str] = field(default_factory=Counter)
    schedule_coordinator_wall_seconds_samples: list[float] = field(default_factory=list)
    schedule_rescued_candidates_by_channel: Counter[str] = field(default_factory=Counter)
    schedule_rejected_candidates_by_channel_and_status: Counter[str] = field(default_factory=Counter)
    penalty_manager: Any | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def record_outcome(self, outcome: CandidateOutcome) -> None:
        self.proposed_actions[outcome.channel] += 1
        self.wall_seconds += float(outcome.wall_seconds)
        self._record_work(outcome.work_accounting)
        if outcome.charging_candidate_status is not None:
            self.charging_candidate_statuses[
                outcome.charging_candidate_status.value
            ] += 1
        if outcome.evaluated:
            self.evaluated_actions[outcome.channel] += 1
            if outcome.evaluation is not None:
                self._record_work(outcome.evaluation.accounting)
        elif outcome.no_change:
            self.no_change_actions[outcome.channel] += 1
        else:
            self.rejected_actions[
                f"{outcome.channel}:{outcome.status.value}"
            ] += 1
            if outcome.status == CandidateStatus.REJECTED_CHARGING:
                reason = (
                    "CHARGING_REPAIR_OTHER"
                    if outcome.charging_rejection_reason is None
                    else str(outcome.charging_rejection_reason)
                )
                self.charging_rejection_reasons[
                    f"{outcome.channel}:{reason}"
                ] += 1

    def record_acceptance(self, channel: str) -> None:
        self.accepted_actions[channel] += 1

    def record_accepted_effect(
        self,
        channel: str,
        before: DutyIndividual,
        before_evaluation: FullEvaluation,
        after: DutyIndividual,
        after_evaluation: FullEvaluation,
    ) -> None:
        """Summarise what one accepted action actually changed."""

        self.accepted_cost_reduction[channel] += float(
            before_evaluation.total_cost
        ) - float(after_evaluation.total_cost)
        self._record_breakdown_reduction(
            self.accepted_carbon_cost_reduction,
            channel,
            before_evaluation,
            after_evaluation,
            "cost_carbon",
        )
        self._record_breakdown_reduction(
            self.accepted_emissions_reduction,
            channel,
            before_evaluation,
            after_evaluation,
            "E_total",
        )
        self.accepted_ev_customer_delta[channel] += (
            _ev_customer_count(after) - _ev_customer_count(before)
        )
        if (
            before_evaluation.participation_margin
            and after_evaluation.participation_margin
        ):
            self.accepted_minimum_margin_delta[channel] += (
                min(
                    float(value)
                    for value in after_evaluation.participation_margin.values()
                )
                - min(
                    float(value)
                    for value in before_evaluation.participation_margin.values()
                )
            )

    @staticmethod
    def _record_breakdown_reduction(
        target: Counter[str],
        channel: str,
        before: FullEvaluation,
        after: FullEvaluation,
        key: str,
    ) -> None:
        if key in before.breakdown and key in after.breakdown:
            target[channel] += float(before.breakdown[key]) - float(
                after.breakdown[key]
            )

    def record_cache_seed(self, duty_slice_count: int) -> None:
        count = int(duty_slice_count)
        if count > 0:
            self.cache_seedings += 1
            self.duty_slice_preparations += count

    def record_education_depth_cap(self, *, still_improving: bool) -> None:
        """Record that a child stopped because its education cap was reached."""

        self.education_depth_cap_triggers += 1
        if still_improving:
            self.education_depth_cap_triggers_while_improving += 1

    def record_population_admission(self, *, inserted: bool) -> None:
        """Record retention without recounting the candidate's evaluation work."""

        self.population_admission_attempts += 1
        if inserted:
            self.population_admissions += 1
            self.record_acceptance("hgs_population")

    def record_schedule_oracle_result(self, result: Any) -> None:
        """Merge one prototype Oracle call without turning it into a gate."""

        self.schedule_oracle_calls += 1
        elapsed = float(result.wall_seconds)
        self.schedule_oracle_wall_seconds_samples.append(elapsed)
        if bool(result.cache_hit):
            self.schedule_oracle_cache_hits += 1
            self.schedule_oracle_cache_hit_wall_seconds_samples.append(elapsed)
        else:
            self.schedule_oracle_cache_misses += 1
            self.schedule_oracle_cache_miss_wall_seconds_samples.append(elapsed)
        status = str(getattr(result.status, "value", result.status))
        self.schedule_oracle_statuses[status] += 1
        if result.failure_reason:
            self.schedule_oracle_failure_reasons[str(result.failure_reason)] += 1
        accounting = dict(result.accounting)
        self.schedule_oracle_event_counts.append(
            int(accounting.get("schedule_oracle_event_count", 0))
        )
        self.schedule_oracle_labels_generated += int(
            accounting.get("schedule_oracle_labels_generated", 0)
        )
        self.schedule_oracle_labels_pruned += int(
            accounting.get("schedule_oracle_labels_pruned", 0)
        )
        self.schedule_oracle_slot_pricing_calls += int(
            accounting.get("schedule_oracle_slot_pricing_calls", 0)
        )
        self.schedule_oracle_curve_transitions += int(
            accounting.get("schedule_oracle_curve_transitions", 0)
        )
        self.schedule_oracle_pricing_mismatches += int(
            accounting.get("schedule_oracle_pricing_mismatches", 0)
        )
        self.schedule_oracle_frontier_sizes.append(len(result.frontier))

    def record_schedule_coordinator_result(
        self,
        result: Any,
        *,
        changed_duty_count: int,
    ) -> None:
        self.schedule_coordinator_calls += 1
        self.schedule_coordinator_wall_seconds_samples.append(
            float(result.wall_seconds)
        )
        self.scheduled_changed_duty_counts[int(changed_duty_count)] += 1
        status = str(getattr(result.status, "value", result.status))
        self.schedule_coordinator_statuses[status] += 1
        accounting = dict(result.accounting)
        self.schedule_coordinator_combinations_attempted += int(
            accounting.get("schedule_coordinator_combinations_attempted", 0)
        )
        self.schedule_coordinator_capacity_prunes += int(
            accounting.get("schedule_coordinator_capacity_prunes", 0)
        )
        self.schedule_coordinator_full_candidates += int(
            accounting.get("schedule_coordinator_full_candidates", 0)
        )

    def record_crossover(self, action: str, work_units: int) -> None:
        work = int(work_units)
        if work < 1:
            raise ValueError("crossover work units must be positive")
        self.crossover_actions[str(action)] += 1
        self.crossover_work_units[str(action)] += work

    def _record_work(self, accounting: Mapping[str, int]) -> None:
        self.full_evaluations += int(accounting.get("full_evaluations", 0))
        self.incremental_evaluations += int(
            accounting.get("incremental_evaluations", 0)
        )
        self.cache_seedings += int(accounting.get("cache_seedings", 0))
        self.duty_slice_preparations += int(
            accounting.get("duty_slice_preparations", 0)
        )
        self.candidate_assemblies += int(
            accounting.get("candidate_assemblies", 0)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposed_actions": dict(sorted(self.proposed_actions.items())),
            "evaluated_actions": dict(sorted(self.evaluated_actions.items())),
            "accepted_actions": dict(sorted(self.accepted_actions.items())),
            "accepted_cost_reduction": dict(
                sorted(self.accepted_cost_reduction.items())
            ),
            "accepted_carbon_cost_reduction": dict(
                sorted(self.accepted_carbon_cost_reduction.items())
            ),
            "accepted_emissions_reduction": dict(
                sorted(self.accepted_emissions_reduction.items())
            ),
            "accepted_ev_customer_delta": dict(
                sorted(self.accepted_ev_customer_delta.items())
            ),
            "accepted_minimum_margin_delta": dict(
                sorted(self.accepted_minimum_margin_delta.items())
            ),
            "rejected_actions": dict(sorted(self.rejected_actions.items())),
            "charging_rejection_reasons": dict(
                sorted(self.charging_rejection_reasons.items())
            ),
            "charging_candidate_statuses": dict(
                sorted(self.charging_candidate_statuses.items())
            ),
            "no_change_actions": dict(sorted(self.no_change_actions.items())),
            "full_evaluations": int(self.full_evaluations),
            "initialization_full_evaluations": int(
                self.initialization_full_evaluations
            ),
            "incremental_evaluations": int(self.incremental_evaluations),
            "cache_seedings": int(self.cache_seedings),
            "duty_slice_preparations": int(
                self.duty_slice_preparations
            ),
            "candidate_assemblies": int(self.candidate_assemblies),
            "crossover_calls": int(self.crossover_calls),
            "crossover_actions": dict(sorted(self.crossover_actions.items())),
            "crossover_work_units": dict(
                sorted(self.crossover_work_units.items())
            ),
            "repair_calls": int(self.repair_calls),
            "outer_refinement_calls": int(self.outer_refinement_calls),
            "education_rounds": int(self.education_rounds),
            "education_depth_cap_triggers": int(
                self.education_depth_cap_triggers
            ),
            "education_depth_cap_triggers_while_improving": int(
                self.education_depth_cap_triggers_while_improving
            ),
            "education_cache_hits": int(self.education_cache_hits),
            "education_cache_misses": int(self.education_cache_misses),
            "charging_repair_cache_hits": int(
                self.charging_repair_cache_hits
            ),
            "charging_repair_cache_misses": int(
                self.charging_repair_cache_misses
            ),
            "population_admission_attempts": int(
                self.population_admission_attempts
            ),
            "population_admissions": int(self.population_admissions),
            "restarts": int(self.restarts),
            "rounds": int(self.rounds),
            "stop_semantics_actual": (
                None
                if self.stop_semantics_actual is None
                else str(self.stop_semantics_actual)
            ),
            "outer_stop_callback_effective": (
                None
                if self.outer_stop_callback_effective is None
                else bool(self.outer_stop_callback_effective)
            ),
            "improvement_events": [
                {
                    "round": int(event["round"]),
                    "iteration": int(event["iteration"]),
                    "kernel_best_cost": float(event["kernel_best_cost"]),
                }
                for event in self.improvement_events
            ],
            "kernel_round_summaries": [
                {
                    "round": int(summary["round"]),
                    "iterations": int(summary["iterations"]),
                    "runtime_seconds": float(summary["runtime_seconds"]),
                    "improvements": int(summary["improvements"]),
                    # 该轮内核最优始终停在不可行哨兵时没有代价可报。
                    "kernel_best_cost": (
                        None
                        if summary["kernel_best_cost"] is None
                        else float(summary["kernel_best_cost"])
                    ),
                }
                for summary in self.kernel_round_summaries
            ],
            "reload_gap_seconds_by_round": [
                float(gap) for gap in self.reload_gap_seconds_by_round
            ],
            "kernel_seed_infeasible_by_round": [
                int(count) for count in self.kernel_seed_infeasible_by_round
            ],
            "kernel_seed_count_by_round": [
                int(count) for count in self.kernel_seed_count_by_round
            ],
            "round_patience_by_round": [
                int(value) for value in self.round_patience_by_round
            ],
            "round_patience_mode": (
                None
                if self.round_patience_mode is None
                else str(self.round_patience_mode)
            ),
            "round1_max_improvement_gap": (
                None
                if self.round1_max_improvement_gap is None
                else int(self.round1_max_improvement_gap)
            ),
            "round_improved_by_round": [
                bool(flag) for flag in self.round_improved_by_round
            ],
            "no_electricity_exit_deferred_rounds": [
                int(index) for index in self.no_electricity_exit_deferred_rounds
            ],
            "stop_after_nonimproving_rounds": (
                None
                if self.stop_after_nonimproving_rounds is None
                else int(self.stop_after_nonimproving_rounds)
            ),
            "max_outer_rounds": (
                None
                if self.max_outer_rounds is None
                else int(self.max_outer_rounds)
            ),
            "round_one_starts": (
                None
                if self.round_one_starts is None
                else int(self.round_one_starts)
            ),
            "round_one_start_summaries": [
                {
                    "start": int(summary["start"]),
                    "iterations": int(summary["iterations"]),
                    "runtime_seconds": float(summary["runtime_seconds"]),
                    "improvements": int(summary["improvements"]),
                    "kernel_best_cost": (
                        None
                        if summary["kernel_best_cost"] is None
                        else float(summary["kernel_best_cost"])
                    ),
                    "selected": bool(summary["selected"]),
                }
                for summary in self.round_one_start_summaries
            ],
            "frozen_reload_gap_seconds": (
                None
                if self.frozen_reload_gap_seconds is None
                else float(self.frozen_reload_gap_seconds)
            ),
            "frozen_first_trip_window_open_second": (
                None
                if self.frozen_first_trip_window_open_second is None
                else float(self.frozen_first_trip_window_open_second)
            ),
            "wall_seconds": float(self.wall_seconds),
            "run_wall_seconds": float(self.run_wall_seconds),
            "initialization_wall_seconds": float(
                self.initialization_wall_seconds
            ),
            "total_algorithm_wall_seconds": float(
                self.initialization_wall_seconds + self.run_wall_seconds
            ),
            "schedule_oracle_calls": int(self.schedule_oracle_calls),
            "schedule_oracle_cache_hits": int(self.schedule_oracle_cache_hits),
            "schedule_oracle_cache_misses": int(self.schedule_oracle_cache_misses),
            "schedule_oracle_statuses": dict(sorted(self.schedule_oracle_statuses.items())),
            "schedule_oracle_failure_reasons": dict(
                sorted(self.schedule_oracle_failure_reasons.items())
            ),
            "schedule_oracle_wall_seconds": _sample_summary(
                self.schedule_oracle_wall_seconds_samples
            ),
            "schedule_oracle_cache_hit_wall_seconds": _sample_summary(
                self.schedule_oracle_cache_hit_wall_seconds_samples
            ),
            "schedule_oracle_cache_miss_wall_seconds": _sample_summary(
                self.schedule_oracle_cache_miss_wall_seconds_samples
            ),
            "schedule_oracle_event_counts": _sample_summary(
                self.schedule_oracle_event_counts
            ),
            "schedule_oracle_labels_generated": int(
                self.schedule_oracle_labels_generated
            ),
            "schedule_oracle_labels_pruned": int(
                self.schedule_oracle_labels_pruned
            ),
            "schedule_oracle_slot_pricing_calls": int(
                self.schedule_oracle_slot_pricing_calls
            ),
            "schedule_oracle_curve_transitions": int(
                self.schedule_oracle_curve_transitions
            ),
            "schedule_oracle_pricing_mismatches": int(
                self.schedule_oracle_pricing_mismatches
            ),
            "schedule_oracle_frontier_sizes": _sample_summary(
                self.schedule_oracle_frontier_sizes
            ),
            "schedule_oracle_frontier_cache_bytes": int(
                self.schedule_oracle_frontier_cache_bytes
            ),
            "scheduled_changed_duty_counts": {
                str(key): int(value)
                for key, value in sorted(self.scheduled_changed_duty_counts.items())
            },
            "schedule_coordinator_calls": int(self.schedule_coordinator_calls),
            "schedule_coordinator_cache_hits": int(
                self.schedule_coordinator_cache_hits
            ),
            "schedule_coordinator_cache_misses": int(
                self.schedule_coordinator_cache_misses
            ),
            "schedule_coordinator_combinations_attempted": int(
                self.schedule_coordinator_combinations_attempted
            ),
            "schedule_coordinator_capacity_prunes": int(
                self.schedule_coordinator_capacity_prunes
            ),
            "schedule_coordinator_full_candidates": int(
                self.schedule_coordinator_full_candidates
            ),
            "schedule_coordinator_statuses": dict(
                sorted(self.schedule_coordinator_statuses.items())
            ),
            "schedule_coordinator_wall_seconds": _sample_summary(
                self.schedule_coordinator_wall_seconds_samples
            ),
            "schedule_rescued_candidates_by_channel": dict(
                sorted(self.schedule_rescued_candidates_by_channel.items())
            ),
            "schedule_rejected_candidates_by_channel_and_status": dict(
                sorted(
                    self.schedule_rejected_candidates_by_channel_and_status.items()
                )
            ),
        }


def _sample_summary(values: list[float] | list[int]) -> dict[str, float | int | None]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {
            "samples": 0,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        }

    def percentile(probability: float) -> float:
        index = int(math.ceil(probability * len(ordered))) - 1
        return ordered[max(0, min(len(ordered) - 1, index))]

    return {
        "samples": len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


def _ev_customer_count(individual: DutyIndividual) -> int:
    return sum(
        len(trip.customer_ids)
        for duty in individual.duties
        if duty.vehicle_type == "ev"
        for trip in duty.trips
    )


@dataclass(frozen=True)
class TrajectoryRow:
    iteration: int
    phase: str
    arm: str
    action_id: str
    channel: str
    status: str
    accepted: bool
    before_fingerprint: str
    after_fingerprint: str | None
    before_cost: float | None
    after_cost: float | None
    before_violations: int | None
    after_violations: int | None
    before_carbon_cost: float | None
    after_carbon_cost: float | None
    before_emissions_kg: float | None
    after_emissions_kg: float | None
    participation_margin_before: tuple[tuple[str, float], ...]
    participation_margin_after: tuple[tuple[str, float], ...] | None
    minimum_participation_margin_before: float | None
    minimum_participation_margin_after: float | None
    error_type: str | None = None
    error: str | None = None
