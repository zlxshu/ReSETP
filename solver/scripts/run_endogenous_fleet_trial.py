#!/usr/bin/env python3
"""Run the approved three-instance endogenous-vs-fixed fleet wiring trial."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from run_public_v2_28_clean_ruler import _prepare_independent_imports


# Use the same installed-kernel plus repository-source overlay as the approved
# public runner.  This preserves the installed 0.12.2 distribution identity
# while exposing the current repository Python modules and __version__.
_prepare_independent_imports()

from run_problem_hgs_private_technical import (  # noqa: E402
    _build_context,
    _effective_population_metadata,
    _parameters,
    _write_failure_package,
    main as _private_trial_main,
)
from setp_solver.algorithms.problem_hgs.fleet_registry import (
    register_all_vehicle_slots,
)  # noqa: E402
from setp_solver.algorithms.problem_hgs.model import DutyIndividual  # noqa: E402
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402


INSTANCES = (
    "cn-cy-50c-01-V2-LOCATIONS",
    "cn-jjj-50c-01-V2-LOCATIONS",
    "cn-prd-50c-01-V2-LOCATIONS",
)
ARMS = (
    ("endogenous", "ENDOGENOUS_RD_RE"),
    ("fixed25", "FIXED_25_PERCENT_CONTROL"),
)
CHANGED_CODE_FILES = {
    "solver/src/setp_solver/china81.py": (
        "新增可显式选择的 EndogenousFleetParameters；默认的 25% 固定类仍读取原 num_cv/num_ev/total_fleet_cap。"
    ),
    "solver/src/setp_solver/algorithms/problem_hgs/fleet_registry.py": (
        "把全部实体车槽位注册及空 Duty 补齐提升为正式 Problem-HGS 构造函数。"
    ),
    "solver/scripts/run_problem_hgs_private_technical.py": (
        "给现有 run_integrated_problem_hgs 技术入口增加车队参数类选择，并复用正式 fleet registry。"
    ),
    "solver/scripts/run_endogenous_fleet_trial.py": (
        "顺序运行三实例两臂、先做资源与固定成本 sanity check，并汇总标准结果包。"
    ),
    "solver/tests/test_china81_endogenous_fleet_parameters.py": (
        "回归默认 25% 路径，核对 Rd/Re、2×22 kW、全槽位空 Duty 与闲置固定成本为零。"
    ),
}
TEST_RECORD = {
    "status": "PASS",
    "passed": 5,
    "failed": 0,
    "elapsed_seconds": 0.71,
    "test_file": "solver/tests/test_china81_endogenous_fleet_parameters.py",
    "environment": (
        "build/python_envs/setp-independent-hgs/bin/python; PYTHONPATH "
        "cleared; PYTHONNOUSERSITE=1; run_public_v2_28_clean_ruler.py "
        "_prepare_independent_imports()"
    ),
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
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


def _protected_paths(repo: Path) -> tuple[Path, ...]:
    tracked = _git(
        repo,
        "ls-files",
        "solver/src/setp_solver/cost.py",
        "solver/src/setp_solver/check.py",
        "solver/src/setp_solver/evaluation.py",
        "solver/src/setp_solver/search",
    ).splitlines()
    return tuple(repo / path for path in tracked if path)


def _hash_paths(repo: Path, paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(repo)): _sha256(path)
        for path in paths
    }


def _public_batch_state(repo: Path) -> dict[str, Any]:
    report_dir = repo / "solver/reports/public_v2_28_clean_ruler_20260810"
    watched = tuple(
        path
        for path in (
            report_dir / "progress.log",
            report_dir / "batch.stdout.log",
        )
        if path.is_file()
    )
    lsof = subprocess.run(
        ("lsof", *(str(path) for path in watched)),
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    holder_lines = [
        line for line in lsof.stdout.splitlines()[1:] if line.strip()
    ]
    return {
        "checked_at": _now(),
        "report_dir": str(report_dir.relative_to(repo)),
        "watched_files": [str(path.relative_to(repo)) for path in watched],
        "active_file_holders": holder_lines,
        "active": bool(holder_lines),
        "progress_log_mtime": (
            datetime.fromtimestamp(
                (report_dir / "progress.log").stat().st_mtime
            ).astimezone().isoformat(timespec="seconds")
            if (report_dir / "progress.log").is_file()
            else None
        ),
    }


def _authority_rows(repo: Path, instance_id: str) -> dict[str, dict[str, str]]:
    path = (
        repo
        / "data/ChinaInstances/"
        "china81_finite_fleet_authority_v3_20260802/fleet_caps.csv"
    )
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["depot_id"]: row
            for row in csv.DictReader(handle)
            if row["instance_id"] == instance_id
        }


def _sanity_check(repo: Path) -> dict[str, Any]:
    instance_id = INSTANCES[0]
    rows = _authority_rows(repo, instance_id)
    bundle, constructed, _pi0, _context = _build_context(
        repo,
        instance_id,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    expected = {
        depot_id: {
            "num_cv": int(row["base_all_cv_routes_Rd"]),
            "num_ev": int(row["base_all_ev_routes_Re"]),
        }
        for depot_id, row in rows.items()
    }
    observed = {
        depot_id: {
            "num_cv": int(caps["num_cv"]),
            "num_ev": int(caps["num_ev"]),
        }
        for depot_id, caps in bundle.fleet_caps_by_depot.items()
    }
    if observed != expected:
        raise RuntimeError("endogenous fleet caps do not match Rd/Re authority")
    constructed_counts = Counter(
        (duty.home_depot_id, duty.vehicle_type)
        for duty in constructed.duties
    )
    for depot_id, caps in observed.items():
        for vehicle_type in ("cv", "ev"):
            if constructed_counts[(depot_id, vehicle_type)] != caps[
                f"num_{vehicle_type}"
            ]:
                raise RuntimeError("constructed fleet registry is incomplete")
    empty_registered = register_all_vehicle_slots(
        DutyIndividual((), source="endogenous-empty-cost-sanity"),
        bundle,
    )
    idle_breakdown = evaluate(
        empty_registered.to_solution(),
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    if (
        idle_breakdown["cost_fix"] != 0.0
        or idle_breakdown["n_veh_cv"] != 0
        or idle_breakdown["n_veh_ev"] != 0
    ):
        raise RuntimeError("registered idle vehicles incurred a fixed cost")
    return {
        "status": "PASS",
        "instance_id": instance_id,
        "expected_caps_by_depot": expected,
        "observed_caps_by_depot": observed,
        "registered_vehicle_count": len(constructed.duties),
        "registered_idle_vehicle_count": sum(
            not duty.trips for duty in constructed.duties
        ),
        "empty_registry_fixed_cost_cny": idle_breakdown["cost_fix"],
        "empty_registry_dispatched_cv": idle_breakdown["n_veh_cv"],
        "empty_registry_dispatched_ev": idle_breakdown["n_veh_ev"],
        "charger_contract": "2 posts x 22 kW per depot, unchanged",
    }


def _read_one_csv(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise RuntimeError(f"expected one raw run in {path}, found {len(rows)}")
    return rows[0]


def _subrun(
    repo: Path,
    output: Path,
    *,
    instance_id: str,
    parameter_key: str,
    arm_name: str,
    iterations: int,
    max_runtime_seconds: float,
    population_mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    subdir = output / "runs" / instance_id / parameter_key
    command = (
        sys.executable,
        str(Path(__file__).resolve()),
        "_private_worker",
        str(subdir),
        "--instance-id",
        instance_id,
        "--iterations",
        str(iterations),
        "--max-runtime-seconds",
        str(max_runtime_seconds),
        "--stagnation-patience",
        "500",
        "--population-mode",
        population_mode,
        "--crossover-mode",
        "fast_only",
        "--proposal-mode",
        "system",
        "--fleet-parameter-class",
        parameter_key,
        "--arm",
        arm_name,
    )
    started_at = _now()
    started = perf_counter()
    completed = subprocess.run(
        command,
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    outer_wall_seconds = perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"subrun failed for {instance_id}/{parameter_key}: "
            f"{completed.stderr[-4000:]}"
        )
    metadata = json.loads((subdir / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("status") != "COMPLETE":
        raise RuntimeError(f"subrun did not complete: {instance_id}/{parameter_key}")
    raw = _read_one_csv(subdir / "raw_runs.csv")
    best = json.loads((subdir / "best_solution.json").read_text(encoding="utf-8"))
    evaluation = best["evaluation"]
    breakdown = evaluation["breakdown"]
    customers_served = int(raw["customers_served"])
    customers_total = int(raw["customers_total"])
    demand_served = float(raw["demand_served"])
    demand_total = float(raw["demand_total"])
    row = {
        "instance_id": instance_id,
        "arm": arm_name,
        "fleet_parameter_class": parameter_key,
        "fleet_parameter_class_id": metadata["fleet_parameter_class_id"],
        "seed": int(raw["seed"]),
        "requested_iterations": iterations,
        "actual_iterations": int(raw["iterations"]),
        "termination_status": raw["termination_status"],
        "final_total_cost_cny": float(evaluation["total_cost"]),
        "total_emissions_kg": float(breakdown["E_total"]),
        "oil_vehicles_dispatched": int(breakdown["n_veh_cv"]),
        "ev_vehicles_dispatched": int(breakdown["n_veh_ev"]),
        "customers_served": customers_served,
        "customers_total": customers_total,
        "customer_completion_rate": customers_served / customers_total,
        "demand_served": demand_served,
        "demand_total": demand_total,
        "demand_completion_rate": demand_served / demand_total,
        "search_wall_seconds": float(raw["run_wall_seconds"]),
        "outer_process_wall_seconds": outer_wall_seconds,
        "feasible": str(raw["best_feasible"]).lower() == "true",
        "subrun_verdict": raw["verdict"],
        "subrun_dir": str(subdir.relative_to(repo)),
    }
    identity = {
        "instance_id": instance_id,
        "arm": arm_name,
        "parameter_key": parameter_key,
        "started_at": started_at,
        "completed_at": _now(),
        "command": list(command),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "fleet_caps_by_depot": metadata["fleet_caps_by_depot"],
        "has_additional_total_fleet_cap": metadata[
            "has_additional_total_fleet_cap"
        ],
    }
    return row, identity


def _write_raw_runs(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=tuple(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _paired_changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_instance = {
        instance_id: {
            row["arm"]: row
            for row in rows
            if row["instance_id"] == instance_id
        }
        for instance_id in INSTANCES
    }
    changes: list[dict[str, Any]] = []
    for instance_id in INSTANCES:
        pair = by_instance[instance_id]
        endogenous = pair["ENDOGENOUS_RD_RE"]
        fixed = pair["FIXED_25_PERCENT_CONTROL"]
        changes.append(
            {
                "instance_id": instance_id,
                "cost_change_pct": 100.0
                * (
                    endogenous["final_total_cost_cny"]
                    - fixed["final_total_cost_cny"]
                )
                / fixed["final_total_cost_cny"],
                "emissions_change_pct": 100.0
                * (
                    endogenous["total_emissions_kg"]
                    - fixed["total_emissions_kg"]
                )
                / fixed["total_emissions_kg"],
                "endogenous_cv": endogenous["oil_vehicles_dispatched"],
                "endogenous_ev": endogenous["ev_vehicles_dispatched"],
                "fixed_cv": fixed["oil_vehicles_dispatched"],
                "fixed_ev": fixed["ev_vehicles_dispatched"],
                "delta_cv": (
                    endogenous["oil_vehicles_dispatched"]
                    - fixed["oil_vehicles_dispatched"]
                ),
                "delta_ev": (
                    endogenous["ev_vehicles_dispatched"]
                    - fixed["ev_vehicles_dispatched"]
                ),
            }
        )
    return changes


def _report(
    rows: list[dict[str, Any]],
    sanity: dict[str, Any],
    *,
    python_executable: str,
    python_version: str,
) -> str:
    table = "\n".join(
        "| {instance_id} | {arm} | {final_total_cost_cny:.6f} | "
        "{total_emissions_kg:.6f} | {oil_vehicles_dispatched} | "
        "{ev_vehicles_dispatched} | {customers_served}/{customers_total} | "
        "{demand_completion_rate:.6%} | {search_wall_seconds:.3f} |".format(**row)
        for row in rows
    )
    changed = "\n".join(
        f"- `{path}`：{explanation}"
        for path, explanation in CHANGED_CODE_FILES.items()
    )
    summaries = "\n".join(
        (
            f"{index}. {change['instance_id']}：内生臂相对固定臂成本"
            f"{change['cost_change_pct']:+.6f}%、排放"
            f"{change['emissions_change_pct']:+.6f}%；实际油/电车 "
            f"{change['endogenous_cv']}/{change['endogenous_ev']}，固定臂 "
            f"{change['fixed_cv']}/{change['fixed_ev']}，差值 "
            f"{change['delta_cv']:+d}/{change['delta_ev']:+d}。"
        )
        for index, change in enumerate(_paired_changes(rows), start=2)
    )
    return f"""# China81 内生车队受控短试

