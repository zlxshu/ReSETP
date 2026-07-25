"""Six-worker integration gate for the absolute execution harness."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any


def bootstrap(root: Path) -> None:
    root_text = str(root.resolve())
    if root_text not in sys.path:
        sys.path.insert(0, root_text)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", required=True, type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).resolve()
    registration_path = Path(args.registration).resolve()
    output = Path(args.output_dir).resolve()
    bootstrap(root)
    from baselines.experiment_infrastructure.absolute_execution_harness_20260725.paths import (
        read_json,
        validate_project_root,
    )
    from baselines.experiment_infrastructure.absolute_execution_harness_20260725.worker_probe import (
        EXPECTED_FILE,
        EXPECTED_MODULE,
        probe_worker,
    )

    metadata = {
        "schema": "resetp.absolute-execution-harness-result.v1",
        "contract_id": "EXPERIMENT-ABSOLUTE-HARNESS-001",
        "real_instance_loaded": False,
        "candidate_algorithm_imported": False,
        "workers_requested": args.workers,
    }
    rows: list[dict[str, Any]] = []
    try:
        if args.workers != 6:
            raise RuntimeError("frozen integration gate requires six workers")
        validated_root = validate_project_root(root)
        registration = read_json(registration_path)
        if registration["project_root"] != str(validated_root):
            raise RuntimeError("registration project root mismatch")
        if Path.cwd().resolve() != validated_root:
            raise RuntimeError(
                f"main cwd mismatch: {Path.cwd().resolve()} != {validated_root}"
            )
        if Path(sys.executable).resolve() != Path(
            registration["python"]
        ).resolve():
            raise RuntimeError("main Python identity mismatch")
        if Path(__file__).resolve() != Path(
            registration["main_script"]
        ).resolve():
            raise RuntimeError("main script identity mismatch")
        for raw, expected in registration["protected_sha256"].items():
            path = Path(raw)
            if not path.is_absolute() or not path.is_file():
                raise RuntimeError(f"protected path invalid: {raw}")
            actual = sha256(path)
            if actual != expected:
                raise RuntimeError(
                    f"protected hash drift: {raw}: {actual} != {expected}"
                )
        if not EXPECTED_FILE.is_absolute():
            raise RuntimeError("worker module file is not absolute")

        release_at = time.time() + 2.0
        tasks = [
            (
                index,
                str(validated_root),
                str(Path(sys.executable).resolve()),
                str(validated_root),
                release_at,
            )
            for index in range(6)
        ]
        context = mp.get_context("spawn")
        with context.Pool(processes=6) as pool:
            rows = pool.map(probe_worker, tasks)
        rows.sort(key=lambda row: row["worker_index"])
        if len(rows) != 6 or len({row["pid"] for row in rows}) != 6:
            raise RuntimeError("six distinct worker processes were not observed")
        if any(
            row["module"] != EXPECTED_MODULE
            or row["module_file"] != str(EXPECTED_FILE)
            or row["real_instance_loaded"]
            for row in rows
        ):
            raise RuntimeError("worker identity or no-instance assertion failed")

        write_csv(output / "raw_runs.csv", rows)
        decision = {
            "status": "PASS_EXPERIMENT_ABSOLUTE_HARNESS_V1",
            "pass": True,
            "workers": 6,
            "distinct_worker_pids": 6,
            "all_absolute_paths": True,
            "monitor_config_absolute_paths": True,
            "real_instance_loaded": False,
            "authorization": (
                "infrastructure only; no candidate rerun is automatically "
                "authorized"
            ),
        }
        write_json(output / "metadata.json", metadata)
        write_json(output / "decision.json", decision)
        (output / "report.md").write_text(
            "# 绝对路径实验启动器集成门\n\n"
            "结论：`PASS_EXPERIMENT_ABSOLUTE_HARNESS_V1`。\n\n"
            "监督器、主进程和六个不同 spawn 子进程均使用同一绝对项目根、"
            "绝对 Python 与绝对脚本路径。六个子进程均未加载真实算例或候选"
            "算法。该结果只验收启动基础设施，不自动授权重跑任何候选。\n",
            encoding="utf-8",
        )
        write_json(
            output / "artifact_hashes.json", artifact_manifest(output)
        )
        write_json(
            output / "done.json",
            {"status": decision["status"], "pass": True},
        )
        return 0
    except Exception as exc:
        if rows:
            write_csv(output / "raw_runs.csv", rows)
        else:
            write_csv(
                output / "raw_runs.csv",
                [
                    {
                        "worker_index": -1,
                        "pid": os.getpid(),
                        "module": "NOT_RUN",
                        "module_file": str(Path(__file__).resolve()),
                        "cwd": str(Path.cwd().resolve()),
                        "project_root": str(root),
                        "python": str(Path(sys.executable).resolve()),
                        "real_instance_loaded": False,
                    }
                ],
            )
        decision = {
            "status": "HALT_EXPERIMENT_ABSOLUTE_HARNESS_V1",
            "pass": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(output / "metadata.json", metadata)
        write_json(output / "decision.json", decision)
        (output / "report.md").write_text(
            "# 绝对路径实验启动器集成门\n\n"
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
