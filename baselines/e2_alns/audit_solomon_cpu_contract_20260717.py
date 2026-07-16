#!/usr/bin/env python3
"""Audit the current machine against the frozen Solomon CPU contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "baselines/e2_alns/solomon_cpu_contract_20260717.json"
OUT = REPO / "baselines/e2_alns/solomon_cpu_preflight_20260717_v5"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def hardware_profile() -> dict[str, object]:
    text = command("system_profiler", "SPHardwareDataType")

    def value(label: str) -> str:
        prefix = f"{label}:"
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(prefix):
                return stripped[len(prefix) :].strip()
        raise RuntimeError(f"hardware field missing: {label}")

    core_text = value("Total Number of Cores")
    return {
        "model_name": value("Model Name"),
        "model_identifier": value("Model Identifier"),
        "chip": value("Chip"),
        "physical_cores": int(command("sysctl", "-n", "hw.physicalcpu")),
        "performance_cores": int(core_text.split("(", 1)[1].split(" performance", 1)[0]),
        "efficiency_cores": int(core_text.split(" and ", 1)[1].split(" efficiency", 1)[0]),
        "logical_cores": int(command("sysctl", "-n", "hw.logicalcpu")),
        "memory_bytes": int(command("sysctl", "-n", "hw.memsize")),
        "operating_system": f"macOS {command('sw_vers', '-productVersion')}",
        "architecture": platform.machine(),
    }


def runtime_profile() -> dict[str, object]:
    return {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    actual_hardware = hardware_profile()
    actual_runtime = runtime_profile()
    failures: list[str] = []
    for section, actual in (("machine", actual_hardware), ("runtime", actual_runtime)):
        expected = contract[section]
        for key, value in actual.items():
            if expected.get(key) != value:
                failures.append(f"{section}.{key}: expected {expected.get(key)!r}, got {value!r}")
    timing = contract["dimacs_time_standardization"]
    calculated_factor = timing["passmark_single_thread_rating"] / timing["dimacs_baseline_rating"]
    if abs(calculated_factor - timing["time_factor"]) > 1e-12:
        failures.append("DIMACS time factor is arithmetically inconsistent")
    verdict = "PASS_SOLOMON_CPU_CONTRACT" if not failures else "FAIL_SOLOMON_CPU_CONTRACT"
    args.output.mkdir(parents=True, exist_ok=True)
    if any(item for item in args.output.iterdir() if not item.name.startswith("._")):
        raise RuntimeError(f"refuse to overwrite non-empty output: {args.output}")
    metadata = {
        "schema_version": "resetp.e2.solomon-cpu-preflight.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_path": str(CONTRACT.relative_to(REPO)),
        "contract_sha256": sha256(CONTRACT),
        "actual_hardware": actual_hardware,
        "actual_runtime": actual_runtime,
        "time_factor": calculated_factor,
        "literature_reporting_semantics": contract["literature_reporting_semantics"],
        "search_performed": False,
    }
    (args.output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "raw_runs.csv").write_text(
        "machine,chip,physical_cores,performance_cores,efficiency_cores,passmark_single_thread,time_factor,search_evaluations\n"
        f"{actual_hardware['model_identifier']},{actual_hardware['chip']},{actual_hardware['physical_cores']},"
        f"{actual_hardware['performance_cores']},{actual_hardware['efficiency_cores']},"
        f"{timing['passmark_single_thread_rating']},{calculated_factor},0\n",
        encoding="utf-8",
    )
    (args.output / "report.md").write_text(
        "# Solomon公开基准CPU预检\n\n"
        f"判定：`{verdict}`。Apple M1含4个性能核和4个能效核；匹配墙钟时间时并行4项，"
        "按评价预算运行或执行非定时审计时可并行8项，每项均为单线程。\n\n"
        f"冻结PassMark单线程分数为{timing['passmark_single_thread_rating']}，DIMACS基准为2000，"
        f"时间换算系数为{calculated_factor:.3f}。该换算只用于DIMACS补充口径。\n\n"
        "SINTEF主表中的CPU指单个求解进程的计算时间，RT指墙钟时间，Runs指独立运行次数；"
        "处理器型号、核心数和内存另在实验环境中报告。\n\n"
        "本预检不执行路径搜索；正式运行开始时必须重新生成一次新的、不可覆盖的CPU现场记录。\n",
        encoding="utf-8",
    )
    subprocess.run(["dot_clean", "-m", str(args.output)], check=True)
    appledouble = sorted(path.name for path in args.output.rglob("._*"))
    if appledouble:
        failures.append(f"AppleDouble cleanup failed: {appledouble}")
        verdict = "FAIL_SOLOMON_CPU_CONTRACT"
    decision = {
        "verdict": verdict,
        "failures": failures,
        "formal_search_authorized": False,
        "appledouble_count": len(appledouble),
    }
    (args.output / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["dot_clean", "-m", str(args.output)], check=True)
    hashes = {
        path.name: sha256(path)
        for path in args.output.iterdir()
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    (args.output / "artifact_hashes.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["dot_clean", "-m", str(args.output)], check=True)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
