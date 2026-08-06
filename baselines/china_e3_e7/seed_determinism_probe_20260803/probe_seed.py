#!/usr/bin/env python3
"""SEEDPROBE: measure seed sensitivity on the SCOUT3 fleet code path."""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import traceback
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
OUTPUT = SCRIPT.parent
REPO = SCRIPT.parents[3]

TASK_ID = "SEEDPROBE"
INSTANCE_ID = "cn-cy-100c-01-V2-LOCATIONS"
LEVEL = 25
ITERATION_BUDGETS = (100, 1_000, 25_000)
SEEDS = (1, 2)
MAX_WORKERS = 2
ORIGINAL_OBJECTIVE = 4562.024573963715

THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
for _name, _value in THREAD_ENV.items():
    os.environ[_name] = _value

RAW_FIELDS = (
    "iterations",
    "seed",
    "status",
    "objective_float_hex",
    "total_cost_cny",
    "route_structure_sha256",
    "charging_structure_sha256",
    "dispatched_cv",
    "dispatched_ev",
    "used_physical_vehicles",
    "route_count",
    "complete_candidate_evaluation_attempts",
    "hgs_iterations_by_view",
    "stop_reasons_by_view",
    "elapsed_seconds",
    "failure_reason",
)

DELIVERABLES_BEFORE_DONE = (
    "raw_probe.csv",
    "metadata.json",
    "findings.json",
    "report.md",
    "artifact_hashes.json",
)

