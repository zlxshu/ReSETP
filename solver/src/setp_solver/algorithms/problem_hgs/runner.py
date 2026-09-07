"""Runnable isolated Problem-HGS search.

v1 2026-08-07: join the independently implemented HGS population/control
backbone with the prototype duty exchange, regret repair, charging-safe
best-improvement education, and transparent trajectory accounting.
The caller supplies every numerical parameter and the stopping policy.

v2 2026-08-07: reuse the repair phase's verified evaluation when education
starts, so the same child is not fully evaluated twice without disclosure.

v3 2026-08-07: pass the whole-duty EV/CV exchange switch unchanged into
education for paired ablation.

"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import perf_counter

from setp_solver.check import PROFIT_FAIRNESS

from .charging import ChargingRepairPolicy
from .contracts import (
    CandidateStatus,
    SearchAccounting,
    TrajectoryRow,
)
from .evaluation import DutyFullEvaluator, FullEvaluation
from .execution_settings import ExecutionSettings
from .integrated_private import build_integrated_private_hgs
from .kernel_proposals import (
    RELOAD_GAP_QUANTILE,
    IndependentKernelDutyRouteProposalEngine,
    inter_trip_reload_seconds,
)
from .model import DutyIndividual
from .population import (
    PopulationParameters,
)


SINGLE_OBJECTIVE = "single_objective"


@dataclass(frozen=True)
class ProblemHGSSearchParameters:
    population: PopulationParameters
    stagnation_patience: int = 20_000
    include_whole_duty_type_exchange: bool = True
    objective_mode: str = SINGLE_OBJECTIVE
    education_depth_limit: int | None = None

    def __post_init__(self) -> None:
        if self.stagnation_patience < 1:
            raise ValueError("stagnation patience must be positive")
        if self.education_depth_limit is not None and self.education_depth_limit < 1:
            raise ValueError("education depth limit must be positive")
        if self.objective_mode != SINGLE_OBJECTIVE:
            raise ValueError("only single-objective population mode is supported")


@dataclass(frozen=True)
class PrivateAblationTreatment:
    """The only component switches allowed to differ inside one paired run."""

    schedule_all_changed_move_evaluation: bool = False
    fleet_activation_enabled: bool = False

    def __post_init__(self) -> None:
        if self.fleet_activation_enabled and not (
            self.schedule_all_changed_move_evaluation
        ):
            raise ValueError("endogenous fleet treatment requires all-move DSS")


@dataclass(frozen=True)
class ProblemHGSSearchState:
    iterations: int
    iterations_without_improvement: int
    best_cost: float | None
    elapsed_seconds: float
    full_evaluations: int
    incremental_evaluations: int
    duty_slice_preparations: int
    candidate_assemblies: int
    has_feasible: bool = False
    best_feasible_raw_cost: float | None = None
    current_solution_raw_cost: float | None = None
    current_solution_penalized_cost: float | None = None
    physical_feasible: bool | None = None
    fairness_feasible: bool | None = None
    violation_counts: tuple[tuple[str, int], ...] = ()
    violation_magnitudes: tuple[tuple[str, float], ...] = ()
    outer_repair_calls: int = 0
    outer_refinement_calls: int = 0


@dataclass(frozen=True)
class ProblemHGSRunResult:
    best: DutyIndividual
    best_evaluation: FullEvaluation
    iterations: int
    accounting: SearchAccounting
    trajectory: tuple[TrajectoryRow, ...]
    effective_execution: ExecutionSettings
    termination_status: str
    termination_error_type: str | None = None
    termination_error: str | None = None
    objective_mode: str = SINGLE_OBJECTIVE
    charging_prescreen_accounting: dict[str, object] | None = None

class _TrajectoryRecorder:
    """Optionally stream trajectory batches without retaining the full run."""

    def __init__(
        self,
        sink: Callable[[tuple[TrajectoryRow, ...]], None] | None,
        *,
        retain: bool,
    ) -> None:
        self._sink = sink
        self._retain = bool(retain)
        self.retained: list[TrajectoryRow] = []

    def emit(self, row: TrajectoryRow) -> None:
        self.emit_many((row,))

    def emit_many(self, rows) -> None:
        batch = tuple(rows)
        if not batch:
            return
        if self._sink is not None:
            self._sink(batch)
        if self._retain:
            self.retained.extend(batch)


def _record_integrated_population_admissions(
    population,
    accounting: SearchAccounting,
    *,
    initial_candidate_count: int,
) -> None:
    """Count the standard population's existing admissions without changing it."""

    original_add = population.add
    initial_additions_remaining = int(initial_candidate_count)

    def add(candidate):
        nonlocal initial_additions_remaining
        retained = original_add(candidate)
        if initial_additions_remaining > 0:
            initial_additions_remaining -= 1
        else:
            accounting.record_population_admission(inserted=bool(retained))
        return retained

    population.add = add


