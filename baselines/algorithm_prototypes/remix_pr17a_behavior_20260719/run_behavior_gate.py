#!/usr/bin/env python3
"""Execute and independently audit the ReMIX PR17A behaviour gate."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.freeze_mdvrptw_v13_foundation_20260719 import (  # noqa: E402
    build_hash_manifest,
    parse_normalised,
    validate_solution_independently,
    write_json,
)


HERE = Path(__file__).resolve().parent
WORKER = HERE / "behavior_worker.py"
INSTANCE = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "mdvrptw_v13_comparison_20260719"
    / "sources"
    / "normalised_instances"
    / "PR17A.vrp"
)
OUTPUT = (
    REPO
    / "baselines"
    / "algorithm_foundation"
    / "remix_pr17a_behavior_gate_v2_20260719"
)
BUDGETS = (0, 1, 2, 5)
SEED = 1
CORE_OUTPUTS = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def assign_routes_to_vehicles(
    normalised: Any,
    route_records: list[dict[str, Any]],
) -> dict[int, list[int]]:
    routes = {
        vehicle: []
        for vehicle in range(1, normalised.num_vehicles + 1)
    }
    available: dict[int, list[int]] = {}
    for vehicle, depot in normalised.vehicle_depots.items():
        available.setdefault(depot - 1, []).append(vehicle)
    used = {depot: 0 for depot in available}
    for record in route_records:
        depot = int(record["start_depot"])
        if int(record["end_depot"]) != depot:
            raise ValueError("route starts and ends at different depots")
        position = used[depot]
        if position >= len(available[depot]):
            raise ValueError("solution exceeds depot vehicle availability")
        vehicle = available[depot][position]
        used[depot] += 1
        routes[vehicle] = [int(client) for client in record["visits"]]
    return routes


def has_complete_flow(trace: list[dict[str, Any]]) -> bool:
    ingests = [
        event
        for event in trace
        if event.get("stage") == "elite_pool_ingest"
    ]
    return any(
        "route_exchange" in event.get("lineage", [])
        and "destroy_repair" in event.get("lineage", [])
        and "local_search" in event.get("lineage", [])
        and any(
            str(item).startswith("island:")
            for item in event.get("lineage", [])
        )
        for event in ingests
    )


def main() -> int:
    for filename in CORE_OUTPUTS:
        if (OUTPUT / filename).exists():
            raise FileExistsError(
                f"refusing to overwrite behaviour evidence: {OUTPUT / filename}"
            )
    if not INSTANCE.is_file():
        raise FileNotFoundError(INSTANCE)

    started = datetime.now(timezone.utc)
    protected_before = {
        path.relative_to(REPO).as_posix(): sha256_file(path)
        for path in PROTECTED
    }
    run_dir = OUTPUT / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "PYTHONHASHSEED": str(SEED),
        }
    )

    arms = [("mother", None), *[(f"budget_{b}", b) for b in BUDGETS]]
    outputs: dict[str, dict[str, Any]] = {}
    for mode, budget in arms:
        scratch = run_dir / mode
        command = [
            sys.executable,
            str(WORKER),
            "--instance",
            str(INSTANCE),
            "--seed",
            str(SEED),
            "--scratch",
            str(scratch),
        ]
        if mode == "mother":
            command.append("--mother")
        else:
            command.extend(["--budget", str(budget)])
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"{mode} failed: stdout={completed.stdout} "
                f"stderr={completed.stderr}"
            )
        output = json.loads(completed.stdout)
        outputs[mode] = output
        write_json(run_dir / f"{mode}.json", output)

    normalised = parse_normalised(INSTANCE.read_text(encoding="utf-8"))
    independent: dict[str, dict[str, Any]] = {}
    for mode, output in outputs.items():
        payload = output["deterministic_payload"]
        vehicle_routes = assign_routes_to_vehicles(
            normalised,
            payload["routes"],
        )
        check = validate_solution_independently(
            normalised,
            vehicle_routes,
            int(payload["distance"]),
        )
        independent[mode] = check
        if not check["all_checks_pass"]:
            raise ValueError(f"{mode}: independent validation failed")

    zero_identity = (
        outputs["mother"]["deterministic_signature_sha256"]
        == outputs["budget_0"]["deterministic_signature_sha256"]
    )
    zero_calls = (
        outputs["budget_0"]["component_counters"]["enhancement_calls"] == 0
    )
    exact_call_counts = all(
        outputs[f"budget_{budget}"]["component_counters"][
            "route_exchange_calls"
        ]
        == budget
        and outputs[f"budget_{budget}"]["component_counters"][
            "destroy_repair_calls"
        ]
        == budget
        and outputs[f"budget_{budget}"]["component_counters"][
            "local_search_calls"
        ]
        == budget
        and outputs[f"budget_{budget}"]["component_counters"][
            "route_pool_calls"
        ]
        == 1
        for budget in (1, 2, 5)
    )
    all_islands_entered = all(
        {"island_0", "island_1", "island_2"}
        <= set(
            outputs[f"budget_{budget}"]["route_pool"].get(
                "input_sources",
                [],
            )
        )
        for budget in (1, 2, 5)
    )
    complete_flow = all(
        has_complete_flow(outputs[f"budget_{budget}"]["trace"])
        for budget in (1, 2, 5)
    )
    route_pool_success = all(
        outputs[f"budget_{budget}"]["route_pool"].get("success", False)
        for budget in (1, 2, 5)
    )
    cross_source_selected = any(
        len(
            outputs[f"budget_{budget}"]["route_pool"].get(
                "selected_sources",
                [],
            )
        )
        >= 2
        for budget in (1, 2, 5)
    )
    all_valid = all(
        output["deterministic_payload"]["complete"]
        and output["deterministic_payload"]["feasible"]
        and independent[mode]["all_checks_pass"]
        for mode, output in outputs.items()
    )
    protected_after = {
        path.relative_to(REPO).as_posix(): sha256_file(path)
        for path in PROTECTED
    }
    protected_unchanged = protected_before == protected_after

    hard_pass = (
        zero_identity
        and zero_calls
        and exact_call_counts
        and all_islands_entered
        and complete_flow
        and route_pool_success
        and all_valid
        and protected_unchanged
    )
    if not hard_pass:
        verdict = "FAIL_REMIX_PR17A_BEHAVIOR"
    elif not cross_source_selected:
        verdict = "HOLD_ROUTE_POOL_CROSS_SOURCE_UNPROVEN"
    else:
        verdict = "PASS_REMIX_PR17A_BEHAVIOR"

    rows = []
    for mode, output in outputs.items():
        payload = output["deterministic_payload"]
        counters = output["component_counters"]
        rows.append(
            {
                "mode": mode,
                "seed": SEED,
                "budget": output["requested_budget"],
                "distance": payload["distance"],
                "routes": payload["num_routes"],
                "complete": str(payload["complete"]).lower(),
                "feasible": str(payload["feasible"]).lower(),
                "independent_valid": str(
                    independent[mode]["all_checks_pass"]
                ).lower(),
                "independent_validation_calls_runner": 1,
                "island_calls": counters["island_solve_calls"],
                "exchange_calls": counters["route_exchange_calls"],
                "destroy_repair_calls": counters["destroy_repair_calls"],
                "local_search_calls": counters["local_search_calls"],
                "route_pool_calls": counters["route_pool_calls"],
                "route_pool_sources_selected": len(
                    output.get("route_pool", {}).get(
                        "selected_sources",
                        [],
                    )
                ),
                "best_source": output["best_source"],
                "signature_sha256": output[
                    "deterministic_signature_sha256"
                ],
            }
        )
    write_csv(OUTPUT / "raw_runs.csv", rows)

    decision = {
        "verdict": verdict,
        "zero_budget_matches_mother": zero_identity,
        "zero_budget_component_calls_zero": zero_calls,
        "positive_budget_call_counts_exact": exact_call_counts,
        "all_three_islands_entered_elite_pool": all_islands_entered,
        "complete_upstream_to_pool_lineage_observed": complete_flow,
        "route_pool_milp_success_all_positive_budgets": route_pool_success,
        "cross_source_routes_selected_in_at_least_one_budget": (
            cross_source_selected
        ),
        "all_final_solutions_complete_feasible_independently_valid": all_valid,
        "protected_files_unchanged": protected_unchanged,
        "performance_claim_allowed": False,
        "six_instance_development_authorized": verdict
        == "PASS_REMIX_PR17A_BEHAVIOR",
        "formal_28_instance_run_authorized": False,
        "china81_authorized": False,
        "stage2_authorized": False,
        "honest_boundary": (
            "This gate proves component flow and accounting only. "
            "It does not prove performance or a new BKS."
        ),
    }
    write_json(OUTPUT / "decision.json", decision)

    finished = datetime.now(timezone.utc)
    metadata = {
        "contract": "REMIX-BEHAVIOR-PR17A-001",
        "purpose": (
            "audit-identical replay correcting v1 validation accounting"
        ),
        "supersedes_for_audit_accounting": (
            "baselines/algorithm_foundation/"
            "remix_pr17a_behavior_gate_20260719"
        ),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pyvrp": version("pyvrp"),
            "scipy_subprocess": "/opt/anaconda3/bin/python",
        },
        "input": {
            "instance": INSTANCE.relative_to(REPO).as_posix(),
            "instance_sha256": sha256_file(INSTANCE),
            "seed": SEED,
            "budgets": list(BUDGETS),
            "island_seeds": [1, 1001, 2001],
            "island_iterations": 2,
        },
        "thread_limits": {
            key: env[key]
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
        "protected_file_hashes_before": protected_before,
        "protected_file_hashes_after": protected_after,
        "counts": {
            "solver_arms": len(outputs),
            "independent_validation_calls": len(independent),
            "performance_search_calls": 0,
            "formal_benchmark_calls": 0,
            "china81_calls": 0,
        },
    }
    write_json(OUTPUT / "metadata.json", metadata)

    report = f"""# ReMIX PR17A 多重混合行为门

