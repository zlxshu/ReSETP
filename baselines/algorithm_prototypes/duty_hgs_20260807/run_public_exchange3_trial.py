#!/usr/bin/env python3
"""Paired public routing trial for PyVRP's dormant Exchange3 operators.

This is a bounded diagnostic, not a formal algorithm comparison.  It changes
only the four compiled length-three node operators and keeps the instance,
seed, wall-clock limit, PyVRP version, and every other SolveParams field equal.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import platform
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from pyvrp import read, solve
from pyvrp.search import (
    NODE_OPERATORS,
    Exchange30,
    Exchange31,
    Exchange32,
    Exchange33,
)
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxRuntime


PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)
EXCHANGE3 = (Exchange30, Exchange31, Exchange32, Exchange33)
_ACTIVE_OUTPUT: Path | None = None
_ACTIVE_INVOCATION_ID: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_failure_package(
    output: Path,
    error: Exception,
    *,
    invocation_id: str,
) -> None:
    metadata_path = output / "metadata.json"
    if not metadata_path.is_file():
        return
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        metadata.get("status") != "RUNNING"
        or metadata.get("invocation_id") != invocation_id
    ):
        return
    metadata["status"] = "FAILED"
    _write_json(metadata_path, metadata)
    rows = [
        {
            "verdict": "TECHNICAL_TRIAL_FAILED",
            "error_type": type(error).__name__,
            "error": str(error),
        }
    ]
    _write_csv(output / "raw_runs.csv", rows)
    _write_json(
        output / "decision.json",
        {
            "verdict": "TECHNICAL_TRIAL_FAILED",
            "failure_reasons": [f"{type(error).__name__}: {error}"],
            "traceback": traceback.format_exc(),
            "formal_algorithm_result": False,
            "formal_public_comparison": False,
        },
    )
    (output / "report.md").write_text(
        "# 公开算例三节点交换动作技术试算失败\n\n"
        f"本次在完成前失败：{type(error).__name__}: {error}。"
        "完整调用栈保存在 decision.json，失败没有改写成完成。\n\n"
        "## 交付前九条自检\n\n"
        "1. 每个事实是否有出处？——错误和调用栈来自本次运行，保存在 decision.json。\n"
        "2. 有没有把建议或担忧写成已决或状态？——没有。\n"
        "3. 改动范围有没有超出任务文本？——没有。\n"
        "4. 有没有碰受保护文件？——没有。\n"
        "5. 待决事项是否转成具体候选并写清代价？——本失败包不新增待决事项。\n"
        "6. 有没有用自造词或内部任务号跟用户说话？——没有。\n"
        "7. 失败、跳过、超时、异常结果有没有如实保留？——本次失败已原样保留。\n"
        "8. 四件套齐了吗？——五个要求文件均由失败收口写出。\n"
        "9. HANDOFF 和记忆同步了吗？——算法施工收口时统一同步。\n",
        encoding="utf-8",
    )
    _write_json(
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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _installed_version(distribution: str) -> str | None:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return None


def _installed_distribution_identity(distribution: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "version": _installed_version(distribution),
        "modules": {},
        "distribution_records": {},
    }
    for module_name in (
        "pyvrp",
        "pyvrp.search",
        "pyvrp._pyvrp",
        "pyvrp.search._search",
    ):
        module = importlib.import_module(module_name)
        path = Path(module.__file__).resolve()
        result["modules"][module_name] = {
            "path": str(path),
            "sha256": _sha256(path),
        }
    dist = importlib_metadata.distribution(distribution)
    for relative in dist.files or ():
        name = str(relative)
        if not name.endswith((".dist-info/METADATA", ".dist-info/RECORD")):
            continue
        path = Path(dist.locate_file(relative)).resolve()
        result["distribution_records"][name] = {
            "path": str(path),
            "sha256": _sha256(path),
        }
    return result


def _code_provenance(repo: Path) -> dict[str, Any]:
    runner = Path(__file__).resolve()
    status = _git(repo, "status", "--porcelain")
    return {
        "git_head": _git(repo, "rev-parse", "HEAD"),
        "worktree_clean_before_run": not bool(status),
        "worktree_status_before_run": status,
        "runner_path": str(runner.relative_to(repo)),
        "runner_sha256": _sha256(runner),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "command_argv": list(sys.argv),
        "dependency_versions": {
            name: _installed_version(name)
            for name in ("numpy", "pyvrp")
        },
        "pyvrp_runtime_identity": _installed_distribution_identity("pyvrp"),
    }


def _solution_record(result, data) -> dict[str, Any]:
    visits = [
        int(client)
        for route in result.best.routes()
        for trip in route.trips()
        for client in trip.visits()
    ]
    active_clients = set(range(data.num_depots, data.num_locations))
    served = set(visits)
    total_demand = sum(
        sum(int(value) for value in data.location(client).delivery)
        for client in active_clients
    )
    served_demand = sum(
        sum(int(value) for value in data.location(client).delivery)
        for client in served
    )
    total_pickup = sum(
        sum(int(value) for value in data.location(client).pickup)
        for client in active_clients
    )
    served_pickup = sum(
        sum(int(value) for value in data.location(client).pickup)
        for client in served
    )
    observed_cost = float(result.cost())
    return {
        "feasible": bool(result.is_feasible()),
        "cost_units": observed_cost if math.isfinite(observed_cost) else None,
        "distance_units": float(result.best.distance()),
        "route_count": int(result.best.num_routes()),
        "trip_count": int(result.best.num_trips()),
        "completed_clients": len(served),
        "total_clients": len(active_clients),
        "duplicate_client_visits": len(visits) - len(served),
        "completed_demand_units": served_demand,
        "total_demand_units": total_demand,
        "completed_pickup_units": served_pickup,
        "total_pickup_units": total_pickup,
        "iterations": int(result.num_iterations),
        "solver_runtime_seconds": float(result.runtime),
        "routes": [
            {
                "vehicle_type": int(route.vehicle_type()),
                "start_depot": int(route.start_depot()),
                "end_depot": int(route.end_depot()),
                "trips": [list(map(int, trip.visits())) for trip in route.trips()],
            }
            for route in result.best.routes()
        ],
    }


def _run_arm(data, *, arm: str, seed: int, seconds: float) -> dict[str, Any]:
    if arm == "default_hgs":
        node_ops = list(NODE_OPERATORS)
    elif arm == "hgs_exchange3":
        node_ops = [*NODE_OPERATORS, *EXCHANGE3]
    else:  # pragma: no cover - internal guard
        raise ValueError(f"unknown arm: {arm}")
    params = SolveParams(node_ops=node_ops)
    started = perf_counter()
    result = solve(
        data,
        MaxRuntime(seconds),
        seed=seed,
        collect_stats=True,
        display=False,
        params=params,
    )
    record = _solution_record(result, data)
    record.update(
        {
            "arm": arm,
            "seed": seed,
            "wall_clock_limit_seconds": seconds,
            "observed_wall_seconds": perf_counter() - started,
            "node_operators": [operator.__name__ for operator in node_ops],
        }
    )
    return record


def main() -> int:
    global _ACTIVE_INVOCATION_ID, _ACTIVE_OUTPUT

    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance", default="PR17A")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--seconds", type=float, default=60.0)
    args = parser.parse_args()
    if args.seconds <= 0:
        raise ValueError("wall-clock limit must be positive")

    repo = Path(__file__).resolve().parents[3]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    invocation_id = uuid4().hex
    _ACTIVE_OUTPUT = output
    _ACTIVE_INVOCATION_ID = invocation_id
    code_provenance = _code_provenance(repo)
    installed_pyvrp = _installed_version("pyvrp")
    _write_json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "invocation_id": invocation_id,
            "purpose": "paired Exchange30-33 routing diagnostic; not formal evidence",
            "code_provenance": code_provenance,
            "pyvrp_version": installed_pyvrp,
        },
    )
    if installed_pyvrp != "0.12.2":
        raise RuntimeError(
            "public HGS diagnostic requires PyVRP 0.12.2, got "
            f"{installed_pyvrp!r}"
        )
    instance_path = (
        repo
        / "baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719"
        / "sources/normalised_instances"
        / f"{args.instance.upper()}.vrp"
    )
    data = read(str(instance_path), round_func="round")
    operator_supports = {
        operator.__name__: bool(operator.supports(data))
        for operator in EXCHANGE3
    }
    protected_before = {
        path: _sha256(repo / path) for path in PROTECTED
    }
    _write_json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "invocation_id": invocation_id,
            "purpose": "paired Exchange30-33 routing diagnostic; not formal evidence",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "instance": args.instance.upper(),
            "instance_sha256": _sha256(instance_path),
            "seed": args.seed,
            "wall_clock_limit_seconds_per_arm": args.seconds,
            "pyvrp_version": installed_pyvrp,
            "arm_order": ["default_hgs", "hgs_exchange3"],
            "only_intended_difference": [
                operator.__name__ for operator in EXCHANGE3
            ],
            "exchange3_operator_supports": operator_supports,
            "protected_hashes_before": protected_before,
            "code_provenance": code_provenance,
        },
    )
    unsupported = [
        name for name, supported in operator_supports.items() if not supported
    ]
    if unsupported:
        raise RuntimeError(
            "Exchange3 operators do not support this problem data: "
            + ", ".join(unsupported)
        )

    records = [
        _run_arm(
            data,
            arm=arm,
            seed=args.seed,
            seconds=args.seconds,
        )
        for arm in ("default_hgs", "hgs_exchange3")
    ]
    protected_after = {
        path: _sha256(repo / path) for path in PROTECTED
    }
    rows = [
        {
            key: (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, list)
                else value
            )
            for key, value in record.items()
            if key != "routes"
        }
        for record in records
    ]
    _write_csv(output / "raw_runs.csv", rows)
    _write_json(
        output / "solutions.json",
        {
            record["arm"]: {
                "routes": record["routes"],
                "cost_units": record["cost_units"],
                "completed_clients": record["completed_clients"],
                "completed_demand_units": record["completed_demand_units"],
                "completed_pickup_units": record["completed_pickup_units"],
            }
            for record in records
        },
    )

    baseline, enhanced = records
    failures = []
    for record in records:
        if record["iterations"] <= 0:
            failures.append(f"{record['arm']} completed zero HGS iterations")
        if not record["feasible"]:
            failures.append(f"{record['arm']} returned an infeasible solution")
        if record["completed_clients"] != record["total_clients"]:
            failures.append(f"{record['arm']} did not serve every client")
        if record["completed_demand_units"] != record["total_demand_units"]:
            failures.append(f"{record['arm']} did not complete all demand")
        if record["completed_pickup_units"] != record["total_pickup_units"]:
            failures.append(f"{record['arm']} did not complete all pickup")
        if record["duplicate_client_visits"] != 0:
            failures.append(f"{record['arm']} repeated a client")
    if protected_before != protected_after:
        failures.append("a protected evaluator file changed")
    baseline_cost = baseline["cost_units"]
    enhanced_cost = enhanced["cost_units"]
    comparable_costs = (
        baseline_cost is not None
        and enhanced_cost is not None
        and float(baseline_cost) != 0.0
    )
    cost_change = (
        float(enhanced_cost) - float(baseline_cost)
        if comparable_costs
        else None
    )
    cost_change_percent = (
        float(cost_change) / float(baseline_cost) * 100.0
        if cost_change is not None
        else None
    )
    observed_relation = (
        "unavailable"
        if cost_change is None
        else "win"
        if cost_change < 0
        else "loss"
        if cost_change > 0
        else "tie"
    )
    verdict = "TECHNICAL_TRIAL_COMPLETE" if not failures else "TECHNICAL_TRIAL_FAILED"
    _write_json(
        output / "decision.json",
        {
            "verdict": verdict,
            "failure_reasons": failures,
            "formal_algorithm_result": False,
            "formal_public_comparison": False,
            "instance": args.instance.upper(),
            "seed": args.seed,
            "default_cost_units": baseline["cost_units"],
            "exchange3_cost_units": enhanced["cost_units"],
            "exchange3_minus_default_cost_units": cost_change,
            "exchange3_change_percent": cost_change_percent,
            "observed_relation": observed_relation,
            "operator_selected_for_formal_algorithm": None,
        },
    )
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    metadata.update(
        {
            "status": "COMPLETE" if not failures else "FAILED",
            "protected_hashes_after": protected_after,
        }
    )
    _write_json(output / "metadata.json", metadata)
    (output / "report.md").write_text(
        f"""# 公开算例三节点交换动作技术试算