def run_integrated_problem_hgs(
    initial_candidates: tuple[DutyIndividual, ...],
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    parameters: ProblemHGSSearchParameters,
    stop: Callable[[ProblemHGSSearchState], bool],
    arm: str,
    route_engine: IndependentKernelDutyRouteProposalEngine,
    trajectory_sink: Callable[[tuple[TrajectoryRow, ...]], None] | None = None,
    retain_trajectory: bool = True,
    initial_evaluations: tuple[FullEvaluation, ...] | None = None,
    initialization_full_evaluation_count: int | None = None,
    initialization_wall_seconds: float = 0.0,
    treatment: PrivateAblationTreatment | None = None,
    charging_prescreen_enabled: bool = False,
    cross_depot_enabled: bool = True,
    multi_trip_enabled: bool = True,
    type_exchange_enabled: bool = True,
    include_mechanism_refinement: bool = True,
    include_charging_candidates: bool = True,
    lazy_exact_evaluation: bool = False,
) -> ProblemHGSRunResult:
    """Run the common HGS control flow over complete Duty candidates."""

    started = perf_counter()
    if not initial_candidates:
        raise ValueError("Problem-HGS requires at least one initial candidate")
    if any(candidate.unserved_customers for candidate in initial_candidates):
        raise ValueError(
            "integrated Problem-HGS cannot seed incomplete customer service"
        )
    if float(initialization_wall_seconds) < 0.0:
        raise ValueError("initialization wall time cannot be negative")
    if initial_evaluations is None:
        initial_evaluations = tuple(
            evaluator.evaluate(candidate) for candidate in initial_candidates
        )
        initialization_full_evaluation_count = len(initial_evaluations)
    elif initialization_full_evaluation_count is None:
        initialization_full_evaluation_count = len(initial_evaluations)

    trajectory_enabled = trajectory_sink is not None or retain_trajectory
    trajectory = _TrajectoryRecorder(
        trajectory_sink,
        retain=retain_trajectory,
    )
    full_calls_before = evaluator.full_calls
    iterations = 0
    no_improvement = 0
    previous_best: float | None = None
    accounting: SearchAccounting | None = None
    bundle = None

    def current_state() -> ProblemHGSSearchState:
        live = accounting or SearchAccounting()
        exact = (
            None
            if bundle is None or bundle.algorithm.best_so_far is None
            else bundle.algorithm.best_so_far.evaluation.full
        )
        counts: Counter[str] = Counter()
        magnitudes: Counter[str] = Counter()
        if exact is not None:
            for violation, magnitude, axis in zip(
                exact.violations,
                exact.violation_magnitudes,
                exact.violation_axes,
                strict=True,
            ):
                counts[violation.type] += 1
                magnitudes[axis] += float(magnitude)
        has_feasible = bool(exact is not None and exact.feasible)
        best_feasible_raw_cost = (
            float(exact.total_cost) if has_feasible else None
        )
        penalty_manager = live.penalty_manager
        full_evaluations = int(initialization_full_evaluation_count) + (
            evaluator.full_calls - full_calls_before
        )
        return ProblemHGSSearchState(
            iterations=iterations,
            iterations_without_improvement=no_improvement,
            best_cost=best_feasible_raw_cost,
            elapsed_seconds=(
                float(initialization_wall_seconds) + perf_counter() - started
            ),
            full_evaluations=full_evaluations,
            incremental_evaluations=live.incremental_evaluations,
            duty_slice_preparations=live.duty_slice_preparations,
            candidate_assemblies=live.candidate_assemblies,
            has_feasible=has_feasible,
            best_feasible_raw_cost=best_feasible_raw_cost,
            current_solution_raw_cost=(
                None if exact is None else float(exact.total_cost)
            ),
            current_solution_penalized_cost=(
                None
                if exact is None or penalty_manager is None
                else float(penalty_manager.cost(exact))
            ),
            physical_feasible=(
                None
                if exact is None
                else not any(
                    item.type != PROFIT_FAIRNESS
                    for item in exact.violations
                )
            ),
            fairness_feasible=(
                None
                if exact is None
                else not any(
                    item.type == PROFIT_FAIRNESS
                    for item in exact.violations
                )
            ),
            violation_counts=tuple(sorted(counts.items())),
            violation_magnitudes=tuple(sorted(magnitudes.items())),
            outer_repair_calls=(
                0 if bundle is None else bundle.accounting.repair_calls
            ),
            outer_refinement_calls=(
                0 if bundle is None else bundle.accounting.mechanism_calls
            ),
        )

    class _IntegratedStop:
        def __init__(self) -> None:
            self._iteration_was_started = False

        def __call__(self, best_cost: float) -> bool:
            nonlocal iterations, no_improvement, previous_best
            if self._iteration_was_started:
                iterations += 1
            current = float(best_cost)
            if previous_best is not None:
                no_improvement = (
                    0 if current < previous_best else no_improvement + 1
                )
            previous_best = current
            if stop(current_state()):
                return True
            self._iteration_was_started = True
            return False

    _stop_memo: dict[tuple[int, int], bool] = {}

    def _memoized_stop() -> bool:
        key = (iterations, no_improvement)
        cached = _stop_memo.get(key)
        if cached is None:
            cached = bool(stop(current_state()))
            _stop_memo.clear()
            _stop_memo[key] = cached
        return cached

    bundle = build_integrated_private_hgs(
        initial_candidates,
        evaluator=evaluator,
        charging_policy=charging_policy,
        route_engine=route_engine,
        include_mechanism_refinement=include_mechanism_refinement,
        include_whole_duty_type_exchange=(
            parameters.include_whole_duty_type_exchange
        ),
        include_charging_candidates=include_charging_candidates,
        stop_requested=_memoized_stop,
        population_parameters=parameters.population,
        initial_evaluations=initial_evaluations,
        trajectory_sink=(trajectory.emit_many if trajectory_enabled else None),
        arm=arm,
        schedule_all_changed_move_evaluation=(
            False
            if treatment is None
            else treatment.schedule_all_changed_move_evaluation
        ),
        fleet_activation_enabled=(
            True if treatment is None else treatment.fleet_activation_enabled
        ),
        objective_mode=parameters.objective_mode,
        charging_prescreen_enabled=charging_prescreen_enabled,
        cross_depot_enabled=cross_depot_enabled,
        multi_trip_enabled=multi_trip_enabled,
        type_exchange_enabled=type_exchange_enabled,
        education_depth_limit=parameters.education_depth_limit,
        lazy_exact_evaluation=lazy_exact_evaluation,
    )
    accounting = bundle.accounting.mechanism
    accounting.penalty_manager = bundle.complete_penalty_manager
    effective_execution = bundle.effective_execution
    _record_integrated_population_admissions(
        bundle.population,
        accounting,
        initial_candidate_count=len(initial_candidates),
    )
    result = bundle.algorithm.run(_IntegratedStop())
    accounting.restarts = result.accounting.restarts
    accounting.repair_calls += int(bundle.accounting.repair_calls)
    accounting.outer_refinement_calls += int(
        bundle.accounting.mechanism_calls
    )
    accounting.initialization_wall_seconds = float(
        initialization_wall_seconds
    )
    accounting.initialization_full_evaluations = int(
        initialization_full_evaluation_count
    )
    accounting.full_evaluations = int(
        initialization_full_evaluation_count
    ) + (evaluator.full_calls - full_calls_before)
    accounting.charging_repair_cache_hits = int(
        bundle.charging_repair_cache.hits
    )
    accounting.charging_repair_cache_misses = int(
        bundle.charging_repair_cache.misses
    )
    return _finish_result(
        result.best.solution,
        evaluator,
        result.accounting.iterations,
        accounting,
        trajectory.retained,
        started,
        effective_execution,
        status="STOPPED_BY_CALLER",
        objective_mode=parameters.objective_mode,
        charging_prescreen_accounting=(
            None
            if bundle.charging_prescreen is None
            else bundle.charging_prescreen.statistics()
        ),
    )


