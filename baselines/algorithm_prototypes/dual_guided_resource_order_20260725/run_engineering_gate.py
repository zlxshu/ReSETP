#!/usr/bin/env python3
"""Six-process, zero-candidate-objective engineering and resource gate."""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from candidate_core import generate_pair_candidates, select_route_pairs
from common import (
    ENGINEERING,
    artifact_hashes,
    load_bundle,
    load_registered_solutions,
    memory_snapshot,
    peak_rss_bytes,
    set_single_thread_environment,
    sha256,
    verify_registration,
    write_csv,
    write_json,
)


def run_one(spec: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    set_single_thread_environment()
    bundle = load_bundle(spec["instance_id"])
    start, parents = load_registered_solutions(spec)
    ranked, duals, columns = select_route_pairs(start, parents, bundle)
    total_states = 0
    candidate_count = 0
    pair_rows = []
    for first, second, pressure in ranked:
        candidates, expanded = generate_pair_candidates(
            start,
            (first, second),
            bundle,
            k=int(config["k"]),
            top_per_direction=int(config["top_candidates_per_direction"]),
            state_limit=int(config["max_dp_states_per_instance"]) - total_states,
        )
        total_states += expanded
        candidate_count += len(candidates)
        pair_rows.append(
            {
                "first": first,
                "second": second,
                "pressure": pressure,
                "candidate_count": len(candidates),
                "states": expanded,
            }
        )
    if len(ranked) != int(config["route_pair_limit"]):
        raise RuntimeError("route-pair selector did not return two pairs")
    if candidate_count < 1 or candidate_count > int(
        config["max_complete_evaluations_per_instance"]
    ):
        raise RuntimeError(f"invalid distinct candidate count: {candidate_count}")
    if total_states > int(config["max_dp_states_per_instance"]):
        raise RuntimeError("DP state cap exceeded")
    return {
        "instance_id": spec["instance_id"],
        "status": "PASS",
        "route_pool_columns": len(columns),
        "lp_primal_residual": duals.primal_residual,
        "lp_stationarity_residual": duals.stationarity_residual,
        "positive_scarcity_resources": sum(
            resource.scarcity > 0.0 for resource in duals.resources
        ),
        "candidate_count": candidate_count,
        "dp_states": total_states,
        "pairs_json": json.dumps(pair_rows, sort_keys=True),
        "peak_rss_bytes": peak_rss_bytes(),
        "error": "",
    }


def main() -> int:
    if ENGINEERING.exists():
        raise RuntimeError(f"engineering output exists: {ENGINEERING}")
    ENGINEERING.mkdir(parents=True)
    registration = verify_registration()
    config = registration["config"]
    before = memory_snapshot()
    write_json(
        ENGINEERING / "metadata.json",
        {
            "schema": "resetp.dual-guided-resource-order-engineering.v1",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "workers": int(config["workers"]),
            "candidate_objectives_evaluated": 0,
            "memory_before": before,
            "registration_sha256": sha256(
                Path(__file__).resolve().parent / "g0_registration_v1.json"
            ),
        },
    )
    rows = []
    failures = []
    with ProcessPoolExecutor(max_workers=int(config["workers"])) as pool:
        futures = {
            pool.submit(run_one, spec, config): spec
            for spec in registration["inputs"]
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
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
    write_csv(ENGINEERING / "raw_runs.csv", rows)
    ok = [row for row in rows if row["status"] == "PASS"]
    projected_peak = sum(int(row["peak_rss_bytes"]) for row in ok)
    passed = bool(
        not failures
        and len(ok) == len(registration["inputs"])
        and before["available_percent"]
        >= float(config["minimum_available_memory_percent"])
        and projected_peak
        <= int(config["maximum_projected_peak_rss_bytes"])
    )
    verdict = (
        "PASS_ZERO_OBJECTIVE_ENGINEERING_AND_SIX_WORKER_RESOURCE_GATE"
        if passed
        else "HALT_ZERO_OBJECTIVE_ENGINEERING_OR_RESOURCE_GATE"
    )
    decision = {
        "schema": "resetp.dual-guided-resource-order-engineering-decision.v1",
        "verdict": verdict,
        "pass": passed,
        "candidate_objectives_evaluated": 0,
        "workers": int(config["workers"]),
        "rows": len(ok),
        "expected_rows": len(registration["inputs"]),
        "available_memory_percent_before": before["available_percent"],
        "projected_combined_peak_rss_bytes": projected_peak,
        "failures": failures,
        "next_step": "RUN_FROZEN_G0_ONCE" if passed else "STOP_NO_RESCUE",
    }
    write_json(ENGINEERING / "decision.json", decision)
    (ENGINEERING / "report.md").write_text(
        "# Zero-objective engineering gate\n\n"
        f"Verdict: `{verdict}`\n\n"
        f"Candidate objectives evaluated: 0. Workers: {config['workers']}. "
        f"Projected combined peak RSS: {projected_peak / 2**20:.1f} MiB. "
        f"Available memory before launch: {before['available_percent']:.1f}%.\n",
        encoding="utf-8",
    )
    write_json(ENGINEERING / "artifact_hashes.json", artifact_hashes(ENGINEERING))
    write_json(
        ENGINEERING / "done.json",
        {
            "verdict": verdict,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

