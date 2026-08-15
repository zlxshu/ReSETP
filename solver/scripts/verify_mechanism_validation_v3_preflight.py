#!/usr/bin/env python3
"""Replay the frozen preflight witness without search and persist hard checks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path


PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).parents[2])
    parser.add_argument("--preflight-raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve()
    from run_public_v2_28_clean_ruler import _prepare_independent_imports

    _prepare_independent_imports()
    from run_problem_hgs_private_technical import _build_context
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
    from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS

    bundle, initial, _pi0, context = _build_context(
        repo,
        "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS",
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    evaluation = DutyFullEvaluator(context).evaluate(initial)
    customers = {
        customer
        for duty in initial.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    customer_nodes = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served_demand = sum(float(customer_nodes[item].demand) for item in customers)
    total_demand = sum(float(node.demand) for node in customer_nodes.values())
    with args.preflight_raw.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError("preflight raw must contain exactly one run")
    search_cost = float(rows[0]["total_cost"])
    payload = {
        "schema": "resetp.mechanism-validation-v3.preflight-truth-replay.v1",
        "run_kind": "no_search_exact_replay",
        "search_evaluations": 0,
        "instance_id": bundle.instance_id,
        "full_evaluation_feasible": bool(evaluation.feasible),
        "hard_violation_count": len(evaluation.violations),
        "hard_violations": [asdict(item) for item in evaluation.violations],
        "customers_served": len(customers),
        "customers_total": len(customer_nodes),
        "demand_served": served_demand,
        "demand_total": total_demand,
        "demand_completion_ratio": served_demand / total_demand,
        "replayed_total_cost": float(evaluation.total_cost),
        "preflight_final_total_cost": search_cost,
        "preflight_cost_matches_replayed_witness": abs(
            search_cost - float(evaluation.total_cost)
        ) <= 1.0e-9,
        "protected_file_hashes": {
            path: _sha256(repo / path) for path in PROTECTED
        },
    }
    if not payload["full_evaluation_feasible"]:
        raise RuntimeError("frozen preflight witness is not fully feasible")
    if len(customers) != len(customer_nodes) or served_demand != total_demand:
        raise RuntimeError("frozen preflight witness does not serve all demand")
    if not payload["preflight_cost_matches_replayed_witness"]:
        raise RuntimeError("preflight final cost differs from the replayed witness")
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
