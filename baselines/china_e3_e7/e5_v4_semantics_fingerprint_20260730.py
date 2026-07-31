#!/usr/bin/env python3
"""Emit a deterministic E5 search-semantics fingerprint.

This helper runs the same search call used by the E5 runner and atomically
persists the full final solution plus a projection of the evaluation trace
that excludes diagnostic-only exception fields.  It is used once before and
once after adding exception diagnostics to ``epochal_hgs.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_e5_nonlinear_v2_20260730 as base

DIAGNOSTIC_KEYS = {
    "exception_type",
    "exception_message",
    "failure_category",
}


def semantic_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in row.items() if key not in DIAGNOSTIC_KEYS}
        for row in trace
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--complete-eval-budget", required=True, type=int)
    parser.add_argument(
        "--arm",
        choices=base.ARMS,
        default="L100_control",
    )
    args = parser.parse_args()

    for name, value in base.REQUIRED_THREAD_ENV.items():
        os.environ[name] = value

    instance_id = base.PROBE_INSTANCE
    seed = base.PROBE_SEED
    base_bundle = base.load_china81_bundle(base.REPO, instance_id)
    bundle = base.curve_bundle(base_bundle, args.arm)
    initial = base.load_initial(instance_id)
    archives = base.archive_limits(args.complete_eval_budget)
    run = base.run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=base.EXACT_ELITES_PER_VIEW,
        max_archive_candidates_per_view=archives,
        sp_time_limit_seconds=base.MIP_TIME_LIMIT_SECONDS,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=base.MAX_HGS_ITERATIONS_PER_VIEW,
        wallclock_safety_seconds_per_view=900.0,
        exact_checkpoint_interval_iterations=None,
        preserve_base_pool_recombination=False,
    )
    trace = semantic_trace(
        list(run.stats["complete_candidate_evaluation_trace"])
    )
    solution = base.solution_payload(run.solution)
    semantic_payload = {
        "instance_id": instance_id,
        "seed": seed,
        "arm": args.arm,
        "complete_candidate_budget_cap": args.complete_eval_budget,
        "archive_candidates_per_view": archives,
        "solution": solution,
        "solution_sha256": base.payload_sha256(solution),
        "completion_objective": float(run.completion.objective),
        "parent_completion_objective": float(run.parent_completion.objective),
        "complete_candidate_evaluation_attempts": int(
            run.stats["complete_candidate_evaluation_attempts"]
        ),
        "semantic_evaluation_trace": trace,
        "semantic_evaluation_trace_sha256": base.payload_sha256(trace),
        "last_strict_improvement_evaluation": int(
            run.stats["last_strict_improvement_evaluation"]
        ),
    }
    payload = {
        "schema_version": "E5-SEARCH-SEMANTICS-FINGERPRINT-v1",
        "label": args.label,
        "epochal_hgs_sha256": base.file_sha256(
            base.PROTOTYPE / "epochal_hgs.py"
        ),
        "route_pool_sp_sha256": base.file_sha256(
            base.PROTOTYPE / "route_pool_sp.py"
        ),
        "semantic_payload": semantic_payload,
        "semantic_payload_sha256": base.payload_sha256(semantic_payload),
    }
    base.atomic_json(args.output.resolve(), payload)
    print(
        "SEMANTICS_FINGERPRINT_COMPLETE "
        f"label={args.label} "
        f"solution_sha256={semantic_payload['solution_sha256']} "
        f"semantic_payload_sha256={payload['semantic_payload_sha256']} "
        f"output={args.output.resolve()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