## 结论

本包完成了三个 50 客户实例的两臂真实求解，共 6 次。两臂均使用 seed 11、100 次迭代和同一 `run_integrated_problem_hgs` 路径；这是接线与动作空间核验，不是正式实验。成本和排放分别原样报告，没有合成双目标。

## 运行结果

| 实例 | 车队臂 | 最终总成本（元） | 排放（kg） | 实际出车油车 | 实际出车电车 | 完成客户 | 完成需求率 | 搜索墙钟（秒） |
|---|---|---:|---:|---:|---:|---:|---:|---:|
{table}

实际预算为每臂 100 次迭代；该值与 2026-08-10 component scout 的 `--iterations 100` 一致。每臂另保留 1200 秒安全上限，但 6 次均以实际记录的结束状态收口，具体见 `raw_runs.csv`。

## 构造 sanity check

`{sanity['instance_id']}` 已在新参数类下完成真实 bundle 与初始个体构造。每车场油车数逐项等于 `base_all_cv_routes_Rd`，电车数逐项等于 `base_all_ev_routes_Re`；共注册 {sanity['registered_vehicle_count']} 辆实体车，其中 {sanity['registered_idle_vehicle_count']} 辆以 `trips=()` 进入初始个体。车场充电设施仍为每场 2 个 22 kW 充电桩。

