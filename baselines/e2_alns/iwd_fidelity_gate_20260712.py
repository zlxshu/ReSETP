#!/usr/bin/env python3
"""Small, isolated fidelity gate for the repaired IWD baseline.

This gate is deliberately outside the sealed E2 matrix.  It compares the
repaired IWD with the frozen implementation and with a fixed-velocity
ablation under the same 280 kWh diagnostic contract.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
OLD_ROOT = REPO_ROOT / ".codex/worktrees/e2-frozen-0124623e"
OLD_WORKER = OLD_ROOT / "baselines/e2_alns/e2_final_closure.py"
GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/iwd_fidelity_gate_20260712"
INSTANCES = ("L-main-threeshift-25c-01", "L-main-threeshift-100c-01")
SEEDS = (1, 2, 3)
ARMS = ("repaired_dynamic", "frozen_legacy", "velocity_fixed")
EVAL_BUDGET = 800
RUNTIME_CAP_SECONDS = 600.0
DIAGNOSTIC_BATTERY_KWH = 280.0
CARBON_PRICE = 0.05034
OLD_COMMIT = "0124623e347cd2a6a5548e07e0af66e16d3b634b"
EXCLUDED_HASH_NAMES = {"artifact_hashes.json", "decision.json"}


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()


def source_sha() -> str:
    return hashlib.sha256((REPO_ROOT / "solver/src/setp_solver/search/metaheuristic_baselines.py").read_bytes()).hexdigest()


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def run_id(arm: str, instance: str, seed: int) -> str:
    return f"IWD_FIDELITY__280KWH__{arm}__{instance}__seed{seed}"


def bundle_rel(instance: str) -> str:
    return f"models/data_bundle/generated_instances/L-main/{instance}"


def task_payload(output_dir: Path, arm: str, instance: str, seed: int, parameter_profile: str) -> dict[str, Any]:
    rid = run_id(arm, instance, seed)
    # The frozen runner requires the same bookkeeping fields as its formal
    # task factory, even though this is only an isolated diagnostic gate.
    checkpoint = output_dir / "checkpoints" / f"{rid}.json"
    return {
        "schema": "resetp.iwd-fidelity-task.v1",
        "repo_root": str(REPO_ROOT),
        "phase": "IWD_FIDELITY_GATE",
        "category": "threeshift",
        "output_dir": str(output_dir),
        "run_id": rid,
        "arm": arm,
        "algorithm": "IWD",
        "instance": instance,
        "seed": int(seed),
        "bundle_dir": bundle_rel(instance),
        "eval_budget": EVAL_BUDGET,
        "runtime_cap_seconds": RUNTIME_CAP_SECONDS,
        "scenario_type": "diagnostic_280_override",
        "parameter_profile": parameter_profile,
        "checkpoint_path": str(checkpoint),
        "execution_commit": git_head(),
        "source_sha256": source_sha(),
        "old_execution_commit": OLD_COMMIT,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def route_signature(solution: Any) -> str:
    payload = sorted(
        (route.vehicle_id, route.vehicle_type.lower(), route.home_depot_id, tuple(route.node_sequence))
        for route in solution.routes
    )
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def first_improvement(history: list[dict[str, Any]], warm_cost: float) -> int | None:
    for item in history:
        if int(float(item.get("eval", 0))) > 0 and safe_float(item.get("best_cost")) < warm_cost - 1e-9:
            return int(float(item["eval"]))
    return None


def run_current(task: dict[str, Any]) -> dict[str, Any]:
    # Imports are kept inside the worker so every row has an isolated solver
    # process and the legacy arm can use a separate frozen checkout.
    from setp_solver.check import check_solution
    from setp_solver.cost import evaluate
    from setp_solver.prices import DEFAULT_PRICES
    from setp_solver.search.bundle import load_search_bundle
    from setp_solver.search.candidates import make_shared_initial_solution
    from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline, solution_to_dict

    started = time.perf_counter()
    prices = replace(DEFAULT_PRICES, B_battery_kwh=DIAGNOSTIC_BATTERY_KWH, carbon_price=CARBON_PRICE)
    bundle_dir = REPO_ROOT / str(task["bundle_dir"])
    bundle = load_search_bundle(bundle_dir)
    warm = make_shared_initial_solution(bundle, prices=prices)
    mode = "fixed" if task["arm"] == "velocity_fixed" else "dynamic"
    parameter_profile = str(task.get("parameter_profile", "canonical"))
    if parameter_profile != "canonical":
        os.environ["SETP_IWD_PARAM_PROFILE"] = parameter_profile
    else:
        os.environ.pop("SETP_IWD_PARAM_PROFILE", None)
    result = run_metaheuristic_baseline(
        "IWD",
        bundle_dir,
        seed=int(task["seed"]),
        eval_budget=EVAL_BUDGET,
        max_runtime_seconds=RUNTIME_CAP_SECONDS,
        initial_solution=warm,
        prices=prices,
        iwd_velocity_mode=mode,
    )
    solution = result.best_solution
    violations = check_solution(solution, bundle.instance, prices) if solution is not None else ["missing_solution"]
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices) if solution is not None else {}
    warm_cost = float(result.shared_seed_cost) if result.shared_seed_cost is not None else math.inf
    best_cost = float(result.best_cost) if result.best_cost is not None else math.inf
    history = list(result.history)
    row = {
        "run_id": task["run_id"],
        "arm": task["arm"],
        "instance": task["instance"],
        "size": int(str(task["instance"]).split("-")[-2][:-1]),
        "seed": int(task["seed"]),
        "scenario_type": task["scenario_type"],
        "eval_budget": EVAL_BUDGET,
        "actual_evals": int(result.evals),
        "eval_closed": int(result.evals) == EVAL_BUDGET,
        "status": result.status,
        "gate_status": "OK" if result.status == "OK" and result.evals == EVAL_BUDGET and not violations else "HALT",
        "failure_reason": result.failure_reason,
        "elapsed_seconds": time.perf_counter() - started,
        "best_cost": best_cost,
        "warm_start_cost": warm_cost,
        "best_below_start": best_cost < warm_cost - 1e-9,
        "first_improvement_eval": first_improvement(history, warm_cost),
        "violation_count": len(violations),
        "route_count": int(result.route_count),
        "route_count_unique": int(result.route_count_unique),
        "candidate_signature_unique": int(result.candidate_signature_unique),
        "candidate_evaluation_count": int(result.candidate_evaluation_count),
        "candidate_feasible_count": int(result.candidate_feasible_count),
        "native_best_updates": int(result.native_best_updates),
        "iwd_velocity_update_count": int(result.iwd_velocity_update_count),
        "liveness_verdict": result.liveness_verdict,
        "liveness_flags": "|".join(result.liveness_flags),
        "best_signature": result.solution_signature_hash,
        "route_structure_signature": route_signature(solution) if solution is not None else "",
        "operator_counts_json": json.dumps(result.operator_counts, ensure_ascii=False, sort_keys=True),
        "parameter_notes_json": json.dumps(result.parameter_notes, ensure_ascii=False, sort_keys=True),
        "history_json": json.dumps(history, ensure_ascii=False, sort_keys=True),
        "solution_json": json.dumps(solution_to_dict(solution), ensure_ascii=False, sort_keys=True) if solution is not None else "",
        "E_total": metrics.get("E_total", math.nan),
        "E_ev_indirect": metrics.get("E_ev_indirect", math.nan),
        "cost_carbon": metrics.get("cost_carbon", math.nan),
        "execution_commit": task["execution_commit"],
        "source_sha256": task["source_sha256"],
        "old_execution_commit": task["old_execution_commit"],
        "parameter_profile": parameter_profile,
    }
    return row


def run_legacy(task: dict[str, Any], task_path: Path, row_path: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONPATH"] = "solver/src:models/src:."
    completed = subprocess.run(
        [GOLD_PYTHON, str(OLD_WORKER), "--task-json", str(task_path), "--task-output-json", str(row_path)],
        cwd=OLD_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=RUNTIME_CAP_SECONDS + 60.0,
        check=False,
    )
    if completed.returncode != 0 or not row_path.exists():
        raise RuntimeError(f"legacy worker failed: rc={completed.returncode}; stderr={completed.stderr[-1000:]}")
    row = read_json(row_path)
    row.update(
        {
            "arm": "frozen_legacy",
            "run_id": task["run_id"],
            "execution_commit": task["old_execution_commit"],
            "source_sha256": hashlib.sha256((OLD_ROOT / "solver/src/setp_solver/search/metaheuristic_baselines.py").read_bytes()).hexdigest(),
            "old_execution_commit": task["old_execution_commit"],
        }
    )
    # The legacy runner already records the same core history/solution fields;
    # keep the missing new diagnostics explicit rather than inferring them.
    row.setdefault("candidate_signature_unique", "")
    row.setdefault("candidate_evaluation_count", "")
    row.setdefault("candidate_feasible_count", "")
    row.setdefault("iwd_velocity_update_count", 0)
    row.setdefault("warm_start_cost", row.get("shared_seed_cost", math.nan))
    row["best_below_start"] = safe_float(row.get("best_cost")) < safe_float(row.get("warm_start_cost")) - 1e-9
    history = json.loads(str(row.get("history_json", "[]")) or "[]")
    row["first_improvement_eval"] = first_improvement(history, safe_float(row.get("warm_start_cost")))
    row["violation_count"] = int(float(row.get("violation_count", 0)))
    row["eval_closed"] = int(float(row.get("actual_evals", 0))) == EVAL_BUDGET
    row["gate_status"] = "OK" if row.get("status") == "OK" and row["eval_closed"] and row["violation_count"] == 0 else "HALT"
    return row


def worker_main(task_path: Path, row_path: Path) -> None:
    task = read_json(task_path)
    if task["arm"] == "frozen_legacy":
        row = run_legacy(task, task_path, row_path)
    else:
        row = run_current(task)
    write_json(row_path, row)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def hash_artifacts(root: Path) -> dict[str, Any]:
    root = root.resolve()
    repo_root = REPO_ROOT.resolve()
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in EXCLUDED_HASH_NAMES or path.name.startswith("._") or ".tasks" in path.parts:
            continue
        files.append({"path": str(path.relative_to(repo_root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {"schema": "resetp.iwd-fidelity-artifacts.v1", "files": files}


def evaluate_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = len(INSTANCES) * len(SEEDS) * len(ARMS)
    p1 = len(rows) == expected and all(
        row.get("gate_status") == "OK" and int(float(row.get("actual_evals", -1))) == EVAL_BUDGET and int(float(row.get("violation_count", -1))) == 0
        for row in rows
    )
    repaired = {(row["instance"], int(row["seed"])): row for row in rows if row.get("arm") == "repaired_dynamic"}
    legacy = {(row["instance"], int(row["seed"])): row for row in rows if row.get("arm") == "frozen_legacy"}
    fixed = {(row["instance"], int(row["seed"])): row for row in rows if row.get("arm") == "velocity_fixed"}
    p2 = sum(bool(repaired[("L-main-threeshift-25c-01", seed)].get("best_below_start")) for seed in SEEDS if ("L-main-threeshift-25c-01", seed) in repaired) >= 2
    p3 = sum(bool(repaired[("L-main-threeshift-100c-01", seed)].get("best_below_start")) for seed in SEEDS if ("L-main-threeshift-100c-01", seed) in repaired) >= 2
    p4_items = []
    for key, dynamic in repaired.items():
        fixed_row = fixed.get(key, {})
        p4_items.append(
            safe_float(dynamic.get("best_cost")) != safe_float(fixed_row.get("best_cost"))
            or str(dynamic.get("history_json", "")) != str(fixed_row.get("history_json", ""))
            or str(dynamic.get("candidate_signature_unique", "")) != str(fixed_row.get("candidate_signature_unique", ""))
        )
    p4 = len(p4_items) == 6 and all(p4_items)
    p5_items = []
    for key, dynamic in repaired.items():
        legacy_row = legacy.get(key, {})
        p5_items.append(safe_float(dynamic.get("best_cost")) < safe_float(legacy_row.get("best_cost")) - 1e-9)
    p5 = sum(p5_items) >= 5
    return {
        "schema": "resetp.iwd-fidelity-gate-decision.v1",
        "verdict": "IWD_FIDELITY_GATE_PASS" if all((p1, p2, p3, p4, p5)) else "IWD_FIDELITY_GATE_FAIL",
        "expected_rows": expected,
        "observed_rows": len(rows),
        "criteria": {
            "P1_all_18_zero_violation_exact_800": p1,
            "P2_repaired_25c_beats_start_at_least_2_of_3": p2,
            "P3_repaired_100c_beats_start_at_least_2_of_3": p3,
            "P4_dynamic_vs_fixed_velocity_differs_on_all_6_pairs": p4,
            "P5_repaired_beats_frozen_legacy_on_at_least_5_of_6": p5,
        },
        "counts": {
            "repaired_25c_beats": sum(bool(repaired[("L-main-threeshift-25c-01", seed)].get("best_below_start")) for seed in SEEDS if ("L-main-threeshift-25c-01", seed) in repaired),
            "repaired_100c_beats": sum(bool(repaired[("L-main-threeshift-100c-01", seed)].get("best_below_start")) for seed in SEEDS if ("L-main-threeshift-100c-01", seed) in repaired),
            "dynamic_fixed_differences": sum(p4_items),
            "repaired_legacy_wins": sum(p5_items),
        },
        "execution_commit": git_head(),
        "source_sha256": source_sha(),
        "old_execution_commit": OLD_COMMIT,
        "formal_e2_untouched": True,
    }


def run_matrix(output_dir: Path, workers: int, parameter_profile: str) -> int:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir = output_dir / ".tasks"
    solutions_dir = output_dir / "solutions"
    tasks_dir.mkdir(exist_ok=True)
    solutions_dir.mkdir(exist_ok=True)
    metadata = {
        "schema": "resetp.iwd-fidelity-gate-metadata.v1",
        "purpose": "post-E2 IWD fidelity gate; not formal E2 evidence",
        "instances": list(INSTANCES),
        "seeds": list(SEEDS),
        "arms": list(ARMS),
        "eval_budget": EVAL_BUDGET,
        "battery_kwh": DIAGNOSTIC_BATTERY_KWH,
        "carbon_price": CARBON_PRICE,
        "workers": int(workers),
        "python": GOLD_PYTHON,
        "numpy_expected": "2.3.5",
        "pythonhashseed": "0",
        "execution_commit": git_head(),
        "source_sha256": source_sha(),
        "old_execution_commit": OLD_COMMIT,
        "parameter_profile": parameter_profile,
        "formula_contract": "Zhang-2025 transcription of IWD velocity^2/time^2/soil + Shah-Hosseini soil shift, with existing shared ReSETP decoder",
        "formal_e2_untouched": True,
        "pre_registered": True,
    }
    write_json(output_dir / "metadata.json", metadata)
    formula_parameters = {"soil0": 10000.0, "velocity0": 200.0, "a_s": 1000.0, "b_s": 0.01, "c_s": 1.0, "a_v": 1000.0, "b_v": 0.01, "c_v": 1.0, "rho_local": 0.9, "rho_global": 0.9, "epsilon_s": 0.01, "epsilon_v": 0.0001}
    if parameter_profile == "zhang_scaled":
        formula_parameters.update({"soil0": 1000.0, "velocity0": 100.0})
    write_json(
        output_dir / "formula_contract.json",
        {
            "transition": "p(j)=f(soil(i,j))/sum f(soil(i,k)); f=1/(epsilon_s+g(soil))",
            "g_soil": "g(soil(i,j))=soil(i,j)-min(0,min_k soil(i,k))",
            "velocity": "vel(t+1)=vel(t)+a_v/(b_v+c_v*soil(i,j)^2)",
            "time": "Time=d(i,j)/max(epsilon_v,vel)",
            "local_soil": "soil=(1-rho_local)*soil-rho_local*delta_soil",
            "delta_soil": "delta_soil=a_s/(b_s+c_s*Time^2)",
            "global_soil": "soil=(1+rho_global)*soil-rho_global*carried_soil/(N-1) on iteration-best edges",
            "parameters": formula_parameters,
            "source_notes": "This follows the specific Zhang 2025 design transcription recorded in baseline-algorithm-catalog.md and the approved gate prompt; the shared customer-order decoder remains unchanged. The zhang_scaled profile is the one allowed source-aligned rescue round.",
        },
    )
    write_json(output_dir / "decision.json", {"schema": "resetp.iwd-fidelity-gate-decision.v1", "verdict": "PENDING_PRE_REGISTERED", "formal_e2_untouched": True})

    tasks = [task_payload(output_dir, arm, instance, seed, parameter_profile) for arm in ARMS for instance in INSTANCES for seed in SEEDS]
    rows: list[dict[str, Any]] = []

    def execute(task: dict[str, Any]) -> dict[str, Any]:
        # The legacy worker runs from its frozen checkout.  Use absolute
        # paths so a custom rescue output directory cannot be interpreted
        # relative to that checkout.
        task_path = (tasks_dir / f"{task['run_id']}.json").resolve()
        row_path = (tasks_dir / f"{task['run_id']}.row.json").resolve()
        write_json(task_path, task)
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = "0"
        env["PYTHONPATH"] = "solver/src:models/src:."
        if task["parameter_profile"] == "canonical":
            env.pop("SETP_IWD_PARAM_PROFILE", None)
        else:
            env["SETP_IWD_PARAM_PROFILE"] = str(task["parameter_profile"])
        completed = subprocess.run(
            [GOLD_PYTHON, str(Path(__file__).resolve()), "--task-json", str(task_path), "--task-output-json", str(row_path)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=RUNTIME_CAP_SECONDS + 90.0,
            check=False,
        )
        if completed.returncode != 0 or not row_path.exists():
            return {"run_id": task["run_id"], "arm": task["arm"], "instance": task["instance"], "seed": task["seed"], "gate_status": "HALT", "status": "HALT_WORKER", "failure_reason": f"rc={completed.returncode}; stderr={completed.stderr[-1200:]}"}
        row = read_json(row_path)
        if row.get("solution_json"):
            write_json(solutions_dir / f"{task['run_id']}.json", json.loads(str(row["solution_json"])))
        return row

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = {pool.submit(execute, task): task for task in tasks}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            write_csv(output_dir / "raw_runs.csv", sorted(rows, key=lambda item: str(item.get("run_id", ""))))

    rows = sorted(rows, key=lambda item: str(item.get("run_id", "")))
    write_csv(output_dir / "raw_runs.csv", rows)
    decision = evaluate_gate(rows)
    write_json(output_dir / "decision.json", decision)
    report_lines = [
        "# IWD忠实度微门",
        "",
        f"判决：`{decision['verdict']}`。",
        "",
        "这不是正式E2重跑，而是检查修复后的IWD是否真正使用速度、时间和土壤机制。",
        "",
        "## 大白话结果",
        "",
        f"- 共 {len(rows)}/18 行，每行目标 {EVAL_BUDGET} 次完整评价。",
        f"- P1零违规且预算闭合：{decision['criteria']['P1_all_18_zero_violation_exact_800']}。",
        f"- 25c修复版超过起点：{decision['counts']['repaired_25c_beats']}/3。",
        f"- 100c修复版超过起点：{decision['counts']['repaired_100c_beats']}/3。",
        f"- 动态速度与固定速度有差异：{decision['counts']['dynamic_fixed_differences']}/6。",
        f"- 修复版超过封存旧版：{decision['counts']['repaired_legacy_wins']}/6。",
        "",
        "## 边界",
        "",
        "E2封存目录未写入；本门通过也不能直接改写E2主表，必须先做IWD 90行替换并重新核验。",
    ]
    (output_dir / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    write_json(output_dir / "artifact_hashes.json", hash_artifacts(output_dir))
    return 0 if decision["verdict"] == "IWD_FIDELITY_GATE_PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--parameter-profile", choices=("canonical", "zhang_scaled"), default="canonical")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--task-json", type=Path, default=None)
    parser.add_argument("--task-output-json", type=Path, default=None)
    args = parser.parse_args()
    if args.task_json and args.task_output_json:
        worker_main(args.task_json, args.task_output_json)
        return 0
    return run_matrix(args.output_dir, args.workers, args.parameter_profile)


if __name__ == "__main__":
    raise SystemExit(main())
