#!/usr/bin/env python3
"""Resumable E2 submission matrix for the staged hybrid and healthy baselines."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns import e2_final_closure as closure


OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/e2_submission_20260711"
INSTANCES = tuple(f"L-main-threeshift-{size}c-01" for size in (10, 15, 20, 25, 50, 75, 100, 150, 200))
PREFLIGHT_INSTANCES = tuple(f"L-main-threeshift-{size}c-01" for size in (100, 150, 200))
EVIDENCE_ALGORITHMS = (
    "staged_hybrid_carbon_aware",
    "staged_hybrid_carbon_naive",
    "LNS",
    "GA",
    "PSO",
    "VNS",
)
BASELINES = ("LNS", "GA", "PSO", "VNS")
TASK_ALGORITHMS = ("staged_hybrid_carbon_pair", *BASELINES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preflight", "baseline-health", "formal-80", "carbon-280", "decide"), required=True)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--eval-budget", type=int, default=4000)
    parser.add_argument("--seeds", default="1,2,3,4,5")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rejudge-only", action="store_true", help="Recompute decisions from saved rows without running tasks.")
    parser.add_argument("--task-json", default="")
    parser.add_argument("--task-output-json", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.task_json:
        closure.write_json(Path(args.task_output_json), closure.run_task(closure.read_json(Path(args.task_json))))
        return 0

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    seeds = closure.parse_seeds(args.seeds)
    if args.phase == "preflight":
        phase_dir = output_dir / "preflight"
        instances = PREFLIGHT_INSTANCES
        seeds = [1]
        eval_budget = min(400, int(args.eval_budget))
        scenario = "diagnostic_280_override"
        algorithms = TASK_ALGORITHMS
    elif args.phase == "baseline-health":
        phase_dir = output_dir / "baseline_health"
        instances = ("L-main-threeshift-100c-01",)
        seeds = [1]
        eval_budget = int(args.eval_budget)
        scenario = "diagnostic_280_override"
        algorithms = BASELINES
    elif args.phase == "formal-80":
        phase_dir = output_dir / "formal_80"
        instances = INSTANCES
        eval_budget = int(args.eval_budget)
        scenario = "formal_goeke80"
        algorithms = TASK_ALGORITHMS
    elif args.phase == "carbon-280":
        phase_dir = output_dir / "carbon_280"
        instances = INSTANCES
        eval_budget = int(args.eval_budget)
        scenario = "diagnostic_280_override"
        algorithms = TASK_ALGORITHMS
    else:
        decision = final_decision(output_dir)
        closure.write_json(output_dir / "decision.json", decision)
        write_report(output_dir, decision)
        closure.write_hashes(output_dir)
        print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.rejudge_only:
        metadata_path = phase_dir / "metadata.json"
        raw_path = phase_dir / "raw_runs.csv"
        if not metadata_path.exists() or not raw_path.exists():
            raise FileNotFoundError("--rejudge-only requires existing metadata.json and raw_runs.csv")
        metadata = closure.read_json(metadata_path)
        rows = closure.read_csv(raw_path)
        liveness = closure.liveness_verdicts(rows, BASELINES)
        adjudications = adjudicate_submission_liveness(rows, liveness)
        decision = baseline_health_decision(rows, metadata) if args.phase == "baseline-health" else phase_decision(rows, metadata)
        closure.write_csv(phase_dir / "baseline_liveness.csv", liveness)
        closure.write_csv(phase_dir / "baseline_liveness_adjudication.csv", adjudications)
        closure.write_json(phase_dir / "decision.json", decision)
        write_phase_report(phase_dir, decision)
        closure.write_hashes(phase_dir)
        print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if decision["verdict"].endswith("READY") or decision["verdict"] == "E2_BASELINES_HEALTHY" else 2

    phase_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "setp-e2-submission-matrix.v1",
        "phase": args.phase,
        "head": closure.git_head(),
        "instances": list(instances),
        "task_algorithms": list(algorithms),
        "evidence_algorithms": list(EVIDENCE_ALGORITHMS if args.phase != "baseline-health" else BASELINES),
        "seeds": seeds,
        "eval_budget": eval_budget,
        "scenario_type": scenario,
        "workers": int(args.workers),
        "expected_tasks": len(instances) * len(seeds) * len(algorithms),
        "expected_evidence_rows": len(instances) * len(seeds) * (len(EVIDENCE_ALGORITHMS) if args.phase != "baseline-health" else len(BASELINES)),
        "legacy_carbon_search_operators": False,
        "protected_paths": list(closure.PROTECTED_PATHS),
    }
    closure.write_json(phase_dir / "metadata.json", metadata)
    tasks = build_tasks(phase_dir, instances, seeds, eval_budget, scenario, algorithms)
    closure.write_csv(phase_dir / "task_manifest.csv", tasks)
    if args.dry_run:
        run_ids = [str(task["run_id"]) for task in tasks]
        decision = {
            "schema": "setp-e2-task-manifest-decision.v1",
            "verdict": "E2_TASK_MANIFEST_READY" if len(tasks) == metadata["expected_tasks"] and len(set(run_ids)) == len(run_ids) else "HALT_E2_TASK_MANIFEST",
            "head": closure.git_head(),
            "expected_tasks": metadata["expected_tasks"],
            "expected_evidence_rows": metadata["expected_evidence_rows"],
            "observed_tasks": len(tasks),
            "unique_run_ids": len(set(run_ids)),
            "scenario_type": scenario,
            "eval_budget": eval_budget,
        }
        closure.write_json(phase_dir / "task_manifest_decision.json", decision)
        closure.write_hashes(phase_dir)
        print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if decision["verdict"] == "E2_TASK_MANIFEST_READY" else 2
    task_rows = closure.run_tasks(phase_dir, tasks, workers=int(args.workers), force=bool(args.force))
    rows = expand_carbon_pair_rows(task_rows)
    export_solutions(phase_dir, rows)
    decision = baseline_health_decision(rows, metadata) if args.phase == "baseline-health" else phase_decision(rows, metadata)
    closure.write_csv(phase_dir / "raw_runs.csv", rows)
    closure.write_csv(phase_dir / "paired_comparisons.csv", paired_comparisons(rows))
    closure.write_csv(phase_dir / "per_instance_summary.csv", per_instance_summary(rows))
    closure.write_csv(phase_dir / "baseline_liveness.csv", closure.liveness_verdicts(rows, BASELINES))
    closure.write_csv(
        phase_dir / "baseline_liveness_adjudication.csv",
        adjudicate_submission_liveness(rows, closure.liveness_verdicts(rows, BASELINES)),
    )
    closure.write_json(phase_dir / "decision.json", decision)
    write_phase_report(phase_dir, decision)
    closure.write_hashes(phase_dir)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["verdict"].endswith("READY") or decision["verdict"] == "E2_BASELINES_HEALTHY" else 2


def build_tasks(
    phase_dir: Path,
    instances: tuple[str, ...],
    seeds: list[int],
    eval_budget: int,
    scenario: str,
    algorithms: tuple[str, ...],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for instance in instances:
        for seed in seeds:
            for algorithm in algorithms:
                tasks.append(
                    closure.make_task(
                        phase="E2_SUBMISSION",
                        phase_dir=phase_dir,
                        category="threeshift",
                        instance=instance,
                        algorithm=algorithm,
                        seed=seed,
                        eval_budget=eval_budget,
                        runtime_cap_seconds=closure.runtime_cap_for_instance(instance),
                        scenario_type=scenario,
                    )
                )
    return tasks


def phase_decision(rows: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    expected = int(metadata["expected_evidence_rows"])
    ok = [row for row in rows if row.get("gate_status") == "OK"]
    closed = [row for row in rows if closure.truthy(row.get("eval_closed"))]
    zero_violation = [row for row in rows if int(closure.as_float(row.get("violation_count"), -1)) == 0]
    aware = [row for row in rows if row.get("algorithm") == "staged_hybrid_carbon_aware"]
    naive = [row for row in rows if row.get("algorithm") == "staged_hybrid_carbon_naive"]
    carbon_pairs = pair_rows(aware, naive)
    carbon_contract_pairs = sum(
        1
        for left, right in carbon_pairs
        if str(left.get("route_structure_signature")) == str(right.get("route_structure_signature"))
        and abs(closure.as_float(left.get("electricity_kwh")) - closure.as_float(right.get("electricity_kwh"))) <= 1e-7
    )
    carbon_moved_pairs = sum(
        1
        for left, right in carbon_pairs
        if str(left.get("best_signature")) != str(right.get("best_signature"))
        or int(closure.as_float(left.get("charging_actions_moved_from_search_output"), 0)) > 0
    )
    liveness = closure.liveness_verdicts(rows, BASELINES)
    liveness_adjudications = adjudicate_submission_liveness(rows, liveness)
    liveness_halts = [row for row in liveness_adjudications if row.get("decision") == "HALT"]
    ready = (
        len(rows) == expected
        and len(ok) == expected
        and len(closed) == expected
        and len(zero_violation) == expected
        and len(carbon_pairs) == len(metadata["instances"]) * len(metadata["seeds"])
        and carbon_contract_pairs == len(carbon_pairs)
        and carbon_moved_pairs > 0
        and not liveness_halts
    )
    return {
        "schema": "setp-e2-submission-decision.v1",
        "verdict": "E2_PREFLIGHT_READY" if ready and metadata["phase"] == "preflight" else "E2_MATRIX_READY" if ready else "HALT_E2_MATRIX",
        "phase": metadata["phase"],
        "head": closure.git_head(),
        "expected_tasks": expected,
        "observed_tasks": len(rows),
        "ok_tasks": len(ok),
        "eval_closed_tasks": len(closed),
        "zero_violation_tasks": len(zero_violation),
        "carbon_pair_count": len(carbon_pairs),
        "carbon_fixed_route_equal_energy_pairs": carbon_contract_pairs,
        "carbon_moved_pair_count": carbon_moved_pairs,
        "baseline_liveness_halts": liveness_halts,
        "baseline_liveness_adjudication_summary": {
            "total": len(liveness_adjudications),
            "informational": sum(row.get("decision") == "INFO" for row in liveness_adjudications),
            "halts": len(liveness_halts),
        },
        "algorithm_win_loss_claim": False,
    }


def baseline_health_decision(rows: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    expected = int(metadata["expected_tasks"])
    ok = [row for row in rows if row.get("gate_status") == "OK"]
    closed = [row for row in rows if closure.truthy(row.get("eval_closed"))]
    zero_violation = [row for row in rows if int(closure.as_float(row.get("violation_count"), -1)) == 0]
    active = [row for row in rows if algorithm_specific_update_count(row) >= 1]
    signatures = {str(row.get("best_signature")) for row in rows}
    ready = (
        len(rows) == expected
        and len(ok) == expected
        and len(closed) == expected
        and len(zero_violation) == expected
        and len(active) == expected
        and len(signatures) == expected
    )
    return {
        "schema": "setp-e2-baseline-health-decision.v1",
        "verdict": "E2_BASELINES_HEALTHY" if ready else "HALT_E2_BASELINES",
        "phase": metadata["phase"],
        "head": closure.git_head(),
        "expected_tasks": expected,
        "observed_tasks": len(rows),
        "ok_tasks": len(ok),
        "eval_closed_tasks": len(closed),
        "zero_violation_tasks": len(zero_violation),
        "algorithm_specific_active_tasks": len(active),
        "legacy_native_route_update_tasks": sum(
            int(closure.as_float(row.get("native_best_updates"), 0)) >= 1 for row in rows
        ),
        "unique_best_signatures": len(signatures),
        "algorithm_win_loss_claim": False,
    }


def expand_carbon_pair_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for row in rows:
        if row.get("algorithm") != "staged_hybrid_carbon_pair":
            expanded.append(row)
            continue
        aware = dict(row)
        aware["run_id"] = str(row["run_id"]).replace("staged_hybrid_carbon_pair", "staged_hybrid_carbon_aware")
        aware["algorithm"] = "staged_hybrid_carbon_aware"
        aware["display_algorithm"] = "staged ALNS-LNS hybrid + carbon-aware charging schedule"
        expanded.append(aware)
        payload = json.loads(str(row.get("charging_ablation_json", "{}")))
        if not payload:
            continue
        naive = dict(row)
        naive["run_id"] = str(row["run_id"]).replace("staged_hybrid_carbon_pair", "staged_hybrid_carbon_naive")
        naive["algorithm"] = "staged_hybrid_carbon_naive"
        naive["display_algorithm"] = "staged ALNS-LNS hybrid + immediate charging ablation"
        naive["charging_strategy"] = "naive"
        naive["best_cost"] = payload["best_cost"]
        naive["best_signature"] = payload["best_signature"]
        naive["route_structure_signature"] = payload["route_structure_signature"]
        naive["violation_count"] = payload["violation_count"]
        naive["charging_action_count"] = payload["charging_action_count"]
        naive["E_total"] = payload["E_total"]
        naive["E_cv_direct"] = payload["E_cv_direct"]
        naive["E_ev_indirect"] = payload["E_ev_indirect"]
        naive["electricity_kwh"] = payload["electricity_kwh"]
        naive["cost_carbon"] = payload["cost_carbon"]
        naive["solution_json"] = json.dumps(payload["solution"], ensure_ascii=False, sort_keys=True)
        expanded.append(naive)
    return closure.sorted_rows(expanded)


def algorithm_specific_update_count(row: dict[str, Any]) -> int:
    recorded = int(closure.as_float(row.get("algorithm_specific_update_count"), 0))
    if recorded:
        return recorded
    try:
        history = json.loads(str(row.get("history_json", "[]")))
    except json.JSONDecodeError:
        return 0
    return sum(
        1
        for item in history[1:]
        if str(item.get("channel", "")).startswith("native_")
        or str(item.get("channel", "")) == "flip_operator"
    )


def adjudicate_submission_liveness(
    rows: list[dict[str, Any]],
    liveness_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Separate wiring failures from normal convergence to the same small-instance solution.

    The legacy cross-algorithm check compares ``best_signature`` values.  That
    signature is not an algorithm identity: independent algorithms can reach
    the same solution, and in some historical rows the same summary signature
    can even accompany different route-structure signatures.  A collision is
    therefore informational when every matching baseline has recorded genuine
    algorithm-specific updates.  Missing activity and seed invariance remain
    hard stops.
    """

    baseline_rows = [row for row in rows if row.get("algorithm") in BASELINES]
    run_by_id = {str(row.get("run_id")): row for row in baseline_rows}
    out: list[dict[str, Any]] = []
    for item in liveness_rows:
        verdict = str(item.get("verdict", ""))
        if verdict == "CROSS_ALGO_IDENTITY_SUSPECT":
            flag = str(item.get("flags", ""))
            signature = flag.split("shared_signature=", 1)[-1] if "shared_signature=" in flag else ""
            matches = [row for row in baseline_rows if str(row.get("best_signature")) == signature]
            active_count = sum(algorithm_specific_update_count(row) >= 1 for row in matches)
            route_signatures = {str(row.get("route_structure_signature", "")) for row in matches}
            algorithms = sorted({str(row.get("algorithm")) for row in matches})
            independent_activity = bool(matches) and active_count == len(matches)
            out.append(
                {
                    "scope": "cross_algorithm",
                    "algorithm": "|".join(algorithms) or str(item.get("algorithm", "")),
                    "signature": signature,
                    "source_verdict": verdict,
                    "decision": "INFO" if independent_activity else "HALT",
                    "adjudicated_verdict": (
                        "INDEPENDENT_CONVERGENCE_INFO"
                        if independent_activity
                        else "CROSS_ALGORITHM_WIRING_NOT_CLEARED"
                    ),
                    "matching_runs": len(matches),
                    "algorithm_specific_active_runs": active_count,
                    "route_structure_signature_count": len(route_signatures),
                    "reason": (
                        "All matching baselines recorded algorithm-specific updates; an output collision is not evidence of shared execution."
                        if independent_activity
                        else "At least one matching baseline lacks an algorithm-specific update trail."
                    ),
                }
            )
            continue

        if verdict == "BASELINE_LIVENESS_FAIL":
            run_id = str(item.get("run_id", ""))
            source = run_by_id.get(run_id)
            activity = algorithm_specific_update_count(source) if source is not None else 0
            activity_cleared = source is not None and activity >= 1
            out.append(
                {
                    "scope": "run",
                    "algorithm": item.get("algorithm"),
                    "signature": "",
                    "source_verdict": verdict,
                    "decision": "INFO" if activity_cleared else "HALT",
                    "adjudicated_verdict": (
                        "ALGORITHM_SPECIFIC_ACTIVITY_CONFIRMED"
                        if activity_cleared
                        else "ALGORITHM_SPECIFIC_ACTIVITY_MISSING"
                    ),
                    "matching_runs": 1 if source is not None else 0,
                    "algorithm_specific_active_runs": 1 if activity_cleared else 0,
                    "route_structure_signature_count": "",
                    "reason": (
                        f"legacy_flags={item.get('flags', '')}; algorithm_specific_update_count={activity}"
                    ),
                }
            )
            continue

        hard = (
            verdict == "SEED_INVARIANCE_SUSPECT"
            or "HALT" in verdict
        )
        if hard:
            out.append(
                {
                    "scope": item.get("scope"),
                    "algorithm": item.get("algorithm"),
                    "signature": "",
                    "source_verdict": verdict,
                    "decision": "HALT",
                    "adjudicated_verdict": verdict,
                    "matching_runs": "",
                    "algorithm_specific_active_runs": "",
                    "route_structure_signature_count": "",
                    "reason": item.get("flags", ""),
                }
            )
    return out


