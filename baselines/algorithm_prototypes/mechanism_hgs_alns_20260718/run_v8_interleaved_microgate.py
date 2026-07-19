#!/usr/bin/env python3
"""Three-task one-seed gate for in-search mechanism education."""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
for path in (REPO / "solver/src", REPO / "models/src", HERE, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prototype import independent_cost  # noqa: E402
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from v7_responsibility_solver import run_mechanism_alns_v7  # noqa: E402
from v8_interleaved_mechanism_solver import (  # noqa: E402
    run_mechanism_alns_v8_interleaved,
)


OUT = HERE / "mechanism_v8_interleaved_microgate"
BUNDLES = (
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
)
INSTANCES = (
    "L-main-threeshift-20c-01",
    "L-main-threeshift-25c-01",
    "L-main-threeshift-50c-01",
)
SEED = 1
BUDGET = 100
CHUNK = 20
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
TOL = 1e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def solution_hash(solution: Any) -> str:
    payload = {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [
            asdict(service) for service in solution.cross_site_services
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def row(instance: str, result: Any) -> dict[str, Any]:
    bundle = BUNDLES / instance
    loaded = load_search_bundle(bundle)
    recomputed = independent_cost(bundle, result.best_solution, PRICES)
    violations = check_solution(result.best_solution, loaded.instance, PRICES)
    return {
        "instance": instance,
        "seed": SEED,
        "algorithm": result.algorithm,
        "budget": BUDGET,
        "evaluations": int(result.evaluations),
        "cost": float(result.best_cost),
        "recomputed_cost": float(recomputed),
        "cost_match": abs(float(result.best_cost) - recomputed) <= 1e-7,
        "feasible": bool(result.feasible and not violations),
        "violation_count": len(violations),
        "elapsed_seconds": float(result.elapsed_seconds),
        "solution_sha256": solution_hash(result.best_solution),
        "mechanism_activity": json.dumps(
            result.mechanism_activity,
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def main() -> int:
    rows = []
    comparisons = []
    for instance in INSTANCES:
        bundle = BUNDLES / instance
        baseline = run_mechanism_alns_v7(
            bundle,
            seed=SEED,
            eval_budget=BUDGET,
            prices=PRICES,
        )
        candidate = run_mechanism_alns_v8_interleaved(
            bundle,
            seed=SEED,
            eval_budget=BUDGET,
            prices=PRICES,
            chunk_budget=CHUNK,
        )
        baseline_row = row(instance, baseline)
        candidate_row = row(instance, candidate)
        rows.extend((baseline_row, candidate_row))
        delta = candidate_row["recomputed_cost"] - baseline_row["recomputed_cost"]
        activity = candidate.mechanism_activity
        comparisons.append(
            {
                "instance": instance,
                "baseline_v7_cost": baseline_row["recomputed_cost"],
                "candidate_v8_cost": candidate_row["recomputed_cost"],
                "candidate_minus_baseline": delta,
                "strict_win": delta < -TOL,
                "nonloss": delta <= TOL,
                "mechanism_improvements": int(
                    activity["joint_improvement_count"]
                    + activity["carbon_improvement_count"]
                ),
            }
        )
    failures = [
        f"{item['instance']}:{item['algorithm']}"
        for item in rows
        if not item["feasible"]
        or not item["cost_match"]
        or int(item["evaluations"]) != BUDGET
    ]
    wins = sum(item["strict_win"] for item in comparisons)
    nonloss = sum(item["nonloss"] for item in comparisons)
    active = sum(item["mechanism_improvements"] > 0 for item in comparisons)
    strong = not failures and wins >= 2 and nonloss == 3 and active >= 2
    decision = {
        "verdict": (
            "GO_V8_THREE_SEED_DEVELOPMENT"
            if strong
            else "STOP_INTERLEAVED_MECHANISM_EDUCATION"
        ),
        "strong_positive": strong,
        "strict_win_count": wins,
        "nonloss_count": nonloss,
        "mechanism_active_instance_count": active,
        "failure_tasks": failures,
        "predeclared_gate": {
            "strict_wins_minimum": 2,
            "nonloss_required": 3,
            "active_instances_minimum": 2,
        },
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.mechanism-v8-interleaved-microgate.v1",
        "instances": list(INSTANCES),
        "seed": SEED,
        "complete_route_evaluation_budget": BUDGET,
        "chunk_budget": CHUNK,
        "battery_kwh": 280.0,
        "claim_boundary": (
            "One-seed development microgate only. It tests whether repeated "
            "mechanism education is worth a three-seed development follow-up."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(OUT / "raw_runs.csv", buffer.getvalue())
    atomic_json(OUT / "comparisons.json", comparisons)
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(
        OUT / "report.md",
        "# 搜索中机制教育最小门\n\n"
        f"结论：`{decision['verdict']}`。严格胜 {wins}/3，"
        f"不退步 {nonloss}/3，机制真实改善 {active}/3。\n\n"
        "本门只比较“搜完再修”与“边搜边修”，不授权正式试验。\n",
    )
    hashes = {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    atomic_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
