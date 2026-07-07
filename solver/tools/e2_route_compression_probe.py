from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from setp_solver.cost import evaluate
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.alns_crush import low_utilization_route_elimination_probe
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.winner_operators import WinnerKernelConfig, run_winner_kernel, run_winner_kernel_plus_route_elimination
from setp_solver.solution import Solution


DEFAULT_BUNDLES = [
    Path("models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-01"),
    Path("models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-02"),
    Path("models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-200c-01"),
]
DEFAULT_OUTPUT_DIR = Path("solver/reports/e2_route_compression_probe_20260707")


def solution_row(
    *,
    bundle_id: str,
    algorithm: str,
    seed: int,
    solution: Solution,
    carbon_profile: list[dict[str, Any]],
    instance: Any,
    eval_budget: int,
    evaluations: int | None = None,
    elapsed_seconds: float | None = None,
    probe_attempts: int | None = None,
    accepted_merges: int | None = None,
) -> dict[str, Any]:
    metrics = evaluate(solution, instance, carbon_profile, DEFAULT_PRICES)
    violations = check_solution(solution, instance, DEFAULT_PRICES)
    return {
        "bundle": bundle_id,
        "seed": int(seed),
        "algorithm": algorithm,
        "eval_budget": int(eval_budget),
        "evaluations": "" if evaluations is None else int(evaluations),
        "elapsed_seconds": "" if elapsed_seconds is None else float(elapsed_seconds),
        "best_cost": float(metrics["total_cost"]),
        "route_count": len(solution.routes),
        "fixed_cost": float(metrics.get("cost_fix", 0.0)),
        "ev_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "cv_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
        "violation_count": len(violations),
        "feasible": len(violations) == 0,
        "probe_attempts": "" if probe_attempts is None else int(probe_attempts),
        "accepted_merges": "" if accepted_merges is None else int(accepted_merges),
        "route_count_delta_vs_winner": "",
        "fixed_cost_delta_vs_winner": "",
        "objective_delta_vs_winner": "",
        "gap_vs_lns_delta_pp": "",
    }


def annotate_vs_winner(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    winners: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if row["algorithm"] == "winner_kernel":
            winners[(str(row["bundle"]), int(row["seed"]))] = row
    annotated: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        winner = winners.get((str(row["bundle"]), int(row["seed"])))
        if winner is not None and row["algorithm"] != "winner_kernel":
            out["route_count_delta_vs_winner"] = int(row["route_count"]) - int(winner["route_count"])
            out["fixed_cost_delta_vs_winner"] = float(row["fixed_cost"]) - float(winner["fixed_cost"])
            out["objective_delta_vs_winner"] = float(row["best_cost"]) - float(winner["best_cost"])
        annotated.append(out)
    return annotated


def probe_bundle(bundle_dir: Path, *, seed: int, eval_budget: int, max_runtime_seconds: float) -> list[dict[str, Any]]:
    bundle = load_search_bundle(bundle_dir)
    bundle_id = bundle_dir.name
    warm = make_shared_initial_solution(bundle)
    rows = [
        solution_row(
            bundle_id=bundle_id,
            algorithm="shared_initial_solution",
            seed=seed,
            solution=warm,
            carbon_profile=bundle.carbon_profile,
            instance=bundle.instance,
            eval_budget=0,
        )
    ]
    headroom = low_utilization_route_elimination_probe(
        warm,
        bundle.instance,
        bundle.carbon_profile,
        max_seconds=min(30.0, max(5.0, max_runtime_seconds / 2.0)),
    )
    rows.append(
        solution_row(
            bundle_id=bundle_id,
            algorithm="low_utilization_route_elimination_probe",
            seed=seed,
            solution=headroom.best_solution,
            carbon_profile=bundle.carbon_profile,
            instance=bundle.instance,
            eval_budget=0,
            probe_attempts=headroom.attempts,
            accepted_merges=headroom.accepted_merges,
        )
    )
    config = WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds)
    winner = run_winner_kernel(bundle_dir, config=config, initial_solution=warm)
    rows.append(
        solution_row(
            bundle_id=bundle_id,
            algorithm="winner_kernel",
            seed=seed,
            solution=winner["best_solution"],
            carbon_profile=bundle.carbon_profile,
            instance=bundle.instance,
            eval_budget=eval_budget,
            evaluations=int(winner["evaluations"]),
            elapsed_seconds=float(winner["elapsed_seconds"]),
        )
    )
    route_elim = run_winner_kernel_plus_route_elimination(bundle_dir, config=config, initial_solution=warm)
    rows.append(
        solution_row(
            bundle_id=bundle_id,
            algorithm="winner_kernel_plus_route_elimination",
            seed=seed,
            solution=route_elim["best_solution"],
            carbon_profile=bundle.carbon_profile,
            instance=bundle.instance,
            eval_budget=eval_budget,
            evaluations=int(route_elim["evaluations"]),
            elapsed_seconds=float(route_elim["elapsed_seconds"]),
        )
    )
    return annotate_vs_winner(rows)


