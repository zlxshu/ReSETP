"""Mechanism-judged dual-basin ALNS with strict G0 candidate accounting.

The official HGS-CVRP library contributes one alternative customer order.
The full ReSETP route-local fleet, charging, and carbon layer judges whether
that order or the current deterministic ALNS warm start is the better search
basin.  HGS is not presented as a solver for the complete ReSETP model.

If the deterministic ALNS basin wins and enough budget remains, a single
bounded full mechanism correction can create a second search basin.  Because
that corrected solution enters later search, it is charged as one complete
candidate whenever it actually changes the solution.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import random
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fast_mechanism_completion import (  # noqa: E402
    FastCompletionResult,
    apply_fast_route_local_completion,
)
from initial_pool import solution_signature_hash  # noqa: E402
from official_hgs_resetp_adapter import (  # noqa: E402
    HGSAdapterConfig,
    OfficialHGSLibrary,
    decode_official_hgs_order,
    official_hgs_order,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    run_winner_kernel,
)
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (  # noqa: E402
    score_reference_solution,
    score_search_candidate,
)
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.algorithms.resetp_alns.support.fleet import (  # noqa: E402
    infer_fleet_limits,
    normalize_solution_vehicle_trips,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import SearchBundle, load_search_bundle  # noqa: E402
from setp_solver.search.evaluation import EvalBudget, EvaluationContext  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402
from terminal_completion import CompletionResult, apply_terminal_completion  # noqa: E402
from v7_responsibility_solver import annotate_cross_site_services  # noqa: E402


TOL = 1.0e-9
SELECTOR_MECHANISM = "mechanism"
SELECTOR_RAW = "raw"


@dataclass(frozen=True)
class DualBasinConfig:
    total_eval_budget: int = 100
    hgs_no_improvement_iterations: int = 100
    hgs_time_window_weight: float = 1.0
    tail_share: float = 0.30
    phase_runtime_cap_seconds: float = 60.0
    selector_mode: str = SELECTOR_MECHANISM
    enable_mid_completion: bool = True

    def __post_init__(self) -> None:
        if self.total_eval_budget < 0:
            raise ValueError("total_eval_budget must be non-negative")
        if self.hgs_no_improvement_iterations <= 0:
            raise ValueError(
                "hgs_no_improvement_iterations must be positive"
            )
        if not 0.0 < self.tail_share < 1.0:
            raise ValueError("tail_share must be strictly between zero and one")
        if self.phase_runtime_cap_seconds <= 0:
            raise ValueError("phase_runtime_cap_seconds must be positive")
        if self.selector_mode not in {SELECTOR_MECHANISM, SELECTOR_RAW}:
            raise ValueError(f"unsupported selector_mode={self.selector_mode!r}")


@dataclass(frozen=True)
class DualBasinResult:
    algorithm: str
    best_solution: Solution
    best_cost: float
    evaluations: int
    elapsed_seconds: float
    route_count: int
    feasible: bool
    selected_basin: str
    mechanism_activity: dict[str, Any]


@dataclass(frozen=True)
class BasinSelection:
    selected_basin: str
    selected_raw_solution: Solution
    selected_scored_solution: Solution
    selected_cost: float
    hgs_raw_solution: Solution
    hgs_native: dict[str, Any]
    selector_activity: dict[str, Any]
    candidate_evaluations: int


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def build_v7_warm(
    bundle: SearchBundle,
    *,
    prices: Any = DEFAULT_PRICES,
) -> Solution:
    """Build the exact all-CV warm start used by the current winner kernel."""

    solution = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    violations = check_solution(solution, bundle.instance, prices)
    if violations:
        raise ValueError(f"v7 warm start is infeasible: {violations[:8]}")
    return solution


def _build_hgs_raw(
    bundle: SearchBundle,
    warm: Solution,
    *,
    seed: int,
    config: DualBasinConfig,
    prices: Any,
) -> tuple[Solution, dict[str, Any]]:
    engine = OfficialHGSLibrary()
    result = official_hgs_order(
        instance=bundle.instance,
        initial_solution=warm,
        capacity=_price(prices, "Q_capacity"),
        speed_m_per_second=_price(prices, "v_speed_ms"),
        config=HGSAdapterConfig(
            seed=int(seed),
            no_improvement_iterations=config.hgs_no_improvement_iterations,
            time_window_weight=config.hgs_time_window_weight,
        ),
        library=engine,
    )
    decoded = decode_official_hgs_order(
        result,
        instance=bundle.instance,
        carbon_profile=bundle.carbon_profile,
        prices=prices,
        initial_solution=warm,
        rng=random.Random(int(seed)),
    )
    limits = infer_fleet_limits(bundle.bundle_dir)
    decoded = normalize_solution_vehicle_trips(
        decoded,
        bundle.instance,
        max_cv=limits.cv,
        max_ev=limits.ev,
    )
    decoded = annotate_cross_site_services(
        decoded,
        infer_customer_home_depots(bundle.instance),
    )
    violations = check_solution(decoded, bundle.instance, prices)
    if violations:
        raise ValueError(
            "official-HGS order decode is infeasible: "
            f"{violations[:8]}"
        )
    return decoded, {
        "official_commit": result.official_commit,
        "native_calls": int(result.native_calls),
        "native_cpu_seconds": float(result.native_cpu_seconds),
        "wall_seconds": float(result.wall_seconds),
        "no_improvement_iterations": int(
            config.hgs_no_improvement_iterations
        ),
        "time_window_weight": float(config.hgs_time_window_weight),
        "native_route_count": int(
            sum(len(routes) for routes in result.routes_by_depot.values())
        ),
        "native_cost_by_depot": {
            str(key): float(value)
            for key, value in result.native_cost_by_depot.items()
        },
        "order_hash": _hash_order(result.order),
    }


def select_search_basin(
    bundle: SearchBundle,
    *,
    warm: Solution,
    hgs_raw: Solution,
    config: DualBasinConfig,
    prices: Any = DEFAULT_PRICES,
) -> BasinSelection:
    """Charge one HGS alternative and keep the default tie-breaking bypass."""

    if config.selector_mode == SELECTOR_MECHANISM:
        default_completed = apply_fast_route_local_completion(
            warm,
            bundle,
            prices=prices,
        )
        hgs_completed = apply_fast_route_local_completion(
            hgs_raw,
            bundle,
            prices=prices,
        )
    else:
        default_completed = FastCompletionResult(
            solution=warm,
            changed=False,
            activity={
                "ablation": "route-local mechanism judgement removed",
                "complete_candidate_evaluations": 0,
            },
        )
        hgs_completed = FastCompletionResult(
            solution=hgs_raw,
            changed=False,
            activity={
                "ablation": "route-local mechanism judgement removed",
                "complete_candidate_evaluations": 0,
            },
        )

    owners = infer_customer_home_depots(bundle.instance)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=1, target=1),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    default_prepared, default_cost = score_reference_solution(
        default_completed.solution,
        context,
        phase="dual_basin_default_anchor",
    )
    hgs_prepared, hgs_cost = score_search_candidate(
        hgs_completed.solution,
        context,
        channel="dual_basin_hgs_alternative",
    )
    if context.budget is None or context.budget.count != 1:
        raise RuntimeError("dual-basin selector candidate ledger did not close")
    for label, candidate in (
        ("default", default_prepared),
        ("hgs", hgs_prepared),
    ):
        violations = check_solution(candidate, bundle.instance, prices)
        if violations:
            raise RuntimeError(
                f"{label} selector solution became infeasible: {violations[:8]}"
            )

    if hgs_cost < default_cost - TOL:
        selected_basin = "official_hgs_order"
        selected_raw = hgs_raw
        selected_scored = hgs_prepared
        selected_cost = float(hgs_cost)
    else:
        selected_basin = "current_alns_warm"
        selected_raw = warm
        selected_scored = default_prepared
        selected_cost = float(default_cost)
    return BasinSelection(
        selected_basin=selected_basin,
        selected_raw_solution=selected_raw,
        selected_scored_solution=selected_scored,
        selected_cost=selected_cost,
        hgs_raw_solution=hgs_raw,
        hgs_native={},
        selector_activity={
            "selector_mode": config.selector_mode,
            "default_cost": float(default_cost),
            "hgs_cost": float(hgs_cost),
            "cost_margin_hgs_minus_default": float(
                hgs_cost - default_cost
            ),
            "selected_basin": selected_basin,
            "default_fast_completion": default_completed.activity,
            "hgs_fast_completion": hgs_completed.activity,
            "reference_replays": int(
                context.score_counts.get("reference", 0)
            ),
            "candidate_evaluations": int(context.budget.count),
            "score_counts": {
                str(key): int(value)
                for key, value in context.score_counts.items()
            },
        },
        candidate_evaluations=int(context.budget.count),
    )


def run_dual_basin_mechanism_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    config: DualBasinConfig | None = None,
    prices: Any = DEFAULT_PRICES,
) -> DualBasinResult:
    """Run the frozen candidate or one explicitly labelled ablation."""

    started = time.perf_counter()
    cfg = config or DualBasinConfig()
    total = int(cfg.total_eval_budget)
    bundle = load_search_bundle(bundle_dir)
    warm = build_v7_warm(bundle, prices=prices)

    if total == 0:
        cost = _independent_cost(warm, bundle, prices)
        return DualBasinResult(
            algorithm=_algorithm_label(cfg),
            best_solution=warm,
            best_cost=cost,
            evaluations=0,
            elapsed_seconds=time.perf_counter() - started,
            route_count=len(warm.routes),
            feasible=not check_solution(warm, bundle.instance, prices),
            selected_basin="current_alns_warm",
            mechanism_activity={
                "stop_reason": "zero_budget",
                "hgs_native_calls": 0,
                "alns_phase_evaluations": [],
                "mid_candidate_evaluations": 0,
                "total_candidate_evaluations": 0,
            },
        )

    hgs_raw, hgs_native = _build_hgs_raw(
        bundle,
        warm,
        seed=seed,
        config=cfg,
        prices=prices,
    )
    selection = select_search_basin(
        bundle,
        warm=warm,
        hgs_raw=hgs_raw,
        config=cfg,
        prices=prices,
    )
    remaining = total - selection.candidate_evaluations
    envelope: list[tuple[str, Solution, float]] = [
        (
            "selected_scored_seed",
            selection.selected_scored_solution,
            float(selection.selected_cost),
        )
    ]
    phase_rows: list[dict[str, Any]] = []
    mid_activity: dict[str, Any] = {
        "attempted": False,
        "changed": False,
        "candidate_evaluations": 0,
    }
    final_completion: CompletionResult | None = None

    if remaining <= 0:
        final_completion = apply_terminal_completion(
            bundle_dir,
            selection.selected_raw_solution,
            prices=prices,
        )
        envelope.append(
            ("terminal_after_selector", final_completion.solution, final_completion.cost)
        )
    elif (
        selection.selected_basin != "current_alns_warm"
        or not cfg.enable_mid_completion
        or remaining < 3
    ):
        phase = _run_alns_phase(
            bundle_dir,
            initial_solution=selection.selected_raw_solution,
            seed=seed,
            eval_budget=remaining,
            prices=prices,
            runtime_cap=cfg.phase_runtime_cap_seconds,
        )
        phase_rows.append(phase["activity"])
        envelope.append(
            ("single_alns_phase", phase["solution"], phase["cost"])
        )
        final_completion = apply_terminal_completion(
            bundle_dir,
            phase["solution"],
            prices=prices,
        )
        envelope.append(
            ("terminal_after_single_phase", final_completion.solution, final_completion.cost)
        )
    else:
        tail_reserved = max(1, int(math.ceil(cfg.tail_share * remaining)))
        opening_budget = remaining - tail_reserved - 1
        if opening_budget < 1:
            raise RuntimeError("dual-basin split produced an empty opening phase")
        opening = _run_alns_phase(
            bundle_dir,
            initial_solution=selection.selected_raw_solution,
            seed=seed,
            eval_budget=opening_budget,
            prices=prices,
            runtime_cap=cfg.phase_runtime_cap_seconds,
        )
        phase_rows.append(opening["activity"])
        envelope.append(
            ("opening_alns_phase", opening["solution"], opening["cost"])
        )
        middle = apply_terminal_completion(
            bundle_dir,
            opening["solution"],
            prices=prices,
        )
        middle_changed = (
            solution_signature_hash(middle.solution)
            != solution_signature_hash(opening["solution"])
        )
        mid_activity = {
            "attempted": True,
            "changed": bool(middle_changed),
            "source_cost": float(opening["cost"]),
            "completed_cost": float(middle.cost),
            "completion": middle.activity,
            "candidate_evaluations": 0,
        }
        if middle_changed:
            middle_context = EvaluationContext(
                bundle.instance,
                bundle.carbon_profile,
                prices=prices,
                budget=EvalBudget(limit=1, target=1),
                customer_home_depot=infer_customer_home_depots(
                    bundle.instance
                ),
                allow_cross_depot=True,
            )
            middle_prepared, middle_cost = score_search_candidate(
                middle.solution,
                middle_context,
                channel="dual_basin_mid_mechanism",
            )
            if (
                middle_context.budget is None
                or middle_context.budget.count != 1
            ):
                raise RuntimeError("middle mechanism candidate ledger did not close")
            if abs(float(middle_cost) - float(middle.cost)) > 1.0e-7:
                raise RuntimeError(
                    "middle mechanism score does not match independent replay"
                )
            middle_start = middle_prepared
            mid_candidate_evaluations = 1
            tail_budget = tail_reserved
            envelope.append(
                ("charged_mid_mechanism", middle_prepared, float(middle_cost))
            )
            mid_activity["candidate_evaluations"] = 1
            mid_activity["score_counts"] = {
                str(key): int(value)
                for key, value in middle_context.score_counts.items()
            }
        else:
            middle_start = opening["solution"]
            mid_candidate_evaluations = 0
            tail_budget = tail_reserved + 1
        tail = _run_alns_phase(
            bundle_dir,
            initial_solution=middle_start,
            seed=_tail_seed(seed),
            eval_budget=tail_budget,
            prices=prices,
            runtime_cap=cfg.phase_runtime_cap_seconds,
        )
        phase_rows.append(tail["activity"])
        envelope.append(("tail_alns_phase", tail["solution"], tail["cost"]))
        final_completion = apply_terminal_completion(
            bundle_dir,
            tail["solution"],
            prices=prices,
        )
        envelope.append(
            ("terminal_after_tail", final_completion.solution, final_completion.cost)
        )
        mid_activity["tail_budget"] = int(tail_budget)
        mid_activity["opening_budget"] = int(opening_budget)
        mid_activity["candidate_evaluations"] = int(
            mid_candidate_evaluations
        )

    winner_label, winner_solution, winner_cost = min(
        envelope,
        key=lambda item: (float(item[2]), solution_signature_hash(item[1])),
    )
    recomputed = _independent_cost(winner_solution, bundle, prices)
    if abs(recomputed - float(winner_cost)) > 1.0e-7:
        raise RuntimeError(
            f"dual-basin final objective mismatch: {winner_cost} != {recomputed}"
        )
    violations = check_solution(winner_solution, bundle.instance, prices)
    alns_evaluations = sum(
        int(row["evaluations"]) for row in phase_rows
    )
    mid_evaluations = int(mid_activity.get("candidate_evaluations", 0))
    total_evaluations = (
        selection.candidate_evaluations
        + alns_evaluations
        + mid_evaluations
    )
    if total_evaluations != total:
        raise RuntimeError(
            "dual-basin candidate ledger did not close: "
            f"{total_evaluations} != {total}"
        )
    alns_reference_replays = sum(
        int(
            row.get("operator_counts", {})
            .get("score_counts", {})
            .get("reference", 0)
        )
        for row in phase_rows
    )
    middle_completion_replays = int(
        mid_activity.get("completion", {}).get(
            "full_solution_replays",
            0,
        )
    )
    final_completion_replays = int(
        final_completion.activity.get("full_solution_replays", 0)
        if final_completion is not None
        else 0
    )
    selector_reference_replays = int(
        selection.selector_activity.get("reference_replays", 0)
    )
    reference_replays_total = (
        selector_reference_replays
        + alns_reference_replays
        + middle_completion_replays
        + final_completion_replays
        + 1
    )
    return DualBasinResult(
        algorithm=_algorithm_label(cfg),
        best_solution=winner_solution,
        best_cost=float(recomputed),
        evaluations=int(total_evaluations),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(winner_solution.routes),
        feasible=not violations,
        selected_basin=selection.selected_basin,
        mechanism_activity={
            "selector": selection.selector_activity,
            "hgs_native": hgs_native,
            "alns_phases": phase_rows,
            "middle": mid_activity,
            "final_completion": (
                final_completion.activity
                if final_completion is not None
                else {}
            ),
            "envelope_costs": {
                label: float(cost) for label, _, cost in envelope
            },
            "envelope_selected": winner_label,
            "selector_candidate_evaluations": int(
                selection.candidate_evaluations
            ),
            "alns_candidate_evaluations": int(alns_evaluations),
            "mid_candidate_evaluations": int(mid_evaluations),
            "total_candidate_evaluations": int(total_evaluations),
            "reference_replay_ledger": {
                "selector": selector_reference_replays,
                "alns_initial_and_final": alns_reference_replays,
                "middle_completion": middle_completion_replays,
                "final_completion": final_completion_replays,
                "final_envelope_recompute": 1,
                "total_reported": int(reference_replays_total),
            },
            "final_recomputed_cost": float(recomputed),
        },
    )


def _run_alns_phase(
    bundle_dir: str | Path,
    *,
    initial_solution: Solution,
    seed: int,
    eval_budget: int,
    prices: Any,
    runtime_cap: float,
) -> dict[str, Any]:
    result = run_winner_kernel(
        bundle_dir,
        config=WinnerKernelConfig(
            seed=int(seed),
            eval_budget=int(eval_budget),
            max_runtime_seconds=float(runtime_cap),
            require_charging_signal=False,
        ),
        initial_solution=initial_solution,
        prices=prices,
    )
    if int(result["evaluations"]) != int(eval_budget):
        raise RuntimeError(
            "ALNS phase candidate ledger did not close: "
            f"{result['evaluations']} != {eval_budget}"
        )
    if not bool(result["feasible"]):
        raise RuntimeError("ALNS phase returned an infeasible best solution")
    return {
        "solution": result["best_solution"],
        "cost": float(result["best_cost"]),
        "activity": {
            "seed": int(seed),
            "eval_budget": int(eval_budget),
            "evaluations": int(result["evaluations"]),
            "elapsed_seconds": float(result["elapsed_seconds"]),
            "history_length": len(result.get("history", [])),
            "operator_counts": result.get("operator_counts", {}),
        },
    }


def _independent_cost(
    solution: Solution,
    bundle: SearchBundle,
    prices: Any,
) -> float:
    return float(
        evaluate(
            solution,
            bundle.instance,
            bundle.carbon_profile,
            prices,
        )["total_cost"]
    )


def _tail_seed(seed: int) -> int:
    return int(seed) * 100_003


def _algorithm_label(config: DualBasinConfig) -> str:
    if config.selector_mode == SELECTOR_RAW:
        return "raw_cost_dual_basin_ablation"
    if not config.enable_mid_completion:
        return "mechanism_judged_dual_basin_no_mid_ablation"
    return "mechanism_judged_dual_basin_alns"


def _hash_order(order: tuple[str, ...]) -> str:
    import hashlib

    return hashlib.sha256("\n".join(order).encode("utf-8")).hexdigest()
