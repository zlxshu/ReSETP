"""Run the frozen six-task G0 and apply the pre-registered stop rule."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
import traceback
from typing import Any

from .common import (
    ENGINEERING_OUT,
    G0_OUT,
    artifact_manifest,
    read_json,
    verify_registration,
    write_csv,
    write_json,
)
from .independent_replay import replay_all
from .worker_entry import run_task


def decision_from_rows(
    rows: list[dict[str, Any]],
    registration: dict[str, Any],
) -> dict[str, Any]:
    rules = registration["pass_rules"]
    by_instance: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_instance.setdefault(row["instance_id"], {})[row["arm"]] = row
    b_rows = [row for row in rows if row["arm"] == "B_EXACT_NH"]
    ab_rows = [
        row for row in rows if row["arm"] == "AB_HGS_EXACT_NH"
    ]
    all_exact = (
        len(rows) == 6
        and all(row["optimality_proven"] for row in rows)
        and all(row["complete_candidate_scores"] == 1 for row in rows)
    )
    b_improves = sum(row["strict_improvement"] for row in b_rows)
    ab_improves = sum(row["strict_improvement"] for row in ab_rows)
    ab_losses = sum(row["final_cost"] > row["start_cost"] + 1.0e-9 for row in ab_rows)
    ab_pct = max((row["improvement_pct"] for row in ab_rows), default=0.0)
    ab_beats_both = 0
    for arms in by_instance.values():
        b = arms["B_EXACT_NH"]
        ab = arms["AB_HGS_EXACT_NH"]
        if (
            ab["final_cost"] < ab["start_cost"] - 1.0e-9
            and ab["final_cost"] < b["final_cost"] - 1.0e-9
        ):
            ab_beats_both += 1
    ab_structural = all(
        (not row["strict_improvement"])
        or (
            row["adjacency_change_count"]
            >= int(rules["ab_adjacency_change_min"])
            and row["resource_change_count"]
            >= int(rules["ab_resource_change_min"])
        )
        for row in ab_rows
    )
    checks = {
        "all_tasks_exact_feasible_replayed": all_exact,
        "b_improves_count": b_improves,
        "b_improves_pass": b_improves
        >= int(rules["b_improves_count_min"]),
        "ab_improves_count": ab_improves,
        "ab_improves_pass": ab_improves
        >= int(rules["ab_improves_count_min"]),
        "ab_loss_count": ab_losses,
        "ab_zero_loss_pass": ab_losses
        <= int(rules["ab_loss_count_max"]),
        "ab_best_improvement_pct": ab_pct,
        "ab_material_improvement_pass": ab_pct
        >= float(rules["ab_one_improvement_pct_min"]),
        "ab_beats_a_and_b_count": ab_beats_both,
        "ab_beats_a_and_b_pass": ab_beats_both
        >= int(rules["ab_beats_a_and_b_count_min"]),
        "ab_structural_change_pass": ab_structural,
        "matched_candidate_budget_pass": all(
            row["complete_candidate_scores"] == 1 for row in rows
        ),
    }
    passed = all(
        value for key, value in checks.items() if key.endswith("_pass")
    ) and checks["all_tasks_exact_feasible_replayed"]
    return {
        "status": (
            "PASS_JRC_EXACT_NH_LOW_COST_G0"
            if passed
            else "FINAL_STOP_JRC_EXACT_NH_NO_STRONG_HGS_HEADROOM"
        ),
        "pass": passed,
        "checks": checks,
        "scope": (
            "PASS authorizes only a separately registered matched "
            "A/B/A+B next gate; no full run, SOTA, E3, or paper claim"
            if passed
            else "candidate sealed; no rescue, retry, or renamed revival"
        ),
    }


def main() -> int:
    G0_OUT.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "resetp.jrc-exact-nh-g0-result.v1",
        "contract_id": "E2-JRC-EXACT-NH-001",
        "workers": 6,
        "threads_per_worker": 1,
        "candidate_complete_scores_per_task": 1,
        "protected_fallback_modified": False,
    }
    try:
        engineering = read_json(ENGINEERING_OUT / "decision.json")
        if engineering.get("status") != "PASS_JRC_EXACT_NH_ENGINEERING_GATE":
            raise RuntimeError("engineering gate is not PASS")
        registration = verify_registration()
        tasks = registration["tasks"]
        if len(tasks) != 6:
            raise RuntimeError("registration does not contain six tasks")
        context = mp.get_context("spawn")
        rows: list[dict[str, Any]] = []
        with ProcessPoolExecutor(
            max_workers=6,
            mp_context=context,
        ) as executor:
            futures = {
                executor.submit(run_task, task): task for task in tasks
            }
            for future in as_completed(futures):
                rows.append(future.result())
        rows.sort(key=lambda row: row["task_id"])
        witnesses = {
            row["task_id"]: {
                "instance_id": row["instance_id"],
                "arm": row["arm"],
                "final_cost": row["final_cost"],
                "solution": row.pop("solution"),
            }
            for row in rows
        }
        write_csv(G0_OUT / "raw_runs.csv", rows)
        write_json(G0_OUT / "solution_witnesses.json", witnesses)
        replay_rows = replay_all()
        if len(replay_rows) != 6:
            raise RuntimeError("independent replay did not cover six tasks")
        decision = decision_from_rows(rows, registration)
        write_json(G0_OUT / "decision.json", decision)
        write_json(G0_OUT / "metadata.json", metadata)
        (G0_OUT / "report.md").write_text(
            "# JRC 联合路线—充电精确小邻域 G0\n\n"
            f"结论：`{decision['status']}`。\n\n"
            "六任务均按冻结的单次完整候选评分和 30 秒安全上限执行。"
            "效果判定完全按登记阈值一次性完成；失败不救援，通过也只授权"
            "另立匹配预算 A/B/A+B 小门。\n\n"
            f"判定明细：`{decision['checks']}`。\n",
            encoding="utf-8",
        )
        write_json(
            G0_OUT / "artifact_hashes.json",
            artifact_manifest(G0_OUT),
        )
        write_json(
            G0_OUT / "done.json",
            {"status": decision["status"], "pass": decision["pass"]},
        )
        return 0 if decision["pass"] else 3
    except Exception as exc:
        decision = {
            "status": "FINAL_STOP_JRC_EXACT_NH_EXECUTION_FAILURE",
            "pass": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "scope": "candidate sealed; no rescue or retry",
        }
        write_json(G0_OUT / "metadata.json", metadata)
        if not (G0_OUT / "raw_runs.csv").exists():
            write_csv(
                G0_OUT / "raw_runs.csv",
                [{"status": "NO_COMPLETE_SIX_TASK_RESULT"}],
            )
        write_json(G0_OUT / "decision.json", decision)
        (G0_OUT / "report.md").write_text(
            "# JRC 联合路线—充电精确小邻域 G0\n\n"
            f"结论：`{decision['status']}`。\n\n"
            f"失败：{type(exc).__name__}: {exc}\n",
            encoding="utf-8",
        )
        write_json(
            G0_OUT / "artifact_hashes.json",
            artifact_manifest(G0_OUT),
        )
        write_json(
            G0_OUT / "done.json",
            {"status": decision["status"], "pass": False},
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
