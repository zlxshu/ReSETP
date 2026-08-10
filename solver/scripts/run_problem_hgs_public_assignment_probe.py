#!/usr/bin/env python3
"""Probe customer-level depot assignment on one saved public solution."""

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

from setp_hgs_kernel import RandomNumberGenerator, Route, Solution, read
from setp_hgs_kernel.PenaltyManager import PenaltyManager
from setp_hgs_kernel.search import LocalSearch, compute_neighbours
from setp_hgs_kernel.solve import SolveParams
from setp_solver.algorithms.problem_hgs.public_assignment import (
    improve_customer_depot_assignment,
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


def _load_solution(data, payload: dict) -> Solution:
    return Solution(
        data,
        [
            Route(
                data,
                [int(customer) for customer in route["customer_nodes"]],
                int(route["vehicle_type"]),
            )
            for route in payload["routes"]
        ],
    )


def _local_search(data, seed: int) -> LocalSearch:
    parameters = SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))
    search = LocalSearch(
        data,
        rng,
        compute_neighbours(data, parameters.neighbourhood),
    )
    for operator in parameters.node_ops:
        if operator.supports(data):
            search.add_node_operator(operator(data))
    for operator in parameters.route_ops:
        if operator.supports(data):
            search.add_route_operator(operator(data))
    return search


def _service(data, solution: Solution) -> dict[str, int | bool]:
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


def _route_payload(solution: Solution) -> list[dict[str, object]]:
    return [
        {
            "vehicle_type": int(route.vehicle_type()),
            "start_depot": int(route.start_depot()),
            "end_depot": int(route.end_depot()),
            "customer_nodes": list(map(int, route.visits())),
        }
        for route in solution.routes()
    ]


