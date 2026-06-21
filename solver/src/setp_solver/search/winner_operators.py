"""Public winner-kernel operator facade for isolated ALNS experiments."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterator

import numpy as np

from ..check import check_solution
from ..prices import DEFAULT_PRICES
from ..solution import Solution
from .alns_wouda import (
    AlnsRunResult,
    AlnsState,
    SearchPolicy,
    _budget_limit,
    _customers_in_solution,
    _hard_violations,
    _make_acceptance_criterion,
    _make_operator_selector,
    _solution_changed,
    _target_iterations,
    greedy_insert_repair,
    random_customer_removal,
    regret2_insert_repair,
    regret3_insert_repair,
    route_elimination_removal,
    route_segment_removal,
    run_alns_wouda,
    shaw_related_removal,
    vehicle_type_swap_destroy,
    whole_route_removal,
    worst_customer_removal,
)
from .bundle import load_search_bundle
from .candidates import run_candidate
from .construction import build_initial_solution
from .evaluation import EvalBudget, model_cost, EvaluationContext, score_reference
from .local_search import improve_solution_locally


winner_operator_module = "setp_solver.search.winner_operators"
operator_base_id = "winner_kernel_v1"


_CRUSH_FLAG_NAMES = (
    "SETP_ALNS_CRUSH_TRUE_REPAIR",
    "SETP_ALNS_CRUSH_ROUTE_ELIMINATION",
    "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE",
    "SETP_ALNS_CRUSH_LOCAL_SEARCH",
    "SETP_ALNS_CRUSH_ADAPTIVE_Q",
)


E2_ALNS_COMPONENT_SOURCES = {
    "SETP_ALNS_CRUSH_TRUE_REPAIR": "Ropke-Pisinger/Wu: cost-aware greedy/regret repair",
    "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "Gao GLNS: route elimination large neighborhood",
    "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "Wu/Ropke-Pisinger: non-hillclimbing ALNS acceptance",
    "SETP_ALNS_CRUSH_LOCAL_SEARCH": "VNS/RVND: bounded 2-opt/Or-opt/relocate polishing",
    "SETP_ALNS_CRUSH_ADAPTIVE_Q": "Ropke-Pisinger/Wu: adaptive large destroy size",
}


@dataclass(frozen=True)
class WinnerKernelConfig:
    """Configuration for reproducible winner-kernel ALNS runs."""

    algorithm: str = "ALNS-Wouda"
    seed: int = 1
    eval_budget: int = 16_000
    max_runtime_seconds: float = 900.0
    require_charging_signal: bool = False
    include_route_elimination: bool = False


@dataclass(frozen=True)
class WinnerOperatorAction:
    """One PPO-controllable winner-operator action."""

    destroy_op_id: str
    repair_op_id: str
    remove_count_q: int | None = None
    accept_param: float | None = None
    temperature: float | None = None
    remove_fraction: float | None = None
    raw_action: tuple[int, ...] = ()


@dataclass(frozen=True)
class WinnerOperatorSet:
    """Registry for the exact operators used by the winner kernel."""

    destroy_ops: tuple[tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]], ...]
    repair_ops: tuple[tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]], ...]
    include_route_elimination: bool = False

    @classmethod
    def create(cls, *, include_route_elimination: bool = False) -> "WinnerOperatorSet":
        destroy_ops: list[tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]]] = [
            ("random_customer_removal", random_customer_removal),
            ("worst_customer_removal", worst_customer_removal),
            ("shaw_related_removal", shaw_related_removal),
            ("whole_route_removal", whole_route_removal),
            ("route_segment_removal", route_segment_removal),
            ("vehicle_type_swap", vehicle_type_swap_destroy),
        ]
        if include_route_elimination:
            destroy_ops.insert(4, ("route_elimination_removal", route_elimination_removal))
        repair_ops: list[tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]]] = [
            ("greedy_insert_repair", greedy_insert_repair),
            ("regret2_insert_repair", regret2_insert_repair),
            ("regret3_insert_repair", regret3_insert_repair),
        ]
        return cls(tuple(destroy_ops), tuple(repair_ops), bool(include_route_elimination))

    @property
    def action_space_nvec(self) -> tuple[int, int, int, int]:
        return (len(self.destroy_ops), len(self.repair_ops), 10, 100)

    def destroy_index(self, destroy_op_id: str) -> int:
        return [name for name, _ in self.destroy_ops].index(str(destroy_op_id))

    def repair_index(self, repair_op_id: str) -> int:
        return [name for name, _ in self.repair_ops].index(str(repair_op_id))

    def destroy_callable(self, destroy_op_id: str) -> Callable[[AlnsState, np.random.Generator], AlnsState]:
        return dict(self.destroy_ops)[str(destroy_op_id)]

    def repair_callable(self, repair_op_id: str) -> Callable[[AlnsState, np.random.Generator], AlnsState]:
        return dict(self.repair_ops)[str(repair_op_id)]


def winner_variant_flags(*, include_route_elimination: bool = False) -> dict[str, str]:
    """Return the V2 flags that disable harmful Prompt1 add-ons by default."""

    return {
        "SETP_ALNS_CRUSH_TRUE_REPAIR": "0",
        "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "1" if include_route_elimination else "0",
        "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_LOCAL_SEARCH": "0",
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "0",
    }


def e2_alns_variant_flags() -> dict[str, str]:
    """Return the promoted E2 literature-component ALNS flags.

    Phase-0/short ablation promoted only true repair scoring and adaptive q.
    Route elimination, RRT acceptance, and local search remain explicit
    literature components, but are not defaulted into the E2 final wrapper until
    larger E2 ablations show they help.
    """

    return {
        "SETP_ALNS_CRUSH_TRUE_REPAIR": "1",
        "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "0",
        "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_LOCAL_SEARCH": "0",
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "1",
    }


def decode_winner_action(
    raw_action: list[int] | tuple[int, ...],
    operator_set: WinnerOperatorSet | None = None,
    *,
    base_temperature: float = 100.0,
    customer_count: int | None = None,
) -> WinnerOperatorAction:
    """Decode a PPO raw action into a winner-kernel operator action."""

    ops = operator_set or WinnerOperatorSet.create()
    if len(raw_action) != 4:
        raise ValueError(f"Expected 4 action components, got {len(raw_action)}")
    d_idx, r_idx, q_idx, t_idx = [int(value) for value in raw_action]
    n_destroy, n_repair, n_q, n_temp = ops.action_space_nvec
    if not 0 <= d_idx < n_destroy:
        raise ValueError(f"destroy index out of range: {d_idx}")
    if not 0 <= r_idx < n_repair:
        raise ValueError(f"repair index out of range: {r_idx}")
    if not 0 <= q_idx < n_q:
        raise ValueError(f"q index out of range: {q_idx}")
    if not 0 <= t_idx < n_temp:
        raise ValueError(f"temperature index out of range: {t_idx}")
    q_fraction = 0.10 + (0.30 * q_idx / max(1, n_q - 1))
    remove_count_q = None
    if customer_count is not None:
        remove_count_q = max(1, int(math.ceil(q_fraction * max(0, int(customer_count)))))
    temperature = float(base_temperature) * (0.10 + 1.90 * t_idx / max(1, n_temp - 1))
    return WinnerOperatorAction(
        destroy_op_id=ops.destroy_ops[d_idx][0],
        repair_op_id=ops.repair_ops[r_idx][0],
        remove_count_q=remove_count_q,
        accept_param=temperature,
        temperature=temperature,
        remove_fraction=q_fraction,
        raw_action=tuple(int(value) for value in raw_action),
    )


def apply_winner_action(
    solution: Solution,
    action: WinnerOperatorAction,
    context: EvaluationContext,
    *,
    rng: np.random.Generator | None = None,
    operator_set: WinnerOperatorSet | None = None,
    policy: SearchPolicy | None = None,
    current_obj: float | None = None,
    progress: float = 0.0,
    variant_flags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply one winner destroy+repair action and score one complete candidate."""

    ops = operator_set or WinnerOperatorSet.create()
    rng = rng or np.random.default_rng()
    search_policy = policy or SearchPolicy(require_charging_signal=False)
    previous_state = AlnsState(
        solution,
        context,
        objective_value=current_obj,
        policy=search_policy,
    )
    before_evals = int(context.score_counts.get("candidate", 0))
    remove_count_q = action.remove_count_q
    if remove_count_q is None and action.remove_fraction is not None:
        customer_count = len(_customers_in_solution(solution, context.instance))
        remove_count_q = max(1, int(math.ceil(float(action.remove_fraction) * max(0, customer_count)))) if customer_count else 0
    destroy_op = ops.destroy_callable(action.destroy_op_id)
    repair_op = ops.repair_callable(action.repair_op_id)
    flags = variant_flags or winner_variant_flags(include_route_elimination=ops.include_route_elimination)
    with _temporary_flags(flags):
        destroyed = destroy_op(
            previous_state,
            rng,
            progress=float(progress),
            remove_count_q=remove_count_q,
        )
        candidate = repair_op(destroyed, rng)
        if (
            not candidate.removed_customers
            and not _hard_violations(candidate.solution, candidate.context)
            and _solution_changed(previous_state.solution, candidate.solution)
        ):
            improved_solution = improve_solution_locally(candidate.solution, candidate.context)
            if _solution_changed(candidate.solution, improved_solution):
                candidate = replace(candidate, solution=improved_solution, objective_value=None)
        previous_obj = previous_state.objective()
        if action.destroy_op_id == "route_elimination_removal" and (
            len(candidate.solution.routes) >= len(previous_state.solution.routes)
            or candidate.objective() >= previous_obj - 1e-9
        ):
            candidate = previous_state
        if (
            candidate.removed_customers
            or _hard_violations(candidate.solution, candidate.context)
            or not _solution_changed(previous_state.solution, candidate.solution)
        ):
            candidate = previous_state
        candidate_obj = candidate.objective()
    after_evals = int(context.score_counts.get("candidate", 0))
    trace = {
        "operator_base_id": operator_base_id,
        "winner_operator_module": winner_operator_module,
        "destroy_id": action.destroy_op_id,
        "repair_id": action.repair_op_id,
        "remove_count_q": remove_count_q,
        "remove_fraction": action.remove_fraction,
        "temperature": action.temperature,
        "raw_action": list(action.raw_action),
        "changed": _solution_changed(previous_state.solution, candidate.solution),
        "removed_count": len(candidate.removed_customers),
        "candidate_obj": float(candidate_obj),
        "actual_evals_added": after_evals - before_evals,
    }
    return {
        "operator_base_id": operator_base_id,
        "candidate_solution": candidate.solution,
        "candidate_state": candidate,
        "candidate_obj": float(candidate_obj),
        "actual_evals_added": after_evals - before_evals,
        "trace": trace,
    }


