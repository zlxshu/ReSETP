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
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.metaheuristic_baselines import BaselineRunResult, run_metaheuristic_baseline
from setp_solver.search.winner_operators import WinnerKernelConfig, run_winner_kernel, run_winner_kernel_plus_route_elimination
from setp_solver.search.winner_operators import _run_winner_variant, winner_variant_flags
from setp_solver.solution import Solution


DEFAULT_BUNDLES = [
    Path("models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-01"),
    Path("models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-100c-02"),
    Path("models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-200c-01"),
]
DEFAULT_OUTPUT_DIR = Path("solver/reports/e2_route_compression_probe_20260707")
MATRIX_PROFILES = (
    "winner_kernel",
    "winner_kernel_local_search",
    "winner_kernel_route_elimination",
    "winner_kernel_route_elimination_local_search",
    "winner_kernel_scan_rebuild",
    "winner_kernel_route_elimination_scan_rebuild",
    "winner_kernel_scan_rebuild_local_search",
    "winner_kernel_route_elimination_scan_rebuild_local_search",
)


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
    best_update_count: int | None = None,
    unique_solution_count: int | None = None,
    profile_flags: dict[str, str] | None = None,
) -> dict[str, Any]:
    metrics = evaluate(solution, instance, carbon_profile, DEFAULT_PRICES)
    violations = check_solution(solution, instance, DEFAULT_PRICES)
    route_count = len(solution.routes)
    ev_routes = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
    cv_routes = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv")
    return {
        "bundle": bundle_id,
        "seed": int(seed),
        "algorithm": algorithm,
        "eval_budget": int(eval_budget),
        "evaluations": "" if evaluations is None else int(evaluations),
        "elapsed_seconds": "" if elapsed_seconds is None else float(elapsed_seconds),
        "best_cost": float(metrics["total_cost"]),
        "route_count": route_count,
        "fixed_cost": float(metrics.get("cost_fix", 0.0)),
        "ev_routes": ev_routes,
        "cv_routes": cv_routes,
        "ev_route_share": (ev_routes / route_count) if route_count else 0.0,
        "cv_route_share": (cv_routes / route_count) if route_count else 0.0,
        "violation_count": len(violations),
        "feasible": len(violations) == 0,
        "zero_violations": len(violations) == 0,
        "probe_attempts": "" if probe_attempts is None else int(probe_attempts),
        "accepted_merges": "" if accepted_merges is None else int(accepted_merges),
        "best_update_count": "" if best_update_count is None else int(best_update_count),
        "unique_solution_count": "" if unique_solution_count is None else int(unique_solution_count),
        "profile_flags_json": "" if profile_flags is None else json.dumps(profile_flags, sort_keys=True, separators=(",", ":")),
        "route_count_delta_vs_winner": "",
        "fixed_cost_delta_vs_winner": "",
        "objective_delta_vs_winner": "",
        "winner_gap_vs_lns_pp": "",
        "profile_gap_vs_lns_pp": "",
        "gap_improvement_vs_winner_pp": "",
        "gap_vs_lns_delta_pp": "",
    }


def winner_profile_flags(
    *,
    include_route_elimination: bool,
    local_search: bool,
    scan_rebuild: bool,
) -> dict[str, str]:
    flags = winner_variant_flags(include_route_elimination=bool(include_route_elimination))
    flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1" if bool(local_search) else "0"
    flags["SETP_ALNS_CRUSH_SCAN_RESTART"] = "1" if bool(scan_rebuild) else "0"
    flags["SETP_ALNS_CRUSH_SCAN_REBUILD"] = "1" if bool(scan_rebuild) else "0"
    return flags