# ``CostEvaluator.cost`` returns this int64 sentinel when the kernel's best
# solution is infeasible, so it is not a cost and must never enter a trace.
KERNEL_INFEASIBLE_COST = 2**63 - 1


# 2026-09-05：确认轮的耐心值改由本次跑自己的第一轮标定，不再全轮固定 20,000。
# 依据是 solver/reports/reload_fix_shortrun_20260905 的 6 跑 16 轮：第 2 轮起
# 的 10 轮里 8 轮零改善、各自烧满 20,000 圈，占总墙钟 43%；而有改善的两轮，
# 改善分别出现在轮内第 2720 与第 13258 圈，都不超过该跑第一轮里"两次相邻改善
# 之间等得最久的那一次"（15,812 圈）。所以"第一轮等得最久的那段"就是后续轮
# 值得等多久的本机标定量。SAFETY 是这个标定量的放大系数：1.0 ＝ 恰好给后续轮
# 第一轮真正需要过的最长等待。它是常量不是命令行开关——改它要改代码，改代码
# 就要重新给出上面这类数据。
CONFIRMING_ROUND_PATIENCE_SAFETY = 1.0
# 下限。第一轮若很快就收敛（例如最长等待只有 4,516 圈），把后续轮压到那么短
# 会让确认轮变成走过场，故不低于 5,000 圈。
CONFIRMING_ROUND_PATIENCE_FLOOR = 5_000
CONFIRMING_ROUND_PATIENCE_MODES = ("fixed", "adaptive")

# 2026-09-05：确认轮的停机由"任一轮无改善即停"改为"连续 N 轮无改善才停"。
# 依据是 docs/handoff/run_variance_diagnosis_20260905.md：同车队内，多拿到一轮
# 的跑比只跑两轮的低 18.47 元（B 批 2CV/3EV，4 对 2）和 19.19 元（A 批同车队，
# 1 对 5），两批同号同量级，而要检出的择时效应只有 7–10 元；也就是说"这次跑
# 有没有拿到第 3 轮"是一次抽签，不是收敛判据。N=1 逐位复现历史行为。
STOP_AFTER_NONIMPROVING_ROUNDS = 2
# 轮数硬上限。改动前 ``confirming_round`` 的轮次循环没有任何总轮数上限：它只
# 在"某一轮没改善"、"没有可行解"、"最优方案不用电"三处退出。N=1 时"改善—不
# 改善"交替的跑必在第一个不改善的轮停住，所以不设上限也终止；N≥2 时这种交替
# 序列永远凑不满 N 个连续，循环就没有出口。这个上限是那个出口，不是调参旋钮：
# 已落盘的全部跑（A 批 10、B 批 10、C 批 6）轮数最多 4 轮，8 从未被碰到。
MAX_OUTER_ROUNDS = 8

# 2026-09-08：第 1 轮独立起跑几次。1 ＝ 改动前的行为（一次运算一个起点）。
# 依据是 docs/handoff/fleet_dispersion_kernel_vs_python_20260908.md §2.4：同一
# 张代理成本表下，内核最好的一跑与最差的一跑差 36.9–60.3 元代理，而这段差距
# 在内核自己的记分牌上就已经全部存在；也就是说"这次运算搜得好不好"是第 1 轮的
# 一次抽签。多起点把这次抽签改成"抽 K 张取最好的一张"，判据用每轮本来就在记的
# ``kernel_best_cost``（轮内可行代理最优），所以取优不额外付一次完整精确评价。
# 库内默认留 1：改动前的行为逐位不变，是不是要多起点由调用方明说。
ROUND_ONE_STARTS = 1


def max_improvement_gap(iterations: Iterable[int]) -> int:
    """相邻两次内核改善之间等得最久的那一段，按内核圈数计。

    从圈 0 起算：内核的停止判据在第 1 圈之前先被调用一次，所以种群播种后的
    最优会记在圈 0，这样的一轮在首个事件上贡献 0；若某轮直到第 900 圈才第一
    次改善，它在首个事件上贡献 900。轮末那段"再也没有改善"的尾巴不是两次改
    善之间的间隔，不计入——它恰好就是 patience 本身，计入即等于自证。
    """

    widest = 0
    previous = 0
    for iteration in iterations:
        widest = max(widest, int(iteration) - previous)
        previous = int(iteration)
    return widest


def confirming_round_patience(
    widest_gap: int,
    *,
    mode: str,
    floor: int,
    cap: int,
) -> int:
    """一个确认轮允许连续空转多少圈。

    ``fixed`` 逐位复现 2026-09-05 之前的行为：每轮都拿 ``cap``。``adaptive``
    给这一轮"搜索到目前为止真正等过的最长一段"，再夹进 ``[floor, cap]``。
    冲突时 ``cap`` 赢：``stagnation_patience`` 是这次跑对外声明的上限，任何一
    轮都不得超过它（夹具上 cap=300 < floor=5000 时结果是 300）。
    """

    if mode not in CONFIRMING_ROUND_PATIENCE_MODES:
        raise ValueError(
            "unknown confirming-round patience mode: "
            f"{mode!r}; expected one of {CONFIRMING_ROUND_PATIENCE_MODES}"
        )
    if mode == "fixed":
        return int(cap)
    scaled = int(float(widest_gap) * CONFIRMING_ROUND_PATIENCE_SAFETY)
    return min(int(cap), max(int(floor), scaled))