def run_winner_kernel(
    bundle_dir: str | Path,
    *,
    config: WinnerKernelConfig | None = None,
    initial_solution: Solution | None = None,
) -> dict[str, Any]:
    """Run the winner kernel and return a normalized result dictionary."""

    cfg = config or WinnerKernelConfig()
    cfg = WinnerKernelConfig(**{**asdict(cfg), "include_route_elimination": False})
    return _run_winner_variant(bundle_dir, cfg, initial_solution=initial_solution)


def run_winner_kernel_plus_route_elimination(
    bundle_dir: str | Path,
    *,
    config: WinnerKernelConfig | None = None,
    initial_solution: Solution | None = None,
) -> dict[str, Any]:
    """Run winner kernel with route elimination as the only V2 add-on."""

    cfg = config or WinnerKernelConfig()
    cfg = WinnerKernelConfig(**{**asdict(cfg), "include_route_elimination": True})
    return _run_winner_variant(bundle_dir, cfg, initial_solution=initial_solution)


def run_e2_alns_final(
    bundle_dir: str | Path,
    *,
    config: WinnerKernelConfig | None = None,
    initial_solution: Solution | None = None,
) -> dict[str, Any]:
    """Run the explicit E2 literature-component ALNS variant.

    This wrapper does not change ``run_winner_kernel``. It exists so E2 can
    compare a strengthened ALNS candidate while legacy E1-E7 anchors stay
    callable through the original winner-kernel entry point.
    """

    cfg = config or WinnerKernelConfig()
    flags = e2_alns_variant_flags()
    cfg = WinnerKernelConfig(
        **{
            **asdict(cfg),
            "include_route_elimination": flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] == "1",
        }
    )
    return _run_winner_variant(
        bundle_dir,
        cfg,
        initial_solution=initial_solution,
        variant_flags=flags,
        variant_id="e2_alns_final",
    )