def annotate_vs_winner(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    winners: dict[tuple[str, int], dict[str, Any]] = {}
    lns_refs: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if row["algorithm"] == "winner_kernel":
            winners[(str(row["bundle"]), int(row["seed"]))] = row
        if row["algorithm"] == "lns_reference":
            lns_refs[(str(row["bundle"]), int(row["seed"]))] = row
    annotated: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        key = (str(row["bundle"]), int(row["seed"]))
        winner = winners.get(key)
        if winner is not None and row["algorithm"] != "winner_kernel":
            out["route_count_delta_vs_winner"] = int(row["route_count"]) - int(winner["route_count"])
            out["fixed_cost_delta_vs_winner"] = float(row["fixed_cost"]) - float(winner["fixed_cost"])
            out["objective_delta_vs_winner"] = float(row["best_cost"]) - float(winner["best_cost"])
        lns = lns_refs.get(key)
        if lns is not None and row["algorithm"] != "lns_reference":
            lns_cost = float(lns["best_cost"])
            if lns_cost > 1e-9:
                profile_gap = 100.0 * (float(row["best_cost"]) - lns_cost) / lns_cost
                winner_gap = profile_gap
                if winner is not None:
                    winner_gap = 100.0 * (float(winner["best_cost"]) - lns_cost) / lns_cost
                out["winner_gap_vs_lns_pp"] = winner_gap
                out["profile_gap_vs_lns_pp"] = profile_gap
                out["gap_improvement_vs_winner_pp"] = winner_gap - profile_gap
                out["gap_vs_lns_delta_pp"] = profile_gap
        annotated.append(out)
    return annotated


def probe_bundle(
    bundle_dir: Path,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    include_lns: bool = False,
    matrix_profiles: bool = False,
) -> list[dict[str, Any]]:
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
    if include_lns:
        lns = run_metaheuristic_baseline(
            "LNS",
            bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            initial_solution=warm,
        )
        if lns.best_solution is not None:
            rows.append(
                baseline_solution_row(
                    bundle_id=bundle_id,
                    algorithm="lns_reference",
                    seed=seed,
                    result=lns,
                    carbon_profile=bundle.carbon_profile,
                    instance=bundle.instance,
                    eval_budget=eval_budget,
                )
            )
    config = WinnerKernelConfig(seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds)
    if matrix_profiles:
        for profile in MATRIX_PROFILES:
            include_route_elimination = "route_elimination" in profile
            local_search = "local_search" in profile
            scan_rebuild = "scan_rebuild" in profile
            flags = winner_profile_flags(
                include_route_elimination=include_route_elimination,
                local_search=local_search,
                scan_rebuild=scan_rebuild,
            )
            profile_config = WinnerKernelConfig(
                **{
                    **config.__dict__,
                    "include_route_elimination": include_route_elimination,
                }
            )
            result = _run_winner_variant(
                bundle_dir,
                profile_config,
                initial_solution=warm,
                variant_flags=flags,
                variant_id=profile,
            )
            stats = _history_stats(result, result["best_solution"])
            rows.append(
                solution_row(
                    bundle_id=bundle_id,
                    algorithm=profile,
                    seed=seed,
                    solution=result["best_solution"],
                    carbon_profile=bundle.carbon_profile,
                    instance=bundle.instance,
                    eval_budget=eval_budget,
                    evaluations=int(result["evaluations"]),
                    elapsed_seconds=float(result["elapsed_seconds"]),
                    best_update_count=stats["best_update_count"],
                    unique_solution_count=stats["unique_solution_count"],
                    profile_flags=flags,
                )
            )
    else:
        winner = run_winner_kernel(bundle_dir, config=config, initial_solution=warm)
        winner_stats = _history_stats(winner, winner["best_solution"])
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
                best_update_count=winner_stats["best_update_count"],
                unique_solution_count=winner_stats["unique_solution_count"],
                profile_flags=dict(winner.get("flags") or {}),
            )
        )
        route_elim = run_winner_kernel_plus_route_elimination(bundle_dir, config=config, initial_solution=warm)
        route_elim_stats = _history_stats(route_elim, route_elim["best_solution"])
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
                best_update_count=route_elim_stats["best_update_count"],
                unique_solution_count=route_elim_stats["unique_solution_count"],
                profile_flags=dict(route_elim.get("flags") or {}),
            )
        )
    return annotate_vs_winner(rows)


