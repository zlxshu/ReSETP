#!/usr/bin/env python3
"""Run the route-column generation and capacity-aware MIP G0."""

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
AUTHORITY_PACKAGE = (
    REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
)
REGISTRATION = PACKAGE / "g0_registration_v1.json"
OUTPUT = PACKAGE / "g0_gate_v1"
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

from china81_columns import assemble_customer_order, customer_order
from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)

TOL = 1.0e-9


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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload["routes"]],
        charging_actions=[
            ChargingAction(**row)
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row)
            for row in payload.get("cross_site_services", [])
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


def run_one(spec: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[name] = "1"
    started = time.perf_counter()
    bundle = load_bundle(spec["instance_id"])
    witness = read_json(REPO / spec["witness_path"])
    incumbent = load_solution(witness[spec["witness_key"]])
    before, _, violations = exact_china81_score(incumbent, bundle)
    if violations or check_solution(
        incumbent,
        bundle.instance,
        bundle.prices,
    ):
        raise RuntimeError("sealed incumbent replay failed")
    if not math.isclose(
        before,
        float(spec["expected_objective"]),
        rel_tol=0.0,
        abs_tol=TOL,
    ):
        raise RuntimeError("sealed incumbent objective drift")
    order = customer_order(incumbent, bundle)
    solution, mip, pool = assemble_customer_order(
        order,
        bundle,
        incumbent,
        time_limit_seconds=float(config["mip_time_limit_seconds"]),
    )
    if int(pool["columns_after_dedup"]) > int(
        config["max_route_columns"]
    ):
        raise RuntimeError("route-column safety limit exceeded")
    after, _, after_violations = exact_china81_score(solution, bundle)
    if after_violations or check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    ):
        raise RuntimeError("assembled solution replay failed")
    if after > before + TOL:
        raise RuntimeError("MIP lost the injected incumbent cover")
    if not math.isclose(
        float(mip.objective),
        after,
        rel_tol=1.0e-9,
        abs_tol=1.0e-6,
    ):
        raise RuntimeError("MIP objective does not close under exact score")
    rss_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = (
        int(rss_raw)
        if sys.platform == "darwin"
        else int(rss_raw) * 1024
    )
    witness_path = OUTPUT / "witnesses" / f"{spec['instance_id']}.json"
    write_json(
        witness_path,
        {
            "schema": "resetp.route-column-mip-witness.v1",
            "instance_id": spec["instance_id"],
            "routes": [asdict(row) for row in solution.routes],
            "charging_actions": [
                asdict(row) for row in solution.charging_actions
            ],
            "cross_site_services": [
                asdict(row) for row in solution.cross_site_services
            ],
        },
    )
    return {
        "instance_id": spec["instance_id"],
        "seed": spec["seed"],
        "status": "OK",
        "customer_count": len(order),
        "incumbent_objective": before,
        "assembled_objective": after,
        "engineering_delta": after - before,
        **pool,
        "selected_route_count": len(mip.selected),
        "mip_status": mip.status,
        "mip_status_class": mip.status_class,
        "mip_message": mip.message,
        "mip_incumbent_available": mip.incumbent_available,
        "mip_dual_bound": mip.dual_bound,
        "mip_gap": mip.mip_gap,
        "mip_node_count": mip.mip_node_count,
        "mip_seconds": mip.elapsed_seconds,
        "mip_integral": mip.integral,
        "mip_exact_cover": mip.exact_cover,
        "mip_fleet_feasible": mip.fleet_feasible,
        "mip_charger_feasible": mip.charger_feasible,
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_bytes": peak_rss_bytes,
        "witness_path": witness_path.relative_to(REPO).as_posix(),
    }


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    for relative, expected in registration["source_hashes"].items():
        if sha256(REPO / relative) != expected:
            raise RuntimeError(f"registered source drift: {relative}")
    for spec in registration["inputs"]:
        if sha256(REPO / spec["witness_path"]) != spec["witness_sha256"]:
            raise RuntimeError(f"witness drift: {spec['instance_id']}")
    authority = registration["authority_registration"]
    if sha256(REPO / authority["path"]) != authority["sha256"]:
        raise RuntimeError("authority drift")
    return registration


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.name.startswith("._")
        and not any(
            part in {"__pycache__", ".pytest_cache", ".tasks"}
            for part in path.parts
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
            "schema": "resetp.route-column-mip-g0-metadata.v1",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "registration_sha256": sha256(REGISTRATION),
            "config": config,
            "claim_boundary": registration["claim_boundary"],
        },
    )
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    with ProcessPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(run_one, spec, config): spec
            for spec in registration["inputs"]
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001 - preserve worker evidence
                failures.append(
                    f"{spec['instance_id']}: "
                    f"{type(exc).__name__}: {exc}"
                )
    rows.sort(key=lambda row: row["instance_id"])
    if rows:
        write_csv(OUTPUT / "raw_runs.csv", rows)
    passed = (
        not failures
        and len(rows) == len(registration["inputs"])
        and all(row["mip_incumbent_available"] for row in rows)
        and all(row["mip_integral"] for row in rows)
        and all(row["mip_exact_cover"] for row in rows)
        and all(row["mip_fleet_feasible"] for row in rows)
        and all(row["mip_charger_feasible"] for row in rows)
        and all(
            int(row["non_incumbent_columns"]) > 0 for row in rows
        )
        and all(
            int(row["columns_after_dedup"])
            <= int(config["max_route_columns"])
            for row in rows
        )
        and all(
            int(row["peak_rss_bytes"])
            <= float(config["max_peak_rss_gib"]) * 1024**3
            for row in rows
        )
    )
    verdict = (
        "PASS_ROUTE_COLUMN_MIP_G0_ENGINEERING"
        if passed
        else "HALT_ROUTE_COLUMN_MIP_G0_STRUCTURE_OR_SCALE"
    )
    decision = {
        "schema": "resetp.route-column-mip-g0-decision.v1",
        "verdict": verdict,
        "pass": passed,
        "rows": len(rows),
        "expected_rows": len(registration["inputs"]),
        "failures": failures,
        "next_step": (
            "REGISTER_FRESH_DIRECT_EFFECT_GATE"
            if passed
            else "NONE"
        ),
        "claim_boundary": registration["claim_boundary"],
    }
    write_json(OUTPUT / "decision.json", decision)
    lines = [
        "# Route-column MIP G0",
        "",
        f"Verdict: `{verdict}`",
        "",
        "| instance | columns | selected | MIP status | gap | MIP s | wall s |",
        "|---|---:|---:|---|---:|---:|---:|",
    ]
    lines.extend(
        (
            f"| {row['instance_id']} | {row['columns_after_dedup']} | "
            f"{row['selected_route_count']} | "
            f"{row['mip_status_class']} | {row['mip_gap']} | "
            f"{float(row['mip_seconds']):.3f} | "
            f"{float(row['wall_seconds']):.3f} |"
        )
        for row in rows
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
    write_json(
        OUTPUT / "artifact_hashes.json",
        artifact_hashes(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