def write_winner_manifest(output_dir: str | Path) -> Path:
    """Write the public winner-operator API manifest."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "winner_operator_manifest.json"
    manifest = {
        "schema_version": "setp-winner-operator-manifest.v1",
        "winner_operator_module": winner_operator_module,
        "operator_base_id": operator_base_id,
        "public_api": [
            "WinnerKernelConfig",
            "WinnerOperatorAction",
            "WinnerOperatorSet",
            "apply_winner_action",
            "decode_winner_action",
            "e2_alns_variant_flags",
            "winner_variant_flags",
            "run_e2_alns_final",
            "run_winner_kernel",
            "run_winner_kernel_plus_route_elimination",
            "write_winner_manifest",
        ],
        "default_flags": winner_variant_flags(include_route_elimination=False),
        "route_elimination_flags": winner_variant_flags(include_route_elimination=True),
        "e2_alns_flags": e2_alns_variant_flags(),
        "e2_alns_component_sources": E2_ALNS_COMPONENT_SOURCES,
        "compatible_instances": ["100-01-24h", "L-main"],
        "semantic_guards": [
            "Does not change cost.py/check.py/evaluation.py model semantics.",
            "Does not guarantee dominance over fair SA; use V2 comparison reports.",
            "PPO may import this API, but untrained PPO results must not be mixed into V2 fair baselines.",
        ],
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _run_winner_variant(
    bundle_dir: str | Path,
    config: WinnerKernelConfig,
    *,
    initial_solution: Solution | None,
    variant_flags: dict[str, str] | None = None,
    variant_id: str = "winner_kernel",
) -> dict[str, Any]:
    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    warm = initial_solution or build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        DEFAULT_PRICES,
        introduce_ev=config.require_charging_signal,
        require_charging_signal=config.require_charging_signal,
    )
    flags = variant_flags or winner_variant_flags(include_route_elimination=config.include_route_elimination)
    with _temporary_flags(flags):
        if config.algorithm == "ALNS-Wouda":
            run = _run_winner_kernel_loop(
                warm,
                bundle.instance,
                bundle.carbon_profile,
                config=config,
                variant_flags=flags,
            )
            solution = run.best_solution
            evaluations = run.evaluations
        elif config.algorithm == "DR-ALNS":
            run = run_candidate(
                "DR-ALNS",
                bundle.bundle_dir,
                seed=config.seed,
                eval_budget=config.eval_budget,
                max_runtime_seconds=config.max_runtime_seconds,
                initial_solution=warm,
            )
            if run.best_solution is None:
                raise RuntimeError("DR-ALNS winner kernel returned no feasible best solution")
            solution = run.best_solution
            evaluations = run.evals
        else:
            raise ValueError(f"Unsupported winner kernel algorithm: {config.algorithm}")
    context = EvaluationContext(bundle.instance, bundle.carbon_profile)
    violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
    return {
        "operator_base_id": operator_base_id,
        "variant": variant_id,
        "algorithm": config.algorithm,
        "seed": int(config.seed),
        "eval_budget": int(config.eval_budget),
        "max_runtime_seconds": float(config.max_runtime_seconds),
        "include_route_elimination": bool(config.include_route_elimination),
        "evaluations": int(evaluations),
        "elapsed_seconds": time.perf_counter() - started,
        "best_solution": solution,
        "best_cost": model_cost(solution, context),
        "feasible": len(violations) == 0,
        "violation_count": len(violations),
        "flags": dict(flags),
    }


def _run_winner_kernel_loop(
    initial_solution: Solution,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    *,
    config: WinnerKernelConfig,
    variant_flags: dict[str, str] | None = None,
) -> AlnsRunResult:
    policy = SearchPolicy(require_charging_signal=config.require_charging_signal)
    context = EvaluationContext(
        instance,
        carbon_profile,
        budget=EvalBudget(
            limit=_budget_limit(None, config.eval_budget),
            target=int(config.eval_budget),
        ),
        repair_delta_mode="fast",
    )
    initial_obj = score_reference(initial_solution, context)
    current = best = AlnsState(initial_solution, context, objective_value=initial_obj, policy=policy)
    operator_set = WinnerOperatorSet.create(include_route_elimination=config.include_route_elimination)
    flags = variant_flags or winner_variant_flags(include_route_elimination=config.include_route_elimination)
    selector = _make_operator_selector(len(operator_set.destroy_ops), len(operator_set.repair_ops))
    acceptance = _make_acceptance_criterion(current, _target_iterations(None, config.eval_budget))
    destroy_counts = {name: [0, 0, 0, 0] for name, _ in operator_set.destroy_ops}
    repair_counts = {name: [0, 0, 0, 0] for name, _ in operator_set.repair_ops}
    rng = np.random.default_rng(config.seed)
    target = int(config.eval_budget)
    started = time.perf_counter()
    moves = 0
    while True:
        if context.budget is not None and context.budget.reached_target:
            break
        if context.budget is not None and context.budget.count >= target:
            break
        if time.perf_counter() - started >= float(config.max_runtime_seconds):
            break
        moves += 1
        progress = min(1.0, moves / max(1, target))
        destroy_idx, repair_idx = selector(rng, best, current)
        destroy_name = operator_set.destroy_ops[int(destroy_idx)][0]
        repair_name = operator_set.repair_ops[int(repair_idx)][0]
        previous_obj = current.objective()
        previous_best_obj = best.objective()
        action = WinnerOperatorAction(
            destroy_op_id=destroy_name,
            repair_op_id=repair_name,
            raw_action=(int(destroy_idx), int(repair_idx), -1, -1),
        )
        result = apply_winner_action(
            current.solution,
            action,
            context,
            rng=rng,
            operator_set=operator_set,
            policy=policy,
            current_obj=previous_obj,
            progress=progress,
            variant_flags=flags,
        )
        candidate = result["candidate_state"]
        candidate_obj = float(result["candidate_obj"])
        changed = _solution_changed(current.solution, candidate.solution)
        accepted = changed and bool(acceptance(rng, best, current, candidate))
        best_improved = accepted and candidate_obj < previous_best_obj - 1e-9 and not _hard_violations(candidate.solution, candidate.context)
        better_current = accepted and candidate_obj < previous_obj - 1e-9
        outcome_idx = 3
        if accepted:
            current = candidate
            outcome_idx = 2
            if better_current:
                outcome_idx = 1
            if best_improved:
                best = candidate
                outcome_idx = 0
        destroy_counts[destroy_name][outcome_idx] += 1
        repair_counts[repair_name][outcome_idx] += 1
        selector.update(candidate, int(destroy_idx), int(repair_idx), outcome_idx)
    destroy_counts_out = {name: tuple(row) for name, row in destroy_counts.items()}
    repair_counts_out = {name: tuple(row) for name, row in repair_counts.items()}
    feasible = len(check_solution(best.solution, instance, DEFAULT_PRICES)) == 0
    actual_moves = sum(sum(row) for row in destroy_counts_out.values())
    return AlnsRunResult(
        initial_solution,
        best.solution,
        initial_obj,
        best.objective(),
        context.budget.count if context.budget else 0,
        feasible,
        0.0,
        destroy_counts_out,
        repair_counts_out,
        actual_moves,
        int(context.score_counts.get("candidate", 0)),
        int(context.score_counts.get("repair_delta", 0)),
        int(context.score_counts.get("repair_delta", 0)),
        {"destroy": destroy_counts_out, "repair": repair_counts_out},
    )


@contextmanager
def _temporary_flags(flags: dict[str, str]) -> Iterator[None]:
    old_env = {name: os.environ.get(name) for name in _CRUSH_FLAG_NAMES}
    try:
        for name, value in flags.items():
            os.environ[name] = str(value)
        yield
    finally:
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
