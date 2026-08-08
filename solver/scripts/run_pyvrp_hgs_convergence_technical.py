#!/usr/bin/env python3
"""Run the frozen PyVRP 0.12.2 HGS until a fixed no-improvement window."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import math
import subprocess
import sys
from pathlib import Path

from pyvrp import read, solve
from pyvrp.stop import MaxRuntime, MultipleCriteria, NoImprovement


def _sha256(path: Path) -> str:
    import hashlib

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance", default="PR17A")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--stagnation-patience", type=int, default=5_000)
    parser.add_argument("--max-runtime-seconds", type=float)
    args = parser.parse_args()
    if args.stagnation_patience < 1:
        raise ValueError("stagnation patience must be positive")
    if args.max_runtime_seconds is not None and args.max_runtime_seconds <= 0:
        raise ValueError("max runtime seconds must be positive")
    version = importlib.metadata.version("pyvrp")
    if version != "0.12.2":
        raise RuntimeError(f"frozen baseline requires PyVRP 0.12.2, got {version}")

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
    module_path = Path(sys.modules["pyvrp"].__file__).resolve()
    git_head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": "frozen PyVRP HGS convergence calibration",
            "formal_performance_result": False,
            "instance": args.instance,
            "seed": args.seed,
            "stagnation_patience": args.stagnation_patience,
            "max_runtime_seconds": args.max_runtime_seconds,
            "stop": (
                "PyVRP NoImprovement plus MaxRuntime when supplied; "
                "no baseline code or operators changed"
            ),
            "git_head": git_head,
            "runner_sha256": _sha256(Path(__file__).resolve()),
            "instance_sha256": _sha256(instance_path),
            "pyvrp_version": version,
            "pyvrp_module_path": str(module_path),
            "pyvrp_module_sha256": _sha256(module_path),
            "python_executable": sys.executable,
            "argv": list(sys.argv),
        },
    )

    data = read(instance_path, round_func="round")
    criteria = [NoImprovement(args.stagnation_patience)]
    if args.max_runtime_seconds is not None:
        criteria.append(MaxRuntime(args.max_runtime_seconds))
    result = solve(
        data,
        MultipleCriteria(criteria),
        seed=args.seed,
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
    complete = bool(result.best.is_complete())
    feasible = bool(result.best.is_feasible())
    service_ok = bool(
        complete
        and feasible
        and set(visits) == clients
        and len(visits) == len(set(visits))
        and served_delivery == total_delivery
    )

    elapsed = 0.0
    best_seen = math.inf
    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("iteration", "elapsed_seconds", "best_cost"),
        )
        writer.writeheader()
        for iteration, (runtime, datum) in enumerate(
            zip(result.stats.runtimes, result.stats.feas_stats),
            start=1,
        ):
            elapsed += float(runtime)
            if math.isfinite(float(datum.best_cost)):
                best_seen = min(best_seen, float(datum.best_cost))
            writer.writerow(
                {
                    "iteration": iteration,
                    "elapsed_seconds": elapsed,
                    "best_cost": (
                        "" if not math.isfinite(best_seen) else int(best_seen)
                    ),
                }
            )

    cost = int(result.cost())
    termination_status = (
        "MAX_RUNTIME"
        if args.max_runtime_seconds is not None
        and float(result.runtime) >= args.max_runtime_seconds
        else "CONVERGED_NO_IMPROVEMENT"
    )
    verdict = (
        "TECHNICAL_TRIAL_COMPLETE"
        if service_ok
        else "TECHNICAL_TRIAL_FAILED"
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
            "algorithm": "unmodified PyVRP 0.12.2 HGS",
            "cost": cost,
            "iterations": int(result.num_iterations),
            "runtime_seconds": float(result.runtime),
            "termination_status": termination_status,
            "completed_clients": len(set(visits)),
            "total_clients": len(clients),
            "completed_delivery": served_delivery,
            "total_delivery": total_delivery,
        },
    )
    (output / "report.md").write_text(
        "# 冻结 PyVRP 0.12.2 HGS 收敛标定\n\n"
        f"{args.instance}、seed {args.seed} 在连续 "
        f"{args.stagnation_patience} 次无改善后停止，成本 {cost}，"
        f"完整服务 {len(set(visits))}/{len(clients)} 个客户、需求 "
        f"{served_delivery}/{total_delivery}。本包只标定冻结母体，"
        "没有增加算子或修改 PyVRP。\n\n"
        "## 交付前九条自检\n\n"
        "1. 事实出处——全部数字来自本包 metadata、raw_runs、decision 和 best_solution。\n"
        "2. 建议冒充状态——没有。\n"
        "3. 超范围改动——没有，只运行冻结母体。\n"
        "4. 受保护文件——未修改。\n"
        "5. 用户待决项——本包不新增。\n"
        "6. 自造术语——没有。\n"
        "7. 失败异常——按 verdict 如实保存。\n"
        "8. 四件套——metadata、raw_runs、decision、artifact_hashes、report 齐。\n"
        "9. 交接同步——在本轮施工总收口时统一同步。\n",
        encoding="utf-8",
    )
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    metadata["status"] = "COMPLETE" if service_ok else "FAILED"
    _json(output / "metadata.json", metadata)
    _write_hashes(output)
    print(json.dumps(json.loads((output / "decision.json").read_text())))
    return 0 if service_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