def pair_rows(left_rows: list[dict[str, Any]], right_rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    right = {(row.get("instance"), int(closure.as_float(row.get("seed"), 0))): row for row in right_rows}
    out = []
    for left in left_rows:
        key = (left.get("instance"), int(closure.as_float(left.get("seed"), 0)))
        if key in right:
            out.append((left, right[key]))
    return out


def paired_comparisons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aware = [row for row in rows if row.get("algorithm") == "staged_hybrid_carbon_aware"]
    out: list[dict[str, Any]] = []
    for baseline in ("staged_hybrid_carbon_naive", *BASELINES):
        for left, right in pair_rows(aware, [row for row in rows if row.get("algorithm") == baseline]):
            right_cost = closure.as_float(right.get("best_cost"))
            left_cost = closure.as_float(left.get("best_cost"))
            out.append(
                {
                    "instance": left.get("instance"),
                    "seed": left.get("seed"),
                    "left_algorithm": left.get("algorithm"),
                    "right_algorithm": baseline,
                    "left_cost": left_cost,
                    "right_cost": right_cost,
                    "left_gain_pct": 100.0 * (right_cost - left_cost) / right_cost if right_cost else math.nan,
                    "left_E_ev_indirect": left.get("E_ev_indirect"),
                    "right_E_ev_indirect": right.get("E_ev_indirect"),
                    "left_elapsed_seconds": left.get("elapsed_seconds"),
                    "right_elapsed_seconds": right.get("elapsed_seconds"),
                }
            )
    return closure.sorted_rows(out)


def per_instance_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = paired_comparisons(rows)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in pairs:
        groups.setdefault((str(row["instance"]), str(row["right_algorithm"])), []).append(row)
    out = []
    for (instance, baseline), items in groups.items():
        gains = [closure.as_float(row["left_gain_pct"]) for row in items]
        out.append(
            {
                "instance": instance,
                "right_algorithm": baseline,
                "pairs": len(items),
                "mean_gain_pct": statistics.fmean(gains),
                "median_gain_pct": statistics.median(gains),
                "wins": sum(gain > 1e-9 for gain in gains),
                "ties": sum(abs(gain) <= 1e-9 for gain in gains),
                "losses": sum(gain < -1e-9 for gain in gains),
            }
        )
    return closure.sorted_rows(out)


def export_solutions(phase_dir: Path, rows: list[dict[str, Any]]) -> None:
    solution_dir = phase_dir / "solutions"
    solution_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        payload = str(row.get("solution_json", ""))
        if not payload:
            continue
        closure.write_json(solution_dir / f"{row['run_id']}.json", json.loads(payload))


def final_decision(output_dir: Path) -> dict[str, Any]:
    phases = {}
    for name in ("preflight", "baseline_health", "formal_80", "carbon_280"):
        path = output_dir / name / "decision.json"
        phases[name] = closure.read_json(path) if path.exists() else {"verdict": "NOT_RUN"}
    performance_path = output_dir / "carbon_280" / "performance_decision.json"
    performance = closure.read_json(performance_path) if performance_path.exists() else {"verdict": "NOT_REVIEWED"}
    main_scenario_ready = (
        phases["carbon_280"].get("verdict") == "E2_MATRIX_READY"
        and performance.get("verdict") == "E2_FULL_BENCHMARK_LEAD_SUPPORTED"
    )
    return {
        "schema": "setp-e2-submission-final-decision.v2",
        "head": closure.git_head(),
        "phase_verdicts": {name: value.get("verdict") for name, value in phases.items()},
        "preflight_short_budget_superseded": (
            phases["preflight"].get("verdict") == "HALT_E2_MATRIX"
            and phases["baseline_health"].get("verdict") == "E2_BASELINES_HEALTHY"
        ),
        "formal_ready": phases["formal_80"].get("verdict") == "E2_MATRIX_READY",
        "carbon_extension_ready": phases["carbon_280"].get("verdict") == "E2_MATRIX_READY",
        "main_scenario": "diagnostic_280_override",
        "main_scenario_ready": main_scenario_ready,
        "submission_e2_ready": main_scenario_ready,
        "performance_verdict": performance.get("verdict"),
        "aggregate_benchmark_gain_pct": performance.get("aggregate_benchmark_gain_pct"),
        "paired_mean_gain_pct": performance.get("paired_mean_gain_pct"),
        "paired_wins_ties_losses": performance.get("paired_wins_ties_losses"),
        "algorithm_win_loss_claim": main_scenario_ready,
        "claim_scope": "280 kWh main scenario; aggregate >5% lead with full paired statistics reported; no uniform per-instance 5% claim",
        "robustness_80_status": phases["formal_80"].get("verdict"),
    }


def write_phase_report(phase_dir: Path, decision: dict[str, Any]) -> None:
    lines = [
        "# E2 Submission Matrix",
        "",
        f"Verdict: `{decision['verdict']}`",
        "",
        f"Tasks: {decision['ok_tasks']}/{decision['expected_tasks']} OK; eval-closed {decision['eval_closed_tasks']}; zero-violation {decision['zero_violation_tasks']}.",
        (
            f"Carbon pairs: {decision['carbon_pair_count']}; pairs with a recorded charging-time mechanism signal: {decision['carbon_moved_pair_count']}."
            if "carbon_pair_count" in decision
            else f"Algorithm-specific active tasks: {decision.get('algorithm_specific_active_tasks', 0)}; unique best signatures: {decision.get('unique_best_signatures', 0)}."
        ),
        "",
        "This is experiment evidence, not paper prose. Algorithm win/loss claims remain disabled until the complete matrix is reviewed.",
    ]
    (phase_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(output_dir: Path, decision: dict[str, Any]) -> None:
    (output_dir / "report.md").write_text(
        "# E2 Submission Closeout\n\n" + json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