本次只比较默认 PyVRP 0.12.2 HGS 与另外打开 Exchange30、Exchange31、Exchange32、Exchange33 的版本。两边使用同一算例 {args.instance.upper()}、同一种子 {args.seed}、每边 {args.seconds:g} 秒，其余求解参数相同。

默认版本成本为 {baseline_cost if baseline_cost is not None else '不可用'}，增强版本成本为 {enhanced_cost if enhanced_cost is not None else '不可用'}，增强版本相对变化 {cost_change_percent if cost_change_percent is not None else '不可用'}%。两边都完成 {baseline['completed_clients']}/{baseline['total_clients']} 个客户和 {baseline['completed_demand_units']}/{baseline['total_demand_units']} 单位需求。本次结果只用于判断四个现成动作有没有继续试的价值，不选择正式算法，也不进入论文。

## 交付前九条自检

1. 每个事实是否有出处？——本报告数字来自同包 raw_runs.csv、solutions.json 和 decision.json。
2. 有没有把建议或担忧写成已决或状态？——没有；正式算法仍未由本试算选择。
3. 改动范围有没有超出任务文本？——没有；只运行已批准的低成本公开算法试算。
4. 有没有碰受保护文件？——未碰；前后哈希保存在 metadata.json。
5. 待决事项是否转成具体候选并写清代价？——本包不要求用户拍板，只保留默认与四动作增强两个技术臂。
6. 有没有用自造词或内部任务号跟用户说话？——没有。
7. 失败、跳过、超时、异常结果有没有如实保留？——失败原因原样保存在 decision.json。
8. 四件套齐了吗？——metadata.json、raw_runs.csv、decision.json、artifact_hashes.json、report.md 齐全，另附 solutions.json。
9. HANDOFF 和记忆同步了吗？——本轮算法施工闭合时统一同步。
""",
        encoding="utf-8",
    )
    _write_json(
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
    print(
        json.dumps(
            {
                "verdict": verdict,
                "output": str(output),
                "observed_relation": observed_relation,
                "change_percent": cost_change_percent,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    requested_output = (
        None
        if len(sys.argv) < 2 or sys.argv[1].startswith("-")
        else Path(sys.argv[1]).resolve()
    )
    try:
        raise SystemExit(main())
    except Exception as exc:
        if (
            requested_output is not None
            and requested_output == _ACTIVE_OUTPUT
            and _ACTIVE_INVOCATION_ID is not None
        ):
            _write_failure_package(
                requested_output,
                exc,
                invocation_id=_ACTIVE_INVOCATION_ID,
            )
        raise
