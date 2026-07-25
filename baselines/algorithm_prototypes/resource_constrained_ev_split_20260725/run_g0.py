#!/usr/bin/env python3
"""Execute the zero-search RC-EV-Split engineering gate."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
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
FAILED_PACKAGE = (
    REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
)
REGISTRATION = PACKAGE / "g0_registration_v1.json"
OUTPUT = PACKAGE / "g0_gate_v1"
RUN_VERSION = os.environ.get("RC_EV_SPLIT_G0_VERSION", "v2")
REGISTRATION = PACKAGE / f"g0_registration_{RUN_VERSION}.json"
OUTPUT = PACKAGE / f"g0_gate_{RUN_VERSION}"
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

from china81_adapter import customer_order, decode_customer_order
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
    for key, value in THREAD_ENV.items():
        os.environ[key] = value
    started = time.perf_counter()
    bundle = load_bundle(str(spec["instance_id"]))
    witness = read_json(REPO / spec["witness_path"])
    incumbent = load_solution(witness[spec["witness_key"]])
    before, _, before_violations = exact_china81_score(
        incumbent,
        bundle,
    )
    if before_violations or check_solution(
        incumbent,
        bundle.instance,
        bundle.prices,
    ):
        raise RuntimeError("sealed incumbent failed direct replay")
    if not math.isclose(
        before,
        float(spec["expected_objective"]),
        rel_tol=0.0,
        abs_tol=TOL,
    ):
        raise RuntimeError("sealed incumbent objective drift")

    order = customer_order(incumbent, bundle)
    decoded = decode_customer_order(
        order,
        bundle,
        incumbent=incumbent,
        max_labels_per_position=int(
            config["max_labels_per_position"]
        ),
        max_generated_labels=int(config["max_generated_labels"]),
    )
    after, _, after_violations = exact_china81_score(
        decoded.solution,
        bundle,
    )
    if after_violations or check_solution(
        decoded.solution,
        bundle.instance,
        bundle.prices,
    ):
        raise RuntimeError("decoded solution failed independent replay")
    if not math.isclose(
        after,
        decoded.objective,
        rel_tol=0.0,
        abs_tol=TOL,
    ):
        raise RuntimeError("decoded objective replay drift")
    if after > before + TOL:
        raise RuntimeError("split lost the injected incumbent path")
    if decoded.non_incumbent_option_count < 1:
        raise RuntimeError("no non-incumbent segment option generated")

    rss_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = (
        int(rss_raw)
        if sys.platform == "darwin"
        else int(rss_raw) * 1024
    )
    witness_out = OUTPUT / "witnesses" / f"{spec['instance_id']}.json"
    write_json(
        witness_out,
        {
            "schema": "resetp.rc-ev-split-witness.v1",
            "instance_id": spec["instance_id"],
            "routes": [asdict(row) for row in decoded.solution.routes],
            "charging_actions": [
                asdict(row)
                for row in decoded.solution.charging_actions
            ],
            "cross_site_services": [
                asdict(row)
                for row in decoded.solution.cross_site_services
            ],
        },
    )
    return {
        "instance_id": spec["instance_id"],
        "seed": spec["seed"],
        "status": "OK",
        "customer_count": len(order),
        "incumbent_objective": before,
        "decoded_objective": after,
        "engineering_delta": after - before,
        "generated_segment_count": decoded.generated_segment_count,
        "generated_option_count": decoded.generated_option_count,
        "incumbent_option_count": decoded.incumbent_option_count,
        "non_incumbent_option_count": (
            decoded.non_incumbent_option_count
        ),
        "route_count": len(decoded.solution.routes),
        "generated_labels": decoded.split.generated_labels,
        "dominated_labels": decoded.split.dominated_labels,
        "duplicate_labels": decoded.split.duplicate_labels,
        "max_labels_at_position": max(
            decoded.split.labels_by_position
        ),
        "labels_by_position": json.dumps(
            decoded.split.labels_by_position
        ),
        "route_local_sum": decoded.route_local_sum,
        "exact_minus_route_local": (
            decoded.exact_minus_route_local
        ),
        "candidate_complete_objective_evaluations": 0,
        "validation_objective_replays": 2,
        "wall_seconds": time.perf_counter() - started,
        "peak_rss_bytes": peak_rss_bytes,
        "witness_path": witness_out.relative_to(REPO).as_posix(),
    }


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    if registration.get("status") != "FROZEN_BEFORE_EXECUTION":
        raise RuntimeError("registration is not frozen")
    for relative, expected in registration["source_hashes"].items():
        if sha256(REPO / relative) != expected:
            raise RuntimeError(f"registered source drift: {relative}")
    for spec in registration["inputs"]:
        if sha256(REPO / spec["witness_path"]) != spec["witness_sha256"]:
            raise RuntimeError(
                f"registered witness drift: {spec['instance_id']}"
            )
    raw = registration["sealed_v7_raw_runs"]
    if sha256(REPO / raw["path"]) != raw["sha256"]:
        raise RuntimeError("sealed v7 raw_runs drift")
    authority = registration["authority_registration"]
    if sha256(REPO / authority["path"]) != authority["sha256"]:
        raise RuntimeError("bundle authority drift")
    return registration


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def clean_appledouble(root: Path) -> int:
    removed = 0
    for path in root.rglob("._*"):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def artifact_hashes(root: Path) -> dict[str, str]:
    excluded = {"__pycache__", ".pytest_cache", ".tasks"}
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.name.startswith("._")
        and not any(part in excluded for part in path.parts)
        and path.name != "artifact_hashes.json"
    }


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"G0 output already exists: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    registration = verify_registration()
    config = registration["config"]
    write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.rc-ev-split-g0-metadata.v1",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "registration_sha256": sha256(REGISTRATION),
            "python": sys.version,
            "platform": platform.platform(),
            "config": config,
            "claim_boundary": registration["claim_boundary"],
        },
    )
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    with ProcessPoolExecutor(
        max_workers=min(
            int(config["workers"]),
            len(registration["inputs"]),
        )
    ) as pool:
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
    max_rss = max(
        (int(row["peak_rss_bytes"]) for row in rows),
        default=0,
    )
    passed = (
        not failures
        and len(rows) == len(registration["inputs"])
        and all(row["status"] == "OK" for row in rows)
        and all(
            int(row["candidate_complete_objective_evaluations"]) == 0
            for row in rows
        )
        and all(
            int(row["non_incumbent_option_count"]) > 0
            for row in rows
        )
        and all(
            int(row["max_labels_at_position"])
            <= int(config["max_labels_per_position"])
            for row in rows
        )
        and all(
            int(row["generated_labels"])
            <= int(config["max_generated_labels"])
            for row in rows
        )
        and max_rss
        <= float(config["max_peak_rss_gib"]) * 1024**3
    )
    verdict = (
        "PASS_RC_EV_SPLIT_G0_ENGINEERING"
        if passed
        else "HALT_RC_EV_SPLIT_G0_STRUCTURE_OR_SCALE"
    )
    decision = {
        "schema": "resetp.rc-ev-split-g0-decision.v1",
        "verdict": verdict,
        "pass": passed,
        "rows": len(rows),
        "expected_rows": len(registration["inputs"]),
        "failures": failures,
        "candidate_complete_objective_evaluations": sum(
            int(row["candidate_complete_objective_evaluations"])
            for row in rows
        ),
        "max_peak_rss_bytes": max_rss,
        "max_generated_labels": max(
            (int(row["generated_labels"]) for row in rows),
            default=0,
        ),
        "max_labels_at_position": max(
            (int(row["max_labels_at_position"]) for row in rows),
            default=0,
        ),
        "next_step": (
            "REGISTER_FRESH_DIRECT_EFFECT_GATE"
            if passed
            else "NONE"
        ),
        "claim_boundary": registration["claim_boundary"],
    }
    write_json(OUTPUT / "decision.json", decision)
    report = [
        "# RC-EV-Split G0 engineering gate",
        "",
        f"Verdict: `{verdict}`",
        "",
        (
            "This is a zero-search engineering and scale gate. It is not "
            "algorithm-performance evidence."
        ),
        "",
        "## Rows",
        "",
        "| instance | n | segments | options | labels | max labels/position | wall s | peak MiB |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    report.extend(
        (
            f"| {row['instance_id']} | {row['customer_count']} | "
            f"{row['generated_segment_count']} | "
            f"{row['generated_option_count']} | "
            f"{row['generated_labels']} | "
            f"{row['max_labels_at_position']} | "
            f"{float(row['wall_seconds']):.3f} | "
            f"{int(row['peak_rss_bytes']) / 1024**2:.1f} |"
        )
        for row in rows
    )
    if failures:
        report.extend(["", "## Failures", "", *failures])
    (OUTPUT / "report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )
    clean_appledouble(OUTPUT)
    write_json(
        OUTPUT / "artifact_hashes.json",
        artifact_hashes(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
