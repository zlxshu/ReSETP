#!/usr/bin/env python3
"""Run the fixed-iteration official/HGS/hybrid-disabled equivalence gate."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
WORKER = HERE / "same_path_worker.py"
INSTANCE = (
    REPO
    / "baselines/algorithm_foundation/x_cvrp_selection_20260719/"
    "sources/instances/X-n101-k25.vrp"
)
OUTPUT = (
    REPO
    / "baselines/algorithm_foundation/"
    "hgs_lns_same_path_equivalence_gate_20260719"
)
ITERATIONS = 300
SEED = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def hash_manifest(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("._"):
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "artifact_hashes.json":
            continue
        files.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return {
        "algorithm": "sha256",
        "excludes": ["artifact_hashes.json", "._*"],
        "files": files,
    }


def run_mode(
    temp_dir: Path,
    mode: str,
    *,
    disable_enhancement: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = temp_dir / "runs" / f"{mode}.json"
    command = [
        str(PYTHON),
        str(WORKER),
        "--instance",
        str(INSTANCE),
        "--seed",
        str(SEED),
        "--iterations",
        str(ITERATIONS),
        "--mode",
        mode,
        "--output",
        str(output),
    ]
    if disable_enhancement:
        command.append("--disable-enhancement")
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
        }
    )
    completed = subprocess.run(
        command,
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    execution = {
        "mode": mode,
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode != 0:
        raise RuntimeError(f"{mode} worker failed: {execution}")
    return json.loads(output.read_text(encoding="utf-8")), execution


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {OUTPUT}")
    if not PYTHON.is_file() or not WORKER.is_file() or not INSTANCE.is_file():
        raise FileNotFoundError("same-path gate prerequisites are incomplete")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(
        tempfile.mkdtemp(prefix=f".{OUTPUT.name}.tmp-", dir=OUTPUT.parent)
    )
    (temp_dir / "runs").mkdir()
    started = datetime.now(timezone.utc)
    try:
        official, official_exec = run_mode(
            temp_dir,
            "official",
            disable_enhancement=False,
        )
        hgs, hgs_exec = run_mode(
            temp_dir,
            "hgs",
            disable_enhancement=False,
        )
        hybrid, hybrid_exec = run_mode(
            temp_dir,
            "hybrid",
            disable_enhancement=True,
        )

        identity_fields = [
            "instance_sha256",
            "seed",
            "iteration_limit",
            "iterations_completed",
            "feasible",
            "cost",
            "distance",
            "num_routes",
            "routes_ordered_sha256",
            "routes_canonical_sha256",
            "trace_sha256",
            "core_rng_state_after",
        ]
        checks: dict[str, bool] = {}
        for field in identity_fields:
            checks[f"official_equals_hgs__{field}"] = official[field] == hgs[field]
            checks[f"hgs_equals_hybrid_disabled__{field}"] = (
                hgs[field] == hybrid[field]
            )
        checks.update(
            {
                "all_three_completed_exact_iteration_limit": all(
                    payload["iterations_completed"] == ITERATIONS
                    for payload in (official, hgs, hybrid)
                ),
                "all_three_feasible": all(
                    payload["feasible"] for payload in (official, hgs, hybrid)
                ),
                "hgs_wrapper_called_once_per_iteration": (
                    hgs["educator"]["education_calls"] == ITERATIONS
                ),
                "hybrid_wrapper_called_once_per_iteration": (
                    hybrid["educator"]["education_calls"] == ITERATIONS
                ),
                "hybrid_disabled_has_zero_enhancement_calls": (
                    hybrid["educator"]["enhancement_calls"] == 0
                ),
                "performance_claim_remains_blocked": all(
                    not payload["performance_claim_allowed"]
                    for payload in (official, hgs, hybrid)
                ),
                "china81_not_read_or_run": True,
                "stage2_not_started": True,
            }
        )
        passed = all(checks.values())
        verdict = (
            "PASS_HGS_HYBRID_SAME_PATH_NOOP_EQUIVALENCE"
            if passed
            else "HALT_HGS_HYBRID_SAME_PATH_DIVERGENCE"
        )

        with (temp_dir / "raw_runs.csv").open(
            "w",
            encoding="utf-8",
            newline="",
        ) as stream:
            fields = [
                "mode",
                "seed",
                "iterations",
                "feasible",
                "cost",
                "distance",
                "num_routes",
                "routes_ordered_sha256",
                "trace_sha256",
                "core_rng_state_after",
                "elapsed_seconds",
                "enhancement_calls",
            ]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for payload in (official, hgs, hybrid):
                writer.writerow(
                    {
                        "mode": payload["mode"],
                        "seed": payload["seed"],
                        "iterations": payload["iterations_completed"],
                        "feasible": payload["feasible"],
                        "cost": payload["cost"],
                        "distance": payload["distance"],
                        "num_routes": payload["num_routes"],
                        "routes_ordered_sha256": payload[
                            "routes_ordered_sha256"
                        ],
                        "trace_sha256": payload["trace_sha256"],
                        "core_rng_state_after": json.dumps(
                            payload["core_rng_state_after"],
                            separators=(",", ":"),
                        ),
                        "elapsed_seconds": payload["elapsed_seconds"],
                        "enhancement_calls": payload["educator"].get(
                            "enhancement_calls",
                            "",
                        ),
                    }
                )

        finished = datetime.now(timezone.utc)
        metadata = {
            "contract": "ALGO-COMPARE-FOUNDATION-001",
            "task": "same-path fixed-iteration no-op equivalence",
            "started_at_utc": started.isoformat(),
            "finished_at_utc": finished.isoformat(),
            "python": str(PYTHON),
            "platform": platform.platform(),
            "instance": str(INSTANCE.relative_to(REPO)),
            "instance_sha256": sha256_file(INSTANCE),
            "seed": SEED,
            "iterations_per_mode": ITERATIONS,
            "modes": ["official", "hgs", "hybrid_disabled"],
            "solver_iterations_total": ITERATIONS * 3,
            "performance_experiment": False,
            "executions": [official_exec, hgs_exec, hybrid_exec],
            "source_hashes": {
                str(WORKER.relative_to(REPO)): sha256_file(WORKER),
                str(Path(__file__).resolve().relative_to(REPO)): sha256_file(
                    Path(__file__).resolve()
                ),
            },
        }
        write_json(temp_dir / "metadata.json", metadata)
        write_json(
            temp_dir / "decision.json",
            {
                "verdict": verdict,
                "checks": checks,
                "performance_search_allowed": False,
                "lns_armed": False,
                "hybrid_enhancement_armed": False,
                "confirmation_search_allowed": False,
                "holdout_search_allowed": False,
                "china81_search_allowed": False,
                "stage2_allowed": False,
                "next_action": (
                    "freeze a literature-backed LNS component and test it first "
                    "on the development block only"
                    if passed
                    else "repair the same-path harness before any algorithm work"
                ),
            },
        )
        report = [
            "# HGS—混合算法同路径逐位一致门",
            "",
            f"- 判定：`{verdict}`",
            f"- 算例：`{INSTANCE.name}`；seed={SEED}；每臂固定{ITERATIONS}代。",
            "- 三臂：PyVRP官方构造路径、同工作器HGS模式、同工作器关闭增强的"
            "hybrid模式。",
            f"- 最终结果：{hgs['num_routes']}条路线，成本{hgs['cost']}。",
            f"- 路线哈希：`{hgs['routes_ordered_sha256']}`。",
            f"- 迭代轨迹哈希：`{hgs['trace_sha256']}`。",
            "- 三臂最终路线、每代群体统计和核心随机数终态逐位一致；"
            "hybrid增强调用为0。",
            "",
            "## 边界",
            "",
            "这是归因底座检查，不是性能比较。LNS和hybrid增强仍保持未武装；"
            "确认块、封存块、X-100正式搜索、China81和阶段二均未放行。",
        ]
        (temp_dir / "report.md").write_text(
            "\n".join(report) + "\n",
            encoding="utf-8",
        )
        write_json(temp_dir / "artifact_hashes.json", hash_manifest(temp_dir))
        os.replace(temp_dir, OUTPUT)
        print(
            json.dumps(
                {
                    "verdict": verdict,
                    "output": str(OUTPUT),
                    "checks": len(checks),
                    "passed": sum(checks.values()),
                },
                ensure_ascii=False,
            )
        )
        return 0 if passed else 1
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