def baseline_solution_row(
    *,
    bundle_id: str,
    algorithm: str,
    seed: int,
    result: BaselineRunResult,
    carbon_profile: list[dict[str, Any]],
    instance: Any,
    eval_budget: int,
) -> dict[str, Any]:
    solution = result.best_solution
    if solution is None:
        raise ValueError(f"{algorithm} produced no solution for {bundle_id} seed {seed}")
    return solution_row(
        bundle_id=bundle_id,
        algorithm=algorithm,
        seed=seed,
        solution=solution,
        carbon_profile=carbon_profile,
        instance=instance,
        eval_budget=eval_budget,
        evaluations=int(result.evals),
        elapsed_seconds=float(result.elapsed_seconds),
        best_update_count=len(result.history),
        unique_solution_count=len({str(row.get("best_cost", "")) for row in result.history}),
    )


def _history_stats(result: dict[str, Any], best_solution: Solution) -> dict[str, int]:
    history = list(result.get("history") or [])
    signatures = {
        str(row.get("solution_signature_hash"))
        for row in history
        if str(row.get("solution_signature_hash") or "").strip()
    }
    signatures.add(solution_signature_hash(best_solution))
    return {
        "best_update_count": max(0, len(history) - 1),
        "unique_solution_count": len(signatures),
    }


def decision_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_rows = [row for row in rows if _is_e2_hypothesis_profile(row)]
    route_rows = [row for row in rows if _is_route_elimination_profile(row)]
    scan_rows = [row for row in rows if _is_scan_rebuild_profile(row)]
    regressions = [row for row in candidate_rows if _float(row["objective_delta_vs_winner"]) > max(1e-9, abs(_winner_cost(rows, row)) * 0.005)]
    mechanism_rows = [
        row
        for row in candidate_rows
        if bool(row["feasible"])
        and row not in regressions
        and (
            _float(row["objective_delta_vs_winner"]) < -1e-9
            or _float(row["fixed_cost_delta_vs_winner"]) < -1e-9
            or _float(row["route_count_delta_vs_winner"]) < 0
        )
    ]
    objective_rows = [
        row
        for row in candidate_rows
        if _truthy(row.get("zero_violations", row.get("feasible")))
        and _float(row.get("objective_delta_vs_winner")) < -1e-9
    ]
    if regressions:
        status = "ROUTE_COMPRESSION_INTEGRATION_REGRESSED"
    elif mechanism_rows:
        status = "ROUTE_COMPRESSION_SIGNAL_FOUND"
    else:
        status = "ROUTE_COMPRESSION_NO_SHORT_BUDGET_SIGNAL"
    first_gate = _first_gate_status(rows)
    e2_gate = _e2_objective_gate_status(rows)
    mechanism_signal_found = bool(mechanism_rows)
    return {
        "status": status,
        "row_count": len(rows),
        "candidate_profile_rows": len(candidate_rows),
        "route_elimination_rows": len(route_rows),
        "scan_rebuild_rows": len(scan_rows),
        "improved_rows": len(mechanism_rows),
        "objective_improved_rows": len(objective_rows),
        "regression_rows_over_0_5pct": len(regressions),
        "mechanism_signal_found": mechanism_signal_found,
        "first_gate_pass": bool(first_gate["pass"]),
        "first_gate_100c_improved_count": int(first_gate["improved_100c_count"]),
        "first_gate_sanity_regression_count": int(first_gate["sanity_regression_count"]),
        "e2_objective_gate_pass": bool(e2_gate["pass"]),
        "documented_exception_objective_improved_count": int(e2_gate["documented_exception_objective_improved_count"]),
        "documented_exception_gap_improved_count": int(e2_gate["documented_exception_gap_improved_count"]),
        "route_count_explanation_count": int(e2_gate["route_count_explanation_count"]),
        "requires_scan_order_rebuild": bool(mechanism_signal_found and not bool(e2_gate["pass"])),
        "lns_reference_available": any(row.get("algorithm") == "lns_reference" for row in rows),
        "requires_code_fix": bool(regressions) or not mechanism_signal_found or not bool(e2_gate["pass"]),
    }


