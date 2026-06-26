"""Unified candidate-algorithm smoke adapters.

v2026-06-12: W1 formal experiment recovery. Candidate algorithms now start
from the same regret-2/charging-repaired warm seed and mutate path collections
through algorithm-specific operators before every solution is scored by the
shared ``evaluate/check`` referee. Thin shells are labelled explicitly when a
reference package cannot be safely imported without executing demo code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Callable

from ..check import check_solution
from ..cost import evaluate, route_node_schedule
from ..instance_loader import Instance, Node
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, Route, Solution
from .alns_wouda import SearchPolicy, run_alns_wouda
from .bundle import SearchBundle, load_search_bundle
from .charging import repair_route_charging
from .construction import build_initial_solution
from .evaluation import BIG_M, EvalBudget, EvaluationContext, model_cost, record_repair_delta, score_candidate, score_reference
from .feasible_repair import repair_removed_customers
from .fleet import FleetLimits, UNBOUNDED_FLEET, infer_fleet_limits, normalize_solution_vehicle_trips
from .local_search import improve_solution_locally
from .repair_scoring import route_model_cost_delta
from .scout import scout_reference_algorithms


PRIMARY_ALGORITHM = "ALNS-Wouda"
Z1_CANDIDATES = [
    "VNS@Valdecy",
    "PyGAD",
    "scikit-opt-GA",
    "scikit-opt-SA",
    "ALNS@wangqianlongucas",
    "NSGA-II@haris989",
    "DR-ALNS",
]

# v2026-06-12: W1g keeps tiny adapter smoke tests from enforcing the formal
# anti-collapse rule; W1 formal smoke uses 2000 evals.
FORMAL_COLLAPSE_MIN_EVAL_BUDGET = 2000


def _empty_search_diagnostics() -> dict[str, Any]:
    return {
        "operator_calls": 0,
        "candidate_generated": 0,
        "candidate_feasible": 0,
        "candidate_changed": 0,
        "candidate_accepted": 0,
        "accepted_changed": 0,
        "best_updates": 0,
        "diagnosis": "",
    }


@dataclass
class CandidateState:
    solution: Solution
    context: EvaluationContext
    history: list[dict[str, float]] = field(default_factory=list)
    operator_trace: list[dict[str, Any]] = field(default_factory=list)
    adapter_type: str = ""
    import_status: str = ""
    package_loaded: bool = False
    search_diagnostics: dict[str, Any] = field(default_factory=_empty_search_diagnostics)


@dataclass(frozen=True)
class CandidateRunResult:
    algorithm: str
    feasible: bool
    evals: int
    elapsed_seconds: float
    best_cost: float | None
    best_penalized_obj: float | None
    best_solution: Solution | None
    history: list[dict[str, float]]
    status: str
    failure_reason: str = ""
    adapter: str = ""
    import_status: str = "not_checked"
    package_loaded: bool = False
    operator_trace: list[dict[str, Any]] = field(default_factory=list)
    shared_seed_cost: float | None = None
    solution_signature_hash: str = ""
    collapse_status: str = "green"
    collapse_explanation: str = ""
    search_diagnostics: dict[str, Any] = field(default_factory=_empty_search_diagnostics)
    actual_moves: int = 0
    candidate_scores: int = 0
    repair_scores: int = 0
    repair_delta_count: int = 0
    operator_counts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateSmokeReport:
    gate: str
    bundle_dir: str
    seed: int
    eval_budget: int
    max_runtime_seconds: float
    alns_wouda_feasible: bool
    feasible_candidate_count: int
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class _PackageProbe:
    status: str
    loaded: bool


@dataclass(frozen=True)
class _OperatorOutcome:
    solution: Solution
    produced: bool
    feasible: bool
    changed: bool
    violation_count: int = 0
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def make_shared_initial_solution(
    bundle: SearchBundle,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> Solution:
    """Build the common W1 warm start for every candidate adapter."""

    # v2026-06-12: W1a aligns all candidates with ALNS-Wouda's construction:
    # nearest depot assignment, regret-2 insertion, and EV charging repair.
    limits = infer_fleet_limits(bundle.bundle_dir)
    solution = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        fleet_limits=limits,
        introduce_ev=True,
        require_charging_signal=False,
    )
    violations = check_solution(solution, bundle.instance, prices)
    if violations:
        detail = "; ".join(f"{v.type}:{v.vehicle_id}:{v.location}:{v.detail}" for v in violations[:6])
        raise ValueError(f"HALT_W1_SHARED_SEED: shared warm start is infeasible: {detail}")
    return solution


def solution_to_random_key(solution: Solution, instance: Instance) -> dict[str, Any]:
    """Encode a route collection as customer random keys and type hints.

    This function remains for vector-only algorithms and compatibility tests;
    it is no longer the common fallback for every external candidate.
    """

    node_lookup = {node.node_id: node for node in instance.nodes}
    customers: list[str] = []
    vehicle_type_keys: dict[str, float] = {}
    for route in solution.routes:
        type_key = 0.95 if route.vehicle_type.lower() == "ev" else 0.05
        for node_id in route.node_sequence:
            node = node_lookup.get(node_id)
            if node is not None and node.node_type.lower() == "c":
                customers.append(node_id)
                vehicle_type_keys[node_id] = type_key
    width = max(1, len(customers) - 1)
    return {
        "customer_keys": {customer_id: idx / width for idx, customer_id in enumerate(customers)},
        "vehicle_type_keys": vehicle_type_keys,
        "ev_threshold": 0.82,
    }


def random_key_to_solution(
    chromosome: dict[str, Any],
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> Solution:
    """Decode vector genes through a capacity/time-window-aware path builder."""

    customers = [node for node in instance.nodes if node.node_type.lower() == "c"]
    customer_keys = {str(key): float(value) for key, value in dict(chromosome.get("customer_keys", {})).items()}
    type_keys = {str(key): float(value) for key, value in dict(chromosome.get("vehicle_type_keys", {})).items()}
    ordered = sorted(customers, key=lambda node: (customer_keys.get(node.node_id, 0.5), node.node_id))

    plans: dict[str, list[list[str]]] = {depot.node_id: [] for depot in _depots(instance)}
    for customer in ordered:
        _append_customer_to_plan(customer, plans, instance, prices)

    routes: list[Route] = []
    actions: list[ChargingAction] = []
    ev_threshold = float(chromosome.get("ev_threshold", 0.82))
    next_cv = 1
    next_ev = 1
    for depot_id, depot_plans in sorted(plans.items()):
        for customer_ids in depot_plans:
            avg_type_key = sum(type_keys.get(customer_id, 0.0) for customer_id in customer_ids) / max(1, len(customer_ids))
            if avg_type_key >= ev_threshold:
                route = Route(f"EV{next_ev}", "ev", depot_id, [depot_id, *customer_ids, depot_id])
                try:
                    repaired, route_actions = repair_route_charging(route, instance, carbon_profile, prices)
                    candidate = Solution(routes=[*routes, repaired], charging_actions=[*actions, *route_actions])
                    if not check_solution(candidate, instance, prices):
                        routes.append(repaired)
                        actions.extend(route_actions)
                        next_ev += 1
                        continue
                except ValueError:
                    pass

            route = Route(f"CV{next_cv}", "cv", depot_id, [depot_id, *customer_ids, depot_id])
            routes.append(route)
            next_cv += 1

    solution = normalize_solution_vehicle_trips(Solution(routes=routes, charging_actions=actions), instance)
    if check_solution(solution, instance, prices):
        try:
            fallback = build_initial_solution(
                instance,
                carbon_profile,
                prices,
                fleet_limits=_fleet_limits_from_instance(instance),
                require_charging_signal=False,
            )
            if not check_solution(fallback, instance, prices):
                return fallback
        except ValueError:
            pass
        return _all_cv_solution(ordered, instance, prices)
    return solution


def run_candidate(
    algorithm: str,
    bundle_dir: str | Path,
    *,
    seed: int = 1,
    eval_budget: int = 2000,
    max_runtime_seconds: float = 300.0,
    initial_solution: Solution | None = None,
) -> CandidateRunResult:
    """Run one W1 candidate through the shared referee."""

    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    shared_solution = initial_solution or make_shared_initial_solution(bundle)
    shared_context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        budget=EvalBudget(limit=_candidate_budget_limit(eval_budget), target=max(1, int(eval_budget))),
    )
    shared_seed_cost = model_cost(shared_solution, shared_context)

    if algorithm == PRIMARY_ALGORITHM:
        return _run_primary_alns(
            bundle.bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            initial_solution=shared_solution,
            shared_seed_cost=shared_seed_cost,
            started=started,
        )

    return _run_external_candidate(
        algorithm,
        bundle,
        shared_solution,
        shared_seed_cost,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        started=started,
    )


def run_z1_smoke(
    repo_root: str | Path,
    bundle_dir: str | Path,
    *,
    seed: int = 1,
    eval_budget: int = 2000,
    max_runtime_seconds: float = 300.0,
    output_path: str | Path | None = None,
) -> CandidateSmokeReport:
    """Run the W1/Z1 smoke board and persist anti-collapse diagnostics."""

    _ = repo_root
    algorithms = [PRIMARY_ALGORITHM, *Z1_CANDIDATES]
    rows = [
        _serializable_result(
            run_candidate(
                algorithm,
                bundle_dir,
                seed=seed,
                eval_budget=eval_budget,
                max_runtime_seconds=max_runtime_seconds,
            )
        )
        for algorithm in algorithms
    ]
    rows = annotate_collapse_diagnostics(rows, eval_budget=eval_budget)

    alns_row = next((row for row in rows if row["algorithm"] == PRIMARY_ALGORITHM), None)
    alns_feasible = bool(alns_row and alns_row["feasible"])
    alns_cost = float(alns_row["best_cost"]) if alns_row and alns_row.get("best_cost") else None
    if alns_cost and math.isfinite(alns_cost) and alns_cost > 0.0:
        for row in rows:
            if row.get("best_cost") is not None:
                row["gap_vs_alns_pct"] = (float(row["best_cost"]) - alns_cost) / alns_cost * 100.0
    candidate_count = sum(1 for row in rows if row["algorithm"] != PRIMARY_ALGORITHM and row["feasible"])
    unexplained_red = [row for row in rows if row.get("collapse_status") == "red"]
    scale_failures = [
        row
        for row in rows
        if row["feasible"]
        and row.get("shared_seed_cost")
        and row.get("best_cost")
        and float(row["best_cost"]) > float(row["shared_seed_cost"]) * 1.35 + 1e-9
    ]
    gate = "PASS" if alns_feasible and candidate_count >= 4 and not unexplained_red and not scale_failures else "HALT_W1"
    if unexplained_red:
        gate = "HALT_COLLAPSE"

    report = CandidateSmokeReport(
        gate=gate,
        bundle_dir=str(bundle_dir),
        seed=int(seed),
        eval_budget=int(eval_budget),
        max_runtime_seconds=float(max_runtime_seconds),
        alns_wouda_feasible=alns_feasible,
        feasible_candidate_count=candidate_count,
        rows=rows,
    )
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def annotate_collapse_diagnostics(rows: list[dict[str, Any]], *, eval_budget: int = FORMAL_COLLAPSE_MIN_EVAL_BUDGET) -> list[dict[str, Any]]:
    """Mark unexplained duplicate algorithm outputs before formal E2."""

    out = [dict(row) for row in rows]
    for row in out:
        row.setdefault("collapse_status", "green")
        row.setdefault("collapse_explanation", "")
    if int(eval_budget) < FORMAL_COLLAPSE_MIN_EVAL_BUDGET:
        for row in out:
            row["collapse_status"] = "not_checked_budget_below_w1_threshold"
            row["collapse_explanation"] = (
                f"collapse_check_deferred_until_eval_budget>={FORMAL_COLLAPSE_MIN_EVAL_BUDGET}"
            )
        return out
    for idx, left in enumerate(out):
        for right in out[idx + 1 :]:
            if left.get("algorithm") == right.get("algorithm"):
                continue
            if not left.get("feasible") or not right.get("feasible"):
                continue
            if left.get("solution_signature_hash") != right.get("solution_signature_hash"):
                continue
            if abs(float(left.get("best_cost") or math.inf) - float(right.get("best_cost") or -math.inf)) > 1e-6:
                continue
            improved = (
                float(left.get("best_cost") or math.inf) < float(left.get("shared_seed_cost") or -math.inf) - 1e-9
                and float(right.get("best_cost") or math.inf) < float(right.get("shared_seed_cost") or -math.inf) - 1e-9
            )
            traces_differ = left.get("native_operator_trace") != right.get("native_operator_trace")
            if improved and traces_differ:
                explanation = f"verified_same_optimum_with_distinct_traces:{left['algorithm']}|{right['algorithm']}"
                for row in (left, right):
                    row["collapse_status"] = "verified_same_optimum"
                    row["collapse_explanation"] = explanation
            else:
                explanation = f"shared_solution_collapse:{left['algorithm']}|{right['algorithm']}"
                for row in (left, right):
                    row["collapse_status"] = "red"
                    row["collapse_explanation"] = explanation
    return out


def dependency_status(repo_root: str | Path) -> list[dict[str, str]]:
    """Return a compact dependency board for W1 install records."""

    root = Path(repo_root)
    return [{"package": name, "status": _importable(name, root)} for name in ["scipy", "cloudpickle", "pygad", "sko"]]


def _run_primary_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    initial_solution: Solution,
    shared_seed_cost: float,
    started: float,
) -> CandidateRunResult:
    try:
        run = run_alns_wouda(
            bundle_dir,
            iterations=None,
            seed=seed,
            policy=SearchPolicy(require_charging_signal=False),
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            initial_solution=initial_solution,
        )
        elapsed = time.perf_counter() - started
        signature = solution_signature_hash(run.best_solution)
        return CandidateRunResult(
            algorithm=PRIMARY_ALGORITHM,
            feasible=run.feasible,
            evals=run.evaluations,
            elapsed_seconds=elapsed,
            best_cost=run.best_obj,
            best_penalized_obj=run.best_obj,
            best_solution=run.best_solution,
            history=[{"eval": float(run.evaluations), "best_obj": float(run.best_obj)}],
            status="feasible" if run.feasible else "failed",
            failure_reason="" if run.feasible else "ALNS-Wouda returned infeasible best solution",
            adapter="native_alns_wouda",
            import_status="local_reference_package_loaded",
            package_loaded=True,
            operator_trace=[
                {"operator": "native_alns_destroy_repair", "eval": float(run.evaluations), "best_obj": float(run.best_obj)}
            ],
            shared_seed_cost=shared_seed_cost,
            solution_signature_hash=signature,
            search_diagnostics={
                **_empty_search_diagnostics(),
                "candidate_generated": int(run.evaluations),
                "candidate_feasible": 1 if run.feasible else 0,
                "candidate_accepted": 1 if run.feasible else 0,
                "diagnosis": "native ALNS-Wouda completed through package operators; feasible best returned.",
            },
            actual_moves=run.actual_moves,
            candidate_scores=run.candidate_scores,
            repair_scores=run.repair_scores,
            repair_delta_count=run.repair_delta_count,
            operator_counts=run.operator_counts,
        )
    except Exception as exc:  # pragma: no cover - smoke board records failures.
        return CandidateRunResult(
            algorithm=PRIMARY_ALGORITHM,
            feasible=False,
            evals=0,
            elapsed_seconds=time.perf_counter() - started,
            best_cost=None,
            best_penalized_obj=None,
            best_solution=None,
            history=[],
            status="failed",
            failure_reason=f"{type(exc).__name__}: {exc}",
            adapter="native_alns_wouda",
            import_status="local_reference_package_loaded",
            package_loaded=True,
            shared_seed_cost=shared_seed_cost,
            search_diagnostics={
                **_empty_search_diagnostics(),
                "diagnosis": f"native ALNS-Wouda failed before candidate diagnostics: {type(exc).__name__}",
            },
        )


def _run_external_candidate(
    algorithm: str,
    bundle: SearchBundle,
    shared_solution: Solution,
    shared_seed_cost: float,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    started: float,
) -> CandidateRunResult:
    probe = _candidate_package_probe(algorithm, _repo_root_from_bundle(bundle.bundle_dir))
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        budget=EvalBudget(limit=_candidate_budget_limit(eval_budget), target=max(1, int(eval_budget))),
    )
    state = CandidateState(
        solution=shared_solution,
        context=context,
        adapter_type=_adapter_type(algorithm, probe),
        import_status=probe.status,
        package_loaded=probe.loaded,
    )
    rng = random.Random(_algorithm_seed(algorithm, seed))
    best_solution = shared_solution
    best_obj = score_reference(best_solution, context)
    best_cost = model_cost(best_solution, context)
    current = shared_solution
    current_obj = best_obj
    failure_reason = ""

    try:
        runner = _runner_for_algorithm(algorithm)
        best_solution, best_obj, best_cost, current, current_obj = runner(
            state,
            rng,
            best_solution,
            best_obj,
            best_cost,
            current,
            current_obj,
            eval_budget=max(1, int(eval_budget)),
            max_runtime_seconds=max_runtime_seconds,
            started=started,
        )
    except Exception as exc:  # pragma: no cover - status board preserves failures.
        failure_reason = f"{type(exc).__name__}: {exc}"

    _finalize_search_diagnosis(state, algorithm, shared_solution, best_solution, current)
    elapsed = time.perf_counter() - started
    feasible = best_solution is not None and not check_solution(best_solution, bundle.instance, DEFAULT_PRICES)
    status = "feasible"
    if algorithm == "NSGA-II@haris989":
        status = "scalarized_after_pareto"
    if not feasible:
        status = "failed"
    return CandidateRunResult(
        algorithm=algorithm,
        feasible=feasible,
        evals=context.budget.count if context.budget else 0,
        elapsed_seconds=elapsed,
        best_cost=best_cost if feasible else None,
        best_penalized_obj=best_obj if feasible else None,
        best_solution=best_solution if feasible else None,
        history=state.history,
        status=status,
        failure_reason="" if feasible else (failure_reason or "no feasible solution found by candidate adapter"),
        adapter=state.adapter_type,
        import_status=state.import_status,
        package_loaded=state.package_loaded,
        operator_trace=state.operator_trace,
        shared_seed_cost=shared_seed_cost,
        solution_signature_hash=solution_signature_hash(best_solution) if feasible else "",
        search_diagnostics=dict(state.search_diagnostics),
        actual_moves=int(state.search_diagnostics.get("operator_calls", 0)),
        candidate_scores=int(context.score_counts.get("candidate", 0)),
        repair_scores=int(context.score_counts.get("repair_delta", 0)),
        repair_delta_count=int(context.score_counts.get("repair_delta", 0)),
        operator_counts=_operator_counts_from_trace(state.operator_trace),
    )


def _runner_for_algorithm(algorithm: str) -> Callable[..., tuple[Solution, float, float, Solution, float]]:
    if algorithm == "VNS@Valdecy":
        return _run_vns_path
    if algorithm in {"PyGAD", "scikit-opt-GA"}:
        return _run_ga_path
    if algorithm == "scikit-opt-SA":
        return _run_sa_path
    if algorithm == "NSGA-II@haris989":
        return _run_nsga_path
    if algorithm == "ALNS@wangqianlongucas":
        return _run_alns_thin_path
    if algorithm == "DR-ALNS":
        return _run_dr_alns_path
    raise ValueError(f"HALT_W1_ADAPTER: unknown candidate algorithm {algorithm}")


def _run_vns_path(
    state: CandidateState,
    rng: random.Random,
    best_solution: Solution,
    best_obj: float,
    best_cost: float,
    current: Solution,
    current_obj: float,
    *,
    eval_budget: int,
    max_runtime_seconds: float,
    started: float,
) -> tuple[Solution, float, float, Solution, float]:
    # v2026-06-12: W1f starts with path-local neighborhoods and only treats a
    # feasible changed route set as an accepted VNS move.
    neighborhoods = ["two_opt_route", "relocate_customer", "swap_customers", "merge_routes"]
    k = 0
    move_idx = 0
    while _search_can_continue(state.context, eval_budget, started, max_runtime_seconds):
        move_idx += 1
        op = neighborhoods[k % len(neighborhoods)]
        outcome = _apply_path_operator_outcome(current, state.context, rng, op)
        candidate = outcome.solution
        score = _score(candidate, state.context)
        accept = outcome.feasible and outcome.changed and score <= current_obj + 1e-9
        _record_operator_outcome(state, outcome, accepted=accept)
        state.operator_trace.append(
            {
                "operator": f"vns_{op}",
                "eval": _eval_count(state.context),
                "move": move_idx,
                "produced": outcome.produced,
                "feasible": outcome.feasible,
                "changed": outcome.changed,
                "accepted": accept,
            }
        )
        if accept:
            current, current_obj = candidate, score
            k = 0
        else:
            k += 1
        best_solution, best_obj, best_cost = _maybe_update_best(candidate, score, best_solution, best_obj, best_cost, state)
        _record_history(state, _eval_count(state.context), best_obj)
    return best_solution, best_obj, best_cost, current, current_obj


def _run_ga_path(
    state: CandidateState,
    rng: random.Random,
    best_solution: Solution,
    best_obj: float,
    best_cost: float,
    current: Solution,
    current_obj: float,
    *,
    eval_budget: int,
    max_runtime_seconds: float,
    started: float,
) -> tuple[Solution, float, float, Solution, float]:
    pop_size = 8
    population = [current]
    for idx in range(pop_size - 1):
        outcome = _apply_path_operator_outcome(current, state.context, rng, _ga_seed_operator(idx))
        _record_operator_outcome(state, outcome, accepted=outcome.feasible and outcome.changed)
        population.append(outcome.solution)
    scored = [(_score(solution, state.context), solution) for solution in population]
    move_idx = 0
    while _search_can_continue(state.context, eval_budget, started, max_runtime_seconds):
        move_idx += 1
        scored.sort(key=lambda item: item[0])
        parent_a = scored[rng.randrange(min(4, len(scored)))][1]
        parent_b = scored[rng.randrange(min(4, len(scored)))][1]
        child = _route_crossover(parent_a, parent_b, state.context, rng)
        outcome = _apply_path_operator_outcome(child, state.context, rng, rng.choice(["relocate_customer", "swap_customers", "vehicle_type_flip"]))
        child = outcome.solution
        child_score = _score(child, state.context)
        scored.append((child_score, child))
        scored = scored[:pop_size]
        accepted = outcome.feasible and outcome.changed and child_score <= scored[-1][0] + 1e-9
        _record_operator_outcome(state, outcome, accepted=accepted)
        state.operator_trace.append({"operator": "ga_crossover_mutation", "eval": _eval_count(state.context), "move": move_idx, "accepted": accepted})
        best_solution, best_obj, best_cost = _maybe_update_best(child, child_score, best_solution, best_obj, best_cost, state)
        _record_history(state, _eval_count(state.context), best_obj)
    return best_solution, best_obj, best_cost, scored[0][1], scored[0][0]


def _run_sa_path(
    state: CandidateState,
    rng: random.Random,
    best_solution: Solution,
    best_obj: float,
    best_cost: float,
    current: Solution,
    current_obj: float,
    *,
    eval_budget: int,
    max_runtime_seconds: float,
    started: float,
    recorder: Callable[..., None] | None = None,
) -> tuple[Solution, float, float, Solution, float]:
    temperature = 250.0
    operators = ["relocate_customer", "swap_customers", "two_opt_route", "vehicle_type_flip"]
    move_idx = 0
    while _search_can_continue(state.context, eval_budget, started, max_runtime_seconds):
        move_idx += 1
        selected_operator = rng.choice(operators)
        previous_current = current
        previous_current_obj = current_obj
        previous_best_obj = best_obj
        outcome = _apply_path_operator_outcome(current, state.context, rng, selected_operator)
        candidate = outcome.solution
        score = _score(candidate, state.context)
        delta = score - current_obj
        accept = outcome.feasible and outcome.changed and (delta <= 0.0 or rng.random() < math.exp(-delta / max(1e-9, temperature)))
        improved_current = score < previous_current_obj - 1e-9
        _record_operator_outcome(state, outcome, accepted=accept)
        if accept:
            current, current_obj = candidate, score
        state.operator_trace.append(
            {
                "operator": "sa_metropolis_path_move",
                "eval": _eval_count(state.context),
                "move": move_idx,
                "temperature": temperature,
                "produced": outcome.produced,
                "feasible": outcome.feasible,
                "changed": outcome.changed,
                "accepted": accept,
            }
        )
        decision_temperature = temperature
        temperature *= 0.995
        best_solution, best_obj, best_cost = _maybe_update_best(candidate, score, best_solution, best_obj, best_cost, state)
        if recorder is not None:
            recorder(
                iteration=move_idx,
                previous_current=previous_current,
                current=current,
                best_solution=best_solution,
                candidate=candidate,
                candidate_obj=score,
                previous_best_obj=previous_best_obj,
                accepted=accept,
                improved_current=improved_current,
                destroy_op="sa_move",
                repair_op=selected_operator,
                remove_count_q=0,
                temperature=decision_temperature,
            )
        _record_history(state, _eval_count(state.context), best_obj)
    return best_solution, best_obj, best_cost, current, current_obj


def _run_nsga_path(
    state: CandidateState,
    rng: random.Random,
    best_solution: Solution,
    best_obj: float,
    best_cost: float,
    current: Solution,
    current_obj: float,
    *,
    eval_budget: int,
    max_runtime_seconds: float,
    started: float,
) -> tuple[Solution, float, float, Solution, float]:
    population = [current]
    for op in ["vehicle_type_flip", "relocate_customer", "swap_customers", "two_opt_route", "merge_routes"]:
        outcome = _apply_path_operator_outcome(current, state.context, rng, op)
        _record_operator_outcome(state, outcome, accepted=outcome.feasible and outcome.changed)
        population.append(outcome.solution)
    move_idx = 0
    while _search_can_continue(state.context, eval_budget, started, max_runtime_seconds):
        move_idx += 1
        offspring = []
        for _ in range(4):
            if not _search_can_continue(state.context, eval_budget, started, max_runtime_seconds):
                break
            outcome = _apply_path_operator_outcome(
                rng.choice(population),
                state.context,
                rng,
                rng.choice(["vehicle_type_flip", "relocate_customer", "swap_customers"]),
            )
            _record_operator_outcome(state, outcome, accepted=outcome.feasible and outcome.changed)
            offspring.append(outcome.solution)
        if not offspring:
            break
        combined = population + offspring
        ranked = sorted(combined, key=lambda solution: (_pareto_rank_key(solution, state.context), solution_signature_hash(solution)))
        population = ranked[: max(4, min(10, len(ranked)))]
        candidate = population[0]
        score = _score(candidate, state.context)
        state.operator_trace.append({"operator": "nsga_fast_non_dominated_sort", "eval": _eval_count(state.context), "move": move_idx, "front_size": len(population)})
        best_solution, best_obj, best_cost = _maybe_update_best(candidate, score, best_solution, best_obj, best_cost, state)
        _record_history(state, _eval_count(state.context), best_obj)
    return best_solution, best_obj, best_cost, population[0], score_reference(population[0], state.context)


def _run_alns_thin_path(
    state: CandidateState,
    rng: random.Random,
    best_solution: Solution,
    best_obj: float,
    best_cost: float,
    current: Solution,
    current_obj: float,
    *,
    eval_budget: int,
    max_runtime_seconds: float,
    started: float,
    recorder: Callable[..., None] | None = None,
) -> tuple[Solution, float, float, Solution, float]:
    destroy_ops = ["remove_reinsert_route", "relocate_customer", "vehicle_type_flip"]
    repair_ops = ["merge_routes", "swap_customers", "two_opt_route"]
    weights = {op: 1.0 for op in [*destroy_ops, *repair_ops]}
    move_idx = 0
    while _search_can_continue(state.context, eval_budget, started, max_runtime_seconds):
        move_idx += 1
        destroy = _weighted_choice(rng, destroy_ops, weights)
        repair = _weighted_choice(rng, repair_ops, weights)
        previous_current = current
        previous_current_obj = current_obj
        previous_best_obj = best_obj
        destroy_outcome = _apply_path_operator_outcome(current, state.context, rng, destroy)
        repair_outcome = _apply_path_operator_outcome(destroy_outcome.solution, state.context, rng, repair)
        candidate = repair_outcome.solution
        score = _score(candidate, state.context)
        changed = solution_signature_hash(candidate) != solution_signature_hash(current)
        produced = destroy_outcome.produced or repair_outcome.produced
        feasible = repair_outcome.feasible or (destroy_outcome.feasible and solution_signature_hash(candidate) == solution_signature_hash(destroy_outcome.solution))
        outcome = _OperatorOutcome(candidate, produced=produced, feasible=feasible, changed=changed)
        accept = feasible and changed and (score <= current_obj + 500.0 or rng.random() < 0.05)
        _record_operator_outcome(state, outcome, accepted=accept)
        if accept:
            current, current_obj = candidate, score
            weights[destroy] += 0.2
            weights[repair] += 0.2
        state.operator_trace.append(
            {
                "operator": f"alns_destroy_repair:{destroy}+{repair}",
                "eval": _eval_count(state.context),
                "move": move_idx,
                "produced": produced,
                "feasible": feasible,
                "changed": changed,
                "accepted": accept,
            }
        )
        best_solution, best_obj, best_cost = _maybe_update_best(candidate, score, best_solution, best_obj, best_cost, state)
        if recorder is not None:
            recorder(
                iteration=move_idx,
                previous_current=previous_current,
                current=current,
                best_solution=best_solution,
                candidate=candidate,
                candidate_obj=score,
                previous_best_obj=previous_best_obj,
                accepted=accept,
                improved_current=score < previous_current_obj - 1e-9,
                destroy_op=destroy,
                repair_op=repair,
                remove_count_q=int(destroy_outcome.metadata.get("removed_count", 0)) if hasattr(destroy_outcome, "metadata") else 0,
            )
        _record_history(state, _eval_count(state.context), best_obj)
    return best_solution, best_obj, best_cost, current, current_obj


def _run_alns_strong_path(
    state: CandidateState,
    rng: random.Random,
    best_solution: Solution,
    best_obj: float,
    best_cost: float,
    current: Solution,
    current_obj: float,
    *,
    eval_budget: int,
    max_runtime_seconds: float,
    started: float,
    recorder: Callable[..., None] | None = None,
) -> tuple[Solution, float, float, Solution, float]:
    destroy_ops = ["random_customer_removal", "worst_customer_removal", "shaw_related_removal", "whole_route_removal", "route_segment_removal"]
    repair_ops = ["greedy_insert_repair", "regret2_insert_repair", "regret3_insert_repair"]
    weights = {op: 1.0 for op in [*destroy_ops, *repair_ops]}
    temperature = 250.0
    move_idx = 0
    while _search_can_continue(state.context, eval_budget, started, max_runtime_seconds):
        move_idx += 1
        destroy = _weighted_choice(rng, destroy_ops, weights)
        repair = _weighted_choice(rng, repair_ops, weights)
        previous_current = current
        previous_current_obj = current_obj
        previous_best_obj = best_obj
        outcome = _apply_strong_alns_destroy_repair(current, state.context, rng, destroy, repair)
        outcome = _improve_outcome_locally(outcome, state.context)
        candidate = outcome.solution
        score = _score(candidate, state.context)
        changed = solution_signature_hash(candidate) != solution_signature_hash(current)
        delta = score - current_obj
        accept = outcome.feasible and changed and (delta <= 0.0 or rng.random() < math.exp(-delta / max(1e-9, temperature)))
        _record_operator_outcome(state, outcome, accepted=accept)
        reward = 0.0
        if accept:
            current, current_obj = candidate, score
            reward = 2.0
            if score < previous_current_obj - 1e-9:
                reward = 8.0
            if score < previous_best_obj - 1e-9 and not check_solution(candidate, state.context.instance, state.context.prices):
                reward = 20.0
        weights[destroy] = 0.8 * weights[destroy] + 0.2 * max(0.05, reward if changed else 0.0)
        weights[repair] = 0.8 * weights[repair] + 0.2 * max(0.05, reward if changed else 0.0)
        temperature *= 0.999
        state.operator_trace.append(
            {
                "operator": f"alns_strong_destroy_repair:{destroy}+{repair}",
                "eval": _eval_count(state.context),
                "move": move_idx,
                "removed_count": outcome.metadata.get("removed_count", 0),
                "produced": outcome.produced,
                "feasible": outcome.feasible,
                "changed": changed,
                "accepted": accept,
                "temperature": temperature,
            }
        )
        best_solution, best_obj, best_cost = _maybe_update_best(candidate, score, best_solution, best_obj, best_cost, state)
        if recorder is not None:
            recorder(
                iteration=move_idx,
                previous_current=previous_current,
                current=current,
                best_solution=best_solution,
                candidate=candidate,
                candidate_obj=score,
                previous_best_obj=previous_best_obj,
                accepted=accept,
                improved_current=score < previous_current_obj - 1e-9,
                destroy_op=destroy,
                repair_op=repair,
                remove_count_q=int(outcome.metadata.get("removed_count", 0)),
                temperature=temperature,
            )
        _record_history(state, _eval_count(state.context), best_obj)
    return best_solution, best_obj, best_cost, current, current_obj


def _run_dr_alns_path(
    state: CandidateState,
    rng: random.Random,
    best_solution: Solution,
    best_obj: float,
    best_cost: float,
    current: Solution,
    current_obj: float,
    *,
    eval_budget: int,
    max_runtime_seconds: float,
    started: float,
    recorder: Callable[..., None] | None = None,
) -> tuple[Solution, float, float, Solution, float]:
    # v2026-06-12: W1f gives DR-ALNS a real path-level destroy/repair adapter:
    # remove customers from route sets, then regret-reinsert with EV charging
    # repair when an EV route is touched.
    destroy_ops = ["random_customer_removal", "worst_customer_removal", "route_segment_removal"]
    if _crush_flag_enabled("SETP_ALNS_CRUSH_ROUTE_ELIMINATION"):
        destroy_ops.append("route_elimination")
    weights = {op: 1.0 for op in destroy_ops}
    move_idx = 0
    while _search_can_continue(state.context, eval_budget, started, max_runtime_seconds):
        move_idx += 1
        destroy = _weighted_choice(rng, destroy_ops, weights)
        previous_current = current
        previous_current_obj = current_obj
        previous_best_obj = best_obj
        outcome = _apply_dr_destroy_repair(current, state.context, rng, destroy)
        outcome = _improve_outcome_locally(outcome, state.context)
        candidate = outcome.solution
        score = _score(candidate, state.context)
        threshold = max(5.0, 300.0 * (1.0 - _eval_count(state.context) / max(1, eval_budget)))
        accept = outcome.feasible and outcome.changed and (score <= current_obj + threshold or rng.random() < 0.03)
        improved_current = score < previous_current_obj - 1e-9
        _record_operator_outcome(state, outcome, accepted=accept)
        if accept:
            current, current_obj = candidate, score
            weights[destroy] += 0.2
        state.operator_trace.append(
            {
                "operator": f"dr_alns_destroy_regret_repair:{destroy}",
                "eval": _eval_count(state.context),
                "move": move_idx,
                "removed_count": outcome.metadata.get("removed_count", 0),
                "produced": outcome.produced,
                "feasible": outcome.feasible,
                "changed": outcome.changed,
                "accepted": accept,
            }
        )
        best_solution, best_obj, best_cost = _maybe_update_best(candidate, score, best_solution, best_obj, best_cost, state)
        if recorder is not None:
            recorder(
                iteration=move_idx,
                previous_current=previous_current,
                current=current,
                best_solution=best_solution,
                candidate=candidate,
                candidate_obj=score,
                previous_best_obj=previous_best_obj,
                accepted=accept,
                improved_current=improved_current,
                destroy_op=destroy,
                repair_op="regret_reinsert",
                remove_count_q=int(outcome.metadata.get("removed_count", 0)),
            )
        _record_history(state, _eval_count(state.context), best_obj)
    return best_solution, best_obj, best_cost, current, current_obj


def _score(solution: Solution, context: EvaluationContext) -> float:
    try:
        return score_candidate(solution, context, label="candidate")
    except RuntimeError:
        raise


def _maybe_update_best(
    candidate: Solution,
    score: float,
    best_solution: Solution,
    best_obj: float,
    best_cost: float,
    state: CandidateState,
) -> tuple[Solution, float, float]:
    try:
        candidate = normalize_solution_vehicle_trips(candidate, state.context.instance)
    except ValueError:
        return best_solution, best_obj, best_cost
    if score < best_obj - 1e-9 and not check_solution(candidate, state.context.instance, state.context.prices):
        state.search_diagnostics["best_updates"] = int(state.search_diagnostics.get("best_updates", 0)) + 1
        return candidate, float(score), model_cost(candidate, state.context)
    return best_solution, best_obj, best_cost


def _record_history(state: CandidateState, eval_count: int, best_obj: float) -> None:
    if eval_count == 1 or eval_count % 100 == 0:
        state.history.append({"eval": float(eval_count), "best_obj": float(best_obj)})


def _record_operator_outcome(state: CandidateState, outcome: _OperatorOutcome, *, accepted: bool = False) -> None:
    # v2026-06-12: W1e records where each adapter loses candidates: generation,
    # feasibility check, or acceptance.
    diag = state.search_diagnostics
    diag["operator_calls"] = int(diag.get("operator_calls", 0)) + 1
    if outcome.produced:
        diag["candidate_generated"] = int(diag.get("candidate_generated", 0)) + 1
    if outcome.feasible:
        diag["candidate_feasible"] = int(diag.get("candidate_feasible", 0)) + 1
    if outcome.changed:
        diag["candidate_changed"] = int(diag.get("candidate_changed", 0)) + 1
    if accepted:
        diag["candidate_accepted"] = int(diag.get("candidate_accepted", 0)) + 1
        if outcome.changed:
            diag["accepted_changed"] = int(diag.get("accepted_changed", 0)) + 1


def _finalize_search_diagnosis(
    state: CandidateState,
    algorithm: str,
    shared_solution: Solution,
    best_solution: Solution,
    current: Solution,
) -> None:
    shared_hash = solution_signature_hash(shared_solution)
    best_hash = solution_signature_hash(best_solution)
    current_hash = solution_signature_hash(current)
    diag = state.search_diagnostics
    diag["returned_shared_seed"] = best_hash == shared_hash
    diag["current_shared_seed"] = current_hash == shared_hash
    if not diag.get("diagnosis"):
        if int(diag.get("candidate_generated", 0)) == 0:
            diagnosis = f"{algorithm}: operators were called but produced no candidate solution before check."
        elif int(diag.get("candidate_feasible", 0)) == 0:
            diagnosis = f"{algorithm}: candidates were generated but all were rejected by check_solution."
        elif int(diag.get("candidate_accepted", 0)) == 0:
            diagnosis = f"{algorithm}: feasible candidates were generated but acceptance rejected all moves."
        elif best_hash == shared_hash and current_hash != shared_hash:
            diagnosis = f"{algorithm}: accepted distinct path moves, but strict global-best reporting still selected the warm start."
        elif best_hash == shared_hash:
            diagnosis = f"{algorithm}: accepted moves did not change the warm-start route signature."
        else:
            diagnosis = f"{algorithm}: path operators generated feasible accepted moves and returned a distinct solution."
        diag["diagnosis"] = diagnosis


def _apply_path_operator(
    solution: Solution,
    context: EvaluationContext,
    rng: random.Random,
    operator: str,
) -> Solution:
    return _apply_path_operator_outcome(solution, context, rng, operator).solution


def _improve_outcome_locally(outcome: _OperatorOutcome, context: EvaluationContext) -> _OperatorOutcome:
    if not outcome.feasible or not outcome.changed:
        return outcome
    improved = improve_solution_locally(outcome.solution, context)
    if solution_signature_hash(improved) == solution_signature_hash(outcome.solution):
        return outcome
    return replace(outcome, solution=improved, changed=True, detail=f"{outcome.detail}|local_search")


def _apply_path_operator_outcome(
    solution: Solution,
    context: EvaluationContext,
    rng: random.Random,
    operator: str,
) -> _OperatorOutcome:
    builders: dict[str, Callable[[Solution, EvaluationContext, random.Random], Solution | None]] = {
        "two_opt_route": _op_two_opt_route,
        "relocate_customer": _op_relocate_customer,
        "swap_customers": _op_swap_customers,
        "merge_routes": _op_merge_routes,
        "vehicle_type_flip": _op_vehicle_type_flip,
        "remove_reinsert_route": _op_remove_reinsert_route,
    }
    candidate = builders[operator](solution, context, rng)
    if candidate is None:
        return _OperatorOutcome(solution, produced=False, feasible=False, changed=False, detail="operator_returned_none")
    try:
        candidate = normalize_solution_vehicle_trips(candidate, context.instance)
    except ValueError as exc:
        return _OperatorOutcome(solution, produced=True, feasible=False, changed=False, detail=str(exc))
    changed = solution_signature_hash(candidate) != solution_signature_hash(solution)
    return _OperatorOutcome(candidate, produced=True, feasible=True, changed=changed, detail="feasibility_deferred_to_candidate_score")


def _op_two_opt_route(solution: Solution, context: EvaluationContext, rng: random.Random) -> Solution | None:
    route_indices = [idx for idx, route in enumerate(solution.routes) if len(_route_customers(route, context.instance)) >= 3]
    if not route_indices:
        return None
    idx = rng.choice(route_indices)
    route = solution.routes[idx]
    customers = _route_customers(route, context.instance)
    i, j = sorted(rng.sample(range(len(customers)), 2))
    customers[i : j + 1] = reversed(customers[i : j + 1])
    routes = list(solution.routes)
    routes[idx] = _route_with_customers(route, customers)
    return _rebuild_solution(routes, context)


def _op_relocate_customer(solution: Solution, context: EvaluationContext, rng: random.Random) -> Solution | None:
    positions = _customer_positions(solution, context.instance)
    if len(positions) < 2:
        return None
    src_route_idx, customer_id = rng.choice(positions)
    dst_route_idx = rng.randrange(len(solution.routes))
    if src_route_idx == dst_route_idx and len(_route_customers(solution.routes[src_route_idx], context.instance)) <= 1:
        return None
    routes = list(solution.routes)
    src_customers = _route_customers(routes[src_route_idx], context.instance)
    if customer_id not in src_customers:
        return None
    src_customers.remove(customer_id)
    dst_customers = _route_customers(routes[dst_route_idx], context.instance)
    insert_at = rng.randrange(len(dst_customers) + 1)
    dst_customers.insert(insert_at, customer_id)
    if src_customers:
        routes[src_route_idx] = _route_with_customers(routes[src_route_idx], src_customers)
    else:
        routes.pop(src_route_idx)
        if dst_route_idx > src_route_idx:
            dst_route_idx -= 1
    routes[dst_route_idx] = _route_with_customers(routes[dst_route_idx], dst_customers)
    return _rebuild_solution(routes, context)


def _op_swap_customers(solution: Solution, context: EvaluationContext, rng: random.Random) -> Solution | None:
    positions = _customer_positions(solution, context.instance)
    if len(positions) < 2:
        return None
    (route_a_idx, customer_a), (route_b_idx, customer_b) = rng.sample(positions, 2)
    if customer_a == customer_b:
        return None
    routes = list(solution.routes)
    customers_a = _route_customers(routes[route_a_idx], context.instance)
    customers_b = _route_customers(routes[route_b_idx], context.instance)
    pos_a = customers_a.index(customer_a)
    pos_b = customers_b.index(customer_b)
    customers_a[pos_a], customers_b[pos_b] = customer_b, customer_a
    routes[route_a_idx] = _route_with_customers(routes[route_a_idx], customers_a)
    routes[route_b_idx] = _route_with_customers(routes[route_b_idx], customers_b)
    return _rebuild_solution(routes, context)


def _op_merge_routes(solution: Solution, context: EvaluationContext, rng: random.Random) -> Solution | None:
    route_pairs = [
        (i, j)
        for i, a in enumerate(solution.routes)
        for j, b in enumerate(solution.routes)
        if i < j and a.home_depot_id == b.home_depot_id and a.vehicle_type.lower() == b.vehicle_type.lower()
    ]
    if not route_pairs:
        return None
    i, j = rng.choice(route_pairs)
    routes = list(solution.routes)
    merged_customers = [*_route_customers(routes[i], context.instance), *_route_customers(routes[j], context.instance)]
    routes[i] = _route_with_customers(routes[i], merged_customers)
    routes.pop(j)
    return _rebuild_solution(routes, context)


def _op_vehicle_type_flip(solution: Solution, context: EvaluationContext, rng: random.Random) -> Solution | None:
    if not solution.routes:
        return None
    idx = rng.randrange(len(solution.routes))
    routes = list(solution.routes)
    route = routes[idx]
    new_type = "ev" if route.vehicle_type.lower() == "cv" else "cv"
    prefix = "EV" if new_type == "ev" else "CV"
    routes[idx] = replace(route, vehicle_id=f"{prefix}_CAND_{idx + 1}", vehicle_type=new_type)
    return _rebuild_solution(routes, context)


def _op_remove_reinsert_route(solution: Solution, context: EvaluationContext, rng: random.Random) -> Solution | None:
    if len(solution.routes) < 2:
        return None
    idx = rng.randrange(len(solution.routes))
    route = solution.routes[idx]
    customers = _route_customers(route, context.instance)
    if not customers:
        return None
    routes = [item for pos, item in enumerate(solution.routes) if pos != idx]
    for customer_id in customers:
        target_idx = rng.randrange(len(routes))
        target_customers = _route_customers(routes[target_idx], context.instance)
        target_customers.insert(rng.randrange(len(target_customers) + 1), customer_id)
        routes[target_idx] = _route_with_customers(routes[target_idx], target_customers)
    return _rebuild_solution(routes, context)


def _apply_dr_destroy_repair(
    solution: Solution,
    context: EvaluationContext,
    rng: random.Random,
    destroy_operator: str,
) -> _OperatorOutcome:
    if destroy_operator == "route_elimination":
        return _apply_dr_route_elimination(solution, context, rng)
    removed = _dr_destroy_customer_ids(solution, context, rng, destroy_operator)
    if not removed:
        return _OperatorOutcome(
            solution,
            produced=False,
            feasible=False,
            changed=False,
            detail="destroy_selected_no_customers",
            metadata={"removed_count": 0},
        )
    partial_routes = _routes_without_customers(solution.routes, set(removed), context.instance)
    repaired = _regret_reinsert_removed(partial_routes, list(removed), context)
    if repaired is None:
        return _OperatorOutcome(
            solution,
            produced=True,
            feasible=False,
            changed=False,
            detail="regret_repair_failed",
            metadata={"removed_count": len(removed)},
        )
    changed = solution_signature_hash(repaired) != solution_signature_hash(solution)
    return _OperatorOutcome(
        repaired,
        produced=True,
        feasible=True,
        changed=changed,
        metadata={"removed_count": len(removed)},
    )


def _crush_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "1").lower() not in {"0", "false", "no"}


def _apply_dr_route_elimination(solution: Solution, context: EvaluationContext, rng: random.Random) -> _OperatorOutcome:
    route_items = [(idx, route) for idx, route in enumerate(solution.routes) if _route_customers(route, context.instance)]
    if len(route_items) < 2:
        return _OperatorOutcome(solution, produced=False, feasible=False, changed=False, detail="route_elimination_needs_two_routes", metadata={"removed_count": 0})
    max_remove = min(3, len(route_items) - 1)
    remove_count = rng.randint(1, max_remove)
    ranked = sorted(route_items, key=lambda item: _weak_route_key(item[1], context.instance))
    removed_customers = [
        customer_id
        for _, route in ranked[:remove_count]
        for customer_id in _route_customers(route, context.instance)
    ]
    if not removed_customers:
        return _OperatorOutcome(solution, produced=False, feasible=False, changed=False, detail="route_elimination_selected_no_customers", metadata={"removed_count": 0})
    partial_routes = _routes_without_customers(solution.routes, set(removed_customers), context.instance)
    repaired = _regret_reinsert_removed(partial_routes, removed_customers, context, allow_new_route=False)
    if repaired is None:
        return _OperatorOutcome(solution, produced=True, feasible=False, changed=False, detail="route_elimination_repair_failed", metadata={"removed_count": len(removed_customers)})
    violations = check_solution(repaired, context.instance, context.prices)
    route_count_delta = len(repaired.routes) - len(solution.routes)
    cost_delta = model_cost(repaired, context) - model_cost(solution, context) if not violations else math.inf
    changed = solution_signature_hash(repaired) != solution_signature_hash(solution)
    accepted_shape = changed and not violations and route_count_delta < 0 and cost_delta < -1e-9
    return _OperatorOutcome(
        repaired if accepted_shape else solution,
        produced=True,
        feasible=accepted_shape,
        changed=accepted_shape,
        violation_count=len(violations),
        detail="route_elimination_improved" if accepted_shape else "route_elimination_no_route_cost_drop",
        metadata={"removed_count": len(removed_customers), "route_count_delta": route_count_delta, "cost_delta": float(cost_delta)},
    )


def _apply_strong_alns_destroy_repair(
    solution: Solution,
    context: EvaluationContext,
    rng: random.Random,
    destroy_operator: str,
    repair_operator: str,
) -> _OperatorOutcome:
    removed = _strong_destroy_customer_ids(solution, context, rng, destroy_operator)
    if not removed:
        return _OperatorOutcome(solution, produced=False, feasible=False, changed=False, detail="destroy_selected_no_customers", metadata={"removed_count": 0})
    partial_routes = _routes_without_customers(solution.routes, set(removed), context.instance)
    mode = {"greedy_insert_repair": "greedy", "regret2_insert_repair": "regret2", "regret3_insert_repair": "regret3"}[repair_operator]
    repaired = repair_removed_customers(Solution(routes=partial_routes, charging_actions=_actions_for_routes(solution, partial_routes)), list(removed), context, _ThinPolicy(), mode=mode)
    if repaired is None:
        return _OperatorOutcome(solution, produced=True, feasible=False, changed=False, detail="strong_repair_failed", metadata={"removed_count": len(removed)})
    violations = check_solution(repaired, context.instance, context.prices)
    changed = solution_signature_hash(repaired) != solution_signature_hash(solution)
    return _OperatorOutcome(
        repaired if not violations else solution,
        produced=True,
        feasible=not violations,
        changed=changed and not violations,
        violation_count=len(violations),
        metadata={"removed_count": len(removed)},
    )


@dataclass(frozen=True)
class _ThinPolicy:
    require_charging_signal: bool = False
    max_cv: int = 10**9
    max_ev: int = 10**9


def _strong_destroy_customer_ids(
    solution: Solution,
    context: EvaluationContext,
    rng: random.Random,
    destroy_operator: str,
) -> list[str]:
    customers = [customer_id for _, customer_id in _customer_positions(solution, context.instance)]
    if not customers:
        return []
    remove_count = _fractional_remove_count(len(customers), rng)
    if destroy_operator == "random_customer_removal":
        return rng.sample(customers, k=min(remove_count, len(customers)))
    if destroy_operator == "worst_customer_removal":
        ranked = sorted(
            ((_customer_distance_contribution(solution, context.instance, customer_id), customer_id) for customer_id in customers),
            reverse=True,
        )
        return [customer_id for _, customer_id in ranked[:remove_count]]
    if destroy_operator == "shaw_related_removal":
        seed_customer = rng.choice(customers)
        related = sorted(
            ((_path_relatedness(solution, context.instance, seed_customer, customer_id), customer_id) for customer_id in customers if customer_id != seed_customer),
            key=lambda item: (item[0], item[1]),
        )
        return [seed_customer, *[customer_id for _, customer_id in related[: max(0, remove_count - 1)]]]
    if destroy_operator == "whole_route_removal":
        routes = [route for route in solution.routes if _route_customers(route, context.instance)]
        if not routes:
            return []
        route = max(routes, key=lambda item: _route_sequence_distance(item.node_sequence, context.instance))
        return _route_customers(route, context.instance)
    if destroy_operator == "route_segment_removal":
        routes = [route for route in solution.routes if _route_customers(route, context.instance)]
        if not routes:
            return []
        route = rng.choice(routes)
        route_customers = _route_customers(route, context.instance)
        start = rng.randrange(len(route_customers))
        return route_customers[start : start + min(remove_count, len(route_customers) - start)]
    raise ValueError(f"unknown strong ALNS destroy operator {destroy_operator}")


def _fractional_remove_count(customer_count: int, rng: random.Random) -> int:
    low = min(customer_count, max(2, math.ceil(0.10 * customer_count)))
    high = min(customer_count, max(low, math.ceil(0.40 * customer_count)))
    high = min(high, 12)
    low = min(low, high)
    return rng.randint(low, high)


def _path_relatedness(solution: Solution, instance: Instance, seed_customer: str, customer_id: str) -> float:
    node_lookup = {node.node_id: node for node in instance.nodes}
    seed = node_lookup[seed_customer]
    customer = node_lookup[customer_id]
    route_of = {
        node_id: route_idx
        for route_idx, route in enumerate(solution.routes)
        for node_id in _route_customers(route, instance)
    }
    return (
        float(instance.distance(seed_customer, customer_id))
        + abs(float(seed.ready_time) - float(customer.ready_time)) * 0.1
        + abs(float(seed.due_time) - float(customer.due_time)) * 0.05
        + abs(float(seed.demand) - float(customer.demand)) * 10.0
        + (0.0 if route_of.get(seed_customer) == route_of.get(customer_id) else 10_000.0)
    )


def _actions_for_routes(solution: Solution, routes: list[Route]) -> list[ChargingAction]:
    vehicle_ids = {route.vehicle_id for route in routes}
    route_nodes = {node_id for route in routes for node_id in route.node_sequence}
    return [action for action in solution.charging_actions if action.vehicle_id in vehicle_ids and action.station_id in route_nodes]


def _dr_destroy_customer_ids(
    solution: Solution,
    context: EvaluationContext,
    rng: random.Random,
    destroy_operator: str,
) -> list[str]:
    customers = [customer_id for _, customer_id in _customer_positions(solution, context.instance)]
    if not customers:
        return []
    remove_count = rng.randint(1, max(1, min(4, len(customers) // 4 or 1)))
    if destroy_operator == "random_customer_removal":
        return rng.sample(customers, k=min(remove_count, len(customers)))
    if destroy_operator == "worst_customer_removal":
        ranked = sorted(
            ((_customer_distance_contribution(solution, context.instance, customer_id), customer_id) for customer_id in customers),
            reverse=True,
        )
        return [customer_id for _, customer_id in ranked[:remove_count]]
    if destroy_operator == "route_segment_removal":
        route_candidates = [route for route in solution.routes if _route_customers(route, context.instance)]
        if not route_candidates:
            return []
        route = rng.choice(route_candidates)
        route_customers = _route_customers(route, context.instance)
        start = rng.randrange(len(route_customers))
        length = min(remove_count, len(route_customers) - start)
        return route_customers[start : start + length]
    raise ValueError(f"unknown DR-ALNS destroy operator {destroy_operator}")


def _routes_without_customers(routes: list[Route], customer_ids: set[str], instance: Instance) -> list[Route]:
    kept: list[Route] = []
    for route in routes:
        customers = [customer_id for customer_id in _route_customers(route, instance) if customer_id not in customer_ids]
        if customers:
            kept.append(_route_with_customers(route, customers))
    return kept


def _regret_reinsert_removed(routes: list[Route], removed_customers: list[str], context: EvaluationContext, *, allow_new_route: bool = True) -> Solution | None:
    pending = list(dict.fromkeys(removed_customers))
    current_routes = list(routes)
    while pending:
        scored: list[tuple[float, float, str, list[Route]]] = []
        for customer_id in pending:
            options = _path_insertion_options(current_routes, customer_id, context, allow_new_route=allow_new_route)
            if not options:
                continue
            best_score, best_routes = options[0]
            second_score = options[1][0] if len(options) > 1 else best_score
            regret = second_score - best_score
            scored.append((-regret, best_score, customer_id, best_routes))
        if not scored:
            return None
        _, _, customer_id, current_routes = min(scored)
        pending.remove(customer_id)
    return _rebuild_solution(current_routes, context)


def _path_insertion_options(
    routes: list[Route],
    customer_id: str,
    context: EvaluationContext,
    *,
    allow_new_route: bool = True,
) -> list[tuple[float, list[Route]]]:
    options: list[tuple[float, list[Route]]] = []
    for route_idx, route in enumerate(routes):
        customers = _route_customers(route, context.instance)
        for insert_at in range(len(customers) + 1):
            candidate_customers = [*customers[:insert_at], customer_id, *customers[insert_at:]]
            candidate_route = _repaired_route_candidate(route, candidate_customers, context)
            if candidate_route is None:
                continue
            candidate_routes = list(routes)
            candidate_routes[route_idx] = candidate_route
            options.append((_path_repair_delta_score(candidate_route, context, base_route=route), candidate_routes))

    if allow_new_route:
        depot_id = _nearest_depot_id(customer_id, context.instance)
        vehicle_id = _next_path_vehicle_id(routes, "CV_DR")
        if _route_customer_plan_feasible(depot_id, [customer_id], context.instance, context.prices):
            candidate_routes = [*routes, Route(vehicle_id, "cv", depot_id, [depot_id, customer_id, depot_id])]
            options.append((_path_repair_delta_score(candidate_routes[-1], context), candidate_routes))
    return sorted(options, key=lambda item: (item[0], solution_signature_hash(Solution(routes=item[1]))))


def _path_repair_delta_score(route: Route, context: EvaluationContext, *, base_route: Route | None = None) -> float:
    record_repair_delta(context)
    return route_model_cost_delta(route, [], context, base_route=base_route)


def _repaired_route_candidate(route: Route, customers: list[str], context: EvaluationContext) -> Route | None:
    if route.vehicle_type.lower() == "ev":
        try:
            repaired, _ = repair_route_charging(_route_with_customers(route, customers), context.instance, context.carbon_profile, context.prices)
        except ValueError:
            return None
        return repaired
    if not _route_customer_plan_feasible(route.home_depot_id, customers, context.instance, context.prices):
        return None
    return _route_with_customers(route, customers)


def _route_set_distance(routes: list[Route], instance: Instance) -> float:
    return sum(_route_sequence_distance(route.node_sequence, instance) for route in routes)


def _route_sequence_distance(sequence: list[str], instance: Instance) -> float:
    index = instance.node_index
    return sum(float(instance.distance_matrix[index[a]][index[b]]) for a, b in zip(sequence, sequence[1:]))


def _weak_route_key(route: Route, instance: Instance) -> tuple[float, float, str]:
    customers = _route_customers(route, instance)
    distance_per_customer = _route_sequence_distance(route.node_sequence, instance) / max(1, len(customers))
    return (float(len(customers)), -float(distance_per_customer), route.vehicle_id)


def _customer_distance_contribution(solution: Solution, instance: Instance, customer_id: str) -> float:
    for route in solution.routes:
        seq = list(route.node_sequence)
        for idx, node_id in enumerate(seq[1:-1], start=1):
            if node_id != customer_id:
                continue
            return instance.distance(seq[idx - 1], node_id) + instance.distance(node_id, seq[idx + 1]) - instance.distance(seq[idx - 1], seq[idx + 1])
    return 0.0


def _nearest_depot_id(customer_id: str, instance: Instance) -> str:
    customer = next(node for node in instance.nodes if node.node_id == customer_id)
    return _nearest_depot(customer, instance).node_id


def _next_path_vehicle_id(routes: list[Route], prefix: str) -> str:
    used = {route.vehicle_id for route in routes}
    idx = 1
    while f"{prefix}{idx}" in used:
        idx += 1
    return f"{prefix}{idx}"


def _route_crossover(parent_a: Solution, parent_b: Solution, context: EvaluationContext, rng: random.Random) -> Solution:
    node_lookup = {node.node_id: node for node in context.instance.nodes}
    all_customers = {node.node_id for node in context.instance.nodes if node.node_type.lower() == "c"}
    keep_routes = rng.sample(parent_a.routes, k=max(1, len(parent_a.routes) // 2)) if parent_a.routes else []
    used = {node_id for route in keep_routes for node_id in route.node_sequence if node_lookup.get(node_id) and node_lookup[node_id].node_type.lower() == "c"}
    routes = [route for route in keep_routes]
    for route in parent_b.routes:
        missing = [node_id for node_id in _route_customers(route, context.instance) if node_id not in used]
        if missing:
            routes.append(_route_with_customers(route, missing))
            used.update(missing)
    still_missing = sorted(all_customers - used)
    if still_missing:
        depot_id = _depots(context.instance)[0].node_id
        routes.append(Route(f"CV_XOVER_{len(routes) + 1}", "cv", depot_id, [depot_id, *still_missing, depot_id]))
    return _rebuild_solution(routes, context) or parent_a


def _rebuild_solution(routes: list[Route], context: EvaluationContext) -> Solution | None:
    rebuilt_routes: list[Route] = []
    actions: list[ChargingAction] = []
    used_ids: dict[str, int] = {}
    for idx, route in enumerate(routes):
        customers = _route_customers(route, context.instance)
        if not customers:
            continue
        vehicle_id = _unique_vehicle_id(route.vehicle_id, used_ids, idx)
        clean_route = Route(vehicle_id, route.vehicle_type.lower(), route.home_depot_id, [route.home_depot_id, *customers, route.home_depot_id])
        if clean_route.vehicle_type == "ev":
            try:
                repaired, route_actions = repair_route_charging(clean_route, context.instance, context.carbon_profile, context.prices)
            except ValueError:
                return None
            rebuilt_routes.append(repaired)
            actions.extend(route_actions)
        else:
            rebuilt_routes.append(clean_route)
    candidate = Solution(routes=rebuilt_routes, charging_actions=actions)
    return normalize_solution_vehicle_trips(candidate, context.instance)


def _unique_vehicle_id(vehicle_id: str, used_ids: dict[str, int], idx: int) -> str:
    if vehicle_id not in used_ids:
        used_ids[vehicle_id] = 1
        return vehicle_id
    used_ids[vehicle_id] += 1
    return f"{vehicle_id}_{idx + 1}_{used_ids[vehicle_id]}"


def _pareto_rank_key(solution: Solution, context: EvaluationContext) -> tuple[float, float]:
    objective = score_candidate(solution, context, label="candidate")
    metrics = evaluate(solution, context.instance, context.carbon_profile, context.prices, carbon_quota_kg=context.carbon_quota_kg)
    violations = check_solution(solution, context.instance, context.prices)
    penalty = 1_000_000_000.0 * len(violations)
    return float(objective), float(metrics["E_total"]) + penalty


def solution_signature(solution: Solution) -> dict[str, Any]:
    # v2026-06-12: W1c anti-collapse signatures must be deterministic and
    # JSON-native so the same-route/same-charge check cannot fail before gating.
    return {
        "routes": sorted(
            (
                route.vehicle_type.lower(),
                route.home_depot_id,
                tuple(route.node_sequence),
            )
            for route in solution.routes
        ),
        "charging_actions": sorted(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.charge_start_second), 6),
                round(float(action.energy_kwh), 9),
                round(float(action.occupancy_minutes), 9),
            )
            for action in solution.charging_actions
        ),
    }


def solution_signature_hash(solution: Solution) -> str:
    payload = json.dumps(solution_signature(solution), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _serializable_result(result: CandidateRunResult) -> dict[str, Any]:
    solution = result.best_solution
    row = {
        "algorithm": result.algorithm,
        "feasible": result.feasible,
        "evals": result.evals,
        "actual_evals": result.evals,
        "actual_moves": result.actual_moves,
        "candidate_scores": result.candidate_scores,
        "repair_scores": result.repair_scores,
        "repair_delta_count": result.repair_delta_count,
        "operator_counts": result.operator_counts,
        "elapsed_seconds": result.elapsed_seconds,
        "best_cost": result.best_cost,
        "best_penalized_obj": result.best_penalized_obj,
        "history": result.history,
        "status": result.status,
        "failure_reason": result.failure_reason,
        "adapter": result.adapter,
        "adapter_type": result.adapter,
        "import_status": result.import_status,
        "package_loaded": result.package_loaded,
        "native_operator_trace": result.operator_trace,
        "shared_seed_cost": result.shared_seed_cost,
        "gap_vs_alns_pct": None,
        "solution_signature_hash": result.solution_signature_hash,
        "collapse_status": result.collapse_status,
        "collapse_explanation": result.collapse_explanation,
        "search_diagnostics": result.search_diagnostics,
        "w1_diagnosis": result.search_diagnostics.get("diagnosis", ""),
        "w1e_root_cause": _w1e_root_cause(result.algorithm),
    }
    if result.best_cost is not None and result.shared_seed_cost:
        row["gap_vs_shared_seed_pct"] = (float(result.best_cost) - float(result.shared_seed_cost)) / float(result.shared_seed_cost) * 100.0
    else:
        row["gap_vs_shared_seed_pct"] = None
    row["route_count"] = len(solution.routes) if solution is not None else 0
    row["ev_route_count"] = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev") if solution is not None else 0
    row["cv_route_count"] = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv") if solution is not None else 0
    row["charging_action_count"] = len(solution.charging_actions) if solution is not None else 0
    return row


def _w1e_root_cause(algorithm: str) -> str:
    # v2026-06-12: W1e records the pre-fix red-light card for the algorithms
    # that previously handed back the shared warm start.
    if algorithm == "VNS@Valdecy":
        return (
            "Pre-fix: VNS kept selecting merge_routes; that operator produced no candidate, "
            "but unchanged handbacks were counted as accepted, so relocate/swap/2-opt never drove the route set."
        )
    if algorithm == "DR-ALNS":
        return (
            "Pre-fix: DR-ALNS generated feasible accepted path moves, but strict global-best reporting "
            "kept the warm-start solution when no accepted move beat the seed."
        )
    return ""


def _candidate_package_probe(algorithm: str, repo_root: Path) -> _PackageProbe:
    root = repo_root / "Reference Algorithm"
    if algorithm == "PyGAD":
        return _probe_import("pygad", root / "GeneticAlgorithmPython-3.6.0@ahmedfgad")
    if algorithm in {"scikit-opt-GA", "scikit-opt-SA"}:
        return _probe_import("sko", root / "scikit-opt-0.6.5@guofei9987")
    if algorithm == "ALNS@wangqianlongucas":
        return _probe_import("ALNS_main", root / "ALNS@wangqianlongucas" / "code")
    if algorithm == "DR-ALNS":
        probe = _probe_import("ALNS_custom", root / "DR-ALNS@RobbertReijnen" / "code" / "src")
        if not probe.loaded:
            return _PackageProbe(f"thin_alns_semantics_package_unloaded:{probe.status}", False)
        return probe
    if algorithm == "VNS@Valdecy":
        path = root / "VNS@Valdecy" / "Python-MH-Local Search-Variable Neighborhood Search.py"
        return _PackageProbe("script_path_exists_not_imported_thin_shell" if path.exists() else f"missing:{path}", False)
    if algorithm == "NSGA-II@haris989":
        path = root / "NSGA-II@haris989" / "NSGA II.py"
        return _PackageProbe("script_path_exists_not_imported_scalarized_shell" if path.exists() else f"missing:{path}", False)
    return _PackageProbe("not_found_in_scout_board", False)


def _probe_import(module: str, path: Path) -> _PackageProbe:
    if not path.exists():
        return _PackageProbe(f"missing:{path}", False)
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(path))
        imported = importlib.import_module(module)
        return _PackageProbe(f"package_loaded:{module}:{getattr(imported, '__file__', '<namespace>')}", True)
    except Exception as exc:
        prefix = "package_unloaded_thin_shell" if module == "ALNS_main" else "unavailable"
        return _PackageProbe(f"{prefix}:{type(exc).__name__}:{exc}", False)
    finally:
        sys.path[:] = old_path


def _adapter_type(algorithm: str, probe: _PackageProbe) -> str:
    if algorithm == "VNS@Valdecy":
        return "path_vns_two_opt_relocate_swap"
    if algorithm == "PyGAD":
        return "pygad_population_path_crossover_mutation" if probe.loaded else "pygad_path_shell_package_unloaded"
    if algorithm == "scikit-opt-GA":
        return "sko_ga_seeded_path_population" if probe.loaded else "HALT_W1_ADAPTER:sko_ga_unavailable"
    if algorithm == "scikit-opt-SA":
        return "sko_sa_path_metropolis" if probe.loaded else "HALT_W1_ADAPTER:sko_sa_unavailable"
    if algorithm == "NSGA-II@haris989":
        return "nsga_path_pareto_scalarized_after_pareto"
    if algorithm == "ALNS@wangqianlongucas":
        return "wang_alns_path_destroy_repair" if probe.loaded else "package_unloaded_thin_shell_path_destroy_repair"
    if algorithm == "DR-ALNS":
        return "dr_alns_path_destroy_repair" if probe.loaded else "thin_alns_semantics_package_unloaded_path_destroy_repair"
    return "unknown"


def _weighted_choice(rng: random.Random, options: list[str], weights: dict[str, float]) -> str:
    total = sum(weights.get(option, 1.0) for option in options)
    pick = rng.random() * total
    current = 0.0
    for option in options:
        current += weights.get(option, 1.0)
        if current >= pick:
            return option
    return options[-1]


def _candidate_budget_limit(eval_budget: int) -> int:
    target = max(1, int(eval_budget))
    return target + max(1000, target // 10)


def _eval_count(context: EvaluationContext) -> int:
    return int(context.budget.count if context.budget is not None else 0)


def _search_can_continue(context: EvaluationContext, eval_budget: int, started: float, max_runtime_seconds: float) -> bool:
    if _time_expired(started, max_runtime_seconds):
        return False
    if _budget_target_reached(context):
        return False
    return True


def _budget_target_reached(context: EvaluationContext) -> bool:
    return bool(context.budget is not None and context.budget.reached_target)


def _operator_counts_from_trace(trace: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in trace:
        name = str(row.get("operator", "unknown"))
        counts[name] = counts.get(name, 0) + 1
    return counts


def _ga_seed_operator(idx: int) -> str:
    return ["merge_routes", "relocate_customer", "swap_customers", "two_opt_route", "vehicle_type_flip"][idx % 5]


def _time_expired(started: float, max_runtime_seconds: float) -> bool:
    return (time.perf_counter() - started) >= float(max_runtime_seconds)


def _route_customers(route: Route, instance: Instance) -> list[str]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return [node_id for node_id in route.node_sequence if node_lookup.get(node_id) and node_lookup[node_id].node_type.lower() == "c"]


def _route_with_customers(route: Route, customers: list[str]) -> Route:
    return replace(route, node_sequence=[route.home_depot_id, *customers, route.home_depot_id])


def _customer_positions(solution: Solution, instance: Instance) -> list[tuple[int, str]]:
    return [
        (idx, customer_id)
        for idx, route in enumerate(solution.routes)
        for customer_id in _route_customers(route, instance)
    ]


def _append_customer_to_plan(
    customer: Node,
    plans: dict[str, list[list[str]]],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> None:
    best: tuple[float, str, int | None] | None = None
    node_index = instance.node_index
    for depot in _depots_by_customer(customer, instance):
        depot_plans = plans[depot.node_id]
        for idx, customer_ids in enumerate(depot_plans):
            candidate = [*customer_ids, customer.node_id]
            if _route_customer_plan_feasible(depot.node_id, candidate, instance, prices):
                distance = _route_distance(depot.node_id, candidate, instance, node_index=node_index)
                key = (distance, depot.node_id, idx)
                if best is None or key < best:
                    best = key
        if _route_customer_plan_feasible(depot.node_id, [customer.node_id], instance, prices):
            key = (_route_distance(depot.node_id, [customer.node_id], instance, node_index=node_index), depot.node_id, None)
            if best is None or key < best:
                best = key
    if best is None:
        depot = _nearest_depot(customer, instance)
        plans[depot.node_id].append([customer.node_id])
        return
    _, depot_id, route_idx = best
    if route_idx is None:
        plans[depot_id].append([customer.node_id])
    else:
        plans[depot_id][route_idx].append(customer.node_id)


def _all_cv_solution(
    customers: list[Node],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> Solution:
    plans: dict[str, list[list[str]]] = {depot.node_id: [] for depot in _depots(instance)}
    for customer in customers:
        _append_customer_to_plan(customer, plans, instance, prices)
    routes: list[Route] = []
    idx = 1
    for depot_id, depot_plans in sorted(plans.items()):
        for customer_ids in depot_plans:
            routes.append(Route(f"CV{idx}", "cv", depot_id, [depot_id, *customer_ids, depot_id]))
            idx += 1
    return Solution(routes=routes)


def _fleet_limits_from_instance(instance: Instance) -> FleetLimits:
    return FleetLimits(
        cv=int(instance.num_cv) if instance.num_cv is not None else UNBOUNDED_FLEET,
        ev=int(instance.num_ev) if instance.num_ev is not None else UNBOUNDED_FLEET,
        source="instance.num_cv/num_ev hard fleet caps",
    )


def _route_customer_plan_feasible(
    depot_id: str,
    customer_ids: list[str],
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any,
) -> bool:
    node_lookup = {node.node_id: node for node in instance.nodes}
    if sum(float(node_lookup[customer_id].demand) for customer_id in customer_ids) > _price(prices, "Q_capacity") + 1e-9:
        return False
    route = Route("TMP", "cv", depot_id, [depot_id, *customer_ids, depot_id])
    for row in route_node_schedule(route, instance, prices):
        if row.t_start > float(node_lookup[row.node_id].due_time) + 1e-9:
            return False
    return True


def _route_distance(
    depot_id: str,
    customer_ids: list[str],
    instance: Instance,
    *,
    node_index: dict[str, int] | None = None,
) -> float:
    sequence = [depot_id, *customer_ids, depot_id]
    # v2026-06-12: W1 vector compatibility helper avoids rebuilding
    # Instance.node_index for every arc.
    index = instance.node_index if node_index is None else node_index
    return sum(float(instance.distance_matrix[index[a]][index[b]]) for a, b in zip(sequence, sequence[1:]))


def _depots(instance: Instance) -> list[Node]:
    return sorted((node for node in instance.nodes if node.node_type.lower() == "d"), key=lambda node: node.node_id)


def _depots_by_customer(customer: Node, instance: Instance) -> list[Node]:
    index = instance.node_index
    return sorted(
        _depots(instance),
        key=lambda depot: (float(instance.distance_matrix[index[depot.node_id]][index[customer.node_id]]), depot.node_id),
    )


def _nearest_depot(customer: Node, instance: Instance) -> Node:
    return _depots_by_customer(customer, instance)[0]


def _algorithm_seed(algorithm: str, seed: int) -> int:
    return int(seed) + sum(ord(ch) for ch in algorithm)


def _repo_root_from_bundle(bundle_dir: Path) -> Path:
    current = bundle_dir.resolve()
    for parent in [current, *current.parents]:
        if (parent / "Reference Algorithm").exists():
            return parent
    return Path.cwd()


def _importable(name: str, repo_root: Path) -> str:
    if importlib.util.find_spec(name) is not None:
        return "installed"
    local_paths = {
        "pygad": repo_root / "Reference Algorithm" / "GeneticAlgorithmPython-3.6.0@ahmedfgad",
        "sko": repo_root / "Reference Algorithm" / "scikit-opt-0.6.5@guofei9987",
    }
    path = local_paths.get(name)
    if path is None or not path.exists():
        return "missing"
    probe = _probe_import(name, path)
    return probe.status


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
