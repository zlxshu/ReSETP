#!/usr/bin/env python3
"""Compare copied HGS with its customer-assignment in-search extension."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

from setp_hgs_kernel import read, solve
from setp_hgs_kernel.stop import MaxIterations
from setp_solver.algorithms.problem_hgs.public_search import (
    build_customer_assignment_hgs,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _service(data, solution) -> dict[str, int | bool]:
    visits = [
        int(customer)
        for route in solution.routes()
        for customer in route.visits()
    ]
    clients = set(range(data.num_depots, data.num_locations))
    total_delivery = sum(
        sum(int(value) for value in data.location(client).delivery)
        for client in clients
    )
    completed_delivery = sum(
        sum(int(value) for value in data.location(client).delivery)
        for client in set(visits)
    )
    return {
        "complete": bool(solution.is_complete()),
        "feasible": bool(solution.is_feasible()),
        "completed_clients": len(set(visits)),
        "total_clients": len(clients),
        "completed_delivery": completed_delivery,
        "total_delivery": total_delivery,
        "no_duplicate_clients": len(visits) == len(set(visits)),
    }


def _service_ok(service: dict[str, int | bool]) -> bool:
    return bool(
        service["complete"]
        and service["feasible"]
        and service["no_duplicate_clients"]
        and service["completed_clients"] == service["total_clients"]
        and service["completed_delivery"] == service["total_delivery"]
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
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("iterations must be positive")
    if importlib.util.find_spec("pyvrp") is not None:
        raise RuntimeError("in-search trial must use the independent environment")

    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    instance_path = (
        repo
        / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
        / "sources/normalised_instances"
        / f"{args.instance}.vrp"
    )
    output.mkdir(parents=True)
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": "fixed-iteration in-search assignment attribution",
            "formal_performance_result": False,
            "instance": args.instance,
            "seed": args.seed,
            "iterations": args.iterations,
            "round_func": "round",
            "instance_sha256": _sha256(instance_path),
            "runner_sha256": _sha256(Path(__file__).resolve()),
            "public_search_sha256": _sha256(
                repo
                / "solver/src/setp_solver/algorithms/problem_hgs"
                / "public_search.py"
            ),
            "public_assignment_sha256": _sha256(
                repo
                / "solver/src/setp_solver/algorithms/problem_hgs"
                / "public_assignment.py"
            ),
            "python_executable": sys.executable,
            "argv": list(sys.argv),
        },
    )

    try:
        data = read(instance_path, round_func="round")
        copied = solve(
            data,
            MaxIterations(args.iterations),
            seed=args.seed,
            collect_stats=False,
            display=False,
        )
        assignment_algorithm = build_customer_assignment_hgs(
            data,
            seed=args.seed,
        )
        assignment = assignment_algorithm.run(
            MaxIterations(args.iterations),
            collect_stats=False,
            display=False,
        )
        accounting = asdict(
            assignment_algorithm.assignment_accounting
        )
        arms = (
            ("direct_copied_hgs", copied),
            ("copied_hgs_plus_customer_assignment", assignment),
        )
        rows = []
        for arm, result in arms:
            service = _service(data, result.best)
            rows.append(
                {
                    "arm": arm,
                    "cost": int(result.cost()),
                    "iterations": int(result.num_iterations),
                    "runtime_seconds": float(result.runtime),
                    **service,
                }
            )
        if any(not _service_ok(_service(data, result.best)) for _, result in arms):
            raise AssertionError("in-search trial changed service or feasibility")
        with (output / "raw_runs.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        decision = {
            "verdict": "TECHNICAL_TRIAL_COMPLETE",
            "formal_performance_result": False,
            "instance": args.instance,
            "seed": args.seed,
            "iterations": args.iterations,
            "direct_copied_hgs_cost": int(copied.cost()),
            "assignment_hgs_cost": int(assignment.cost()),
            "assignment_minus_copied_cost": (
                int(assignment.cost()) - int(copied.cost())
            ),
            "direct_copied_hgs_runtime_seconds": float(copied.runtime),
            "assignment_hgs_runtime_seconds": float(assignment.runtime),
            "assignment_accounting": accounting,
        }
        _json(output / "decision.json", decision)
        _json(
            output / "best_solutions.json",
            {
                arm: {
                    "cost": int(result.cost()),
                    **_service(data, result.best),
                    "routes": [
                        {
                            "vehicle_type": int(route.vehicle_type()),
                            "start_depot": int(route.start_depot()),
                            "end_depot": int(route.end_depot()),
                            "customer_nodes": list(map(int, route.visits())),
                        }
                        for route in result.best.routes()
                    ],
                }
                for arm, result in arms
            },
        )
        metadata = json.loads(
            (output / "metadata.json").read_text(encoding="utf-8")
        )
        metadata["status"] = "COMPLETE"
        _json(output / "metadata.json", metadata)
        (output / "report.md").write_text(
            "# 客户级跨车场重插入的搜索内归因试跑\n\n"
            f"{args.instance}、seed {args.seed}、固定 {args.iterations} 轮：直接复制底座成本 {copied.cost()}，"
            f"加入客户级跨车场重插入后成本 {assignment.cost()}；两者运行时间分别为 {copied.runtime:.6f} 秒和 {assignment.runtime:.6f} 秒。"
            f"重插入被调用 {accounting['calls']} 次，直接产生改善 {accounting['accepted_calls']} 次。\n\n"
            "固定轮数只用于看部件是否实际参与及其原始代价，不是正式性能比较。\n\n"
            "## 交付前九条自检\n\n"
            "1. 事实出处——成本、服务量、时间和调用账来自本包。\n"
            "2. 建议是否冒充已决——没有。\n"
            "3. 是否越界——没有，只比较直接复制底座和单一文献部件。\n"
            "4. 受保护文件——本入口不修改它们。\n"
            "5. 待决项——不以本次单次试跑替用户处置部件。\n"
            "6. 自造术语——没有。\n"
            "7. 失败异常——按实际状态保留。\n"
            "8. 产物包——五件套和双方路线齐全。\n"
            "9. 交接记录——总任务收尾时统一同步。\n",
            encoding="utf-8",
        )
        _write_hashes(output)
        print(json.dumps(decision, ensure_ascii=False))
        return 0
    except Exception as error:
        metadata = json.loads(
            (output / "metadata.json").read_text(encoding="utf-8")
        )
        metadata["status"] = "FAILED"
        _json(output / "metadata.json", metadata)
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
        with (output / "raw_runs.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle, fieldnames=("verdict", "error_type", "error")
            )
            writer.writeheader()
            writer.writerow(
                {
                    "verdict": "TECHNICAL_TRIAL_FAILED",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
        (output / "report.md").write_text(
            "# 客户级跨车场重插入搜索内试跑失败\n\n"
            f"{type(error).__name__}: {error}\n",
            encoding="utf-8",
        )
        _write_hashes(output)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