def _service_ok(service: dict[str, int | bool]) -> bool:
    return bool(
        service["complete"]
        and service["feasible"]
        and service["no_duplicate_clients"]
        and service["completed_clients"] == service["total_clients"]
        and service["completed_delivery"] == service["total_delivery"]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--source-package", type=Path, required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--ls-seed", type=int, default=11)
    args = parser.parse_args()
    if importlib.util.find_spec("pyvrp") is not None:
        raise RuntimeError("assignment probe must use the independent environment")

    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    source = args.source_package.resolve()
    source_metadata = json.loads(
        (source / "metadata.json").read_text(encoding="utf-8")
    )
    if (
        source_metadata.get("status") != "COMPLETE"
        or source_metadata.get("instance") != args.instance
    ):
        raise ValueError("source package is not the requested complete instance")
    source_best_path = source / "best_solution.json"
    source_best = json.loads(source_best_path.read_text(encoding="utf-8"))
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
            "purpose": "offline customer-level depot assignment probe",
            "formal_performance_result": False,
            "instance": args.instance,
            "ls_seed": args.ls_seed,
            "source_package": str(source),
            "source_best_solution_sha256": _sha256(source_best_path),
            "source_metadata_sha256": _sha256(source / "metadata.json"),
            "instance_sha256": _sha256(instance_path),
            "runner_sha256": _sha256(Path(__file__).resolve()),
            "assignment_source_sha256": _sha256(
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
        evaluator = PenaltyManager.init_from(data).cost_evaluator()
        original = _load_solution(data, source_best)
        original_cost = int(evaluator.cost(original))
        if original_cost != int(source_best["cost"]):
            raise ValueError("source best cost does not reproduce")

        direct_ls_candidate = _local_search(data, args.ls_seed)(
            original,
            evaluator,
        )
        assignment = improve_customer_depot_assignment(
            data,
            original,
            evaluator,
        )
        assignment_ls_candidate = _local_search(data, args.ls_seed)(
            assignment.solution,
            evaluator,
        )
        source_service = _service(data, original)
        direct_candidate_service = _service(data, direct_ls_candidate)
        assignment_service = _service(data, assignment.solution)
        assignment_candidate_service = _service(
            data,
            assignment_ls_candidate,
        )
        direct_ls_selected = (
            direct_ls_candidate
            if _service_ok(direct_candidate_service)
            and int(evaluator.cost(direct_ls_candidate))
            < int(evaluator.cost(original))
            else original
        )
        assignment_ls_selected = (
            assignment_ls_candidate
            if _service_ok(assignment_candidate_service)
            and int(evaluator.cost(assignment_ls_candidate))
            < int(evaluator.cost(assignment.solution))
            else assignment.solution
        )
        variants = {
            "source": original,
            "source_then_standard_ls_candidate": direct_ls_candidate,
            "source_after_incumbent_safety": direct_ls_selected,
            "assignment": assignment.solution,
            "assignment_then_standard_ls_candidate": (
                assignment_ls_candidate
            ),
            "assignment_after_incumbent_safety": assignment_ls_selected,
        }
        rows = []
        for name, solution in variants.items():
            service = _service(data, solution)
            rows.append(
                {
                    "variant": name,
                    "cost": int(evaluator.cost(solution)),
                    **service,
                }
            )
        required_services = (
            source_service,
            assignment_service,
            _service(data, direct_ls_selected),
            _service(data, assignment_ls_selected),
        )
        if any(not _service_ok(service) for service in required_services):
            raise AssertionError("assignment probe changed service or feasibility")
        with (output / "raw_runs.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        source_cost = int(evaluator.cost(original))
        direct_ls_candidate_cost = int(evaluator.cost(direct_ls_candidate))
        direct_ls_cost = int(evaluator.cost(direct_ls_selected))
        assignment_cost = int(evaluator.cost(assignment.solution))
        assignment_ls_candidate_cost = int(
            evaluator.cost(assignment_ls_candidate)
        )
        assignment_ls_cost = int(evaluator.cost(assignment_ls_selected))
        decision = {
            "verdict": "TECHNICAL_PROBE_COMPLETE",
            "formal_performance_result": False,
            "instance": args.instance,
            "source_cost": source_cost,
            "source_then_standard_ls_candidate_cost": (
                direct_ls_candidate_cost
            ),
            "source_then_standard_ls_candidate_service": (
                direct_candidate_service
            ),
            "source_then_standard_ls_cost": direct_ls_cost,
            "assignment_cost": assignment_cost,
            "assignment_then_standard_ls_candidate_cost": (
                assignment_ls_candidate_cost
            ),
            "assignment_then_standard_ls_candidate_service": (
                assignment_candidate_service
            ),
            "assignment_then_standard_ls_cost": assignment_ls_cost,
            "assignment_direct_delta": assignment_cost - source_cost,
            "paired_post_ls_delta": assignment_ls_cost - direct_ls_cost,
            "assignment_moves": len(assignment.moves),
            "changed_customer_assignments": (
                assignment.changed_customer_assignments
            ),
            "candidate_evaluations": assignment.candidate_evaluations,
            "assignment_runtime_seconds": assignment.runtime_seconds,
            "moves": [asdict(move) for move in assignment.moves],
        }
        _json(output / "decision.json", decision)
        _json(
            output / "best_solution.json",
            {
                "variant": "assignment_then_standard_ls",
                "cost": assignment_ls_cost,
                **_service(data, assignment_ls_selected),
                "routes": _route_payload(assignment_ls_selected),
            },
        )
        metadata = json.loads(
            (output / "metadata.json").read_text(encoding="utf-8")
        )
        metadata["status"] = "COMPLETE"
        _json(output / "metadata.json", metadata)
        (output / "report.md").write_text(
            "# 客户级跨车场重插入诊断\n\n"
            f"{args.instance} 原保存解成本 {source_cost}；原解直接再做同一套标准局部搜索后为 {direct_ls_cost}；"
            f"客户级跨车场重插入后为 {assignment_cost}；再做同一套标准局部搜索并保留较好可行解后为 {assignment_ls_cost}。"
            f"跨场动作 {len(assignment.moves)} 次，最终改变 {assignment.changed_customer_assignments} 个客户的车场归属。"
            f"两次标准局部搜索候选的可行状态分别为 {direct_candidate_service['feasible']} 和 {assignment_candidate_service['feasible']}。"
            f"共枚举 {assignment.candidate_evaluations} 个插入位置，用时 {assignment.runtime_seconds:.6f} 秒。\n\n"
            "本次只检查保存解上的直接增量和是否打开不同局部解，不改变主算法，也不据此决定是否正式接入。\n\n"
            "## 交付前九条自检\n\n"
            "1. 事实出处——全部数字来自本包 raw_runs、decision 和保存路线。\n"
            "2. 建议是否冒充已决——没有，只记录诊断。\n"
            "3. 是否越界——没有，只做已批准的低成本算法诊断。\n"
            "4. 受保护文件——本入口不修改它们。\n"
            "5. 待决项——是否接入仍由后续完整证据决定并交用户。\n"
            "6. 自造术语——没有。\n"
            "7. 失败异常——按实际状态保留。\n"
            "8. 产物包——五件套和 best_solution.json 齐全。\n"
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
                "verdict": "TECHNICAL_PROBE_FAILED",
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
                    "verdict": "TECHNICAL_PROBE_FAILED",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
        (output / "report.md").write_text(
            "# 客户级跨车场重插入诊断失败\n\n"
            f"{type(error).__name__}: {error}\n",
            encoding="utf-8",
        )
        _write_hashes(output)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
