"""Transcript-backed metaheuristic baselines for the ReSETP paper.

The algorithms in this module differ in representation and search policy, but
they all submit complete :class:`Solution` objects to the same
``evaluate/check`` referee through ``score_candidate`` and ``EvalBudget``.
Route feasibility, EV charging repair, time windows, multi-depot assignment,
and cross-site bookkeeping are delegated to the existing construction/repair
layer; this module only owns the metaheuristic search shells.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
import json
import math
import os
from pathlib import Path
import random
import time
from typing import Any, Callable

from ..check import check_solution
from ..cost import evaluate, route_node_schedule
from ..instance_loader import Instance, Node
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, CrossSiteService, Route, Solution
from .bundle import SearchBundle, load_search_bundle
from .charging import repair_route_charging
from .candidates import (
    _OperatorOutcome,
    _apply_strong_alns_destroy_repair,
    _customer_positions,
    _rebuild_solution,
    _route_crossover,
    _route_customers,
    _route_with_customers,
    make_shared_initial_solution,
    solution_signature_hash,
)
from .evaluation import EvalBudget, EvaluationContext, model_cost, score_candidate, score_reference
from .fleet import normalize_solution_vehicle_trips
from .order_decoder import (
    OrderDecodeCache,
    OrderDecodeContext,
    all_cv_solution_for_order as _shared_all_cv_solution_for_order,
    append_customer_to_cached_plan as _shared_append_customer_to_cached_plan,
    complete_order as _shared_complete_order,
    decode_order_like_random_key as _shared_decode_order_like_random_key,
    exploratory_type_hints as _shared_exploratory_type_hints,
    mutated_type_hints as _shared_mutated_type_hints,
    order_to_solution as _shared_order_to_solution,
    route_customer_plan_feasible_cached as _shared_route_customer_plan_feasible_cached,
    route_distance_cached as _shared_route_distance_cached,
    route_type_hints as _shared_route_type_hints,
    solution_order as _shared_solution_order,
)


BASELINE_ALGORITHMS = ("GA", "PSO", "VNS", "ACO", "GA-VNS", "LNS", "GWO", "IWD")
TRACE_DIAGNOSTIC_FLAG = "SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC"

BASELINE_SOURCES = {
    "GA": "Narayanan et al. 2022 arXiv:2204.05545 sec.2.3",
    "PSO": "Transcript-backed discrete VRPTW PSO",
    "VNS": "Woller et al. 2025 arXiv:2511.09570 algorithm 1",
    "ACO": "He Meiling et al. 2023 IACO transcript",
    "GA-VNS": "Narayanan GA plus Woller VNS memetic hybrid",
    "LNS": "Gao Jiaojiao et al. 2024 GLNS transcript",
    "GWO": "Ma Xiangli et al. 2025 HGWO transcript",
    "IWD": "Zhang Jingwen et al. 2025 IIWD transcript",
}


@dataclass(frozen=True)
class BaselineRunResult:
    algorithm: str
    source: str
    feasible: bool
    status: str
    evals: int
    elapsed_seconds: float
    best_cost: float | None
    best_penalized_obj: float | None
    best_solution: Solution | None
    history: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str = ""
    shared_seed_cost: float | None = None
    solution_signature_hash: str = ""
    route_count: int = 0
    cv_route_count: int = 0
    ev_route_count: int = 0
    violation_count: int = 0
    operator_counts: dict[str, int] = field(default_factory=dict)
    parameter_notes: dict[str, Any] = field(default_factory=dict)
    common_preprocess_cost: float | None = None
    common_preprocess_attempts: int = 0
    common_preprocess_accepted_flips: int = 0
    reference_flip_closure_cost: float | None = None
    reference_flip_closure_attempts: int = 0
    reference_flip_closure_accepted_flips: int = 0
    reference_flip_closure_lift: float = 0.0
    reference_flip_closure_signature: str = ""
    common_lift: float = 0.0
    native_lift: float = 0.0
    flip_lift: float = 0.0
    native_best_updates: int = 0
    flip_best_updates: int = 0
    common_best_updates: int = 0
    route_count_unique: int = 0
    candidate_signature_unique: int = 0
    candidate_evaluation_count: int = 0
    candidate_feasible_count: int = 0
    iwd_velocity_update_count: int = 0
    liveness_verdict: str = ""
    liveness_flags: list[str] = field(default_factory=list)


@dataclass
class _ScoredSolution:
    solution: Solution
    objective: float
    cost: float
    feasible: bool
    signature: str
    violation_count: int = 0


@dataclass(frozen=True)
class _ThinPolicy:
    require_charging_signal: bool = False
    max_cv: int = 10**9
    max_ev: int = 10**9


class _SearchSession:
    def __init__(
        self,
        algorithm: str,
        bundle: SearchBundle,
        seed: int,
        eval_budget: int,
        max_runtime_seconds: float,
        initial_solution: Solution,
        prices: PriceParameters | None = None,
        common_flip_preprocess: bool = False,
    ) -> None:
        self.algorithm = str(algorithm)
        self.bundle = bundle
        effective_prices = prices or DEFAULT_PRICES
        self.rng = random.Random(int(seed))
        self.started = time.perf_counter()
        self.max_runtime_seconds = float(max_runtime_seconds)
        self.context = EvaluationContext(
            bundle.instance,
            bundle.carbon_profile,
            prices=effective_prices,
            budget=EvalBudget(limit=int(eval_budget), target=int(eval_budget)),
        )
        self.shared_seed_cost = model_cost(initial_solution, self.context)
        seed_obj = score_reference(initial_solution, self.context)
        self.customer_ids = _all_customer_ids(bundle.instance)
        self.customer_set = set(self.customer_ids)
        self.node_lookup = {node.node_id: node for node in bundle.instance.nodes}
        self.depots = sorted((node for node in bundle.instance.nodes if node.node_type.lower() == "d"), key=lambda node: node.node_id)
        self.depots_by_customer = {
            customer_id: tuple(
                depot.node_id
                for depot in sorted(
                    self.depots,
                    key=lambda depot, cid=customer_id: (float(bundle.instance.distance(depot.node_id, cid)), depot.node_id),
                )
            )
            for customer_id in self.customer_ids
        }
        self.route_feasible_cache: dict[tuple[str, tuple[str, ...]], bool] = {}
        self.route_distance_cache: dict[tuple[str, tuple[str, ...]], float] = {}
        self.decode_cache: dict[tuple[tuple[str, ...], tuple[tuple[str, float], ...], float], Solution] = {}
        self.reference_objective_cache: dict[str, float] = {}
        self.candidate_route_counts: set[int] = set()
        self.candidate_signature_set: set[str] = set()
        self.candidate_evaluation_count = 0
        self.candidate_feasible_count = 0
        self.iwd_velocity_update_count = 0
        self.iwd_velocity_mode = "dynamic"
        self.common_preprocess_cost: float | None = None
        self.common_preprocess_attempts = 0
        self.common_preprocess_accepted_flips = 0
        self.reference_flip_closure_cost: float | None = None
        self.reference_flip_closure_attempts = 0
        self.reference_flip_closure_accepted_flips = 0
        self.reference_flip_closure_lift = 0.0
        self.reference_flip_closure_signature = ""
        self.current = _ScoredSolution(
            solution=initial_solution,
            objective=float(seed_obj),
            cost=float(self.shared_seed_cost),
            feasible=_is_feasible(initial_solution, self.context),
            signature=solution_signature_hash(initial_solution),
        )
        self.best = self.current
        self.history: list[dict[str, Any]] = [
            {
                "eval": 0,
                "time_seconds": 0.0,
                "best_cost": self.best.cost,
                "current_cost": self.current.cost,
                "operator": "shared_warm_start",
                "channel": "shared_warm_start",
                "route_count": len(initial_solution.routes),
                "signature": self.current.signature,
            }
        ]
        self.trace: list[dict[str, Any]] = []
        self.operator_counts: dict[str, int] = {}
        self.reference_objective_cache[self.current.signature] = float(seed_obj)
        if common_flip_preprocess:
            self.record_reference_flip_closure()

    @property
    def evals(self) -> int:
        return int(self.context.budget.count if self.context.budget is not None else 0)

    @property
    def target(self) -> int:
        return int(self.context.budget.target_count if self.context.budget is not None else 0)

    def can_score(self) -> bool:
        if self.context.budget is not None and self.context.budget.reached_target:
            return False
        return (time.perf_counter() - self.started) < self.max_runtime_seconds

    def time_expired(self) -> bool:
        return (time.perf_counter() - self.started) >= self.max_runtime_seconds

    def count_operator(self, name: str) -> None:
        self.operator_counts[name] = self.operator_counts.get(name, 0) + 1

    def reference_objective(self, solution: Solution) -> float:
        signature = solution_signature_hash(solution)
        cached = self.reference_objective_cache.get(signature)
        if cached is not None:
            return cached
        objective = float(score_reference(solution, self.context))
        if len(self.reference_objective_cache) > 4096:
            self.reference_objective_cache.clear()
        self.reference_objective_cache[signature] = objective
        return objective

    def score(self, solution: Solution, *, operator: str, channel: str | None = None) -> _ScoredSolution | None:
        if not self.can_score():
            return None
        self.count_operator(operator)
        self.candidate_route_counts.add(len(solution.routes))
        objective = float(score_candidate(solution, self.context, label="candidate"))
        breakdown = self.context.score_breakdowns.get(id(solution), {})
        violation_count = int(breakdown.get("violation_count", 0))
        feasible = violation_count == 0
        cost = float(breakdown.get("raw_cost", math.inf)) if feasible else math.inf
        scored = _ScoredSolution(
            solution=solution,
            objective=objective,
            cost=cost,
            feasible=feasible,
            signature=solution_signature_hash(solution),
            violation_count=violation_count,
        )
        self.candidate_evaluation_count += 1
        self.candidate_signature_set.add(scored.signature)
        if feasible:
            self.candidate_feasible_count += 1
        if feasible and objective < self.best.objective - 1e-9:
            before_best_cost = self.best.cost
            self.best = scored
            self.history.append(
                {
                    "eval": self.evals,
                    "time_seconds": time.perf_counter() - self.started,
                    "best_cost": cost,
                    "best_cost_before": before_best_cost,
                    "current_cost": self.current.cost if self.current.feasible else math.inf,
                    "operator": operator,
                    "channel": channel or _operator_channel(operator),
                    "route_count": len(solution.routes),
                    "signature": scored.signature,
                }
            )
            _maybe_write_e2_checkpoint(scored.solution, cost, objective, self.evals, time.perf_counter() - self.started, operator)
        return scored

    def apply_common_flip_preprocess(self) -> None:
        self.record_reference_flip_closure()

    def record_reference_flip_closure(self) -> None:
        before = self.best
        outcome = _deterministic_common_flip_closure(self.best.solution, self)
        self.reference_flip_closure_attempts = int(outcome["attempts"])
        self.reference_flip_closure_accepted_flips = int(outcome["accepted_flips"])
        solution = outcome["solution"]
        cost = float(outcome["cost"])
        reference_signature = solution_signature_hash(solution)
        self.reference_flip_closure_cost = cost if math.isfinite(cost) else None
        self.reference_flip_closure_lift = max(0.0, before.cost - cost) if math.isfinite(cost) else 0.0
        self.reference_flip_closure_signature = reference_signature
        self.history.append(
            {
                "eval": 0,
                "time_seconds": time.perf_counter() - self.started,
                "best_cost": before.cost,
                "current_cost": self.current.cost if self.current.feasible else math.inf,
                "operator": "reference_flip_closure",
                "channel": "reference_flip_closure",
                "route_count": len(solution.routes),
                "signature": before.signature,
                "reference_cost": cost if math.isfinite(cost) else "",
                "reference_signature": reference_signature,
                "reference_lift": self.reference_flip_closure_lift,
                "accepted_flips": self.reference_flip_closure_accepted_flips,
                "attempts": self.reference_flip_closure_attempts,
                "is_reference": True,
            }
        )

    def accept_if_better(self, scored: _ScoredSolution | None) -> bool:
        if scored is None:
            return False
        if scored.feasible and scored.objective <= self.current.objective + 1e-9:
            self.current = scored
            return True
        return False

    def accept_metropolis(self, scored: _ScoredSolution | None, temperature: float) -> bool:
        if scored is None or not scored.feasible:
            return False
        delta = scored.objective - self.current.objective
        if delta <= 1e-9:
            self.current = scored
            return True
        if temperature <= 1e-12:
            return False
        if self.rng.random() < math.exp(-delta / temperature):
            self.current = scored
            return True
        return False

    def record_lns_trace(
        self,
        *,
        iteration: int,
        operator: str,
        trace_path: str,
        destroy: str,
        repair: str,
        fallback_used: bool,
        previous_obj: float,
        previous_best_obj: float,
        previous_route_count: int,
        candidate: Solution,
        scored: _ScoredSolution | None,
        accepted: bool,
        temperature: float,
    ) -> None:
        if not _lns_trace_diagnostic_enabled():
            return
        candidate_obj = float(scored.objective) if scored is not None else math.inf
        hard_violation_count = int(scored.violation_count) if scored is not None else 1
        trace_flags = _trace_acceptance_fields(
            previous_obj=previous_obj,
            candidate_obj=candidate_obj,
            previous_best_obj=previous_best_obj,
            accepted=accepted,
            hard_violation_count=hard_violation_count,
        )
        self.trace.append(
            {
                "eval": self.evals,
                "time_seconds": time.perf_counter() - self.started,
                "iteration": int(iteration),
                "operator": operator,
                "trace_path": trace_path,
                "destroy": destroy,
                "repair": repair,
                "fallback_used": bool(fallback_used),
                "accepted": bool(accepted),
                "temperature": float(temperature),
                "previous_obj": float(previous_obj),
                "candidate_obj": candidate_obj if math.isfinite(candidate_obj) else "UNKNOWN",
                "delta_obj": candidate_obj - float(previous_obj) if math.isfinite(candidate_obj) else "UNKNOWN",
                "previous_best_obj": float(previous_best_obj),
                "previous_route_count": int(previous_route_count),
                "candidate_route_count": len(candidate.routes),
                "route_count_delta": len(candidate.routes) - int(previous_route_count),
                "hard_violation_count": hard_violation_count,
                "feasible": bool(scored.feasible) if scored is not None else False,
                "signature": scored.signature if scored is not None else "UNKNOWN",
                **trace_flags,
            }
        )

    def finalize(self, parameter_notes: dict[str, Any] | None = None, failure_reason: str = "") -> BaselineRunResult:
        elapsed = time.perf_counter() - self.started
        best_solution = self.best.solution if self.best.feasible else None
        violations = check_solution(best_solution, self.context.instance, self.context.prices) if best_solution is not None else []
        channel_stats = _channel_lift_stats(self.history)
        route_count_unique = len(self.candidate_route_counts)
        liveness_flags: list[str] = []
        if channel_stats["native_best_updates"] < 1:
            liveness_flags.append("NO_NATIVE_BEST_UPDATE")
        if route_count_unique < 5:
            liveness_flags.append("ROUTE_COUNT_DIVERSITY_LOW")
        liveness_verdict = "BASELINE_LIVENESS_FAIL" if liveness_flags else "BASELINE_LIVENESS_OK"
        status = "OK"
        reason = failure_reason
        if best_solution is None or violations:
            status = "HALT_INFEASIBLE"
            reason = reason or "No zero-violation complete solution was produced."
        elif self.evals < self.target:
            status = "HALT_RUNTIME_UNDER_EVAL" if self.time_expired() else "HALT_UNDER_EVAL"
            reason = reason or f"Stopped at {self.evals}/{self.target} complete evaluations."
        return BaselineRunResult(
            algorithm=self.algorithm,
            source=BASELINE_SOURCES[self.algorithm],
            feasible=best_solution is not None and not violations,
            status=status,
            evals=self.evals,
            elapsed_seconds=float(elapsed),
            best_cost=float(self.best.cost) if self.best.feasible else None,
            best_penalized_obj=float(self.best.objective) if self.best.feasible else None,
            best_solution=best_solution,
            history=list(self.history),
            trace=list(self.trace),
            failure_reason=reason,
            shared_seed_cost=float(self.shared_seed_cost),
            solution_signature_hash=solution_signature_hash(best_solution) if best_solution is not None else "",
            route_count=len(best_solution.routes) if best_solution is not None else 0,
            cv_route_count=sum(1 for route in best_solution.routes if route.vehicle_type.lower() == "cv") if best_solution is not None else 0,
            ev_route_count=sum(1 for route in best_solution.routes if route.vehicle_type.lower() == "ev") if best_solution is not None else 0,
            violation_count=len(violations),
            operator_counts=dict(self.operator_counts),
            parameter_notes=parameter_notes or {},
            common_preprocess_cost=self.common_preprocess_cost,
            common_preprocess_attempts=int(self.common_preprocess_attempts),
            common_preprocess_accepted_flips=int(self.common_preprocess_accepted_flips),
            reference_flip_closure_cost=self.reference_flip_closure_cost,
            reference_flip_closure_attempts=int(self.reference_flip_closure_attempts),
            reference_flip_closure_accepted_flips=int(self.reference_flip_closure_accepted_flips),
            reference_flip_closure_lift=float(self.reference_flip_closure_lift),
            reference_flip_closure_signature=self.reference_flip_closure_signature,
            common_lift=float(channel_stats["common_lift"]),
            native_lift=float(channel_stats["native_lift"]),
            flip_lift=float(channel_stats["flip_lift"]),
            native_best_updates=int(channel_stats["native_best_updates"]),
            flip_best_updates=int(channel_stats["flip_best_updates"]),
            common_best_updates=int(channel_stats["common_best_updates"]),
            route_count_unique=route_count_unique,
            candidate_signature_unique=len(self.candidate_signature_set),
            candidate_evaluation_count=int(self.candidate_evaluation_count),
            candidate_feasible_count=int(self.candidate_feasible_count),
            iwd_velocity_update_count=int(self.iwd_velocity_update_count),
            liveness_verdict=liveness_verdict,
            liveness_flags=liveness_flags,
        )


def _maybe_write_e2_checkpoint(
    solution: Solution,
    best_cost: float,
    best_obj: float,
    eval_count: int,
    elapsed_seconds: float,
    operator: str,
) -> None:
    path_text = os.environ.get("SETP_E2_ALNS_CHECKPOINT_PATH", "").strip()
    if not path_text:
        return
    path = Path(path_text)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "setp-e2-checkpoint.v1",
            "eval": int(eval_count),
            "time_seconds": float(elapsed_seconds),
            "best_cost": float(best_cost),
            "best_obj": float(best_obj),
            "operator": str(operator),
            "solution": asdict(solution),
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        return


def run_metaheuristic_baseline(
    algorithm: str,
    bundle_dir: str | Path,
    *,
    seed: int = 1,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 900.0,
    initial_solution: Solution | None = None,
    prices: PriceParameters | None = None,
    common_flip_preprocess: bool = False,
    iwd_velocity_mode: str = "dynamic",
) -> BaselineRunResult:
    """Run one formal metaheuristic baseline under the common referee."""

    name = _normalize_algorithm(algorithm)
    bundle = load_search_bundle(bundle_dir)
    effective_prices = prices or DEFAULT_PRICES
    warm = initial_solution or make_shared_initial_solution(bundle, prices=effective_prices)
    session = _SearchSession(
        name,
        bundle,
        seed,
        eval_budget,
        max_runtime_seconds,
        warm,
        prices=effective_prices,
        common_flip_preprocess=bool(common_flip_preprocess),
    )
    if str(iwd_velocity_mode) not in {"dynamic", "fixed"}:
        raise ValueError("iwd_velocity_mode must be 'dynamic' or 'fixed'")
    session.iwd_velocity_mode = str(iwd_velocity_mode)
    runner = {
        "GA": _run_ga,
        "PSO": _run_pso,
        "VNS": _run_vns,
        "ACO": _run_aco,
        "GA-VNS": _run_ga_vns,
        "LNS": _run_lns,
        "GWO": _run_gwo,
        "IWD": _run_iwd,
    }[name]
    return runner(session)


def baseline_result_to_dict(result: BaselineRunResult, *, include_solution: bool = False) -> dict[str, Any]:
    row = {
        "algorithm": result.algorithm,
        "source": result.source,
        "feasible": result.feasible,
        "status": result.status,
        "evals": result.evals,
        "actual_evals": result.evals,
        "elapsed_seconds": result.elapsed_seconds,
        "best_cost": result.best_cost,
        "best_penalized_obj": result.best_penalized_obj,
        "failure_reason": result.failure_reason,
        "shared_seed_cost": result.shared_seed_cost,
        "solution_signature_hash": result.solution_signature_hash,
        "route_count": result.route_count,
        "cv_route_count": result.cv_route_count,
        "ev_route_count": result.ev_route_count,
        "violation_count": result.violation_count,
        "operator_counts": result.operator_counts,
        "parameter_notes": result.parameter_notes,
        "history": result.history,
        "trace": result.trace,
        "common_preprocess_cost": result.common_preprocess_cost,
        "common_preprocess_attempts": result.common_preprocess_attempts,
        "common_preprocess_accepted_flips": result.common_preprocess_accepted_flips,
        "reference_flip_closure_cost": result.reference_flip_closure_cost,
        "reference_flip_closure_attempts": result.reference_flip_closure_attempts,
        "reference_flip_closure_accepted_flips": result.reference_flip_closure_accepted_flips,
        "reference_flip_closure_lift": result.reference_flip_closure_lift,
        "reference_flip_closure_signature": result.reference_flip_closure_signature,
        "common_lift": result.common_lift,
        "native_lift": result.native_lift,
        "flip_lift": result.flip_lift,
        "native_best_updates": result.native_best_updates,
        "flip_best_updates": result.flip_best_updates,
        "common_best_updates": result.common_best_updates,
        "route_count_unique": result.route_count_unique,
        "candidate_signature_unique": result.candidate_signature_unique,
        "candidate_evaluation_count": result.candidate_evaluation_count,
        "candidate_feasible_count": result.candidate_feasible_count,
        "iwd_velocity_update_count": result.iwd_velocity_update_count,
        "liveness_verdict": result.liveness_verdict,
        "liveness_flags": result.liveness_flags,
    }
    if include_solution:
        row["solution"] = solution_to_dict(result.best_solution) if result.best_solution is not None else None
    return row


def solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(item) for item in solution.cross_site_services],
    }


def solution_from_dict(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(str(row["vehicle_id"]), str(row["vehicle_type"]), str(row["home_depot_id"]), [str(node) for node in row["node_sequence"]]) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(str(row["vehicle_id"]), str(row["station_id"]), float(row["energy_kwh"]), float(row["occupancy_minutes"]), float(row["charge_start_second"]), int(row.get("charge_day_offset", 0))) for row in payload.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(str(row["customer_id"]), str(row["served_by_depot_id"])) for row in payload.get("cross_site_services", [])],
    )


def cost_breakdown_row(
    instance_name: str,
    algorithm: str,
    seed: int,
    solution: Solution,
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = evaluate(solution, instance, carbon_profile, DEFAULT_PRICES)
    violations = check_solution(solution, instance, DEFAULT_PRICES)
    row: dict[str, Any] = {
        "instance": instance_name,
        "algorithm": algorithm,
        "seed": int(seed),
        "total_cost": float(metrics["total_cost"]),
        "route_count": len(solution.routes),
        "cv_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
        "ev_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "charging_actions": len(solution.charging_actions),
        "violation_count": len(violations),
        "feasible": len(violations) == 0,
    }
    for field_name, value in metrics.items():
        if field_name.startswith("cost_") or field_name in {"E_total", "E_CV", "E_EV"}:
            try:
                row[field_name] = float(value)
            except (TypeError, ValueError):
                pass
    return row


def _run_ga(session: _SearchSession) -> BaselineRunResult:
    params = {"population": 200, "elite_fraction": 0.10, "mutation_probability": 0.10}
    population = _ga_initial_population(session, params["population"])
    no_improvement = 0
    generation = 0
    while session.can_score() and population:
        generation += 1
        before = session.best.objective
        population = sorted(population, key=lambda item: (item.objective, item.signature))
        elite_count = max(1, int(math.ceil(len(population) * params["elite_fraction"])))
        next_population = population[:elite_count]
        survivor_pool = population[elite_count:]
        session.rng.shuffle(survivor_pool)
        next_population.extend(survivor_pool[: max(0, len(population) - elite_count) // 4])
        while len(next_population) < len(population) and session.can_score():
            parent_a = _tournament(population, session.rng)
            parent_b = _tournament(population, session.rng)
            operator = "ga_common_nodes" if session.rng.random() < 0.5 else "ga_common_arcs"
            child = _ga_crossover(parent_a.solution, parent_b.solution, session, operator=operator)
            if session.rng.random() < params["mutation_probability"]:
                child = _ga_mutation(child, session)
                operator = f"{operator}_mutation"
            scored = session.score(child, operator=operator)
            if scored is not None:
                next_population.append(scored)
                session.accept_if_better(scored)
        if session.best.objective < before - 1e-9:
            no_improvement = 0
        else:
            no_improvement += 1
        population = sorted(next_population, key=lambda item: (item.objective, item.signature))[: max(1, len(population))]
        if no_improvement >= max(5, len(population) // 4):
            _ga_diversify(population, session)
            no_improvement = 0
    return session.finalize(params)


def _run_pso(session: _SearchSession) -> BaselineRunResult:
    params = {"population": 50, "w": 0.72, "c1": 1.49, "c2": 1.49, "calibration_eval_seed0": 1000}
    particles = _pso_initial_particles(session, params["population"])
    if not particles:
        return session.finalize(params, failure_reason="PSO produced no particles.")
    gbest = min((particle["pbest"] for particle in particles), key=lambda item: (item.objective, item.signature))
    while session.can_score():
        for particle in particles:
            if not session.can_score():
                break
            order = list(particle["order"])
            velocity = list(particle.get("velocity", []))
            kept_velocity = [swap for swap in velocity if session.rng.random() < params["w"]]
            pbest_swaps = _order_swap_sequence(order, _solution_order(particle["pbest"].solution, session.context.instance))
            gbest_swaps = _order_swap_sequence(order, _solution_order(gbest.solution, session.context.instance))
            velocity = kept_velocity
            velocity.extend(swap for swap in pbest_swaps if session.rng.random() < min(1.0, params["c1"] / 2.0))
            velocity.extend(swap for swap in gbest_swaps if session.rng.random() < min(1.0, params["c2"] / 2.0))
            if session.rng.random() < 0.10:
                i, j = session.rng.sample(range(len(order)), 2)
                velocity.append((i, j))
            order = _apply_swaps(order, velocity, session.rng, 1.0)
            if session.rng.random() < 0.05:
                order = _apply_order_move(order, session.rng, session.rng.choice(["swap", "relocate", "two_opt"]))
            if session.rng.random() < 0.30:
                type_hints = _route_type_hints(particle["pbest"].solution, session.context.instance)
                candidate = _vehicle_type_mutation(particle["pbest"].solution, session)
                operator = "pso_vehicle_type_mutation"
            else:
                base_hints = dict(particle.get("type_hints") or _route_type_hints(particle["pbest"].solution, session.context.instance))
                type_hints = _mutated_type_hints(base_hints, order, session, flip_probability=0.08, force_ev=True)
                candidate = _order_to_solution(order, session, type_hints=type_hints)
                operator = "pso_velocity_decode"
            scored = session.score(candidate, operator=operator)
            if scored is None:
                continue
            particle["order"] = _solution_order(scored.solution, session.context.instance) if scored.feasible else order
            particle["velocity"] = velocity[-max(1, len(order)) :]
            particle["type_hints"] = _route_type_hints(scored.solution, session.context.instance) if scored.feasible else type_hints
            if scored.objective < particle["pbest"].objective - 1e-9:
                particle["pbest"] = scored
            if scored.objective < gbest.objective - 1e-9:
                gbest = scored
            session.accept_if_better(scored)
    return session.finalize(params)


def _run_vns(session: _SearchSession) -> BaselineRunResult:
    n_customers = len(_all_customer_ids(session.context.instance))
    params = {"restart_parameter_r": 3, "ITERS_MAX": max(1, 3 * n_customers), "shaking": "double_bridge+rvnd"}
    while session.can_score():
        if session.rng.random() < 0.50:
            start_solution = _vehicle_type_mutation(session.current.solution, session)
            start_operator = "vns_vehicle_type_construction"
        else:
            construction_order = _nearest_neighbor_order(session.context.instance, session.rng)
            construction_order = _apply_order_move(construction_order, session.rng, session.rng.choice(["swap", "relocate", "two_opt"]))
            start_solution = _order_to_solution(construction_order, session, type_hints=_exploratory_type_hints(construction_order, session, session.evals))
            start_operator = "vns_construction"
        start_scored = session.score(start_solution, operator=start_operator)
        if start_scored is not None and start_scored.feasible and start_scored.objective < session.current.objective:
            session.current = start_scored
        i = 0
        while session.can_score() and i < params["ITERS_MAX"]:
            if i % 4 == 0:
                shaken = _vehicle_type_mutation(session.current.solution, session)
            else:
                base_order = _solution_order(session.current.solution, session.context.instance)
                shaken_order = _vns_shake(base_order, session.rng, i)
                shaken = _order_to_solution(shaken_order, session)
            local = _vns_local_search(session, shaken)
            scored = session.score(local, operator="vns_shaking_local_search")
            if scored is not None and scored.feasible and scored.objective < session.current.objective - 1e-9:
                session.current = scored
                i = 0
            else:
                i += 1
    return session.finalize(params)


def _run_aco(session: _SearchSession) -> BaselineRunResult:
    params = {"m": 20, "iter": 100, "r0": 0.1, "rho0": 0.8, "rho_min": 0.01, "alpha": 1.0, "beta": 2.0, "Q": 1.0}
    customers = _all_customer_ids(session.context.instance)
    pheromone = {(a, b): 1.0 for a in customers for b in customers if a != b}
    transition_base = _aco_transition_base(customers, session, params)
    rho = float(params["rho0"])
    iteration = 0
    while session.can_score():
        iteration += 1
        iteration_best: _ScoredSolution | None = None
        iteration_worst = 0.0
        for _ in range(int(params["m"])):
            if not session.can_score():
                break
            order = _aco_construct_order(customers, pheromone, transition_base, session, params)
            candidate = _order_to_solution(order, session)
            candidate = _aco_vnd(candidate, session)
            scored = session.score(candidate, operator="aco_ant_vnd")
            if scored is None:
                break
            session.accept_if_better(scored)
            if scored.feasible:
                iteration_worst = max(iteration_worst, scored.objective)
                if iteration_best is None or scored.objective < iteration_best.objective:
                    iteration_best = scored
        rho = max(float(params["rho_min"]), 0.95 * rho)
        for edge in list(pheromone):
            pheromone[edge] = max(1e-9, (1.0 - rho) * pheromone[edge])
        if iteration_best is not None:
            delta = ((iteration_worst - iteration_best.objective) / max(1e-9, abs(iteration_best.objective))) * float(params["Q"])
            for a, b in zip(_solution_order(iteration_best.solution, session.context.instance), _solution_order(iteration_best.solution, session.context.instance)[1:]):
                if (a, b) in pheromone:
                    pheromone[(a, b)] += max(1e-9, delta)
        if iteration >= int(params["iter"]) and session.can_score():
            iteration = 0
    return session.finalize(params)


def _run_ga_vns(session: _SearchSession) -> BaselineRunResult:
    params = {"population": 200, "elite_fraction": 0.10, "mutation_probability": 0.10, "vns_polish_trials": 3}
    population = _ga_initial_population(session, params["population"])
    while session.can_score() and population:
        population = sorted(population, key=lambda item: (item.objective, item.signature))
        elite_count = max(1, int(math.ceil(len(population) * params["elite_fraction"])))
        next_population: list[_ScoredSolution] = []
        for elite in population[:elite_count]:
            if not session.can_score():
                break
            polished = _ga_vns_polish(elite.solution, session, int(params["vns_polish_trials"]))
            scored = session.score(polished, operator="ga_vns_elite_polish")
            next_population.append(scored if scored is not None else elite)
            if scored is not None:
                session.accept_if_better(scored)
        if not next_population:
            next_population = population[:elite_count]
        while len(next_population) < len(population) and session.can_score():
            parent_a = _tournament(population, session.rng)
            parent_b = _tournament(population, session.rng)
            child = _ga_crossover(parent_a.solution, parent_b.solution, session, operator="ga_common_arcs" if session.rng.random() < 0.5 else "ga_common_nodes")
            if session.rng.random() < params["mutation_probability"]:
                child = _ga_mutation(child, session)
                operator = "ga_vns_child_mutation"
            else:
                operator = "ga_vns_child_crossover"
            scored = session.score(child, operator=operator)
            if scored is not None:
                next_population.append(scored)
                session.accept_if_better(scored)
        population = sorted(next_population, key=lambda item: (item.objective, item.signature))[: max(1, len(population))]
    return session.finalize(params)


def _run_lns(session: _SearchSession) -> BaselineRunResult:
    params = {"max_iter": 1000, "epsilon": 0.3, "phi": 0.05, "mu": 0.95, "destroy": "random+shaw", "repair": "farthest+regret"}
    scan_solution = _order_to_solution(_angle_scan_order(session.context.instance), session)
    previous_obj = session.current.objective
    previous_best_obj = session.best.objective
    previous_route_count = len(session.current.solution.routes)
    scored_scan = session.score(scan_solution, operator="lns_scan_initial")
    scan_accepted = False
    if scored_scan is not None and scored_scan.feasible and scored_scan.objective < session.current.objective - 1e-9:
        session.current = scored_scan
        scan_accepted = True
    session.record_lns_trace(
        iteration=0,
        operator="lns_scan_initial",
        trace_path=_classify_lns_trace_path("lns_scan_initial", fallback_used=False),
        destroy="",
        repair="",
        fallback_used=False,
        previous_obj=previous_obj,
        previous_best_obj=previous_best_obj,
        previous_route_count=previous_route_count,
        candidate=scan_solution,
        scored=scored_scan,
        accepted=scan_accepted,
        temperature=0.0,
    )
    temperature = -float(params["phi"]) * abs(session.current.objective) / math.log(0.5)
    iteration = 0
    while session.can_score():
        iteration += 1
        destroy, repair = _lns_operator_pair(session.rng)
        previous_obj = session.current.objective
        previous_best_obj = session.best.objective
        previous_route_count = len(session.current.solution.routes)
        fallback_used = False
        if session.rng.random() < 0.35:
            candidate = _vehicle_type_mutation(session.current.solution, session)
            operator = "lns_vehicle_type_mutation"
        else:
            outcome = _alns_neighbor(session, session.current.solution, destroy, repair)
            fallback_used = not (outcome.produced and outcome.feasible)
            candidate = outcome.solution if not fallback_used else _order_to_solution(_apply_order_move(_solution_order(session.current.solution, session.context.instance), session.rng, "relocate"), session)
            operator = f"lns_{destroy}_{repair}"
        scored = session.score(candidate, operator=operator)
        accepted = session.accept_metropolis(scored, temperature)
        session.record_lns_trace(
            iteration=iteration,
            operator=operator,
            trace_path=_classify_lns_trace_path(operator, fallback_used=fallback_used),
            destroy=destroy if operator.startswith("lns_") and operator != "lns_vehicle_type_mutation" else "",
            repair=repair if operator.startswith("lns_") and operator != "lns_vehicle_type_mutation" else "",
            fallback_used=fallback_used,
            previous_obj=previous_obj,
            previous_best_obj=previous_best_obj,
            previous_route_count=previous_route_count,
            candidate=candidate,
            scored=scored,
            accepted=accepted,
            temperature=temperature,
        )
        temperature *= float(params["mu"])
        if iteration >= int(params["max_iter"]):
            iteration = 0
            temperature = max(1e-9, -float(params["phi"]) * abs(session.current.objective) / math.log(0.5))
    return session.finalize(params)


def _run_gwo(session: _SearchSession) -> BaselineRunResult:
    params = {"NIND": 50, "MAXGEN": 1000, "position_update": "GA-crossover-alpha-beta-delta", "local_search": "Shaw-LNS"}
    wolves = _gwo_initial_wolves(session, int(params["NIND"]))
    generation = 0
    while session.can_score() and wolves:
        generation += 1
        wolves = sorted(wolves, key=lambda item: (item.objective, item.signature))
        guides = wolves[: min(3, len(wolves))]
        next_wolves: list[_ScoredSolution] = list(guides)
        for wolf in wolves[len(guides) :]:
            if not session.can_score():
                break
            guide = guides[0] if session.rng.random() < 1.0 / 3.0 else guides[1 % len(guides)] if session.rng.random() < 0.5 else guides[-1]
            order = _order_crossover(_solution_order(wolf.solution, session.context.instance), _solution_order(guide.solution, session.context.instance), session.rng)
            order = _apply_order_move(order, session.rng, session.rng.choice(["swap", "relocate", "two_opt"]))
            candidate = _order_to_solution(order, session, type_hints=_route_type_hints(guide.solution, session.context.instance))
            outcome = _alns_neighbor(session, candidate, "shaw_related_removal", "regret2_insert_repair")
            if outcome.produced and outcome.feasible:
                candidate = outcome.solution
            scored = session.score(candidate, operator="gwo_alpha_beta_delta_lns")
            if scored is not None:
                next_wolves.append(scored if scored.objective <= wolf.objective else wolf)
                session.accept_if_better(scored)
        wolves = sorted(next_wolves, key=lambda item: (item.objective, item.signature))[: max(1, int(params["NIND"]))]
        if generation >= int(params["MAXGEN"]):
            generation = 0
    return session.finalize(params)


def _run_iwd(session: _SearchSession) -> BaselineRunResult:
    # The implementation follows the explicit equations in the IWD family
    # source: Shah-Hosseini (2009), as used by Zhang et al. (2025) for
    # MDHFVRPTW.  The Zhang paper's application table does not print rho, so
    # the canonical 0.9 local/global value from Shah-Hosseini is recorded here
    # rather than silently inventing a new setting.
    params = {
        "drops": 20,
        "soil0": 10000.0,
        "velocity0": 200.0,
        "a_s": 1000.0,
        "b_s": 0.01,
        "c_s": 1.0,
        "a_v": 1000.0,
        "b_v": 0.01,
        "c_v": 1.0,
        "rho_local": 0.9,
        "rho_global": 0.9,
        # Explicit stabilizers in the Zhang et al. design transcription.
        "epsilon_s": 0.01,
        "epsilon_v": 0.0001,
        "iter": 100,
        "lns": "Shaw+greedy insertion on iteration-best",
        "acceptance": "SA-Metropolis",
        "velocity_mode": session.iwd_velocity_mode,
        "source_formula": "Shah-Hosseini-2009 / Zhang-2025-IIWD",
        "source_initialization": "Shah-Hosseini-2009 canonical InitSoil=10000, InitVel=200",
    }
    # One and only one source-aligned sensitivity profile is available for
    # the pre-registered rescue round.  The default used by formal E2 remains
    # canonical; the scaled profile mirrors the Zhang application table.
    parameter_profile = os.environ.get("SETP_IWD_PARAM_PROFILE", "canonical")
    if parameter_profile == "zhang_scaled":
        params.update({"soil0": 1000.0, "velocity0": 100.0})
        params["source_initialization"] = "Zhang-2025 application InitSoil=1000, InitVel=100"
    elif parameter_profile != "canonical":
        raise ValueError(f"unknown SETP_IWD_PARAM_PROFILE={parameter_profile!r}")
    params["parameter_profile"] = parameter_profile
    customers = _all_customer_ids(session.context.instance)
    soil = {(a, b): float(params["soil0"]) for a in customers for b in customers if a != b}
    temperature = -0.05 * abs(session.current.objective) / math.log(0.5)
    iteration = 0
    while session.can_score():
        iteration += 1
        best_this_iter: _ScoredSolution | None = None
        best_this_iter_carried_soil = 0.0
        for drop_idx in range(int(params["drops"])):
            if not session.can_score():
                break
            order, carried_soil = _iwd_construct_order(customers, soil, session, params)
            candidate = _order_to_solution(order, session)
            scored = session.score(candidate, operator="iwd_construct_sa")
            if scored is None:
                break
            session.accept_metropolis(scored, temperature)
            if scored.feasible and (best_this_iter is None or scored.objective < best_this_iter.objective):
                best_this_iter = scored
                best_this_iter_carried_soil = carried_soil
        if best_this_iter is not None:
            outcome = _alns_neighbor(session, best_this_iter.solution, "shaw_related_removal", "greedy_insert_repair") if session.can_score() else _OperatorOutcome(best_this_iter.solution, produced=False, feasible=False, changed=False)
            if outcome.produced and outcome.feasible:
                polished = session.score(outcome.solution, operator="iwd_iteration_best_lns")
                session.accept_metropolis(polished, temperature)
                if polished is not None and polished.feasible and polished.objective < best_this_iter.objective:
                    best_this_iter = polished
            _iwd_update_global_soil(
                _solution_order(best_this_iter.solution, session.context.instance),
                soil,
                best_this_iter_carried_soil,
                params,
            )
        temperature *= 0.95
        if iteration >= int(params["iter"]):
            iteration = 0
            temperature = max(1e-9, -0.05 * abs(session.current.objective) / math.log(0.5))
    return session.finalize(params)


def _normalize_algorithm(algorithm: str) -> str:
    name = str(algorithm).strip()
    aliases = {item.lower(): item for item in BASELINE_ALGORITHMS}
    aliases.update({"ga_vns": "GA-VNS", "gavns": "GA-VNS", "grey-wolf": "GWO"})
    key = name.lower()
    if key not in aliases:
        raise ValueError(f"Unknown metaheuristic baseline {algorithm!r}; expected one of {BASELINE_ALGORITHMS}")
    return aliases[key]


def _is_feasible(solution: Solution, context: EvaluationContext) -> bool:
    return not check_solution(solution, context.instance, context.prices)


def _lns_trace_diagnostic_enabled() -> bool:
    return os.environ.get(TRACE_DIAGNOSTIC_FLAG, "0").lower() not in {"0", "false", "no"}


def _classify_lns_trace_path(operator: str, *, fallback_used: bool) -> str:
    if operator == "lns_scan_initial":
        return "scan_initial"
    if operator == "lns_vehicle_type_mutation":
        return "vehicle_type_mutation"
    return "fallback_relocate" if fallback_used else "strong_bridge"


def _trace_acceptance_fields(
    *,
    previous_obj: float,
    candidate_obj: float,
    previous_best_obj: float,
    accepted: bool,
    hard_violation_count: int,
) -> dict[str, bool]:
    finite_candidate = math.isfinite(float(candidate_obj))
    return {
        "accepted_worse": bool(accepted) and finite_candidate and float(candidate_obj) > float(previous_obj) + 1e-9,
        "best_improved": finite_candidate and int(hard_violation_count) == 0 and float(candidate_obj) < float(previous_best_obj) - 1e-9,
    }


def _operator_channel(operator: str) -> str:
    if operator == "shared_warm_start":
        return "shared_warm_start"
    if operator == "reference_flip_closure":
        return "reference_flip_closure"
    if operator == "common_flip_preprocess":
        return "common_flip_preprocess"
    if "vehicle_type" in operator:
        return "flip_operator"
    return f"native_{operator}"


def _channel_lift_stats(history: list[dict[str, Any]]) -> dict[str, float | int]:
    stats: dict[str, float | int] = {
        "common_lift": 0.0,
        "native_lift": 0.0,
        "flip_lift": 0.0,
        "common_best_updates": 0,
        "native_best_updates": 0,
        "flip_best_updates": 0,
    }
    for item in history[1:]:
        before = float(item.get("best_cost_before", item.get("current_cost", math.inf)))
        after = float(item.get("best_cost", math.inf))
        lift = max(0.0, before - after) if math.isfinite(before) and math.isfinite(after) else 0.0
        channel = str(item.get("channel") or _operator_channel(str(item.get("operator", ""))))
        if channel == "common_flip_preprocess":
            stats["common_lift"] = float(stats["common_lift"]) + lift
            stats["common_best_updates"] = int(stats["common_best_updates"]) + 1
        elif channel == "flip_operator":
            stats["flip_lift"] = float(stats["flip_lift"]) + lift
            stats["flip_best_updates"] = int(stats["flip_best_updates"]) + 1
        elif channel.startswith("native_"):
            stats["native_lift"] = float(stats["native_lift"]) + lift
            stats["native_best_updates"] = int(stats["native_best_updates"]) + 1
    return stats


def _all_customer_ids(instance: Instance) -> list[str]:
    return [node.node_id for node in instance.nodes if node.node_type.lower() == "c"]


def _order_decode_context(session: _SearchSession) -> OrderDecodeContext:
    return OrderDecodeContext(
        session.context.instance,
        session.context.prices,
        session.context.carbon_profile,
        session.rng,
        cache=OrderDecodeCache(
            decode_cache=session.decode_cache,
            route_feasible_cache=session.route_feasible_cache,
            route_distance_cache=session.route_distance_cache,
        ),
        customer_ids=session.customer_ids,
        node_lookup=session.node_lookup,
        depots=session.depots,
        depots_by_customer=session.depots_by_customer,
    )


def _solution_order(solution: Solution, instance: Instance) -> list[str]:
    return _shared_solution_order(solution, instance)


def _route_type_hints(solution: Solution, instance: Instance) -> dict[str, float]:
    return _shared_route_type_hints(solution, instance)


def _exploratory_type_hints(order: list[str], session: _SearchSession, index: int = 0) -> dict[str, float]:
    return _shared_exploratory_type_hints(order, _order_decode_context(session), index=index)


def _mutated_type_hints(
    base: dict[str, float],
    order: list[str],
    session: _SearchSession,
    *,
    flip_probability: float = 0.12,
    force_ev: bool = False,
) -> dict[str, float]:
    return _shared_mutated_type_hints(
        base,
        order,
        _order_decode_context(session),
        flip_probability=flip_probability,
        force_ev=force_ev,
    )


def _crossover_type_hints(parent_a: Solution, parent_b: Solution, order: list[str], session: _SearchSession) -> dict[str, float]:
    hints_a = _route_type_hints(parent_a, session.context.instance)
    hints_b = _route_type_hints(parent_b, session.context.instance)
    hints: dict[str, float] = {}
    for customer_id in order:
        hints[customer_id] = hints_a.get(customer_id, 0.05) if session.rng.random() < 0.5 else hints_b.get(customer_id, 0.05)
    return _mutated_type_hints(hints, order, session, flip_probability=0.04, force_ev=True)


def _order_to_solution(
    order: list[str],
    session: _SearchSession,
    *,
    type_hints: dict[str, float] | None = None,
    ev_threshold: float = 0.82,
) -> Solution:
    return _shared_order_to_solution(
        order,
        _order_decode_context(session),
        current_solution=session.current.solution,
        type_hints=type_hints,
        ev_threshold=ev_threshold,
    )


def _complete_order(order: list[str], instance: Instance) -> list[str]:
    seen: set[str] = set()
    all_customers = set(_all_customer_ids(instance))
    complete = [customer_id for customer_id in order if customer_id in all_customers and not (customer_id in seen or seen.add(customer_id))]
    missing = sorted(all_customers - set(complete))
    return [*complete, *missing]


def _complete_order_for_session(order: list[str], session: _SearchSession) -> list[str]:
    return _shared_complete_order(order, _order_decode_context(session))


def _decode_order_like_random_key(ordered: list[str], session: _SearchSession, type_keys: dict[str, float], *, ev_threshold: float) -> Solution:
    return _shared_decode_order_like_random_key(ordered, _order_decode_context(session), type_keys, ev_threshold=ev_threshold)


def _normalize_solution_for_session(solution: Solution, session: _SearchSession) -> Solution:
    try:
        return normalize_solution_vehicle_trips(solution, session.context.instance)
    except ValueError:
        return solution


def _deterministic_common_flip_closure(solution: Solution, session: _SearchSession) -> dict[str, Any]:
    current = solution
    current_cost = _feasible_model_cost(current, session)
    accepted = 0
    attempts = 0
    while attempts < 500 and math.isfinite(current_cost):
        best_candidate: Solution | None = None
        best_cost = current_cost
        for idx, _route in enumerate(list(current.routes)):
            attempts += 1
            candidate = _flip_route_type_at_index(current, idx, session)
            if candidate is None:
                continue
            cost = _feasible_model_cost(candidate, session)
            if cost < best_cost - 1e-9:
                best_candidate = candidate
                best_cost = cost
        if best_candidate is None:
            break
        current = best_candidate
        current_cost = best_cost
        accepted += 1
    return {
        "solution": current,
        "cost": current_cost,
        "attempts": attempts,
        "accepted_flips": accepted,
    }


def _flip_route_type_at_index(solution: Solution, idx: int, session: _SearchSession) -> Solution | None:
    routes = list(solution.routes)
    if idx < 0 or idx >= len(routes):
        return None
    route = routes[idx]
    target_type = "ev" if route.vehicle_type.lower() == "cv" else "cv"
    new_route = replace(route, vehicle_id=f"{target_type.upper()}COMMON_{idx + 1}", vehicle_type=target_type)
    new_actions = [action for action in solution.charging_actions if action.vehicle_id != route.vehicle_id]
    if target_type == "ev":
        try:
            new_route, route_actions = repair_route_charging(
                new_route,
                session.context.instance,
                session.context.carbon_profile,
                session.context.prices,
            )
        except ValueError:
            return None
        new_actions.extend(route_actions)
    routes[idx] = new_route
    candidate = _normalize_solution_for_session(
        Solution(routes=routes, charging_actions=new_actions, cross_site_services=solution.cross_site_services),
        session,
    )
    if check_solution(candidate, session.context.instance, session.context.prices):
        return None
    return candidate


def _feasible_model_cost(solution: Solution, session: _SearchSession) -> float:
    if check_solution(solution, session.context.instance, session.context.prices):
        return math.inf
    return float(model_cost(solution, session.context))


def _vehicle_type_mutation(solution: Solution, session: _SearchSession, *, attempts: int = 12) -> Solution:
    routes = list(solution.routes)
    if not routes:
        return solution
    cv_indices = [idx for idx, route in enumerate(routes) if route.vehicle_type.lower() == "cv"]
    ev_indices = [idx for idx, route in enumerate(routes) if route.vehicle_type.lower() == "ev"]
    candidate_indices = list(cv_indices or ev_indices)
    session.rng.shuffle(candidate_indices)
    for idx in candidate_indices[: max(1, int(attempts))]:
        route = routes[idx]
        target_type = "ev" if route.vehicle_type.lower() == "cv" else "cv"
        new_route = replace(route, vehicle_id=f"{target_type.upper()}M{idx + 1}", vehicle_type=target_type)
        new_actions = [action for action in solution.charging_actions if action.vehicle_id != route.vehicle_id]
        if target_type == "ev":
            try:
                new_route, route_actions = repair_route_charging(
                    new_route,
                    session.context.instance,
                    session.context.carbon_profile,
                    session.context.prices,
                )
            except ValueError:
                continue
            new_actions.extend(route_actions)
        new_routes = list(routes)
        new_routes[idx] = new_route
        candidate = _normalize_solution_for_session(
            Solution(routes=new_routes, charging_actions=new_actions, cross_site_services=solution.cross_site_services),
            session,
        )
        if not check_solution(candidate, session.context.instance, session.context.prices):
            return candidate
    return solution


def _append_customer_to_cached_plan(customer_id: str, plans: dict[str, list[list[str]]], session: _SearchSession) -> None:
    _shared_append_customer_to_cached_plan(customer_id, plans, _order_decode_context(session))


def _route_customer_plan_feasible_cached(depot_id: str, customer_ids: tuple[str, ...], session: _SearchSession) -> bool:
    return _shared_route_customer_plan_feasible_cached(depot_id, customer_ids, _order_decode_context(session))


def _route_distance_cached(depot_id: str, customer_ids: tuple[str, ...], session: _SearchSession) -> float:
    return _shared_route_distance_cached(depot_id, customer_ids, _order_decode_context(session))


def _all_cv_solution_for_session(ordered: list[str], session: _SearchSession) -> Solution:
    return _shared_all_cv_solution_for_order(ordered, _order_decode_context(session))


def _distance(instance: Instance, a: str, b: str) -> float:
    return float(instance.distance(a, b))


def _node_lookup(instance: Instance) -> dict[str, Node]:
    return {node.node_id: node for node in instance.nodes}


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _apply_order_move(order: list[str], rng: random.Random, move: str) -> list[str]:
    if len(order) < 2:
        return list(order)
    out = list(order)
    if move == "swap":
        i, j = sorted(rng.sample(range(len(out)), 2))
        out[i], out[j] = out[j], out[i]
    elif move == "relocate":
        i, j = rng.sample(range(len(out)), 2)
        item = out.pop(i)
        out.insert(j, item)
    elif move == "two_opt":
        i, j = sorted(rng.sample(range(len(out)), 2))
        out[i : j + 1] = reversed(out[i : j + 1])
    elif move == "double_bridge":
        if len(out) < 8:
            rng.shuffle(out)
        else:
            cuts = sorted(rng.sample(range(1, len(out)), 4))
            a, b, c, d = cuts
            out = out[:a] + out[c:d] + out[b:c] + out[a:b] + out[d:]
    elif move == "nearest_delete":
        base = rng.choice(out)
        neighbors = sorted(out, key=lambda node: (_distance_placeholder(base, node), node))
        target = neighbors[1] if len(neighbors) > 1 else base
        out.remove(target)
        out.insert(rng.randrange(len(out) + 1), target)
    else:
        rng.shuffle(out)
    return out


def _distance_placeholder(a: str, b: str) -> float:
    return 0.0 if a == b else 1.0


def _order_swap_sequence(source: list[str], target: list[str]) -> list[tuple[int, int]]:
    current = list(source)
    pos = {customer_id: idx for idx, customer_id in enumerate(current)}
    swaps: list[tuple[int, int]] = []
    for idx, customer_id in enumerate(target):
        j = pos.get(customer_id)
        if j is None or j == idx:
            continue
        swaps.append((idx, j))
        other = current[idx]
        current[idx], current[j] = current[j], current[idx]
        pos[customer_id] = idx
        pos[other] = j
    return swaps


def _apply_swaps(order: list[str], swaps: list[tuple[int, int]], rng: random.Random, probability: float) -> list[str]:
    out = list(order)
    for i, j in swaps:
        if i < len(out) and j < len(out) and rng.random() < probability:
            out[i], out[j] = out[j], out[i]
    return out


def _order_crossover(parent_a: list[str], parent_b: list[str], rng: random.Random) -> list[str]:
    if len(parent_a) < 2:
        return list(parent_a)
    i, j = sorted(rng.sample(range(len(parent_a)), 2))
    block = parent_a[i : j + 1]
    used = set(block)
    fill = [customer_id for customer_id in parent_b if customer_id not in used]
    return [*fill[:i], *block, *fill[i:]]


def _ga_initial_population(session: _SearchSession, target_population: int) -> list[_ScoredSolution]:
    order = _solution_order(session.current.solution, session.context.instance)
    population: list[_ScoredSolution] = [session.current]
    desired = max(1, min(int(target_population), max(1, session.target)))
    nn_order = _nearest_neighbor_order(session.context.instance, session.rng)
    for idx in range(desired - 1):
        if not session.can_score():
            break
        vehicle_type_seed = idx % 3 == 1
        if vehicle_type_seed:
            candidate_order = order
            operator = "ga_vehicle_type_initialization"
        elif idx == 0:
            candidate_order = nn_order
            operator = "ga_nn_initialization"
        elif idx % 5 == 0:
            candidate_order = _nearest_neighbor_order(session.context.instance, session.rng)
            operator = "ga_random_start_nn_initialization"
        else:
            move = ("swap", "relocate", "two_opt", "double_bridge")[idx % 4]
            candidate_order = _apply_order_move(order, session.rng, move)
            operator = f"ga_seeded_{move}"
        if vehicle_type_seed:
            candidate = _vehicle_type_mutation(session.current.solution, session, attempts=idx + 1)
            improved = candidate
        else:
            candidate = _order_to_solution(candidate_order, session, type_hints=_exploratory_type_hints(candidate_order, session, idx))
            improved = _ga_initial_improvement(candidate, session)
        scored = session.score(improved, operator=operator)
        if scored is not None:
            population.append(scored)
            session.accept_if_better(scored)
    return sorted(population, key=lambda item: (item.objective, item.signature))


def _ga_initial_improvement(solution: Solution, session: _SearchSession) -> Solution:
    outcome = _alns_neighbor(session, solution, "whole_route_removal", "regret2_insert_repair")
    if outcome.produced and outcome.feasible:
        return outcome.solution
    return solution


def _nearest_neighbor_order(instance: Instance, rng: random.Random) -> list[str]:
    remaining = set(_all_customer_ids(instance))
    if not remaining:
        return []
    current = rng.choice(sorted(remaining))
    order = [current]
    remaining.remove(current)
    while remaining:
        current = min(remaining, key=lambda customer_id: (float(instance.distance(current, customer_id)), customer_id))
        order.append(current)
        remaining.remove(current)
    return order


def _tournament(population: list[_ScoredSolution], rng: random.Random) -> _ScoredSolution:
    if len(population) == 1:
        return population[0]
    a, b = rng.sample(population, 2)
    return a if (a.objective, a.signature) <= (b.objective, b.signature) else b


def _ga_crossover(parent_a: Solution, parent_b: Solution, session: _SearchSession, *, operator: str) -> Solution:
    if operator == "ga_common_arcs":
        return _route_crossover(parent_a, parent_b, session.context, session.rng)
    order_a = _solution_order(parent_a, session.context.instance)
    order_b = _solution_order(parent_b, session.context.instance)
    child_order = _order_crossover(order_a, order_b, session.rng)
    return _order_to_solution(child_order, session, type_hints=_crossover_type_hints(parent_a, parent_b, child_order, session))


def _ga_mutation(solution: Solution, session: _SearchSession) -> Solution:
    order = _solution_order(solution, session.context.instance)
    mutation = session.rng.choice(["random_node_delete", "random_route_delete", "nearest_node_delete", "vehicle_type_mutation"])
    if mutation == "random_route_delete":
        outcome = _alns_neighbor(session, solution, "whole_route_removal", "regret2_insert_repair")
        return outcome.solution if outcome.produced and outcome.feasible else solution
    if mutation == "vehicle_type_mutation":
        return _vehicle_type_mutation(solution, session)
    if mutation == "nearest_node_delete":
        order = _nearest_node_reinsert_order(order, session.context.instance, session.rng)
    else:
        order = _apply_order_move(order, session.rng, session.rng.choice(["swap", "relocate", "two_opt"]))
    hints = _mutated_type_hints(_route_type_hints(solution, session.context.instance), order, session, flip_probability=0.05)
    return _order_to_solution(order, session, type_hints=hints)


def _nearest_node_reinsert_order(order: list[str], instance: Instance, rng: random.Random) -> list[str]:
    if len(order) < 2:
        return list(order)
    base = rng.choice(order)
    candidates = [customer_id for customer_id in order if customer_id != base]
    target = min(candidates, key=lambda customer_id: (float(instance.distance(base, customer_id)), customer_id))
    out = [customer_id for customer_id in order if customer_id != target]
    out.insert(rng.randrange(len(out) + 1), target)
    return out


def _ga_diversify(population: list[_ScoredSolution], session: _SearchSession) -> None:
    if len(population) <= 2:
        return
    # Keep at least two parents; a singleton population cannot produce children
    # and will otherwise spin until the wall-clock cap without consuming evals.
    keep = max(2, len(population) // 2)
    del population[keep:]


def _pso_initial_particles(session: _SearchSession, target_population: int) -> list[dict[str, Any]]:
    base_order = _solution_order(session.current.solution, session.context.instance)
    particles: list[dict[str, Any]] = [
        {"order": base_order, "velocity": [], "pbest": session.current}
    ]
    desired = max(1, min(int(target_population), max(1, session.target)))
    for idx in range(desired - 1):
        if not session.can_score():
            break
        if idx % 3 == 1:
            candidate = _vehicle_type_mutation(session.current.solution, session, attempts=idx + 1)
            order = _solution_order(candidate, session.context.instance)
            operator = "pso_initial_particle_vehicle_type"
        elif idx % 4 == 0:
            order = _nearest_neighbor_order(session.context.instance, session.rng)
            hints = _exploratory_type_hints(order, session, idx)
            candidate = _order_to_solution(order, session, type_hints=hints)
            operator = "pso_initial_particle_nn_decode"
        else:
            order = _apply_order_move(base_order, session.rng, ("swap", "relocate", "two_opt", "double_bridge")[idx % 4])
            hints = _exploratory_type_hints(order, session, idx)
            candidate = _order_to_solution(order, session, type_hints=hints)
            operator = "pso_initial_particle_decode"
        scored = session.score(candidate, operator=operator)
        if scored is None:
            break
        particles.append({"order": order, "velocity": [], "pbest": scored, "type_hints": _route_type_hints(scored.solution, session.context.instance)})
        session.accept_if_better(scored)
    return particles


def _vns_shake(order: list[str], rng: random.Random, iteration: int) -> list[str]:
    moves = ["double_bridge", "relocate", "swap", "two_opt"]
    out = list(order)
    for _ in range(1 + (iteration % 3)):
        out = _apply_order_move(out, rng, moves[iteration % len(moves)])
    return out


def _vns_local_search(session: _SearchSession, solution: Solution) -> Solution:
    best = solution
    best_obj = session.reference_objective(best)
    neighborhoods = ["swap", "relocate", "two_opt", "vehicle_type", "alns_shaw"]
    improved = True
    while improved and session.can_score():
        improved = False
        session.rng.shuffle(neighborhoods)
        for neighborhood in neighborhoods:
            if not session.can_score():
                return best
            if neighborhood == "alns_shaw":
                outcome = _alns_neighbor(session, best, "shaw_related_removal", "regret2_insert_repair")
                candidate = outcome.solution if outcome.produced and outcome.feasible else best
            elif neighborhood == "vehicle_type":
                candidate = _vehicle_type_mutation(best, session)
            else:
                order = _apply_order_move(_solution_order(best, session.context.instance), session.rng, neighborhood)
                hints = _mutated_type_hints(_route_type_hints(best, session.context.instance), order, session, flip_probability=0.04)
                candidate = _order_to_solution(order, session, type_hints=hints)
            scored = session.score(candidate, operator=f"vns_local_{neighborhood}")
            if scored is not None and scored.feasible and scored.objective < best_obj - 1e-9:
                best = scored.solution
                best_obj = scored.objective
                improved = True
                break
    return best


def _aco_transition_base(customers: list[str], session: _SearchSession, params: dict[str, Any]) -> dict[tuple[str, str], float]:
    instance = session.context.instance
    nodes = session.node_lookup
    depots = [depot.node_id for depot in session.depots]
    beta = float(params["beta"])
    base: dict[tuple[str, str], float] = {}
    for a in customers:
        for b in customers:
            if a == b:
                continue
            distance = max(1e-9, float(instance.distance(a, b)))
            eta = 1.0 / distance
            saving = max(1e-9, min(float(instance.distance(depot, a)) + float(instance.distance(depot, b)) for depot in depots) - distance)
            dev = 1.0 / max(1.0, abs(float(nodes[a].due_time) - float(nodes[b].ready_time)))
            width = 1.0 / max(1.0, float(nodes[b].due_time) - float(nodes[b].ready_time))
            base[(a, b)] = (eta ** beta) * (1.0 + saving / 10_000.0) * (1.0 + dev) * (1.0 + width)
    return base


def _aco_construct_order(customers: list[str], pheromone: dict[tuple[str, str], float], transition_base: dict[tuple[str, str], float], session: _SearchSession, params: dict[str, Any]) -> list[str]:
    remaining = set(customers)
    if not remaining:
        return []
    current = session.rng.choice(sorted(remaining))
    order = [current]
    remaining.remove(current)
    while remaining:
        weights = {
            customer_id: _aco_transition_weight(current, customer_id, pheromone, transition_base, params)
            for customer_id in remaining
        }
        if session.rng.random() < float(params["r0"]):
            next_customer = max(weights, key=lambda customer_id: (weights[customer_id], customer_id))
        else:
            next_customer = _weighted_customer_choice(weights, session.rng)
        order.append(next_customer)
        remaining.remove(next_customer)
        current = next_customer
    return order


def _aco_transition_weight(a: str, b: str, pheromone: dict[tuple[str, str], float], transition_base: dict[tuple[str, str], float], params: dict[str, Any]) -> float:
    tau = pheromone.get((a, b), 1.0)
    alpha = float(params["alpha"])
    return (tau ** alpha) * transition_base.get((a, b), 1.0)


def _weighted_customer_choice(weights: dict[str, float], rng: random.Random) -> str:
    total = sum(max(0.0, value) for value in weights.values())
    if total <= 1e-12:
        return rng.choice(sorted(weights))
    pick = rng.random() * total
    current = 0.0
    for customer_id, weight in sorted(weights.items()):
        current += max(0.0, weight)
        if current >= pick:
            return customer_id
    return sorted(weights)[-1]


def _aco_vnd(solution: Solution, session: _SearchSession) -> Solution:
    best = solution
    best_obj = session.reference_objective(best)
    for move in ("relocate", "swap"):
        if not session.can_score():
            return best
        candidate = _order_to_solution(_apply_order_move(_solution_order(best, session.context.instance), session.rng, move), session, type_hints=_route_type_hints(best, session.context.instance))
        scored = session.score(candidate, operator=f"aco_vnd_{move}")
        if scored is not None and scored.feasible and scored.objective < best_obj - 1e-9:
            best = scored.solution
            best_obj = scored.objective
    return best


def _ga_vns_polish(solution: Solution, session: _SearchSession, trials: int) -> Solution:
    best = solution
    for idx in range(max(1, int(trials))):
        if not session.can_score():
            return best
        order = _vns_shake(_solution_order(best, session.context.instance), session.rng, idx)
        candidate = _order_to_solution(order, session, type_hints=_route_type_hints(best, session.context.instance))
        candidate = _vns_local_search(session, candidate)
        obj_best = session.reference_objective(best)
        obj_candidate = session.reference_objective(candidate)
        if obj_candidate < obj_best - 1e-9:
            best = candidate
    return best


def _angle_scan_order(instance: Instance) -> list[str]:
    depots = [node for node in instance.nodes if node.node_type.lower() == "d"]
    if depots:
        cx = sum(float(node.x) for node in depots) / len(depots)
        cy = sum(float(node.y) for node in depots) / len(depots)
    else:
        cx = cy = 0.0
    customers = [node for node in instance.nodes if node.node_type.lower() == "c"]
    return [
        node.node_id
        for node in sorted(customers, key=lambda node: (math.atan2(float(node.y) - cy, float(node.x) - cx), float(node.demand), node.node_id))
    ]


def _lns_operator_pair(rng: random.Random) -> tuple[str, str]:
    destroy = "random_customer_removal" if rng.random() < 0.5 else "shaw_related_removal"
    repair = rng.choice(["greedy_insert_repair", "regret2_insert_repair", "regret3_insert_repair"])
    if rng.random() < 0.25:
        destroy = "worst_customer_removal"
    return destroy, repair


def _gwo_initial_wolves(session: _SearchSession, target_population: int) -> list[_ScoredSolution]:
    wolves = [session.current]
    base_order = _solution_order(session.current.solution, session.context.instance)
    desired = max(1, min(int(target_population), max(1, session.target)))
    for idx in range(desired - 1):
        if not session.can_score():
            break
        if idx % 3 == 0:
            order = _nearest_neighbor_order(session.context.instance, session.rng)
        elif idx % 3 == 1:
            order = _angle_scan_order(session.context.instance)
        else:
            order = _apply_order_move(base_order, session.rng, "double_bridge")
        candidate = _order_to_solution(order, session)
        scored = session.score(candidate, operator="gwo_initial_wolf")
        if scored is not None:
            wolves.append(scored)
            session.accept_if_better(scored)
    return sorted(wolves, key=lambda item: (item.objective, item.signature))


def _iwd_construct_order(
    customers: list[str],
    soil: dict[tuple[str, str], float],
    session: _SearchSession,
    params: dict[str, Any],
) -> tuple[list[str], float]:
    remaining = set(customers)
    if not remaining:
        return [], 0.0
    current = session.rng.choice(sorted(remaining))
    order = [current]
    remaining.remove(current)
    velocity = float(params["velocity0"])
    carried_soil = 0.0
    while remaining:
        weights = {
            candidate: _iwd_transition_weight(current, candidate, soil, remaining, params)
            for candidate in remaining
        }
        nxt = _weighted_customer_choice(weights, session.rng)
        edge = (current, nxt)
        edge_soil = float(soil.get(edge, params["soil0"]))
        if session.iwd_velocity_mode == "dynamic":
            # The source transcription squares soil here.  That matters: soil
            # is allowed to become negative after a local update, but the
            # velocity denominator must remain positive and finite.
            denominator = float(params["b_v"]) + float(params["c_v"]) * (edge_soil ** 2)
            velocity += float(params["a_v"]) / max(float(params["epsilon_s"]), denominator)
            session.iwd_velocity_update_count += 1
        distance = float(session.context.instance.distance(current, nxt))
        travel_time = distance / max(float(params["epsilon_v"]), velocity)
        delta_soil = float(params["a_s"]) / (float(params["b_s"]) + float(params["c_s"]) * (travel_time ** 2))
        soil[edge] = (1.0 - float(params["rho_local"])) * edge_soil - float(params["rho_local"]) * delta_soil
        carried_soil += delta_soil
        order.append(nxt)
        remaining.remove(nxt)
        current = nxt
    return order, carried_soil


def _iwd_transition_weight(
    a: str,
    b: str,
    soil: dict[tuple[str, str], float],
    remaining: set[str],
    params: dict[str, Any],
) -> float:
    edge_soil = float(soil.get((a, b), params["soil0"]))
    min_soil = min((float(soil.get((a, candidate), params["soil0"])) for candidate in remaining), default=0.0)
    # g(soil)=soil-min(0,min_k soil(i,k)); no savings or other heuristic is
    # mixed into the IWD probability.  The savings matrix was an earlier
    # non-IWD adaptation and made the implementation look active while the
    # actual IWD state was ignored.
    shifted_soil = edge_soil - min(0.0, min_soil)
    return 1.0 / (float(params["epsilon_s"]) + max(0.0, shifted_soil))


def _iwd_update_global_soil(
    order: list[str],
    soil: dict[tuple[str, str], float],
    carried_soil: float,
    params: dict[str, Any],
) -> None:
    if not order or not math.isfinite(carried_soil):
        return
    n = max(2, len(order))
    for edge in zip(order, order[1:]):
        if edge in soil:
            soil[edge] = (1.0 + float(params["rho_global"])) * float(soil[edge]) - float(params["rho_global"]) * float(carried_soil) / float(n - 1)


def _alns_neighbor(session: _SearchSession, solution: Solution, destroy: str, repair: str) -> _OperatorOutcome:
    with _baseline_fast_repair_flags():
        return _apply_strong_alns_destroy_repair(solution, session.context, session.rng, destroy, repair)


@contextmanager
def _baseline_fast_repair_flags() -> Any:
    # Baseline repair scoring now uses the same cost-aware insertion metric as
    # the independent ALNS path unless a caller explicitly overrides the
    # environment for a diagnostic A/B run.
    yield


def _local_order_search(session: _SearchSession, solution: Solution, *, max_trials: int = 6) -> Solution:
    best = solution
    best_obj = session.reference_objective(best)
    order = _solution_order(solution, session.context.instance)
    for move in ("swap", "relocate", "two_opt"):
        for _ in range(max(1, max_trials)):
            if not session.can_score():
                return best
            candidate = _order_to_solution(_apply_order_move(order, session.rng, move), session)
            scored = session.score(candidate, operator=f"local_{move}")
            if scored is not None and scored.feasible and scored.objective < best_obj - 1e-9:
                best = scored.solution
                best_obj = scored.objective
                order = _solution_order(best, session.context.instance)
    return best


def _solution_from_routes(routes: list[Route], session: _SearchSession) -> Solution:
    rebuilt = _rebuild_solution(routes, session.context)
    return rebuilt if rebuilt is not None else session.current.solution
