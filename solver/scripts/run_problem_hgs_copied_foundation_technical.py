#!/usr/bin/env python3
"""Run the directly copied HGS foundation without project search changes."""

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

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("/usr/bin/git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_identity(
    repo: Path,
    kernel,
    distribution_name: str,
    other_package: str,
) -> dict[str, object]:
    package = Path(kernel.__file__).resolve().parent
    compiled = sorted(package.glob("*.so"))
    if not compiled:
        raise RuntimeError("copied HGS compiled extension is missing")
    identity = {
        "git_head": _git(repo, "rev-parse", "HEAD"),
        "git_status": _git(repo, "status", "--porcelain"),
        "python_executable": sys.executable,
        "kernel_version": importlib_metadata.version(distribution_name),
        "kernel_package": str(package),
        "other_package_importable": (
            importlib.util.find_spec(other_package) is not None
        ),
        "genetic_algorithm_sha256": _sha256(
            package / "GeneticAlgorithm.py"
        ),
        "solve_sha256": _sha256(package / "solve.py"),
        "compiled_kernel_sha256": {
            str(path): _sha256(path) for path in compiled
        },
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "argv": list(sys.argv),
    }
    if distribution_name == "setp-hgs-kernel":
        vendor = repo / "third_party/setp_hgs_kernel"
        identity.update(
            {
                "upstream_commit": (
                    vendor / "UPSTREAM_COMMIT"
                ).read_text(encoding="utf-8").strip(),
                "upstream_commit_file_sha256": _sha256(
                    vendor / "UPSTREAM_COMMIT"
                ),
                "upstream_license_sha256": _sha256(
                    vendor / "LICENSE.md"
                ),
            }
        )
    return identity


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


def _write_failure(output: Path, error: Exception) -> None:
    metadata_path = output / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["status"] = "FAILED"
    _json(metadata_path, metadata)
    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("verdict", "error_type", "error"),
            lineterminator="\n",
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
            "formal_performance_result": False,
            "error_type": type(error).__name__,
            "error": str(error),
            "traceback": traceback.format_exc(),
        },
    )
    (output / "report.md").write_text(
        "# 直接复制 HGS 基础循环技术试跑失败\n\n"
        f"本次失败：{type(error).__name__}: {error}。"
        "完整调用栈保存在 decision.json。\n\n"
        "## 交付前九条自检\n\n"
        "1. 事实出处——异常和调用栈保存在 decision.json。\n"
        "2. 建议是否冒充已决——没有，只记录失败。\n"
        "3. 是否越界——没有，只运行复制基础循环。\n"
        "4. 受保护文件——本入口不修改它们。\n"
        "5. 待决项——没有新增。\n"
        "6. 自造术语——没有。\n"
        "7. 失败和异常——已原样保留。\n"
        "8. 产物包——失败五件套已写全。\n"
        "9. 交接记录——任务总收尾时统一同步。\n",
        encoding="utf-8",
    )
    _write_hashes(output)


