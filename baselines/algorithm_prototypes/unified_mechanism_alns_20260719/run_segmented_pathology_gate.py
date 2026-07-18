#!/usr/bin/env python3
"""Run the locked score-per-use segmented roulette pathology gate."""

from __future__ import annotations

import copy
import csv
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import solution_payload, solution_signature_hash  # noqa: E402
from segmented_mechanism_solver import (  # noqa: E402
    SegmentedMechanismConfig,
    run_segmented_mechanism_alns,
)
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.algorithms.resetp_alns.support.fleet import (  # noqa: E402
    infer_fleet_limits,
)
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.candidates import make_shared_initial_solution  # noqa: E402


BUNDLE = (
    REPO
    / "models/data_bundle/generated_instances/L-main/"
    "L-main-threeshift-25c-01"
)
CONTRACT = (
    REPO
    / "docs/handoff/"
    "averaged_segmented_roulette_training_contract_20260719.md"
)
OUT = HERE / "segmented_pathology_gate"
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
SEEDS = (1, 2, 3)
BUDGET = 400
TOL = 1.0e-9
PROFILES = {
    "control_alpha": SegmentedMechanismConfig(
        total_eval_budget=BUDGET,
        enable_segmented_roulette=False,
        reaction=0.1,
        segment_length=100,
        split_selector_rng=True,
    ),
    "averaged_segmented_roulette": SegmentedMechanismConfig(
        total_eval_budget=BUDGET,
        enable_segmented_roulette=True,
        reaction=0.1,
        segment_length=100,
        split_selector_rng=True,
    ),
}


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
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def build_starts() -> dict[str, Any]:
    bundle = load_search_bundle(BUNDLE)
    cv_only = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        fleet_limits=infer_fleet_limits(bundle.bundle_dir),
        introduce_ev=False,
        require_charging_signal=False,
    )
    return {
        "CV_ONLY": cv_only,
        "SHARED_ONE_EV": make_shared_initial_solution(
            bundle,
            PRICES,
        ),
    }


def profile_order(start_id: str, seed: int) -> tuple[str, str]:
    reverse = (start_id == "CV_ONLY") == (int(seed) % 2 == 0)
    if reverse:
        return (
            "averaged_segmented_roulette",
            "control_alpha",
        )
    return (
        "control_alpha",
        "averaged_segmented_roulette",
    )


