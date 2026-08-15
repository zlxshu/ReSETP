#!/usr/bin/env python3
"""Run the preregistered five-instance public SISR ablation serially."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import socket
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO / "solver/reports/sisr_public_ablation_20260811"
WORKER = REPO / "solver/scripts/run_public_v2_28_clean_ruler.py"
INDEPENDENT_PYTHON = (
    REPO / "build/python_envs/setp-independent-hgs/bin/python"
)
INSTANCES = ("PR11A", "PR13A", "PR15B", "PR18A", "PR21A")
MAIN_SEED = 11
NOISE_SEEDS = (3, 7)
NO_IMPROVEMENT = 5_000
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)


@dataclass(frozen=True)
class RunSpec:
    instance: str
    arm: str
    seed: int
    sisr_enabled: bool

    @property
    def label(self) -> str:
        return f"{self.instance}_{self.arm}_seed{self.seed}"


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _json(path: Path, value: Any) -> None:
    _atomic_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty ablation table")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ("/usr/bin/git", *args),
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _machine() -> dict[str, Any]:
    return {
        "benchmark_machine_role": "M1 (ARM) paper baseline",
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "controller_pid": os.getpid(),
    }


def _specifications() -> tuple[RunSpec, ...]:
    directional = tuple(
        spec
        for instance in INSTANCES
        for spec in (
            RunSpec(instance, "A", MAIN_SEED, False),
            RunSpec(instance, "B", MAIN_SEED, True),
        )
    )
    noise = tuple(
        RunSpec(instance, "A", seed, False)
        for seed in NOISE_SEEDS
        for instance in INSTANCES
    )
    return directional + noise


def _worker_command(
    output: Path,
    spec: RunSpec,
    max_runtime_seconds: float,
) -> list[str]:
    command = [
        str(INDEPENDENT_PYTHON),
        str(WORKER),
        "worker",
        str(output),
        "--instance",
        spec.instance,
        "--arm",
        "independent",
        "--seed",
        str(spec.seed),
        "--max-runtime-seconds",
        str(max_runtime_seconds),
        "--no-improvement",
        str(NO_IMPROVEMENT),
        "--run-kind",
        "probe",
    ]
    if spec.sisr_enabled:
        command.append("--sisr-enabled")
    return command


def _validate_run(output: Path, spec: RunSpec) -> dict[str, Any]:
    required = (
        "metadata.json",
        "decision.json",
        "audit.json",
        "best_solution.json",
        "raw_runs.csv",
        "artifact_hashes.json",
        "report.md",
    )
    missing = [
        name
        for name in required
        if not (output / name).is_file() or (output / name).stat().st_size == 0
    ]
    if missing:
        raise RuntimeError(f"{spec.label} missing files: {missing}")
    metadata = json.loads((output / "metadata.json").read_text("utf-8"))
    decision = json.loads((output / "decision.json").read_text("utf-8"))
    audit = json.loads((output / "audit.json").read_text("utf-8"))
    if metadata.get("status") != "COMPLETE":
        raise RuntimeError(f"{spec.label} metadata is not complete")
    if bool(metadata.get("sisr_enabled")) != spec.sisr_enabled:
        raise RuntimeError(f"{spec.label} SISR identity mismatch")
    if decision.get("verdict") not in {
        "FORMAL_RUN_COMPLETE",
        "FORMAL_RUN_COMPLETE_WITH_AUDIT_FAILURE",
    }:
        raise RuntimeError(f"{spec.label} has no completed decision")
    if audit.get("status") != "COMPLETE":
        raise RuntimeError(f"{spec.label} raw audit is not complete")
    return {"metadata": metadata, "decision": decision, "audit": audit}


def _row(spec: RunSpec, package: dict[str, Any]) -> dict[str, Any]:
    decision = package["decision"]
    audit = package["audit"]["summary"]
    sisr = decision["algorithm_accounting"]["sisr"]
    return {
        "instance": spec.instance,
        "arm": spec.arm,
        "seed": spec.seed,
        "sisr_enabled": spec.sisr_enabled,
        "max_runtime_seconds": package["metadata"]["max_runtime_seconds"],
        "final_cost_scaled": decision["cost_scaled"],
        "final_cost_original_units": decision["cost_original_units"],
        "paired_b_minus_a_scaled": "",
        "paired_b_minus_a_original_units": "",
        "completed_generations": decision["iterations"],
        "runtime_seconds": decision["runtime_seconds"],
        "time_to_best_seconds": decision["time_to_best_seconds"],
        "algorithm_cpu_seconds": sisr["algorithm_cpu_seconds"],
        "sisr_cpu_seconds": sisr["cpu_seconds"],
        "sisr_cpu_share_percent": sisr["cpu_share_percent"],
        "sisr_calls": sisr["calls"],
        "sisr_completed_calls": sisr["completed_calls"],
        "sisr_reconstruction_failures": sisr["reconstruction_failures"],
        "sisr_customers_removed": sisr["customers_removed"],
        "sisr_strings_removed": sisr["strings_removed"],
        "scaled_feasible": decision["scaled_feasible"],
        "all_routes_raw_precision_feasible": audit[
            "all_routes_raw_precision_feasible"
        ],
        "service_complete": audit["service_complete"],
        "completed_clients": decision["completed_clients"],
        "total_clients": decision["total_clients"],
        "completed_delivery_scaled": decision["completed_delivery"],
        "total_delivery_scaled": decision["total_delivery"],
        "completed_demand_raw": audit["completed_demand_raw"],
        "total_demand_raw": audit["total_demand_raw"],
        "termination_reason": decision["termination_reason"],
        "run_verdict": decision["verdict"],
        "run_directory": f"runs/{spec.label}",
    }


def _add_paired_differences(rows: list[dict[str, Any]]) -> None:
    by_key = {
        (row["instance"], row["arm"], row["seed"]): row for row in rows
    }
    for instance in INSTANCES:
        a = by_key[(instance, "A", MAIN_SEED)]
        b = by_key[(instance, "B", MAIN_SEED)]
        scaled = int(b["final_cost_scaled"]) - int(a["final_cost_scaled"])
        original = (
            float(b["final_cost_original_units"])
            - float(a["final_cost_original_units"])
        )
        for row in (a, b):
            row["paired_b_minus_a_scaled"] = scaled
            row["paired_b_minus_a_original_units"] = original


def _summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {
        (row["instance"], row["arm"], row["seed"]): row for row in rows
    }
    pairs = []
    for instance in INSTANCES:
        a = by_key[(instance, "A", MAIN_SEED)]
        b = by_key[(instance, "B", MAIN_SEED)]
        pairs.append(
            {
                "instance": instance,
                "a_cost_scaled": int(a["final_cost_scaled"]),
                "b_cost_scaled": int(b["final_cost_scaled"]),
                "b_minus_a_scaled": int(b["final_cost_scaled"])
                - int(a["final_cost_scaled"]),
                "a_generations": int(a["completed_generations"]),
                "b_generations": int(b["completed_generations"]),
                "generation_ratio_b_over_a": (
                    int(b["completed_generations"])
                    / int(a["completed_generations"])
                ),
                "sisr_cpu_share_percent": float(
                    b["sisr_cpu_share_percent"]
                ),
                "a_time_to_best_seconds": float(a["time_to_best_seconds"]),
                "b_time_to_best_seconds": float(b["time_to_best_seconds"]),
                "b_valid": bool(
                    b["scaled_feasible"]
                    and b["all_routes_raw_precision_feasible"]
                    and b["service_complete"]
                    and int(b["completed_clients"]) == int(b["total_clients"])
                    and float(b["completed_demand_raw"])
                    == float(b["total_demand_raw"])
                ),
            }
        )
    noise = []
    for instance in INSTANCES:
        costs = {
            seed: int(by_key[(instance, "A", seed)]["final_cost_scaled"])
            for seed in (MAIN_SEED, *NOISE_SEEDS)
        }
        minimum = min(costs.values())
        maximum = max(costs.values())
        noise.append(
            {
                "instance": instance,
                "a_costs_scaled_by_seed": costs,
                "range_scaled": maximum - minimum,
                "range_original_units": (maximum - minimum) / 1_000,
                "range_percent_of_best": (
                    100.0 * (maximum - minimum) / minimum
                    if minimum > 0
                    else math.nan
                ),
            }
        )
    differences = [pair["b_minus_a_scaled"] for pair in pairs]
    nonzero = [difference for difference in differences if difference != 0]
    wins = sum(difference < 0 for difference in nonzero)
    losses = sum(difference > 0 for difference in nonzero)
    sign_p_two_sided = 1.0
    if nonzero:
        tail = min(wins, losses)
        sign_p_two_sided = min(
            1.0,
            2.0
            * sum(
                math.comb(len(nonzero), index)
                for index in range(tail + 1)
            )
            / (2 ** len(nonzero)),
        )
    return {
        "paired": pairs,
        "noise": noise,
        "paired_direction": {
            "b_better_instances": sum(item < 0 for item in differences),
            "ties": sum(item == 0 for item in differences),
            "b_worse_instances": sum(item > 0 for item in differences),
            "sum_b_minus_a_scaled": sum(differences),
            "mean_b_minus_a_scaled": sum(differences) / len(differences),
            "exact_two_sided_sign_test_p": sign_p_two_sided,
        },
        "validity_failure": any(not pair["b_valid"] for pair in pairs),
        "interpretation_boundary": (
            "No significance threshold or numerical definition of 'large generation "
            "drop' was preregistered. The report gives the exact paired, sign-test, "
            "generation, CPU-share, and cross-seed noise values without inventing one."
        ),
    }


def _report(summary: dict[str, Any]) -> str:
    direction = summary["paired_direction"]
    lines = [
        "SISR_ABLATION_DONE",
        "",
        "# 公开侧 SISR 五题消融",
        "",
        "固定五题、seed 11、每臂 600 秒上限的 A/B 配对已经全部完成；"
        "A 为现状，B 为现状加一次 SISR 破坏—重建。另完成 A 组 seed 3/7，"
        "用于量同题种子波动。负的 B−A 表示 SISR 成本更低。",
        "",
        f"五题中 B 胜 {direction['b_better_instances']}、平 "
        f"{direction['ties']}、负 {direction['b_worse_instances']}；"
        f"B−A 合计 {direction['sum_b_minus_a_scaled']}（细缩放整数），"
        f"双侧精确符号检验 p={direction['exact_two_sided_sign_test_p']:.6f}。",
        "",
        "| 题号 | A 成本 | B 成本 | B−A | A 代数 | B 代数 | B/A 代数 | "
        "A time-to-best(s) | B time-to-best(s) | SISR CPU | B 真尺子与覆盖 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for pair in summary["paired"]:
        lines.append(
            f"| {pair['instance']} | {pair['a_cost_scaled']} | "
            f"{pair['b_cost_scaled']} | {pair['b_minus_a_scaled']} | "
            f"{pair['a_generations']} | {pair['b_generations']} | "
            f"{pair['generation_ratio_b_over_a']:.3f} | "
            f"{pair['a_time_to_best_seconds']:.3f} | "
            f"{pair['b_time_to_best_seconds']:.3f} | "
            f"{pair['sisr_cpu_share_percent']:.2f}% | "
            f"{'通过' if pair['b_valid'] else '失败'} |"
        )
    lines.extend(
        [
            "",
            "## A 组同题种子波动",
            "",
            "| 题号 | seed 3 | seed 7 | seed 11 | 极差 | 极差/三种子最好值 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in summary["noise"]:
        costs = item["a_costs_scaled_by_seed"]
        lines.append(
            f"| {item['instance']} | {costs[3]} | {costs[7]} | "
            f"{costs[11]} | {item['range_scaled']} | "
            f"{item['range_percent_of_best']:.4f}% |"
        )
    lines.extend(
        [
            "",
            "## 预注册停止条件核账",
            "",
            "- 不可行或服务不完整："
            + ("已触发。" if summary["validity_failure"] else "未触发。"),
            "- 成本是否能与 0 区分、代数下降是否达到“大幅”：任务没有预先给"
            "显著性阈值或数值定义，本报告不事后补门槛；上表保留精确配对差、"
            "符号检验、代数比、CPU 比例和同题种子极差，供按原合同直接判断。",
            "- 未增加预算、未更换算例、种子、尺度或真尺子口径。",
            "",
            "逐次原始字段在 raw_runs.csv；每次完整路线、逐代轨迹、metadata、"
            "decision 与真尺子审计在 runs/ 对应目录。",
            "",
        ]
    )
    return "\n".join(lines)


def _artifact_hashes(output: Path) -> None:
    files = sorted(
        path
        for path in output.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    _json(
        output / "artifact_hashes.json",
        {
            str(path.relative_to(output)): _sha256(path)
            for path in files
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-runtime-seconds", type=float, default=600.0)
    args = parser.parse_args()
    if args.max_runtime_seconds != 600.0:
        raise ValueError("this preregistered ablation is fixed to 600 seconds")
    if not INDEPENDENT_PYTHON.is_file() or not WORKER.is_file():
        raise FileNotFoundError("missing independent interpreter or public worker")

    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    (output / "runs").mkdir()
    specifications = _specifications()
    protected_before = {
        str(path.relative_to(REPO)): _sha256(path) for path in PROTECTED
    }
    metadata = {
        "status": "RUNNING",
        "evidence_level": "approved directional paired ablation",
        "started_at": _timestamp(),
        "controller_pid": os.getpid(),
        "machine": _machine(),
        "strictly_serial": True,
        "instances": list(INSTANCES),
        "directional_seed": MAIN_SEED,
        "additional_a_seeds": list(NOISE_SEEDS),
        "run_count": len(specifications),
        "max_runtime_seconds_per_run": 600.0,
        "no_improvement_iterations": NO_IMPROVEMENT,
        "round_func": "exact",
        "integer_scale": 1_000,
        "sisr": {
            "default_enabled": False,
            "treatment_enabled_only_in_arm_b": True,
            "average_removed_customers": 10.0,
            "maximum_string_length": 10.0,
            "blink_probability_beta": 0.01,
            "insertion_order_weights": {
                "random": 4,
                "demand": 4,
                "far": 2,
                "close": 1,
            },
            "acceptance": "existing HGS population and penalty logic; no SA",
            "sources": [
                {
                    "citation": "Christiaens and Vanden Berghe (2020)",
                    "doi": "10.1287/trsc.2019.0914",
                    "technical_report_sections": "5.2-5.3; Table 3 p.18",
                },
                {
                    "citation": "Simensen, Hasle and Stalhane (2022)",
                    "doi": "10.1007/s10732-022-09500-9",
                    "article_locations": "Section 2.5; Table 1 p.666; Table 9 p.679",
                },
            ],
        },
        "protected_sha256_before": protected_before,
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "worker_sha256": _sha256(WORKER),
        "sisr_source_sha256": _sha256(
            REPO / "solver/src/setp_solver/algorithms/problem_hgs/sisr.py"
        ),
        "public_search_sha256": _sha256(
            REPO / "solver/src/setp_solver/algorithms/problem_hgs/public_search.py"
        ),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_porcelain": _git("status", "--porcelain"),
        "completed_runs": [],
    }
    _json(output / "metadata.json", metadata)
    _atomic_text(output / "controller.pid", f"{os.getpid()}\n")

    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    rows: list[dict[str, Any]] = []
    try:
        for index, specification in enumerate(specifications, start=1):
            run_output = output / "runs" / specification.label
            log = output / "runs" / f"{specification.label}.log"
            with log.open("w", encoding="utf-8") as handle:
                completed = subprocess.run(
                    _worker_command(
                        run_output,
                        specification,
                        args.max_runtime_seconds,
                    ),
                    cwd=REPO,
                    env=environment,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"worker failed: {specification.label} "
                    f"exit={completed.returncode}"
                )
            package = _validate_run(run_output, specification)
            rows.append(_row(specification, package))
            metadata["completed_runs"].append(
                {
                    "index": index,
                    "label": specification.label,
                    "finished_at": _timestamp(),
                }
            )
            metadata["last_progress_at"] = _timestamp()
            _json(output / "metadata.json", metadata)

        _add_paired_differences(rows)
        summary = _summaries(rows)
        _write_csv(output / "raw_runs.csv", rows)
        _json(
            output / "decision.json",
            {
                "verdict": "SISR_DIRECTIONAL_ABLATION_COMPLETE",
                "formal_paper_result": False,
                "summary": summary,
                "selection_or_filtering_applied": False,
                "budget_or_parameter_changed_after_results": False,
            },
        )
        _atomic_text(output / "report.md", _report(summary))
        protected_after = {
            str(path.relative_to(REPO)): _sha256(path) for path in PROTECTED
        }
        metadata.update(
            {
                "status": "COMPLETE",
                "finished_at": _timestamp(),
                "protected_sha256_after": protected_after,
                "protected_files_unchanged": protected_after == protected_before,
            }
        )
        _json(output / "metadata.json", metadata)
        _atomic_text(output / "DONE", f"SISR_ABLATION_DONE {_timestamp()}\n")
        _artifact_hashes(output)
        return 0
    except BaseException as error:
        metadata.update(
            {
                "status": "FAILED",
                "finished_at": _timestamp(),
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
        _json(output / "metadata.json", metadata)
        _json(
            output / "failure.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
            },
        )
        if rows:
            _write_csv(output / "partial_raw_runs.csv", rows)
        _artifact_hashes(output)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