def _route_payload(solution) -> list[dict[str, object]]:
    return [
        {
            "vehicle_type": int(route.vehicle_type()),
            "start_depot": int(route.start_depot()),
            "end_depot": int(route.end_depot()),
            "customer_nodes": list(map(int, route.visits())),
        }
        for route in solution.routes()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance", default="PR17A")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument(
        "--round-func", choices=("exact", "round"), default="round"
    )
    parser.add_argument(
        "--implementation",
        choices=("copied", "frozen_baseline"),
        default="copied",
    )
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("technical iterations must be positive")

    if args.implementation == "copied":
        import setp_hgs_kernel as kernel
        from setp_hgs_kernel import read, solve
        from setp_hgs_kernel.stop import MaxIterations

        distribution_name = "setp-hgs-kernel"
        other_package = "pyvrp"
    else:
        import pyvrp as kernel
        from pyvrp import read, solve
        from pyvrp.stop import MaxIterations

        distribution_name = "pyvrp"
        other_package = "setp_hgs_kernel"

    if importlib.util.find_spec(other_package) is not None:
        raise RuntimeError(
            f"{args.implementation} environment unexpectedly contains "
            f"{other_package}"
        )
    if importlib_metadata.version(distribution_name) != "0.12.2":
        raise RuntimeError(
            f"{args.implementation} version must be 0.12.2"
        )

    repo = Path(__file__).resolve().parents[2]
    source_identity = _source_identity(
        repo, kernel, distribution_name, other_package
    )
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
            "purpose": (
                "fixed-iteration behaviour check of the directly copied HGS "
                "foundation; no project search component"
            ),
            "formal_performance_result": False,
            "instance": args.instance,
            "seed": args.seed,
            "iterations": args.iterations,
            "round_func": args.round_func,
            "implementation": args.implementation,
            "instance_sha256": _sha256(instance_path),
            "source_identity": source_identity,
        },
    )

    try:
        data = read(instance_path, round_func=args.round_func)
        result = solve(
            data,
            MaxIterations(args.iterations),
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
        complete = result.best.is_complete()
        feasible = result.best.is_feasible()
        service_ok = bool(
            complete
            and feasible
            and set(visits) == clients
            and len(visits) == len(set(visits))
            and served_delivery == total_delivery
        )
        verdict = (
            "TECHNICAL_TRIAL_COMPLETE"
            if service_ok
            else "TECHNICAL_TRIAL_FAILED"
        )
        cost = int(result.cost()) if feasible else None
        with (output / "raw_runs.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
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
                ),
                lineterminator="\n",
            )
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
                    "round_func": args.round_func,
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
                "routes": _route_payload(result.best),
            },
        )
        _json(
            output / "decision.json",
            {
                "verdict": verdict,
                "formal_performance_result": False,
                "algorithm_boundary": (
                    "direct call to the selected 0.12.2 solve and "
                    "GeneticAlgorithm; no project crossover, controller, "
                    "initial education, PI, or DCREX"
                ),
                "implementation": args.implementation,
                "cost": cost,
                "iterations": result.num_iterations,
                "runtime_seconds": result.runtime,
                "completed_clients": len(set(visits)),
                "total_clients": len(clients),
                "completed_delivery": served_delivery,
                "total_delivery": total_delivery,
                "round_func": args.round_func,
            },
        )
        metadata = json.loads(
            (output / "metadata.json").read_text(encoding="utf-8")
        )
        metadata["status"] = (
            "COMPLETE" if verdict.endswith("COMPLETE") else "FAILED"
        )
        _json(output / "metadata.json", metadata)
        (output / "report.md").write_text(
            "# 直接复制 HGS 基础循环技术试跑\n\n"
            f"{args.instance}、seed {args.seed}固定运行 {result.num_iterations} 轮，"
            f"成本 {cost}，完整服务 {len(set(visits))}/{len(clients)} 个客户、"
            f"需求 {served_delivery}/{total_delivery}，用时 {result.runtime:.6f} 秒。\n\n"
            f"本入口直接调用 {args.implementation} 的 solve 和 "
            "GeneticAlgorithm，"
            "不进入项目自写外循环，也不接入初始教育、PI 或 DCREX。"
            "固定迭代只用于与冻结原版做行为等价核对，不是性能实验。\n\n"
            "## 交付前九条自检\n\n"
            "1. 事实出处——成本、服务量、时间和路线保存在本包。\n"
            "2. 建议是否冒充已决——没有。\n"
            "3. 是否越界——没有，未运行项目自研组件。\n"
            "4. 受保护文件——本入口不修改它们。\n"
            "5. 待决项——没有新增。\n"
            "6. 自造术语——没有。\n"
            "7. 失败和异常——本次结束状态如实保存。\n"
            "8. 产物包——五件套和 best_solution.json 均齐全。\n"
            "9. 交接记录——任务总收尾时统一同步。\n",
            encoding="utf-8",
        )
        _write_hashes(output)
        if verdict != "TECHNICAL_TRIAL_COMPLETE":
            raise RuntimeError("copied foundation failed service checks")
        print(
            json.dumps(
                json.loads((output / "decision.json").read_text()),
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as error:
        if not (output / "decision.json").exists():
            _write_failure(output, error)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