def row_from_result(
    *,
    start_id: str,
    seed: int,
    profile_id: str,
    run_order: int,
    start_signature: str,
    result: Any,
) -> dict[str, Any]:
    activity = dict(result.mechanism_activity)
    selector = dict(activity["selector_diagnostics"])
    score_counts = dict(activity["score_counts"])
    destroy_counts = dict(activity["destroy_selection_counts"])
    dominant_destroy_count = max(destroy_counts.values(), default=0)
    actual_moves = int(activity["actual_moves"])
    selector_count = int(selector["selection_count"])
    exact_budget = (
        int(result.evaluations)
        == int(activity["candidate_scores"])
        == int(score_counts.get("candidate", 0))
        == actual_moves
        == selector_count
        == BUDGET
        and bool(selector["selection_count_closed"])
    )
    return {
        "start_id": start_id,
        "start_signature": start_signature,
        "seed": int(seed),
        "profile_id": profile_id,
        "run_order": int(run_order),
        "eval_budget": BUDGET,
        "evaluations": int(result.evaluations),
        "candidate_scores": int(activity["candidate_scores"]),
        "candidate_channel_scores": int(
            score_counts.get("candidate", 0)
        ),
        "actual_moves": actual_moves,
        "selector_selection_count": selector_count,
        "exact_budget": bool(exact_budget),
        "feasible": bool(result.feasible),
        "raw_cost": float(activity["raw_cost"]),
        "final_cost": float(result.best_cost),
        "elapsed_seconds": float(result.elapsed_seconds),
        "raw_search_elapsed_seconds": float(
            activity["raw_search_elapsed_seconds"]
        ),
        "route_count": int(result.route_count),
        "raw_signature": str(activity["raw_signature"]),
        "final_signature": str(
            activity["completed_signature"]
        ),
        "selector_kind": str(selector["selector_kind"]),
        "selector_rng_contract": str(
            selector["selection_rng_contract"]
        ),
        "completed_segments": int(
            selector.get("completed_segments", 0)
        ),
        "distinct_destroy_families_used": int(
            activity["distinct_destroy_families_used"]
        ),
        "dominant_destroy_count": int(dominant_destroy_count),
        "dominant_destroy_share": (
            float(dominant_destroy_count) / max(1, actual_moves)
        ),
        "destroy_selection_counts": json.dumps(
            destroy_counts,
            ensure_ascii=False,
            sort_keys=True,
        ),
        "pair_selection_counts": json.dumps(
            selector["pair_selection_counts"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "final_destroy_weights": json.dumps(
            selector.get("final_destroy_weights", []),
            ensure_ascii=False,
        ),
        "responsibility_updates": int(
            activity["responsibility_updates"]
        ),
        "fleet_charge_updates": int(
            activity["fleet_charge_updates"]
        ),
        "carbon_time_updates": int(
            activity["carbon_time_updates"]
        ),
        "score_counts": json.dumps(
            score_counts,
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def paired_summary(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key = {
        (
            str(row["start_id"]),
            int(row["seed"]),
            str(row["profile_id"]),
        ): row
        for row in rows
    }
    comparisons = []
    for start_id in ("CV_ONLY", "SHARED_ONE_EV"):
        for seed in SEEDS:
            control = by_key[(start_id, seed, "control_alpha")]
            candidate = by_key[
                (start_id, seed, "averaged_segmented_roulette")
            ]
            improvement = (
                (
                    float(control["final_cost"])
                    - float(candidate["final_cost"])
                )
                / float(control["final_cost"])
                * 100.0
            )
            comparisons.append(
                {
                    "start_id": start_id,
                    "seed": seed,
                    "control_cost": float(control["final_cost"]),
                    "candidate_cost": float(
                        candidate["final_cost"]
                    ),
                    "improvement_percent": float(improvement),
                    "strict_win": bool(improvement > TOL),
                    "regression_over_2_percent": bool(
                        improvement < -2.0 - TOL
                    ),
                    "wall_ratio": (
                        float(candidate["elapsed_seconds"])
                        / max(
                            1.0e-12,
                            float(control["elapsed_seconds"]),
                        )
                    ),
                    "candidate_distinct_destroy_families": int(
                        candidate[
                            "distinct_destroy_families_used"
                        ]
                    ),
                    "candidate_dominant_destroy_share": float(
                        candidate["dominant_destroy_share"]
                    ),
                    "exact_budget": bool(
                        control["exact_budget"]
                        and candidate["exact_budget"]
                    ),
                    "feasible": bool(
                        control["feasible"]
                        and candidate["feasible"]
                    ),
                }
            )
    return comparisons


def decide(
    comparisons: list[dict[str, Any]],
    failures: list[str],
) -> dict[str, Any]:
    improvements = [
        float(item["improvement_percent"])
        for item in comparisons
    ]
    wall_ratios = [
        float(item["wall_ratio"]) for item in comparisons
    ]
    strict_wins = sum(item["strict_win"] for item in comparisons)
    gates = {
        "all_arms_complete": not failures
        and len(comparisons) == 6,
        "all_feasible_and_exact_budget": bool(comparisons)
        and all(
            item["feasible"] and item["exact_budget"]
            for item in comparisons
        ),
        "strict_wins_at_least_4_of_6": strict_wins >= 4,
        "median_improvement_at_least_1_percent": (
            bool(improvements)
            and statistics.median(improvements) >= 1.0 - TOL
        ),
        "no_regression_over_2_percent": bool(comparisons)
        and not any(
            item["regression_over_2_percent"]
            for item in comparisons
        ),
        "all_candidate_runs_use_at_least_4_destroy_families": (
            bool(comparisons)
            and all(
                item["candidate_distinct_destroy_families"] >= 4
                for item in comparisons
            )
        ),
        "candidate_dominant_share_at_most_0p75": bool(comparisons)
        and all(
            item["candidate_dominant_destroy_share"] <= 0.75 + TOL
            for item in comparisons
        ),
        "median_wall_ratio_at_most_1p25": bool(wall_ratios)
        and statistics.median(wall_ratios) <= 1.25 + TOL,
        "maximum_wall_ratio_at_most_1p50": bool(wall_ratios)
        and max(wall_ratios) <= 1.50 + TOL,
    }
    passed = all(gates.values())
    return {
        "verdict": (
            "TRAINING_GO_OLD_CROSS_INSTANCE_CONFIRMATION"
            if passed
            else "TRAINING_STOP_AVERAGED_SEGMENTED_ROULETTE"
        ),
        "passed": passed,
        "gates": gates,
        "strict_win_count": strict_wins,
        "median_improvement_percent": (
            statistics.median(improvements)
            if improvements
            else None
        ),
        "worst_improvement_percent": (
            min(improvements) if improvements else None
        ),
        "median_wall_ratio": (
            statistics.median(wall_ratios)
            if wall_ratios
            else None
        ),
        "maximum_wall_ratio": (
            max(wall_ratios) if wall_ratios else None
        ),
        "failures": failures,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "next_allowed_step": (
            "old_d1_d2_cross_instance_confirmation"
            if passed
            else "context_aware_mechanism_scheduler_only"
        ),
        "claim_boundary": (
            "Known pathology instance only; passing permits old-data "
            "cross-instance confirmation, not performance claims."
        ),
    }


def render_report(
    decision: dict[str, Any],
    comparisons: list[dict[str, Any]],
) -> str:
    lines = [
        "# 经典分段轮盘：算子垄断修复门",
        "",
        f"结论：`{decision['verdict']}`。",
        "",
        "| 起点 | 种子 | 控制成本 | 候选成本 | 改善 | 墙钟比 | 候选家族数 | 最大占比 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in comparisons:
        lines.append(
            "| {start} | {seed} | {control:.6f} | "
            "{candidate:.6f} | {improvement:.6f}% | "
            "{wall:.3f} | {families} | {dominant:.3f} |".format(
                start=item["start_id"],
                seed=item["seed"],
                control=item["control_cost"],
                candidate=item["candidate_cost"],
                improvement=item["improvement_percent"],
                wall=item["wall_ratio"],
                families=item[
                    "candidate_distinct_destroy_families"
                ],
                dominant=item[
                    "candidate_dominant_destroy_share"
                ],
            )
        )
    if not comparisons:
        lines.extend(
            [
                "",
                "没有形成完整配对，按失败即停处理。",
                "",
            ]
        )
        return "\n".join(lines)
    lines.extend(
        [
            "",
            f"严格胜：{decision['strict_win_count']}/6；中位改善："
            f"{decision['median_improvement_percent']:.6f}%；"
            f"最差改善：{decision['worst_improvement_percent']:.6f}%。",
            "",
            "这是已知病灶旧题，只能筛设计，不授权阶段二、正式全量实验或外部优胜主张。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {OUT}")
    if not CONTRACT.is_file():
        raise FileNotFoundError(CONTRACT)
    starts = build_starts()
    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    failures: list[str] = []
    started = time.perf_counter()
    for start_id, initial_solution in starts.items():
        start_signature = solution_signature_hash(initial_solution)
        witnesses[start_id] = {
            "initial": solution_payload(initial_solution),
            "runs": {},
        }
        for seed in SEEDS:
            for run_order, profile_id in enumerate(
                profile_order(start_id, seed),
                start=1,
            ):
                run_id = f"{start_id}__seed{seed}__{profile_id}"
                try:
                    result = run_segmented_mechanism_alns(
                        BUNDLE,
                        seed=seed,
                        config=PROFILES[profile_id],
                        prices=PRICES,
                        initial_solution=copy.deepcopy(
                            initial_solution
                        ),
                    )
                    rows.append(
                        row_from_result(
                            start_id=start_id,
                            seed=seed,
                            profile_id=profile_id,
                            run_order=run_order,
                            start_signature=start_signature,
                            result=result,
                        )
                    )
                    witnesses[start_id]["runs"][run_id] = (
                        solution_payload(result.best_solution)
                    )
                except Exception as exc:
                    failures.append(
                        f"{run_id}:{type(exc).__name__}:{exc}"
                    )

    expected = 2 * len(SEEDS) * len(PROFILES)
    if len(rows) != expected:
        failures.append(f"completed_arms:{len(rows)}/{expected}")
    comparisons = (
        paired_summary(rows) if len(rows) == expected else []
    )
    decision = decide(comparisons, failures)
    metadata = {
        "schema_version": (
            "resetp.averaged-segmented-roulette-pathology.v1"
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_repo_relative": str(CONTRACT.relative_to(REPO)),
        "contract_sha256": sha256(CONTRACT),
        "bundle_repo_relative": str(BUNDLE.relative_to(REPO)),
        "seed_list": list(SEEDS),
        "eval_budget": BUDGET,
        "battery_kwh": PRICES.B_battery_kwh,
        "profiles": {
            key: {
                "total_eval_budget": value.total_eval_budget,
                "enable_segmented_roulette": (
                    value.enable_segmented_roulette
                ),
                "reaction": value.reaction,
                "segment_length": value.segment_length,
                "split_selector_rng": value.split_selector_rng,
            }
            for key, value in PROFILES.items()
        },
        "method_sources": [
            "doi:10.1287/trsc.1050.0135",
            "doi:10.1016/j.cor.2005.09.012",
            "doi:10.21105/joss.05028",
        ],
        "license_repo_relative": (
            "solver/src/setp_solver/algorithms/resetp_alns/runtime/"
            "LICENSE-N-WOUDA-ALNS.md"
        ),
        "source_hashes": {
            "run_segmented_pathology_gate.py": sha256(
                HERE / "run_segmented_pathology_gate.py"
            ),
            "segmented_mechanism_solver.py": sha256(
                HERE / "segmented_mechanism_solver.py"
            ),
            "select.py": sha256(
                REPO
                / "solver/src/setp_solver/algorithms/resetp_alns/"
                "runtime/select.py"
            ),
            "winner.py": sha256(
                REPO
                / "solver/src/setp_solver/algorithms/resetp_alns/"
                "kernel/winner.py"
            ),
        },
        "git_head": git_output("rev-parse", "HEAD"),
        "git_status_short": git_output("status", "--short"),
        "elapsed_seconds": time.perf_counter() - started,
        "known_pathology_training_only": True,
        "formal_l_main_activated": False,
        "stage2_activated": False,
    }

    OUT.mkdir(parents=True)
    fields = list(rows[0].keys()) if rows else [
        "start_id",
        "seed",
        "profile_id",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=fields,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(OUT / "raw_runs.csv", buffer.getvalue())
    atomic_json(OUT / "comparisons.json", comparisons)
    atomic_json(OUT / "solution_witnesses.json", witnesses)
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(OUT / "report.md", render_report(decision, comparisons))
    hashes = {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    atomic_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
