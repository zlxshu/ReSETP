"""One independent PyVRP 0.13.4 ILS G0 task."""

from __future__ import annotations

import os
import platform
import resource
import signal
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (REPO / "solver/src", PROTOTYPE, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pyvrp
from common import (
    REPO,
    adjacency_signature,
    load_complete_solution,
    load_route_skeleton,
    native_solution_signature,
    read_json,
    route_signatures,
    solution_payload,
)
from pyvrp import (
    IteratedLocalSearch,
    PenaltyManager,
    RandomNumberGenerator,
)
from pyvrp.search import (
    LocalSearch,
    PerturbationManager,
    compute_neighbours,
)
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxIterations
from pyvrp_adapter import (
    _project_initial_solution,
    _translate_solution,
    build_pyvrp_problem,
)
from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import (
    complete_china81_route_skeleton,
    exact_china81_score,
)

EXPECTED_PYVRP = "0.13.4"


@dataclass(frozen=True)
class RecordedCandidate:
    solution: Any
    signature: tuple[Any, ...]
    proxy_cost: int
    first_seen: int


class RecordingSearch:
    """Observe returned ILS candidates without changing its random stream."""

    def __init__(self, search: LocalSearch):
        self._search = search
        self._calls = 0
        self._records: dict[tuple[Any, ...], RecordedCandidate] = {}

    def __call__(
        self,
        solution: Any,
        cost_evaluator: Any,
        exhaustive: bool = False,
    ) -> Any:
        candidate = self._search(
            solution,
            cost_evaluator,
            exhaustive=exhaustive,
        )
        self._calls += 1
        if candidate.is_feasible():
            signature = native_solution_signature(candidate)
            proxy_cost = int(cost_evaluator.cost(candidate))
            previous = self._records.get(signature)
            if previous is None or proxy_cost < previous.proxy_cost:
                self._records[signature] = RecordedCandidate(
                    solution=candidate,
                    signature=signature,
                    proxy_cost=proxy_cost,
                    first_seen=(
                        self._calls
                        if previous is None
                        else previous.first_seen
                    ),
                )
        return candidate

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def records(self) -> tuple[RecordedCandidate, ...]:
        return tuple(self._records.values())


def _rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() == "Darwin":
        return value / (1024.0 * 1024.0)
    return value / 1024.0


def _load_start(
    instance_id: str,
    start_kind: str,
    instance_manifest: Mapping[str, Any],
) -> Any:
    if start_kind == "cold":
        path = REPO / str(instance_manifest["common_initial_path"])
        return load_route_skeleton(read_json(path))
    if start_kind == "warm":
        path = REPO / str(instance_manifest["warm_start_witness_path"])
        payload = read_json(path)
        return load_route_skeleton(
            payload[str(instance_manifest["warm_start_label"])]
        )
    raise ValueError(f"unsupported start_kind {start_kind!r}")


def _build_official_search(
    data: Any,
    rng: Any,
    params: SolveParams,
) -> LocalSearch:
    neighbours = compute_neighbours(data, params.neighbourhood)
    search = LocalSearch(
        data,
        rng,
        neighbours,
        PerturbationManager(params.perturbation),
    )
    for operator in params.node_ops:
        if operator.supports(data):
            search.add_node_operator(operator(data))
    for operator in params.route_ops:
        if operator.supports(data):
            search.add_route_operator(operator(data))
    return search


def resource_probe(task: Mapping[str, Any]) -> dict[str, Any]:
    if version("pyvrp") != EXPECTED_PYVRP:
        raise RuntimeError(
            f"expected PyVRP {EXPECTED_PYVRP}, found {version('pyvrp')}"
        )
    instance_id = str(task["instance_id"])
    start_kind = str(task["start_kind"])
    instance_manifest = task["instance_manifest"]
    bundle = load_china81_bundle(REPO, instance_id)
    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode="mechanism_ev",
    )
    skeleton = _load_start(instance_id, start_kind, instance_manifest)
    native = _project_initial_solution(
        skeleton,
        problem.model.data(),
        problem,
    )
    time.sleep(float(task.get("probe_hold_seconds", 0.0)))
    return {
        "instance_id": instance_id,
        "start_kind": start_kind,
        "pyvrp_version": version("pyvrp"),
        "engine_family": (
            "HGS" if hasattr(pyvrp, "GeneticAlgorithm") else "ILS"
        ),
        "num_clients": int(problem.model.data().num_clients),
        "initial_complete": bool(native.is_complete()),
        "initial_proxy_feasible": bool(native.is_feasible()),
        "peak_rss_mib": _rss_mib(),
        "pid": os.getpid(),
    }