def decision_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    route_rows = [row for row in rows if row["algorithm"] == "winner_kernel_plus_route_elimination"]
    regressions = [row for row in route_rows if _float(row["objective_delta_vs_winner"]) > max(1e-9, abs(_winner_cost(rows, row)) * 0.005)]
    improved = [
        row
        for row in route_rows
        if bool(row["feasible"])
        and row not in regressions
        and (
            _float(row["objective_delta_vs_winner"]) < -1e-9
            or _float(row["fixed_cost_delta_vs_winner"]) < -1e-9
            or _float(row["route_count_delta_vs_winner"]) < 0
        )
    ]
    if regressions:
        status = "ROUTE_COMPRESSION_INTEGRATION_REGRESSED"
    elif improved:
        status = "ROUTE_COMPRESSION_SIGNAL_FOUND"
    else:
        status = "ROUTE_COMPRESSION_NO_SHORT_BUDGET_SIGNAL"
    return {
        "status": status,
        "row_count": len(rows),
        "route_elimination_rows": len(route_rows),
        "improved_rows": len(improved),
        "regression_rows_over_0_5pct": len(regressions),
        "lns_reference_available": False,
        "requires_code_fix": bool(regressions) or not bool(improved),
    }


def write_outputs(rows: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with (output_dir / "compression_probe_rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    decision = decision_from_rows(rows)
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    report = [
        "# E2 Route Compression Probe",
        "",
        f"Verdict: {decision['status']}",
        f"Rows: {len(rows)}",
        f"Route-elimination improved rows: {decision['improved_rows']}/{decision['route_elimination_rows']}",
        f"Regressions over 0.5%: {decision['regression_rows_over_0_5pct']}",
        "LNS reference available: false",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    hashes = {}
    for name in ("compression_probe_rows.csv", "decision.json", "report.md"):
        hashes[name] = hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
    (output_dir / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")


def _float(value: Any) -> float:
    try:
        if value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _winner_cost(rows: list[dict[str, Any]], row: dict[str, Any]) -> float:
    for candidate in rows:
        if candidate["algorithm"] == "winner_kernel" and candidate["bundle"] == row["bundle"] and int(candidate["seed"]) == int(row["seed"]):
            return float(candidate["best_cost"])
    return float(row["best_cost"])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe E2 route-compression headroom on documented exceptions.")
    parser.add_argument("--bundle", action="append", dest="bundles", default=[])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--eval-budget", type=int, default=800)
    parser.add_argument("--max-runtime-seconds", type=float, default=120.0)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bundles = [Path(item) for item in args.bundles] if args.bundles else DEFAULT_BUNDLES
    rows: list[dict[str, Any]] = []
    for bundle_dir in bundles:
        rows.extend(probe_bundle(bundle_dir, seed=int(args.seed), eval_budget=int(args.eval_budget), max_runtime_seconds=float(args.max_runtime_seconds)))
    rows = annotate_vs_winner(rows)
    write_outputs(rows, Path(args.output_dir))
    print(json.dumps(decision_from_rows(rows), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