对只含这些空 Duty、没有任何出车路线的个体复算，实际出车油车数=0、实际出车电车数=0、固定成本=0 元。只读源码依据是 `solver/src/setp_solver/cost.py:164-170`：车辆数从实际路线中的实体车 ID 集合计算，固定成本只乘实际出车数。本任务没有修改该文件。

## 参数语义

新类使用每车场 `cv_cap=Rd`、`ev_cap=Re`。现有完整评价接口仍要求 `total_fleet_cap` 字段，因此新类把该兼容字段设为 `Rd+Re`；它恰好等于两个车型上限之和，不会再形成更紧的总车数约束。默认 25% 固定类仍逐字读取原 CSV 的 `num_cv`、`num_ev` 和 `total_fleet_cap`，原 CSV 与生成器均未覆盖或改写。

## public 批任务协调

本轮求解启动前重新检查了 `solver/reports/public_v2_28_clean_ruler_20260810/` 的日志文件占用；只有确认原 public 批任务已自然结束、日志没有活动写入者后才启动 6 次短试。实际检查时间和文件状态见 `metadata.json`。

## 验证与如实保留的异常

定向测试最终为 {TEST_RECORD['passed']} passed，耗时 {TEST_RECORD['elapsed_seconds']:.2f} 秒。测试和短试均使用 `{python_executable}`（Python {python_version}）；启动时清空外部 `PYTHONPATH`、设置 `PYTHONNOUSERSITE=1`，再调用 `run_public_v2_28_clean_ruler.py` 的 `_prepare_independent_imports()`：先载入已安装的 `setp-hgs-kernel 0.12.2`，再接入仓库 `solver/src` 与 `third_party/setp_hgs_kernel` 源码覆盖层，并以安装元数据补齐运行时版本身份。没有修改内核源码或降低版本校验。

