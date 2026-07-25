"""Run the unchanged frozen JRC six-task G0 through absolute execution v2."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
import os
from pathlib import Path
import traceback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).resolve()
    if str(root) not in os.sys.path:
        os.sys.path.insert(0, str(root))
    from baselines.algorithm_prototypes.joint_route_charge_exact_neighborhood_20260725.common import (
        verify_registration,
    )
    from baselines.algorithm_prototypes.joint_route_charge_exact_neighborhood_20260725.independent_replay_v2 import (
        replay_all_v2,
    )
    from baselines.algorithm_prototypes.joint_route_charge_exact_neighborhood_20260725.run_g0 import (
        decision_from_rows,
    )
    from baselines.algorithm_prototypes.joint_route_charge_exact_neighborhood_20260725.v2_common import (
        ENGINEERING_OUT_V2,
        artifact_manifest,
        read_json,
        verify_v2_registration,
        write_csv,
        write_json,
    )
    from baselines.algorithm_prototypes.joint_route_charge_exact_neighborhood_20260725.worker_entry import (
        run_task,
    )

    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "resetp.jrc-exact-nh-g0-result.v2",
        "contract_id": "E2-JRC-EXACT-NH-001",
        "execution_harness": "absolute-v2",
        "workers": args.workers,
        "threads_per_worker": 1,
        "candidate_complete_scores_per_task": 1,
        "scientific_candidate_modified": False,
        "protected_fallback_modified": False,
    }
    try:
        if args.workers != 6:
            raise RuntimeError("frozen G0 requires six workers")
        if Path.cwd().resolve() != root:
            raise RuntimeError("G0 main cwd is not the project root")
        engineering = read_json(ENGINEERING_OUT_V2 / "decision.json")
        if (
            engineering.get("status")
            != "PASS_JRC_EXACT_NH_ENGINEERING_GATE_V2"
        ):
            raise RuntimeError("JRC v2 engineering gate is not PASS")
        v1 = verify_registration()
        v2 = verify_v2_registration()
        if (
            v2["tasks"] != v1["tasks"]
            or v2["limits"] != v1["limits"]
            or v2["pass_rules"] != v1["pass_rules"]
        ):
            raise RuntimeError("JRC v2 scientific contract differs from v1")
        context = mp.get_context("spawn")
        rows = []
        with ProcessPoolExecutor(
            max_workers=6, mp_context=context
        ) as executor:
            futures = {
                executor.submit(run_task, task): task
                for task in v2["tasks"]
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
        write_csv(output / "raw_runs.csv", rows)
        write_json(output / "solution_witnesses.json", witnesses)
        replay = replay_all_v2()
        if len(replay) != 6:
            raise RuntimeError("independent replay did not cover six tasks")
        decision = decision_from_rows(rows, v2)
        decision["execution_version"] = "v2_absolute_harness"
        write_json(output / "metadata.json", metadata)
        write_json(output / "decision.json", decision)
        (output / "report.md").write_text(
            "# JRC v2 六任务 G0\n\n"
            f"结论：`{decision['status']}`。\n\n"
            "六任务使用冻结的8客户邻域、30秒上限、每任务一次完整"
            "候选评分和六个单线程worker；独立复算后按v1阈值一次性"
            "判定，未修改科学候选。\n\n"
            f"判定明细：`{decision['checks']}`。\n",
            encoding="utf-8",
        )
        write_json(
            output / "artifact_hashes.json", artifact_manifest(output)
        )
        write_json(
            output / "done.json",
            {"status": decision["status"], "pass": decision["pass"]},
        )
        return 0 if decision["pass"] else 3
    except Exception as exc:
        decision = {
            "status": "FINAL_STOP_JRC_EXACT_NH_EXECUTION_FAILURE_V2",
            "pass": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "scientific_candidate_modified": False,
            "scope": "candidate sealed; no scientific rescue or retry",
        }
        if not (output / "raw_runs.csv").exists():
            write_csv(
                output / "raw_runs.csv",
                [{"status": "NO_COMPLETE_SIX_TASK_RESULT"}],
            )
        write_json(output / "metadata.json", metadata)
        write_json(output / "decision.json", decision)
        (output / "report.md").write_text(
            "# JRC v2 六任务 G0\n\n"
            f"结论：`{decision['status']}`。\n\n"
            f"失败：{type(exc).__name__}: {exc}\n",
            encoding="utf-8",
        )
        write_json(
            output / "artifact_hashes.json", artifact_manifest(output)
        )
        write_json(
            output / "done.json",
            {"status": decision["status"], "pass": False},
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
