#!/usr/bin/env python3
"""Run the pre-registered donor-03 initial-pool diagnosis gate."""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import (  # noqa: E402
    POOL_SIZE,
    build_and_score_initial_pool,
    result_rows,
    solution_payload,
)
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from terminal_completion import apply_terminal_completion  # noqa: E402


BUNDLES = HERE / "blind_d1_bundles"
OUT = HERE / "initial_pool_gate_d1"
CONTRACT = REPO / "docs/handoff/unified_mechanism_alns_execution_contract_20260719.md"
SEED = 1
ARCHIVE_CAPACITY = 6
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
TOL = 1.0e-9
MIN_UNIQUE_ROUTE_STRUCTURES = 6
MIN_ARCHIVE_STRUCTURES = 4
MIN_ARCHIVE_FAMILIES = 2
MIN_MEDIAN_IMPROVEMENT_PERCENT = 0.5


SOURCE_FILES = (
    HERE / "initial_pool.py",
    HERE / "terminal_completion.py",
    HERE / "run_initial_pool_gate.py",
    LEGACY / "v5_carbon_retiming_solver.py",
    LEGACY / "v6_monotone_mechanism_solver.py",
    LEGACY / "v7_responsibility_solver.py",
    CONTRACT,
)
PROTECTED_FILES = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def combined_hash(paths: tuple[Path, ...]) -> str:
    return sha_json(
        [
            {
                "path": str(path.relative_to(REPO)),
                "sha256": sha256(path),
            }
            for path in paths
        ]
    )


def make_blind_lock(
    dataset_manifest: dict[str, Any],
    run_order: list[str],
) -> dict[str, Any]:
    candidate_paths = SOURCE_FILES[:3]
    adapter_paths = SOURCE_FILES[3:6]
    parameters = {
        "seed": SEED,
        "pool_size": POOL_SIZE,
        "archive_capacity": ARCHIVE_CAPACITY,
        "battery_kwh": PRICES.B_battery_kwh,
        "minimum_unique_route_structures": MIN_UNIQUE_ROUTE_STRUCTURES,
        "minimum_archive_structures": MIN_ARCHIVE_STRUCTURES,
        "minimum_archive_families": MIN_ARCHIVE_FAMILIES,
        "minimum_median_improvement_percent": MIN_MEDIAN_IMPROVEMENT_PERCENT,
        "strict_improvement_required_each_instance": True,
        "terminal_nonloss_required_each_instance": True,
    }
    return {
        "schema_version": "resetp.unified-mechanism-alns.blind-lock.v1",
        "created_before_algorithm_scores": True,
        "candidate_sha256": combined_hash(candidate_paths),
        "parameter_sha256": sha_json(parameters),
        "parameters": parameters,
        "dataset_manifest_sha256": sha256(BUNDLES / "manifest.json"),
        "source_adapter_sha256": combined_hash(adapter_paths),
        "contract_sha256": sha256(CONTRACT),
        "seeds": [SEED],
        "arms": [
            "default_regret2_initial",
            "frozen_twelve_start_pool",
            "default_plus_common_terminal_completion",
            "pool_winner_plus_common_terminal_completion",
        ],
        "thresholds": {
            "strict_win_tolerance": TOL,
            "median_improvement_percent_minimum": MIN_MEDIAN_IMPROVEMENT_PERCENT,
            "unique_route_structures_each_minimum": MIN_UNIQUE_ROUTE_STRUCTURES,
        },
        "run_order": run_order,
        "run_order_sha256": sha_json(run_order),
        "protected_file_sha256": {
            str(path.relative_to(REPO)): sha256(path)
            for path in PROTECTED_FILES
        },
        "dataset_instance_ids": [
            item["instance_id"] for item in dataset_manifest["instances"]
        ],
    }


