#!/usr/bin/env python3
"""Run one bounded public convergence scout in one isolated implementation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from importlib.metadata import version
from pathlib import Path


PUBLIC_INSTANCE_ROUND_FUNC = "exact"
PUBLIC_INSTANCE_SCALE = 1_000


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


def _routes(solution) -> list[dict[str, object]]:
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
    parser.add_argument("--instance", required=True)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--no-improvement", type=int, default=5000)
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument("--max-runtime-seconds", type=float, default=1200.0)
    parser.add_argument(
        "--implementation",
        choices=("independent", "frozen_pyvrp"),
        required=True,
    )
    parser.add_argument(
        "--compound-mode",
        choices=("copied", "route_only", "full"),
        default="full",
        help=(
            "independent implementation only: copied HGS loop, route-level "
            "compound refinement, or route plus customer refinement"
        ),
    )
    parser.add_argument(
        "--refinement-scope",
        choices=("every_feasible", "new_incumbent"),
        default="new_incumbent",
        help=(
            "independent implementation only: run the compound refinement "
            "on every feasible child or only on a new objective incumbent"
        ),
    )
    args = parser.parse_args()
    if args.no_improvement < 1:
        raise ValueError("no-improvement iterations must be positive")
    if args.max_iterations is not None and args.max_iterations < 1:
        raise ValueError("maximum iterations must be positive")
    if not 0 < args.max_runtime_seconds <= 1200:
        raise ValueError("runtime must be in (0, 1200] seconds")

    if args.implementation == "frozen_pyvrp":
        if args.compound_mode != "full":
            raise ValueError(
                "compound controls only apply to the independent implementation"
            )
        if importlib.util.find_spec("setp_hgs_kernel") is not None:
            raise RuntimeError("frozen baseline environment contains copied kernel")
        from pyvrp import read, solve
        from pyvrp.stop import (
            MaxIterations,
            MaxRuntime,
            MultipleCriteria,
            NoImprovement,
        )

        if version("pyvrp") != "0.12.2":
            raise RuntimeError("frozen baseline must be PyVRP 0.12.2")
    else:
        if importlib.util.find_spec("pyvrp") is not None:
            raise RuntimeError("independent environment contains PyVRP")
        from setp_hgs_kernel.stop import (
            MaxIterations,
            MaxRuntime,
            MultipleCriteria,
            NoImprovement,
        )
        from setp_solver.algorithms.problem_hgs.public_search import (
            build_integrated_public_hgs,
            read_public_instance,
        )

        if version("setp-hgs-kernel") != "0.12.2":
            raise RuntimeError("independent kernel must be 0.12.2")

    repo = Path(__file__).resolve().parents[2]
    instance_path = (
        repo
        / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
        / "sources/normalised_instances"
        / f"{args.instance}.vrp"
    )
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": "bounded convergence scout; not a formal experiment",
            "implementation": args.implementation,
            "instance": args.instance,
            "seed": args.seed,
            "no_improvement": args.no_improvement,
            "max_iterations": args.max_iterations,
            "max_runtime_seconds": args.max_runtime_seconds,
            "round_func": PUBLIC_INSTANCE_ROUND_FUNC,
            "integer_scale": PUBLIC_INSTANCE_SCALE,
            "compound_mode": args.compound_mode,
            "refinement_scope": args.refinement_scope,
            "instance_sha256": _sha256(instance_path),
            "python_executable": sys.executable,
            "runner_sha256": _sha256(Path(__file__).resolve()),
        },
    )
    data = (
        read(instance_path, round_func=PUBLIC_INSTANCE_ROUND_FUNC)
        if args.implementation == "frozen_pyvrp"
        else read_public_instance(instance_path)
    )
    stop = MultipleCriteria(
        [
            (
                MaxIterations(args.max_iterations)
                if args.max_iterations is not None
                else NoImprovement(args.no_improvement)
            ),
            MaxRuntime(args.max_runtime_seconds),
        ]
    )
    if args.implementation == "frozen_pyvrp":
        result = solve(
            data,
            stop,
            seed=args.seed,
            collect_stats=False,
            display=False,
        )
        solution = result.best
        cost = int(result.cost())
        iterations = int(result.num_iterations)
        runtime = float(result.runtime)
        compound = None
    else:
        bundle = build_integrated_public_hgs(
            data,
            seed=args.seed,
            enable_vidal_compound=args.compound_mode != "copied",
            enable_customer_relocation=args.compound_mode == "full",
            refinement_scope=args.refinement_scope,
        )
        integrated = bundle.algorithm.run(stop)
        solution = integrated.best.solution
        cost = int(integrated.best.evaluation.objective)
        iterations = int(integrated.accounting.iterations)
        runtime = float(integrated.accounting.elapsed_seconds)
        compound = {
            key: value
            for key, value in vars(bundle.vidal_accounting).items()
        }
    service = _service(data, solution)
    if not (
        service["complete"]
        and service["feasible"]
        and service["no_duplicate_clients"]
        and service["completed_clients"] == service["total_clients"]
        and service["completed_delivery"] == service["total_delivery"]
    ):
        raise RuntimeError("convergence scout changed service or feasibility")
    row = {
        "implementation": args.implementation,
        "instance": args.instance,
        "seed": args.seed,
        "compound_mode": (
            args.compound_mode
            if args.implementation == "independent"
            else "not_applicable"
        ),
        "refinement_scope": (
            args.refinement_scope
            if args.implementation == "independent"
            else "not_applicable"
        ),
        "iterations": iterations,
        "runtime_seconds": runtime,
        "cost": cost,
        **service,
    }
    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(row))
        writer.writeheader()
        writer.writerow(row)
    decision = {
        "verdict": "TECHNICAL_SCOUT_COMPLETE",
        "formal_performance_result": False,
        **row,
        "compound_accounting": compound,
    }
    _json(output / "decision.json", decision)
    _json(output / "best_solution.json", {**row, "routes": _routes(solution)})
    (output / "report.md").write_text(
        "# 公开收敛短试\n\n"
        f"{args.implementation} 在 {args.instance}、seed {args.seed} 上运行 "
        f"{iterations} 代，用时 {runtime:.3f} 秒，成本 {cost}。"
        "本次是算法定型前短试，不是正式实验。\n",
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