SCOUT_REL = Path(
    "baselines/china_e3_e7/scout_three_mechanisms_20260803_runner.py"
)
FORMAL_REL = Path(
    "baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py"
)
PROTOTYPE_REL = Path(
    "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
PYVRP_REL = PROTOTYPE_REL / "pyvrp_adapter.py"
ROUTE_POOL_REL = PROTOTYPE_REL / "route_pool_sp.py"
EPOCHAL_REL = PROTOTYPE_REL / "epochal_hgs.py"
HYBRID_REL = PROTOTYPE_REL / "hybrid.py"

WORKER_SENTINEL = "SEEDPROBE_RESULT_JSON="


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def write_json(path: Path, payload: Any) -> None:
    atomic_write_bytes(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n",
    )


def write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if value is None:
        return ""
    return value


def write_raw(rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=OUTPUT,
        prefix=".raw_probe.csv.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {field: csv_value(row.get(field)) for field in RAW_FIELDS}
            )
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(OUTPUT / "raw_probe.csv")


def git_text(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def load_scientific_modules() -> tuple[Any, Any]:
    prototype = REPO / PROTOTYPE_REL
    for entry in (REPO, REPO / "solver/src", REPO / "models/src", prototype):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    import baselines.china_e3_e7.scout_three_mechanisms_20260803_runner as scout
    import baselines.china_e3_e7.run_formal_fleet_levels_xb_20260802 as formal

    return scout, formal


def full_failure_text(result: dict[str, Any]) -> str:
    row = result.get("row", {})
    payload = result.get("payload", {})
    parts: list[str] = []
    if row.get("failure_reason"):
        parts.append(str(row["failure_reason"]))
    for arm, item in payload.get("arm_failures", {}).items():
        block = [f"[{arm}] {item.get('failure_reason', '')}"]
        if item.get("traceback"):
            block.append(str(item["traceback"]))
        parts.append("\n".join(block))
    if payload.get("traceback"):
        parts.append(str(payload["traceback"]))
    return "\n\n".join(part for part in parts if part).strip()


def empty_unit_row(
    iterations: int,
    seed: int,
    status: str,
    failure_reason: str,
) -> dict[str, Any]:
    return {
        "iterations": int(iterations),
        "seed": int(seed),
        "status": status,
        "objective_float_hex": "",
        "total_cost_cny": "",
        "route_structure_sha256": "",
        "charging_structure_sha256": "",
        "dispatched_cv": None,
        "dispatched_ev": None,
        "used_physical_vehicles": None,
        "route_count": None,
        "complete_candidate_evaluation_attempts": None,
        "hgs_iterations_by_view": None,
        "stop_reasons_by_view": None,
        "elapsed_seconds": None,
        "failure_reason": failure_reason,
    }


def execute_worker(iterations: int, seed: int) -> int:
    try:
        scout, _ = load_scientific_modules()
        if scout.INSTANCE_ID != INSTANCE_ID:
            raise RuntimeError(
                f"unexpected scout instance before patch: {scout.INSTANCE_ID}"
            )
        scout.ITERATIONS_PER_VIEW = int(iterations)
        result = scout.fleet_worker((LEVEL, int(seed), {}))
        enriched = scout._enrich_fleet_row(result)
        status = str(enriched.get("status", "TECHNICAL_ERROR"))
        if status != "PASS":
            unit = empty_unit_row(
                iterations,
                seed,
                status,
                full_failure_text(result),
            )
            unit["elapsed_seconds"] = enriched.get("elapsed_seconds")
        else:
            aware = result["payload"]["arms"]["COST_PLUS_CARBON"]
            objective = float(aware["objective"])
            unit = {
                "iterations": int(iterations),
                "seed": int(seed),
                "status": status,
                "objective_float_hex": objective.hex(),
                "total_cost_cny": repr(
                    float(aware["breakdown"]["total_cost"])
                ),
                "route_structure_sha256": enriched[
                    "aware_route_structure_sha256"
                ],
                "charging_structure_sha256": enriched[
                    "aware_charging_structure_sha256"
                ],
                "dispatched_cv": int(aware["used_cv"]),
                "dispatched_ev": int(aware["used_ev"]),
                "used_physical_vehicles": int(aware["used_total"]),
                "route_count": int(aware["route_count"]),
                "complete_candidate_evaluation_attempts": int(
                    aware["search_stats"][
                        "complete_candidate_evaluation_attempts"
                    ]
                ),
                "hgs_iterations_by_view": {
                    key: int(value)
                    for key, value in aware["hgs_iterations_by_view"].items()
                },
                "stop_reasons_by_view": dict(
                    aware["stop_reasons_by_view"]
                ),
                "elapsed_seconds": float(enriched["elapsed_seconds"]),
                "failure_reason": "",
            }
    except BaseException:
        unit = empty_unit_row(
            iterations,
            seed,
            "TECHNICAL_ERROR",
            traceback.format_exc(),
        )
    print(
        WORKER_SENTINEL
        + json.dumps(
            unit,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        flush=True,
    )
    return 0


def parse_worker_output(
    iterations: int,
    seed: int,
    return_code: int,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(WORKER_SENTINEL):
            try:
                return json.loads(line[len(WORKER_SENTINEL) :])
            except json.JSONDecodeError:
                break
    failure = (
        f"worker return_code={return_code}\n"
        f"--- stdout ---\n{stdout}\n"
        f"--- stderr ---\n{stderr}"
    )
    return empty_unit_row(
        iterations,
        seed,
        "TECHNICAL_ERROR",
        failure,
    )


def run_units() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    environment = {**os.environ, **THREAD_ENV}
    for iterations in ITERATION_BUDGETS:
        running: list[tuple[int, subprocess.Popen[str]]] = []
        for seed in SEEDS:
            command = [
                sys.executable,
                str(SCRIPT),
                "--worker",
                "--iterations",
                str(iterations),
                "--seed",
                str(seed),
            ]
            process = subprocess.Popen(
                command,
                cwd=REPO,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            running.append((seed, process))
        if len(running) > MAX_WORKERS:
            raise RuntimeError("worker concurrency exceeded two")
        for seed, process in running:
            stdout, stderr = process.communicate()
            rows.append(
                parse_worker_output(
                    iterations,
                    seed,
                    int(process.returncode),
                    stdout,
                    stderr,
                )
            )
        rows.sort(key=lambda row: (int(row["iterations"]), int(row["seed"])))
        write_raw(rows)
    return rows


def source_line(relative: Path, number: int) -> dict[str, Any]:
    path = REPO / relative
    lines = path.read_text(encoding="utf-8").splitlines()
    if number < 1 or number > len(lines):
        raise IndexError(f"line {number} outside {relative}")
    return {
        "location": f"{relative.as_posix()}:{number}",
        "text": lines[number - 1],
    }


def evidence(relative: Path, *numbers: int) -> list[dict[str, Any]]:
    return [source_line(relative, number) for number in numbers]


def static_forensics() -> dict[str, Any]:
    return {
        "Q1": {
            "fact": (
                "rng 先进入 LocalSearch，同时用于生成随机初始解；随后作为 "
                "GeneticAlgorithm 的构造参数保存，并由 algorithm.run 进入 PyVRP HGS。"
            ),
            "evidence": evidence(
                PYVRP_REL,
                553,
                555,
                565,
                573,
                576,
                583,
                584,
            ),
        },
        "Q2": {
            "fact": (
                "run_unit 对两个搜索侧分别把 seed 传给 _run_arm；_run_arm 再传给 "
                "run_hgs_route_pool_recombination，该函数对三个视角逐一传给 "
                "_run_exact_epoch。"
            ),
            "evidence": [
                *evidence(FORMAL_REL, 801, 803, 805, 530, 533),
                *evidence(ROUTE_POOL_REL, 190, 196, 200),
            ],
        },
        "Q3": {
            "fact": (
                "流程先取得 HGS 完整候选中的最低目标值父解，再运行集合划分生成重组候选；"
                "返回项由 HGS 父解与可用重组候选按完整目标值取最小。集合划分调用和最终 "
                "min 选择均未接收随机数或 seed。"
            ),
            "evidence": evidence(
                ROUTE_POOL_REL,
                225,
                227,
                255,
                279,
                282,
                290,
                305,
                307,
                690,
                698,
            ),
        },
        "Q4": {
            "fact": (
                "本次 scout 车队路径没有调用 hybrid.py 的 homogeneous ensemble；它调用 "
                "run_unit 后进入 route_pool_sp，并在三个视角上使用同一个外部 seed。"
                "hybrid.py 该独立函数若被调用，会先选多个群体中完整目标值最低者，"
                "以它启动 ALNS，再在该群体解和 ALNS 解之间取完整目标值最低者。"
            ),
            "evidence": [
                *evidence(SCOUT_REL, 491, 492, 493),
                *evidence(FORMAL_REL, 530, 533),
                *evidence(ROUTE_POOL_REL, 190, 196, 200),
                *evidence(HYBRID_REL, 346, 347, 363, 364, 368, 375, 376),
            ],
        },
    }


def index_rows(rows: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    return {
        (int(row["iterations"]), int(row["seed"])): row
        for row in rows
    }


def comparison(rows: list[dict[str, Any]], iterations: int) -> dict[str, Any]:
    indexed = index_rows(rows)
    first = indexed[(iterations, 1)]
    second = indexed[(iterations, 2)]
    first_hex = first.get("objective_float_hex") or None
    second_hex = second.get("objective_float_hex") or None
    return {
        "seed1_hex": first_hex,
        "seed2_hex": second_hex,
        "identical": bool(first_hex and second_hex and first_hex == second_hex),
    }


def build_findings(
    rows: list[dict[str, Any]],
    forensics: dict[str, Any],
) -> dict[str, Any]:
    indexed = index_rows(rows)
    comparisons = {
        iterations: comparison(rows, iterations)
        for iterations in ITERATION_BUDGETS
    }
    original_hex = float(ORIGINAL_OBJECTIVE).hex()
    comparisons[25_000][
        "reproduces_original_4562_024573963715"
    ] = all(
        indexed[(25_000, seed)].get("objective_float_hex") == original_hex
        for seed in SEEDS
    )
    technical_failures = [
        {
            "unit": f"{row['iterations']}__seed{row['seed']}",
            "status": row["status"],
            "failure_reason": row.get("failure_reason", ""),
        }
        for row in rows
        if row["status"] != "PASS"
    ]
    attempts = {
        f"{iterations}__seed{seed}": indexed[(iterations, seed)].get(
            "complete_candidate_evaluation_attempts"
        )
        for iterations in ITERATION_BUDGETS
        for seed in SEEDS
    }
    return {
        "schema": "resetp.seedprobe.findings.v1",
        "task_id": TASK_ID,
        "iterations_100": comparisons[100],
        "iterations_1000": comparisons[1_000],
        "iterations_25000": comparisons[25_000],
        "evaluation_attempts_by_unit": attempts,
        "technical_failures": technical_failures,
        "static_forensics": forensics,
    }


def unit_config(iterations: int, seed: int, scout: Any, formal: Any) -> dict[str, Any]:
    return {
        "instance_id": INSTANCE_ID,
        "level": LEVEL,
        "iterations_per_view": int(iterations),
        "seed": int(seed),
        "views": list(formal.HGS_VIEWS),
        "search_arms": list(formal.ARM_ORDER),
        "reported_arm": formal.CARBON_AWARE,
        "no_improvement_stop": None,
        "max_no_improvement_argument_ignored_by_iteration_only_patch": int(
            iterations
        ),
        "exact_elites_per_view": int(scout.EXACT_ELITES_PER_VIEW),
        "max_archive_candidates_per_view": int(scout.ARCHIVE_PER_VIEW),
        "sp_time_limit_seconds": float(scout.SP_SECONDS),
        "wallclock_safety_seconds_per_view": float(
            scout.WALLCLOCK_SAFETY_SECONDS_PER_VIEW
        ),
        "hard_home_depot_lock": False,
        "exact_checkpoint_interval_iterations": None,
        "preserve_base_pool_recombination": False,
        "strict_multitrip": bool(scout.MODEL_CONFIG.strict_multitrip),
        "depot_charger_capacity_mode": str(
            scout.MODEL_CONFIG.depot_charger_capacity_mode
        ),
        "thread_environment": dict(THREAD_ENV),
        "call_path": [
            "scout_three_mechanisms_20260803_runner.fleet_worker",
            "run_formal_fleet_levels_xb_20260802.run_unit",
            "run_formal_fleet_levels_xb_20260802._run_arm",
            "route_pool_sp.run_hgs_route_pool_recombination",
        ],
    }


def build_metadata(
    rows: list[dict[str, Any]],
    started_at: str,
    completed_at: str,
    source_hashes: dict[str, str],
    scout: Any,
    formal: Any,
) -> dict[str, Any]:
    return {
        "schema": "resetp.seedprobe.metadata.v1",
        "task_id": TASK_ID,
        "instance_id": INSTANCE_ID,
        "level": LEVEL,
        "git_commit": git_text("rev-parse", "HEAD"),
        "started_at": started_at,
        "completed_at": completed_at,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "max_parallel_processes": MAX_WORKERS,
        "unit_execution_order": [
            f"{iterations}__seed{seed}"
            for iterations in ITERATION_BUDGETS
            for seed in SEEDS
        ],
        "reported_data_scope": "COST_PLUS_CARBON arm",
        "reused_source_files_sha256": source_hashes,
        "reused_source_tree_sha256": hashlib.sha256(
            canonical_bytes(source_hashes)
        ).hexdigest(),
        "units": [
            unit_config(iterations, seed, scout, formal)
            for iterations in ITERATION_BUDGETS
            for seed in SEEDS
        ],
        "observed_status_by_unit": {
            f"{row['iterations']}__seed{row['seed']}": row["status"]
            for row in rows
        },
    }


def format_evidence(items: list[dict[str, Any]]) -> list[str]:
    rendered: list[str] = []
    for item in items:
        rendered.extend(
            [
                f"`{item['location']}`",
                "",
                "```python",
                item["text"],
                "```",
                "",
            ]
        )
    return rendered


def build_report(
    rows: list[dict[str, Any]],
    forensics: dict[str, Any],
) -> str:
    lines = [
        "# SEEDPROBE 诊断记录",
        "",
        "## 运行内容",
        "",
        (
            f"固定算例 `{INSTANCE_ID}`、电动车占比档位 {LEVEL}，分别使用 "
            "100、1000、25000 次迭代和种子 1、2，共运行 6 个单元。每个单元沿 "
            "`_configure_fleet()` 与 `fleet_worker()` 的现有调用路径执行；下列目标值、"
            "路线、充电、车辆和完整候选评价次数均取 `COST_PLUS_CARBON` 搜索侧。"
        ),
        "",
        "## 单元记录",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"### {row['iterations']} 次，seed {row['seed']}",
                "",
                (
                    f"status=`{row['status']}`；objective_float_hex="
                    f"`{row.get('objective_float_hex') or ''}`；total_cost_cny="
                    f"`{row.get('total_cost_cny') or ''}`；route_structure_sha256="
                    f"`{row.get('route_structure_sha256') or ''}`；"
                    "charging_structure_sha256="
                    f"`{row.get('charging_structure_sha256') or ''}`。"
                ),
                "",
                (
                    f"dispatched_cv={csv_value(row.get('dispatched_cv'))}；"
                    f"dispatched_ev={csv_value(row.get('dispatched_ev'))}；"
                    "used_physical_vehicles="
                    f"{csv_value(row.get('used_physical_vehicles'))}；"
                    f"route_count={csv_value(row.get('route_count'))}；"
                    "complete_candidate_evaluation_attempts="
                    f"{csv_value(row.get('complete_candidate_evaluation_attempts'))}；"
                    f"hgs_iterations_by_view=`{csv_value(row.get('hgs_iterations_by_view'))}`；"
                    f"stop_reasons_by_view=`{csv_value(row.get('stop_reasons_by_view'))}`；"
                    f"elapsed_seconds={csv_value(row.get('elapsed_seconds'))}。"
                ),
                "",
                f"failure_reason：{row.get('failure_reason') or '空'}",
                "",
            ]
        )
    indexed = index_rows(rows)
    lines.extend(["## 逐预算目标值比对", ""])
    for iterations in ITERATION_BUDGETS:
        first_hex = indexed[(iterations, 1)].get("objective_float_hex") or ""
        second_hex = indexed[(iterations, 2)].get("objective_float_hex") or ""
        identical = bool(first_hex and second_hex and first_hex == second_hex)
        lines.extend(
            [
                (
                    f"{iterations} 次：seed 1=`{first_hex}`；seed 2=`{second_hex}`；"
                    f"identical=`{str(identical).lower()}`。"
                ),
                "",
            ]
        )
    reproduction = all(
        indexed[(25_000, seed)].get("objective_float_hex")
        == float(ORIGINAL_OBJECTIVE).hex()
        for seed in SEEDS
    )
    lines.extend(
        [
            (
                "25000 次两个单元逐位复现 4562.024573963715："
                f"`{str(reproduction).lower()}`。"
            ),
            "",
        ]
    )
    lines.extend(["## 静态取证", ""])
    for question in ("Q1", "Q2", "Q3", "Q4"):
        item = forensics[question]
        lines.extend(
            [
                f"### {question}",
                "",
                f"事实：{item['fact']}",
                "",
                *format_evidence(item["evidence"]),
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def ensure_fresh_output() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    forbidden = [
        OUTPUT / name
        for name in (*DELIVERABLES_BEFORE_DONE, "done.json")
        if (OUTPUT / name).exists()
    ]
    if forbidden:
        raise FileExistsError(
            "refusing to overwrite existing SEEDPROBE artifacts: "
            + ", ".join(str(path) for path in forbidden)
        )


def run_parent() -> int:
    ensure_fresh_output()
    started_at = now_utc()
    scout, formal = load_scientific_modules()
    source_hashes = formal.source_hashes()
    source_hashes[SCOUT_REL.as_posix()] = sha256_path(REPO / SCOUT_REL)
    rows = run_units()
    if len(rows) != len(ITERATION_BUDGETS) * len(SEEDS):
        raise RuntimeError(f"unexpected unit count: {len(rows)}")
    forensics = static_forensics()
    findings = build_findings(rows, forensics)
    completed_at = now_utc()
    metadata = build_metadata(
        rows,
        started_at,
        completed_at,
        source_hashes,
        scout,
        formal,
    )
    write_json(OUTPUT / "metadata.json", metadata)
    write_json(OUTPUT / "findings.json", findings)
    write_text(OUTPUT / "report.md", build_report(rows, forensics))

    hash_targets = (
        SCRIPT,
        OUTPUT / "raw_probe.csv",
        OUTPUT / "metadata.json",
        OUTPUT / "findings.json",
        OUTPUT / "report.md",
    )
    artifact_hashes = {
        "schema": "resetp.seedprobe.artifacts.v1",
        "task_id": TASK_ID,
        "files": {
            str(path.relative_to(OUTPUT)): sha256_path(path)
            for path in hash_targets
        },
    }
    write_json(OUTPUT / "artifact_hashes.json", artifact_hashes)

    failures = [row for row in rows if row["status"] != "PASS"]
    status = "COMPLETE" if not failures else "TECHNICAL_HALT"
    halt_reason = "" if not failures else "; ".join(
        f"{row['iterations']}__seed{row['seed']}: {row['status']}"
        for row in failures
    )
    done = {
        "task_id": TASK_ID,
        "status": status,
        "completed_units": len(rows),
        "expected_units": len(ITERATION_BUDGETS) * len(SEEDS),
        "halt_reason": halt_reason,
    }
    write_json(OUTPUT / "done.json", done)
    print(json.dumps(done, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if status == "COMPLETE" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--iterations", type=int, choices=ITERATION_BUDGETS)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        if args.iterations is None or args.seed is None:
            raise ValueError("worker requires --iterations and --seed")
        return execute_worker(args.iterations, args.seed)
    if args.iterations is not None or args.seed is not None:
        raise ValueError("--iterations and --seed are worker-only arguments")
    return run_parent()


if __name__ == "__main__":
    raise SystemExit(main())
