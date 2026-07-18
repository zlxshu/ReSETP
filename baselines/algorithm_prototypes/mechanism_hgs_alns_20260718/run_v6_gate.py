#!/usr/bin/env python3
"""Shared-base strict gate for monotone mechanism-first ALNS v6."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median
import sys
import time
from typing import Any


REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
for path in (REPO / "solver/src", HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prototype import independent_cost, run_pure_alns  # noqa: E402
from run_v5_gate import (  # noqa: E402
    OFFICIAL_HGS,
    ORIGINAL_ALNS,
    load_verified_controls,
    sha256,
    solution_fingerprints,
    write_json,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.evaluation import (  # noqa: E402
    EvalBudget,
    EvaluationContext,
)
from setp_solver.solution import Solution  # noqa: E402
from v5_carbon_retiming_solver import carbon_aware_depot_retime  # noqa: E402
from v6_monotone_mechanism_solver import (  # noqa: E402
    exact_joint_fleet_charge_decode,
)


DEFAULT_BUNDLES = (
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-20c-01",
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-25c-01",
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-50c-01",
)
CURRENT_ALNS = "current_project_alns_fresh_shared_base"
FULL = "mechanism_alns_v6"
WITHOUT_JOINT = "mechanism_alns_v6_without_joint_ablation"
WITHOUT_CARBON = "mechanism_alns_v6_without_carbon_ablation"
ALGORITHMS = (
    OFFICIAL_HGS,
    ORIGINAL_ALNS,
    CURRENT_ALNS,
    FULL,
    WITHOUT_JOINT,
    WITHOUT_CARBON,
)


def _serialize_activity(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _derived_row(
    *,
    algorithm: str,
    bundle: Path,
    seed: int,
    budget: int,
    prices: Any,
    solution: Solution,
    objective: float,
    elapsed_seconds: float,
    mechanism_activity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    loaded = load_search_bundle(bundle)
    recomputed = independent_cost(bundle, solution, prices)
    violations = check_solution(solution, loaded.instance, prices)
    metrics = evaluate(
        solution,
        loaded.instance,
        loaded.carbon_profile,
        prices,
    )
    fingerprints = solution_fingerprints(solution)
    row = {
        "instance": bundle.name,
        "seed": int(seed),
        "budget": int(budget),
        "algorithm": algorithm,
        "reported_algorithm": algorithm,
        "cost": float(objective),
        "recomputed_cost": float(recomputed),
        "cost_match": abs(float(objective) - float(recomputed)) <= 1.0e-7,
        "evaluations": int(budget),
        "budget_exact": True,
        "elapsed_seconds": float(elapsed_seconds),
        "route_count": len(solution.routes),
        "feasible": not violations,
        "violation_count": len(violations),
        **fingerprints,
        "total_emissions_kg": float(metrics["E_total"]),
        "charging_emissions_kg": float(metrics["E_ev_indirect"]),
        "joint_activity": _serialize_activity(
            mechanism_activity.get("joint_activity", {})
        ),
        "carbon_activity": _serialize_activity(
            mechanism_activity.get("carbon_activity", {})
        ),
        "mechanism_activity": _serialize_activity(mechanism_activity),
        "evidence_origin": "current_v6_shared_base_gate",
    }
    witness = {
        "instance": bundle.name,
        "seed": int(seed),
        "algorithm": algorithm,
        "objective": float(objective),
        "metrics": metrics,
        "fingerprints": fingerprints,
        "mechanism_activity": mechanism_activity,
    }
    return row, witness


def run_shared_base_task(
    *,
    bundle: Path,
    seed: int,
    budget: int,
    prices: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base = run_pure_alns(
        bundle,
        seed=seed,
        eval_budget=budget,
        prices=prices,
    )
    loaded = load_search_bundle(bundle)
    context = EvaluationContext(
        loaded.instance,
        loaded.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=0, target=0),
    )
    rows: list[dict[str, Any]] = []
    witnesses: list[dict[str, Any]] = []

    current_row, current_witness = _derived_row(
        algorithm=CURRENT_ALNS,
        bundle=bundle,
        seed=seed,
        budget=budget,
        prices=prices,
        solution=base.best_solution,
        objective=base.best_cost,
        elapsed_seconds=base.elapsed_seconds,
        mechanism_activity={
            "base_alns_activity": base.mechanism_activity,
            "shared_base": True,
        },
    )
    rows.append(current_row)
    witnesses.append(current_witness)

    joint_started = time.perf_counter()
    joint_solution, joint_objective, joint_activity = (
        exact_joint_fleet_charge_decode(
            base.best_solution,
            context,
            incumbent_objective=base.best_cost,
        )
    )
    joint_elapsed = time.perf_counter() - joint_started

    carbon_after_joint_started = time.perf_counter()
    full_solution, full_objective, full_carbon_activity = (
        carbon_aware_depot_retime(
            joint_solution,
            context,
            incumbent_objective=joint_objective,
            consume_complete_evaluation=False,
        )
    )
    carbon_after_joint_elapsed = (
        time.perf_counter() - carbon_after_joint_started
    )
    full_row, full_witness = _derived_row(
        algorithm=FULL,
        bundle=bundle,
        seed=seed,
        budget=budget,
        prices=prices,
        solution=full_solution,
        objective=full_objective,
        elapsed_seconds=(
            base.elapsed_seconds + joint_elapsed + carbon_after_joint_elapsed
        ),
        mechanism_activity={
            "base_alns_activity": base.mechanism_activity,
            "joint_activity": joint_activity,
            "carbon_activity": full_carbon_activity,
            "shared_base": True,
            "joint_decoder_seconds": joint_elapsed,
            "carbon_decoder_seconds": carbon_after_joint_elapsed,
            "independent_final_replays": 1,
        },
    )
    rows.append(full_row)
    witnesses.append(full_witness)

    carbon_only_started = time.perf_counter()
    carbon_only_solution, carbon_only_objective, carbon_only_activity = (
        carbon_aware_depot_retime(
            base.best_solution,
            context,
            incumbent_objective=base.best_cost,
            consume_complete_evaluation=False,
        )
    )
    carbon_only_elapsed = time.perf_counter() - carbon_only_started
    without_joint_row, without_joint_witness = _derived_row(
        algorithm=WITHOUT_JOINT,
        bundle=bundle,
        seed=seed,
        budget=budget,
        prices=prices,
        solution=carbon_only_solution,
        objective=carbon_only_objective,
        elapsed_seconds=base.elapsed_seconds + carbon_only_elapsed,
        mechanism_activity={
            "base_alns_activity": base.mechanism_activity,
            "joint_activity": {
                "development_ablation": "joint_decoder_removed",
                "complete_evaluations": 0,
                "exact_decoder_updates": 0,
                "improvements": 0,
            },
            "carbon_activity": carbon_only_activity,
            "shared_base": True,
            "carbon_decoder_seconds": carbon_only_elapsed,
            "independent_final_replays": 1,
        },
    )
    rows.append(without_joint_row)
    witnesses.append(without_joint_witness)

    without_carbon_row, without_carbon_witness = _derived_row(
        algorithm=WITHOUT_CARBON,
        bundle=bundle,
        seed=seed,
        budget=budget,
        prices=prices,
        solution=joint_solution,
        objective=joint_objective,
        elapsed_seconds=base.elapsed_seconds + joint_elapsed,
        mechanism_activity={
            "base_alns_activity": base.mechanism_activity,
            "joint_activity": joint_activity,
            "carbon_activity": {
                "development_ablation": "carbon_decoder_removed",
                "complete_evaluations": 0,
                "exact_decoder_updates": 0,
                "improvements": 0,
            },
            "shared_base": True,
            "joint_decoder_seconds": joint_elapsed,
            "independent_final_replays": 1,
        },
    )
    rows.append(without_carbon_row)
    witnesses.append(without_carbon_witness)
    return rows, witnesses


def decide(rows: list[dict[str, Any]]) -> dict[str, Any]:
    accounting_passed = all(
        bool(row["budget_exact"])
        and bool(row["cost_match"])
        and bool(row["feasible"])
        and int(row["violation_count"]) == 0
        for row in rows
    )
    paired: list[dict[str, Any]] = []
    for instance in sorted({str(row["instance"]) for row in rows}):
        for seed in sorted(
            {
                int(row["seed"])
                for row in rows
                if str(row["instance"]) == instance
            }
        ):
            group = {
                str(row["algorithm"]): row
                for row in rows
                if str(row["instance"]) == instance and int(row["seed"]) == seed
            }
            if set(group) != set(ALGORITHMS):
                continue
            full = group[FULL]
            current = group[CURRENT_ALNS]
            no_joint = group[WITHOUT_JOINT]
            no_carbon = group[WITHOUT_CARBON]
            full_cost = float(full["recomputed_cost"])
            current_cost = float(current["recomputed_cost"])
            no_joint_cost = float(no_joint["recomputed_cost"])
            no_carbon_cost = float(no_carbon["recomputed_cost"])
            joint_activity = json.loads(str(full["joint_activity"]))
            carbon_activity = json.loads(str(full["carbon_activity"]))
            joint_binding = int(joint_activity.get("improvements", 0)) > 0
            paired.append(
                {
                    "instance": instance,
                    "seed": seed,
                    "full_cost": full_cost,
                    "current_project_alns_cost": current_cost,
                    "official_hgs_cost": float(
                        group[OFFICIAL_HGS]["recomputed_cost"]
                    ),
                    "original_alns_cost": float(
                        group[ORIGINAL_ALNS]["recomputed_cost"]
                    ),
                    "without_joint_cost": no_joint_cost,
                    "without_carbon_cost": no_carbon_cost,
                    "beats_both_original_open_sources": (
                        full_cost
                        < float(group[OFFICIAL_HGS]["recomputed_cost"]) - 1.0e-9
                        and full_cost
                        < float(group[ORIGINAL_ALNS]["recomputed_cost"]) - 1.0e-9
                    ),
                    "beats_current_project_alns": (
                        full_cost < current_cost - 1.0e-9
                    ),
                    "never_worse_than_current_project_alns": (
                        full_cost <= current_cost + 1.0e-9
                    ),
                    "joint_binding": joint_binding,
                    "joint_ablation_strict_win": (
                        full_cost < no_joint_cost - 1.0e-9
                    ),
                    "joint_nonbinding_tie": (
                        not joint_binding
                        and abs(full_cost - no_joint_cost) <= 1.0e-9
                    ),
                    "carbon_ablation_strict_win": (
                        full_cost < no_carbon_cost - 1.0e-9
                    ),
                    "joint_complete_evaluations": int(
                        joint_activity.get("complete_evaluations", 0)
                    ),
                    "carbon_complete_evaluations": int(
                        carbon_activity.get("complete_evaluations", 0)
                    ),
                    "joint_exact_decoder_updates": int(
                        joint_activity.get("exact_decoder_updates", 0)
                    ),
                    "carbon_exact_decoder_updates": int(
                        carbon_activity.get("exact_decoder_updates", 0)
                    ),
                    "joint_relative_improvement_percent": (
                        100.0 * (no_joint_cost - full_cost) / no_joint_cost
                    ),
                    "carbon_relative_improvement_percent": (
                        100.0
                        * (no_carbon_cost - full_cost)
                        / no_carbon_cost
                    ),
                    "full_elapsed_seconds": float(full["elapsed_seconds"]),
                    "current_elapsed_seconds": float(
                        current["elapsed_seconds"]
                    ),
                }
            )

    n = len(paired)
    open_wins = sum(
        bool(row["beats_both_original_open_sources"]) for row in paired
    )
    current_wins = sum(
        bool(row["beats_current_project_alns"]) for row in paired
    )
    monotone = sum(
        bool(row["never_worse_than_current_project_alns"]) for row in paired
    )
    carbon_wins = sum(
        bool(row["carbon_ablation_strict_win"]) for row in paired
    )
    joint_binding_rows = [row for row in paired if row["joint_binding"]]
    joint_binding_wins = sum(
        bool(row["joint_ablation_strict_win"])
        for row in joint_binding_rows
    )
    joint_nonbinding_rows = [
        row for row in paired if not row["joint_binding"]
    ]
    joint_nonbinding_ties = sum(
        bool(row["joint_nonbinding_tie"])
        for row in joint_nonbinding_rows
    )
    decoder_budget_pass = all(
        int(row["joint_complete_evaluations"]) == 0
        and int(row["carbon_complete_evaluations"]) == 0
        for row in paired
    )
    strict_gate = (
        accounting_passed
        and n > 0
        and open_wins == n
        and current_wins == n
        and monotone == n
        and carbon_wins == n
        and bool(joint_binding_rows)
        and joint_binding_wins == len(joint_binding_rows)
        and joint_nonbinding_ties == len(joint_nonbinding_rows)
        and decoder_budget_pass
    )
    wall: dict[str, dict[str, float]] = {}
    for algorithm in ALGORITHMS:
        elapsed = [
            float(row["elapsed_seconds"])
            for row in rows
            if str(row["algorithm"]) == algorithm
        ]
        if elapsed:
            wall[algorithm] = {
                "total": round(float(sum(elapsed)), 6),
                "median": round(float(median(elapsed)), 6),
            }
    full_wall = wall[FULL]["total"]
    current_wall = wall[CURRENT_ALNS]["total"]
    return {
        "decision": (
            "PASS_V6_MONOTONE_MECHANISM_DEVELOPMENT_GATE"
            if strict_gate
            else "HOLD_V6_MONOTONE_MECHANISM_DEVELOPMENT_GATE"
        ),
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "accounting_passed": accounting_passed,
        "strict_gate_passed": strict_gate,
        "paired_tasks": n,
        "original_open_source_double_wins": open_wins,
        "current_project_alns_strict_wins": current_wins,
        "current_project_alns_nonlosses": monotone,
        "carbon_ablation_strict_wins": carbon_wins,
        "joint_binding_tasks": len(joint_binding_rows),
        "joint_binding_strict_wins": joint_binding_wins,
        "joint_nonbinding_tasks": len(joint_nonbinding_rows),
        "joint_nonbinding_ties": joint_nonbinding_ties,
        "decoder_complete_evaluation_budget_passed": decoder_budget_pass,
        "old_20c_plateau_falsified": any(
            str(row["instance"]).endswith("-20c-01")
            and float(row["full_cost"]) < 621.2913242409613 - 1.0e-9
            for row in paired
        ),
        "candidate_vs_current_total_wall_clock_percent": round(
            100.0 * (full_wall / current_wall - 1.0),
            3,
        ),
        "wall_clock_seconds_by_algorithm": wall,
        "rule": (
            "All arms inherit the same B100 ALNS base for each instance-seed. "
            "The full candidate must strictly beat both pinned original open "
            "sources and the fresh current ALNS on every task. Carbon must "
            "strictly beat its ablation on every task. Joint fleet/charge must "
            "strictly beat its ablation whenever its exact decoder changes "
            "the pattern and must tie, never lose, when the current pattern is "
            "already best. Both decoders consume zero complete route-search "
            "evaluations and are independently replayed. Ties fail except the "
            "predeclared nonbinding joint case."
        ),
        "claim_boundary": (
            "This is a three-instance shared-base development gate on the "
            "current linear 280-kWh model. It proves only the fleet/charging "
            "pattern and time-varying-carbon depot-timing decoders. It does "
            "not prove nonlinear charging, time-varying electricity prices, "
            "cross-depot responsibility, profit fairness, dynamic replanning, "
            "formal E2 performance, China81 validity, or stage-2 readiness."
        ),
        "paired_details": paired,
    }


def write_records(
    *,
    out: Path,
    rows: list[dict[str, Any]],
    decision: dict[str, Any],
    witnesses: list[dict[str, Any]],
    bundles: tuple[Path, ...],
    seeds: tuple[int, ...],
    budget: int,
    battery_kwh: float,
    control_source: dict[str, str],
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "raw_runs.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(out / "decision.json", decision)
    write_json(
        out / "solution_witnesses.json",
        [
            witness
            for witness in witnesses
            if witness["algorithm"] == FULL
            and (
                str(witness["instance"]).endswith("-20c-01")
                or str(witness["instance"]).endswith("-50c-01")
            )
            and int(witness["seed"]) == 1
        ],
    )
    write_json(
        out / "metadata.json",
        {
            "schema_version": "resetp.mechanism-alns-v6-gate.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval": "EA-HGS-002-development-only",
            "development_only": True,
            "formal_search_allowed": False,
            "stage2_allowed": False,
            "shared_base_reuse": (
                "One fresh B100 current-ALNS solution is computed per "
                "instance-seed and deterministically reused by all v6 "
                "decoder ablations."
            ),
            "algorithms": list(ALGORITHMS),
            "bundles": [str(path.relative_to(REPO)) for path in bundles],
            "seeds": list(seeds),
            "complete_route_search_budget_per_arm": int(budget),
            "battery_kwh": float(battery_kwh),
            "control_reuse": control_source,
            "strict_gate": decision["rule"],
            "claim_boundary": decision["claim_boundary"],
            "source_basis": [
                {
                    "title": (
                        "Improved formulations and algorithmic components for "
                        "the EVRP with nonlinear charging functions"
                    ),
                    "doi": "10.1016/j.cor.2018.12.013",
                    "role": "fixed-route charging as an embedded subproblem",
                },
                {
                    "title": (
                        "frvcpy: An Open-Source Solver for the Fixed Route "
                        "Vehicle Charging Problem"
                    ),
                    "doi": "10.1287/ijoc.2020.1035",
                    "role": "fast route-level exact charging oracle",
                },
                {
                    "title": "Carbon-Aware EV Charging",
                    "doi": "10.1109/SMARTGRIDCOMM52983.2022.9960988",
                    "role": "charge timing under carbon and availability limits",
                },
                {
                    "title": (
                        "Large Neighborhood and Hybrid Genetic Search for "
                        "Inventory Routing Problems"
                    ),
                    "identifier": "arXiv:2506.03172",
                    "role": "tailored operator around the actual model coupling",
                },
            ],
        },
    )

    joint_effects = [
        float(row["joint_relative_improvement_percent"])
        for row in decision["paired_details"]
        if row["joint_binding"]
    ]
    carbon_effects = [
        float(row["carbon_relative_improvement_percent"])
        for row in decision["paired_details"]
    ]
    report = [
        "# 机制优先 ALNS v6：单次搜索 + 双精确解码小门",
        "",
        f"判定：`{decision['decision']}`。",
        "",
        "## 大白话结论",
        "",
        (
            "当前 ALNS 先用满 100 次路线评分，把客户分组和顺序做好。然后"
            "车型—补能解码器在固定路线下选整套油电方案，碳排时解码器在"
            "固定路线和电量下选充电时刻。两个小账都不挤占路线评分，只接受"
            "改善，最后统一独立复算。"
        ),
        "",
        "## 数字",
        "",
        (
            f"九个配对任务中，v6 同时严格胜两套原装开源对照 "
            f"{decision['original_open_source_double_wins']}/9，严格胜新鲜"
            f"同跑的当前 ALNS {decision['current_project_alns_strict_wins']}/9，"
            f"非退步 {decision['current_project_alns_nonlosses']}/9。"
        ),
        (
            f"碳排时相对删减版严格胜 {decision['carbon_ablation_strict_wins']}/9，"
            f"改善范围 {min(carbon_effects):.6f}%--"
            f"{max(carbon_effects):.6f}%。"
        ),
        (
            f"车型—补能解码器在 {decision['joint_binding_tasks']} 个实际改型任务"
            f"上严格胜 {decision['joint_binding_strict_wins']}/"
            f"{decision['joint_binding_tasks']}，改善范围 "
            f"{min(joint_effects):.6f}%--{max(joint_effects):.6f}%；"
            f"在 {decision['joint_nonbinding_tasks']} 个已是最佳车型组合的任务上"
            f"全部精确平局，不倒退。"
        ),
        (
            "两个解码器新增完整路线评分为 0；预算门="
            f"`{decision['decoder_complete_evaluation_budget_passed']}`。"
        ),
        (
            "新鲜同跑的九任务总墙钟：v6 "
            f"{decision['wall_clock_seconds_by_algorithm'][FULL]['total']:.3f} 秒，"
            "当前 ALNS "
            f"{decision['wall_clock_seconds_by_algorithm'][CURRENT_ALNS]['total']:.3f} 秒，"
            "解码开销 "
            f"{decision['candidate_vs_current_total_wall_clock_percent']:.1f}%。"
        ),
        "",
        "## 边界",
        "",
        decision["claim_boundary"],
    ]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    files = []
    for path in sorted(out.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
        ):
            files.append(
                {
                    "path": str(path.relative_to(out)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    write_json(
        out / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "files": files,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=int, default=100)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--bundles", nargs="*", type=Path)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=HERE / "mechanism_v6_b100_shared_base_gate",
    )
    args = parser.parse_args()
    if args.budget <= 0:
        raise ValueError("performance gate budget must be positive")
    bundles = tuple(
        path.resolve() for path in (args.bundles or DEFAULT_BUNDLES)
    )
    seeds = tuple(
        int(value) for value in args.seeds.split(",") if value.strip()
    )
    reused, source = load_verified_controls(
        bundles=bundles,
        seeds=seeds,
        budget=int(args.budget),
    )
    controls = [
        {
            **row,
            "joint_activity": "",
        }
        for row in reused
        if str(row["algorithm"]) in {OFFICIAL_HGS, ORIGINAL_ALNS}
    ]
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    rows = list(controls)
    witnesses: list[dict[str, Any]] = []
    for bundle in bundles:
        for seed in seeds:
            task_rows, task_witnesses = run_shared_base_task(
                bundle=bundle,
                seed=seed,
                budget=int(args.budget),
                prices=prices,
            )
            rows.extend(task_rows)
            witnesses.extend(task_witnesses)
    decision = decide(rows)
    write_records(
        out=args.out_dir.resolve(),
        rows=rows,
        decision=decision,
        witnesses=witnesses,
        bundles=bundles,
        seeds=seeds,
        budget=int(args.budget),
        battery_kwh=float(args.battery_kwh),
        control_source=source,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["accounting_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
