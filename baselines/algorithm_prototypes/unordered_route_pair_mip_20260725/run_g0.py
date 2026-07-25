#!/usr/bin/env python3
"""Run the unordered route-pair MIP engineering gate."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import time
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
REGISTRATION = PACKAGE / "g0_registration_v1.json"
OUTPUT = PACKAGE / "g0_gate_v1"

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

from decoder_cache import RouteLocalDecoderCache
from pair_core import optimize_route_pair
from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


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
    registration = read_json(REGISTRATION)
    for relative, expected in registration["source_hashes"].items():
        if sha256(REPO / relative) != expected:
            raise RuntimeError(f"registered source drift: {relative}")
    witness_spec = registration["witness"]
    if sha256(REPO / witness_spec["path"]) != witness_spec["sha256"]:
        raise RuntimeError("registered witness drift")
    authority_spec = registration["authority_registration"]
    if sha256(REPO / authority_spec["path"]) != authority_spec["sha256"]:
        raise RuntimeError("registered authority drift")

    OUTPUT.mkdir(parents=True)
    started = time.perf_counter()
    write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.unordered-route-pair-g0-metadata.v1",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "registration_sha256": sha256(REGISTRATION),
            "claim_boundary": registration["claim_boundary"],
        },
    )
    config = registration["config"]
    authority = registration["authority"]
    bundle = load_china81_bundle(
        REPO,
        config["instance_id"],
        date=registration["scenario_date"],
        static_input_authority=authority["static_inputs"]["path"],
        road_matrix_authority=authority["road_matrices"]["path"],
        runtime_parameter_authority=authority["runtime_parameters"]["path"],
        fleet_authority=authority["finite_fleet"]["path"],
    )
    solution = load_solution(read_json(REPO / witness_spec["path"]))
    before, _, before_violations = exact_china81_score(solution, bundle)
    if before_violations or check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    ):
        raise RuntimeError("engineering witness replay failed")
    if not math.isclose(
        before,
        float(registration["expected_objective"]),
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("engineering witness objective drift")

    candidate, mip, stats = optimize_route_pair(
        solution,
        tuple(config["route_pair_indices"]),
        bundle,
        cache=RouteLocalDecoderCache(),
        time_limit_seconds=float(config["mip_time_limit_seconds"]),
        max_columns=int(config["max_pair_columns"]),
    )
    after, _, after_violations = exact_china81_score(candidate, bundle)
    direct_violations = check_solution(
        candidate,
        bundle.instance,
        bundle.prices,
    )
    passed = bool(
        not after_violations
        and not direct_violations
        and mip.selected
        and mip.integral
        and mip.exact_cover
        and mip.fleet_feasible
        and mip.charger_feasible
        and after <= before + 1.0e-9
        and int(stats["columns_after_dedup"]) <= int(config["max_pair_columns"])
    )
    row = {
        "instance_id": config["instance_id"],
        "route_pair_indices": json.dumps(config["route_pair_indices"]),
        "before_objective": before,
        "after_objective": after,
        **stats,
        "mip_status": mip.status,
        "mip_status_class": mip.status_class,
        "mip_dual_bound": mip.dual_bound,
        "mip_gap": mip.mip_gap,
        "mip_node_count": mip.mip_node_count,
        "mip_seconds": mip.elapsed_seconds,
        "mip_integral": mip.integral,
        "mip_exact_cover": mip.exact_cover,
        "mip_fleet_feasible": mip.fleet_feasible,
        "mip_charger_feasible": mip.charger_feasible,
        "exact_violation_count": len(after_violations),
        "direct_violation_count": len(direct_violations),
        "wall_seconds": time.perf_counter() - started,
    }
    with (OUTPUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    write_json(
        OUTPUT / "witness.json",
        {
            "schema": "resetp.unordered-route-pair-g0-witness.v1",
            "routes": [asdict(route) for route in candidate.routes],
            "charging_actions": [
                asdict(action) for action in candidate.charging_actions
            ],
            "cross_site_services": [
                asdict(service) for service in candidate.cross_site_services
            ],
        },
    )
    verdict = "PASS_URP_MIP_G0_ENGINEERING" if passed else "HALT_URP_MIP_G0_ENGINEERING"
    write_json(
        OUTPUT / "decision.json",
        {
            "schema": "resetp.unordered-route-pair-g0-decision.v1",
            "verdict": verdict,
            "pass": passed,
            "next_step": ("REGISTER_FRESH_DIRECT_GATE" if passed else "NONE"),
            "claim_boundary": registration["claim_boundary"],
        },
    )
    (OUTPUT / "report.md").write_text(
        "\n".join(
            [
                "# Unordered route-pair MIP G0",
                "",
                f"Verdict: `{verdict}`",
                "",
                f"- objective: {before:.12f} -> {after:.12f}",
                f"- columns: {stats['columns_after_dedup']}",
                f"- MIP: {mip.status_class}, gap={mip.mip_gap}",
                (
                    "- violations: "
                    f"exact={len(after_violations)}, "
                    f"direct={len(direct_violations)}"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for path in OUTPUT.rglob("._*"):
        if path.is_file():
            path.unlink()
    write_json(OUTPUT / "artifact_hashes.json", artifact_hashes(OUTPUT))
    print(json.dumps({"verdict": verdict}, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
