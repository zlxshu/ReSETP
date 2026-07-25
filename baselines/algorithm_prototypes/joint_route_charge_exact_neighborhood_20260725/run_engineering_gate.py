"""Run all frozen zero-objective engineering gates."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing as mp
import os
from pathlib import Path
import py_compile
import resource
import traceback
from typing import Any

from .common import (
    ENGINEERING_OUT,
    PACKAGE,
    artifact_manifest,
    verify_registration,
    write_csv,
    write_json,
)
from .exact_neighborhood import synthetic_six_customer_equivalence
from .worker_entry import EXPECTED_MODULE, inspect_task, worker_identity


SOURCE_FILES = (
    "__init__.py",
    "common.py",
    "exact_neighborhood.py",
    "build_registration.py",
    "worker_entry.py",
    "run_engineering_gate.py",
    "run_g0.py",
    "independent_replay.py",
)


def memory_snapshot() -> dict[str, Any]:
    page = os.sysconf("SC_PAGE_SIZE")
    available_pages = os.sysconf("SC_AVPHYS_PAGES")
    return {
        "logical_cpus": os.cpu_count(),
        "available_memory_mib": available_pages * page / 1024**2,
        "process_peak_rss_mib": resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss
        / 1024,
    }


def main() -> int:
    ENGINEERING_OUT.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "schema": "resetp.jrc-exact-nh-engineering.v1",
        "contract_id": "E2-JRC-EXACT-NH-001",
        "gate_type": "zero_objective_engineering_only",
        "real_neighborhood_search_launched": False,
    }
    rows: list[dict[str, Any]] = []
    try:
        registration = verify_registration()
        for name in SOURCE_FILES:
            py_compile.compile(
                str(PACKAGE / name),
                doraise=True,
            )
        proof = synthetic_six_customer_equivalence()
        if not proof["equivalent"]:
            raise RuntimeError("six-customer equivalence proof failed")

        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=6,
            mp_context=context,
        ) as executor:
            identities = list(executor.map(worker_identity, range(6)))
        expected_file = str((PACKAGE / "worker_entry.py").resolve())
        if any(
            row["module"] != EXPECTED_MODULE
            or row["file"] != expected_file
            or row["expected_file"] != expected_file
            for row in identities
        ):
            raise RuntimeError("spawned worker module identity mismatch")

        for task in registration["tasks"]:
            row = inspect_task(task)
            if row["selected_customer_count"] != 8:
                raise RuntimeError(
                    f"{row['task_id']}: not an eight-customer neighborhood"
                )
            rows.append(row)

        resources = memory_snapshot()
        if resources["logical_cpus"] is None or resources["logical_cpus"] < 8:
            raise RuntimeError("six-worker gate requires at least 8 logical CPUs")
        if resources["available_memory_mib"] < 4096:
            raise RuntimeError(
                "less than frozen 4096 MiB aggregate worker allowance available"
            )
        decision = {
            "status": "PASS_JRC_EXACT_NH_ENGINEERING_GATE",
            "pass": True,
            "six_customer_proof": proof,
            "spawn_worker_identities": identities,
            "real_start_inspections": len(rows),
            "resource_gate": resources,
            "authorization": (
                "only the frozen six-task G0 may proceed; no broader run"
            ),
        }
        metadata["real_neighborhood_search_launched"] = False
        write_csv(ENGINEERING_OUT / "raw_runs.csv", rows)
        write_json(ENGINEERING_OUT / "decision.json", decision)
        write_json(ENGINEERING_OUT / "metadata.json", metadata)
        (ENGINEERING_OUT / "report.md").write_text(
            "# JRC 精确小邻域工程门\n\n"
            "结论：`PASS_JRC_EXACT_NH_ENGINEERING_GATE`。\n\n"
            "六客户独立穷举等价证明、源码编译、六 worker 模块身份、"
            "六个真实起点只读复算与邻域选择、资源门全部通过。"
            "本阶段没有启动真实邻域效果搜索。\n",
            encoding="utf-8",
        )
        write_json(
            ENGINEERING_OUT / "artifact_hashes.json",
            artifact_manifest(ENGINEERING_OUT),
        )
        write_json(
            ENGINEERING_OUT / "done.json",
            {"status": decision["status"], "pass": True},
        )
        return 0
    except Exception as exc:
        decision = {
            "status": "FINAL_STOP_JRC_EXACT_NH_ENGINEERING_GATE",
            "pass": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(ENGINEERING_OUT / "metadata.json", metadata)
        if rows:
            write_csv(ENGINEERING_OUT / "raw_runs.csv", rows)
        else:
            write_csv(
                ENGINEERING_OUT / "raw_runs.csv",
                [{"status": "NO_REAL_EFFECT_TASK_LAUNCHED"}],
            )
        write_json(ENGINEERING_OUT / "decision.json", decision)
        (ENGINEERING_OUT / "report.md").write_text(
            "# JRC 精确小邻域工程门\n\n"
            f"结论：`{decision['status']}`。\n\n"
            f"失败：{type(exc).__name__}: {exc}\n",
            encoding="utf-8",
        )
        write_json(
            ENGINEERING_OUT / "artifact_hashes.json",
            artifact_manifest(ENGINEERING_OUT),
        )
        write_json(
            ENGINEERING_OUT / "done.json",
            {"status": decision["status"], "pass": False},
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