def write_outputs(rows: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with (output_dir / "compression_probe_rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    decision = decision_from_rows(rows)
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8", newline="\n")
    metadata = {
        "schema_version": "setp-e2-route-compression-probe.v2",
        "metric_definitions": {
            "best_update_count": "max(0, len(winner history) - 1); history records warm start and each accepted best improvement",
            "unique_solution_count": "distinct solution_signature_hash values in winner history plus final best solution",
            "zero_violations": "check_solution returned no hard or soft violations for the reported solution",
            "winner_gap_vs_lns_pp": "100 * (winner_kernel best_cost - lns_reference best_cost) / lns_reference best_cost for the same bundle and seed",
            "profile_gap_vs_lns_pp": "100 * (profile best_cost - lns_reference best_cost) / lns_reference best_cost for the same bundle and seed",
            "gap_improvement_vs_winner_pp": "winner_gap_vs_lns_pp - profile_gap_vs_lns_pp; positive means the profile closes the gap to LNS versus winner",
            "gap_vs_lns_delta_pp": "legacy alias for profile_gap_vs_lns_pp; do not use as an improvement metric",
            "first_gate_pass": "at least one documented 100c exception improves and no 150/200c sanity row regresses by more than 0.5 percent",
            "e2_objective_gate_pass": "documented 100c route-elimination profile has objective_delta_vs_winner < 0, gap_improvement_vs_winner_pp > 0, and zero violations",
        },
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8", newline="\n")
    report = [
        "# E2 Route Compression Probe",
        "",
        f"Verdict: {decision['status']}",
        f"Rows: {len(rows)}",
        f"Candidate profile rows: {decision['candidate_profile_rows']}",
        f"Route-elimination rows: {decision['route_elimination_rows']}",
        f"Scan/order rebuild hypothesis rows: {decision['scan_rebuild_rows']}",
        f"Candidate mechanism-improved rows: {decision['improved_rows']}/{decision['candidate_profile_rows']}",
        f"Candidate objective-improved rows: {decision['objective_improved_rows']}/{decision['candidate_profile_rows']}",
        f"Regressions over 0.5%: {decision['regression_rows_over_0_5pct']}",
        f"Mechanism signal found: {decision['mechanism_signal_found']}",
        f"First gate pass: {decision['first_gate_pass']}",
        f"100c improved count: {decision['first_gate_100c_improved_count']}",
        f"Sanity regression count: {decision['first_gate_sanity_regression_count']}",
        f"E2 objective gate pass: {decision['e2_objective_gate_pass']}",
        f"Documented exception objective improved count: {decision['documented_exception_objective_improved_count']}",
        f"Documented exception gap improved count: {decision['documented_exception_gap_improved_count']}",
        f"Route-count explanation count: {decision['route_count_explanation_count']}",
        f"Requires scan/order rebuild: {decision['requires_scan_order_rebuild']}",
        f"LNS reference available: {decision['lns_reference_available']}",
        f"Requires code/mechanism fix: {decision['requires_code_fix']}",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    hashes = {}
    for name in ("compression_probe_rows.csv", "decision.json", "metadata.json", "report.md"):
        hashes[name] = hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
    (output_dir / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8", newline="\n")


def _first_gate_status(rows: list[dict[str, Any]]) -> dict[str, int | bool]:
    candidate_rows = [row for row in rows if _is_e2_hypothesis_profile(row)]
    exception_rows = [row for row in candidate_rows if str(row.get("bundle")) in {"e2-threeshift-100c-01", "e2-threeshift-100c-02"}]
    sanity_rows = [row for row in candidate_rows if str(row.get("bundle")).startswith(("e2-threeshift-150c", "e2-threeshift-200c"))]
    improved = [
        row
        for row in exception_rows
        if _truthy(row.get("zero_violations", row.get("feasible")))
        and (
            _float(row.get("objective_delta_vs_winner")) < -1e-9
            or _float(row.get("fixed_cost_delta_vs_winner")) < -1e-9
            or _float(row.get("route_count_delta_vs_winner")) < 0
        )
    ]
    sanity_regressions = [
        row
        for row in sanity_rows
        if _float(row.get("objective_delta_vs_winner")) > max(1e-9, abs(_winner_cost(rows, row)) * 0.005)
        or not _truthy(row.get("zero_violations", row.get("feasible")))
    ]
    return {
        "pass": bool(improved) and not sanity_regressions,
        "improved_100c_count": len(improved),
        "sanity_regression_count": len(sanity_regressions),
    }


def _e2_objective_gate_status(rows: list[dict[str, Any]]) -> dict[str, int | bool]:
    candidate_rows = [row for row in rows if _is_e2_hypothesis_profile(row)]
    exception_rows = [
        row
        for row in candidate_rows
        if str(row.get("bundle")) in {"e2-threeshift-100c-01", "e2-threeshift-100c-02"}
    ]
    objective_improved = [
        row
        for row in exception_rows
        if _truthy(row.get("zero_violations", row.get("feasible")))
        and _float(row.get("objective_delta_vs_winner")) < -1e-9
    ]
    gap_improved = [
        row
        for row in objective_improved
        if _float(row.get("gap_improvement_vs_winner_pp")) > 1e-9
    ]
    route_explained = [
        row
        for row in gap_improved
        if _float(row.get("route_count_delta_vs_winner")) < 0
        or _float(row.get("fixed_cost_delta_vs_winner")) < -1e-9
    ]
    any_violation = any(not _truthy(row.get("zero_violations", row.get("feasible"))) for row in candidate_rows)
    return {
        "pass": bool(objective_improved) and bool(gap_improved) and not any_violation,
        "documented_exception_objective_improved_count": len(objective_improved),
        "documented_exception_gap_improved_count": len(gap_improved),
        "route_count_explanation_count": len(route_explained),
    }


def _float(value: Any) -> float:
    try:
        if value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _is_route_elimination_profile(row: dict[str, Any]) -> bool:
    algorithm = str(row.get("algorithm", ""))
    return algorithm == "winner_kernel_plus_route_elimination" or (
        algorithm.startswith("winner_kernel_route_elimination")
    )


def _is_scan_rebuild_profile(row: dict[str, Any]) -> bool:
    return "scan_rebuild" in str(row.get("algorithm", ""))


def _is_e2_hypothesis_profile(row: dict[str, Any]) -> bool:
    algorithm = str(row.get("algorithm", ""))
    return algorithm.startswith("winner_kernel_") and algorithm != "winner_kernel"


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
    parser.add_argument("--include-lns", action="store_true")
    parser.add_argument("--matrix-profiles", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bundles = [Path(item) for item in args.bundles] if args.bundles else DEFAULT_BUNDLES
    rows: list[dict[str, Any]] = []
    for bundle_dir in bundles:
        rows.extend(
            probe_bundle(
                bundle_dir,
                seed=int(args.seed),
                eval_budget=int(args.eval_budget),
                max_runtime_seconds=float(args.max_runtime_seconds),
                include_lns=bool(args.include_lns),
                matrix_profiles=bool(args.matrix_profiles),
            )
        )
    rows = annotate_vs_winner(rows)
    write_outputs(rows, Path(args.output_dir))
    print(json.dumps(decision_from_rows(rows), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
