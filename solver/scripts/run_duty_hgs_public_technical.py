#!/usr/bin/env python3
"""Run a bounded public technical trial of the formal Duty-HGS portfolio."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import traceback
from dataclasses import asdict
from importlib import metadata as importlib_metadata
from pathlib import Path

from pyvrp import read
from setp_solver.algorithms.duty_hgs.public import build_public_dcrex_hgs


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
    package = repo / "solver/src/setp_solver/algorithms/duty_hgs"
    sources = sorted(
        path
        for path in package.glob("*.py")
        if not path.name.startswith("._")
    )
    return {
        "git_head": _git(repo, "rev-parse", "HEAD"),
        "git_status": _git(repo, "status", "--porcelain"),
        "python_executable": sys.executable,
        "pyvrp_version": importlib_metadata.version("pyvrp"),
        "source_sha256": {
            str(path.relative_to(repo)): _sha256(path) for path in sources
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
        "# 自研 Duty-HGS 公开接口技术试跑失败\n\n"
        f"本次技术试跑失败：{type(error).__name__}: {error}。"
        "错误和调用栈已原样保存在 decision.json。\n",
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
    parser.add_argument(
        "--crossover-mode",
        choices=("hybrid", "fast_only"),
        default="hybrid",
    )
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("technical iterations must be positive")
    if args.stagnation_patience < 1:
        raise ValueError("stagnation patience must be positive")

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
            "purpose": "formal SREX-DCREX Duty-HGS public wiring trial",
            "formal_performance_result": False,
            "instance": args.instance,
            "seed": args.seed,
            "iterations": args.iterations,
            "stagnation_patience": args.stagnation_patience,
            "crossover_mode": args.crossover_mode,
            "stopping": (
                "bounded calibration iterations plus a no-improvement window; "
                "not a frozen formal limit"
            ),
            "source_identity": _source_identity(repo),
            "instance_sha256": _sha256(instance_path),
        },
    )

    try:
        data = read(instance_path, round_func="round")
        algorithm = build_public_dcrex_hgs(
            data,
            seed=args.seed,
            max_iterations=args.iterations,
            stagnation_patience=args.stagnation_patience,
            crossover_mode=args.crossover_mode,
        )
        result = algorithm.run()
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
        cost = int(algorithm.cost_evaluator.cost(result.best))
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
            fieldnames = tuple(asdict(result.trajectory[0]))
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(asdict(row) for row in result.trajectory)
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
                "iterations": result.iterations,
                "termination_status": result.termination_status,
                "runtime_seconds": result.runtime_seconds,
                "completed_clients": len(set(visits)),
                "total_clients": len(clients),
                "completed_delivery": served_delivery,
                "total_delivery": total_delivery,
                "five_insertion_actions_observed": sorted(
                    {
                        row.insertion_operator
                        for row in result.trajectory
                        if row.insertion_operator is not None
                    }
                ),
                "crossover_actions_observed": sorted(
                    {row.crossover_action for row in result.trajectory}
                ),
                "crossover_work_units": {
                    action: sum(
                        row.deterministic_work_units
                        for row in result.trajectory
                        if row.crossover_action == action
                    )
                    for action in sorted(
                        {row.crossover_action for row in result.trajectory}
                    )
                },
            },
        )
        metadata = json.loads(
            (output / "metadata.json").read_text(encoding="utf-8")
        )
        metadata["status"] = "COMPLETE" if verdict.endswith("COMPLETE") else "FAILED"
        _json(output / "metadata.json", metadata)
        (output / "report.md").write_text(
            "# 自研 Duty-HGS 公开接口技术试跑\n\n"
            f"本次在 {args.instance} 上运行 {result.iterations} 次组合交叉迭代，"
            f"得到成本 {cost}，完整服务 {len(set(visits))}/{len(clients)} 个客户、"
            f"需求 {served_delivery}/{total_delivery}，运行 {result.runtime_seconds:.3f} 秒。\n\n"
            "本包用于检查正式算法的公开接口、完整服务和收敛轨迹；"
            "迭代数尚未按各自收敛标定，因此不是正式性能比较。\n",
            encoding="utf-8",
        )
        _write_hashes(output)
        if verdict != "TECHNICAL_TRIAL_COMPLETE":
            raise RuntimeError("public DCREX technical service checks failed")
        print(json.dumps(json.loads((output / "decision.json").read_text())))
        return 0
    except Exception as error:
        if not (output / "decision.json").exists():
            _write_failure(output, error)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
