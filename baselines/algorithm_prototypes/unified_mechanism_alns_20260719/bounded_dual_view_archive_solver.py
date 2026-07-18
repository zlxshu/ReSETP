"""Protected route-first ALNS with a bounded post-search mechanism archive.

The ALNS trajectory is identical whether the archive is enabled or disabled.
Historical best solutions are copied only for post-search inspection.  At
most twelve non-final route skeletons receive a cheap, fixed-route mechanism
completion and at most two of them join the ordinary final skeleton for the
common terminal completion.  The ordinary final branch is always present.

This is a stage-one development candidate governed by
``docs/handoff/bounded_dual_view_archive_contract_20260719.md``.  It does not
modify the formal solver entry point and it never starts a second route search.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any

from fast_mechanism_completion import apply_fast_route_local_completion
from initial_pool import solution_signature_hash
from prototype import ArmResult, independent_cost
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    run_winner_kernel,
)
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)
from terminal_completion import apply_terminal_completion


TOL = 1.0e-9
ARCHIVE_CAPACITY = 3
PRESCORE_CAPACITY = 12


@dataclass(frozen=True)
class BoundedDualViewArchiveConfig:
    """Controls that do not alter the frozen archive capacities or ranking."""

    total_eval_budget: int = 100
    enable_archive: bool = True
    runtime_cap_seconds: float = 3600.0


def run_bounded_dual_view_archive_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    config: BoundedDualViewArchiveConfig | None = None,
    prices: Any = DEFAULT_PRICES,
    initial_solution: Solution | None = None,
) -> ArmResult:
    """Run one route search and a bounded, non-feedback terminal archive."""

    cfg = config or BoundedDualViewArchiveConfig()
    budget = max(0, int(cfg.total_eval_budget))
    started = time.perf_counter()
    bundle = load_search_bundle(bundle_dir)
    raw = run_winner_kernel(
        bundle_dir,
        config=WinnerKernelConfig(
            seed=int(seed),
            eval_budget=budget,
            max_runtime_seconds=float(cfg.runtime_cap_seconds),
            require_charging_signal=False,
            capture_best_solutions=True,
        ),
        initial_solution=initial_solution,
        prices=prices,
    )
    _assert_main_search_ledger(raw, budget)

    raw_solution = raw["best_solution"]
    raw_cost = independent_cost(bundle_dir, raw_solution, prices)
    _require_finite(
        "raw_search_cost",
        float(raw["best_cost"]),
        float(raw_cost),
    )
    if abs(float(raw_cost) - float(raw["best_cost"])) > 1.0e-7:
        raise RuntimeError(
            "bounded archive raw objective replay mismatch: "
            f"{raw['best_cost']} != {raw_cost}"
        )
    if check_solution(raw_solution, bundle.instance, prices):
        raise RuntimeError("bounded archive raw search result is infeasible")

    history, scalar_history = _unique_route_skeleton_history(
        list(raw.get("history", [])),
        bundle.instance,
    )
    final_item = _archive_item(
        solution=raw_solution,
        raw_cost=float(raw_cost),
        history_index=len(raw.get("history", [])),
        eval_count=budget,
        operator="winner_kernel_final",
        instance=bundle.instance,
        is_main_search_final=True,
    )
    raw_activity = _raw_activity(raw, scalar_history, final_item)

    # Match the existing v7 zero-budget contract: no mechanism completion is
    # started.  Only the independent result replay above is reported.
    if budget == 0:
        return ArmResult(
            algorithm=_algorithm_label(cfg.enable_archive),
            best_solution=raw_solution,
            best_cost=float(raw_cost),
            evaluations=0,
            elapsed_seconds=time.perf_counter() - started,
            route_count=len(raw_solution.routes),
            feasible=True,
            mechanism_activity={
                **raw_activity,
                "archive_enabled": bool(cfg.enable_archive),
                "archive_feedback_into_search": False,
                "second_route_search_started": False,
                "candidate_budget_equalized": True,
                "post_search_reference_work_equalized": False,
                "zero_budget_no_mechanism_completion": True,
                "prescore_capacity": PRESCORE_CAPACITY,
                "archive_capacity": ARCHIVE_CAPACITY,
                "unique_nonfinal_history_size": max(
                    0,
                    len(
                        {
                            item["skeleton_signature"]
                            for item in history
                            if item["skeleton_signature"]
                            != final_item["skeleton_signature"]
                        }
                    ),
                ),
                "prescore_candidate_count": 0,
                "prescore_reference_replays": 0,
                "archive_entry_count": 0,
                "archive_completion_call_count": 0,
                "archive_completion_reference_replays": 0,
                "post_search_full_solution_replays": 1,
                "raw_search_independent_replays": 1,
                "selected_final_independent_replays": 0,
                "independent_final_replays": 1,
                "mechanism_feasibility_checks": 0,
                "archive_contributed": False,
                "ordinary_final_forced": False,
                "ordinary_final_completed_cost": float(raw_cost),
                "selected_completed_cost": float(raw_cost),
                "selected_is_main_search_final": True,
                "selected_raw_signature": final_item["raw_signature"],
                "selected_exact_signature": final_item["exact_signature"],
                "selected_skeleton_signature": final_item[
                    "skeleton_signature"
                ],
                "main_search_final_solution_snapshot": asdict(raw_solution),
                "prescore_rows": [],
                "archive_entries": [],
            },
        )

    nonfinal = [
        item
        for item in history
        if item["skeleton_signature"] != final_item["skeleton_signature"]
    ]
    sampled = (
        _evenly_spaced(nonfinal, PRESCORE_CAPACITY)
        if cfg.enable_archive
        else []
    )
    prescore_rows: list[dict[str, Any]] = []
    for item in sampled:
        fast = apply_fast_route_local_completion(
            item["solution"],
            bundle,
            prices=prices,
        )
        fast_cost = independent_cost(bundle_dir, fast.solution, prices)
        expected = (
            float(item["raw_cost"])
            + float(fast.activity["projected_objective_delta"])
        )
        _require_finite(
            "fast_prescore",
            float(item["raw_cost"]),
            float(fast.activity["projected_objective_delta"]),
            float(fast_cost),
            float(expected),
        )
        closure_error = abs(float(fast_cost) - expected)
        if closure_error > 1.0e-7:
            raise RuntimeError(
                "fast mechanism prescore did not close against an independent "
                f"replay: {fast_cost} != {expected}"
            )
        prescore_rows.append(
            {
                **{
                    key: value
                    for key, value in item.items()
                    if key != "solution"
                },
                "fast_completed_cost": float(fast_cost),
                "fast_completed_signature": solution_signature_hash(
                    fast.solution
                ),
                "fast_completed_exact_signature": _exact_solution_hash(
                    fast.solution
                ),
                "fast_changed": bool(fast.changed),
                "fast_cost_closure_error": float(closure_error),
                "fast_activity": fast.activity,
                "raw_solution_snapshot": asdict(item["solution"]),
                "fast_completed_solution_snapshot": asdict(
                    fast.solution
                ),
            }
        )

    ranked = sorted(
        prescore_rows,
        key=lambda item: (
            float(item["fast_completed_cost"]),
            float(item["raw_cost"]),
            -int(item["eval"]),
            str(item["skeleton_signature"]),
            str(item["exact_signature"]),
        ),
    )
    selected_skeletons = {
        str(final_item["skeleton_signature"]),
    }
    selected_nonfinal: list[dict[str, Any]] = []
    item_by_exact = {
        str(item["exact_signature"]): item for item in sampled
    }
    if cfg.enable_archive:
        for row in ranked:
            skeleton = str(row["skeleton_signature"])
            if skeleton in selected_skeletons:
                continue
            selected_skeletons.add(skeleton)
            selected_nonfinal.append(
                item_by_exact[str(row["exact_signature"])]
            )
            if len(selected_nonfinal) >= ARCHIVE_CAPACITY - 1:
                break

    terminal_sources = [final_item, *selected_nonfinal]
    if len(terminal_sources) > ARCHIVE_CAPACITY:
        raise RuntimeError("bounded archive exceeded its frozen capacity")
    if len(
        {str(item["skeleton_signature"]) for item in terminal_sources}
    ) != len(terminal_sources):
        raise RuntimeError("bounded archive contains a duplicate route skeleton")

    completed: list[dict[str, Any]] = []
    for item in terminal_sources:
        completion = apply_terminal_completion(
            bundle_dir,
            item["solution"],
            prices=prices,
        )
        if not completion.feasible:
            raise RuntimeError(
                "bounded archive terminal completion returned infeasible"
            )
        _require_finite(
            "terminal_completion",
            float(completion.source_cost),
            float(completion.cost),
        )
        completed.append(
            {
                **{
                    key: value
                    for key, value in item.items()
                    if key != "solution"
                },
                "completed_cost": float(completion.cost),
                "completed_signature": solution_signature_hash(
                    completion.solution
                ),
                "completed_exact_signature": _exact_solution_hash(
                    completion.solution
                ),
                "selected_branch": str(completion.selected_branch),
                "activity": completion.activity,
                "raw_solution_snapshot": asdict(item["solution"]),
                "completed_solution_snapshot": asdict(completion.solution),
                "_solution": completion.solution,
            }
        )

    ordinary_rows = [
        item for item in completed if item["is_main_search_final"]
    ]
    if len(ordinary_rows) != 1:
        raise RuntimeError(
            "bounded archive must contain exactly one ordinary final branch"
        )
    ordinary = ordinary_rows[0]
    if (
        str(ordinary["exact_signature"])
        != str(final_item["exact_signature"])
    ):
        raise RuntimeError(
            "bounded archive ordinary branch is not the raw search final"
        )
    selected = min(
        completed,
        key=lambda item: (
            float(item["completed_cost"]),
            0 if item["is_main_search_final"] else 1,
            -int(item["eval"]),
            str(item["skeleton_signature"]),
            str(item["completed_exact_signature"]),
        ),
    )
    if (
        float(selected["completed_cost"])
        > float(ordinary["completed_cost"]) + TOL
    ):
        raise RuntimeError("bounded archive violated the ordinary-final envelope")

    final_solution = selected["_solution"]
    final_cost = independent_cost(bundle_dir, final_solution, prices)
    _require_finite(
        "selected_final",
        float(ordinary["completed_cost"]),
        float(selected["completed_cost"]),
        float(final_cost),
    )
    if abs(float(final_cost) - float(selected["completed_cost"])) > 1.0e-7:
        raise RuntimeError(
            "bounded archive selected objective replay mismatch: "
            f"{selected['completed_cost']} != {final_cost}"
        )
    violations = check_solution(final_solution, bundle.instance, prices)
    if violations:
        raise RuntimeError(
            f"bounded archive final solution is infeasible: {violations[:8]}"
        )

    completion_reference_replays = sum(
        int(item["activity"].get("full_solution_replays", 0))
        for item in completed
    )
    route_local_exact = sum(
        int(item["activity"].get("route_local_exact_evaluations", 0))
        for item in completed
    )
    route_proxy = sum(
        int(item["activity"].get("route_proxy_evaluations", 0))
        for item in completed
    ) + sum(
        int(item["fast_activity"].get("route_proxy_evaluations", 0))
        for item in prescore_rows
    )
    route_schedule = sum(
        int(
            item["activity"].get(
                "route_local_schedule_evaluations",
                0,
            )
        )
        for item in completed
    ) + sum(
        int(
            item["fast_activity"].get(
                "route_local_schedule_evaluations",
                0,
            )
        )
        for item in prescore_rows
    )
    feasibility_checks = sum(
        int(item["activity"].get("full_feasibility_checks", 0))
        for item in completed
    ) + sum(
        int(item["fast_activity"].get("full_feasibility_checks", 0))
        for item in prescore_rows
    )
    archive_contributed = bool(
        not selected["is_main_search_final"]
        and float(selected["completed_cost"])
        < float(ordinary["completed_cost"]) - TOL
    )
    serializable_entries = [
        {key: value for key, value in item.items() if key != "_solution"}
        for item in completed
    ]
    return ArmResult(
        algorithm=_algorithm_label(cfg.enable_archive),
        best_solution=final_solution,
        best_cost=float(final_cost),
        evaluations=int(raw["evaluations"]),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(final_solution.routes),
        feasible=True,
        mechanism_activity={
            **raw_activity,
            "archive_enabled": bool(cfg.enable_archive),
            "archive_feedback_into_search": False,
            "second_route_search_started": False,
            "candidate_budget_equalized": True,
            "post_search_reference_work_equalized": False,
            "zero_budget_no_mechanism_completion": False,
            "prescore_capacity": PRESCORE_CAPACITY,
            "archive_capacity": ARCHIVE_CAPACITY,
            "unique_nonfinal_history_size": len(nonfinal),
            "prescore_candidate_count": len(prescore_rows),
            "prescore_reference_replays": len(prescore_rows),
            "archive_entry_count": len(completed),
            "archive_completion_call_count": len(completed),
            "archive_completion_reference_replays": int(
                completion_reference_replays
            ),
            "post_search_full_solution_replays": int(
                len(prescore_rows) + completion_reference_replays + 2
            ),
            "raw_search_independent_replays": 1,
            "selected_final_independent_replays": 1,
            "independent_final_replays": 2,
            "route_local_exact_evaluations": int(route_local_exact),
            "route_proxy_evaluations": int(route_proxy),
            "route_local_schedule_evaluations": int(route_schedule),
            "mechanism_feasibility_checks": int(feasibility_checks),
            "archive_contributed": archive_contributed,
            "ordinary_final_forced": True,
            "ordinary_final_completed_cost": float(
                ordinary["completed_cost"]
            ),
            "ordinary_final_completed_exact_signature": str(
                ordinary["completed_exact_signature"]
            ),
            "selected_completed_cost": float(final_cost),
            "selected_is_main_search_final": bool(
                selected["is_main_search_final"]
            ),
            "selected_raw_signature": str(selected["raw_signature"]),
            "selected_exact_signature": str(selected["exact_signature"]),
            "selected_skeleton_signature": str(
                selected["skeleton_signature"]
            ),
            "archive_gain_over_ordinary_final_percent": (
                (
                    float(ordinary["completed_cost"]) - float(final_cost)
                )
                / float(ordinary["completed_cost"])
                * 100.0
                if float(ordinary["completed_cost"]) > 0.0
                else 0.0
            ),
            "main_search_final_solution_snapshot": asdict(raw_solution),
            "prescore_rows": prescore_rows,
            "archive_entries": serializable_entries,
        },
    )


def _assert_main_search_ledger(raw: dict[str, Any], budget: int) -> None:
    score_counts = dict(
        raw.get("operator_counts", {}).get("score_counts", {})
    )
    selector = dict(
        raw.get("operator_counts", {}).get("selector", {})
    )
    candidate_channels = sum(
        int(value)
        for key, value in score_counts.items()
        if str(key).startswith("candidate_channel:")
    )
    values = (
        int(raw["evaluations"]),
        int(raw["candidate_scores"]),
        int(raw["actual_moves"]),
        int(score_counts.get("candidate", 0)),
        int(candidate_channels),
        int(selector.get("selection_count", 0)),
    )
    if any(value != int(budget) for value in values):
        raise RuntimeError(
            "bounded archive main-search ledger did not close: "
            f"{values} != {budget}"
        )
    if not bool(selector.get("selection_count_closed", False)):
        raise RuntimeError("bounded archive selector count did not close")


def _raw_activity(
    raw: dict[str, Any],
    scalar_history: list[dict[str, Any]],
    final_item: dict[str, Any],
) -> dict[str, Any]:
    operator_counts = dict(raw.get("operator_counts", {}))
    score_counts = dict(operator_counts.get("score_counts", {}))
    selector = dict(operator_counts.get("selector", {}))
    return {
        "continuous_main_search": True,
        "search_loop_count": 1,
        "search_restart_count": 0,
        "hgs_calls": 0,
        "complete_search_candidate_evaluations": int(raw["evaluations"]),
        "generic_candidate_evaluations": int(raw["evaluations"]),
        "mechanism_candidate_evaluations": 0,
        "candidate_scores": int(raw["candidate_scores"]),
        "actual_moves": int(raw["actual_moves"]),
        "score_counts": score_counts,
        "selector_diagnostics": selector,
        "raw_search_reference_replays": int(
            score_counts.get("reference", 0)
        ),
        "raw_search_cost": float(raw["best_cost"]),
        "raw_search_signature": str(final_item["raw_signature"]),
        "raw_search_exact_signature": str(final_item["exact_signature"]),
        "raw_search_skeleton_signature": str(
            final_item["skeleton_signature"]
        ),
        "main_search_history_length": len(scalar_history),
        "main_search_history_fingerprint": _sha_json(scalar_history),
        "main_search_operator_fingerprint": _operator_fingerprint(raw),
        "main_rng_final_state_sha256": str(
            selector.get("main_rng_final_state_sha256", "")
        ),
        "selector_rng_final_state_sha256": str(
            selector.get("selector_rng_final_state_sha256", "")
        ),
        "main_search_scalar_history": scalar_history,
    }


def _unique_route_skeleton_history(
    history: list[dict[str, Any]],
    instance: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    latest_by_skeleton: dict[str, dict[str, Any]] = {}
    scalar_history: list[dict[str, Any]] = []
    for index, row in enumerate(history):
        payload = row.get("solution_snapshot")
        if not isinstance(payload, dict):
            raise RuntimeError(
                "winner history omitted a requested solution snapshot"
            )
        solution = _solution_from_snapshot(payload)
        item = _archive_item(
            solution=solution,
            raw_cost=float(row["best_cost"]),
            history_index=index,
            eval_count=int(row.get("eval", 0)),
            operator=str(row.get("operator", "")),
            instance=instance,
            is_main_search_final=False,
        )
        scalar_history.append(
            {
                "eval": int(row.get("eval", 0)),
                "best_cost": float(row["best_cost"]),
                "best_obj": float(row["best_obj"]),
                "operator": str(row.get("operator", "")),
            }
        )
        latest_by_skeleton[str(item["skeleton_signature"])] = item
    return (
        sorted(
            latest_by_skeleton.values(),
            key=lambda item: int(item["history_index"]),
        ),
        scalar_history,
    )


def _archive_item(
    *,
    solution: Solution,
    raw_cost: float,
    history_index: int,
    eval_count: int,
    operator: str,
    instance: Any,
    is_main_search_final: bool,
) -> dict[str, Any]:
    _require_finite("archive_raw_cost", float(raw_cost))
    return {
        "history_index": int(history_index),
        "eval": int(eval_count),
        "operator": str(operator),
        "raw_cost": float(raw_cost),
        "raw_signature": solution_signature_hash(solution),
        "exact_signature": _exact_solution_hash(solution),
        "skeleton_signature": _route_skeleton_hash(solution, instance),
        "is_main_search_final": bool(is_main_search_final),
        "solution": solution,
    }


def _evenly_spaced(
    items: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return list(items)
    indices = [
        (index * (len(items) - 1)) // (limit - 1)
        for index in range(limit)
    ]
    if len(set(indices)) != limit:
        raise RuntimeError("deterministic archive sampling produced duplicates")
    return [items[index] for index in indices]


def _route_skeleton_hash(solution: Solution, instance: Any) -> str:
    node_types = {
        str(node.node_id): str(node.node_type).lower()
        for node in instance.nodes
    }
    payload = sorted(
        (
            str(route.home_depot_id),
            tuple(
                str(node_id)
                for node_id in route.node_sequence
                if node_types.get(str(node_id)) == "c"
            ),
        )
        for route in solution.routes
    )
    return _sha_json(payload)


def _exact_solution_hash(solution: Solution) -> str:
    payload = {
        "routes": sorted(
            (
                str(route.vehicle_id),
                str(route.vehicle_type).lower(),
                str(route.home_depot_id),
                tuple(str(node) for node in route.node_sequence),
            )
            for route in solution.routes
        ),
        "charging_actions": sorted(
            (
                str(action.vehicle_id),
                str(action.station_id),
                float(action.energy_kwh).hex(),
                float(action.occupancy_minutes).hex(),
                float(action.charge_start_second).hex(),
                int(action.charge_day_offset),
            )
            for action in solution.charging_actions
        ),
        "cross_site_services": sorted(
            (
                str(item.customer_id),
                str(item.served_by_depot_id),
            )
            for item in solution.cross_site_services
        ),
    }
    return _sha_json(payload)


def _solution_from_snapshot(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                str(row["vehicle_id"]),
                str(row["vehicle_type"]),
                str(row["home_depot_id"]),
                [str(node) for node in row["node_sequence"]],
            )
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            ChargingAction(
                str(row["vehicle_id"]),
                str(row["station_id"]),
                float(row["energy_kwh"]),
                float(row["occupancy_minutes"]),
                float(row["charge_start_second"]),
                int(row.get("charge_day_offset", 0)),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                str(row["customer_id"]),
                str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def _operator_fingerprint(raw: dict[str, Any]) -> str:
    counts = dict(raw.get("operator_counts", {}))
    stable = {
        key: value
        for key, value in counts.items()
        if key not in {"timing", "candidate_trace", "final_rng_state"}
    }
    return _sha_json(stable)


def _algorithm_label(enable_archive: bool) -> str:
    return (
        "bounded_dual_view_mechanism_archive_alns"
        if enable_archive
        else "bounded_dual_view_archive_disabled_v7_control"
    )


def _sha_json(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_finite(label: str, *values: float) -> None:
    if not all(math.isfinite(float(value)) for value in values):
        raise RuntimeError(f"{label} contains a non-finite value: {values}")
