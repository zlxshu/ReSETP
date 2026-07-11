#!/usr/bin/env python3
"""Independent saved-solution verification for the refined-carbon short gate."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

from setp_solver.algorithms.resetp_alns.operators.strong_bridge import solution_signature_hash
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution


def _load_solution(path: Path) -> Solution:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(**row) for row in payload.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(**row) for row in payload.get("cross_site_services", [])],
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hash_artifacts(output_dir: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output_dir.resolve()
    rows = list(csv.DictReader((output / "raw_runs.csv").open(encoding="utf-8", newline="")))
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)
    checks: list[dict[str, Any]] = []
    for row in rows:
        bundle = load_search_bundle(root / "models/data_bundle/generated_instances/L-main" / row["instance"])
        solution = _load_solution(root / row["solution_path"])
        breakdown = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(solution, bundle.instance, prices)
        customer_nodes = {node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"}
        served = [node_id for route in solution.routes for node_id in route.node_sequence if node_id in customer_nodes]
        phase_budgets = json.loads(row["phase_budgets"])
        checks.append(
            {
                "instance": row["instance"],
                "seed": int(row["seed"]),
                "arm": row["arm"],
                "cost_match": abs(float(breakdown["total_cost"]) - float(row["total_cost"])) <= 1e-8,
                "ev_carbon_match": abs(float(breakdown["E_ev_indirect"]) - float(row["E_ev_indirect"])) <= 1e-8,
                "electricity_match": abs(float(breakdown["electricity_kwh"]) - float(row["electricity_kwh"])) <= 1e-8,
                "solution_hash_match": solution_signature_hash(solution) == row["solution_hash"],
                "zero_violation": len(violations) == 0,
                "full_budget": int(row["actual_evals"]) == int(row["eval_budget"]) == 400,
                "phase_budget_contract": phase_budgets == [40, 320, 40],
                "customer_coverage_exact": len(served) == len(set(served)) == len(customer_nodes),
            }
        )
    existing_hashes = json.loads((output / "artifact_hashes.json").read_text(encoding="utf-8"))
    hash_mismatches = [
        relative
        for relative, expected in existing_hashes.items()
        if not Path(relative).name.startswith("._")
        if not (output / relative).is_file()
        or hashlib.sha256((output / relative).read_bytes()).hexdigest() != expected
    ]
    all_clean = len(rows) == 12 and not hash_mismatches and all(
        all(bool(value) for key, value in check.items() if key not in {"instance", "seed", "arm"})
        for check in checks
    )
    verification = {
        "verdict": "REFINED_CARBON_SHORT_GATE_VERIFIED" if all_clean else "HALT_REFINED_CARBON_SHORT_GATE_VERIFICATION",
        "row_count": len(rows),
        "hash_mismatches_before_verification": hash_mismatches,
        "all_saved_solutions_recomputed_clean": all_clean,
        "checks": checks,
    }
    _write_json(output / "verification.json", verification)
    _write_json(output / "artifact_hashes.json", _hash_artifacts(output))
    print(json.dumps({key: value for key, value in verification.items() if key != "checks"}, ensure_ascii=False, sort_keys=True))
    if not all_clean:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
