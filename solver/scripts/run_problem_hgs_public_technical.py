#!/usr/bin/env python3
"""Run the default public adapter through the independently copied HGS."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import traceback
from importlib import metadata as importlib_metadata
from pathlib import Path

import setp_hgs_kernel
from setp_hgs_kernel import read, solve
from setp_hgs_kernel.stop import (
    MaxIterations,
    MaxRuntime,
    MultipleCriteria,
    NoImprovement,
)


PUBLIC_INSTANCE_ROUND_FUNC = "exact"
PUBLIC_INSTANCE_SCALE = 1_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_identity(repo: Path) -> dict[str, object]:
    package = repo / "solver/src/setp_solver/algorithms/problem_hgs"
    vendor = repo / "third_party/setp_hgs_kernel"
    sources = sorted(
        path
        for path in package.glob("*.py")
        if not path.name.startswith("._")
    )
    return {
        "git_head": _git(repo, "rev-parse", "HEAD"),
        "git_status": _git(repo, "status", "--porcelain"),
        "python_executable": sys.executable,
        "kernel_version": importlib_metadata.version("setp-hgs-kernel"),
        "kernel_package": str(Path(setp_hgs_kernel.__file__).resolve()),
        "pyvrp_importable": importlib.util.find_spec("pyvrp") is not None,
        "source_sha256": {
            str(path.relative_to(repo)): _sha256(path)
            for path in (
                *sources,
                vendor / "UPSTREAM_COMMIT",
                vendor / "LICENSE.md",
                vendor / "meson.build",
                vendor / "pyproject.toml",
            )
        },
        "compiled_kernel_sha256": {
            str(path): _sha256(path)
            for path in sorted(
                Path(setp_hgs_kernel.__file__).resolve().parent.rglob("*.so")
            )
            if not path.name.startswith("._")
        },
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "argv": list(sys.argv),
    }


def _write_hashes(output: Path) -> None:
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    _json(
        output / "artifact_hashes.json",
        {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        },
    )
    for sidecar in output.glob("._*"):
        sidecar.unlink()


def _write_failure(output: Path, error: Exception) -> None:
    metadata_path = output / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["status"] = "FAILED"
    _json(metadata_path, metadata)
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("verdict", "error_type", "error"),
        )
        writer.writeheader()
        writer.writerow(
            {
                "verdict": "TECHNICAL_TRIAL_FAILED",
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
    _json(
        output / "decision.json",
        {
            "verdict": "TECHNICAL_TRIAL_FAILED",
            "error_type": type(error).__name__,
            "error": str(error),
            "traceback": traceback.format_exc(),
            "formal_performance_result": False,
        },
    )
    (output / "report.md").write_text(
        "# 自研 Problem-HGS 公开接口技术试跑失败\n\n"
        f"本次技术试跑失败：{type(error).__name__}: {error}。"
        "错误和调用栈已原样保存在 decision.json。\n\n"
        "## 交付前九条自检\n\n"
        "1. 每个事实是否有出处？——错误类型、错误信息和调用栈均来自本次运行并保存在 decision.json。\n"
        "2. 有没有把建议或担忧写成已决？——没有；这里只记录运行失败。\n"
        "3. 是否超出任务范围？——没有；只运行自研公开技术试跑并保存失败现场。\n"
        "4. 是否碰受保护文件？——本入口不写 cost.py、check.py 或 search/evaluation.py；任务收尾统一复核哈希。\n"
        "5. 是否留下新的待决选项？——没有。\n"
        "6. 是否使用自造术语？——没有。\n"
        "7. 失败、跳过、超时、异常是否如实保留？——本次异常已原样保留。\n"
        "8. 四件套是否齐全？——metadata.json、raw_runs.csv、decision.json、artifact_hashes.json 和 report.md 均由失败收口写入。\n"
        "9. 交接和记忆是否同步？——本单包只保存现场，任务收尾时统一同步项目记录。\n",
        encoding="utf-8",
    )
    _write_hashes(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance", default="PR17A")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--stagnation-patience", type=int, default=500)
    parser.add_argument("--max-runtime-seconds", type=float)
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("technical iterations must be positive")
    if args.stagnation_patience < 1:
        raise ValueError("stagnation patience must be positive")
    if args.max_runtime_seconds is not None and args.max_runtime_seconds <= 0:
        raise ValueError("max runtime seconds must be positive")
    if importlib.util.find_spec("pyvrp") is not None:
        raise RuntimeError(
            "independent Problem-HGS environment must not install PyVRP"
        )

    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    instance_path = (
        repo
        / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
        / "sources/normalised_instances"
        / f"{args.instance}.vrp"
    )
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": "independent Problem-HGS public wiring trial",
            "formal_performance_result": False,
            "instance": args.instance,
            "seed": args.seed,
            "iterations": args.iterations,
            "stagnation_patience": args.stagnation_patience,
            "max_runtime_seconds": args.max_runtime_seconds,
            "default_components": {
                "copied_hgs": True,
                "public_customer_depot_reassignment": False,
                "initial_population_preeducation": False,
            },
            "round_func": PUBLIC_INSTANCE_ROUND_FUNC,
            "integer_scale": PUBLIC_INSTANCE_SCALE,
            "stopping": (
                "bounded calibration iterations plus a no-improvement window; "
                "not a frozen formal limit"
            ),
            "source_identity": _source_identity(repo),
            "instance_sha256": _sha256(instance_path),
        },
    )

    try:
        data = read(instance_path, round_func=PUBLIC_INSTANCE_ROUND_FUNC)
        criteria = [
            MaxIterations(args.iterations),
            NoImprovement(args.stagnation_patience),
        ]
        if args.max_runtime_seconds is not None:
            criteria.append(MaxRuntime(args.max_runtime_seconds))
        result = solve(
            data,
            MultipleCriteria(criteria),
            seed=args.seed,
            collect_stats=False,
            display=False,
        )
        visits = [
            int(client)
            for route in result.best.routes()
            for client in route.visits()
        ]
        clients = set(range(data.num_depots, data.num_locations))
        total_delivery = sum(
            sum(int(value) for value in data.location(client).delivery)
            for client in clients
        )
        served_delivery = sum(
            sum(int(value) for value in data.location(client).delivery)
            for client in set(visits)
        )
        cost = int(result.cost()) if result.best.is_feasible() else None
        complete = result.best.is_complete()
        feasible = result.best.is_feasible()
        verdict = (
            "TECHNICAL_TRIAL_COMPLETE"
            if complete
            and feasible
            and set(visits) == clients
            and len(visits) == len(set(visits))
            and served_delivery == total_delivery
            else "TECHNICAL_TRIAL_FAILED"
        )
        with (output / "raw_runs.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            fieldnames = (
                "instance",
                "seed",
                "iterations",
                "runtime_seconds",
                "cost",
                "complete",
                "feasible",
                "completed_clients",
                "total_clients",
                "completed_delivery",
                "total_delivery",
                "round_func",
                "customer_depot_reassignment_enabled",
                "initial_population_preeducation_enabled",
            )
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "instance": args.instance,
                    "seed": args.seed,
                    "iterations": result.num_iterations,
                    "runtime_seconds": result.runtime,
                    "cost": cost,
                    "complete": complete,
                    "feasible": feasible,
                    "completed_clients": len(set(visits)),
                    "total_clients": len(clients),
                    "completed_delivery": served_delivery,
                    "total_delivery": total_delivery,
                    "round_func": PUBLIC_INSTANCE_ROUND_FUNC,
                    "customer_depot_reassignment_enabled": False,
                    "initial_population_preeducation_enabled": False,
                }
            )
        _json(
            output / "best_solution.json",
            {
                "cost": cost,
                "complete": complete,
                "feasible": feasible,
                "completed_clients": len(set(visits)),
                "total_clients": len(clients),
                "completed_delivery": served_delivery,
                "total_delivery": total_delivery,
                "routes": [
                    {
                        "vehicle_type": int(route.vehicle_type()),
                        "start_depot": int(route.start_depot()),
                        "end_depot": int(route.end_depot()),
                        "customer_nodes": list(map(int, route.visits())),
                    }
                    for route in result.best.routes()
                ],
            },
        )
        _json(
            output / "decision.json",
            {
                "verdict": verdict,
                "formal_performance_result": False,
                "cost": cost,
                "iterations": result.num_iterations,
                "runtime_seconds": result.runtime,
                "round_func": PUBLIC_INSTANCE_ROUND_FUNC,
                "completed_clients": len(set(visits)),
                "total_clients": len(clients),
                "completed_delivery": served_delivery,
                "total_delivery": total_delivery,
                "default_components": {
                    "copied_hgs": True,
                    "public_customer_depot_reassignment": False,
                    "initial_population_preeducation": False,
                },
            },
        )
        metadata = json.loads(
            (output / "metadata.json").read_text(encoding="utf-8")
        )
        metadata["status"] = "COMPLETE" if verdict.endswith("COMPLETE") else "FAILED"
        _json(output / "metadata.json", metadata)
        (output / "report.md").write_text(
            "# 自研 Problem-HGS 公开接口技术试跑\n\n"
            f"本次在 {args.instance} 上运行 {result.num_iterations} 次 HGS 迭代，"
            f"得到成本 {cost}，完整服务 {len(set(visits))}/{len(clients)} 个客户、"
            f"需求 {served_delivery}/{total_delivery}，运行 {result.runtime:.3f} 秒。\n\n"
            "本包用于检查默认公开接口和完整服务；"
            "公开端直接进入独立复制的 HGS 主体，客户重分车场与"
            "初始种群预教育默认关闭。"
            "迭代数尚未按各自收敛标定，因此不是正式性能比较。\n\n"
            "## 交付前九条自检\n\n"
            "1. 每个事实是否有出处？——成本、服务量、运行时间和动作来自本包 decision.json、best_solution.json 与 raw_runs.csv。\n"
            "2. 有没有把建议或担忧写成已决？——没有；技术试跑没有被写成正式性能结论。\n"
            "3. 是否超出任务范围？——没有；只运行指定公开算例并保存轨迹。\n"
            "4. 是否碰受保护文件？——本入口不写 cost.py、check.py 或 search/evaluation.py；任务收尾统一复核哈希。\n"
            "5. 是否留下新的待决选项？——没有。\n"
            "6. 是否使用自造术语？——没有；Problem-HGS 是工作名称，不是论文创新命名。\n"
            "7. 失败、跳过、超时、异常是否如实保留？——结束状态和原始读数已保存，没有删掉不利读数。\n"
            "8. 四件套是否齐全？——metadata.json、raw_runs.csv、decision.json、artifact_hashes.json 和 report.md 均已生成。\n"
            "9. 交接和记忆是否同步？——本单包先保存证据，任务收尾时统一同步项目记录。\n",
            encoding="utf-8",
        )
        _write_hashes(output)
        if verdict != "TECHNICAL_TRIAL_COMPLETE":
            raise RuntimeError("public copied-HGS technical service checks failed")
        print(json.dumps(json.loads((output / "decision.json").read_text())))
        return 0
    except Exception as error:
        if not (output / "decision.json").exists():
            _write_failure(output, error)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
