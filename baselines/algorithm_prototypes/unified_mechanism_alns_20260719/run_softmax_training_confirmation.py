#!/usr/bin/env python3
"""Run the locked four-instance selector training confirmation."""

from __future__ import annotations

import copy
import csv
from dataclasses import asdict, replace
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

from dual_basin_solver import build_v7_warm  # noqa: E402
from initial_pool import solution_payload  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from softmax_mechanism_solver import (  # noqa: E402
    SoftmaxMechanismConfig,
    run_softmax_mechanism_alns,
)


CONTRACT = (
    REPO
    / "docs/handoff/softmax_mechanism_training_contract_20260719.md"
)
OUT = HERE / "softmax_training_confirmation"
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
SEED = 1
BUDGET = 100
TOL = 1.0e-9

BUNDLES = (
    (
        "DEV-INIT-D1-DONOR03-SRC25-N54-DEP2",
        HERE
        / "blind_d1_bundles/DEV-INIT-D1-DONOR03-SRC25-N54-DEP2",
    ),
    (
        "DEV-INIT-D1-DONOR03-SRC50-N108-DEP2",
        HERE
        / "blind_d1_bundles/DEV-INIT-D1-DONOR03-SRC50-N108-DEP2",
    ),
    (
        "DEV-DUAL-D2-GROUP456-SRC10-N21-DEP2",
        HERE
        / "fresh_d2_bundles/DEV-DUAL-D2-GROUP456-SRC10-N21-DEP2",
    ),
    (
        "DEV-DUAL-D2-GROUP789-SRC15-N34-DEP2",
        HERE
        / "fresh_d2_bundles/DEV-DUAL-D2-GROUP789-SRC15-N34-DEP2",
    ),
)

POLICIES = {
    "control_alpha": SoftmaxMechanismConfig(
        total_eval_budget=BUDGET,
        enable_softmax=False,
        temperature_start=1.0,
        temperature_end=1.0,
        split_selector_rng=True,
    ),
    "softmax_linear_1_to_0p1": SoftmaxMechanismConfig(
        total_eval_budget=BUDGET,
        enable_softmax=True,
        temperature_start=1.0,
        temperature_end=0.1,
        split_selector_rng=True,
    ),
    "softmax_fixed_1": SoftmaxMechanismConfig(
        total_eval_budget=BUDGET,
        enable_softmax=True,
        temperature_start=1.0,
        temperature_end=1.0,
        split_selector_rng=True,
    ),
}

