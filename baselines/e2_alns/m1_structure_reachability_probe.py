"""One-step structure reachability diagnostic for the static M1 line.

This probe does not change the evaluator, physical parameters, or any search
algorithm.  It freezes one start solution and asks each existing operator for
one candidate.  The output separates three different failures:

* no usable structural candidate can be made;
* structural candidates exist, but every one is immediately more expensive;
* an improving structural candidate exists, so the remaining problem is how
  operators are scheduled or how several moves are chained together.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
from typing import Any, Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setp_solver.algorithms.resetp_alns.kernel.winner import (
    TRACE_DIAGNOSTIC_FLAG,
    WinnerOperatorAction,
    WinnerOperatorSet,
    apply_winner_action,
    e2_alns_throughput_flags,
    winner_variant_flags,
)
from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution
from setp_solver.algorithms.resetp_alns.support.fleet import infer_fleet_limits
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import _apply_path_operator_outcome, make_shared_initial_solution
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir
from setp_solver.solution import Solution


DEFAULT_INSTANCE = "L-main-threeshift-25c-01"
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_structure_reachability_20260710")
SA_OPERATORS = (
    "two_opt_route",
    "relocate_customer",
    "swap_customers",
    "merge_routes",
    "vehicle_type_flip",
    "remove_reinsert_route",
)


def classify_reachability(rows: Iterable[dict[str, Any]]) -> str:
    """Classify ALNS rows without turning the diagnostic into a win claim."""

    alns = [row for row in rows if str(row.get("engine", "")).upper() == "ALNS"]
    structural = [
        row
        for row in alns
        if _truthy(row.get("feasible"))
        and _truthy(row.get("changed"))
        and (
            _number(row.get("route_delta")) != 0.0
            or _number(row.get("ev_route_delta")) != 0.0
            or _number(row.get("charging_action_delta")) != 0.0
        )
    ]
    if not structural:
        return "ALNS_OPERATOR_REACHABILITY_BLOCKED"
    if not any(_number(row.get("cost_delta"), default=math.inf) < -1e-9 for row in structural):
        return "ALNS_ACCEPTANCE_BARRIER"
    return "ALNS_SCHEDULER_OR_MULTI_STEP_BARRIER"


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _number(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _solution_metrics(solution: Solution) -> dict[str, int]:
    return {
        "route_count": len(solution.routes),
        "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "charging_action_count": len(solution.charging_actions),
    }


def _git_value(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _profile_flags() -> list[tuple[str, bool, dict[str, str]]]:
    lean = winner_variant_flags(include_route_elimination=False)
    throughput = e2_alns_throughput_flags()
    t3 = dict(throughput)
    t3["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "1"
    route_elimination = winner_variant_flags(include_route_elimination=True)
    profiles = [
        ("LEAN_PUBLIC", False, lean),
        ("CURRENT_THROUGHPUT", False, throughput),
        ("CURRENT_T3_LOCAL_SEARCH", False, t3),
        ("ROUTE_ELIMINATION_DIAGNOSTIC", True, route_elimination),
    ]
    for _, _, flags in profiles:
        flags[TRACE_DIAGNOSTIC_FLAG] = "1"
    return profiles


def _start_solutions(bundle: Any, prices: Any) -> dict[str, Solution]:
    limits = infer_fleet_limits(bundle.bundle_dir)
    cv_only = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        fleet_limits=limits,
        introduce_ev=False,
        require_charging_signal=False,
    )
    return {
        "CV_ONLY": cv_only,
        "SHARED_ONE_EV": make_shared_initial_solution(bundle, prices=prices),
    }


def _base_row(
    *,
    engine: str,
    profile: str,
    start_name: str,
    operator: str,
    repair: str,
    repetition: int,
    start: Solution,
    candidate: Solution,
    start_cost: float,
    candidate_cost: float,
    changed: bool,
    feasible: bool,
    violation_count: int,
    detail: str,
    temperature: float,
) -> dict[str, Any]:
    before = _solution_metrics(start)
    after = _solution_metrics(candidate)
    delta = float(candidate_cost - start_cost)
    sa_probability = 1.0 if delta <= 0.0 else math.exp(-delta / max(1e-12, temperature))
    return {
        "engine": engine,
        "profile": profile,
        "start": start_name,
        "operator": operator,
        "repair": repair,
        "repetition": repetition,
        "changed": bool(changed),
        "feasible": bool(feasible),
        "violation_count": int(violation_count),
        "start_cost": float(start_cost),
        "candidate_cost": float(candidate_cost),
        "cost_delta": delta,
        "route_count_before": before["route_count"],
        "route_count_after": after["route_count"],
        "route_delta": after["route_count"] - before["route_count"],
        "ev_routes_before": before["ev_route_count"],
        "ev_routes_after": after["ev_route_count"],
        "ev_route_delta": after["ev_route_count"] - before["ev_route_count"],
        "charging_actions_before": before["charging_action_count"],
        "charging_actions_after": after["charging_action_count"],
        "charging_action_delta": after["charging_action_count"] - before["charging_action_count"],
        "hill_climb_would_accept": bool(feasible and changed and delta <= 1e-9),
        "sa_accept_probability_at_temperature": float(sa_probability if feasible and changed else 0.0),
        "detail": detail,
    }


def _alns_rows(
    bundle: Any,
    prices: Any,
    starts: dict[str, Solution],
    *,
    repetitions: int,
    seed: int,
    remove_fraction: float,
    temperature: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    customer_count = sum(1 for node in bundle.instance.nodes if node.node_type.lower() == "c")
    remove_count = max(1, int(math.ceil(customer_count * remove_fraction)))
    for profile_index, (profile, include_route_elimination, flags) in enumerate(_profile_flags()):
        operators = WinnerOperatorSet.create(include_route_elimination=include_route_elimination)
        for start_index, (start_name, start) in enumerate(starts.items()):
            start_context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
            start_cost = model_cost(start, start_context)
            for destroy_index, (destroy_name, _) in enumerate(operators.destroy_ops):
                for repair_index, (repair_name, _) in enumerate(operators.repair_ops):
                    for repetition in range(1, repetitions + 1):
                        derived_seed = (
                            seed
                            + profile_index * 1_000_000
                            + start_index * 100_000
                            + destroy_index * 10_000
                            + repair_index * 1_000
                            + repetition
                        )
                        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
                        outcome = apply_winner_action(
                            start,
                            WinnerOperatorAction(
                                destroy_op_id=destroy_name,
                                repair_op_id=repair_name,
                                remove_count_q=remove_count,
                                temperature=temperature,
                                accept_param=temperature,
                                remove_fraction=remove_fraction,
                            ),
                            context,
                            rng=np.random.default_rng(derived_seed),
                            operator_set=operators,
                            current_obj=start_cost,
                            variant_flags=flags,
                        )
                        candidate = outcome["candidate_solution"]
                        violations = check_solution(candidate, bundle.instance, prices)
                        candidate_cost = model_cost(candidate, context)
                        trace = outcome.get("trace", {})
                        rows.append(
                            {
                                **_base_row(
                                    engine="ALNS",
                                    profile=profile,
                                    start_name=start_name,
                                    operator=destroy_name,
                                    repair=repair_name,
                                    repetition=repetition,
                                    start=start,
                                    candidate=candidate,
                                    start_cost=start_cost,
                                    candidate_cost=candidate_cost,
                                    changed=bool(outcome["changed"]),
                                    feasible=not violations,
                                    violation_count=len(violations),
                                    detail=str(trace.get("revert_reason", "")),
                                    temperature=temperature,
                                ),
                                "remove_count": remove_count,
                                "raw_changed_before_wrapper_revert": trace.get("raw_changed", "N/A"),
                                "raw_route_delta_before_wrapper_revert": trace.get("raw_candidate_route_count_delta", "N/A"),
                                "raw_hard_violations_before_wrapper_revert": trace.get("raw_hard_violation_count", "N/A"),
                            }
                        )
    return rows


def _sa_rows(
    bundle: Any,
    prices: Any,
    starts: dict[str, Solution],
    *,
    repetitions: int,
    seed: int,
    temperature: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start_index, (start_name, start) in enumerate(starts.items()):
        start_context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
        start_cost = model_cost(start, start_context)
        for operator_index, operator in enumerate(SA_OPERATORS):
            for repetition in range(1, repetitions + 1):
                derived_seed = seed + start_index * 100_000 + operator_index * 10_000 + repetition
                context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
                outcome = _apply_path_operator_outcome(start, context, random.Random(derived_seed), operator)
                candidate = outcome.solution
                violations = check_solution(candidate, bundle.instance, prices) if outcome.produced else []
                feasible = bool(outcome.produced and not violations)
                candidate_cost = model_cost(candidate, context)
                rows.append(
                    _base_row(
                        engine="SA",
                        profile="DIRECT_PATH_OPERATORS",
                        start_name=start_name,
                        operator=operator,
                        repair="N/A",
                        repetition=repetition,
                        start=start,
                        candidate=candidate,
                        start_cost=start_cost,
                        candidate_cost=candidate_cost,
                        changed=bool(outcome.changed),
                        feasible=feasible,
                        violation_count=len(violations),
                        detail=str(outcome.detail),
                        temperature=temperature,
                    )
                )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row["engine"]), str(row["profile"]), str(row["start"])), []).append(row)
    summary: list[dict[str, Any]] = []
    for (engine, profile, start), items in sorted(groups.items()):
        usable = [row for row in items if row["feasible"] and row["changed"]]
        structural = [
            row
            for row in usable
            if row["route_delta"] != 0 or row["ev_route_delta"] != 0 or row["charging_action_delta"] != 0
        ]
        improving_structural = [row for row in structural if row["cost_delta"] < -1e-9]
        summary.append(
            {
                "engine": engine,
                "profile": profile,
                "start": start,
                "attempts": len(items),
                "feasible_changed": len(usable),
                "structural_candidates": len(structural),
                "route_drop_candidates": sum(1 for row in structural if row["route_delta"] < 0),
                "ev_change_candidates": sum(1 for row in structural if row["ev_route_delta"] != 0),
                "charging_change_candidates": sum(1 for row in structural if row["charging_action_delta"] != 0),
                "improving_structural_candidates": len(improving_structural),
                "best_structural_cost_delta": min((float(row["cost_delta"]) for row in structural), default="N/A"),
            }
        )
    return summary


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_label(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    activation_manifest = assert_formal_benchmark_ready(repo_root)
    bundle_dir = instance_abs_dir(repo_root, args.instance)
    bundle = load_search_bundle(bundle_dir)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    starts = _start_solutions(bundle, prices)

    start_rows: list[dict[str, Any]] = []
    for name, solution in starts.items():
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
        metrics = _solution_metrics(solution)
        violations = check_solution(solution, bundle.instance, prices)
        start_rows.append(
            {
                "start": name,
                **metrics,
                "cost": model_cost(solution, context),
                "violation_count": len(violations),
            }
        )
    if any(row["violation_count"] for row in start_rows):
        raise RuntimeError(f"probe start solution is infeasible: {start_rows}")

    rows = _alns_rows(
        bundle,
        prices,
        starts,
        repetitions=args.repetitions,
        seed=args.seed,
        remove_fraction=args.remove_fraction,
        temperature=args.temperature,
    )
    rows.extend(
        _sa_rows(
            bundle,
            prices,
            starts,
            repetitions=args.repetitions,
            seed=args.seed,
            temperature=args.temperature,
        )
    )
    summary = _summary_rows(rows)
    verdict = classify_reachability(rows)

    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    operator_csv = output_dir / "operator_rows.csv"
    starts_csv = output_dir / "start_states.csv"
    summary_csv = output_dir / "summary.csv"
    _write_csv(operator_csv, rows)
    _write_csv(starts_csv, start_rows)
    _write_csv(summary_csv, summary)

    manifest_path = repo_root / "models/data_bundle/generated_instances/L-main/resetp-l-main-main-benchmark.v3.json"
    metadata = {
        "schema_version": "setp-m1-structure-reachability.v1",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "repo_commit": _git_value(repo_root, "rev-parse", "HEAD"),
        "repo_dirty_at_run": bool(_git_value(repo_root, "status", "--porcelain")),
        "instance": args.instance,
        "actual_customer_count": sum(1 for node in bundle.instance.nodes if node.node_type.lower() == "c"),
        "battery_kwh": float(args.battery_kwh),
        "seed": int(args.seed),
        "repetitions": int(args.repetitions),
        "remove_fraction": float(args.remove_fraction),
        "temperature": float(args.temperature),
        "formal_manifest_schema": activation_manifest.get("schema_version"),
        "formal_manifest_sha256": _sha256(manifest_path),
        "profiles": [name for name, _, _ in _profile_flags()],
        "sa_operators": list(SA_OPERATORS),
        "algorithm_source_sha256": {
            str(path.relative_to(repo_root)): _sha256(path)
            for path in (
                repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
                repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
                repo_root / "solver/src/setp_solver/search/candidates.py",
            )
        },
    }
    decision = {
        "schema_version": "setp-m1-structure-reachability-decision.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "meaning": {
            "ALNS_OPERATOR_REACHABILITY_BLOCKED": "Current ALNS one-step operators made no usable route/fleet/charging structure change.",
            "ALNS_ACCEPTANCE_BARRIER": "ALNS made usable structural candidates, but every observed one was immediately more expensive.",
            "ALNS_SCHEDULER_OR_MULTI_STEP_BARRIER": "ALNS made at least one immediately improving structural candidate; scheduling or move chaining is the next suspect.",
        }[verdict],
        "row_count": len(rows),
        "alns_row_count": sum(1 for row in rows if row["engine"] == "ALNS"),
        "sa_row_count": sum(1 for row in rows if row["engine"] == "SA"),
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report_lines = [
        "# M1 structure reachability diagnostic",
        "",
        f"Verdict: `{verdict}`.",
        "",
        "This is a one-step mechanism test, not an algorithm ranking and not a formal T3 result. "
        "It keeps the shared evaluator and checker unchanged and uses the same frozen starts for ALNS and SA.",
        "",
        f"Instance: `{args.instance}`; actual customers: `{metadata['actual_customer_count']}`; battery: `{args.battery_kwh}` kWh.",
        "",
        "## Start states",
        "",
    ]
    for row in start_rows:
        report_lines.append(
            f"- {row['start']}: cost {float(row['cost']):.6f}, routes {row['route_count']}, "
            f"EV routes {row['ev_route_count']}, charging actions {row['charging_action_count']}."
        )
    report_lines.extend(["", "## One-step summary", ""])
    for row in summary:
        report_lines.append(
            f"- {row['engine']} / {row['profile']} / {row['start']}: "
            f"{row['structural_candidates']} structural candidates, "
            f"{row['improving_structural_candidates']} immediately improving, "
            f"{row['route_drop_candidates']} route drops, {row['ev_change_candidates']} EV changes."
        )
    report_lines.extend(
        [
            "",
            "## Boundary",
            "",
            "A missing one-step change is strong evidence that the present move set cannot directly cross that boundary. "
            "It does not prove that a long sequence can never reach it. An improving one-step change only proves that "
            "the move exists; it does not prove the scheduler will choose it often enough in a full run.",
            "",
        ]
    )
    report_path = output_dir / "report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    hash_targets = [
        Path(__file__).resolve(),
        manifest_path,
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
        repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
        repo_root / "solver/src/setp_solver/search/candidates.py",
        operator_csv,
        starts_csv,
        summary_csv,
        output_dir / "metadata.json",
        output_dir / "decision.json",
        report_path,
    ]
    artifact_hashes = {
        _artifact_label(path, repo_root): _sha256(path)
        for path in hash_targets
    }
    (output_dir / "artifact_hashes.json").write_text(
        json.dumps(artifact_hashes, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"verdict": verdict, "output_dir": str(output_dir), "rows": len(rows), "summary": summary}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[2])
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--remove-fraction", type=float, default=0.10)
    parser.add_argument("--temperature", type=float, default=250.0)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run_probe(parse_args()), indent=2, sort_keys=True))