def validate_lock(lock: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if lock["candidate_sha256"] != combined_hash(SOURCE_FILES[:3]):
        failures.append("candidate_sha256")
    if lock["source_adapter_sha256"] != combined_hash(SOURCE_FILES[3:6]):
        failures.append("source_adapter_sha256")
    if lock["contract_sha256"] != sha256(CONTRACT):
        failures.append("contract_sha256")
    if lock["dataset_manifest_sha256"] != sha256(BUNDLES / "manifest.json"):
        failures.append("dataset_manifest_sha256")
    for relative, expected in lock["protected_file_sha256"].items():
        if sha256(REPO / relative) != expected:
            failures.append(f"protected:{relative}")
    return failures


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite frozen gate output: {OUT}")
    manifest_path = BUNDLES / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"build result-blind D1 bundles first: {manifest_path}"
        )
    dataset_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    instance_rows = {
        str(item["instance_id"]): item
        for item in dataset_manifest["instances"]
    }
    run_order = sorted(
        instance_rows,
        key=lambda instance_id: sha_json(
            {
                "instance_id": instance_id,
                "seed": SEED,
                "gate": "initial_pool_d1",
            }
        ),
    )
    OUT.mkdir(parents=True)
    blind_lock = make_blind_lock(dataset_manifest, run_order)
    atomic_json(OUT / "blind_lock.json", blind_lock)

    started = time.perf_counter()
    raw_rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    run_failures: list[str] = []
    for instance_id in run_order:
        bundle_dir = BUNDLES / instance_id
        dataset_row = instance_rows[instance_id]
        try:
            pool = build_and_score_initial_pool(
                bundle_dir,
                seed=SEED,
                prices=PRICES,
                archive_capacity=ARCHIVE_CAPACITY,
            )
            rows = result_rows(pool)
            for row in rows:
                raw_rows.append(
                    {
                        "instance_id": instance_id,
                        "source_scale": int(dataset_row["source_scale"]),
                        "actual_customer_count": int(
                            dataset_row["actual_customer_count"]
                        ),
                        "actual_depot_count": int(
                            dataset_row["actual_depot_count"]
                        ),
                        "seed": SEED,
                        **row,
                    }
                )

            anchor_terminal = apply_terminal_completion(
                bundle_dir,
                pool.anchor.solution,
                prices=PRICES,
            )
            winner_terminal = apply_terminal_completion(
                bundle_dir,
                pool.best.solution,
                prices=PRICES,
            )
            if not anchor_terminal.feasible or not winner_terminal.feasible:
                raise RuntimeError("common terminal completion returned an infeasible solution")

            unique_routes = len({item.route_signature for item in pool.entries})
            archive_unique_routes = len(
                {item.route_signature for item in pool.archive}
            )
            archive_families = len({item.family for item in pool.archive})
            improvement_percent = (
                (pool.anchor.raw_cost - pool.best.raw_cost)
                / pool.anchor.raw_cost
                * 100.0
            )
            terminal_improvement_percent = (
                (anchor_terminal.cost - winner_terminal.cost)
                / anchor_terminal.cost
                * 100.0
            )
            comparison = {
                "instance_id": instance_id,
                "source_scale": int(dataset_row["source_scale"]),
                "actual_customer_count": int(
                    dataset_row["actual_customer_count"]
                ),
                "actual_depot_count": int(dataset_row["actual_depot_count"]),
                "seed": SEED,
                "anchor_label": pool.anchor.label,
                "winner_label": pool.best.label,
                "winner_family": pool.best.family,
                "anchor_raw_cost": pool.anchor.raw_cost,
                "winner_raw_cost": pool.best.raw_cost,
                "raw_improvement_percent": improvement_percent,
                "strict_raw_win": pool.best.raw_cost < pool.anchor.raw_cost - TOL,
                "anchor_terminal_cost": anchor_terminal.cost,
                "winner_terminal_cost": winner_terminal.cost,
                "terminal_improvement_percent": terminal_improvement_percent,
                "terminal_nonloss": (
                    winner_terminal.cost <= anchor_terminal.cost + TOL
                ),
                "unique_route_structures": unique_routes,
                "archive_unique_route_structures": archive_unique_routes,
                "archive_family_count": archive_families,
                "archive_labels": [item.label for item in pool.archive],
                "initial_pool_candidate_evals": pool.candidate_evaluations,
                "initial_pool_reference_replays": pool.reference_replays,
                "terminal_full_solution_replays": int(
                    anchor_terminal.activity["full_solution_replays"]
                    + winner_terminal.activity["full_solution_replays"]
                ),
                "terminal_route_local_exact_evaluations": int(
                    anchor_terminal.activity["route_local_exact_evaluations"]
                    + winner_terminal.activity["route_local_exact_evaluations"]
                ),
                "terminal_route_proxy_evaluations": int(
                    anchor_terminal.activity["route_proxy_evaluations"]
                    + winner_terminal.activity["route_proxy_evaluations"]
                ),
                "terminal_route_local_schedule_evaluations": int(
                    anchor_terminal.activity[
                        "route_local_schedule_evaluations"
                    ]
                    + winner_terminal.activity[
                        "route_local_schedule_evaluations"
                    ]
                ),
                "full_solution_replays_total": int(
                    POOL_SIZE
                    + anchor_terminal.activity["full_solution_replays"]
                    + winner_terminal.activity["full_solution_replays"]
                ),
                "construction_attempts": pool.construction_attempts,
                "construction_failure_count": len(pool.construction_failures),
                "score_counts": pool.score_counts,
                "anchor_terminal_selected_branch": (
                    anchor_terminal.selected_branch
                ),
                "winner_terminal_selected_branch": (
                    winner_terminal.selected_branch
                ),
                "anchor_terminal_activity": anchor_terminal.activity,
                "winner_terminal_activity": winner_terminal.activity,
            }
            comparisons.append(comparison)
            witnesses[instance_id] = {
                "anchor_initial": solution_payload(pool.anchor.solution),
                "winner_initial": solution_payload(pool.best.solution),
                "anchor_terminal": solution_payload(anchor_terminal.solution),
                "winner_terminal": solution_payload(winner_terminal.solution),
            }
        except Exception as exc:
            run_failures.append(
                f"{instance_id}:{type(exc).__name__}:{exc}"
            )

    lock_failures = validate_lock(blind_lock)
    raw_strict = (
        len(comparisons) == len(run_order)
        and all(item["strict_raw_win"] for item in comparisons)
    )
    median_improvement = (
        statistics.median(
            item["raw_improvement_percent"] for item in comparisons
        )
        if comparisons
        else float("-inf")
    )
    diversity_pass = (
        len(comparisons) == len(run_order)
        and all(
            item["unique_route_structures"] >= MIN_UNIQUE_ROUTE_STRUCTURES
            and item["archive_unique_route_structures"]
            >= MIN_ARCHIVE_STRUCTURES
            and item["archive_family_count"] >= MIN_ARCHIVE_FAMILIES
            for item in comparisons
        )
    )
    terminal_pass = (
        len(comparisons) == len(run_order)
        and all(item["terminal_nonloss"] for item in comparisons)
    )
    ledger_pass = (
        len(comparisons) == len(run_order)
        and all(
            item["initial_pool_candidate_evals"] == POOL_SIZE - 1
            and item["initial_pool_reference_replays"] == 1
            and item["construction_failure_count"] == 0
            for item in comparisons
        )
    )
    nondefault_winner = any(
        item["winner_label"] != "default_regret2"
        for item in comparisons
    )
    strong_positive = (
        not run_failures
        and not lock_failures
        and raw_strict
        and median_improvement >= MIN_MEDIAN_IMPROVEMENT_PERCENT
        and diversity_pass
        and terminal_pass
        and ledger_pass
        and nondefault_winner
    )
    if lock_failures:
        verdict = "INVALID_GATE_POST_LOCK_MUTATION"
    elif strong_positive:
        verdict = "GO_EMBED_DIVERSE_INITIAL_POOL"
    else:
        verdict = "STOP_DIVERSE_INITIAL_POOL"

    decision = {
        "verdict": verdict,
        "strong_positive": strong_positive,
        "instance_count": len(run_order),
        "completed_instance_count": len(comparisons),
        "strict_raw_win_count": sum(
            bool(item["strict_raw_win"]) for item in comparisons
        ),
        "terminal_nonloss_count": sum(
            bool(item["terminal_nonloss"]) for item in comparisons
        ),
        "median_raw_improvement_percent": median_improvement,
        "diversity_pass": diversity_pass,
        "ledger_pass": ledger_pass,
        "nondefault_winner_present": nondefault_winner,
        "run_failures": run_failures,
        "lock_failures": lock_failures,
        "predeclared_gate": {
            "strict_raw_win_required_each_instance": True,
            "median_raw_improvement_percent_minimum": (
                MIN_MEDIAN_IMPROVEMENT_PERCENT
            ),
            "unique_route_structures_each_minimum": (
                MIN_UNIQUE_ROUTE_STRUCTURES
            ),
            "archive_unique_route_structures_each_minimum": (
                MIN_ARCHIVE_STRUCTURES
            ),
            "archive_family_count_each_minimum": MIN_ARCHIVE_FAMILIES,
            "terminal_nonloss_required_each_instance": True,
            "initial_pool_candidate_evals_required": POOL_SIZE - 1,
        },
        "claim_boundary": (
            "Initial-construction diagnosis only. Passing authorizes an "
            "equal-total-budget continuous-ALNS development gate, not Stage 2 "
            "or any formal experiment."
        ),
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.unified-mechanism-alns.initial-pool-gate.v1",
        "started_after_blind_lock": True,
        "run_order": run_order,
        "seed": SEED,
        "pool_size": POOL_SIZE,
        "archive_capacity": ARCHIVE_CAPACITY,
        "battery_kwh": PRICES.B_battery_kwh,
        "dataset_manifest_sha256": sha256(manifest_path),
        "blind_lock_sha256": sha256(OUT / "blind_lock.json"),
        "elapsed_seconds": time.perf_counter() - started,
        "protected_files_unchanged": not any(
            item.startswith("protected:") for item in lock_failures
        ),
        "formal_l_main_activated": False,
        "stage2_activated": False,
    }

    raw_fields = [
        "instance_id",
        "source_scale",
        "actual_customer_count",
        "actual_depot_count",
        "seed",
        "label",
        "family",
        "type_mode",
        "objective",
        "raw_cost",
        "feasible",
        "violation_count",
        "route_count",
        "ev_route_count",
        "charging_action_count",
        "full_signature",
        "route_signature",
        "in_archive",
        "is_anchor",
        "is_best",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=raw_fields)
    writer.writeheader()
    writer.writerows(raw_rows)
    atomic_text(OUT / "raw_runs.csv", buffer.getvalue())
    atomic_json(OUT / "comparisons.json", comparisons)
    atomic_json(OUT / "solution_witnesses.json", witnesses)
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)

    lines = [
        "# 真正多样初解池：D1 最小门",
        "",
        f"结论：`{verdict}`。",
        "",
        (
            f"两份新鲜开发题完成 {len(comparisons)}/{len(run_order)}；"
            f"原始初解严格胜 {decision['strict_raw_win_count']}/{len(run_order)}；"
            f"共同终局处理后不退步 {decision['terminal_nonloss_count']}/{len(run_order)}；"
            f"原始成本中位改善 {median_improvement:.6f}% 。"
        ),
        "",
        "这张门只检验真正不同的构造起点。十二选一阶段没有运行短 ALNS，"
        "也没有调用终局机制栈；默认起点和新赢家只在选完后各走一次相同终局处理。",
        "",
        "本结果不授权阶段二，不授权正式 E2--E7 或全量 benchmark。",
    ]
    if run_failures:
        lines.extend(["", "运行失败：" + " | ".join(run_failures)])
    if lock_failures:
        lines.extend(["", "锁失败：" + " | ".join(lock_failures)])
    atomic_text(OUT / "report.md", "\n".join(lines) + "\n")

    hashes = {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    atomic_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not run_failures and not lock_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