def _timeout_handler(_signum: int, _frame: Any) -> None:
    raise TimeoutError("G0 task exceeded the 60 second safety limit")


def run_task(task: Mapping[str, Any]) -> dict[str, Any]:
    installed = version("pyvrp")
    if installed != EXPECTED_PYVRP:
        raise RuntimeError(
            f"expected PyVRP {EXPECTED_PYVRP}, found {installed}"
        )
    if hasattr(pyvrp, "GeneticAlgorithm"):
        raise RuntimeError("G0 B arm must be ILS, not HGS")

    instance_id = str(task["instance_id"])
    start_kind = str(task["start_kind"])
    instance_manifest = task["instance_manifest"]
    seed = int(task["seed"])
    iterations = int(task["iterations"])
    candidate_limit = int(task["candidate_limit"])
    safety_seconds = float(task["safety_seconds"])

    previous_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, safety_seconds)
    started = time.perf_counter()
    try:
        bundle = load_china81_bundle(REPO, instance_id)
        problem = build_pyvrp_problem(
            bundle,
            route_proxy_mode="mechanism_ev",
        )
        data = problem.model.data()
        start_skeleton = _load_start(
            instance_id,
            start_kind,
            instance_manifest,
        )
        native_initial = _project_initial_solution(
            start_skeleton,
            data,
            problem,
        )
        initial_signature = native_solution_signature(native_initial)
        if start_kind == "warm":
            warm_payload = read_json(
                REPO / str(instance_manifest["warm_start_witness_path"])
            )[str(instance_manifest["warm_start_label"])]
            start_complete_solution = load_complete_solution(warm_payload)
            start_exact_objective, _, start_violations = (
                exact_china81_score(start_complete_solution, bundle)
            )
            start_independent_violations = check_solution(
                start_complete_solution,
                bundle.instance,
                bundle.prices,
            )
            if start_violations or start_independent_violations:
                raise RuntimeError(
                    "registered HGS warm start is not independently feasible"
                )
            registered_cost = float(instance_manifest["warm_start_cost"])
            if abs(start_exact_objective - registered_cost) > 1.0e-6:
                raise RuntimeError(
                    "registered HGS warm-start cost does not close: "
                    f"exact={start_exact_objective}, "
                    f"registered={registered_cost}"
                )
        else:
            start_completion = complete_china81_route_skeleton(
                start_skeleton,
                bundle,
            )
            start_exact_objective, _, start_violations = (
                exact_china81_score(start_completion.solution, bundle)
            )
            start_independent_violations = check_solution(
                start_completion.solution,
                bundle.instance,
                bundle.prices,
            )
            if start_violations or start_independent_violations:
                raise RuntimeError(
                    "registered common cold start is not independently feasible"
                )

        params = SolveParams()
        rng = RandomNumberGenerator(seed=seed)
        official_search = _build_official_search(data, rng, params)
        recording_search = RecordingSearch(official_search)
        penalties = PenaltyManager.init_from(data, params.penalty)
        runner = IteratedLocalSearch(
            data,
            penalties,
            rng,
            recording_search,
            native_initial,
            params.ils,
        )
        result = runner.run(
            MaxIterations(iterations),
            collect_stats=False,
            display=False,
            display_interval=params.display_interval,
        )

        final_signature = native_solution_signature(result.best)
        current_evaluator = penalties.cost_evaluator()
        records = {
            record.signature: record
            for record in recording_search.records
            if record.signature != initial_signature
        }
        if final_signature != initial_signature:
            records[final_signature] = RecordedCandidate(
                solution=result.best,
                signature=final_signature,
                proxy_cost=int(current_evaluator.cost(result.best)),
                first_seen=records.get(
                    final_signature,
                    RecordedCandidate(
                        result.best,
                        final_signature,
                        int(current_evaluator.cost(result.best)),
                        recording_search.calls + 1,
                    ),
                ).first_seen,
            )

        ordered: list[RecordedCandidate] = []
        final_record = records.get(final_signature)
        if final_record is not None:
            ordered.append(final_record)
        ordered.extend(
            sorted(
                (
                    record
                    for signature, record in records.items()
                    if signature != final_signature
                ),
                key=lambda item: (
                    item.proxy_cost,
                    item.first_seen,
                    repr(item.signature),
                ),
            )
        )
        selected = ordered[:candidate_limit]

        reference_pool = {
            tuple(str(item) for item in signature)
            for signature in instance_manifest[
                "v7_reference_route_signatures"
            ]
        }
        start_edges = adjacency_signature(start_skeleton.routes)
        attempts: list[dict[str, Any]] = []
        exact_candidates: list[tuple[float, Any, dict[str, Any]]] = []
        for rank, record in enumerate(selected, start=1):
            attempt: dict[str, Any] = {
                "rank": rank,
                "proxy_cost": record.proxy_cost,
                "first_seen": record.first_seen,
                "native_signature": repr(record.signature),
            }
            try:
                skeleton = _translate_solution(
                    record.solution,
                    problem,
                )
                completion = complete_china81_route_skeleton(
                    skeleton,
                    bundle,
                )
                objective, _breakdown, violations = exact_china81_score(
                    completion.solution,
                    bundle,
                )
                independent_violations = check_solution(
                    completion.solution,
                    bundle.instance,
                    bundle.prices,
                )
                if violations or independent_violations:
                    raise RuntimeError(
                        "candidate has full-model violations: "
                        f"exact={len(violations)}, "
                        f"independent={len(independent_violations)}"
                    )
                if abs(objective - completion.objective) > 1.0e-6:
                    raise RuntimeError(
                        "completion and exact objectives do not close"
                    )
                signatures = route_signatures(
                    completion.solution.routes,
                    minimum_customers=2,
                )
                new_routes = sorted(signatures - reference_pool)
                edges = adjacency_signature(completion.solution.routes)
                attempt.update(
                    {
                        "status": "EXACT_FEASIBLE",
                        "exact_objective": float(objective),
                        "route_signature_count": len(signatures),
                        "new_route_signature_count": len(new_routes),
                        "new_route_signatures": [
                            list(item) for item in new_routes
                        ],
                        "adjacency_changed_from_start": edges != start_edges,
                        "added_customer_edges": [
                            list(item) for item in sorted(edges - start_edges)
                        ],
                        "removed_customer_edges": [
                            list(item) for item in sorted(start_edges - edges)
                        ],
                    }
                )
                exact_candidates.append(
                    (float(objective), completion.solution, attempt)
                )
            except (
                IndexError,
                KeyError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                attempt.update(
                    {
                        "status": "INFEASIBLE_OR_ERROR",
                        "failure": str(exc),
                    }
                )
            attempts.append(attempt)

        best_payload = None
        best_attempt = None
        if exact_candidates:
            best_objective, best_solution, best_attempt = min(
                exact_candidates,
                key=lambda item: (
                    item[0],
                    int(item[2]["rank"]),
                ),
            )
            best_payload = solution_payload(best_solution)
        else:
            best_objective = None

        return {
            "schema": "resetp.hgs-ils-xd.g0-task.v1",
            "instance_id": instance_id,
            "start_kind": start_kind,
            "seed": seed,
            "pyvrp_version": installed,
            "engine_family": "ILS",
            "requested_iterations": iterations,
            "iterations_completed": int(result.num_iterations),
            "search_calls": recording_search.calls,
            "distinct_proxy_feasible_generated_candidates": len(records),
            "selected_complete_evaluation_attempts": len(selected),
            "exact_feasible_generated_candidates": len(exact_candidates),
            "official_final_differs_from_start": (
                final_signature != initial_signature
            ),
            "has_exact_feasible_output": bool(exact_candidates),
            "start_exact_objective": float(start_exact_objective),
            "has_route_outside_v7_reference_pool": any(
                int(attempt.get("new_route_signature_count", 0)) > 0
                for attempt in attempts
            ),
            "has_exact_feasible_adjacency_change": any(
                bool(attempt.get("adjacency_changed_from_start", False))
                for attempt in attempts
            ),
            "best_exact_objective": (
                None if best_objective is None else float(best_objective)
            ),
            "strictly_improves_start": (
                best_objective is not None
                and best_objective < start_exact_objective - 1.0e-9
            ),
            "improvement_over_start": (
                None
                if best_objective is None
                else float(start_exact_objective - best_objective)
            ),
            "best_attempt_rank": (
                None if best_attempt is None else int(best_attempt["rank"])
            ),
            "attempts": attempts,
            "best_witness": best_payload,
            "runtime_seconds": time.perf_counter() - started,
            "peak_rss_mib": _rss_mib(),
            "rng_state": [int(value) for value in rng.state()],
        }
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)
