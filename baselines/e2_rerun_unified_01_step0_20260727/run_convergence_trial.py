#!/usr/bin/env python3
"""E2-RERUN-UNIFIED-01 step-0 result-blind convergence trial.

Runs exactly 45 arm-units (nine frozen instances, seed 1, five arms) with
six concurrent, one-task-per-process spawn workers.  The script records costs
in the raw ledger but deliberately emits no inter-arm cost comparisons.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import inspect
import json
import math
import multiprocessing as mp
import os
import platform
import resource
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from statistics import median
from time import perf_counter, process_time
from typing import Any

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CAMPAIGN = REPO / "baselines/e2_final_campaign_20260720"
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
OPEN_SOURCE = (
    REPO
    / "baselines/algorithm_prototypes/china81_vs_opensource_20260727"
)
PYVRP_SITE = (
    REPO
    / "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages"
)
IMPORT_PATHS = (PYVRP_SITE, PROTOTYPE, CAMPAIGN, OPEN_SOURCE, REPO / "solver/src")
for path in IMPORT_PATHS:
    while str(path) in sys.path:
        sys.path.remove(str(path))
for path in reversed(IMPORT_PATHS):
    sys.path.insert(0, str(path))

import epochal_hgs  # noqa: E402
import route_pool_sp  # noqa: E402
import run_corrected_china81_d6 as corrected  # noqa: E402
from pyvrp.stop import NoImprovement  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)

_O_SPEC = importlib.util.spec_from_file_location(
    "_step0_open_source_adapter",
    OPEN_SOURCE / "pyvrp_adapter.py",
)
if _O_SPEC is None or _O_SPEC.loader is None:
    raise RuntimeError("cannot load isolated O adapter")
_O_ADAPTER = importlib.util.module_from_spec(_O_SPEC)
sys.modules[_O_SPEC.name] = _O_ADAPTER
_O_SPEC.loader.exec_module(_O_ADAPTER)
_project_initial_solution = _O_ADAPTER._project_initial_solution
_translate_solution = _O_ADAPTER._translate_solution
build_distance_problem = _O_ADAPTER.build_pyvrp_problem

K = 3_000
WORKERS = 6
SEED = 1
EPS = 1.0e-9
SP_SECONDS = 5.0
ARCHIVE_CANDIDATES = 24
EXACT_ELITES = 8
INSTANCES = (
    ("cn-jjj-25c-01-V2-LOCATIONS", "jjj", "small", 25),
    ("cn-jjj-100c-01-V2-LOCATIONS", "jjj", "medium", 100),
    ("cn-jjj-200c-01-V2-LOCATIONS", "jjj", "large", 200),
    ("cn-prd-25c-01-V2-LOCATIONS", "prd", "small", 25),
    ("cn-prd-100c-01-V2-LOCATIONS", "prd", "medium", 100),
    ("cn-prd-200c-01-V2-LOCATIONS", "prd", "large", 200),
    ("cn-cy-25c-01-V2-LOCATIONS", "cy", "small", 25),
    ("cn-cy-100c-01-V2-LOCATIONS", "cy", "medium", 100),
    ("cn-cy-200c-01-V2-LOCATIONS", "cy", "large", 200),
)
ARMS = ("O", "F", "E", "M", "MV")
VIEW_BY_ARM = {"F": "cv_only", "E": "naive_ev", "M": "mechanism_ev"}
REQUIRED_ENV = {
    "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)
SEALED = (
    REPO / "baselines/e2_final_campaign_20260720/corrected_china81_rerun_v4_20260724",
    REPO / "baselines/algorithm_prototypes/china81_vs_opensource_20260727",
)
RAW_FIELDS = (
    "instance_id", "region", "size_layer", "customer_count", "seed",
    "arm", "status", "stop_iterations", "last_strict_improvement_iteration",
    "l_over_s", "mv_critical_view", "view_stop_iterations_json",
    "view_last_improvements_json", "view_l_over_s_json", "trajectory_path",
    "trajectory_sha256", "final_cost", "feasible", "violation_count",
    "cpu_seconds", "wallclock_seconds", "peak_rss_mib", "pid",
    "start_method", "price_binding_json", "selected_source", "notes",
)


def canonical_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(payload))
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


class AuditedNoImprovement:
    """NoImprovement(K) plus the complete pre-iteration best trajectory."""

    def __init__(self, maximum: int):
        self.maximum = int(maximum)
        self._criterion = NoImprovement(self.maximum)
        self._best: float | None = None
        self._started = perf_counter()
        self.observations: list[dict[str, Any]] = []

    def __call__(self, best_cost: float) -> bool:
        value = float(best_cost)
        strict = self._best is None or value < self._best
        if strict:
            self._best = value
        stopped = bool(self._criterion(value))
        self.observations.append({
            "iteration": len(self.observations),
            "best_proxy_cost": value,
            "strict_improvement": strict,
            "elapsed_seconds": perf_counter() - self._started,
            "stop_triggered": stopped,
        })
        return stopped

    @property
    def stop_iterations(self) -> int:
        if not self.observations or not self.observations[-1]["stop_triggered"]:
            raise RuntimeError("NoImprovement criterion did not trigger")
        return int(self.observations[-1]["iteration"])

    @property
    def last_improvement(self) -> int:
        return max(
            int(row["iteration"])
            for row in self.observations
            if row["strict_improvement"]
        )


def _peak_rss_mib() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw / (1024.0 * 1024.0) if sys.platform == "darwin" else raw / 1024.0


def _criterion_payload(criterion: AuditedNoImprovement) -> dict[str, Any]:
    s = criterion.stop_iterations
    last_improvement = criterion.last_improvement
    return {
        "K": criterion.maximum,
        "stop_iterations": s,
        "last_strict_improvement_iteration": last_improvement,
        "l_over_s": last_improvement / s if s else 0.0,
        "observations": criterion.observations,
    }


def _exact_result(solution: Any, bundle: Any, expected: float) -> tuple[float, int]:
    annotated = annotate_cross_site_services(solution, bundle.customer_home_depot)
    objective, _breakdown, violations = exact_china81_score(annotated, bundle)
    if violations or abs(float(objective) - float(expected)) > EPS:
        raise RuntimeError(f"exact recheck failed: violations={len(violations)}")
    return float(objective), len(violations)


def _patch_epoch_stop(criteria: list[AuditedNoImprovement]) -> tuple[Any, Any]:
    old_max = epochal_hgs.MaxIterations
    old_multiple = epochal_hgs.MultipleCriteria

    def make_no_improvement(_ignored: int) -> AuditedNoImprovement:
        criterion = AuditedNoImprovement(K)
        criteria.append(criterion)
        return criterion

    epochal_hgs.MaxIterations = make_no_improvement
    epochal_hgs.MultipleCriteria = lambda items: items[0]
    return old_max, old_multiple


def _restore_epoch_stop(old: tuple[Any, Any]) -> None:
    epochal_hgs.MaxIterations, epochal_hgs.MultipleCriteria = old


def _run_o(bundle: Any, initial: Any) -> tuple[float, str, list[AuditedNoImprovement]]:
    initial_completion = complete_china81_route_skeleton(initial, bundle)
    problem = build_distance_problem(bundle, route_proxy_mode="distance_only")
    data = problem.model.data()
    projected = _project_initial_solution(initial, data, problem)
    kwargs: dict[str, Any] = {"seed": SEED, "display": False, "collect_stats": True}
    if "initial_solution" in inspect.signature(problem.model.solve).parameters:
        kwargs["initial_solution"] = projected
    criterion = AuditedNoImprovement(K)
    result = problem.model.solve(criterion, **kwargs)
    if int(result.num_iterations) != criterion.stop_iterations:
        raise RuntimeError("O iteration count disagrees with stop audit")
    searched = _translate_solution(result.best, problem)
    try:
        searched_completion = complete_china81_route_skeleton(searched, bundle)
    except (IndexError, KeyError, RuntimeError, TypeError, ValueError):
        searched_completion = None
    if searched_completion is not None and searched_completion.objective < initial_completion.objective - EPS:
        completion = searched_completion
        source = "distance_only_hgs_search"
    else:
        completion = initial_completion
        source = "common_initial_incumbent"
    objective, _ = _exact_result(completion.solution, bundle, completion.objective)
    return objective, source, [criterion]


def _run_single_view(bundle: Any, initial: Any, mode: str) -> tuple[float, str, list[AuditedNoImprovement]]:
    criteria: list[AuditedNoImprovement] = []
    old = _patch_epoch_stop(criteria)
    try:
        problem = epochal_hgs.build_pyvrp_problem(bundle, route_proxy_mode=mode)
        epoch = epochal_hgs._run_exact_epoch(
            bundle, problem, initial, seed=SEED, runtime_seconds=None,
            warm_elites=(), exact_elite_count=EXACT_ELITES,
            max_archive_candidates=ARCHIVE_CANDIDATES,
            max_hgs_iterations=K, wallclock_safety_seconds=1.0,
        )
    finally:
        _restore_epoch_stop(old)
    if len(criteria) != 1 or epoch.stats["hgs_iterations"] != criteria[0].stop_iterations:
        raise RuntimeError("single-view stop audit mismatch")
    best = min((*epoch.elite_completions, epoch.proxy_best_completion),
               key=lambda item: item.objective)
    objective, _ = _exact_result(best.solution, bundle, best.objective)
    return objective, "best_complete_single_view_candidate", criteria


def _run_mv(bundle: Any, initial: Any) -> tuple[float, str, list[AuditedNoImprovement]]:
    criteria: list[AuditedNoImprovement] = []
    old = _patch_epoch_stop(criteria)
    try:
        run = route_pool_sp.run_hgs_route_pool_recombination(
            bundle, initial, seed=SEED, hgs_seconds_per_view=None,
            exact_elites_per_view=EXACT_ELITES,
            max_archive_candidates_per_view=ARCHIVE_CANDIDATES,
            sp_time_limit_seconds=SP_SECONDS, hard_home_depot_lock=False,
            max_hgs_iterations_per_view=K,
            wallclock_safety_seconds_per_view=1.0,
        )
    finally:
        _restore_epoch_stop(old)
    modes = ("cv_only", "naive_ev", "mechanism_ev")
    if len(criteria) != 3:
        raise RuntimeError("MV did not create three independent stop criteria")
    for mode, criterion in zip(modes, criteria):
        if run.view_epochs[mode].stats["hgs_iterations"] != criterion.stop_iterations:
            raise RuntimeError(f"MV stop audit mismatch for {mode}")
    objective, _ = _exact_result(run.solution, bundle, run.completion.objective)
    return objective, str(run.stats["selected_source"]), criteria


def _run_unit(spec: tuple[str, str, str, int, str]) -> dict[str, Any]:
    instance_id, region, size_layer, customer_count, arm = spec
    if any(os.environ.get(key) != value for key, value in REQUIRED_ENV.items()):
        raise RuntimeError("required deterministic thread environment mismatch")
    if version("pyvrp") != "0.12.2":
        raise RuntimeError("PyVRP 0.12.2 is required")
    task_key = f"{instance_id}__seed{SEED}__{arm}"
    task_dir = HERE / "tasks" / task_key
    result_path = task_dir / "result.json"
    if result_path.is_file():
        return json.loads(result_path.read_text(encoding="utf-8"))
    started_wall = perf_counter()
    started_cpu = process_time()
    bundle = load_china81_bundle(REPO, instance_id)
    initial = corrected._load_initial(instance_id)
    if arm == "O":
        final_cost, selected_source, criteria = _run_o(bundle, initial)
        view_names = ("distance_only",)
    elif arm in VIEW_BY_ARM:
        final_cost, selected_source, criteria = _run_single_view(
            bundle, initial, VIEW_BY_ARM[arm]
        )
        view_names = (VIEW_BY_ARM[arm],)
    elif arm == "MV":
        final_cost, selected_source, criteria = _run_mv(bundle, initial)
        view_names = ("cv_only", "naive_ev", "mechanism_ev")
    else:
        raise ValueError(f"unknown arm {arm}")
    cpu_seconds = process_time() - started_cpu
    wallclock_seconds = perf_counter() - started_wall
    view_payloads = {
        name: _criterion_payload(criterion)
        for name, criterion in zip(view_names, criteria)
    }
    critical_view = max(view_payloads, key=lambda name: view_payloads[name]["l_over_s"])
    critical = view_payloads[critical_view]
    trajectory_rel = Path("tasks") / task_key / "trajectory.json"
    trajectory_path = HERE / trajectory_rel
    write_json(trajectory_path, {
        "schema": "resetp.e2-rerun-unified-01.step0.trajectory.v1",
        "instance_id": instance_id, "seed": SEED, "arm": arm,
        "mv_unit_rule": "maximum view L/S; S and L are from the critical view",
        "views": view_payloads,
    })
    price_binding = dict(
        sorted(dict(bundle.prices.diesel_price_by_city).items())
    )
    row = {
        "instance_id": instance_id, "region": region,
        "size_layer": size_layer, "customer_count": customer_count,
        "seed": SEED, "arm": arm, "status": "PASS",
        "stop_iterations": critical["stop_iterations"],
        "last_strict_improvement_iteration": critical["last_strict_improvement_iteration"],
        "l_over_s": critical["l_over_s"], "mv_critical_view": critical_view,
        "view_stop_iterations_json": json.dumps({k: v["stop_iterations"] for k, v in view_payloads.items()}, sort_keys=True),
        "view_last_improvements_json": json.dumps({k: v["last_strict_improvement_iteration"] for k, v in view_payloads.items()}, sort_keys=True),
        "view_l_over_s_json": json.dumps({k: v["l_over_s"] for k, v in view_payloads.items()}, sort_keys=True),
        "trajectory_path": str(trajectory_rel),
        "trajectory_sha256": sha256(trajectory_path),
        "final_cost": final_cost, "feasible": True, "violation_count": 0,
        "cpu_seconds": cpu_seconds, "wallclock_seconds": wallclock_seconds,
        "peak_rss_mib": _peak_rss_mib(), "pid": os.getpid(),
        "start_method": mp.get_start_method(),
        "price_binding_json": json.dumps(price_binding, sort_keys=True),
        "selected_source": selected_source,
        "notes": "MV uses worst-view L/S; raw cost retained but not compared in report" if arm == "MV" else "",
    }
    write_json(result_path, row)
    return row


def _ceil_thousand(value: int) -> int:
    return int(math.ceil(value / 1000.0) * 1000)


def _group_shape(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in sorted({str(row[field]) for row in rows}):
        selected = [row for row in rows if str(row[field]) == value]
        result[value] = {
            "unit_count": len(selected),
            "median_S": median(int(row["stop_iterations"]) for row in selected),
            "median_L_over_S": median(float(row["l_over_s"]) for row in selected),
            "late_fraction": sum(float(row["l_over_s"]) >= 0.5 for row in selected) / len(selected),
            "median_cpu_seconds": median(float(row["cpu_seconds"]) for row in selected),
            "median_wallclock_seconds": median(float(row["wallclock_seconds"]) for row in selected),
            "max_peak_rss_mib": max(float(row["peak_rss_mib"]) for row in selected),
        }
    for value, item in result.items():
        peers = [float(other["median_S"]) for key, other in result.items() if key != value]
        peer_median = median(peers) if peers else float(item["median_S"])
        item["peer_median_S"] = peer_median
        item["clearly_earlier_stop"] = float(item["median_S"]) < 0.5 * peer_median
    return result


def _archive_prior_halt() -> None:
    archive = HERE / "halt_history/20260727_non_sandbox_halt"
    archive.mkdir(parents=True, exist_ok=True)
    for name in ("metadata.json", "raw_runs.csv", "decision.json", "artifact_hashes.json", "report.md", "environment_probe.json"):
        source = HERE / name
        target = archive / name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)


def _finalize(rows: list[dict[str, Any]], initial_hashes: dict[str, str]) -> None:
    rows.sort(key=lambda row: (row["instance_id"], ARMS.index(row["arm"])))
    write_csv(HERE / "raw_runs.csv", rows)
    passing = sum(float(row["l_over_s"]) < 0.5 for row in rows)
    criterion_pass = passing >= math.ceil(0.95 * len(rows))
    ordered_l = sorted(int(row["last_strict_improvement_iteration"]) for row in rows)
    derived_k = K if criterion_pass else _ceil_thousand(ordered_l[math.ceil(0.95 * len(rows)) - 1] + 1)
    arm_shape = _group_shape(rows, "arm")
    size_shape = _group_shape(rows, "size_layer")
    early = [f"arm:{key}" for key, val in arm_shape.items() if val["clearly_earlier_stop"]]
    early += [f"size:{key}" for key, val in size_shape.items() if val["clearly_earlier_stop"]]
    size_required = {
        size: _ceil_thousand(max(int(row["last_strict_improvement_iteration"]) for row in rows if row["size_layer"] == size) + 1)
        for size in ("small", "medium", "large")
    }
    scaling_needed = size_required["large"] > 1.5 * max(size_required["small"], size_required["medium"])
    decision = {
        "schema": "resetp.e2-rerun-unified-01.step0.decision.v2",
        "task_id": "E2-RERUN-UNIFIED-01", "verdict": "PASS_STEP0_CONVERGENCE_TRIAL_COMPLETE",
        "prior_halts_preserved_at": "halt_history/20260727_non_sandbox_halt",
        "raw_run_count": len(rows), "step1_started": False,
        "cost_comparison_performed": False,
        "k_decision": {
            "tested_k": K, "criterion": "at least 95% of 45 arm-units have L/S < 0.5",
            "passing_units": passing, "required_units": math.ceil(0.95 * len(rows)),
            "criterion_satisfied": criterion_pass, "recommended_k": derived_k,
            "recommendation_status": "DIRECTLY_TESTED" if criterion_pass else "DERIVED_FROM_OBSERVED_TRAJECTORIES_NOT_RERUN",
            "size_specific_observed_required_k": size_required,
            "customer_count_scaling_recommended": scaling_needed,
        },
        "mv_unit_rule": "max of the three independent view L/S values; unit S and L are from that critical view",
        "convergence_shape_by_arm": arm_shape,
        "convergence_shape_by_size": size_shape,
        "early_stop_starvation_fingerprints": early,
        "protected_files_modified": [],
        "sealed_directories_modified": [],
    }
    write_json(HERE / "decision.json", decision)
    metadata = {
        "schema": "resetp.e2-rerun-unified-01.step0.metadata.v2",
        "task_id": "E2-RERUN-UNIFIED-01", "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": "result_blind_convergence_trial_and_k_recommendation_only",
        "python": sys.executable, "python_version": sys.version,
        "platform": platform.platform(), "pyvrp_version": version("pyvrp"),
        "workers": WORKERS, "start_method": "spawn", "max_tasks_per_child": 1,
        "thread_environment": {key: os.environ.get(key) for key in REQUIRED_ENV},
        "instances": [item[0] for item in INSTANCES], "seed": SEED,
        "arms": list(ARMS), "planned_and_actual_units": 45,
        "stop_rule": f"NoImprovement({K}) independently for every HGS view",
        "mv_unit_rule": decision["mv_unit_rule"], "step1_formal_units_authorized": False,
        "prior_halt_record": "halt_history/20260727_non_sandbox_halt",
        "engineering_halt_records": [
            "halt_history/20260727_engineering_import_halt",
            "halt_history/20260727_monitor_schema_halts",
            "halt_history/20260727_result_packaging_halt",
        ],
        "initial_protected_and_sealed_hashes": initial_hashes,
    }
    write_json(HERE / "metadata.json", metadata)
    arm_lines = [
        f"| {arm} | {vals['unit_count']} | {vals['median_S']:.0f} | {vals['median_L_over_S']:.3f} | {vals['median_cpu_seconds']:.2f} | {vals['median_wallclock_seconds']:.2f} | {vals['max_peak_rss_mib']:.1f} |"
        for arm, vals in arm_shape.items()
    ]
    size_lines = [
        f"| {size} | {vals['unit_count']} | {vals['median_S']:.0f} | {vals['median_L_over_S']:.3f} | {vals['median_cpu_seconds']:.2f} | {vals['median_wallclock_seconds']:.2f} | {vals['max_peak_rss_mib']:.1f} |"
        for size, vals in size_shape.items()
    ]
    if criterion_pass:
        k_text = f"K=3000 已实测满足：{passing}/45 个单元满足 L/S < 0.5，建议保留 K=3000。"
    else:
        k_text = (f"K=3000 未满足：仅 {passing}/45 个单元满足。按已观测最后改进位置推导，建议 K={derived_k}；"
                  "该值未另行重跑验证，不能写成已实测通过。")
    starvation = "未触发预登记的明显早停指纹。" if not early else "明显早停/饥饿指纹：" + "、".join(early) + "。"
    scaling = ("大规模层的观测所需 K 超过其余层 1.5 倍，建议按客户数缩放。" if scaling_needed
               else "没有观测到足以支持按客户数缩放 K 的跨规模差异。")
    report = "\n".join([
        "# E2-RERUN-UNIFIED-01 第 0 步第三、四条报告", "",
        "结论：45/45 个结果盲单元以六进程 spawn 完成；第 1 步 2025 单元未启动。报告只描述机时、收敛形状和工程可行性，不作任何臂间成本比较。", "",
        "上一轮 `HALT_NON_SANDBOX_EXECUTION_UNAVAILABLE` 的四件套、报告与环境现场完整保留在 `halt_history/20260727_non_sandbox_halt/`。本轮启动中的 adapter 导入、空 CSV 监控和价格绑定序列化异常均版本化保留在 `halt_history/`；未形成完整单元账本的轨迹不计入本次 45 单元。", "",
        "## 收敛与机时", "", "| 臂 | 单元 | 中位 S | 中位 L/S | 中位 CPU 秒 | 中位墙钟秒 | 最大峰值 RSS MiB |",
        "|---|---:|---:|---:|---:|---:|---:|", *arm_lines, "",
        "| 规模层 | 单元 | 中位 S | 中位 L/S | 中位 CPU 秒 | 中位墙钟秒 | 最大峰值 RSS MiB |",
        "|---|---:|---:|---:|---:|---:|---:|", *size_lines, "",
        "MV-HGS-SP 的 cv_only、naive_ev、mechanism_ev 均各自使用完整 NoImprovement(3000)。MV 单元以三个视角中最大的 L/S 作为保守判据，三套原始 S、L 和完整轨迹均保留。", "",
        "## K 建议", "", k_text, scaling, starvation, "",
        "## 工程边界", "",
        "每个单元在一次性独立子进程中运行，因此 CPU、墙钟和峰值 RSS 是单元级观测。原始成本只保留在 raw_runs.csv，正文未比较成本、胜负或改进幅度。受保护三文件和两个封存目录均未修改；正式第 1 步仍未授权。", "",
    ])
    (HERE / "report.md").write_text(report, encoding="utf-8")
    write_json(HERE / "done.json", {"status": "COMPLETED", "units": len(rows), "created_at_utc": datetime.now(UTC).isoformat()})


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file() and not p.name.startswith("._")):
        digest.update(str(item.relative_to(path)).encode("utf-8"))
        digest.update(sha256(item).encode("ascii"))
    return digest.hexdigest()


def _evidence_hashes() -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(HERE.rglob("*")):
        transient_part = any(
            part in {"__pycache__", ".pytest_cache"}
            or (part.startswith(".") and part.endswith(".monitor"))
            for part in path.parts
        )
        if (path.is_file() and path.name != "artifact_hashes.json"
                and not path.name.startswith("._") and not path.name.endswith(".tmp")
                and not transient_part):
            files[str(path.relative_to(REPO))] = sha256(path)
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()
    if args.workers != WORKERS:
        raise SystemExit("this contract requires exactly 6 workers")
    frozen_adapter = Path(inspect.getsourcefile(epochal_hgs.build_pyvrp_problem) or "").resolve()
    if frozen_adapter != (PROTOTYPE / "pyvrp_adapter.py").resolve():
        raise RuntimeError(f"frozen view adapter identity mismatch: {frozen_adapter}")
    if Path(inspect.getsourcefile(build_distance_problem) or "").resolve() != (OPEN_SOURCE / "pyvrp_adapter.py").resolve():
        raise RuntimeError("isolated O adapter identity mismatch")
    probe_bundle = load_china81_bundle(REPO, INSTANCES[0][0])
    canonical_bytes(
        dict(sorted(dict(probe_bundle.prices.diesel_price_by_city).items()))
    )
    _archive_prior_halt()
    initial_hashes = {str(path.relative_to(REPO)): sha256(path) for path in PROTECTED}
    initial_hashes.update({str(path.relative_to(REPO)): _tree_hash(path) for path in SEALED})
    specs = [(*instance, arm) for instance in INSTANCES for arm in ARMS]
    existing = []
    for spec in specs:
        result_path = HERE / "tasks" / f"{spec[0]}__seed{SEED}__{spec[4]}" / "result.json"
        if result_path.is_file():
            existing.append(json.loads(result_path.read_text(encoding="utf-8")))
    completed = {(row["instance_id"], row["arm"]) for row in existing}
    pending = [spec for spec in specs if (spec[0], spec[4]) not in completed]
    rows = list(existing)
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=WORKERS, mp_context=context, max_tasks_per_child=1) as pool:
        futures = {pool.submit(_run_unit, spec): spec for spec in pending}
        for future in as_completed(futures):
            rows.append(future.result())
            write_csv(HERE / "raw_runs.csv", sorted(rows, key=lambda row: (row["instance_id"], ARMS.index(row["arm"]))))
            write_json(HERE / "progress.json", {"completed": len(rows), "expected": len(specs), "updated_at_utc": datetime.now(UTC).isoformat()})
    if len(rows) != 45 or len({(row["instance_id"], row["arm"]) for row in rows}) != 45:
        raise RuntimeError("45 unique units were not completed")
    current_hashes = {str(path.relative_to(REPO)): sha256(path) for path in PROTECTED}
    current_hashes.update({str(path.relative_to(REPO)): _tree_hash(path) for path in SEALED})
    if current_hashes != initial_hashes:
        raise RuntimeError("protected file or sealed directory drift")
    _finalize(rows, initial_hashes)
    write_json(HERE / "artifact_hashes.json", {
        "schema": "resetp.e2-rerun-unified-01.step0.artifact-hashes.v2",
        "algorithm": "sha256", "self_excluded": True,
        "exclusions": ["artifact_hashes.json", "._*", "*.tmp", "__pycache__", ".pytest_cache", ".*.monitor"],
        "appledouble_files_included": False, "files": _evidence_hashes(),
        "protected_and_sealed_hashes_after": current_hashes,
    })


if __name__ == "__main__":
    main()
