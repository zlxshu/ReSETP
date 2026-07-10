"""Public winner-kernel operator facade for isolated ALNS experiments."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import json
import math
import os
from pathlib import Path
import random
import time
from typing import Any, Callable, Iterator

import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import route_node_schedule
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.solution import Route, Solution
from setp_solver.algorithms.resetp_alns.kernel.alns_core import (
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
from setp_solver.algorithms.resetp_alns.operators.carbon_operators import carbon_related_removal, low_carbon_charging_repair, worst_carbon_removal
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import _apply_strong_alns_destroy_repair
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import solution_signature_hash
from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution
from setp_solver.algorithms.resetp_alns.support.elite_archive import EliteArchive
from setp_solver.search.evaluation import EvalBudget, model_cost, EvaluationContext, score_candidate, score_reference
from setp_solver.algorithms.resetp_alns.support.fleet import UNBOUNDED_FLEET
from setp_solver.algorithms.resetp_alns.support.fleet_charge_corepair import propose_fleet_charge_corepair
from setp_solver.algorithms.resetp_alns.support.global_order_repack import propose_global_order_repack
from setp_solver.algorithms.resetp_alns.operators.local_search import improve_solution_locally, rvnd_swapstar_intensify
from setp_solver.algorithms.resetp_alns.support.route_pool import RoutePool
from setp_solver.algorithms.resetp_alns.runtime import SimulatedAnnealing
from setp_solver.algorithms.resetp_alns.support.timing import TimingLedger, attach_timing_ledger, timed_section

def _load_search_bundle(path):
    from setp_solver.search.bundle import load_search_bundle as _lsb
    return _lsb(path)


def _lazy_run_candidate():
    from setp_solver.search.candidates import run_candidate
    return run_candidate


winner_operator_module = "setp_solver.algorithms.resetp_alns.kernel.winner"
operator_base_id = "winner_kernel_v1"


_CRUSH_FLAG_NAMES = (
    "SETP_ALNS_CRUSH_TRUE_REPAIR",
    "SETP_ALNS_CRUSH_ROUTE_ELIMINATION",
    "SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION",
    "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE",
    "SETP_ALNS_CRUSH_SA_ACCEPTANCE",
    "SETP_ALNS_CRUSH_SA_MODE",
    "SETP_ALNS_CRUSH_LOCAL_SEARCH",
    "SETP_ALNS_CRUSH_ADAPTIVE_Q",
    "SETP_ALNS_CRUSH_SCAN_RESTART",
    "SETP_ALNS_CRUSH_SCAN_REBUILD",
    "SETP_ALNS_CRUSH_ROUTE_COST_CACHE",
    "SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE",
    "SETP_ALNS_CRUSH_TIMING_LEDGER",
    "SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC",
    "SETP_ALNS_CRUSH_STRONG_BRIDGE_BACKEND",
    "SETP_ALNS_CRUSH_BALANCED_SELECTOR",
    "SETP_ALNS_CRUSH_EPS_DECAY_SELECTOR",
    "SETP_ALNS_CRUSH_THOMPSON_SELECTOR",
    "SETP_ALNS_CRUSH_SOFTMAX_SELECTOR",
    "SETP_ALNS_CRUSH_MINIMUM_COVERAGE_SELECTOR",
    "SETP_ALNS_CRUSH_CHAIN_UCB_SELECTOR",
    "SETP_ALNS_CRUSH_ROUTE_POOL_RECOMBINATION",
    "SETP_ALNS_CRUSH_RVND_SWAPSTAR",
    "SETP_ALNS_CRUSH_ELITE_ARCHIVE_RESTART",
    "SETP_ALNS_CRUSH_GLOBAL_ORDER_REPACK",
    "SETP_ALNS_CRUSH_FLEET_CHARGE_COREPAIR",
)

TRACE_DIAGNOSTIC_FLAG = "SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC"
STRONG_BRIDGE_BACKEND_FLAG = "SETP_ALNS_CRUSH_STRONG_BRIDGE_BACKEND"
BALANCED_SELECTOR_FLAG = "SETP_ALNS_CRUSH_BALANCED_SELECTOR"
EPS_DECAY_SELECTOR_FLAG = "SETP_ALNS_CRUSH_EPS_DECAY_SELECTOR"
THOMPSON_SELECTOR_FLAG = "SETP_ALNS_CRUSH_THOMPSON_SELECTOR"
SOFTMAX_SELECTOR_FLAG = "SETP_ALNS_CRUSH_SOFTMAX_SELECTOR"
MINIMUM_COVERAGE_SELECTOR_FLAG = "SETP_ALNS_CRUSH_MINIMUM_COVERAGE_SELECTOR"
CHAIN_UCB_SELECTOR_FLAG = "SETP_ALNS_CRUSH_CHAIN_UCB_SELECTOR"
SELECTOR_FLAGS = (
    BALANCED_SELECTOR_FLAG,
    EPS_DECAY_SELECTOR_FLAG,
    THOMPSON_SELECTOR_FLAG,
    SOFTMAX_SELECTOR_FLAG,
    MINIMUM_COVERAGE_SELECTOR_FLAG,
    CHAIN_UCB_SELECTOR_FLAG,
)
ROUTE_POOL_RECOMBINATION_FLAG = "SETP_ALNS_CRUSH_ROUTE_POOL_RECOMBINATION"
RVND_SWAPSTAR_FLAG = "SETP_ALNS_CRUSH_RVND_SWAPSTAR"
ELITE_ARCHIVE_RESTART_FLAG = "SETP_ALNS_CRUSH_ELITE_ARCHIVE_RESTART"
GLOBAL_ORDER_REPACK_FLAG = "SETP_ALNS_CRUSH_GLOBAL_ORDER_REPACK"
FLEET_CHARGE_COREPAIR_FLAG = "SETP_ALNS_CRUSH_FLEET_CHARGE_COREPAIR"
STRUCTURAL_FLAGS = (
    ROUTE_POOL_RECOMBINATION_FLAG,
    RVND_SWAPSTAR_FLAG,
    ELITE_ARCHIVE_RESTART_FLAG,
    GLOBAL_ORDER_REPACK_FLAG,
    FLEET_CHARGE_COREPAIR_FLAG,
)
_STRONG_BRIDGE_BACKEND_DESTROY_OPS = frozenset(
    {
        "random_customer_removal",
        "shaw_related_removal",
        "worst_customer_removal",
    }
)
_STRONG_BRIDGE_BACKEND_REPAIR_OPS = frozenset(
    {
        "greedy_insert_repair",
        "regret2_insert_repair",
        "regret3_insert_repair",
    }
)


E2_ALNS_COMPONENT_SOURCES = {
    "SETP_ALNS_CRUSH_TRUE_REPAIR": "Ropke-Pisinger/Wu: cost-aware greedy/regret repair",
    "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "Gao GLNS: route elimination large neighborhood",
    "SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION": "Diagnostic: route-compression repair may improve cost before immediate route-count drop",
    "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "Wu/Ropke-Pisinger: non-hillclimbing ALNS acceptance",
    "SETP_ALNS_CRUSH_SA_ACCEPTANCE": "Ropke-Pisinger: simulated annealing acceptance with geometric cooling",
    "SETP_ALNS_CRUSH_SA_MODE": "Ropke-Pisinger/Gao GLNS: SA cooling schedule selector",
    "SETP_ALNS_CRUSH_LOCAL_SEARCH": "VNS/RVND: bounded 2-opt/Or-opt/relocate polishing",
    "SETP_ALNS_CRUSH_ADAPTIVE_Q": "Ropke-Pisinger/Wu: adaptive large destroy size",
    "SETP_ALNS_CRUSH_SCAN_RESTART": "Gao GLNS: scan/sweep all-CV construction restart",
    "SETP_ALNS_CRUSH_SCAN_REBUILD": "Gao GLNS: periodic scan/sweep whole-solution rebuild",
    "SETP_ALNS_CRUSH_ROUTE_COST_CACHE": "Engineering: route-local model-cost cache for E2 throughput profiling",
    "SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE": "Engineering: route/EV repair structure cache for E2 throughput profiling",
    "SETP_ALNS_CRUSH_TIMING_LEDGER": "Engineering: opt-in timing ledger for E2 throughput profiling",
    TRACE_DIAGNOSTIC_FLAG: "Diagnostic only: scheduler/acceptance trace fields; no formal semantics change",
    STRONG_BRIDGE_BACKEND_FLAG: "Diagnostic only: align official ALNS candidate backend with LNS strong bridge for supported destroy/repair pairs",
    BALANCED_SELECTOR_FLAG: "Diagnostic only: balanced operator pair scheduler warmup plus epsilon exploration",
    EPS_DECAY_SELECTOR_FLAG: "Diagnostic only: balanced scheduler with decaying epsilon exploration",
    THOMPSON_SELECTOR_FLAG: "Diagnostic only: Thompson-sampling operator pair scheduler",
    SOFTMAX_SELECTOR_FLAG: "Diagnostic only: softmax operator pair scheduler over AlphaUCB values",
    MINIMUM_COVERAGE_SELECTOR_FLAG: "Diagnostic only: one-pass legal-pair coverage plus sparse structural-family refresh",
    CHAIN_UCB_SELECTOR_FLAG: "Diagnostic only: bounded rewards preserve accepted-move continuity without twenty-point lock-in",
    ROUTE_POOL_RECOMBINATION_FLAG: "Diagnostic only: route-pool recombination on stagnation; candidate still uses existing evaluator/checker",
    RVND_SWAPSTAR_FLAG: "Diagnostic only: bounded RVND/SWAP*-lite intensification on stagnation",
    ELITE_ARCHIVE_RESTART_FLAG: "Diagnostic only: diverse elite archive current-restart on stagnation",
    GLOBAL_ORDER_REPACK_FLAG: "Diagnostic only: global customer-order repack using the shared LNS order decoder",
    FLEET_CHARGE_COREPAIR_FLAG: "Diagnostic only: fleet-type and charging co-repair for complete candidate routes",
}


SA_AUTOFIT_WORSE_PCT = 0.05
SA_AUTOFIT_ACCEPT_PROB = 0.5
SA_TARGET_EVALS_PER_SECOND = 25.0
SA_LNS_PHI = 0.05
SA_LNS_MU = 0.95


@dataclass(frozen=True)
class WinnerKernelConfig:
    """Configuration for reproducible winner-kernel ALNS runs."""

    algorithm: str = "ALNS-Wouda"
    seed: int = 1
    eval_budget: int = 16_000
    max_runtime_seconds: float = 900.0
    require_charging_signal: bool = False
    include_route_elimination: bool = False
    carbon_aware_operators: bool = False
    carbon_operator_bias: float = 0.0


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
    carbon_aware: bool = False
    carbon_bias_weight: float = 0.0

    @classmethod
    def create(
        cls,
        *,
        include_route_elimination: bool = False,
        carbon_aware: bool = False,
        carbon_bias_weight: float = 1.0,
    ) -> "WinnerOperatorSet":
        bias = float(carbon_bias_weight) if carbon_aware else 0.0

        def _with_carbon_bias(fn: Callable[..., AlnsState]) -> Callable[[AlnsState, np.random.Generator], AlnsState]:
            def _wrapped(state: AlnsState, rng: np.random.Generator, **kwargs: Any) -> AlnsState:
                return fn(state, rng, carbon_bias_weight=bias, **kwargs)

            return _wrapped

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
        if carbon_aware:
            destroy_ops.extend(
                [
                    ("worst_carbon_removal", _with_carbon_bias(worst_carbon_removal)),
                    ("carbon_related_removal", _with_carbon_bias(carbon_related_removal)),
                ]
            )
        repair_ops: list[tuple[str, Callable[[AlnsState, np.random.Generator], AlnsState]]] = [
            ("greedy_insert_repair", greedy_insert_repair),
            ("regret2_insert_repair", regret2_insert_repair),
            ("regret3_insert_repair", regret3_insert_repair),
        ]
        if carbon_aware:
            repair_ops.append(("low_carbon_charging_repair", _with_carbon_bias(low_carbon_charging_repair)))
        return cls(tuple(destroy_ops), tuple(repair_ops), bool(include_route_elimination), bool(carbon_aware), bias)

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
        "SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION": "0",
        "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_SA_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_SA_MODE": "off",
        "SETP_ALNS_CRUSH_LOCAL_SEARCH": "0",
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "0",
        "SETP_ALNS_CRUSH_SCAN_RESTART": "0",
        "SETP_ALNS_CRUSH_SCAN_REBUILD": "0",
        "SETP_ALNS_CRUSH_ROUTE_COST_CACHE": "0",
        "SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE": "0",
        "SETP_ALNS_CRUSH_TIMING_LEDGER": "0",
        STRONG_BRIDGE_BACKEND_FLAG: "0",
        BALANCED_SELECTOR_FLAG: "0",
        EPS_DECAY_SELECTOR_FLAG: "0",
        THOMPSON_SELECTOR_FLAG: "0",
        SOFTMAX_SELECTOR_FLAG: "0",
        MINIMUM_COVERAGE_SELECTOR_FLAG: "0",
        ROUTE_POOL_RECOMBINATION_FLAG: "0",
        RVND_SWAPSTAR_FLAG: "0",
        ELITE_ARCHIVE_RESTART_FLAG: "0",
        GLOBAL_ORDER_REPACK_FLAG: "0",
        FLEET_CHARGE_COREPAIR_FLAG: "0",
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
        "SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION": "0",
        "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_SA_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_SA_MODE": "off",
        "SETP_ALNS_CRUSH_LOCAL_SEARCH": "0",
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "1",
        "SETP_ALNS_CRUSH_SCAN_RESTART": "0",
        "SETP_ALNS_CRUSH_SCAN_REBUILD": "0",
        "SETP_ALNS_CRUSH_ROUTE_COST_CACHE": "0",
        "SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE": "0",
        "SETP_ALNS_CRUSH_TIMING_LEDGER": "0",
        STRONG_BRIDGE_BACKEND_FLAG: "0",
        BALANCED_SELECTOR_FLAG: "0",
        EPS_DECAY_SELECTOR_FLAG: "0",
        THOMPSON_SELECTOR_FLAG: "0",
        SOFTMAX_SELECTOR_FLAG: "0",
        MINIMUM_COVERAGE_SELECTOR_FLAG: "0",
        ROUTE_POOL_RECOMBINATION_FLAG: "0",
        RVND_SWAPSTAR_FLAG: "0",
        ELITE_ARCHIVE_RESTART_FLAG: "0",
        GLOBAL_ORDER_REPACK_FLAG: "0",
        FLEET_CHARGE_COREPAIR_FLAG: "0",
    }


def e2_alns_scan_bridge_flags() -> dict[str, str]:
    """Return the 09b GLNS scan-bridge candidate flags."""

    return {
        "SETP_ALNS_CRUSH_TRUE_REPAIR": "1",
        "SETP_ALNS_CRUSH_ROUTE_ELIMINATION": "0",
        "SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION": "0",
        "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_SA_ACCEPTANCE": "0",
        "SETP_ALNS_CRUSH_SA_MODE": "off",
        "SETP_ALNS_CRUSH_LOCAL_SEARCH": "0",
        "SETP_ALNS_CRUSH_ADAPTIVE_Q": "1",
        "SETP_ALNS_CRUSH_SCAN_RESTART": "1",
        "SETP_ALNS_CRUSH_SCAN_REBUILD": "1",
        "SETP_ALNS_CRUSH_ROUTE_COST_CACHE": "0",
        "SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE": "0",
        "SETP_ALNS_CRUSH_TIMING_LEDGER": "0",
        STRONG_BRIDGE_BACKEND_FLAG: "0",
        BALANCED_SELECTOR_FLAG: "0",
        EPS_DECAY_SELECTOR_FLAG: "0",
        THOMPSON_SELECTOR_FLAG: "0",
        SOFTMAX_SELECTOR_FLAG: "0",
        MINIMUM_COVERAGE_SELECTOR_FLAG: "0",
        ROUTE_POOL_RECOMBINATION_FLAG: "0",
        RVND_SWAPSTAR_FLAG: "0",
        ELITE_ARCHIVE_RESTART_FLAG: "0",
        GLOBAL_ORDER_REPACK_FLAG: "0",
        FLEET_CHARGE_COREPAIR_FLAG: "0",
    }


def e2_alns_sa_acceptance_flags(*, mode: str = "autofit") -> dict[str, str]:
    """Return the 09c E2 ALNS SA-acceptance candidate flags."""

    normalized_mode = str(mode).strip().lower().replace("-", "_")
    if normalized_mode not in {"autofit", "lns_cooling"}:
        raise ValueError(f"Unsupported E2 ALNS SA mode: {mode}")
    flags = e2_alns_scan_bridge_flags()
    flags.update(
        {
            "SETP_ALNS_CRUSH_TRUE_ACCEPTANCE": "0",
            "SETP_ALNS_CRUSH_SA_ACCEPTANCE": "1",
            "SETP_ALNS_CRUSH_SA_MODE": normalized_mode,
        }
    )
    return flags


def e2_alns_throughput_flags(
    *,
    route_cost_cache: bool = True,
    repair_structure_cache: bool = True,
    timing_ledger: bool = True,
) -> dict[str, str]:
    """Return the fixed 09d E2 ALNS throughput candidate flags."""

    flags = e2_alns_sa_acceptance_flags(mode="lns_cooling")
    flags.update(
        {
            "SETP_ALNS_CRUSH_ROUTE_COST_CACHE": "1" if route_cost_cache else "0",
            "SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE": "1" if repair_structure_cache else "0",
            "SETP_ALNS_CRUSH_TIMING_LEDGER": "1" if timing_ledger else "0",
        }
    )
    return flags


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


def _strong_bridge_backend_pair_enabled(flags: dict[str, str], destroy_op_id: str, repair_op_id: str) -> bool:
    return (
        _flag_enabled_from(flags, STRONG_BRIDGE_BACKEND_FLAG)
        and str(destroy_op_id) in _STRONG_BRIDGE_BACKEND_DESTROY_OPS
        and str(repair_op_id) in _STRONG_BRIDGE_BACKEND_REPAIR_OPS
    )


def _derive_strong_bridge_rng(rng: np.random.Generator) -> random.Random:
    seed = int(rng.integers(0, np.iinfo(np.int64).max, dtype=np.int64))
    return random.Random(seed)


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
    search_policy = policy or _search_policy_for_instance(context.instance, require_charging_signal=False)
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
    strong_bridge_backend = _strong_bridge_backend_pair_enabled(flags, action.destroy_op_id, action.repair_op_id)
    trace_diagnostic = _trace_diagnostic_enabled(flags)
    local_search_trace: dict[str, Any] | None = {} if trace_diagnostic else None
    revert_reason = "candidate_usable"
    previous_route_count = len(previous_state.solution.routes)
    bridge_metadata: dict[str, Any] = {}
    bridge_detail = "N/A"
    bridge_produced: bool | str = "N/A"
    bridge_feasible: bool | str = "N/A"
    bridge_changed: bool | str = "N/A"
    with _temporary_flags(flags):
        if strong_bridge_backend:
            with timed_section(context, f"strong_bridge_backend:{action.destroy_op_id}+{action.repair_op_id}"):
                bridge_outcome = _apply_strong_alns_destroy_repair(
                    previous_state.solution,
                    context,
                    _derive_strong_bridge_rng(rng),
                    action.destroy_op_id,
                    action.repair_op_id,
                )
            bridge_metadata = dict(getattr(bridge_outcome, "metadata", {}) or {})
            bridge_detail = str(getattr(bridge_outcome, "detail", "") or "")
            bridge_produced = bool(getattr(bridge_outcome, "produced", False))
            bridge_feasible = bool(getattr(bridge_outcome, "feasible", False))
            bridge_changed = bool(getattr(bridge_outcome, "changed", False))
            with timed_section(context, "score:strong_bridge_backend"):
                bridge_obj = float(score_candidate(bridge_outcome.solution, context, label="candidate"))
            candidate = replace(
                previous_state,
                solution=bridge_outcome.solution,
                objective_value=bridge_obj,
                removed_customers=(),
                source_solution=previous_state.solution,
                allow_new_route_repair=True,
            )
        else:
            with timed_section(context, f"destroy:{action.destroy_op_id}"):
                destroyed = destroy_op(
                    previous_state,
                    rng,
                    progress=float(progress),
                    remove_count_q=remove_count_q,
                )
            with timed_section(context, f"repair:{action.repair_op_id}"):
                candidate = repair_op(destroyed, rng)
        candidate, changed, hard_violation_count = _candidate_change_and_violations(
            previous_state,
            candidate,
            trace=local_search_trace,
        )
        relaxed_route_compression = (
            action.destroy_op_id == "route_elimination_removal"
            and _flag_enabled_from(flags, "SETP_ALNS_CRUSH_RELAXED_ROUTE_COMPRESSION")
        )
        if relaxed_route_compression and not _relaxed_route_candidate_usable(previous_state, candidate, changed, hard_violation_count):
            retry_state = replace(destroyed, allow_new_route_repair=True)
            with timed_section(context, f"repair:{action.repair_op_id}:allow_new_route"):
                retry = repair_op(retry_state, rng)
            retry_trace: dict[str, Any] | None = {} if trace_diagnostic else None
            retry, retry_changed, retry_hard_violation_count = _candidate_change_and_violations(
                previous_state,
                retry,
                trace=retry_trace,
            )
            if _relaxed_route_candidate_usable(previous_state, retry, retry_changed, retry_hard_violation_count):
                candidate = retry
                changed = retry_changed
                hard_violation_count = retry_hard_violation_count
                local_search_trace = retry_trace
        previous_obj = previous_state.objective()
        raw_candidate_obj = candidate.objective()
        raw_candidate_route_count = len(candidate.solution.routes)
        raw_changed = bool(changed)
        raw_removed_count = len(candidate.removed_customers)
        raw_hard_violation_count = int(hard_violation_count)
        if action.destroy_op_id == "route_elimination_removal":
            if relaxed_route_compression:
                if candidate.objective() >= previous_obj - 1e-9:
                    revert_reason = "relaxed_route_compression_no_objective_drop"
                    candidate = previous_state
                    changed = False
                    hard_violation_count = 0
            elif len(candidate.solution.routes) >= len(previous_state.solution.routes) or candidate.objective() >= previous_obj - 1e-9:
                revert_reason = "route_elimination_no_route_or_objective_drop"
                candidate = previous_state
                changed = False
                hard_violation_count = 0
        if (
            candidate.removed_customers
            or hard_violation_count
            or not changed
        ):
            if revert_reason == "candidate_usable":
                if candidate.removed_customers:
                    revert_reason = "removed_customers_remaining"
                elif hard_violation_count:
                    revert_reason = "hard_violation"
                else:
                    revert_reason = "unchanged"
            candidate = previous_state
            changed = False
            hard_violation_count = 0
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
        "candidate_backend": "strong_bridge_backend" if strong_bridge_backend else "winner_operator_set",
        "changed": changed,
        "removed_count": len(candidate.removed_customers),
        "hard_violation_count": hard_violation_count,
        "candidate_obj": float(candidate_obj),
        "actual_evals_added": after_evals - before_evals,
    }
    if trace_diagnostic:
        trace.update(
            {
                "previous_obj": float(previous_obj),
                "previous_route_count": previous_route_count,
                "raw_candidate_obj": float(raw_candidate_obj),
                "raw_candidate_route_count": int(raw_candidate_route_count),
                "raw_candidate_route_count_delta": int(raw_candidate_route_count - previous_route_count),
                "raw_changed": bool(raw_changed),
                "raw_removed_count": int(raw_removed_count),
                "raw_hard_violation_count": int(raw_hard_violation_count),
                "candidate_route_count": len(candidate.solution.routes),
                "candidate_route_count_delta": len(candidate.solution.routes) - previous_route_count,
                "revert_reason": revert_reason,
                "strong_bridge_backend_destroy": action.destroy_op_id if strong_bridge_backend else "N/A",
                "strong_bridge_backend_repair": action.repair_op_id if strong_bridge_backend else "N/A",
                "strong_bridge_backend_removed_count": bridge_metadata.get("removed_count", "N/A") if strong_bridge_backend else "N/A",
                "strong_bridge_backend_detail": bridge_detail,
                "strong_bridge_backend_produced": bridge_produced,
                "strong_bridge_backend_feasible": bridge_feasible,
                "strong_bridge_backend_changed": bridge_changed,
                **(local_search_trace or _unknown_local_search_trace()),
            }
        )
    return {
        "operator_base_id": operator_base_id,
        "candidate_solution": candidate.solution,
        "candidate_state": candidate,
        "candidate_obj": float(candidate_obj),
        "actual_evals_added": after_evals - before_evals,
        "changed": bool(changed),
        "hard_violation_count": int(hard_violation_count),
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


def run_e2_alns_scan_bridge(
    bundle_dir: str | Path,
    *,
    config: WinnerKernelConfig | None = None,
    initial_solution: Solution | None = None,
) -> dict[str, Any]:
    """Run the 09b GLNS scan-bridge ALNS candidate."""

    cfg = config or WinnerKernelConfig()
    flags = e2_alns_scan_bridge_flags()
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
        variant_id="e2_alns_scan_bridge",
    )


def run_e2_alns_sa_acceptance(
    bundle_dir: str | Path,
    *,
    config: WinnerKernelConfig | None = None,
    initial_solution: Solution | None = None,
    mode: str = "autofit",
) -> dict[str, Any]:
    """Run the 09c E2 ALNS candidate with standard SA acceptance."""

    cfg = config or WinnerKernelConfig()
    flags = e2_alns_sa_acceptance_flags(mode=mode)
    cfg = WinnerKernelConfig(
        **{
            **asdict(cfg),
            "include_route_elimination": flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] == "1",
        }
    )
    normalized_mode = flags["SETP_ALNS_CRUSH_SA_MODE"]
    return _run_winner_variant(
        bundle_dir,
        cfg,
        initial_solution=initial_solution,
        variant_flags=flags,
        variant_id=f"e2_alns_sa_{normalized_mode}",
    )


def run_e2_alns_throughput(
    bundle_dir: str | Path,
    *,
    config: WinnerKernelConfig | None = None,
    initial_solution: Solution | None = None,
    prices: PriceParameters | None = None,
    route_cost_cache: bool = True,
    repair_structure_cache: bool = True,
    timing_ledger: bool = True,
) -> dict[str, Any]:
    """Run the 09d E2 ALNS throughput candidate."""

    cfg = config or WinnerKernelConfig()
    flags = e2_alns_throughput_flags(route_cost_cache=route_cost_cache, repair_structure_cache=repair_structure_cache, timing_ledger=timing_ledger)
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
        prices=prices,
        variant_flags=flags,
        variant_id="e2_alns_throughput",
    )


def run_e2_alns_carbon(
    bundle_dir: str | Path,
    *,
    config: WinnerKernelConfig | None = None,
    initial_solution: Solution | None = None,
    prices: PriceParameters | None = None,
    carbon_bias_weight: float = 1.0,
    variant_id: str = "alns_e2_carbon",
    route_cost_cache: bool = True,
    repair_structure_cache: bool = True,
    timing_ledger: bool = True,
) -> dict[str, Any]:
    """Run the 09x carbon-aware ALNS probe variant."""

    cfg = config or WinnerKernelConfig()
    flags = e2_alns_throughput_flags(route_cost_cache=route_cost_cache, repair_structure_cache=repair_structure_cache, timing_ledger=timing_ledger)
    flags["SETP_ALNS_CARBON_OPERATORS"] = "1"
    flags["SETP_ALNS_CARBON_OPERATOR_BIAS"] = str(float(carbon_bias_weight))
    cfg = WinnerKernelConfig(
        **{
            **asdict(cfg),
            "include_route_elimination": flags["SETP_ALNS_CRUSH_ROUTE_ELIMINATION"] == "1",
            "carbon_aware_operators": True,
            "carbon_operator_bias": float(carbon_bias_weight),
        }
    )
    return _run_winner_variant(
        bundle_dir,
        cfg,
        initial_solution=initial_solution,
        prices=prices,
        variant_flags=flags,
        variant_id=variant_id,
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
            "e2_alns_sa_acceptance_flags",
            "e2_alns_scan_bridge_flags",
            "e2_alns_throughput_flags",
            "e2_alns_variant_flags",
            "run_e2_alns_sa_acceptance",
            "run_e2_alns_scan_bridge",
            "run_e2_alns_carbon",
            "run_e2_alns_throughput",
            "scan_all_cv_solution",
            "winner_variant_flags",
            "run_e2_alns_final",
            "run_winner_kernel",
            "run_winner_kernel_plus_route_elimination",
            "write_winner_manifest",
        ],
        "default_flags": winner_variant_flags(include_route_elimination=False),
        "route_elimination_flags": winner_variant_flags(include_route_elimination=True),
        "e2_alns_flags": e2_alns_variant_flags(),
        "e2_alns_scan_bridge_flags": e2_alns_scan_bridge_flags(),
        "e2_alns_sa_acceptance_flags": {
            "autofit": e2_alns_sa_acceptance_flags(mode="autofit"),
            "lns_cooling": e2_alns_sa_acceptance_flags(mode="lns_cooling"),
        },
        "e2_alns_throughput_flags": e2_alns_throughput_flags(),
        "e2_alns_carbon_flags": {
            **e2_alns_throughput_flags(),
            "SETP_ALNS_CARBON_OPERATORS": "1",
            "SETP_ALNS_CARBON_OPERATOR_BIAS": "1.0",
        },
        "e2_alns_component_sources": E2_ALNS_COMPONENT_SOURCES,
        "compatible_instances": ["L-main"],
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
    prices: PriceParameters | None = None,
    variant_flags: dict[str, str] | None = None,
    variant_id: str = "winner_kernel",
) -> dict[str, Any]:
    started = time.perf_counter()
    bundle = _load_search_bundle(bundle_dir)
    effective_prices = prices or DEFAULT_PRICES
    warm = initial_solution or build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        effective_prices,
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
                prices=effective_prices,
                variant_flags=flags,
            )
            solution = run.best_solution
            evaluations = run.evaluations
        elif config.algorithm == "DR-ALNS":
            run = _lazy_run_candidate()(
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
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=effective_prices)
    violations = check_solution(solution, bundle.instance, effective_prices)
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
        "history": list(getattr(run, "history", [])) if config.algorithm == "ALNS-Wouda" else [],
        "operator_counts": getattr(run, "operator_counts", {}) if config.algorithm == "ALNS-Wouda" else {},
        "timings": getattr(run, "operator_counts", {}).get("timing", {}) if config.algorithm == "ALNS-Wouda" else {},
    }


def _run_winner_kernel_loop(
    initial_solution: Solution,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    *,
    config: WinnerKernelConfig,
    prices: PriceParameters | None = None,
    variant_flags: dict[str, str] | None = None,
) -> AlnsRunResult:
    policy = _search_policy_for_instance(instance, require_charging_signal=config.require_charging_signal)
    effective_prices = prices or DEFAULT_PRICES
    context = EvaluationContext(
        instance,
        carbon_profile,
        prices=effective_prices,
        budget=EvalBudget(
            limit=_budget_limit(None, config.eval_budget),
            target=int(config.eval_budget),
        ),
        repair_delta_mode="fast",
    )
    flags = variant_flags or winner_variant_flags(include_route_elimination=config.include_route_elimination)
    object.__setattr__(
        instance,
        "_setp_repair_structure_cache_enabled",
        _flag_enabled_from(flags, "SETP_ALNS_CRUSH_REPAIR_STRUCTURE_CACHE"),
    )
    trace_diagnostic = _trace_diagnostic_enabled(flags)
    structural_component = structural_component_from_flags(flags)
    ledger: TimingLedger | None = attach_timing_ledger(context) if _flag_enabled_from(flags, "SETP_ALNS_CRUSH_TIMING_LEDGER") else None
    with timed_section(context, "initial_reference_score"):
        initial_obj = score_reference(initial_solution, context)
    current = best = AlnsState(initial_solution, context, objective_value=initial_obj, policy=policy)
    route_pool = RoutePool(max_routes=512) if structural_component == "route_pool" else None
    elite_archive = EliteArchive(max_size=16, diversity_min=0.10) if structural_component == "elite_archive" else None
    if route_pool is not None:
        route_pool.record_solution(current.solution, objective=current.objective())
    if elite_archive is not None:
        elite_archive.maybe_add(current.solution, objective=current.objective())
    operator_set = WinnerOperatorSet.create(
        include_route_elimination=config.include_route_elimination,
        carbon_aware=config.carbon_aware_operators,
        carbon_bias_weight=config.carbon_operator_bias,
    )
    selector_kind = _selector_kind_from_flags(flags)
    selector_coupling, protected_destroy_indices = _minimum_coverage_contract(operator_set, selector_kind)
    selector = _make_operator_selector(
        len(operator_set.destroy_ops),
        len(operator_set.repair_ops),
        selector_kind=selector_kind,
        balanced=_flag_enabled_from(flags, BALANCED_SELECTOR_FLAG),
        target_iterations=int(config.eval_budget),
        op_coupling=selector_coupling,
        protected_destroy_indices=protected_destroy_indices,
    )
    acceptance = _make_winner_acceptance_criterion(current, config=config, flags=flags)
    destroy_counts = {name: [0, 0, 0, 0] for name, _ in operator_set.destroy_ops}
    repair_counts = {name: [0, 0, 0, 0] for name, _ in operator_set.repair_ops}
    scan_counts = {
        "restart_attempts": 0,
        "restart_accepts": 0,
        "rebuild_attempts": 0,
        "rebuild_accepts": 0,
        "infeasible": 0,
    }
    rng = np.random.default_rng(config.seed)
    target = int(config.eval_budget)
    started = time.perf_counter()
    history = [
        _winner_history_entry(
            context,
            best.solution,
            best.objective(),
            0,
            started,
            "shared_warm_start",
            include_trace_fields=trace_diagnostic,
        )
    ]
    candidate_trace: list[dict[str, Any]] = []
    structural_counts = {"attempts": 0, "accepted": 0, "best_improved": 0, "rejected": 0}
    _maybe_write_e2_checkpoint(best.solution, context, best.objective(), 0, started, "shared_warm_start")
    moves = 0
    scan_attempts = 0
    moves_since_best_improvement = 0
    if _flag_enabled_from(flags, "SETP_ALNS_CRUSH_SCAN_RESTART") and _can_consume_scan_eval(context, target):
        scan_state = _scan_restart_state(current, offset=scan_attempts, counter=scan_counts, counter_prefix="restart")
        scan_attempts += 1
        if scan_state is not None and scan_state.objective() < current.objective() - 1e-9:
            current = scan_state
            scan_counts["restart_accepts"] += 1
            if scan_state.objective() < best.objective() - 1e-9:
                best = scan_state
                history.append(
                    _winner_history_entry(
                        context,
                        best.solution,
                        best.objective(),
                        context.budget.count if context.budget else 0,
                        started,
                        "scan_restart",
                        include_trace_fields=trace_diagnostic,
                    )
                )
    while True:
        if context.budget is not None and context.budget.reached_target:
            break
        if context.budget is not None and context.budget.count >= target:
            break
        if time.perf_counter() - started >= float(config.max_runtime_seconds):
            break
        moves += 1
        if (
            _flag_enabled_from(flags, "SETP_ALNS_CRUSH_SCAN_REBUILD")
            and moves_since_best_improvement >= _scan_rebuild_interval(target)
            and _can_consume_scan_eval(context, target)
        ):
            scan_state = _scan_restart_state(current, offset=scan_attempts, counter=scan_counts, counter_prefix="rebuild")
            scan_attempts += 1
            moves_since_best_improvement = 0
            if scan_state is not None and scan_state.objective() < current.objective() - 1e-9:
                current = scan_state
                scan_counts["rebuild_accepts"] += 1
                if scan_state.objective() < best.objective() - 1e-9:
                    best = scan_state
                    history.append(
                        _winner_history_entry(
                            context,
                            best.solution,
                            best.objective(),
                            context.budget.count if context.budget else 0,
                            started,
                            "scan_rebuild",
                            include_trace_fields=trace_diagnostic,
                        )
                    )
                continue
        if context.budget is not None and context.budget.reached_target:
            break
        if (
            structural_component in {"route_pool", "elite_archive", "global_order_repack", "fleet_charge_corepair"}
            and _structural_component_due(structural_component, moves=moves, moves_since_best_improvement=moves_since_best_improvement, target=target)
            and _can_consume_scan_eval(context, target)
        ):
            proposal: Solution | None = None
            structural_operator = structural_component
            structural_trace: dict[str, Any] = {}
            if route_pool is not None:
                proposal = route_pool.recombine(set(_customers_in_solution(current.solution, instance)))
                structural_operator = "route_pool_recombination"
            elif elite_archive is not None:
                proposal = elite_archive.propose_restart(_derive_strong_bridge_rng(rng))
                structural_operator = "elite_archive_restart"
            elif structural_component == "global_order_repack":
                structural_operator = "global_order_repack"
                outcome = propose_global_order_repack(current.solution, best.solution, context, _derive_strong_bridge_rng(rng))
                proposal = outcome.solution
                structural_trace.update(
                    {
                        "repack_attempts": int(outcome.attempts),
                        "repack_feasible": int(outcome.feasible),
                        "repack_accepted": bool(outcome.accepted),
                        "repack_best_improved": bool(outcome.best_improved),
                        "repack_route_count_delta": int(outcome.route_count_delta),
                        "repack_cost_fix_delta": float(outcome.cost_fix_delta),
                        "repack_order_source": outcome.order_source,
                        "repack_trace_rows": outcome.trace_rows,
                    }
                )
            elif structural_component == "fleet_charge_corepair":
                structural_operator = "fleet_charge_corepair"
                outcome = propose_fleet_charge_corepair(current.solution, context, max_attempts=16)
                proposal = outcome.solution
                if proposal is None and best.solution is not current.solution:
                    outcome = propose_fleet_charge_corepair(best.solution, context, max_attempts=16)
                    proposal = outcome.solution
                structural_trace.update(
                    {
                        "fleet_charge_attempts": int(outcome.attempts),
                        "fleet_charge_feasible": int(outcome.feasible),
                        "fleet_charge_accepted": bool(outcome.accepted),
                        "fleet_charge_best_improved": bool(outcome.best_improved),
                        "fleet_charge_source_route_type": outcome.source_route_type,
                        "fleet_charge_target_route_type": outcome.target_route_type,
                        "fleet_charge_fuel_delta": float(outcome.fuel_delta),
                        "fleet_charge_electric_delta": float(outcome.electric_delta),
                        "fleet_charge_carbon_delta": float(outcome.carbon_delta),
                        "fleet_charge_fixed_delta": float(outcome.fixed_delta),
                        "fleet_charge_route_index": int(outcome.route_index),
                        "fleet_charge_trace_rows": outcome.trace_rows,
                    }
                )
            structural_counts["attempts"] += 1
            previous_obj = current.objective()
            previous_best_obj = best.objective()
            hard_violation_count = 1
            changed = False
            accepted = False
            candidate_obj = math.inf
            if proposal is not None:
                with timed_section(context, structural_operator):
                    candidate_obj = float(score_candidate(proposal, context, label="candidate"))
                candidate = AlnsState(proposal, context, objective_value=candidate_obj, policy=policy)
                hard_violation_count = _hard_violation_count(candidate.solution, candidate.context)
                changed = _solution_changed(current.solution, candidate.solution)
                with timed_section(context, "acceptance"):
                    accepted = changed and hard_violation_count == 0 and bool(acceptance(rng, best, current, candidate))
                best_improved = accepted and candidate_obj < previous_best_obj - 1e-9
                better_current = accepted and candidate_obj < previous_obj - 1e-9
                if accepted:
                    current = candidate
                    structural_counts["accepted"] += 1
                    if route_pool is not None:
                        route_pool.record_solution(current.solution, objective=current.objective())
                    if elite_archive is not None:
                        elite_archive.maybe_add(current.solution, objective=current.objective())
                    if best_improved:
                        best = candidate
                        structural_counts["best_improved"] += 1
                        history.append(
                            _winner_history_entry(
                                context,
                                best.solution,
                                best.objective(),
                                context.budget.count if context.budget else 0,
                                started,
                                structural_operator,
                                include_trace_fields=trace_diagnostic,
                            )
                        )
                        _maybe_write_e2_checkpoint(
                            best.solution,
                            context,
                            best.objective(),
                            context.budget.count if context.budget else 0,
                            started,
                            structural_operator,
                        )
                else:
                    structural_counts["rejected"] += 1
                if trace_diagnostic:
                    candidate_trace.append(
                        {
                            "operator_base_id": operator_base_id,
                            "winner_operator_module": winner_operator_module,
                            "move": int(moves),
                            "eval": int(context.budget.count if context.budget else 0),
                            "destroy_id": structural_operator,
                            "repair_id": structural_operator,
                            "candidate_backend": structural_operator,
                            "changed": bool(changed),
                            "removed_count": 0,
                            "hard_violation_count": int(hard_violation_count),
                            "candidate_obj": float(candidate_obj),
                            "previous_obj": float(previous_obj),
                            "previous_best_obj": float(previous_best_obj),
                            "accepted": bool(accepted),
                            "best_improved": bool(best_improved),
                            "accepted_worse": bool(accepted and candidate_obj > previous_obj + 1e-9),
                            "better_current": bool(better_current),
                            "outcome_candidate_obj": float(candidate_obj),
                            "outcome_hard_violation_count": int(hard_violation_count),
                            "revert_reason": "candidate_usable" if accepted else "structural_not_accepted",
                            "structural_component": structural_component,
                            **structural_trace,
                        }
                    )
                moves_since_best_improvement = 0
                continue
            structural_counts["rejected"] += 1
            if trace_diagnostic:
                candidate_trace.append(
                    {
                        "operator_base_id": operator_base_id,
                        "winner_operator_module": winner_operator_module,
                        "move": int(moves),
                        "eval": int(context.budget.count if context.budget else 0),
                        "destroy_id": structural_operator,
                        "repair_id": structural_operator,
                        "candidate_backend": structural_operator,
                        "changed": False,
                        "removed_count": 0,
                        "hard_violation_count": 1,
                        "candidate_obj": math.inf,
                        "previous_obj": float(previous_obj),
                        "previous_best_obj": float(previous_best_obj),
                        "accepted": False,
                        "best_improved": False,
                        "accepted_worse": False,
                        "better_current": False,
                        "outcome_candidate_obj": math.inf,
                        "outcome_hard_violation_count": 1,
                        "revert_reason": "structural_no_candidate",
                        "structural_component": structural_component,
                        **structural_trace,
                    }
                )
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
        if (
            structural_component == "rvnd_swapstar"
            and moves_since_best_improvement >= 3 * _structural_rescue_interval(target)
            and moves >= _structural_late_stage_start(target)
            and not candidate.removed_customers
            and int(result.get("hard_violation_count", 0)) == 0
            and _solution_changed(current.solution, candidate.solution)
            and _can_consume_scan_eval(context, target)
        ):
            with timed_section(context, "rvnd_swapstar"):
                rvnd_result = rvnd_swapstar_intensify(candidate.solution, context, max_moves=4)
            if rvnd_result.solution is not None and _solution_changed(candidate.solution, rvnd_result.solution):
                rvnd_obj = float(score_candidate(rvnd_result.solution, context, label="candidate"))
                if rvnd_obj < candidate_obj - 1e-9:
                    candidate = replace(candidate, solution=rvnd_result.solution, objective_value=rvnd_obj)
                    candidate_obj = rvnd_obj
                    result["candidate_state"] = candidate
                    result["candidate_obj"] = candidate_obj
                    result["trace"].update(
                        {
                            "structural_component": "rvnd_swapstar",
                            "rvnd_swapstar_attempted": True,
                            "rvnd_swapstar_improved": True,
                            "rvnd_swapstar_moves_used": rvnd_result.moves_used,
                            "rvnd_swapstar_improve_count": rvnd_result.improve_count,
                            "rvnd_swapstar_time_seconds": rvnd_result.time_seconds,
                            "rvnd_swapstar_route_count_delta": rvnd_result.route_count_delta,
                        }
                    )
                else:
                    result["trace"].update(
                        {
                            "structural_component": "rvnd_swapstar",
                            "rvnd_swapstar_attempted": True,
                            "rvnd_swapstar_improved": False,
                            "rvnd_swapstar_moves_used": rvnd_result.moves_used,
                            "rvnd_swapstar_improve_count": rvnd_result.improve_count,
                            "rvnd_swapstar_time_seconds": rvnd_result.time_seconds,
                            "rvnd_swapstar_route_count_delta": rvnd_result.route_count_delta,
                        }
                    )
        changed = _solution_changed(current.solution, candidate.solution)
        with timed_section(context, "acceptance"):
            accepted = changed and bool(acceptance(rng, best, current, candidate))
        hard_violation_count = int(result.get("hard_violation_count", _hard_violation_count(candidate.solution, candidate.context)))
        best_improved = accepted and candidate_obj < previous_best_obj - 1e-9 and hard_violation_count == 0
        better_current = accepted and candidate_obj < previous_obj - 1e-9
        if trace_diagnostic:
            trace_row = dict(result.get("trace", {}))
            selector_info = selector.last_selection_info() if hasattr(selector, "last_selection_info") else {}
            trace_row.update(
                {
                    "move": int(moves),
                    "eval": int(context.budget.count if context.budget else 0),
                    "previous_best_obj": float(previous_best_obj),
                    "accepted": bool(accepted),
                    "best_improved": bool(best_improved),
                    "accepted_worse": bool(accepted and candidate_obj > previous_obj + 1e-9),
                    "better_current": bool(better_current),
                    "outcome_candidate_obj": float(candidate_obj),
                    "outcome_hard_violation_count": int(hard_violation_count),
                }
            )
            trace_row.update(selector_info)
            candidate_trace.append(trace_row)
        outcome_idx = 3
        if accepted:
            current = candidate
            if route_pool is not None:
                route_pool.record_solution(current.solution, objective=current.objective())
            if elite_archive is not None:
                elite_archive.maybe_add(current.solution, objective=current.objective())
            outcome_idx = 2
            if better_current:
                outcome_idx = 1
            if best_improved:
                best = candidate
                if route_pool is not None:
                    route_pool.record_solution(best.solution, objective=best.objective())
                if elite_archive is not None:
                    elite_archive.maybe_add(best.solution, objective=best.objective())
                outcome_idx = 0
                moves_since_best_improvement = 0
                history.append(
                    _winner_history_entry(
                        context,
                        best.solution,
                        best.objective(),
                        context.budget.count if context.budget else 0,
                        started,
                        f"{destroy_name}+{repair_name}",
                        include_trace_fields=trace_diagnostic,
                    )
                )
                _maybe_write_e2_checkpoint(
                    best.solution,
                    context,
                    best.objective(),
                    context.budget.count if context.budget else 0,
                    started,
                    f"{destroy_name}+{repair_name}",
                )
        if not best_improved:
            moves_since_best_improvement += 1
        destroy_counts[destroy_name][outcome_idx] += 1
        repair_counts[repair_name][outcome_idx] += 1
        selector.update(candidate, int(destroy_idx), int(repair_idx), outcome_idx)
    destroy_counts_out = {name: tuple(row) for name, row in destroy_counts.items()}
    repair_counts_out = {name: tuple(row) for name, row in repair_counts.items()}
    with timed_section(context, "final_check"):
        feasible = len(check_solution(best.solution, instance, effective_prices)) == 0
    actual_moves = sum(sum(row) for row in destroy_counts_out.values())
    timing_snapshot = ledger.snapshot() if ledger is not None else {}
    operator_counts_out = {
        "destroy": destroy_counts_out,
        "repair": repair_counts_out,
        "scan": dict(scan_counts),
        "timing": timing_snapshot,
        "structural": dict(structural_counts),
        "score_counts": dict(context.score_counts),
    }
    if trace_diagnostic:
        operator_counts_out["candidate_trace"] = candidate_trace
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
        operator_counts_out,
        history,
    )


def _search_policy_for_instance(instance: Any, *, require_charging_signal: bool) -> SearchPolicy:
    return SearchPolicy(
        require_charging_signal=bool(require_charging_signal),
        max_cv=_instance_fleet_limit(instance, "num_cv"),
        max_ev=_instance_fleet_limit(instance, "num_ev"),
    )


def _instance_fleet_limit(instance: Any, attr: str) -> int:
    value = getattr(instance, attr, None)
    if value is None:
        return UNBOUNDED_FLEET
    return int(float(value))


def _make_winner_acceptance_criterion(initial_state: AlnsState, *, config: WinnerKernelConfig, flags: dict[str, str]) -> Any:
    if not _flag_enabled_from(flags, "SETP_ALNS_CRUSH_SA_ACCEPTANCE"):
        with _temporary_flags(flags):
            return _make_acceptance_criterion(initial_state, _target_iterations(None, config.eval_budget))

    mode = str(flags.get("SETP_ALNS_CRUSH_SA_MODE", "autofit")).strip().lower().replace("-", "_")
    initial_obj = max(1.0, abs(float(initial_state.objective())))
    if mode == "autofit":
        return SimulatedAnnealing.autofit(
            initial_obj,
            SA_AUTOFIT_WORSE_PCT,
            SA_AUTOFIT_ACCEPT_PROB,
            _sa_target_iterations(config),
            method="exponential",
        )
    if mode == "lns_cooling":
        start_temperature = max(1e-9, -SA_LNS_PHI * initial_obj / math.log(0.5))
        return SimulatedAnnealing(start_temperature, 1e-9, SA_LNS_MU, method="exponential")
    raise ValueError(f"Unsupported E2 ALNS SA mode: {mode}")


def _sa_target_iterations(config: WinnerKernelConfig) -> int:
    return min(int(config.eval_budget), max(100, int(float(config.max_runtime_seconds) * SA_TARGET_EVALS_PER_SECOND)))


def _winner_history_entry(
    context: EvaluationContext,
    solution: Solution,
    objective: float,
    eval_count: int,
    started: float,
    operator: str,
    *,
    include_trace_fields: bool = False,
) -> dict[str, Any]:
    with timed_section(context, "history_model_cost"):
        best_cost = float(model_cost(solution, context))
    row = {
        "eval": int(eval_count),
        "time_seconds": max(0.0, time.perf_counter() - started),
        "best_cost": best_cost,
        "best_obj": float(objective),
        "operator": str(operator),
    }
    if include_trace_fields:
        row["route_count"] = len(solution.routes)
        row["signature"] = solution_signature_hash(solution)
    return row


def _flag_enabled_from(flags: dict[str, str], name: str) -> bool:
    return str(flags.get(name, "0")).lower() not in {"0", "false", "no"}


def _selector_kind_from_flags(flags: dict[str, str]) -> str:
    enabled = [name for name in SELECTOR_FLAGS if _flag_enabled_from(flags, name)]
    if len(enabled) > 1:
        raise ValueError(f"HALT_CONFIG_CONFLICT_SELECTOR_FLAGS:{','.join(enabled)}")
    if not enabled:
        return "alpha_ucb"
    mapping = {
        BALANCED_SELECTOR_FLAG: "balanced",
        EPS_DECAY_SELECTOR_FLAG: "eps_decay",
        THOMPSON_SELECTOR_FLAG: "thompson",
        SOFTMAX_SELECTOR_FLAG: "softmax",
        MINIMUM_COVERAGE_SELECTOR_FLAG: "minimum_coverage",
        CHAIN_UCB_SELECTOR_FLAG: "chain_ucb",
    }
    return mapping[enabled[0]]


def _minimum_coverage_contract(
    operator_set: WinnerOperatorSet,
    selector_kind: str,
) -> tuple[np.ndarray | None, tuple[int, ...]]:
    coupling = _selector_coupling_contract(operator_set)
    if selector_kind != "minimum_coverage":
        return coupling, ()
    destroy_names = [name for name, _ in operator_set.destroy_ops]
    protected = tuple(
        destroy_names.index(name)
        for name in ("whole_route_removal", "route_segment_removal", "vehicle_type_swap")
        if name in destroy_names
    )
    return coupling, protected


def _selector_coupling_contract(operator_set: WinnerOperatorSet) -> np.ndarray:
    destroy_names = [name for name, _ in operator_set.destroy_ops]
    repair_count = len(operator_set.repair_ops)
    coupling = np.ones((len(destroy_names), repair_count), dtype=bool)
    vehicle_idx = destroy_names.index("vehicle_type_swap")
    if repair_count > 1:
        coupling[vehicle_idx, 1:] = False
    return coupling


def structural_component_from_flags(flags: dict[str, str] | None = None) -> str | None:
    active_flags = flags or {}
    enabled = [name for name in STRUCTURAL_FLAGS if _flag_enabled_from(active_flags, name)]
    if len(enabled) > 1:
        raise ValueError(f"HALT_CONFIG_CONFLICT_STRUCTURAL_FLAGS:{','.join(enabled)}")
    if not enabled:
        return None
    mapping = {
        ROUTE_POOL_RECOMBINATION_FLAG: "route_pool",
        RVND_SWAPSTAR_FLAG: "rvnd_swapstar",
        ELITE_ARCHIVE_RESTART_FLAG: "elite_archive",
        GLOBAL_ORDER_REPACK_FLAG: "global_order_repack",
        FLEET_CHARGE_COREPAIR_FLAG: "fleet_charge_corepair",
    }
    return mapping[enabled[0]]


def _trace_diagnostic_enabled(flags: dict[str, str] | None = None) -> bool:
    if flags is not None and TRACE_DIAGNOSTIC_FLAG in flags:
        return _flag_enabled_from(flags, TRACE_DIAGNOSTIC_FLAG)
    return os.environ.get(TRACE_DIAGNOSTIC_FLAG, "0").lower() not in {"0", "false", "no"}


def _unknown_local_search_trace() -> dict[str, Any]:
    return {
        "local_search_attempted": False,
        "local_search_improved": "UNKNOWN",
        "local_search_obj_before": "UNKNOWN",
        "local_search_obj_after": "UNKNOWN",
        "local_search_route_count_before": "UNKNOWN",
        "local_search_route_count_after": "UNKNOWN",
        "local_search_route_count_delta": "UNKNOWN",
    }


def _candidate_change_and_violations(
    previous_state: AlnsState,
    candidate: AlnsState,
    *,
    trace: dict[str, Any] | None = None,
) -> tuple[AlnsState, bool, int]:
    changed = _solution_changed(previous_state.solution, candidate.solution)
    hard_violation_count = _hard_violation_count(candidate.solution, candidate.context) if not candidate.removed_customers else 1
    if trace is not None:
        trace.update(_unknown_local_search_trace())
    if not candidate.removed_customers and hard_violation_count == 0 and changed:
        before_solution = candidate.solution
        before_obj = candidate.objective()
        with timed_section(candidate.context, "local_search"):
            improved_solution = improve_solution_locally(candidate.solution, candidate.context)
        if trace is not None:
            improved = _solution_changed(before_solution, improved_solution)
            after_state = replace(candidate, solution=improved_solution, objective_value=None) if improved else candidate
            trace.update(
                {
                    "local_search_attempted": True,
                    "local_search_improved": bool(improved),
                    "local_search_obj_before": float(before_obj),
                    "local_search_obj_after": float(after_state.objective()),
                    "local_search_route_count_before": len(before_solution.routes),
                    "local_search_route_count_after": len(improved_solution.routes),
                    "local_search_route_count_delta": len(improved_solution.routes) - len(before_solution.routes),
                }
            )
        if _solution_changed(candidate.solution, improved_solution):
            candidate = replace(candidate, solution=improved_solution, objective_value=None)
            changed = _solution_changed(previous_state.solution, candidate.solution)
            hard_violation_count = _hard_violation_count(candidate.solution, candidate.context)
    return candidate, changed, hard_violation_count


def _relaxed_route_candidate_usable(
    previous_state: AlnsState,
    candidate: AlnsState,
    changed: bool,
    hard_violation_count: int,
) -> bool:
    if candidate.removed_customers or hard_violation_count or not changed:
        return False
    return candidate.objective() < previous_state.objective() - 1e-9


def _hard_violation_count(solution: Solution, context: EvaluationContext) -> int:
    breakdown = context.score_breakdowns.get(id(solution), {})
    if "violation_count" in breakdown:
        return int(breakdown["violation_count"])
    return len(_hard_violations(solution, context))


def _maybe_write_e2_checkpoint(
    solution: Solution,
    context: EvaluationContext,
    objective: float,
    eval_count: int,
    started: float,
    operator: str,
) -> None:
    path_text = os.environ.get("SETP_E2_ALNS_CHECKPOINT_PATH", "").strip()
    if not path_text:
        return
    path = Path(path_text)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with timed_section(context, "checkpoint_model_cost"):
            cost = float(model_cost(solution, context))
        payload = {
            "schema_version": "setp-e2-checkpoint.v1",
            "eval": int(eval_count),
            "time_seconds": max(0.0, time.perf_counter() - started),
            "best_cost": cost,
            "best_obj": float(objective),
            "operator": str(operator),
            "solution": asdict(solution),
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        return


def _scan_rebuild_interval(target: int) -> int:
    return max(25, min(250, int(target) // 20))


def _structural_rescue_interval(target: int) -> int:
    return max(40, min(300, int(target) // 24))


def _structural_late_stage_start(target: int) -> int:
    return max(1, int(0.75 * int(target)))


def _structural_component_due(
    component: str | None,
    *,
    moves: int,
    moves_since_best_improvement: int,
    target: int,
) -> bool:
    interval = _structural_rescue_interval(target)
    late_stage = _structural_late_stage_start(target)
    if component in {"global_order_repack", "fleet_charge_corepair"}:
        return moves_since_best_improvement >= interval or (moves >= late_stage and moves % interval == 0)
    return moves_since_best_improvement >= interval and moves >= late_stage


def _can_consume_scan_eval(context: EvaluationContext, target: int) -> bool:
    return context.budget is None or context.budget.count < int(target)


def _scan_restart_state(
    state: AlnsState,
    *,
    offset: int,
    counter: dict[str, int],
    counter_prefix: str,
) -> AlnsState | None:
    counter[f"{counter_prefix}_attempts"] += 1
    with timed_section(state.context, "scan_build"):
        solution = scan_all_cv_solution(state.context.instance, offset=offset, prices=state.context.prices)
    with timed_section(state.context, "scan_score"):
        objective = float(score_candidate(solution, state.context, label="candidate"))
    breakdown = state.context.score_breakdowns.get(id(solution), {})
    if int(breakdown.get("violation_count", 0)) != 0:
        counter["infeasible"] += 1
        return None
    candidate = replace(
        state,
        solution=solution,
        objective_value=objective,
        removed_customers=(),
        source_solution=None,
        allow_new_route_repair=True,
    )
    return candidate


def scan_all_cv_solution(instance: Any, *, offset: int = 0, prices: PriceParameters | None = None) -> Solution:
    """Build a deterministic GLNS-style sweep all-CV solution."""

    effective_prices = prices or DEFAULT_PRICES
    ordered = _scan_sweep_order(instance, offset=offset)
    depots = _scan_depots(instance)
    if not depots:
        return Solution(routes=[])
    node_lookup = {node.node_id: node for node in instance.nodes}
    depots_by_customer = {
        customer_id: tuple(
            depot.node_id
            for depot in sorted(
                depots,
                key=lambda depot, cid=customer_id: (float(instance.distance(depot.node_id, cid)), depot.node_id),
            )
        )
        for customer_id in ordered
    }
    plans: dict[str, list[list[str]]] = {depot.node_id: [] for depot in depots}
    for customer_id in ordered:
        _append_scan_customer(instance, node_lookup, depots_by_customer, plans, customer_id, effective_prices)
    routes: list[Route] = []
    next_cv = 1
    for depot_id, depot_plans in sorted(plans.items()):
        for customer_ids in depot_plans:
            routes.append(Route(f"CV{next_cv}", "cv", depot_id, [depot_id, *customer_ids, depot_id]))
            next_cv += 1
    return Solution(routes=routes)


def _scan_sweep_order(instance: Any, *, offset: int = 0) -> list[str]:
    depots = _scan_depots(instance)
    if depots:
        cx = sum(float(node.x) for node in depots) / len(depots)
        cy = sum(float(node.y) for node in depots) / len(depots)
    else:
        cx = cy = 0.0
    customers = [node for node in instance.nodes if node.node_type.lower() == "c"]
    ordered = [
        node.node_id
        for node in sorted(
            customers,
            key=lambda node: (
                math.atan2(float(node.y) - cy, float(node.x) - cx),
                float(node.demand),
                node.node_id,
            ),
        )
    ]
    if not ordered:
        return []
    shift = int(offset) % len(ordered)
    return [*ordered[shift:], *ordered[:shift]]


def _scan_depots(instance: Any) -> list[Any]:
    return sorted((node for node in instance.nodes if node.node_type.lower() == "d"), key=lambda node: node.node_id)


def _append_scan_customer(
    instance: Any,
    node_lookup: dict[str, Any],
    depots_by_customer: dict[str, tuple[str, ...]],
    plans: dict[str, list[list[str]]],
    customer_id: str,
    prices: PriceParameters,
) -> None:
    for depot_id in depots_by_customer[customer_id]:
        depot_plans = plans[depot_id]
        if depot_plans:
            candidate = [*depot_plans[-1], customer_id]
            if _scan_route_plan_feasible(instance, node_lookup, depot_id, candidate, prices):
                depot_plans[-1] = candidate
                return
        if _scan_route_plan_feasible(instance, node_lookup, depot_id, [customer_id], prices):
            depot_plans.append([customer_id])
            return
    plans[depots_by_customer[customer_id][0]].append([customer_id])


def _scan_route_plan_feasible(instance: Any, node_lookup: dict[str, Any], depot_id: str, customer_ids: list[str], prices: PriceParameters) -> bool:
    capacity = _price(prices, "Q_capacity")
    if sum(float(node_lookup[customer_id].demand) for customer_id in customer_ids) > capacity + 1e-9:
        return False
    route = Route("SCAN", "cv", depot_id, [depot_id, *customer_ids, depot_id])
    for row in route_node_schedule(route, instance, prices):
        node = node_lookup.get(row.node_id)
        if node is not None and row.t_start > float(node.due_time) + 1e-9:
            return False
    return True


def _scan_route_distance(instance: Any, depot_id: str, customer_ids: list[str]) -> float:
    sequence = [depot_id, *customer_ids, depot_id]
    return sum(float(instance.distance(a, b)) for a, b in zip(sequence, sequence[1:]))


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


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
