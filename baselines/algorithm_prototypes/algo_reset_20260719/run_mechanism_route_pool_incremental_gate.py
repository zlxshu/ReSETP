"""Run the pre-registered cheapest full-model route-pool incremental gate."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MECHANISM_DIR = HERE.parent / "mechanism_hgs_alns_20260718"
for path in (HERE, MECHANISM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mechanism_route_pool_fusion import fuse_route_sources  # noqa: E402
from prototype import run_pure_alns  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from v2_solver import run_official_hgs_neutral  # noqa: E402


OUTPUT = HERE / "mechanism_route_pool_incremental_gate"
MULTIDEPOT = (
    REPO
    / "models/data_bundle/generated_instances/L-main_mixed23_archive_20260709"
)
TASKS = ("L-main-multidepot-25c-01", "L-main-multidepot-50c-01")
SEED = 1
ALNS_EVALUATIONS = 20
HGS_ADAPTER_CALLS = 1
HGS_NO_IMPROVEMENT = 100
POOL_TIME_LIMIT_SECONDS = 2.0
TOL = 1.0e-9


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=REPO,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _activity_count(activity: dict[str, Any], section: str) -> int:
    value = activity.get(section, {})
    return int(value.get("improvements", 0)) if isinstance(value, dict) else 0


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    started = time.time()
    rows: list[dict[str, Any]] = []

    for task in TASKS:
        bundle = MULTIDEPOT / task
        hgs = run_official_hgs_neutral(
            bundle,
            seed=SEED,
            eval_budget=HGS_ADAPTER_CALLS,
            prices=DEFAULT_PRICES,
            no_improvement_iterations=HGS_NO_IMPROVEMENT,
        )
        alns = run_pure_alns(
            bundle,
            seed=SEED,
            eval_budget=ALNS_EVALUATIONS,
            prices=DEFAULT_PRICES,
        )
        fusion = fuse_route_sources(
            bundle,
            hgs_solution=hgs.best_solution,
            alns_solution=alns.best_solution,
            prices=DEFAULT_PRICES,
            time_limit_seconds=POOL_TIME_LIMIT_SECONDS,
        )
        selected = (
            list(fusion.recombination.selected_sources)
            if fusion.recombination is not None
            else []
        )
        selected_set = set(selected)
        genuinely_mixed = selected_set == {
            "hgs_adapter_route_source",
            "alns_route_source",
        }
        pool_cost = (
            float(fusion.pool_expert.objective)
            if fusion.pool_expert is not None
            else None
        )
        strict_double_win = bool(
            genuinely_mixed
            and pool_cost is not None
            and pool_cost < fusion.hgs_expert.objective - TOL
            and pool_cost < fusion.alns_expert.objective - TOL
        )
        rows.append(
            {
                "task": task,
                "seed": SEED,
                "hgs_adapter_calls": HGS_ADAPTER_CALLS,
                "hgs_internal_no_improvement_iterations": HGS_NO_IMPROVEMENT,
                "alns_complete_evaluations": int(alns.evaluations),
                "hgs_source_cost": float(hgs.best_cost),
                "alns_source_cost": float(alns.best_cost),
                "hgs_after_shared_experts": float(
                    fusion.hgs_expert.objective
                ),
                "alns_after_shared_experts": float(
                    fusion.alns_expert.objective
                ),
                "pool_after_shared_experts": pool_cost,
                "hgs_expert_improvement": float(
                    hgs.best_cost - fusion.hgs_expert.objective
                ),
                "alns_expert_improvement": float(
                    alns.best_cost - fusion.alns_expert.objective
                ),
                "selected_hgs_routes": selected.count(
                    "hgs_adapter_route_source"
                ),
                "selected_alns_routes": selected.count("alns_route_source"),
                "candidate_route_count": (
                    int(fusion.recombination.candidate_route_count)
                    if fusion.recombination is not None
                    else 0
                ),
                "genuinely_mixed": genuinely_mixed,
                "strict_double_win": strict_double_win,
                "pool_feasible": bool(
                    fusion.pool_expert is not None
                    and fusion.pool_expert.feasible
                ),
                "pool_error": fusion.pool_error or "",
                "hgs_responsibility_improvements": _activity_count(
                    fusion.hgs_expert.activity,
                    "responsibility",
                ),
                "hgs_joint_improvements": _activity_count(
                    fusion.hgs_expert.activity,
                    "joint",
                ),
                "hgs_carbon_improvements": _activity_count(
                    fusion.hgs_expert.activity,
                    "carbon",
                ),
                "alns_responsibility_improvements": _activity_count(
                    fusion.alns_expert.activity,
                    "responsibility",
                ),
                "alns_joint_improvements": _activity_count(
                    fusion.alns_expert.activity,
                    "joint",
                ),
                "alns_carbon_improvements": _activity_count(
                    fusion.alns_expert.activity,
                    "carbon",
                ),
            }
        )

    with (OUTPUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    positive_tasks = [
        str(row["task"]) for row in rows if bool(row["strict_double_win"])
    ]
    if positive_tasks:
        verdict = "GO_FRESH_RESULT_BLIND_CONFIRMATION_REQUIRED"
        reason = (
            "At least one pre-registered screening task used routes from both "
            "sources and strictly beat both expert-processed parents. Old "
            "tasks remain screening-only."
        )
    else:
        verdict = "STOP_ROUTE_POOL_FUSION_NO_STRONG_INCREMENTAL_SIGNAL"
        reason = (
            "Neither pre-registered task produced a genuinely mixed route "
            "pool that strictly beat both expert-processed parents."
        )

    metadata = {
        "schema_version": "mechanism-route-pool-incremental-gate.v1",
        "purpose": "screening_only_not_formal_benchmark",
        "tasks": list(TASKS),
        "seed": SEED,
        "alns_complete_evaluations": ALNS_EVALUATIONS,
        "hgs_adapter_calls": HGS_ADAPTER_CALLS,
        "hgs_internal_no_improvement_iterations": HGS_NO_IMPROVEMENT,
        "pool_time_limit_seconds": POOL_TIME_LIMIT_SECONDS,
        "hgs_identity_boundary": (
            "route source only; not a fair complete-model pure-HGS arm"
        ),
        "confirmation_set": "not_created_or_run",
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "python": sys.version,
        "platform": platform.platform(),
        "started_unix": started,
        "finished_unix": time.time(),
        "protected_files_modified_by_task": False,
    }
    decision = {
        "verdict": verdict,
        "reason": reason,
        "positive_tasks": positive_tasks,
        "strong_positive_count": len(positive_tasks),
        "task_count": len(rows),
        "formal_search_allowed": False,
        "formal_solver_integration_allowed": False,
        "stage2_allowed": False,
        "full_benchmark_allowed": False,
        "next_action": (
            "freeze a genuinely new result-blind rich development set"
            if positive_tasks
            else "stop this route-pool design; do not tune on these tasks"
        ),
    }
    _write_json(OUTPUT / "metadata.json", metadata)
    _write_json(OUTPUT / "decision.json", decision)

    lines = [
        "# 机制路线仓库最低成本增量门",
        "",
        f"判定：`{verdict}`。",
        "",
        reason,
        "",
        "本门只回答路线仓库是否在旧开发题上出现增量信号。HGS "
        "适配器只提供路线，不是公平的完整模型 HGS 基线；本结果不能写入"
        "正式 E2 或论文性能表。",
        "",
        "|题目|HGS+专家|ALNS+专家|路线仓库+专家|HGS路线|ALNS路线|严格双胜|",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        pool = (
            "NA"
            if row["pool_after_shared_experts"] is None
            else f"{float(row['pool_after_shared_experts']):.9f}"
        )
        lines.append(
            f"|{row['task']}|"
            f"{float(row['hgs_after_shared_experts']):.9f}|"
            f"{float(row['alns_after_shared_experts']):.9f}|{pool}|"
            f"{row['selected_hgs_routes']}|{row['selected_alns_routes']}|"
            f"{row['strict_double_win']}|"
        )
    lines.extend(
        [
            "",
            "停止纪律：若本门失败，不在这两题上改路线分数、仓库大小或"
            "题目；若本门出现阳性，也只能先冻结一组从未看过结果的新富模型"
            "题，再做三种子确认。",
            "",
        ]
    )
    (OUTPUT / "report.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    evidence_files = [
        OUTPUT / "metadata.json",
        OUTPUT / "raw_runs.csv",
        OUTPUT / "decision.json",
        OUTPUT / "report.md",
    ]
    _write_json(
        OUTPUT / "artifact_hashes.json",
        {
            path.name: _sha(path)
            for path in evidence_files
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