def confirming_round_should_stop(
    *,
    rounds: int,
    nonimproving_streak: int,
    stop_after_nonimproving_rounds: int,
) -> bool:
    """``confirming_round`` 的轮次循环这一轮跑完之后停不停。

    ``nonimproving_streak`` ＝ 到这一轮为止连续多少轮没有改善精确最优（这一轮
    改善了就是 0）。``rounds > 1`` 这个护栏留着不动：第 1 轮从不停机，它是那
    个要被确认的轮本身。

    ``stop_after_nonimproving_rounds == 1`` 与 2026-09-05 之前的
    ``rounds > 1 and not improved`` 逐位等价：streak 只在 ``not improved``
    那一轮取到 ≥1，改善的那一轮取 0。
    """

    if stop_after_nonimproving_rounds < 1:
        raise ValueError(
            "stop-after-nonimproving-rounds must be at least 1; got "
            f"{stop_after_nonimproving_rounds!r}"
        )
    return int(rounds) > 1 and int(nonimproving_streak) >= int(
        stop_after_nonimproving_rounds
    )


def no_electricity_exit_should_fire(
    *,
    electricity_kwh: float,
    ever_improved: bool,
) -> bool:
    """轮次循环末尾那个"最优方案不用电就不再往下搜"的出口，该不该触发。

    第二阶段做的事是"按精确最优实付的每 kWh 价格重标定内核里的电车定价，再搜
    一轮"。方案真的一度电都不用，这件事确实没有意义——**前提是这个方案是搜出
    来的**。任何一轮把精确最优压下去之前，``best`` 还是初始见证解本身；见证解
    若是纯燃油的，这个出口就会在第 1 轮末把整跑送走，一个确认轮都不给。

    实测两例：``solver/reports/grid2x2_20260905/midday/P=1.0/MT-HGS/run_08``
    与 ``run_10``——``rounds=1``、``round_improved_by_round=[False]``、
    ``initial_cost`` 逐位等于最终成本 3333.49 元（8 辆燃油车）。彼时
    ``confirming_round_should_stop`` 的 ``rounds > 1`` 护栏对任何
    ``stop_after_nonimproving_rounds`` 都返回 False，这条分支是唯一出口，
    所以把停机规则从 N=1 改到 N=2 对这两跑逐位无效。

    ``ever_improved`` 这道闸只可能改变"第 1 轮没改进过"的跑：首轮改进过的跑
    在到达本判据时闸已经是开的，与改动前逐位相同。
    """

    return float(electricity_kwh) <= 0.0 and bool(ever_improved)


class _KernelImprovementTrace:
    """Record the kernel's in-round improvement curve without touching search.

    ``GeneticAlgorithm.run`` evaluates ``while not stop(cost(best))`` exactly
    once per iteration, so wrapping the stopping criterion observes the whole
    per-iteration best-cost series at O(1) per iteration and draws no random
    numbers: the search sees the delegate's verdict unchanged and its RNG
    stream is untouched.  ``Statistics(collect_stats=True)`` reports the same
    series, but its ``collect_from`` walks both subpopulations every iteration
    computing penalised costs and diversities, which would inflate the very
    wall clock this trace exists to explain.

    ``iteration`` counts kernel iterations completed in this round when the
    cost was first observed; the criterion is called once before iteration 1,
    so an event at iteration 0 is the seeded population's best.
    """

    def __init__(self, criterion, *, round_index: int) -> None:
        self._criterion = criterion
        self._round = int(round_index)
        self._iteration = 0
        self._best: float | None = None
        self.events: list[dict[str, float | int]] = []

    def __call__(self, best_cost: float) -> bool:
        stop_now = self._criterion(best_cost)
        cost = float(best_cost)
        if cost < KERNEL_INFEASIBLE_COST and (
            self._best is None or cost < self._best
        ):
            self._best = cost
            self.events.append(
                {
                    "round": self._round,
                    "iteration": self._iteration,
                    "kernel_best_cost": cost,
                }
            )
        self._iteration += 1
        return stop_now

    @property
    def best_cost(self) -> float | None:
        return self._best


def _finish_result(
    best: DutyIndividual,
    evaluator: DutyFullEvaluator,
    iterations: int,
    accounting: SearchAccounting,
    trajectory: list[TrajectoryRow],
    started: float,
    effective_execution: ExecutionSettings,
    *,
    status: str,
    error: Exception | None = None,
    objective_mode: str = SINGLE_OBJECTIVE,
    charging_prescreen_accounting: dict[str, object] | None = None,
) -> ProblemHGSRunResult:
    final_evaluation = evaluator.evaluate(best)
    accounting.full_evaluations += 1
    accounting.run_wall_seconds = perf_counter() - started
    return ProblemHGSRunResult(
        best=best,
        best_evaluation=final_evaluation,
        iterations=iterations,
        accounting=accounting,
        trajectory=tuple(trajectory),
        effective_execution=effective_execution,
        termination_status=(
            CandidateStatus.NO_FEASIBLE_SOLUTION.value
            if not final_evaluation.feasible
            else status
        ),
        termination_error_type=(None if error is None else type(error).__name__),
        termination_error=None if error is None else str(error),
        objective_mode=objective_mode,
        charging_prescreen_accounting=charging_prescreen_accounting,
    )


