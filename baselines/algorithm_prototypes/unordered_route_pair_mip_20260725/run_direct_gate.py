#!/usr/bin/env python3
"""Run the fresh unordered route-pair exact-resplit headroom gate."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import resource
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
AUTHORITY_PACKAGE = REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
ROUTE_COLUMN_PACKAGE = (
    REPO / "baselines/algorithm_prototypes/route_column_mip_assembly_20260725"
)
REGISTRATION = PACKAGE / "direct_registration_v1.json"
OUTPUT = PACKAGE / "direct_gate_v1"
AUTHORITY = AUTHORITY_PACKAGE / "g0_real_bundle_preregistration_v1.json"

for path in (
    REPO,
    REPO / "solver/src",
    REPO / "models/src",
    AUTHORITY_PACKAGE,
    ROUTE_COLUMN_PACKAGE,
    PACKAGE,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from china81_columns import materialize_columns
from decoder_cache import RouteLocalDecoderCache
from fleet_assignment_dp import _station_charger_caps
from mip_core import solve_route_columns
from pair_core import (
    build_parent_route_pool,
    optimize_route_pair,
)
from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)

REPLAY_TOL = 1.0e-9


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload["routes"]],
        charging_actions=[
            ChargingAction(**row) for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row) for row in payload.get("cross_site_services", [])
        ],
    )


def load_bundle(instance_id: str) -> Any:
    authority = read_json(AUTHORITY)
    inputs = authority["authorities"]
    return load_china81_bundle(
        REPO,
        instance_id,
        date=authority["scenario_date"],
        static_input_authority=inputs["static_inputs"]["path"],
        road_matrix_authority=inputs["road_matrices"]["path"],
        runtime_parameter_authority=inputs["runtime_parameters"]["path"],
        fleet_authority=inputs["finite_fleet"]["path"],
    )


def exact_replay(solution: Solution, bundle: Any, label: str) -> float:
    objective, _, violations = exact_china81_score(solution, bundle)
    direct = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    if violations or direct:
        raise RuntimeError(
            f"{label} replay failed: exact={len(violations)}, direct={len(direct)}"
        )
    return float(objective)


def global_fleet_caps(bundle: Any) -> tuple[int, ...]:
    return tuple(
        int(bundle.fleet_caps_by_depot[depot_id][f"num_{vehicle_type}"])
        for depot_id in sorted(bundle.fleet_caps_by_depot)
        for vehicle_type in ("cv", "ev")
    )


def run_one(spec: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[name] = "1"
    started = time.perf_counter()
    instance_id = spec["instance_id"]
    bundle = load_bundle(instance_id)
    parents: list[Solution] = []
    parent_objectives: list[float] = []
    for parent_spec in spec["parents"]:
        witness = read_json(REPO / parent_spec["witness_path"])
        parent = load_solution(witness[parent_spec["witness_key"]])
        objective = exact_replay(
            parent,
            bundle,
            f"parent seed {parent_spec['seed']}",
        )
        if not math.isclose(
            objective,
            float(parent_spec["expected_objective"]),
            rel_tol=0.0,
            abs_tol=REPLAY_TOL,
        ):
            raise RuntimeError(f"sealed parent drift at seed {parent_spec['seed']}")
        parents.append(parent)
        parent_objectives.append(objective)

    customers, old_pool = build_parent_route_pool(
        tuple(parents),
        bundle,
    )
    old_mip = solve_route_columns(
        customers,
        old_pool,
        fleet_caps=global_fleet_caps(bundle),
        charger_caps=_station_charger_caps(bundle),
        time_limit_seconds=10.0,
    )
    if not old_mip.selected:
        raise RuntimeError("parent-route pool has no valid incumbent")
    old_solution = materialize_columns(old_mip.selected, bundle)
    old_objective = exact_replay(old_solution, bundle, "old-pool")
    if old_mip.objective is None or not math.isclose(
        float(old_mip.objective),
        old_objective,
        rel_tol=1.0e-9,
        abs_tol=1.0e-6,
    ):
        raise RuntimeError("old-pool objective does not close")

    best_parent = min(parent_objectives)
    baseline = min(best_parent, old_objective)
    tolerance = float(config["strict_improvement_absolute_tolerance"])
    best_solution = (
        old_solution
        if old_objective <= best_parent
        else parents[parent_objectives.index(best_parent)]
    )
    best_objective = baseline
    best_source = "old_pool" if old_objective <= best_parent else "parent"
    best_pair: tuple[int, int] | None = None
    best_from_nonadjacent_parent_pair = False
    any_nonadjacent_parent_pair_headroom = False
    cache = RouteLocalDecoderCache()
    trace_rows: list[dict[str, Any]] = []
    sources = [
        *[
            (f"parent_seed_{seed}", "parent", solution, objective)
            for seed, solution, objective in zip(
                range(1, 6),
                parents,
                parent_objectives,
                strict=True,
            )
        ],
        ("old_pool", "old_pool", old_solution, old_objective),
    ]
    exact_candidate_evaluations = 0
    pair_attempts = 0
    local_improvement_signals = 0
    for source_label, source_kind, source, source_objective in sources:
        route_count = len(source.routes)
        for first in range(route_count):
            for second in range(first + 1, route_count):
                if time.perf_counter() - started > float(
                    config["instance_wallclock_safety_seconds"]
                ):
                    raise TimeoutError(
                        "registered instance wallclock safety limit reached"
                    )
                pair_attempts += 1
                candidate, mip, stats = optimize_route_pair(
                    source,
                    (first, second),
                    bundle,
                    cache=cache,
                    time_limit_seconds=float(config["pair_mip_time_limit_seconds"]),
                    max_columns=int(config["max_pair_columns"]),
                )
                if mip.objective is None:
                    raise RuntimeError("pair MIP objective missing")
                local_delta = float(mip.objective) - float(stats["fallback_objective"])
                exact_evaluated = False
                candidate_objective: float | None = None
                exact_improvement = False
                if local_delta < -float(
                    config["strict_improvement_absolute_tolerance"]
                ):
                    local_improvement_signals += 1
                    candidate_objective = exact_replay(
                        candidate,
                        bundle,
                        (f"{source_label} pair {first},{second}"),
                    )
                    exact_candidate_evaluations += 1
                    exact_evaluated = True
                    exact_improvement = candidate_objective < source_objective - float(
                        config["strict_improvement_absolute_tolerance"]
                    )
                    if (
                        source_kind == "parent"
                        and second != first + 1
                        and candidate_objective < baseline - tolerance
                    ):
                        any_nonadjacent_parent_pair_headroom = True
                    if candidate_objective < best_objective - float(
                        config["strict_improvement_absolute_tolerance"]
                    ):
                        best_solution = candidate
                        best_objective = candidate_objective
                        best_source = source_label
                        best_pair = (first, second)
                        best_from_nonadjacent_parent_pair = bool(
                            source_kind == "parent" and second != first + 1
                        )
                trace_rows.append(
                    {
                        "instance_id": instance_id,
                        "source": source_label,
                        "source_kind": source_kind,
                        "source_objective": source_objective,
                        "route_first": first,
                        "route_second": second,
                        "source_adjacent": second == first + 1,
                        **stats,
                        "mip_status_class": mip.status_class,
                        "mip_gap": mip.mip_gap,
                        "mip_seconds": mip.elapsed_seconds,
                        "local_delta": local_delta,
                        "exact_evaluated": exact_evaluated,
                        "candidate_objective": candidate_objective,
                        "exact_improvement": exact_improvement,
                    }
                )

    trace_path = OUTPUT / "traces" / f"{instance_id}.csv"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(trace_rows[0]),
        )
        writer.writeheader()
        writer.writerows(trace_rows)

    final_objective = exact_replay(
        best_solution,
        bundle,
        "best route-pair result",
    )
    if not math.isclose(
        final_objective,
        best_objective,
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("best route-pair objective drift")
    strict_improvement = final_objective < baseline - tolerance
    witness_path = OUTPUT / "witnesses" / f"{instance_id}.json"
    write_json(
        witness_path,
        {
            "schema": "resetp.unordered-route-pair-direct-witness.v1",
            "instance_id": instance_id,
            "baseline_objective": baseline,
            "final_objective": final_objective,
            "best_source": best_source,
            "best_pair": best_pair,
            "best_from_nonadjacent_parent_pair": (best_from_nonadjacent_parent_pair),
            "any_nonadjacent_parent_pair_headroom": (
                any_nonadjacent_parent_pair_headroom
            ),
            "routes": [asdict(route) for route in best_solution.routes],
            "charging_actions": [
                asdict(action) for action in best_solution.charging_actions
            ],
            "cross_site_services": [
                asdict(service) for service in best_solution.cross_site_services
            ],
        },
    )
    rss_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = int(rss_raw) if sys.platform == "darwin" else int(rss_raw) * 1024
    return {
        "instance_id": instance_id,
        "status": "OK",
        "customer_count": len(customers),
        "parent_objectives_json": json.dumps(parent_objectives),
        "best_parent_objective": best_parent,
        "old_pool_objective": old_objective,
        "baseline_objective": baseline,
        "final_objective": final_objective,
        "absolute_improvement": baseline - final_objective,
        "relative_improvement_pct": (100.0 * (baseline - final_objective) / baseline),
        "strict_improvement": strict_improvement,
        "no_loss": final_objective <= baseline + tolerance,
        "best_source": best_source,
        "best_pair_json": json.dumps(best_pair),
        "best_from_nonadjacent_parent_pair": (best_from_nonadjacent_parent_pair),
        "any_nonadjacent_parent_pair_headroom": (any_nonadjacent_parent_pair_headroom),
        "pair_attempts": pair_attempts,
        "local_improvement_signals": local_improvement_signals,
        "exact_candidate_evaluations": exact_candidate_evaluations,
        "old_pool_columns": len(old_pool),
        "old_pool_mip_status": old_mip.status_class,
        "old_pool_mip_gap": old_mip.mip_gap,
        "old_pool_mip_seconds": old_mip.elapsed_seconds,
        "decoder_cache_json": json.dumps(cache.as_dict()),
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_bytes": peak_rss_bytes,
        "trace_path": trace_path.relative_to(REPO).as_posix(),
        "witness_path": witness_path.relative_to(REPO).as_posix(),
        "error": "",
    }


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    for relative, expected in registration["source_hashes"].items():
        if sha256(REPO / relative) != expected:
            raise RuntimeError(f"registered source drift: {relative}")
    for key in ("selection", "invalid_selection_preserved"):
        spec = registration[key]
        if sha256(REPO / spec["path"]) != spec["sha256"]:
            raise RuntimeError(f"registered {key} drift")
    g0 = registration["g0"]
    if sha256(REPO / g0["decision_path"]) != g0["decision_sha256"]:
        raise RuntimeError("G0 decision drift")
    if sha256(REPO / g0["artifact_hashes_path"]) != g0["artifact_hashes_sha256"]:
        raise RuntimeError("G0 artifact manifest drift")
    for spec in registration["inputs"]:
        for parent in spec["parents"]:
            if sha256(REPO / parent["witness_path"]) != parent["witness_sha256"]:
                raise RuntimeError(
                    f"witness drift: {spec['instance_id']} seed {parent['seed']}"
                )
    authority = registration["authority_registration"]
    if sha256(REPO / authority["path"]) != authority["sha256"]:
        raise RuntimeError("authority drift")
    return registration


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.name.startswith("._")
        and path.name != "artifact_hashes.json"
        and not any(part in {"__pycache__", ".pytest_cache"} for part in path.parts)
    }


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"output exists: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    registration = verify_registration()
    config = registration["config"]
    write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.unordered-route-pair-direct-metadata.v1",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "registration_sha256": sha256(REGISTRATION),
            "config": config,
            "claim_boundary": registration["claim_boundary"],
        },
    )
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    with ProcessPoolExecutor(max_workers=int(config["workers"])) as pool:
        futures = {
            pool.submit(run_one, spec, config): spec for spec in registration["inputs"]
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001 - preserve evidence
                message = f"{spec['instance_id']}: {type(exc).__name__}: {exc}"
                failures.append(message)
                rows.append(
                    {
                        "instance_id": spec["instance_id"],
                        "status": "ERROR",
                        "error": message,
                    }
                )
    rows.sort(key=lambda row: row["instance_id"])
    write_csv(OUTPUT / "raw_runs.csv", rows)
    ok_rows = [row for row in rows if row["status"] == "OK"]
    improving_rows = [row for row in ok_rows if row["strict_improvement"]]
    has_nonadjacent = any(
        row["any_nonadjacent_parent_pair_headroom"] for row in improving_rows
    )
    passed = bool(
        not failures
        and len(ok_rows) == len(registration["inputs"])
        and all(row["no_loss"] for row in ok_rows)
        and len(improving_rows) >= int(config["required_improving_instances"])
        and has_nonadjacent
    )
    verdict = (
        "PASS_URP_MIP_DIRECT_HEADROOM" if passed else "STOP_URP_MIP_NO_DIRECT_HEADROOM"
    )
    decision = {
        "schema": "resetp.unordered-route-pair-direct-decision.v1",
        "verdict": verdict,
        "pass": passed,
        "rows": len(ok_rows),
        "expected_rows": len(registration["inputs"]),
        "strictly_improving_instances": len(improving_rows),
        "required_improving_instances": int(config["required_improving_instances"]),
        "improving_instances": [row["instance_id"] for row in improving_rows],
        "has_nonadjacent_parent_pair_improvement": has_nonadjacent,
        "failures": failures,
        "next_step": (
            "DESIGN_STANDALONE_ITERATED_ALGORITHM_B"
            if passed
            else "ROOT_CAUSE_REVIEW__NO_PARAMETER_RESCUE"
        ),
        "claim_boundary": registration["claim_boundary"],
    }
    write_json(OUTPUT / "decision.json", decision)
    lines = [
        "# Unordered route-pair direct headroom gate",
        "",
        f"Verdict: `{verdict}`",
        "",
        (
            "| instance | baseline | final | improve % | pairs | "
            "exact checks | nonadjacent |"
        ),
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in ok_rows:
        lines.append(
            f"| {row['instance_id']} | "
            f"{float(row['baseline_objective']):.6f} | "
            f"{float(row['final_objective']):.6f} | "
            f"{float(row['relative_improvement_pct']):.6f} | "
            f"{row['pair_attempts']} | "
            f"{row['exact_candidate_evaluations']} | "
            f"{row['any_nonadjacent_parent_pair_headroom']} |"
        )
    if failures:
        lines.extend(["", "## Failures", "", *failures])
    (OUTPUT / "report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    for path in OUTPUT.rglob("._*"):
        if path.is_file():
            path.unlink()
    write_json(OUTPUT / "artifact_hashes.json", artifact_hashes(OUTPUT))
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
