"""Continuous ALNS with a mechanism-aware archive of historical best routes.

The main ALNS trajectory is never interrupted or educated by a second solver.
It consumes the full candidate budget exactly as the frozen winner kernel
does.  Whenever that kernel records a new historical best, an optional deep
snapshot is retained.  Only after the continuous search has ended do the
frozen responsibility, fleet/charging, and carbon-time experts complete each
unique snapshot.  The completed archive is a monotone envelope containing the
ordinary final-v7 completion, so the archive cannot return a worse solution.

Method background:

* Ropke and Pisinger (2006), doi:10.1287/trsc.1050.0135, motivates one
  continuous adaptive search rather than repeated cold restarts.
* Vidal et al. (2012), doi:10.1287/opre.1120.1048, motivates retaining
  distinct elite solutions under more than one quality view.
* Hiermann et al. (2019), doi:10.1016/j.ejor.2018.06.025, motivates
  separating customer-route search from fleet and charging completion.

This is an isolated stage-one development implementation.  Archive completion
replays and route-local mechanism work are reported separately from the
complete search-candidate budget; they do not feed back into ALNS.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Any

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
from initial_pool import solution_signature_hash


TOL = 1.0e-9


@dataclass(frozen=True)
class MechanismEliteConfig:
    """Fixed controls for the passive mechanism-elite archive."""

    total_eval_budget: int = 100
    enable_archive: bool = True
    runtime_cap_seconds: float = 3600.0


def run_mechanism_elite_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    config: MechanismEliteConfig | None = None,
    prices: Any = DEFAULT_PRICES,
) -> ArmResult:
    """Run one continuous ALNS and complete its historical-best archive."""

    cfg = config or MechanismEliteConfig()
    budget = max(0, int(cfg.total_eval_budget))
    started = time.perf_counter()
    raw = run_winner_kernel(
        bundle_dir,
        config=WinnerKernelConfig(
            seed=int(seed),
            eval_budget=budget,
            max_runtime_seconds=float(cfg.runtime_cap_seconds),
            require_charging_signal=False,
            capture_best_solutions=True,
        ),
        prices=prices,
    )
    if int(raw["evaluations"]) != budget:
        raise RuntimeError(
            "mechanism-elite ALNS did not close the complete candidate budget: "
            f"{raw['evaluations']} != {budget}"
        )

    archive, scalar_history = _unique_history_archive(
        list(raw.get("history", [])),
        raw["best_solution"],
        float(raw["best_cost"]),
    )
    final_signature = solution_signature_hash(raw["best_solution"])
    if final_signature not in {item["raw_signature"] for item in archive}:
        raise RuntimeError("final ALNS solution is absent from its own archive")

    eligible = (
        archive
        if cfg.enable_archive
        else [
            item
            for item in archive
            if item["raw_signature"] == final_signature
        ]
    )
    completed: list[dict[str, Any]] = []
    for item in eligible:
        outcome = apply_terminal_completion(
            bundle_dir,
            item["solution"],
            prices=prices,
        )
        if not outcome.feasible:
            raise RuntimeError(
                "mechanism completion returned an infeasible archive entry: "
                f"{item['raw_signature']}"
            )
        completed.append(
            {
                "history_index": int(item["history_index"]),
                "eval": int(item["eval"]),
                "operator": str(item["operator"]),
                "is_main_search_final": bool(
                    item["raw_signature"] == final_signature
                ),
                "raw_cost": float(item["raw_cost"]),
                "raw_signature": str(item["raw_signature"]),
                "completed_cost": float(outcome.cost),
                "completed_signature": solution_signature_hash(
                    outcome.solution
                ),
                "selected_branch": str(outcome.selected_branch),
                "solution": outcome.solution,
                "activity": outcome.activity,
            }
        )
    if not completed:
        raise RuntimeError("mechanism archive produced no completed solution")

    # Exact ties fall back to the ordinary final-v7 branch.  This preserves the
    # incumbent identity when the archive contributes no strict improvement.
    selected = min(
        completed,
        key=lambda item: (
            float(item["completed_cost"]),
            0 if item["is_main_search_final"] else 1,
            -int(item["eval"]),
            str(item["raw_signature"]),
        ),
    )
    final_completed = next(
        item for item in completed if item["is_main_search_final"]
    )
    if (
        float(selected["completed_cost"])
        > float(final_completed["completed_cost"]) + TOL
    ):
        raise RuntimeError("mechanism archive violated its monotone envelope")

    solution = selected["solution"]
    recomputed = independent_cost(bundle_dir, solution, prices)
    if abs(float(recomputed) - float(selected["completed_cost"])) > 1.0e-7:
        raise RuntimeError(
            "mechanism archive final objective mismatch: "
            f"{selected['completed_cost']} != {recomputed}"
        )
    bundle = load_search_bundle(bundle_dir)
    violations = check_solution(solution, bundle.instance, prices)
    if violations:
        raise RuntimeError(
            f"mechanism archive final solution is infeasible: {violations[:8]}"
        )

    score_counts = dict(
        raw.get("operator_counts", {}).get("score_counts", {})
    )
    completion_replays = sum(
        int(item["activity"].get("full_solution_replays", 0))
        for item in completed
    )
    completion_summaries = [
        {
            key: value
            for key, value in item.items()
            if key not in {"solution", "activity"}
        }
        | {
            "responsibility_updates": int(
                item["activity"]
                .get("responsibility", {})
                .get("exact_decoder_updates", 0)
            ),
            "fleet_charge_updates": int(
                item["activity"]
                .get("joint", {})
                .get("exact_decoder_updates", 0)
            ),
            "carbon_updates": int(
                item["activity"]
                .get("carbon", {})
                .get("exact_decoder_updates", 0)
            ),
            "reference_replays": int(
                item["activity"].get("full_solution_replays", 0)
            ),
            "route_local_exact_evaluations": int(
                item["activity"].get(
                    "route_local_exact_evaluations",
                    0,
                )
            ),
            "route_proxy_evaluations": int(
                item["activity"].get("route_proxy_evaluations", 0)
            ),
            "route_local_schedule_evaluations": int(
                item["activity"].get(
                    "route_local_schedule_evaluations",
                    0,
                )
            ),
        }
        for item in completed
    ]
    archive_contributed = bool(
        not selected["is_main_search_final"]
        and float(selected["completed_cost"])
        < float(final_completed["completed_cost"]) - TOL
    )
    label = (
        "mechanism_elite_archive_alns"
        if cfg.enable_archive
        else "mechanism_elite_archive_disabled_control"
    )
    return ArmResult(
        algorithm=label,
        best_solution=solution,
        best_cost=float(recomputed),
        evaluations=int(raw["evaluations"]),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(solution.routes),
        feasible=True,
        mechanism_activity={
            "continuous_main_search": True,
            "archive_feedback_into_search": False,
            "archive_enabled": bool(cfg.enable_archive),
            "complete_search_candidate_evaluations": int(raw["evaluations"]),
            "total_compute_equalized": False,
            "history_snapshot_count": len(raw.get("history", [])),
            "unique_archive_size": len(archive),
            "completed_archive_size": len(completed),
            "archive_contributed": archive_contributed,
            "main_search_final_cost": float(raw["best_cost"]),
            "main_search_final_signature": final_signature,
            "main_search_history_fingerprint": _sha_json(scalar_history),
            "main_search_operator_fingerprint": _operator_fingerprint(raw),
            "main_search_final_rng_fingerprint": _sha_json(
                raw.get("operator_counts", {}).get("final_rng_state", {})
            ),
            "selected_history_eval": int(selected["eval"]),
            "selected_raw_signature": str(selected["raw_signature"]),
            "selected_completed_signature": str(
                selected["completed_signature"]
            ),
            "ordinary_final_completed_cost": float(
                final_completed["completed_cost"]
            ),
            "archive_gain_over_ordinary_final_percent": (
                (
                    float(final_completed["completed_cost"])
                    - float(selected["completed_cost"])
                )
                / float(final_completed["completed_cost"])
                * 100.0
                if float(final_completed["completed_cost"]) > 0.0
                else 0.0
            ),
            "raw_search_reference_replays": int(
                score_counts.get("reference", 0)
            ),
            "archive_completion_reference_replays": int(
                completion_replays
            ),
            "total_reported_reference_replays": int(
                score_counts.get("reference", 0)
            )
            + int(completion_replays)
            + 1,
            "independent_final_replays": 1,
            "score_counts": score_counts,
            "archive_entries": completion_summaries,
        },
    )


def _unique_history_archive(
    history: list[dict[str, Any]],
    final_solution: Solution,
    final_cost: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    archive: list[dict[str, Any]] = []
    scalar_history: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(history):
        payload = row.get("solution_snapshot")
        if not isinstance(payload, dict):
            raise RuntimeError(
                "winner history omitted a requested solution snapshot"
            )
        solution = _solution_from_snapshot(payload)
        signature = solution_signature_hash(solution)
        scalar = {
            "eval": int(row.get("eval", 0)),
            "best_cost": float(row["best_cost"]),
            "best_obj": float(row["best_obj"]),
            "operator": str(row["operator"]),
            "signature": signature,
        }
        scalar_history.append(scalar)
        if signature in seen:
            continue
        seen.add(signature)
        archive.append(
            {
                "history_index": int(index),
                "eval": int(row.get("eval", 0)),
                "operator": str(row["operator"]),
                "raw_cost": float(row["best_cost"]),
                "raw_signature": signature,
                "solution": solution,
            }
        )

    final_signature = solution_signature_hash(final_solution)
    if final_signature not in seen:
        archive.append(
            {
                "history_index": len(history),
                "eval": max(
                    [int(row.get("eval", 0)) for row in history] or [0]
                ),
                "operator": "winner_kernel_final",
                "raw_cost": float(final_cost),
                "raw_signature": final_signature,
                "solution": final_solution,
            }
        )
        scalar_history.append(
            {
                "eval": archive[-1]["eval"],
                "best_cost": float(final_cost),
                "best_obj": float(final_cost),
                "operator": "winner_kernel_final",
                "signature": final_signature,
            }
        )
    return archive, scalar_history


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


def _sha_json(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
