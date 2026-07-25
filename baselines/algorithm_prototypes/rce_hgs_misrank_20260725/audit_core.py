"""Frozen zero-search audit of HGS proxy ranking against full China81 scoring."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from china81_mechanism_hybrid_20260720.pyvrp_adapter import (
    _project_initial_solution,
    build_pyvrp_problem,
)
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.solve import SolveParams
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import (
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import (
    CrossSiteService,
    Route,
    Solution,
    charging_action_from_dict,
)

ACTION_QUOTA = 24
ACTION_TYPES = (
    "relocate",
    "swap",
    "segment_reversal",
    "tail_exchange",
)
REL_TOL = 1.0e-9


@dataclass(frozen=True)
class AuditTask:
    """One frozen instance/seed/witness audit unit."""

    instance_id: str
    seed: int
    witness_path: str
    raw_run_path: str

    @property
    def task_id(self) -> str:
        return f"{self.instance_id}__seed{self.seed}"


@dataclass(frozen=True)
class CandidateDescriptor:
    """A deterministic, non-iterative customer-order perturbation."""

    action_type: str
    source_route: int
    target_route: int
    source_pos: int
    target_pos: int
    aux: int = 0

    def stable_key(self, instance_id: str, seed: int) -> str:
        payload = (
            f"{instance_id}|{seed}|{self.action_type}|"
            f"{self.source_route}|{self.target_route}|"
            f"{self.source_pos}|{self.target_pos}|{self.aux}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def solution_from_mapping(row: dict[str, Any]) -> Solution:
    """Load one complete protected witness."""

    return Solution(
        routes=[
            Route(
                vehicle_id=str(route["vehicle_id"]),
                vehicle_type=str(route["vehicle_type"]),
                home_depot_id=str(route["home_depot_id"]),
                node_sequence=[
                    str(node_id)
                    for node_id in route["node_sequence"]
                ],
            )
            for route in row["routes"]
        ],
        charging_actions=[
            charging_action_from_dict(action)
            for action in row.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(service["customer_id"]),
                served_by_depot_id=str(service["served_by_depot_id"]),
            )
            for service in row.get("cross_site_services", [])
        ],
    )


def load_frozen_hgs_m_witness(task: AuditTask) -> Solution:
    """Load exactly the protected HGS-M witness."""

    payload = json.loads(
        Path(task.witness_path).read_text(encoding="utf-8")
    )
    if "HGS-M" not in payload:
        raise ValueError(f"{task.task_id}: witness has no HGS-M arm")
    return solution_from_mapping(payload["HGS-M"])


def load_recorded_hgs_m_cost(task: AuditTask) -> float:
    """Read the one protected task row and return its HGS-M cost."""

    with Path(task.raw_run_path).open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError(
            f"{task.task_id}: expected one protected raw row, got {len(rows)}"
        )
    row = rows[0]
    if row["instance_id"] != task.instance_id:
        raise ValueError(f"{task.task_id}: protected row instance mismatch")
    if int(row["seed"]) != task.seed:
        raise ValueError(f"{task.task_id}: protected row seed mismatch")
    if row.get("status") != "PASS":
        raise ValueError(f"{task.task_id}: protected row is not PASS")
    return float(row["HGS-M_cost"])


def _customers(route: Route) -> list[str]:
    return [
        node_id
        for node_id in route.node_sequence
        if node_id != route.home_depot_id
    ]


def _descriptor_space(solution: Solution) -> dict[str, list[CandidateDescriptor]]:
    routes = [_customers(route) for route in solution.routes]
    descriptors = {action: [] for action in ACTION_TYPES}

    for source_idx, source in enumerate(routes):
        for target_idx, target in enumerate(routes):
            if source_idx == target_idx:
                continue
            if len(source) > 1:
                for source_pos in range(len(source)):
                    for target_pos in range(len(target) + 1):
                        descriptors["relocate"].append(
                            CandidateDescriptor(
                                "relocate",
                                source_idx,
                                target_idx,
                                source_pos,
                                target_pos,
                            )
                        )
            for source_pos in range(len(source)):
                for target_pos in range(len(target)):
                    descriptors["swap"].append(
                        CandidateDescriptor(
                            "swap",
                            source_idx,
                            target_idx,
                            source_pos,
                            target_pos,
                        )
                    )
            if len(source) > 1 and len(target) > 1:
                for source_pos in range(1, len(source)):
                    for target_pos in range(1, len(target)):
                        descriptors["tail_exchange"].append(
                            CandidateDescriptor(
                                "tail_exchange",
                                source_idx,
                                target_idx,
                                source_pos,
                                target_pos,
                            )
                        )

    for route_idx, customers in enumerate(routes):
        for start in range(len(customers)):
            for end in range(start + 2, len(customers) + 1):
                descriptors["segment_reversal"].append(
                    CandidateDescriptor(
                        "segment_reversal",
                        route_idx,
                        route_idx,
                        start,
                        end,
                    )
                )
    return descriptors


def _apply_descriptor(
    solution: Solution,
    descriptor: CandidateDescriptor,
) -> Solution:
    customer_routes = [_customers(route) for route in solution.routes]
    source = customer_routes[descriptor.source_route]
    target = customer_routes[descriptor.target_route]

    if descriptor.action_type == "relocate":
        customer = source.pop(descriptor.source_pos)
        target.insert(descriptor.target_pos, customer)
    elif descriptor.action_type == "swap":
        source[descriptor.source_pos], target[descriptor.target_pos] = (
            target[descriptor.target_pos],
            source[descriptor.source_pos],
        )
    elif descriptor.action_type == "segment_reversal":
        start = descriptor.source_pos
        end = descriptor.target_pos
        source[start:end] = reversed(source[start:end])
    elif descriptor.action_type == "tail_exchange":
        left_tail = source[descriptor.source_pos :]
        right_tail = target[descriptor.target_pos :]
        source[descriptor.source_pos :] = right_tail
        target[descriptor.target_pos :] = left_tail
    else:
        raise ValueError(f"unknown action {descriptor.action_type!r}")

    routes = []
    for route, customers in zip(
        solution.routes,
        customer_routes,
        strict=True,
    ):
        if not customers:
            continue
        routes.append(
            Route(
                vehicle_id=route.vehicle_id,
                vehicle_type=route.vehicle_type,
                home_depot_id=route.home_depot_id,
                node_sequence=[
                    route.home_depot_id,
                    *customers,
                    route.home_depot_id,
                ],
            )
        )
    return Solution(routes=routes)


def solution_signature(solution: Solution) -> str:
    """Return a stable signature that preserves depot and route order."""

    payload = [
        {
            "home_depot_id": route.home_depot_id,
            "customers": _customers(route),
        }
        for route in solution.routes
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generate_candidates(
    solution: Solution,
    instance_id: str,
    seed: int,
) -> list[tuple[CandidateDescriptor, Solution, str]]:
    """Generate the frozen 24-per-action audit panel."""

    base_signature = solution_signature(solution)
    selected: list[tuple[CandidateDescriptor, Solution, str]] = []
    seen = {base_signature}
    for action_type in ACTION_TYPES:
        descriptors = sorted(
            _descriptor_space(solution)[action_type],
            key=lambda item: item.stable_key(instance_id, seed),
        )
        action_count = 0
        for descriptor in descriptors:
            candidate = _apply_descriptor(solution, descriptor)
            signature = solution_signature(candidate)
            if signature in seen:
                continue
            seen.add(signature)
            selected.append((descriptor, candidate, signature))
            action_count += 1
            if action_count == ACTION_QUOTA:
                break
        if action_count != ACTION_QUOTA:
            raise ValueError(
                f"{instance_id} seed {seed}: {action_type} generated "
                f"{action_count}/{ACTION_QUOTA} unique candidates"
            )
    if len(selected) != ACTION_QUOTA * len(ACTION_TYPES):
        raise RuntimeError("candidate ledger did not close at 96")
    return selected


def _proxy_scorer(bundle: Any) -> tuple[Any, Any, Any]:
    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode="mechanism_ev",
    )
    data = problem.model.data()
    params = SolveParams()
    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    return problem, data, penalty_manager.cost_evaluator()


def _proxy_score(
    solution: Solution,
    problem: Any,
    data: Any,
    cost_evaluator: Any,
) -> tuple[int, bool]:
    native = _project_initial_solution(solution, data, problem)
    return (
        int(cost_evaluator.penalised_cost(native)),
        bool(native.is_feasible()),
    )


def _has_strict_inversion(rows: Iterable[dict[str, Any]]) -> bool:
    feasible = [row for row in rows if row["exact_status"] == "PASS"]
    by_proxy = sorted(
        feasible,
        key=lambda row: (row["proxy_score"], row["candidate_signature"]),
    )
    best_exact_so_far = float("inf")
    for row in reversed(by_proxy):
        objective = float(row["exact_objective"])
        if objective > best_exact_so_far + REL_TOL:
            return True
        best_exact_so_far = min(best_exact_so_far, objective)
    return False


def run_audit_task(
    repo_root: str,
    task: AuditTask,
    *,
    exact_candidates: bool,
) -> dict[str, Any]:
    """Run one isolated audit unit without accepting any candidate."""

    started = perf_counter()
    bundle = load_china81_bundle(repo_root, task.instance_id)
    witness = load_frozen_hgs_m_witness(task)
    recorded_cost = load_recorded_hgs_m_cost(task)
    baseline_cost, _, baseline_violations = exact_china81_score(
        witness,
        bundle,
    )
    baseline_closed = (
        not baseline_violations
        and abs(baseline_cost - recorded_cost)
        <= REL_TOL * max(1.0, abs(recorded_cost))
    )
    if not baseline_closed:
        raise ValueError(
            f"{task.task_id}: protected HGS-M witness replay failed: "
            f"recorded={recorded_cost}, exact={baseline_cost}, "
            f"violations={len(baseline_violations)}"
        )

    problem, data, cost_evaluator = _proxy_scorer(bundle)
    candidates = generate_candidates(
        witness,
        task.instance_id,
        task.seed,
    )
    rows: list[dict[str, Any]] = []
    for descriptor, candidate, signature in candidates:
        proxy_score, proxy_feasible = _proxy_score(
            candidate,
            problem,
            data,
            cost_evaluator,
        )
        row: dict[str, Any] = {
            "task_id": task.task_id,
            "instance_id": task.instance_id,
            "seed": task.seed,
            "candidate_signature": signature,
            **asdict(descriptor),
            "proxy_score": proxy_score,
            "proxy_feasible": proxy_feasible,
            "exact_status": "NOT_RUN_ENGINEERING_ONLY",
            "exact_objective": None,
            "exact_improvement": None,
            "exact_violation_count": None,
            "exact_completion_seconds": None,
            "error": "",
        }
        if exact_candidates:
            exact_started = perf_counter()
            try:
                completion = complete_china81_route_skeleton(
                    candidate,
                    bundle,
                )
                exact_obj, _, violations = exact_china81_score(
                    completion.solution,
                    bundle,
                )
                if violations:
                    raise RuntimeError(
                        "completed candidate failed independent check"
                    )
                if (
                    abs(exact_obj - completion.objective)
                    > REL_TOL * max(1.0, abs(exact_obj))
                ):
                    raise RuntimeError(
                        "completion and independent score differ"
                    )
                row.update(
                    {
                        "exact_status": "PASS",
                        "exact_objective": float(exact_obj),
                        "exact_improvement": float(
                            baseline_cost - exact_obj
                        ),
                        "exact_violation_count": 0,
                    }
                )
            except (IndexError, KeyError, RuntimeError, TypeError, ValueError) as exc:
                row.update(
                    {
                        "exact_status": "INFEASIBLE_OR_ERROR",
                        "error": str(exc),
                    }
                )
            finally:
                row["exact_completion_seconds"] = (
                    perf_counter() - exact_started
                )
        rows.append(row)

    summary: dict[str, Any] = {
        "task_id": task.task_id,
        "instance_id": task.instance_id,
        "seed": task.seed,
        "recorded_baseline_cost": float(recorded_cost),
        "replayed_baseline_cost": float(baseline_cost),
        "baseline_violation_count": len(baseline_violations),
        "baseline_replay_closed": baseline_closed,
        "candidate_count": len(rows),
        "action_counts": {
            action_type: sum(
                row["action_type"] == action_type
                for row in rows
            )
            for action_type in ACTION_TYPES
        },
        "exact_candidates_enabled": bool(exact_candidates),
        "elapsed_seconds": perf_counter() - started,
    }
    if exact_candidates:
        exact_feasible = [
            row for row in rows if row["exact_status"] == "PASS"
        ]
        proxy_ranked = sorted(
            rows,
            key=lambda row: (
                int(row["proxy_score"]),
                row["candidate_signature"],
            ),
        )
        improving = [
            row
            for row in exact_feasible
            if float(row["exact_improvement"]) > REL_TOL
        ]
        best_improving = (
            min(
                improving,
                key=lambda row: (
                    float(row["exact_objective"]),
                    row["candidate_signature"],
                ),
            )
            if improving
            else None
        )
        proxy_rank = {
            row["candidate_signature"]: index + 1
            for index, row in enumerate(proxy_ranked)
        }
        summary.update(
            {
                "exact_pass_count": len(exact_feasible),
                "exact_failure_count": len(rows) - len(exact_feasible),
                "strict_proxy_exact_inversion": _has_strict_inversion(rows),
                "strict_improving_candidate_count": len(improving),
                "has_strict_improvement": bool(improving),
                "best_improving_candidate_signature": (
                    None
                    if best_improving is None
                    else best_improving["candidate_signature"]
                ),
                "best_improving_objective": (
                    None
                    if best_improving is None
                    else float(best_improving["exact_objective"])
                ),
                "best_improving_proxy_rank": (
                    None
                    if best_improving is None
                    else int(
                        proxy_rank[
                            best_improving["candidate_signature"]
                        ]
                    )
                ),
                "best_improvement_missed_by_proxy_top8": bool(
                    best_improving is not None
                    and proxy_rank[
                        best_improving["candidate_signature"]
                    ]
                    > 8
                ),
            }
        )
    return {"summary": summary, "rows": rows}