def run_kernel_native_problem_hgs(
    initial_candidates: tuple[DutyIndividual, ...],
    *,
    evaluator: DutyFullEvaluator,
    charging_policy: ChargingRepairPolicy,
    parameters: ProblemHGSSearchParameters,
    stop: Callable[[ProblemHGSSearchState], bool],
    arm: str,
    route_engine: IndependentKernelDutyRouteProposalEngine,
    route_engine_factory: Callable[..., IndependentKernelDutyRouteProposalEngine],
    initial_evaluations: tuple[FullEvaluation, ...] | None = None,
    initialization_full_evaluation_count: int | None = None,
    initialization_wall_seconds: float = 0.0,
    charging_prescreen_enabled: bool = False,
    cross_depot_enabled: bool = True,
    multi_trip_enabled: bool = True,
    type_exchange_enabled: bool = True,
    include_mechanism_refinement: bool = True,
    include_charging_candidates: bool = True,
    confirming_round: bool = False,
    confirming_round_patience_mode: str = "adaptive",
    confirming_patience_floor: int = CONFIRMING_ROUND_PATIENCE_FLOOR,
    stop_after_nonimproving_rounds: int = STOP_AFTER_NONIMPROVING_ROUNDS,
    max_outer_rounds: int = MAX_OUTER_ROUNDS,
    reload_gap_quantile: float = RELOAD_GAP_QUANTILE,
    round_one_starts: int = ROUND_ONE_STARTS,
    frozen_reload_gap_seconds: float | None = None,
    frozen_first_trip_window_open_second: float | None = None,
) -> ProblemHGSRunResult:
    """Route-then-charge search: the kernel searches, the exact model judges.

    2026-09-03.  Following the decomposition of Montoya et al. (2017) and
    Froger et al. (2019) for EV routing with nonlinear charging, the copied
    HGS kernel (PyVRP 0.12.2 ``GeneticAlgorithm``) runs its own population
    search on the route proxy until ``stagnation_patience`` iterations pass
    without improvement.  Every feasible member of its final population is
    then decoded, charging-repaired, evaluated exactly and educated with the
    mechanism moves.  Two phases: the first searches with the calendar
    estimate of the EV price, the second with the electricity-plus-carbon
    price per kWh the exact best actually paid, warm-started from the exact
    candidates (Froger et al. 2019: route search, then the charging
    subproblem on the candidates).  The second phase is skipped when the
    best plan uses no electricity -- but only once some round has actually
    improved on the witness, see the no-electricity note below.  With
    ``confirming_round`` the priced
    search repeats until a round no longer improves the exact best.  Every
    reported number is a complete evaluation; the exact best of all phases
    is the answer.

    Accounting note (2026-09-05).  ``accounting.restarts`` holds the number
    of outer rounds, not genetic-algorithm restarts: the kernel is built with
    ``num_iters_no_improvement=10**9`` and never restarts internally.  The
    name is a historical misnomer kept for downstream readers;
    ``accounting.rounds`` carries the same value under the honest name, and
    ``accounting.stop_semantics_actual`` states the whole-run stopping rule.

    Patience note (2026-09-05).  Round one keeps the declared
    ``stagnation_patience``; from round two on, ``confirming_round_patience_mode
    == "adaptive"`` (the default) sizes the round from this run's own measured
    improvement gaps -- see ``confirming_round_patience``.  ``"fixed"`` gives
    every round ``stagnation_patience`` and reproduces the pre-2026-09-05
    behaviour bit for bit.  The adaptive rule reaches round two of an ordinary
    two-phase run as well, not only the repeated rounds of
    ``confirming_round``; ``"fixed"`` is the switch back.

    Stopping note (2026-09-05).  ``stop_after_nonimproving_rounds`` is how many
    rounds in a row must fail to improve the exact best before the run stops.
    It only reaches the ``confirming_round`` branch: without that flag the loop
    still stops after round two, unchanged.  ``1`` reproduces the historical
    ``rounds > 1 and not improved`` bit for bit -- see
    ``confirming_round_should_stop``.  ``max_outer_rounds`` is the loop's hard
    exit; before this change the confirming branch had none, which an
    improve/no-improve alternation would never terminate under ``N >= 2``.

    No-electricity note (2026-09-05).  The "best plan uses no electricity"
    exit fires only after at least one round has improved on the witness.
    Before that ``best`` is still the witness itself, so an all-fuel witness
    used to end the run after round one whatever ``stop_after_nonimproving_
    rounds`` said: ``confirming_round_should_stop``'s ``rounds > 1`` guard
    returns False for every N in round one, which left that exit as the only
    way out.  Runs whose first round did improve are unchanged bit for bit --
    the gate is already open by the time they reach the test.

    Multi-start note (2026-09-08).  ``round_one_starts`` runs round one's
    kernel search K times and keeps the start with the lowest
    ``kernel_best_cost`` -- the kernel's own in-round feasible proxy best,
    which every round already records, so selecting on it costs no extra
    complete evaluation.  The exact stage runs once, on the winner.  K == 1 is
    the pre-2026-09-08 behaviour bit for bit: the projected seeds, the random
    top-up, the population and the genetic algorithm are built in the same
    order from the same random stream.  The K starts are NOT exchangeable
    draws: ``route_engine.rng``, ``route_engine.local_search`` and
    ``route_engine.penalty_manager`` are one shared, stateful triple, so start
    k+1 begins from the stream and the adapted penalties start k left behind.
    That is fine for selection -- ``kernel_best_cost`` is an unpenalised cost
    of a feasible solution, so the comparison does not depend on the penalty
    state -- but it means the starts are sequential samples, not independent
    replicates.  Only the winner's improvement trace feeds
    ``widest_improvement_gap`` and ``round1_max_improvement_gap``: a loser's
    long wait must not silently buy every later round a bigger patience.
    ``total_iterations`` and ``crossover_calls`` count all K starts (that is
    the work actually done); ``kernel_round_summaries[0]`` reports the winner,
    and ``round_one_start_summaries`` carries every start, so the two views
    reconcile.

    Frozen-anchor note (2026-09-08).  ``frozen_reload_gap_seconds`` and
    ``frozen_first_trip_window_open_second`` pin the two route-independent
    anchors of the kernel's EV proxy for the whole run: the between-trip
    charging reservation and the opening instant of the first shift's charging
    window.  Both default to None, which keeps the historical behaviour --
    the reservation re-estimated from the previous round's exact best, and the
    window opening silently lost from round two on because the round-two
    factory call never passed it.  When they are set, every round rebuilds the
    engine with the same two values, so the proxy's cost table no longer moves
    inside a run (its LEVEL still does, through the deliberate
    ``ev_unit_cost`` second-phase feedback, which is untouched).  The purpose
    is variance, not depth: the two anchors used to be estimated per run from
    that run's own random initial population, which made "ten runs" ten
    different proxy problems -- 40 measured runs spread 1348-2117 s and
    55619-58732 s (docs/handoff/fleet_dispersion_kernel_vs_python_20260908.md
    section 2.1).
    """

    from setp_hgs_kernel import Solution as KernelSolution
    from setp_hgs_kernel.GeneticAlgorithm import (
        GeneticAlgorithm,
        GeneticAlgorithmParams,
    )
    from setp_hgs_kernel.Population import Population as KernelPopulation
    from setp_hgs_kernel.crossover import ordered_crossover, selective_route_exchange
    from setp_hgs_kernel.diversity import broken_pairs_distance as kernel_bpd
    from setp_hgs_kernel.solve import SolveParams
    from setp_hgs_kernel.stop import NoImprovement

    from .charging import repair_changed_duties_outcome
    from .evaluation import assert_candidate_routes_single_shift
    from .external_population import EvaluatedSolution
    from .fleet_registry import assert_fleet_activation_allowed
    from .integrated_private import PrivateIntegratedEvaluation
    from .operators import DutySkeletonMove

    started = perf_counter()
    if initial_evaluations is None:
        initial_evaluations = tuple(
            evaluator.evaluate(candidate) for candidate in initial_candidates
        )
        initialization_full_evaluation_count = len(initial_evaluations)
    elif initialization_full_evaluation_count is None:
        initialization_full_evaluation_count = len(initial_evaluations)
    full_calls_before = evaluator.full_calls
    reference = initial_candidates[0]
    context = evaluator.context
    bundle = build_integrated_private_hgs(
        initial_candidates,
        evaluator=evaluator,
        charging_policy=charging_policy,
        route_engine=route_engine,
        include_mechanism_refinement=include_mechanism_refinement,
        include_whole_duty_type_exchange=parameters.include_whole_duty_type_exchange,
        include_charging_candidates=include_charging_candidates,
        population_parameters=parameters.population,
        initial_evaluations=initial_evaluations,
        arm=arm,
        charging_prescreen_enabled=charging_prescreen_enabled,
        cross_depot_enabled=cross_depot_enabled,
        multi_trip_enabled=multi_trip_enabled,
        type_exchange_enabled=type_exchange_enabled,
        education_depth_limit=parameters.education_depth_limit,
        # The kernel seeds itself; an idle reference may stand in for
        # complete initial candidates (fleet overrides, 2026-09-03).
        allow_incomplete_initial=True,
    )
    accounting = bundle.accounting.mechanism
    accounting.penalty_manager = bundle.complete_penalty_manager
    refine = bundle.algorithm._adapter.refine
    policy = bundle.effective_execution.effective_charging_policy
    carbon_price = float(context.bundle.prices.carbon_price)
    kernel_params = SolveParams()
    patience = int(parameters.stagnation_patience)
    patience_mode = str(confirming_round_patience_mode)
    patience_floor = int(confirming_patience_floor)
    stop_after_nonimproving = int(stop_after_nonimproving_rounds)
    round_cap = int(max_outer_rounds)
    if stop_after_nonimproving < 1:
        raise ValueError(
            "stop-after-nonimproving-rounds must be at least 1; got "
            f"{stop_after_nonimproving_rounds!r}"
        )
    if round_cap < 1:
        raise ValueError(
            f"max-outer-rounds must be at least 1; got {max_outer_rounds!r}"
        )
    starts_round_one = int(round_one_starts)
    if starts_round_one < 1:
        raise ValueError(
            f"round-one-starts must be at least 1; got {round_one_starts!r}"
        )
    if patience_mode not in CONFIRMING_ROUND_PATIENCE_MODES:
        raise ValueError(
            "unknown confirming-round patience mode: "
            f"{patience_mode!r}; expected one of {CONFIRMING_ROUND_PATIENCE_MODES}"
        )
    # 迄今所有已跑完的轮里，相邻两次内核改善之间等得最久的那一段。只增不减：
    # 某个后续轮真出了改善，下一轮的参考随之放宽，不会因为某轮收得快而收紧。
    widest_improvement_gap = 0
    round1_widest_gap: int | None = None

    best: tuple[DutyIndividual, FullEvaluation] | None = min(
        (
            (candidate, full)
            for candidate, full in zip(initial_candidates, initial_evaluations, strict=True)
            if full.feasible
        ),
        key=lambda item: float(item[1].total_cost),
        default=None,
    )
    seeds: list[DutyIndividual] = list(initial_candidates)
    exact_pool: list[FullEvaluation] = list(initial_evaluations)
    total_iterations = 0
    rounds = 0
    # 到目前为止有没有任何一轮把精确最优压到见证解之下。只被循环末尾那个
    # "不用电"提前出口读。
    ever_improved = False
    # Kernel iterations since the exact best last improved.  Reported instead
    # of the hardcoded 0 this state used to carry (2026-09-05); the outer
    # ``stop`` return value is discarded on this path either way, which
    # ``accounting.outer_stop_callback_effective`` records.
    iterations_without_improvement = 0
    # 与 ``iterations_without_improvement`` 是两件事：那个按内核圈数累加、进
    # ``state()`` 报给外层回调；这个按"轮"计，只喂停机规则。
    nonimproving_streak = 0
    improvement_events: list[dict[str, float | int]] = []
    # ``kernel_best_cost`` is ``None`` for a round whose kernel best never
    # left the infeasible sentinel, so the value type admits ``None``.
    round_summaries: list[dict[str, float | int | None]] = []
    ev_unit_cost: float | None = None
    # Reload-gap proxy feedback (fleet-composition experiment): the seconds
    # the exact best actually spent charging between trips replace the
    # reference estimate in the next kernel round.
    reload_gap_feedback = bool(
        getattr(route_engine, "ev_reload_gap_proxy_enabled", False)
    )
    # 2026-09-08：冻结时这两个数从头到尾不变，第 2 轮起的重建也照原样传回去。
    # ``frozen_first_trip_window_open_second`` 必须显式传给每一轮的工厂调用：
    # ``make_route_engine`` 只记得构造时给过的 kwargs，而第 2 轮起的工厂调用从
    # 来没有带过它，于是首班窗口开启时刻在第 2 轮就退回契约的末班结束时刻。
    reload_gap_seconds: float | None = (
        None
        if frozen_reload_gap_seconds is None
        else float(frozen_reload_gap_seconds)
    )
    engine = route_engine

    def state() -> ProblemHGSSearchState:
        cost = None if best is None else float(best[1].total_cost)
        return ProblemHGSSearchState(
            iterations=total_iterations,
            iterations_without_improvement=iterations_without_improvement,
            best_cost=cost,
            elapsed_seconds=float(initialization_wall_seconds) + perf_counter() - started,
            full_evaluations=int(initialization_full_evaluation_count)
            + (evaluator.full_calls - full_calls_before),
            incremental_evaluations=accounting.incremental_evaluations,
            duty_slice_preparations=accounting.duty_slice_preparations,
            candidate_assemblies=accounting.candidate_assemblies,
            has_feasible=best is not None,
            best_feasible_raw_cost=cost,
            current_solution_raw_cost=cost,
            outer_refinement_calls=bundle.accounting.mechanism_calls,
        )

    while True:
        rounds += 1
        round_patience = (
            patience
            if rounds == 1
            else confirming_round_patience(
                widest_improvement_gap,
                mode=patience_mode,
                floor=patience_floor,
                cap=patience,
            )
        )
        accounting.round_patience_by_round.append(int(round_patience))
        if rounds > 1:
            factory_kwargs = {"ev_unit_cost_cny_per_kwh": ev_unit_cost}
            if reload_gap_feedback and reload_gap_seconds is not None:
                factory_kwargs["ev_reload_gap_seconds"] = reload_gap_seconds
            if frozen_first_trip_window_open_second is not None:
                factory_kwargs["first_trip_window_open_second"] = float(
                    frozen_first_trip_window_open_second
                )
            engine = route_engine_factory(**factory_kwargs)
        if reload_gap_feedback:
            proxy = getattr(engine, "ev_charge_time_proxy", None) or {}
            accounting.reload_gap_seconds_by_round.append(
                float(proxy.get("reload_gap_seconds", 0.0))
            )
        data = engine.data
        projected: list[KernelSolution] = []
        seen_seed: set[str] = set()
        for individual in seeds:
            if individual.fingerprint in seen_seed:
                continue
            seen_seed.add(individual.fingerprint)
            if individual.unserved_customers:
                # An idle reference (fleet override the witness cannot
                # seat) carries no routes; the kernel seeds itself randomly.
                continue
            projected.append(engine.project(individual))
        # 2026-09-05: the round-N reservation can put the previous round's own
        # exact best into the kernel's infeasible subpopulation, where
        # ``GeneticAlgorithm._best`` can never reach it.  Record it here
        # instead of re-deriving it offline.  Counted before the random
        # top-up below, so the number is about the projected seeds only --
        # ``Solution.make_random`` members are routinely infeasible and would
        # drown the signal.
        accounting.kernel_seed_infeasible_by_round.append(
            sum(1 for candidate in projected if not candidate.is_feasible())
        )
        accounting.kernel_seed_count_by_round.append(len(projected))
        crossover = (
            selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
        )
        # 2026-09-08：第 1 轮起跑 K 次，其余轮恒为 1 次。K==1 时下面这段与改动
        # 前逐位相同——补员、种群、遗传算法仍按同一顺序从同一条随机流上建起来。
        starts_this_round = starts_round_one if rounds == 1 else 1
        attempts: list[tuple[object, object, _KernelImprovementTrace]] = []
        for _start in range(starts_this_round):
            init = list(projected)
            while len(init) < kernel_params.population.min_pop_size:
                init.append(KernelSolution.make_random(data, engine.rng))
            population = KernelPopulation(kernel_bpd, kernel_params.population)
            algorithm = GeneticAlgorithm(
                data,
                engine.penalty_manager,
                engine.rng,
                population,
                engine.local_search,
                crossover,
                init,
                GeneticAlgorithmParams(
                    repair_probability=kernel_params.genetic.repair_probability,
                    num_iters_no_improvement=10**9,  # no stagnation restart
                ),
            )
            trace = _KernelImprovementTrace(
                NoImprovement(round_patience), round_index=rounds
            )
            result_this_start = algorithm.run(trace, collect_stats=False)
            total_iterations += int(result_this_start.num_iterations)
            accounting.crossover_calls += int(result_this_start.num_iterations)
            attempts.append((result_this_start, population, trace))
        # 取优判据：内核自己的轮内可行代理最优。从未离开不可行哨兵的起点
        # （``best_cost is None``）排在所有有可行最优的起点之后。
        selected_index = min(
            range(len(attempts)),
            key=lambda index: (
                attempts[index][2].best_cost is None,
                attempts[index][2].best_cost or 0.0,
                index,
            ),
        )
        kernel_result, population, trace = attempts[selected_index]
        if rounds == 1:
            accounting.round_one_starts = starts_this_round
            accounting.round_one_start_summaries = [
                {
                    "start": index + 1,
                    "iterations": int(attempt.num_iterations),
                    "runtime_seconds": float(attempt.runtime),
                    "improvements": len(attempt_trace.events),
                    "kernel_best_cost": attempt_trace.best_cost,
                    "selected": index == selected_index,
                }
                for index, (attempt, _pop, attempt_trace) in enumerate(attempts)
            ]
        improvement_events.extend(trace.events)
        round_gap = max_improvement_gap(
            event["iteration"] for event in trace.events
        )
        if rounds == 1:
            round1_widest_gap = round_gap
        widest_improvement_gap = max(widest_improvement_gap, round_gap)
        round_summaries.append(
            {
                "round": rounds,
                "iterations": int(kernel_result.num_iterations),
                "runtime_seconds": float(kernel_result.runtime),
                "improvements": len(trace.events),
                "kernel_best_cost": trace.best_cost,
            }
        )

        # Exact stage: decode, charge, evaluate and educate every member of
        # the kernel's final population, time-warped ones included.  With EV
        # charging time amortised over the arcs the kernel sees real feasible
        # chains as 9-18 minutes late (measured on the batch-1 best solutions),
        # so they live in its infeasible subpopulation; the exact model, not
        # the proxy clock, decides feasibility.
        natives = [kernel_result.best, *population]
        exact: list[tuple[DutyIndividual, FullEvaluation]] = []
        seen: set[tuple] = set()
        for index, native in enumerate(natives):
            replacements = engine.decode_replacements(reference, native)
            key = tuple(sorted(replacements))
            if key in seen:
                continue
            seen.add(key)
            if not engine._mechanism_locks_preserved(reference, replacements):
                continue
            try:
                raw = (
                    DutySkeletonMove(
                        action_id=f"kernel-native:r{rounds}:{index}",
                        channel="route_kernel",
                        replacements=replacements,
                        dynamic_future_only=False,
                    ).apply(reference)
                    if replacements
                    else reference
                )
                assert_candidate_routes_single_shift(
                    raw,
                    context.rebuilt_route_constraints,
                )
                assert_fleet_activation_allowed(
                    reference,
                    raw,
                    enabled=bundle.effective_execution.fleet_activation_enabled,
                )
            except (TypeError, ValueError):
                continue
            if raw.unserved_customers:
                continue
            outcome = repair_changed_duties_outcome(
                reference,
                raw,
                changed_duty_ids={duty_id for duty_id, _trips in replacements},
                context=context,
                policy=policy,
                cache=bundle.charging_repair_cache,
            )
            if outcome.candidate is None:
                continue
            try:
                full = evaluator.evaluate(outcome.candidate)
            except (TypeError, ValueError):
                continue
            if full.feasible:
                exact.append((outcome.candidate, full))
        exact_pool = [*exact_pool, *(full for _candidate, full in exact)]
        bundle.complete_penalty_manager.update(tuple(exact_pool[-max(4, len(exact_pool)):]))
        educated: list[tuple[DutyIndividual, FullEvaluation]] = []
        for candidate, full in exact:
            refined = refine(
                EvaluatedSolution(candidate, PrivateIntegratedEvaluation(candidate, full))
            )
            educated.append((refined.solution, refined.evaluation.full))
        round_best = min(
            educated,
            key=lambda item: float(item[1].total_cost),
            default=None,
        )
        improved = round_best is not None and (
            best is None
            or float(round_best[1].total_cost) < float(best[1].total_cost) - 1e-9
        )
        if improved:
            best = round_best
            iterations_without_improvement = 0
            nonimproving_streak = 0
            ever_improved = True
        else:
            iterations_without_improvement += int(kernel_result.num_iterations)
            nonimproving_streak += 1
        accounting.round_improved_by_round.append(bool(improved))
        stop(state())
        if best is None:
            break
        if confirming_round:
            if confirming_round_should_stop(
                rounds=rounds,
                nonimproving_streak=nonimproving_streak,
                stop_after_nonimproving_rounds=stop_after_nonimproving,
            ):
                break
        elif rounds == 2:
            break
        if rounds >= round_cap:
            break
        breakdown = best[1].breakdown
        kwh = float(breakdown.get("electricity_kwh", 0.0))
        # 2026-09-05：这个出口现在要求"至少改进过一轮"，见
        # ``no_electricity_exit_should_fire``。第 1 轮没改进的跑不再从这里被
        # 送走，改由正常停机规则（连续 N 轮无改善）决定何时停；下一轮的
        # ``ev_unit_cost`` 保持 None，即与第 1 轮同样的日历电价估计。
        if no_electricity_exit_should_fire(
            electricity_kwh=kwh, ever_improved=ever_improved
        ):
            break
        if kwh <= 0.0:
            accounting.no_electricity_exit_deferred_rounds.append(int(rounds))
        else:
            ev_unit_cost = (
                float(breakdown.get("cost_elec", 0.0))
                + float(breakdown.get("E_ev_indirect", 0.0)) * carbon_price
            ) / kwh
        if reload_gap_feedback and frozen_reload_gap_seconds is None:
            # 2026-09-05: the quantile, not the maximum.  Reserving the exact
            # best's longest single between-trip charge booked 2380-2642 s and
            # put 25 of 33 exactly-feasible solutions into the kernel's
            # infeasible subpopulation, which ``GeneticAlgorithm._best`` never
            # reads; see ``RELOAD_GAP_QUANTILE`` for the measured distribution.
            measured = inter_trip_reload_seconds(
                best[0], quantile=reload_gap_quantile
            )
            if measured is not None:
                reload_gap_seconds = measured
        seeds = [candidate for candidate, _full in educated]
        if best is not None:
            seeds.append(best[0])
        if not seeds:
            seeds = list(initial_candidates)

    if best is None:
        raise ValueError("kernel-native search found no feasible exact candidate")
    # ``restarts`` is a historical misnomer for the outer round count; keep it
    # for downstream readers and publish the same number under ``rounds``.
    accounting.restarts = rounds
    accounting.rounds = rounds
    accounting.round_patience_mode = patience_mode
    accounting.round1_max_improvement_gap = round1_widest_gap
    accounting.stop_after_nonimproving_rounds = stop_after_nonimproving
    accounting.max_outer_rounds = round_cap
    accounting.frozen_reload_gap_seconds = (
        None
        if frozen_reload_gap_seconds is None
        else float(frozen_reload_gap_seconds)
    )
    accounting.frozen_first_trip_window_open_second = (
        None
        if frozen_first_trip_window_open_second is None
        else float(frozen_first_trip_window_open_second)
    )
    accounting.stop_semantics_actual = (
        "per-round NoImprovement(patience) x rounds"
        if patience_mode == "fixed"
        else (
            f"round 1: NoImprovement({patience}); confirming rounds: adaptive"
            " patience = max improvement gap of round 1, floor"
            f" {patience_floor}, cap {patience}"
        )
    ) + (
        f"; stop after {stop_after_nonimproving} consecutive non-improving"
        f" rounds, at most {round_cap} rounds"
        if confirming_round
        else ""
    )
    # The outer callback's return value is discarded by this loop: rounds end
    # on the kernel's own no-improvement rule and the loop breaks on its round
    # bookkeeping, never on what ``stop`` returns.
    accounting.outer_stop_callback_effective = False
    accounting.improvement_events = improvement_events
    accounting.kernel_round_summaries = round_summaries
    accounting.initialization_wall_seconds = float(initialization_wall_seconds)
    accounting.initialization_full_evaluations = int(initialization_full_evaluation_count)
    accounting.full_evaluations = int(initialization_full_evaluation_count) + (
        evaluator.full_calls - full_calls_before
    )
    accounting.charging_repair_cache_hits = int(bundle.charging_repair_cache.hits)
    accounting.charging_repair_cache_misses = int(bundle.charging_repair_cache.misses)
    return _finish_result(
        best[0],
        evaluator,
        total_iterations,
        accounting,
        [],
        started,
        bundle.effective_execution,
        status="STOPPED_BY_CALLER",
        objective_mode=parameters.objective_mode,
        charging_prescreen_accounting=None,
    )
