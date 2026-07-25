#!/usr/bin/env python3
"""Run the zero-candidate-objective feasibility and wiring gate."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
FAILED_PACKAGE = (
    REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
)
REGISTRATION = PACKAGE / "g0_registration_v1.json"
OUTPUT = PACKAGE / "g0_gate_v1"
AUTHORITY = FAILED_PACKAGE / "g0_real_bundle_preregistration_v1.json"
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

for path in (
    REPO,
    REPO / "solver/src",
    REPO / "models/src",
    FAILED_PACKAGE,
    PACKAGE,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from decoder_cache import RouteLocalDecoderCache
from ejection_rebuild import generate_ejection_rebuild_moves
from feasible_moves import (
    LOCAL_NEIGHBORHOODS,
    collect_feasible_moves,
    iter_raw_local_moves,
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

from baselines.algorithm_prototypes.tailored_dp_vns_20260725.neighborhoods import (
    customer_multiset,
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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=list(row["node_sequence"]),
            )
            for row in payload["routes"]
        ],
        charging_actions=[
            ChargingAction(**row)
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row)
            for row in payload.get("cross_site_services", [])
        ],
    )


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    if registration.get("status") != "FROZEN_BEFORE_EXECUTION":
        raise RuntimeError("G0 registration is not frozen")
    for relative, expected in registration["source_hashes"].items():
        path = REPO / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"registered source drift: {relative}")
    for row in registration["inputs"]:
        path = REPO / row["witness_path"]
        if not path.is_file() or sha256(path) != row["witness_sha256"]:
            raise RuntimeError(f"registered witness drift: {path}")
    raw = registration["sealed_v7_raw_runs"]
    if sha256(REPO / raw["path"]) != raw["sha256"]:
        raise RuntimeError("sealed v7 raw_runs drift")
    authority = registration["authority_registration"]
    if sha256(REPO / authority["path"]) != authority["sha256"]:
        raise RuntimeError("authority registration drift")
    return registration


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
    for key, value in THREAD_ENV.items():
        os.environ[key] = value
    bundle = load_bundle(str(spec["instance_id"]))
    witness = read_json(REPO / spec["witness_path"])
    solution = load_solution(witness[str(spec["witness_key"])])
    objective, _, exact_violations = exact_china81_score(solution, bundle)
    direct_violations = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    if exact_violations or direct_violations:
        raise RuntimeError(
            f"{spec['instance_id']}: frozen starting solution infeasible"
        )
    if not math.isclose(
        objective,
        float(spec["expected_objective"]),
        rel_tol=0.0,
        abs_tol=TOL,
    ):
        raise RuntimeError(
            f"{spec['instance_id']}: frozen objective mismatch"
        )

    cache = RouteLocalDecoderCache()
    baseline = customer_multiset(solution, bundle)
    neighborhood_rows: dict[str, dict[str, Any]] = {}
    for neighborhood in LOCAL_NEIGHBORHOODS:
        collection = collect_feasible_moves(
            iter_raw_local_moves(
                solution,
                bundle,
                neighborhood=neighborhood,
                candidate_pool_limit=int(
                    config["inspection_limit_per_local_neighborhood"]
                ),
            ),
            bundle,
            baseline_customers=baseline,
            route_local_cache=cache,
            inspection_limit=int(
                config["inspection_limit_per_local_neighborhood"]
            ),
            feasible_limit=int(
                config["feasible_structures_per_neighborhood"]
            ),
        )
        neighborhood_rows[neighborhood] = {
            "raw_generated": collection.raw_generated,
            "raw_inspected": collection.raw_inspected,
            "feasible_structures": len(collection.moves),
            "infeasible_structures": collection.infeasible_structures,
            "inspection_limit_hit": collection.inspection_limit_hit,
            "signatures": [
                sha256_text(
                    json.dumps(
                        {
                            "detail": move.detail,
                            "route_local_cost": move.route_local_cost,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                for move in collection.moves
            ],
        }

    rebuild_moves, rebuild = generate_ejection_rebuild_moves(
        solution,
        bundle,
        route_local_cache=cache,
        block_widths=tuple(int(v) for v in config["block_widths"]),
        block_seed_limit=int(config["block_seed_limit"]),
        beam_width=int(config["rebuild_beam_width"]),
        nearest_anchor_count=int(config["nearest_anchor_count"]),
        feasible_limit=int(config["feasible_structures_per_neighborhood"]),
    )
    neighborhood_rows["ejection_rebuild"] = {
        **asdict(rebuild),
        "feasible_structures": len(rebuild_moves),
        "signatures": [
            sha256_text(
                json.dumps(
                    {
                        "detail": move.detail,
                        "route_local_cost": move.route_local_cost,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            for move in rebuild_moves
        ],
    }
    return {
        "instance_id": spec["instance_id"],
        "seed": spec["seed"],
        "task_id": spec["task_id"],
        "expected_objective": spec["expected_objective"],
        "replayed_objective": objective,
        "start_direct_violations": len(direct_violations),
        "start_exact_violations": len(exact_violations),
        "candidate_complete_objective_evaluations": 0,
        "neighborhoods": neighborhood_rows,
        "route_local_cache": cache.as_dict(),
    }


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def artifact_hashes() -> dict[str, str]:
    return {
        path.relative_to(OUTPUT).as_posix(): sha256(path)
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"G0 output already exists: {OUTPUT}")
    registration = verify_registration()
    OUTPUT.mkdir(parents=True)
    config = registration["config"]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=int(config["workers"]),
    ) as executor:
        futures = {
            executor.submit(run_one, spec, config): spec
            for spec in registration["inputs"]
        }
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["instance_id"])

    local_coverage = {
        name: sum(
            int(row["neighborhoods"][name]["feasible_structures"])
            for row in results
        )
        for name in LOCAL_NEIGHBORHOODS
    }
    rebuild_total = sum(
        int(row["neighborhoods"]["ejection_rebuild"]["feasible_structures"])
        for row in results
    )
    candidate_evaluations = sum(
        int(row["candidate_complete_objective_evaluations"])
        for row in results
    )
    replay_ok = all(
        math.isclose(
            float(row["expected_objective"]),
            float(row["replayed_objective"]),
            rel_tol=0.0,
            abs_tol=TOL,
        )
        and row["start_direct_violations"] == 0
        and row["start_exact_violations"] == 0
        for row in results
    )
    passed = bool(
        replay_ok
        and all(value > 0 for value in local_coverage.values())
        and rebuild_total > 0
        and candidate_evaluations == 0
    )
    verdict = (
        "PASS_FGE_VNS_G0_ZERO_OBJECTIVE_WIRING"
        if passed
        else "HALT_FGE_VNS_G0_WIRING_OR_FEASIBILITY"
    )

    metadata = {
        "schema": "resetp.fge-vns-g0-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "registration_path": REGISTRATION.relative_to(REPO).as_posix(),
        "registration_sha256": sha256(REGISTRATION),
        "candidate_complete_objective_evaluations": candidate_evaluations,
        "python": sys.version,
        "platform": platform.platform(),
        "thread_environment": THREAD_ENV,
    }
    write_json(OUTPUT / "metadata.json", metadata)
    with (OUTPUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        fieldnames = [
            "instance_id",
            "seed",
            "task_id",
            "expected_objective",
            "replayed_objective",
            "start_direct_violations",
            "start_exact_violations",
            "candidate_complete_objective_evaluations",
            *(
                f"{name}_feasible_structures"
                for name in (*LOCAL_NEIGHBORHOODS, "ejection_rebuild")
            ),
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(
                {
                    key: (
                        row["neighborhoods"][
                            key.removesuffix("_feasible_structures")
                        ]["feasible_structures"]
                        if key.endswith("_feasible_structures")
                        else row[key]
                    )
                    for key in fieldnames
                }
            )
    write_json(OUTPUT / "g0_details.json", results)
    decision = {
        "schema": "resetp.fge-vns-g0-decision.v1",
        "verdict": verdict,
        "passed": passed,
        "replay_ok": replay_ok,
        "local_feasible_structure_totals": local_coverage,
        "ejection_rebuild_feasible_structure_total": rebuild_total,
        "candidate_complete_objective_evaluations": candidate_evaluations,
        "next_step_authorized": (
            "FREEZE_AND_RUN_DIRECT_IMPROVEMENT_GATE"
            if passed
            else "NONE_STOP_CANDIDATE"
        ),
        "claim_boundary": registration["claim_boundary"],
    }
    write_json(OUTPUT / "decision.json", decision)
    report_lines = [
        "# FEASIBILITY-GUIDED-EJECTION-VNS G0",
        "",
        f"判定：`{verdict}`。",
        "",
        (
            "本门没有运行 HGS、MIP 或候选完整目标评价；"
            f"候选完整目标评价次数={candidate_evaluations}。"
        ),
        "",
        f"封存起点复算与零违约={replay_ok}。",
        (
            "四类局部邻域联合可行结构总数："
            + "，".join(
                f"{name}={value}"
                for name, value in local_coverage.items()
            )
            + "。"
        ),
        f"连续块弹出—束搜索完整可行结构总数={rebuild_total}。",
        "",
        (
            "边界：仅验证新算法能否在生成阶段交付联合可行结构；"
            "不证明性能、真混合、E3、BKS、SOTA 或论文结论。"
        ),
    ]
    (OUTPUT / "report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )
    write_json(OUTPUT / "artifact_hashes.json", artifact_hashes())
    print(verdict)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