判定：`{verdict}`。

本包是 v1 的同输入、同种子、同预算审计重放。算法参数与选择规则没有变化；只把
独立复算次数和“三岛进入路线库”的检查改成直接读取真实执行位置。

## 核验结果

- 预算 0 与母算法逐位一致：`{zero_identity}`。
- 预算 0 增强调用为零：`{zero_calls}`。
- 预算 1/2/5 调用数与合同一致：`{exact_call_counts}`。
- 三个小岛都进入精英库：`{all_islands_entered}`。
- 上游到路线库的完整谱系存在：`{complete_flow}`。
- 三个正预算的精确路线会审都成功：`{route_pool_success}`。
- 至少一次选中两个以上来源的路线：`{cross_source_selected}`。
- 全部最终解经独立复算完整可行：`{all_valid}`。
- 三个保护文件运行前后哈希不变：`{protected_unchanged}`。

## 诚实边界

本门只证明多岛搜索、路线交换、定向拆解重建、邻域精修和精确路线会审能够在
PR17A 上真实传递同一份解，并且预算与可行性账闭合。它不是性能试验，没有刷新
BKS，也不允许声称 ReMIX 胜过任何外部算法。
"""
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    write_json(OUTPUT / "artifact_hashes.json", build_hash_manifest(OUTPUT))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if verdict == "PASS_REMIX_PR17A_BEHAVIOR" else 3


if __name__ == "__main__":
    raise SystemExit(main())
