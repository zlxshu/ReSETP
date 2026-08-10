#!/usr/bin/env python3
"""Run one bounded 28-instance attribution scout for the integrated public HGS."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from setp_hgs_kernel import read
from setp_hgs_kernel.stop import MaxIterations
from setp_solver.algorithms.problem_hgs.public_search import (
    build_integrated_public_hgs,
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


def _route_sha256(solution) -> str:
    payload = sorted(
        (
            int(route.vehicle_type()),
            tuple(int(customer) for customer in route.visits()),
        )
        for route in solution.routes()
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def _run_one(
    task: tuple[str, str, int, int, str],
) -> list[dict[str, object]]:
    instance, path, seed, iterations, round_func = task
    data = read(Path(path), round_func=round_func)
    rows = []
    arms = (
        ("copied_loop", False, False),
        ("route_only_compound", True, False),
        ("full_customer_compound", True, True),
    )
    for arm, compound_enabled, customer_enabled in arms:
        bundle = build_integrated_public_hgs(
            data,
            seed=seed,
            enable_vidal_compound=compound_enabled,
            enable_customer_relocation=customer_enabled,
        )
        started = perf_counter()
        result = bundle.algorithm.run(MaxIterations(iterations))
        runtime = perf_counter() - started
        solution = result.best.solution
        evaluation = result.best.evaluation
        service = _service(data, solution)
        if not (
            service["complete"]
            and service["feasible"]
            and service["no_duplicate_clients"]
            and service["completed_clients"] == service["total_clients"]
            and service["completed_delivery"] == service["total_delivery"]
        ):
            raise RuntimeError(f"{instance} changed service or feasibility")
        rows.append(
            {
                "instance": instance,
                "arm": arm,
                "seed": seed,
                "requested_iterations": iterations,
                "iterations": result.accounting.iterations,
                "runtime_seconds": runtime,
                "cost": int(evaluation.objective),
                "route_sha256": _route_sha256(solution),
                **service,
                **{
                    f"compound_{key}": value
                    for key, value in asdict(bundle.vidal_accounting).items()
                },
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--instances", nargs="*")
    parser.add_argument(
        "--round-func",
        choices=("round", "exact"),
        default="round",
    )
    args = parser.parse_args()
    if args.iterations < 1 or args.workers < 1:
        raise ValueError("iterations and workers must be positive")

    repo = Path(__file__).resolve().parents[2]
    source = (
        repo
        / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
        / "sources/normalised_instances"
    )
    available = tuple(sorted(path.stem for path in source.glob("*.vrp")))
    if len(available) != 28:
        raise RuntimeError(f"expected 28 public instances, found {len(available)}")
    instances = tuple(args.instances) if args.instances else available
    unknown = sorted(set(instances) - set(available))
    if not instances or unknown:
        raise ValueError(f"invalid public instance selection: {unknown}")
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": "bounded component attribution scout; not a formal experiment",
            "instances": instances,
            "seed": args.seed,
            "iterations": args.iterations,
            "workers": args.workers,
            "round_func": args.round_func,
            "runner_sha256": _sha256(Path(__file__).resolve()),
            "public_search_sha256": _sha256(
                repo
                / "solver/src/setp_solver/algorithms/problem_hgs/public_search.py"
            ),
            "vidal_compound_sha256": _sha256(
                repo
                / "solver/src/setp_solver/algorithms/problem_hgs/vidal_compound.py"
            ),
        },
    )
    tasks = tuple(
        (
            instance,
            str(source / f"{instance}.vrp"),
            args.seed,
            args.iterations,
            args.round_func,
        )
        for instance in instances
    )
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        nested = tuple(executor.map(_run_one, tasks))
    rows = [row for pair in nested for row in pair]
    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    by_instance = {
        instance: {
            row["arm"]: row for row in rows if row["instance"] == instance
        }
        for instance in instances
    }
    full_vs_copied = {
        instance: int(arms["full_customer_compound"]["cost"])
        - int(arms["copied_loop"]["cost"])
        for instance, arms in by_instance.items()
    }
    full_vs_route_only = {
        instance: int(arms["full_customer_compound"]["cost"])
        - int(arms["route_only_compound"]["cost"])
        for instance, arms in by_instance.items()
    }
    wins = sum(delta < 0 for delta in full_vs_route_only.values())
    losses = sum(delta > 0 for delta in full_vs_route_only.values())
    ties = sum(delta == 0 for delta in full_vs_route_only.values())
    decision = {
        "verdict": "TECHNICAL_SCOUT_COMPLETE",
        "formal_performance_result": False,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "mean_full_vs_route_only_delta": (
            sum(full_vs_route_only.values()) / len(full_vs_route_only)
        ),
        "full_vs_route_only": full_vs_route_only,
        "full_vs_copied": full_vs_copied,
    }
    _json(output / "decision.json", decision)
    (output / "report.md").write_text(
        "# 独立公开算法部件试跑\n\n"
        f"同一种子、固定 {args.iterations} 代，{len(instances)} 个公开算例："
        f"补全客户移动后，相对原整路线联合评价胜 {wins}、负 {losses}、平 {ties}。"
        "这是快速归因试跑，不是正式实验。\n",
        encoding="utf-8",
    )
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    metadata["status"] = "COMPLETE"
    _json(output / "metadata.json", metadata)
    _json(
        output / "artifact_hashes.json",
        {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file() and path.name != "artifact_hashes.json"
        },
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
