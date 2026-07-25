#!/usr/bin/env python3
"""Run the fresh five-parent route-column direct headroom gate."""

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
REGISTRATION = PACKAGE / "direct_gate_registration_v1.json"
OUTPUT = PACKAGE / "direct_headroom_gate_v1"
AUTHORITY = AUTHORITY_PACKAGE / "g0_real_bundle_preregistration_v1.json"

for path in (
    REPO,
    REPO / "solver/src",
    REPO / "models/src",
    AUTHORITY_PACKAGE,
    PACKAGE,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from china81_columns import materialize_columns
from direct_gate_support import (
    build_comparison_pools,
    selected_new_boundaries,
)
from fleet_assignment_dp import _station_charger_caps
from mip_core import MipAssemblyResult, solve_route_columns
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    checker_violations = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    if violations or checker_violations:
        raise RuntimeError(
            f"{label} failed exact replay: "
            f"exact={len(violations)}, checker={len(checker_violations)}"
        )
    return float(objective)


def fleet_caps(bundle: Any) -> tuple[int, ...]:
    return tuple(
        int(bundle.fleet_caps_by_depot[depot_id][f"num_{vehicle_type}"])
        for depot_id in sorted(bundle.fleet_caps_by_depot)
        for vehicle_type in ("cv", "ev")
    )


def mip_fields(prefix: str, result: MipAssemblyResult) -> dict[str, Any]:
    return {
        f"{prefix}_mip_status": result.status,
        f"{prefix}_mip_status_class": result.status_class,
        f"{prefix}_mip_message": result.message,
        f"{prefix}_mip_dual_bound": result.dual_bound,
        f"{prefix}_mip_gap": result.mip_gap,
        f"{prefix}_mip_node_count": result.mip_node_count,
        f"{prefix}_mip_seconds": result.elapsed_seconds,
        f"{prefix}_mip_integral": result.integral,
        f"{prefix}_mip_exact_cover": result.exact_cover,
        f"{prefix}_mip_fleet_feasible": result.fleet_feasible,
        f"{prefix}_mip_charger_feasible": result.charger_feasible,
    }


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
            raise RuntimeError(
                f"sealed parent objective drift at seed {parent_spec['seed']}"
            )
        parents.append(parent)
        parent_objectives.append(objective)

    customers, old_pool, new_pool, pool_stats = build_comparison_pools(
        tuple(parents),
        bundle,
    )
    if len(new_pool) > int(config["max_route_columns"]):
        raise RuntimeError(f"new route pool exceeds registered cap: {len(new_pool)}")
    caps = fleet_caps(bundle)
    chargers = _station_charger_caps(bundle)
    old_mip = solve_route_columns(
        customers,
        old_pool,
        fleet_caps=caps,
        charger_caps=chargers,
        time_limit_seconds=float(config["mip_time_limit_seconds"]),
    )
    new_mip = solve_route_columns(
        customers,
        new_pool,
        fleet_caps=caps,
        charger_caps=chargers,
        time_limit_seconds=float(config["mip_time_limit_seconds"]),
    )
    if not old_mip.selected:
        raise RuntimeError("old parent-route pool returned no valid incumbent")
    if not new_mip.selected:
        raise RuntimeError("new route pool returned no valid incumbent")

    old_solution = materialize_columns(old_mip.selected, bundle)
    new_solution = materialize_columns(new_mip.selected, bundle)
    old_objective = exact_replay(old_solution, bundle, "old-pool solution")
    new_objective = exact_replay(new_solution, bundle, "new-pool solution")
    for label, mip, objective in (
        ("old", old_mip, old_objective),
        ("new", new_mip, new_objective),
    ):
        if mip.objective is None or not math.isclose(
            float(mip.objective),
            objective,
            rel_tol=1.0e-9,
            abs_tol=1.0e-6,
        ):
            raise RuntimeError(
                f"{label}-pool MIP objective does not close under exact score"
            )

    tolerance = float(config["strict_improvement_absolute_tolerance"])
    best_parent = min(parent_objectives)
    comparison_baseline = min(best_parent, old_objective)
    no_loss = new_objective <= comparison_baseline + tolerance
    if not no_loss:
        raise RuntimeError("new pool lost despite containing every old column")
    strict_improvement = new_objective < comparison_baseline - tolerance
    novel_boundaries = selected_new_boundaries(
        new_mip.selected,
        old_pool,
    )

    witness_path = OUTPUT / "witnesses" / f"{instance_id}.json"
    write_json(
        witness_path,
        {
            "schema": "resetp.route-column-mip-direct-witness.v1",
            "instance_id": instance_id,
            "best_parent_objective": best_parent,
            "old_pool_objective": old_objective,
            "new_pool_objective": new_objective,
            "selected_new_customer_boundaries": novel_boundaries,
            "old_pool_solution": {
                "routes": [asdict(row) for row in old_solution.routes],
                "charging_actions": [
                    asdict(row) for row in old_solution.charging_actions
                ],
                "cross_site_services": [
                    asdict(row) for row in old_solution.cross_site_services
                ],
            },
            "new_pool_solution": {
                "routes": [asdict(row) for row in new_solution.routes],
                "charging_actions": [
                    asdict(row) for row in new_solution.charging_actions
                ],
                "cross_site_services": [
                    asdict(row) for row in new_solution.cross_site_services
                ],
            },
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
        "new_pool_objective": new_objective,
        "comparison_baseline": comparison_baseline,
        "absolute_improvement": comparison_baseline - new_objective,
        "relative_improvement_pct": (
            100.0 * (comparison_baseline - new_objective) / comparison_baseline
        ),
        "strict_improvement": strict_improvement,
        "no_loss": no_loss,
        "selected_new_boundary_count": len(novel_boundaries),
        "selected_new_boundaries_json": json.dumps(
            novel_boundaries,
            ensure_ascii=False,
        ),
        **pool_stats,
        "old_selected_routes": len(old_mip.selected),
        "new_selected_routes": len(new_mip.selected),
        **mip_fields("old", old_mip),
        **mip_fields("new", new_mip),
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_bytes": peak_rss_bytes,
        "witness_path": witness_path.relative_to(REPO).as_posix(),
        "error": "",
    }


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    for relative, expected in registration["source_hashes"].items():
        if sha256(REPO / relative) != expected:
            raise RuntimeError(f"registered source drift: {relative}")
    selection = registration["selection"]
    if sha256(REPO / selection["path"]) != selection["sha256"]:
        raise RuntimeError("registered input selection drift")
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
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.name.startswith("._")
        and not any(
            part in {"__pycache__", ".pytest_cache", ".tasks"} for part in path.parts
        )
        and path.name != "artifact_hashes.json"
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
            "schema": "resetp.route-column-mip-direct-metadata.v1",
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
    passed = (
        not failures
        and len(ok_rows) == len(registration["inputs"])
        and all(row["no_loss"] for row in ok_rows)
        and len(improving_rows) >= int(config["required_improving_instances"])
        and any(int(row["selected_new_boundary_count"]) > 0 for row in improving_rows)
        and all(
            int(row["new_pool_columns"]) <= int(config["max_route_columns"])
            for row in ok_rows
        )
    )
    verdict = (
        "PASS_ROUTE_COLUMN_MIP_DIRECT_HEADROOM"
        if passed
        else "STOP_ROUTE_COLUMN_MIP_NO_DIRECT_HEADROOM"
    )
    decision = {
        "schema": "resetp.route-column-mip-direct-decision.v1",
        "verdict": verdict,
        "pass": passed,
        "rows": len(ok_rows),
        "expected_rows": len(registration["inputs"]),
        "strictly_improving_instances": len(improving_rows),
        "required_improving_instances": int(config["required_improving_instances"]),
        "improving_instances": [row["instance_id"] for row in improving_rows],
        "improving_solution_has_new_boundary": any(
            int(row["selected_new_boundary_count"]) > 0 for row in improving_rows
        ),
        "failures": failures,
        "next_step": (
            "DESIGN_HGS_ROUTE_COLUMN_INTEGRATION_GATE"
            if passed
            else "ROOT_CAUSE_REVIEW__NO_PARAMETER_RESCUE"
        ),
        "claim_boundary": registration["claim_boundary"],
    }
    write_json(OUTPUT / "decision.json", decision)
    lines = [
        "# Route-column MIP fresh direct headroom gate",
        "",
        f"Verdict: `{verdict}`",
        "",
        (
            "| instance | best parent | old pool | new pool | improve % | "
            "new boundary | columns |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in ok_rows:
        lines.append(
            f"| {row['instance_id']} | "
            f"{float(row['best_parent_objective']):.6f} | "
            f"{float(row['old_pool_objective']):.6f} | "
            f"{float(row['new_pool_objective']):.6f} | "
            f"{float(row['relative_improvement_pct']):.6f} | "
            f"{row['selected_new_boundary_count']} | "
            f"{row['new_pool_columns']} |"
        )
    if failures:
        lines.extend(["", "## Failures", "", *failures])
    lines.extend(
        [
            "",
            (
                "This gate compares five sealed parent solutions with no new "
                "HGS search. A PASS only demonstrates direct recombination "
                "headroom."
            ),
        ]
    )
    (OUTPUT / "report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    for path in OUTPUT.rglob("._*"):
        if path.is_file():
            path.unlink()
    write_json(
        OUTPUT / "artifact_hashes.json",
        artifact_hashes(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
