"""One-seed fresh-bundle gate for mechanism-normalised ALNS acceptance."""

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

from mechanism_normalized_alns import (  # noqa: E402
    run_mechanism_normalized_alns,
)
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from v7_responsibility_solver import run_mechanism_alns_v7  # noqa: E402


BUNDLES = HERE / "fresh_donor02_mechanism_bundles"
OUTPUT = HERE / "mechanism_normalized_fresh_gate"
TASKS = (
    "DEV-fullsource-donor02-25c",
    "DEV-fullsource-donor02-50c",
)
SEED = 1
EVALUATIONS = 100
TOL = 1.0e-9
REQUIRED_STRICT_WINS = 2
MIN_MEDIAN_RELATIVE_IMPROVEMENT = 0.005


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


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    started = time.time()
    for task in TASKS:
        bundle = BUNDLES / task
        baseline = run_mechanism_alns_v7(
            bundle,
            seed=SEED,
            eval_budget=EVALUATIONS,
            prices=DEFAULT_PRICES,
        )
        candidate = run_mechanism_normalized_alns(
            bundle,
            seed=SEED,
            eval_budget=EVALUATIONS,
            prices=DEFAULT_PRICES,
        )
        relative = (
            float(baseline.best_cost) - float(candidate.best_cost)
        ) / float(baseline.best_cost)
        rows.append(
            {
                "task": task,
                "seed": SEED,
                "evaluation_budget": EVALUATIONS,
                "baseline_v7_cost": float(baseline.best_cost),
                "candidate_cost": float(candidate.best_cost),
                "candidate_minus_baseline": float(
                    candidate.best_cost - baseline.best_cost
                ),
                "relative_improvement": float(relative),
                "strict_win": bool(
                    candidate.best_cost < baseline.best_cost - TOL
                ),
                "nonloss": bool(
                    candidate.best_cost <= baseline.best_cost + TOL
                ),
                "baseline_evaluations": int(baseline.evaluations),
                "candidate_evaluations": int(candidate.evaluations),
                "baseline_elapsed_seconds": float(
                    baseline.elapsed_seconds
                ),
                "candidate_elapsed_seconds": float(
                    candidate.elapsed_seconds
                ),
                "baseline_feasible": bool(baseline.feasible),
                "candidate_feasible": bool(candidate.feasible),
                "normalizer_calls": int(
                    candidate.mechanism_activity["normalizer_calls"]
                ),
                "normalizer_improvements": int(
                    candidate.mechanism_activity[
                        "normalizer_improvements"
                    ]
                ),
                "joint_updates_inside_search": int(
                    candidate.mechanism_activity["joint_updates"]
                ),
                "carbon_updates_inside_search": int(
                    candidate.mechanism_activity["carbon_updates"]
                ),
                "route_proxy_evaluations": int(
                    candidate.mechanism_activity[
                        "route_proxy_evaluations"
                    ]
                ),
                "carbon_route_local_evaluations": int(
                    candidate.mechanism_activity[
                        "carbon_route_local_evaluations"
                    ]
                ),
                "mechanism_feasibility_checks": int(
                    candidate.mechanism_activity[
                        "mechanism_feasibility_checks"
                    ]
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

    strict_wins = sum(bool(row["strict_win"]) for row in rows)
    all_nonloss = all(bool(row["nonloss"]) for row in rows)
    all_feasible = all(
        bool(row["baseline_feasible"]) and bool(row["candidate_feasible"])
        for row in rows
    )
    budgets_close = all(
        int(row["baseline_evaluations"]) == EVALUATIONS
        and int(row["candidate_evaluations"]) == EVALUATIONS
        for row in rows
    )
    relatives = sorted(float(row["relative_improvement"]) for row in rows)
    median_relative = sum(relatives) / len(relatives)
    mechanisms_active = all(
        int(row["normalizer_improvements"]) > 0 for row in rows
    )
    strong_positive = bool(
        all_feasible
        and budgets_close
        and all_nonloss
        and strict_wins >= REQUIRED_STRICT_WINS
        and median_relative >= MIN_MEDIAN_RELATIVE_IMPROVEMENT
        and mechanisms_active
    )
    verdict = (
        "GO_THREE_SEED_MECHANISM_NORMALIZED_CONFIRMATION"
        if strong_positive
        else "STOP_MECHANISM_NORMALIZED_ACCEPTANCE_NO_STRONG_SIGNAL"
    )
    decision = {
        "verdict": verdict,
        "strong_positive": strong_positive,
        "strict_win_count": strict_wins,
        "all_nonloss": all_nonloss,
        "all_feasible": all_feasible,
        "budget_closure": budgets_close,
        "mechanisms_active_both_tasks": mechanisms_active,
        "median_relative_improvement": median_relative,
        "predeclared_gate": {
            "strict_wins_required": REQUIRED_STRICT_WINS,
            "all_nonloss_required": True,
            "median_relative_improvement_minimum": (
                MIN_MEDIAN_RELATIVE_IMPROVEMENT
            ),
            "mechanism_active_each_task": True,
        },
        "formal_search_allowed": False,
        "formal_solver_integration_allowed": False,
        "stage2_allowed": False,
        "next_action": (
            "run seeds 1,2,3 on the same frozen fresh bundles without tuning"
            if strong_positive
            else "stop this design without tuning on the frozen fresh bundles"
        ),
    }
    metadata = {
        "schema_version": "mechanism-normalized-fresh-gate.v1",
        "purpose": "algorithm_development_only_not_formal_benchmark",
        "tasks": list(TASKS),
        "seed": SEED,
        "evaluation_budget_per_arm": EVALUATIONS,
        "candidate_frozen_before_results": True,
        "bundle_selection_frozen_before_results": True,
        "bundle_manifest_sha256": _sha(BUNDLES / "manifest.json"),
        "candidate_source_sha256": _sha(
            HERE / "mechanism_normalized_alns.py"
        ),
        "baseline_source_sha256": _sha(
            MECHANISM_DIR / "v7_responsibility_solver.py"
        ),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "python": sys.version,
        "platform": platform.platform(),
        "started_unix": started,
        "finished_unix": time.time(),
        "protected_files_modified_by_task": False,
    }
    _write_json(OUTPUT / "metadata.json", metadata)
    _write_json(OUTPUT / "decision.json", decision)

    report = [
        "# 搜索内机制归一化：新开发题单种子门",
        "",
        f"判定：`{verdict}`。",
        "",
        "候选与阶段一 v7 使用相同完整评价预算。候选的区别是：每个"
        "完整路线候选在接受前先做车型--补能和低碳充电时刻配套，最后"
        "再做跨车场责任收口。额外的路线局部计算已单独列账。",
        "",
        "|题目|v7|候选|相对改善|严格胜|完整评价|局部路线评价|",
        "|---|---:|---:|---:|---|---:|---:|",
    ]
    for row in rows:
        report.append(
            f"|{row['task']}|{float(row['baseline_v7_cost']):.9f}|"
            f"{float(row['candidate_cost']):.9f}|"
            f"{100.0 * float(row['relative_improvement']):.3f}%|"
            f"{row['strict_win']}|{row['candidate_evaluations']}|"
            f"{row['route_proxy_evaluations']}|"
        )
    report.extend(
        [
            "",
            "这仍不是纯 HGS/纯 ALNS 的正式双赢证据。通过时只允许扩大到"
            "同两题三种子；失败时不得在这两题上调频率、阈值或算子。",
            "",
        ]
    )
    (OUTPUT / "report.md").write_text(
        "\n".join(report),
        encoding="utf-8",
    )
    for sidecar in OUTPUT.glob("._*"):
        sidecar.unlink()
    files = [
        OUTPUT / "metadata.json",
        OUTPUT / "raw_runs.csv",
        OUTPUT / "decision.json",
        OUTPUT / "report.md",
    ]
    _write_json(
        OUTPUT / "artifact_hashes.json",
        {path.name: _sha(path) for path in files},
    )
    for sidecar in OUTPUT.glob("._*"):
        sidecar.unlink()
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
