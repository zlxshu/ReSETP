#!/usr/bin/env python3
"""Bounded pre/post probe for T4-SOLVER-FLEETCAP-FIX."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for entry in (REPO, REPO / "solver/src", REPO / "models/src", PROTOTYPE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

for name in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[name] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import route_pool_sp  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import exact_china81_score  # noqa: E402
from setp_solver.model_config import ModelConfig, model_config_scope  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402


INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
AUTHORITY = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v3_20260802"
)
SPECS = (
    ("seed1_budget100", 1, 100),
    ("seed2_budget100", 2, 100),
    ("seed3_budget100", 3, 100),
    ("seed1_budget1000", 1, 1_000),
)
CHECKPOINT_INTERVAL = 100
ARCHIVE_LIMIT = 8
EXACT_ELITES = 2
SP_SECONDS = 0.5
WALLCLOCK_SAFETY_SECONDS = 600.0
CANDIDATE_SOURCES = {
    "hgs_iteration_checkpoint",
    "terminal_population_archive",
    "proxy_best_solution",
}


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = (
        "label",
        "run_id",
        "seed",
        "budget",
        "evaluation_index",
        "view",
        "source",
        "iteration",
        "candidate_id",
        "completion_succeeded",
        "status",
        "complete_objective",
        "complete_objective_float_hex",
        "exception_type",
        "exception_message",
        "failure_category",
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def initial_solution() -> Solution:
    witness = json.loads(
        (AUTHORITY / "witnesses" / f"{INSTANCE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    level = witness["levels"]["25"]
    if level["status"] != "CERTIFIED" or level["violations"]:
        raise RuntimeError("v3 level-25 witness is not certified")
    routes: list[Route] = []
    for depot_id, depot in sorted(level["depots"].items()):
        for vehicle_type in ("cv", "ev"):
            for timed in depot[f"{vehicle_type}_routes"]:
                routes.append(
                    Route(
                        vehicle_id=f"T4-INIT-{len(routes) + 1:04d}",
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        node_sequence=[
                            depot_id,
                            *timed["customers"],
                            depot_id,
                        ],
                    )
                )
    return Solution(routes=routes)


def route_signature(solution: Solution) -> list[list[Any]]:
    return [
        [
            route.vehicle_type.lower(),
            route.home_depot_id,
            list(route.node_sequence),
        ]
        for route in sorted(
            solution.routes,
            key=lambda item: (
                item.vehicle_type.lower(),
                item.home_depot_id,
                tuple(item.node_sequence),
            ),
        )
    ]


def classify_failure(message: str) -> str:
    if not message:
        raise RuntimeError("completion failure has an empty exception message")
    if message.startswith("SEARCH_NOT_FOUND:"):
        return "搜索未找到"
    if message.startswith("BUSINESS_HARD_INFEASIBLE:"):
        return "业务硬不可行"
    return "代理找到但完成失败"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, choices=("pre", "post"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC).isoformat()
    trace_rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    try:
        config = ModelConfig(
            strict_multitrip=True,
            depot_charger_capacity_mode="unbounded",
        )
        bundle = load_china81_bundle(
            REPO,
            INSTANCE_ID,
            fleet_authority=AUTHORITY,
            model_config=config,
        )
        initial = initial_solution()
        for run_id, seed, budget in SPECS:
            print(
                f"START {args.label} {run_id} seed={seed} budget={budget}",
                flush=True,
            )
            with model_config_scope(config):
                run = route_pool_sp.run_hgs_route_pool_recombination(
                    bundle,
                    initial,
                    seed=seed,
                    hgs_seconds_per_view=None,
                    exact_elites_per_view=EXACT_ELITES,
                    max_archive_candidates_per_view=ARCHIVE_LIMIT,
                    sp_time_limit_seconds=SP_SECONDS,
                    hard_home_depot_lock=False,
                    max_hgs_iterations_per_view=budget,
                    max_no_improvement_iterations_per_view=None,
                    wallclock_safety_seconds_per_view=(
                        WALLCLOCK_SAFETY_SECONDS
                    ),
                    exact_checkpoint_interval_iterations=(
                        CHECKPOINT_INTERVAL
                    ),
                    preserve_base_pool_recombination=False,
                )
            objective, breakdown, violations = exact_china81_score(
                run.completion.solution,
                bundle,
            )
            if violations:
                raise RuntimeError(
                    f"{run_id} final violations: {violations[:3]!r}"
                )
            signature = route_signature(run.completion.solution)
            per_run_trace: list[dict[str, Any]] = []
            failure_distribution: Counter[str] = Counter()
            candidate_attempts = 0
            candidate_successes = 0
            for item in run.stats["complete_candidate_evaluation_trace"]:
                message = str(item.get("exception_message") or "")
                source = str(item["source"])
                success = bool(
                    item.get(
                        "completion_succeeded",
                        item.get("status") == "PASS",
                    )
                )
                category = str(item.get("failure_category") or "")
                if not success and not category:
                    category = classify_failure(message)
                objective_value = item.get("complete_objective")
                row = {
                    "label": args.label,
                    "run_id": run_id,
                    "seed": seed,
                    "budget": budget,
                    "evaluation_index": int(item["evaluation_index"]),
                    "view": item["view"],
                    "source": source,
                    "iteration": (
                        "" if item.get("iteration") is None else int(item["iteration"])
                    ),
                    "candidate_id": item.get("candidate_id", ""),
                    "completion_succeeded": success,
                    "status": item["status"],
                    "complete_objective": (
                        "" if objective_value is None else float(objective_value)
                    ),
                    "complete_objective_float_hex": (
                        "" if objective_value is None else float(objective_value).hex()
                    ),
                    "exception_type": item.get("exception_type", ""),
                    "exception_message": message,
                    "failure_category": category,
                }
                trace_rows.append(row)
                per_run_trace.append(
                    {
                        key: row[key]
                        for key in (
                            "evaluation_index",
                            "view",
                            "source",
                            "iteration",
                            "candidate_id",
                            "completion_succeeded",
                            "status",
                            "complete_objective_float_hex",
                            "exception_type",
                            "exception_message",
                            "failure_category",
                        )
                    }
                )
                if source in CANDIDATE_SOURCES:
                    candidate_attempts += 1
                    candidate_successes += int(success)
                    if not success:
                        failure_distribution[category] += 1
            checkpoint_series = [
                item
                for item in per_run_trace
                if item["source"] == "hgs_iteration_checkpoint"
            ]
            run_rows.append(
                {
                    "run_id": run_id,
                    "seed": seed,
                    "budget": budget,
                    "checkpoint_interval": CHECKPOINT_INTERVAL,
                    "archive_limit_per_view": ARCHIVE_LIMIT,
                    "exact_elites_per_view": EXACT_ELITES,
                    "sp_seconds": SP_SECONDS,
                    "objective": float(objective),
                    "objective_float_hex": float(objective).hex(),
                    "route_signature": signature,
                    "route_signature_sha256": canonical_sha256(signature),
                    "solution_sha256": canonical_sha256(
                        asdict(run.completion.solution)
                    ),
                    "route_count": len(run.completion.solution.routes),
                    "candidate_completion_attempts": candidate_attempts,
                    "candidate_completion_successes": candidate_successes,
                    "candidate_completion_failures": (
                        candidate_attempts - candidate_successes
                    ),
                    "failure_category_distribution": dict(
                        sorted(failure_distribution.items())
                    ),
                    "hgs_iterations_by_view": {
                        view: int(epoch.stats["hgs_iterations"])
                        for view, epoch in run.view_epochs.items()
                    },
                    "checkpoint_series": checkpoint_series,
                    "search_trace_sha256": canonical_sha256(per_run_trace),
                    "selected_source": run.stats["selected_source"],
                    "total_distance_m": float(breakdown["distance_total"]),
                    "total_emissions_kg": float(breakdown["E_total"]),
                }
            )
            print(
                f"DONE {args.label} {run_id} objective={objective.hex()} "
                f"success={candidate_successes}/{candidate_attempts}",
                flush=True,
            )
        result = {
            "schema": "resetp.t4-solver-fleetcap-probe.v1",
            "status": "PASS_PROBE_EXECUTION",
            "label": args.label,
            "instance_id": INSTANCE_ID,
            "fleet_authority": str(AUTHORITY.relative_to(REPO)),
            "fleet_caps_by_depot": {
                depot: dict(values)
                for depot, values in bundle.fleet_caps_by_depot.items()
            },
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "python_executable": sys.executable,
            "runs": run_rows,
        }
        atomic_csv(output / "trace.csv", trace_rows)
        atomic_json(output / "result.json", result)
        atomic_json(
            output / "done.json",
            {
                "status": result["status"],
                "completed_at": result["completed_at"],
                "result_sha256": canonical_sha256(result),
            },
        )
        return 0
    except Exception as exc:
        failure = {
            "schema": "resetp.t4-solver-fleetcap-probe.v1",
            "status": "HALT_OTHER",
            "label": args.label,
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
            "partial_runs": run_rows,
        }
        atomic_csv(output / "trace.csv", trace_rows)
        atomic_json(output / "result.json", failure)
        atomic_json(
            output / "done.json",
            {
                "status": failure["status"],
                "completed_at": failure["completed_at"],
                "result_sha256": canonical_sha256(failure),
            },
        )
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