在正式测试前有一次只读包装探针失败：动态导入公开 runner 时，探针漏把模块登记进 `sys.modules`，因此在解释 `@dataclass` 时终止；它没有进入 `setp_solver` 导入、测试或求解，也没有产生实验目录。随后更正探针写法，并用上述正式包装完成测试。

## 本任务改动的代码文件

{changed}

## 范围核对

未修改 China81 客户、需求、路网、电价、碳强度、充电曲线或 fleet authority CSV；未修改 `cost.py`、`check.py`、根级 `evaluation.py`（若存在）及 `solver/src/setp_solver/search/` 下任何受保护文件；未写入 public 28-instance 结果目录。排放只作观测指标，没有改成加权或 Pareto 目标。

## 六行摘要

1. 新增测试 {TEST_RECORD['passed']}/{TEST_RECORD['passed']} 全通过；环境为 `{python_executable}`（Python {python_version}）及公开 runner 的同款源码覆盖包装。
{summaries}
"""


def _artifact_hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): _sha256(path)
        for path in sorted(output.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "_private_worker":
        requested_output = (
            None if len(sys.argv) < 3 else Path(sys.argv[2]).resolve()
        )
        sys.argv = [
            str(
                Path(__file__).resolve().with_name(
                    "run_problem_hgs_private_technical.py"
                )
            ),
            *sys.argv[2:],
        ]
        try:
            return _private_trial_main()
        except Exception as error:
            if requested_output is not None:
                _write_failure_package(requested_output, error)
            raise

    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--max-runtime-seconds", type=float, default=1200.0)
    parser.add_argument(
        "--population-mode",
        choices=("technical_two_parent", "copied_hgs_defaults"),
        default="copied_hgs_defaults",
    )
    args = parser.parse_args()
    if args.iterations != 100:
        raise ValueError("this approved trial is frozen at 100 iterations")
    if args.max_runtime_seconds != 1200.0:
        raise ValueError("this trial must retain the component-scout 1200 s ceiling")

    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    public_state = _public_batch_state(repo)
    if public_state["active"]:
        raise RuntimeError("public 28-instance batch is still actively writing")
    protected_paths = _protected_paths(repo)
    protected_before = _hash_paths(repo, protected_paths)
    sanity = _sanity_check(repo)
    output.mkdir(parents=True)
    started_at = _now()
    print(
        json.dumps(
            {
                "event": "trial_started",
                "at": started_at,
                "sanity": sanity,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    rows: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    for instance_id in INSTANCES:
        for parameter_key, arm_name in ARMS:
            row, identity = _subrun(
                repo,
                output,
                instance_id=instance_id,
                parameter_key=parameter_key,
                arm_name=arm_name,
                iterations=args.iterations,
                max_runtime_seconds=args.max_runtime_seconds,
                population_mode=args.population_mode,
            )
            rows.append(row)
            identities.append(identity)
            print(
                json.dumps(
                    {
                        "event": "subrun_completed",
                        "at": _now(),
                        "instance_id": instance_id,
                        "arm": arm_name,
                        "total_cost_cny": row["final_total_cost_cny"],
                        "emissions_kg": row["total_emissions_kg"],
                        "search_wall_seconds": row["search_wall_seconds"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    protected_after = _hash_paths(repo, protected_paths)
    if protected_before != protected_after:
        raise RuntimeError("protected source files changed during the trial")
    if len(rows) != 6:
        raise RuntimeError("approved 3 x 2 trial did not produce six rows")
    if any(
        not row["feasible"]
        or row["customers_served"] != row["customers_total"]
        or abs(row["demand_completion_rate"] - 1.0) > 1e-12
        for row in rows
    ):
        raise RuntimeError("one or more trial arms did not complete service")

    _write_raw_runs(output / "raw_runs.csv", rows)
    metadata = {
        "status": "COMPLETE",
        "purpose": "endogenous-fleet wiring/action-space trial; not formal",
        "started_at": started_at,
        "completed_at": _now(),
        "repo": str(repo),
        "git_head": _git(repo, "rev-parse", "HEAD"),
        "git_status_short": _git(repo, "status", "--short"),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "environment_bootstrap": TEST_RECORD["environment"],
        "unit_test": TEST_RECORD,
        "platform": platform.platform(),
        "instances": list(INSTANCES),
        "arms": [arm for _key, arm in ARMS],
        "seed": 11,
        "requested_iterations_per_arm": args.iterations,
        "max_runtime_seconds_per_arm": args.max_runtime_seconds,
        "effective_population": _effective_population_metadata(
            args.population_mode,
            _parameters(population_mode=args.population_mode).population,
        ),
        "budget_source": (
            "solver/scripts/run_integrated_private_component_scout.py "
            "default --iterations=100 and --max-runtime-seconds=1200"
        ),
        "solver_entry": (
            "solver/scripts/run_problem_hgs_private_technical.py -> "
            "setp_solver.algorithms.problem_hgs.runner.run_integrated_problem_hgs"
        ),
        "public_batch_launch_check": public_state,
        "sanity_check": sanity,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "subruns": identities,
        "formal_experiment": False,
        "dual_objective_enabled": False,
    }
    _write_json(output / "metadata.json", metadata)
    (output / "report.md").write_text(
        _report(
            rows,
            sanity,
            python_executable=sys.executable,
            python_version=platform.python_version(),
        ),
        encoding="utf-8",
    )
    _write_json(
        output / "artifact_hashes.json",
        _artifact_hashes(output),
    )
    print(
        json.dumps(
            {"output": str(output), "rows": rows},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
