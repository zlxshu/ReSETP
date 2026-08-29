#!/usr/bin/env python3
"""Run the default public adapter through the independently copied HGS."""

from __future__ import annotations

import argparse
import csv
import json
import traceback
from pathlib import Path
from random import SystemRandom

from setp_hgs_kernel import read, solve
from setp_hgs_kernel.stop import NoImprovement


PUBLIC_INSTANCE_ROUND_FUNC = "exact"
PUBLIC_INSTANCE_SCALE = 1_000
NO_IMPROVEMENT_LIMIT = 500


def _json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
        },
    )
    (output / "report.md").write_text(
        "# 自研 Problem-HGS 公开接口技术试跑失败\n\n"
        f"本次运行失败：{type(error).__name__}: {error}。"
        "错误和调用栈保存在 decision.json。\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance", default="PR17A")
    args = parser.parse_args()

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
            "purpose": "independent Problem-HGS public run",
            "instance": args.instance,
            "stagnation_patience": NO_IMPROVEMENT_LIMIT,
            "default_components": {
                "copied_hgs": True,
                "public_customer_depot_reassignment": False,
                "initial_population_preeducation": False,
            },
            "round_func": PUBLIC_INSTANCE_ROUND_FUNC,
            "integer_scale": PUBLIC_INSTANCE_SCALE,
            "stopping": "500-iteration no-improvement stop",
        },
    )

    try:
        data = read(instance_path, round_func=PUBLIC_INSTANCE_ROUND_FUNC)
        result = solve(
            data,
            NoImprovement(NO_IMPROVEMENT_LIMIT),
            seed=SystemRandom().randrange(2**32),
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
        passed = (
            complete
            and feasible
            and set(visits) == clients
            and len(visits) == len(set(visits))
            and served_delivery == total_delivery
        )
        verdict = "FORMAL_RUN_COMPLETE" if passed else "FORMAL_RUN_FAILED"
        with (output / "raw_runs.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            fieldnames = (
                "instance",
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
                "accepted": passed,
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
        report_body = (
            "# 自研 Problem-HGS 公开算例运行\n\n"
            f"本次在 {args.instance} 上运行 {result.num_iterations} 次 HGS 迭代，"
            f"得到成本 {cost}，完整服务 {len(set(visits))}/{len(clients)} 个客户、"
            f"需求 {served_delivery}/{total_delivery}，运行 {result.runtime:.3f} 秒。\n\n"
            "公开端直接进入 HGS，客户重分车场与初始种群预教育默认关闭。\n"
        )
        (output / "report.md").write_text(
            report_body,
            encoding="utf-8",
        )
        if not passed:
            raise RuntimeError("public copied-HGS technical service checks failed")
        print(json.dumps(json.loads((output / "decision.json").read_text())))
        return 0
    except Exception as error:
        if not (output / "decision.json").exists():
            _write_failure(output, error)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