RUN_ORDERS = {
    BUNDLES[0][0]: (
        "control_alpha",
        "softmax_linear_1_to_0p1",
        "softmax_fixed_1",
    ),
    BUNDLES[1][0]: (
        "softmax_fixed_1",
        "softmax_linear_1_to_0p1",
        "control_alpha",
    ),
    BUNDLES[2][0]: (
        "control_alpha",
        "softmax_fixed_1",
        "softmax_linear_1_to_0p1",
    ),
    BUNDLES[3][0]: (
        "softmax_linear_1_to_0p1",
        "softmax_fixed_1",
        "control_alpha",
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


def row_from_result(
    *,
    instance_id: str,
    policy_id: str,
    run_order: int,
    result: Any,
) -> dict[str, Any]:
    activity = dict(result.mechanism_activity)
    selector = dict(activity["selector_diagnostics"])
    score_counts = dict(activity["score_counts"])
    actual_moves = int(activity["alns_actual_moves"])
    selector_selection_count = int(selector["selection_count"])
    selector_count_closed = bool(
        selector["selection_count_closed"]
    )
    exact_budget = (
        int(result.evaluations)
        == int(activity["candidate_scores"])
        == int(score_counts.get("candidate", -1))
        == actual_moves
        == selector_selection_count
        == BUDGET
        and selector_count_closed
    )
    return {
        "instance_id": instance_id,
        "policy_id": policy_id,
        "run_order": int(run_order),
        "seed": SEED,
        "eval_budget": BUDGET,
        "evaluations": int(result.evaluations),
        "candidate_scores": int(activity["candidate_scores"]),
        "candidate_channel_scores": int(
            score_counts.get("candidate", 0)
        ),
        "reference_scores": int(score_counts.get("reference", 0)),
        "repair_delta_count": int(activity["repair_delta_count"]),
        "actual_moves": actual_moves,
        "exact_budget": bool(exact_budget),
        "feasible": bool(result.feasible),
        "best_cost": float(result.best_cost),
        "raw_cost": float(activity["raw_cost"]),
        "elapsed_seconds": float(result.elapsed_seconds),
        "raw_search_elapsed_seconds": float(
            activity["raw_search_elapsed_seconds"]
        ),
        "terminal_completion_elapsed_seconds": float(
            activity["terminal_completion_elapsed_seconds"]
        ),
        "route_count": int(result.route_count),
        "raw_signature": str(activity["raw_signature"]),
        "completed_signature": str(activity["completed_signature"]),
        "history_fingerprint": str(
            activity["main_search_history_fingerprint"]
        ),
        "selector_kind": str(selector["selector_kind"]),
        "selector_rng_contract": str(
            selector["selection_rng_contract"]
        ),
        "selector_selection_count": selector_selection_count,
        "selector_count_closed": selector_count_closed,
        "softmax_sample_count": int(
            selector["softmax_sample_count"]
        ),
        "forced_cross_depot_count": int(
            selector["forced_cross_depot_count"]
        ),
        "first_temperature": selector["first_temperature"],
        "final_temperature": selector["final_temperature"],
        "mean_temperature": selector["mean_temperature"],
        "distinct_destroy_families_used": int(
            activity["distinct_destroy_families_used"]
        ),
        "destroy_selection_counts": json.dumps(
            activity["destroy_selection_counts"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "pair_selection_counts": json.dumps(
            selector["pair_selection_counts"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "score_counts": json.dumps(
            score_counts,
            ensure_ascii=False,
            sort_keys=True,
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
    }


def evaluate_policy(
    policy_id: str,
    rows_by_key: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    comparisons = []
    for instance_id, _ in BUNDLES:
        control = rows_by_key[(instance_id, "control_alpha")]
        candidate = rows_by_key[(instance_id, policy_id)]
        improvement = (
            (float(control["best_cost"]) - float(candidate["best_cost"]))
            / float(control["best_cost"])
            * 100.0
        )
        wall_ratio = (
            float(candidate["elapsed_seconds"])
            / max(1.0e-12, float(control["elapsed_seconds"]))
        )
        comparisons.append(
            {
                "instance_id": instance_id,
                "control_cost": float(control["best_cost"]),
                "candidate_cost": float(candidate["best_cost"]),
                "improvement_percent": float(improvement),
                "strict_win": bool(improvement > TOL),
                "regression_over_0p25_percent": bool(
                    improvement < -0.25 - TOL
                ),
                "wall_ratio": float(wall_ratio),
                "exact_budget": bool(
                    control["exact_budget"]
                    and candidate["exact_budget"]
                ),
                "feasible": bool(
                    control["feasible"] and candidate["feasible"]
                ),
            }
        )
    wins = sum(item["strict_win"] for item in comparisons)
    improvements = [
        float(item["improvement_percent"])
        for item in comparisons
    ]
    wall_ratios = [
        float(item["wall_ratio"])
        for item in comparisons
    ]
    eligible = (
        wins >= 3
        and not any(
            item["regression_over_0p25_percent"]
            for item in comparisons
        )
        and all(item["exact_budget"] for item in comparisons)
        and all(item["feasible"] for item in comparisons)
        and max(wall_ratios) <= 3.0 + TOL
        and statistics.median(wall_ratios) <= 2.0 + TOL
    )
    return {
        "policy_id": policy_id,
        "eligible": bool(eligible),
        "strict_win_count": int(wins),
        "worst_improvement_percent": min(improvements),
        "median_improvement_percent": statistics.median(
            improvements
        ),
        "median_wall_ratio": statistics.median(wall_ratios),
        "maximum_wall_ratio": max(wall_ratios),
        "comparisons": comparisons,
    }


def selection_key(summary: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(summary["strict_win_count"]),
        float(summary["worst_improvement_percent"]),
        float(summary["median_improvement_percent"]),
        -float(summary["median_wall_ratio"]),
        int(summary["policy_id"] == "softmax_fixed_1"),
    )


def render_report(
    decision: dict[str, Any],
    policy_summaries: list[dict[str, Any]],
) -> str:
    lines = [
        "# 机制均衡 ALNS：旧题训练确认",
        "",
        f"结论：`{decision['verdict']}`。",
        "",
        "这四道题都是旧开发题，只用于选择设计，不能确认最终性能。",
        "",
        "| 版本 | 严格胜 | 最差改善 | 中位改善 | 中位墙钟比 | 最大墙钟比 | 合格 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in policy_summaries:
        lines.append(
            "| {policy} | {wins}/4 | {worst:.6f}% | "
            "{median:.6f}% | {wall:.3f} | {wall_max:.3f} | "
            "{eligible} |".format(
                policy=item["policy_id"],
                wins=item["strict_win_count"],
                worst=item["worst_improvement_percent"],
                median=item["median_improvement_percent"],
                wall=item["median_wall_ratio"],
                wall_max=item["maximum_wall_ratio"],
                eligible="是" if item["eligible"] else "否",
            )
        )
    lines.extend(
        [
            "",
            "本门不授权多种子、全量实验或阶段二。若冻结了候选，下一步只允许先修复开源对照健康性，再申请一次预锁定未出分的定向开发门。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if OUT.exists():
        raise FileExistsError(
            f"refusing to overwrite training evidence: {OUT}"
        )
    if not CONTRACT.is_file():
        raise FileNotFoundError(CONTRACT)

    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    failures: list[str] = []
    started = time.perf_counter()
    for instance_id, bundle_dir in BUNDLES:
        try:
            bundle = load_search_bundle(bundle_dir)
            warm = build_v7_warm(bundle, prices=PRICES)
            witnesses[instance_id] = {
                "warm_start": solution_payload(warm),
                "policies": {},
            }
            for run_order, policy_id in enumerate(
                RUN_ORDERS[instance_id],
                start=1,
            ):
                result = run_softmax_mechanism_alns(
                    bundle_dir,
                    seed=SEED,
                    config=POLICIES[policy_id],
                    prices=PRICES,
                    initial_solution=copy.deepcopy(warm),
                )
                row = row_from_result(
                    instance_id=instance_id,
                    policy_id=policy_id,
                    run_order=run_order,
                    result=result,
                )
                rows.append(row)
                witnesses[instance_id]["policies"][policy_id] = (
                    solution_payload(result.best_solution)
                )
        except Exception as exc:
            failures.append(
                f"{instance_id}:{type(exc).__name__}:{exc}"
            )

    rows_by_key = {
        (str(row["instance_id"]), str(row["policy_id"])): row
        for row in rows
    }
    expected_keys = {
        (instance_id, policy_id)
        for instance_id, _ in BUNDLES
        for policy_id in POLICIES
    }
    missing_keys = sorted(expected_keys - set(rows_by_key))
    if missing_keys:
        failures.append(f"missing_arms:{missing_keys}")

    policy_summaries: list[dict[str, Any]] = []
    if not missing_keys:
        policy_summaries = [
            evaluate_policy(policy_id, rows_by_key)
            for policy_id in (
                "softmax_linear_1_to_0p1",
                "softmax_fixed_1",
            )
        ]
    eligible = [
        item for item in policy_summaries if item["eligible"]
    ]
    selected = (
        max(eligible, key=selection_key)
        if eligible and not failures
        else None
    )
    verdict = (
        f"TRAINING_FREEZE_{selected['policy_id'].upper()}"
        if selected is not None
        else "TRAINING_STOP_SOFTMAX_MECHANISM"
    )
    decision = {
        "verdict": verdict,
        "training_signal": selected is not None,
        "selected_policy": (
            selected["policy_id"] if selected is not None else None
        ),
        "policy_summaries": policy_summaries,
        "failures": failures,
        "missing_arms": missing_keys,
        "dataset_already_seen": True,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "next_allowed_step": (
            "repair_external_baseline_health_then_request_targeted_gate"
            if selected is not None
            else "stop_selector_line"
        ),
        "claim_boundary": (
            "Old D1/D2 development data only. This can freeze one design "
            "but cannot confirm final performance or external dominance."
        ),
    }

    metadata = {
        "schema_version": (
            "resetp.softmax-mechanism-training-confirmation.v1"
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_repo_relative": str(CONTRACT.relative_to(REPO)),
        "contract_sha256": sha256(CONTRACT),
        "instances": [
            {
                "instance_id": instance_id,
                "bundle_repo_relative": str(bundle_dir.relative_to(REPO)),
            }
            for instance_id, bundle_dir in BUNDLES
        ],
        "policies": {
            policy_id: asdict(config)
            for policy_id, config in POLICIES.items()
        },
        "run_orders": {
            key: list(value) for key, value in RUN_ORDERS.items()
        },
        "seed": SEED,
        "eval_budget": BUDGET,
        "battery_kwh": PRICES.B_battery_kwh,
        "selector_source": (
            "N-Wouda/alns AlphaUCB adaptation plus project Softmax "
            "extension"
        ),
        "license_repo_relative": (
            "solver/src/setp_solver/algorithms/resetp_alns/runtime/"
            "LICENSE-N-WOUDA-ALNS.md"
        ),
        "source_hashes": {
            "softmax_mechanism_solver.py": sha256(
                HERE / "softmax_mechanism_solver.py"
            ),
            "winner.py": sha256(
                REPO
                / "solver/src/setp_solver/algorithms/resetp_alns/"
                "kernel/winner.py"
            ),
            "alns_core.py": sha256(
                REPO
                / "solver/src/setp_solver/algorithms/resetp_alns/"
                "kernel/alns_core.py"
            ),
            "select.py": sha256(
                REPO
                / "solver/src/setp_solver/algorithms/resetp_alns/"
                "runtime/select.py"
            ),
        },
        "git_head": git_output("rev-parse", "HEAD"),
        "git_status_short": git_output("status", "--short"),
        "elapsed_seconds": time.perf_counter() - started,
        "formal_l_main_activated": False,
        "stage2_activated": False,
    }

    OUT.mkdir(parents=True)
    fields = list(rows[0].keys()) if rows else [
        "instance_id",
        "policy_id",
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
    atomic_json(OUT / "comparisons.json", policy_summaries)
    atomic_json(OUT / "solution_witnesses.json", witnesses)
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(
        OUT / "report.md",
        render_report(decision, policy_summaries),
    )
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
