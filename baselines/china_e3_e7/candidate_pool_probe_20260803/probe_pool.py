#!/usr/bin/env python3
"""SEEDPROBE3: measure candidate-pool completion without source edits."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import UTC, datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import traceback
from typing import Any, Iterable, Mapping


SCRIPT = Path(__file__).resolve()
OUTPUT = SCRIPT.parent
REPO = SCRIPT.parents[3]

TASK_ID = "SEEDPROBE3"
INSTANCE_ID = "cn-cy-100c-01-V2-LOCATIONS"
LEVEL = 25
UNITS = ((100, 1), (100, 2), (25_000, 1))
VIEWS = ("cv_only", "naive_ev", "mechanism_ev")
REPORTED_ARM = "COST_PLUS_CARBON"
MAX_WORKERS = 2

PRE_UNIT_STARTUP_EVENTS = [
    {
        "status": "EXITED_BEFORE_ANY_UNIT",
        "python_executable": "/opt/anaconda3/bin/python3.13",
        "exception": "ModuleNotFoundError: No module named 'pyvrp'",
        "units_started": 0,
    }
]

THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}
for _name, _value in THREAD_ENV.items():
    os.environ[_name] = _value

RAW_FIELDS = (
    "iterations",
    "seed",
    "view",
    "status",
    "proxy_ranked_count",
    "max_archive_candidates_effective",
    "completion_attempted",
    "completion_succeeded",
    "completion_failed",
    "completion_failure_reasons",
    "archive_completions_count",
    "elite_completions_count",
    "distinct_full_objective_among_succeeded",
    "succeeded_full_objectives_float_hex",
    "unit_failure_text",
)

DELIVERABLES_BEFORE_DONE = (
    "raw_pool.csv",
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
ROUTE_POOL_REL = PROTOTYPE_REL / "route_pool_sp.py"
EPOCHAL_REL = PROTOTYPE_REL / "epochal_hgs.py"
ADAPTER_REL = PROTOTYPE_REL / "pyvrp_adapter.py"
PROBE1_REL = Path(
    "baselines/china_e3_e7/seed_determinism_probe_20260803/probe_seed.py"
)
PROBE2_REL = Path(
    "baselines/china_e3_e7/seed_determinism_probe2_20260803/probe_proxy.py"
)

WORKER_SENTINEL = "SEEDPROBE3_RESULT_JSON="
BANNED_FINDINGS_WORDS = (
    "情形A",
    "情形B",
    "结论",
    "建议",
    "应当",
    "根因",
    "修复",
)


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
    if isinstance(value, bool):
        return str(value).lower()
    return value


def write_raw(rows: Iterable[dict[str, Any]]) -> None:
    ordered = sorted(
        rows,
        key=lambda row: (
            next(
                index
                for index, unit in enumerate(UNITS)
                if unit == (int(row["iterations"]), int(row["seed"]))
            ),
            VIEWS.index(str(row["view"])),
        ),
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=OUTPUT,
        prefix=".raw_pool.csv.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        writer.writeheader()
        for row in ordered:
            writer.writerow(
                {field: csv_value(row.get(field)) for field in RAW_FIELDS}
            )
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(OUTPUT / "raw_pool.csv")


def git_text(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.rstrip("\n")


def load_scientific_modules() -> tuple[Any, Any]:
    prototype = REPO / PROTOTYPE_REL
    for entry in (REPO, REPO / "solver/src", REPO / "models/src", prototype):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    import baselines.china_e3_e7.scout_three_mechanisms_20260803_runner as scout
    import baselines.china_e3_e7.run_formal_fleet_levels_xb_20260802 as formal

    return scout, formal


def source_line(relative: Path, number: int) -> str:
    lines = (REPO / relative).read_text(encoding="utf-8").splitlines()
    return lines[number - 1]


def source_block(relative: Path, first: int, last: int) -> str:
    lines = (REPO / relative).read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[first - 1 : last])


def numbered_source_block(relative: Path, first: int, last: int) -> str:
    lines = (REPO / relative).read_text(encoding="utf-8").splitlines()
    width = len(str(last))
    return "\n".join(
        f"{number:>{width}}  {lines[number - 1]}"
        for number in range(first, last + 1)
    )


def evidence_line(relative: Path, number: int) -> dict[str, str]:
    return {
        "location": f"{relative.as_posix()}:{number}",
        "text": source_line(relative, number),
    }


def evidence_block(relative: Path, first: int, last: int) -> dict[str, str]:
    return {
        "location": f"{relative.as_posix()}:{first}-{last}",
        "text": source_block(relative, first, last),
    }


def config_chain() -> dict[str, dict[str, Any]]:
    return {
        "Q1": {
            "evidence": [
                evidence_block(SCOUT_REL, 447, 482),
                evidence_line(FORMAL_REL, 76),
                evidence_line(FORMAL_REL, 536),
            ],
            "fact": (
                "fleet 路径的 scout 配置改写实例与迭代量，没有改写归档候选常量；"
                "_run_arm 将值为 24 的 ARCHIVE_CANDIDATES_PER_VIEW 显式传给 "
                "max_archive_candidates_per_view，没有采用 route_pool_sp 的形参默认值。"
            ),
        },
        "Q2": {
            "evidence": [
                evidence_block(ROUTE_POOL_REL, 117, 130),
                evidence_line(ROUTE_POOL_REL, 208),
            ],
            "fact": (
                "实参是整数 24，不是 Mapping；归一化进入 else 分支，为 cv_only、"
                "naive_ev、mechanism_ev 各生成 24，随后每个视角把 "
                "archive_limits[mode] 作为 max_archive_candidates 传入。"
            ),
        },
        "Q3": {
            "evidence": [
                evidence_line(FORMAL_REL, 75),
                evidence_line(FORMAL_REL, 535),
                evidence_line(ROUTE_POOL_REL, 207),
            ],
            "fact": (
                "_run_arm 显式传入值为 8 的 EXACT_ELITES_PER_VIEW；"
                "route_pool_sp 转为 int 后以 exact_elite_count=8 传入每个视角。"
            ),
        },
        "Q4": {
            "evidence": [
                evidence_line(EPOCHAL_REL, 172),
                evidence_line(EPOCHAL_REL, 177),
                evidence_block(EPOCHAL_REL, 430, 443),
                evidence_block(EPOCHAL_REL, 475, 476),
                evidence_line(EPOCHAL_REL, 715),
            ],
            "fact": (
                "函数体内该形参在候选选择上用于 _quality_diverse_native_archive 的 limit，"
                "或用于普通分支排序后的切片；本路径未启用历史种群归档，走普通分支。"
                "切片发生在补全循环前，循环只遍历切片后的 proxy_ranked，因此它限制补全尝试数；"
                "另有一处把该值写入 stats。"
            ),
        },
        "Q5": {
            "evidence": [
                evidence_block(EPOCHAL_REL, 411, 443),
                evidence_block(EPOCHAL_REL, 475, 543),
                evidence_block(EPOCHAL_REL, 544, 594),
                evidence_block(EPOCHAL_REL, 664, 667),
                evidence_block(EPOCHAL_REL, 819, 824),
                evidence_line(FORMAL_REL, 538),
                evidence_line(FORMAL_REL, 541),
            ],
            "fact": (
                "从 PyVRP 运行结果和种群组装到两个输出集合的连续主体为 "
                "epochal_hgs.py:411-825。丢弃点包括：427-429 按 native key 去重；"
                "430-443 按上限截断；499-512 在硬 home-depot 锁开启且出现跨场服务时过滤；"
                "532-543 捕获 IndexError、KeyError、TypeError、ValueError 后不加入 exact_candidates；"
                "594 对 elite_completions 按 exact_elite_count 截断。421-443 没有单独的 "
                "is_feasible() 丢弃语句；本路径 hard_home_depot_lock=False、"
                "exact_checkpoint_interval_iterations=None。archive_completions 使用完整的 "
                "exact_ranked，未在 819-821 再截断。"
            ),
        },
    }


def failure_reason_from_trace(item: Mapping[str, Any]) -> str:
    if "exception_type" in item:
        return (
            f"{item['exception_type']}: "
            f"{str(item.get('exception_message', ''))[:200]}"
        )
    return str(item.get("status", ""))


def observe_epoch(epoch: Any) -> dict[str, Any]:
    stats = epoch.stats
    trace = [
        item
        for item in stats["complete_candidate_evaluation_trace"]
        if item.get("source") == "terminal_population_archive"
    ]
    attempted = int(stats["archive_completion_attempts"])
    if len(trace) != attempted:
        raise RuntimeError(
            "terminal archive trace count differs from archive completion attempts: "
            f"trace={len(trace)} attempted={attempted}"
        )
    passed = [item for item in trace if item.get("status") == "PASS"]
    failed = [item for item in trace if item.get("status") != "PASS"]
    reasons = Counter(failure_reason_from_trace(item) for item in failed)
    objectives = [float(item["complete_objective"]).hex() for item in passed]
    return {
        "proxy_ranked_count": int(stats["archive_unique_native_candidates"]),
        "max_archive_candidates_effective": int(
            stats["archive_candidate_limit"]
        ),
        "completion_attempted": attempted,
        "completion_succeeded": len(passed),
        "completion_failed": len(failed),
        "completion_failure_reasons": dict(sorted(reasons.items())),
        "archive_completions_count": len(epoch.archive_completions),
        "elite_completions_count": len(epoch.elite_completions),
        "distinct_full_objective_among_succeeded": len(set(objectives)),
        "succeeded_full_objectives_float_hex": (
            objectives if len(passed) > 1 else []
        ),
    }


class ObservationPatch:
    """Retain per-view epoch observations and restore both symbols on exit."""

    def __init__(self, formal: Any) -> None:
        self.formal = formal
        self.route_pool = formal.route_pool_sp
        self.current_arm: str | None = None
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self._original_run_arm: Any = None
        self._original_route_pool_run: Any = None

    def __enter__(self) -> "ObservationPatch":
        observer = self
        self._original_run_arm = self.formal._run_arm
        self._original_route_pool_run = (
            self.route_pool.run_hgs_route_pool_recombination
        )
        original_run_arm = self._original_run_arm
        original_route_pool_run = self._original_route_pool_run

        def observed_run_arm(
            level: int,
            seed: int,
            arm: str,
            *,
            max_iterations: int,
            max_no_improvement: int,
        ) -> dict[str, Any]:
            previous = observer.current_arm
            observer.current_arm = str(arm)
            try:
                return original_run_arm(
                    level,
                    seed,
                    arm,
                    max_iterations=max_iterations,
                    max_no_improvement=max_no_improvement,
                )
            finally:
                observer.current_arm = previous

        def observed_route_pool_run(*args: Any, **kwargs: Any) -> Any:
            run = original_route_pool_run(*args, **kwargs)
            if observer.current_arm is None:
                raise RuntimeError("route-pool observation has no active arm")
            for view, epoch in run.view_epochs.items():
                key = (observer.current_arm, str(view))
                if key in observer.records:
                    raise RuntimeError(f"duplicate epoch observation for {key}")
                observer.records[key] = observe_epoch(epoch)
            return run

        self.formal._run_arm = observed_run_arm
        self.route_pool.run_hgs_route_pool_recombination = observed_route_pool_run
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.formal._run_arm = self._original_run_arm
        self.route_pool.run_hgs_route_pool_recombination = (
            self._original_route_pool_run
        )
        self.current_arm = None


def full_failure_text(result: Mapping[str, Any]) -> str:
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


def empty_view_row(
    iterations: int,
    seed: int,
    view: str,
    status: str,
    failure_text: str,
) -> dict[str, Any]:
    return {
        "iterations": int(iterations),
        "seed": int(seed),
        "view": view,
        "status": status,
        "proxy_ranked_count": None,
        "max_archive_candidates_effective": None,
        "completion_attempted": None,
        "completion_succeeded": None,
        "completion_failed": None,
        "completion_failure_reasons": {},
        "archive_completions_count": None,
        "elite_completions_count": None,
        "distinct_full_objective_among_succeeded": None,
        "succeeded_full_objectives_float_hex": [],
        "unit_failure_text": failure_text,
    }


def execute_worker(iterations: int, seed: int) -> int:
    try:
        scout, formal = load_scientific_modules()
        if scout.INSTANCE_ID != INSTANCE_ID:
            raise RuntimeError(
                f"unexpected scout instance before patch: {scout.INSTANCE_ID}"
            )
        scout.ITERATIONS_PER_VIEW = int(iterations)
        with ObservationPatch(formal) as observer:
            result = scout.fleet_worker((LEVEL, int(seed), {}))
        enriched = scout._enrich_fleet_row(result)
        status = str(enriched.get("status", "TECHNICAL_ERROR"))
        if status != "PASS":
            rows = [
                empty_view_row(
                    iterations,
                    seed,
                    view,
                    status,
                    full_failure_text(result),
                )
                for view in VIEWS
            ]
        else:
            rows = []
            for view in VIEWS:
                key = (REPORTED_ARM, view)
                if key not in observer.records:
                    raise RuntimeError(f"missing epoch observation for {key}")
                rows.append(
                    {
                        "iterations": int(iterations),
                        "seed": int(seed),
                        "view": view,
                        "status": "PASS",
                        **observer.records[key],
                        "unit_failure_text": "",
                    }
                )
    except BaseException:
        failure = traceback.format_exc()
        rows = [
            empty_view_row(
                iterations,
                seed,
                view,
                "TECHNICAL_ERROR",
                failure,
            )
            for view in VIEWS
        ]
    print(
        WORKER_SENTINEL
        + json.dumps(
            rows,
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
) -> list[dict[str, Any]]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(WORKER_SENTINEL):
            try:
                rows = json.loads(line[len(WORKER_SENTINEL) :])
                if len(rows) != len(VIEWS):
                    raise ValueError(f"worker returned {len(rows)} view rows")
                return rows
            except (json.JSONDecodeError, TypeError, ValueError):
                break
    failure = (
        f"worker return_code={return_code}\n"
        f"--- stdout ---\n{stdout}\n"
        f"--- stderr ---\n{stderr}"
    )
    return [
        empty_view_row(
            iterations,
            seed,
            view,
            "TECHNICAL_ERROR",
            failure,
        )
        for view in VIEWS
    ]


def run_units() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    environment = {**os.environ, **THREAD_ENV}
    batches = (((100, 1), (100, 2)), ((25_000, 1),))
    for batch in batches:
        if len(batch) > MAX_WORKERS:
            raise RuntimeError("worker concurrency exceeded two")
        running: list[tuple[tuple[int, int], subprocess.Popen[str]]] = []
        for iterations, seed in batch:
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
            running.append(((iterations, seed), process))
        for (iterations, seed), process in running:
            stdout, stderr = process.communicate()
            rows.extend(
                parse_worker_output(
                    iterations,
                    seed,
                    int(process.returncode),
                    stdout,
                    stderr,
                )
            )
        write_raw(rows)
    return rows


def row_key(row: Mapping[str, Any]) -> str:
    return f"{int(row['iterations'])}__seed{int(row['seed'])}__{row['view']}"


def unit_statuses(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[tuple[int, int], list[str]] = {}
    for row in rows:
        grouped.setdefault(
            (int(row["iterations"]), int(row["seed"])), []
        ).append(str(row["status"]))
    return {
        f"{iterations}__seed{seed}": (
            "PASS"
            if len(statuses) == len(VIEWS)
            and all(status == "PASS" for status in statuses)
            else "TECHNICAL_ERROR"
        )
        for (iterations, seed), statuses in sorted(grouped.items())
    }


def missing_quantities(rows: Iterable[dict[str, Any]]) -> list[str]:
    required = RAW_FIELDS[4:14]
    missing: list[str] = []
    for row in rows:
        if row["status"] != "PASS":
            missing.append(f"{row_key(row)}: unit_status={row['status']}")
            continue
        for field in required:
            if row.get(field) is None or row.get(field) == "":
                missing.append(f"{row_key(row)}: {field}: value_not_observed")
    return missing


def build_findings(rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_unit_view = {
        row_key(row): {
            field: row.get(field)
            for field in RAW_FIELDS
            if field not in ("iterations", "seed", "view")
        }
        for row in rows
    }
    findings = {
        "schema": "resetp.poolprobe.findings.v1",
        "task_id": TASK_ID,
        "config_chain": config_chain(),
        "per_unit_view": per_unit_view,
        "unobtainable_quantities": missing_quantities(rows),
    }
    rendered = json.dumps(findings, ensure_ascii=False, sort_keys=True)
    present = [word for word in BANNED_FINDINGS_WORDS if word in rendered]
    if present:
        raise RuntimeError(
            "findings contains prohibited wording: " + ", ".join(present)
        )
    return findings


def acquisition_methods() -> dict[str, dict[str, str]]:
    return {
        "proxy_ranked_count": {
            "method": "打补丁保留返回对象后直接读",
            "detail": "HgsExactEpoch.stats.archive_unique_native_candidates；即 unique 代理候选在上限切片前的数量",
        },
        "max_archive_candidates_effective": {
            "method": "打补丁保留返回对象后直接读",
            "detail": "HgsExactEpoch.stats.archive_candidate_limit",
        },
        "completion_attempted": {
            "method": "打补丁保留返回对象后直接读",
            "detail": "HgsExactEpoch.stats.archive_completion_attempts",
        },
        "completion_succeeded": {
            "method": "打补丁保留返回对象后直接读",
            "detail": "complete_candidate_evaluation_trace 中 source=terminal_population_archive 且 status=PASS 的条数",
        },
        "completion_failed": {
            "method": "打补丁保留返回对象后直接读",
            "detail": "同一 trace 中 source=terminal_population_archive 且 status 不是 PASS 的条数",
        },
        "completion_failure_reasons": {
            "method": "打补丁保留返回对象后直接读",
            "detail": "逐条保留 trace 的 exception_type 与 exception_message 前 200 字符并计数；无异常字段时保留原 status",
        },
        "archive_completions_count": {
            "method": "打补丁保留返回对象后直接读",
            "detail": "len(HgsExactEpoch.archive_completions)",
        },
        "elite_completions_count": {
            "method": "打补丁保留返回对象后直接读",
            "detail": "len(HgsExactEpoch.elite_completions)",
        },
        "distinct_full_objective_among_succeeded": {
            "method": "打补丁保留返回对象后直接读再计算",
            "detail": "terminal_population_archive 的 PASS 完整目标值转 float.hex 后去重计数",
        },
        "succeeded_full_objectives_float_hex": {
            "method": "打补丁保留返回对象后直接读",
            "detail": "completion_succeeded 大于 1 时按补全 trace 顺序列出全部完整目标值的 float.hex",
        },
    }


def current_reused_hashes(formal: Any) -> dict[str, str]:
    hashes = formal.source_hashes()
    for relative in (SCOUT_REL, PROBE1_REL, PROBE2_REL):
        hashes[relative.as_posix()] = sha256_path(REPO / relative)
    return dict(sorted(hashes.items()))


def build_metadata(
    rows: list[dict[str, Any]],
    started_at: str,
    completed_at: str,
    source_hashes_before: dict[str, str],
    source_hashes_after: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema": "resetp.poolprobe.metadata.v1",
        "task_id": TASK_ID,
        "instance_id": INSTANCE_ID,
        "level": LEVEL,
        "git_commit": git_text("rev-parse", "HEAD"),
        "started_at": started_at,
        "completed_at": completed_at,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "package_versions": {
            name: importlib.metadata.version(name)
            for name in ("pyvrp", "numpy", "scipy")
        },
        "runtime_pythonpath": os.environ.get("PYTHONPATH", ""),
        "platform": platform.platform(),
        "max_parallel_worker_processes": MAX_WORKERS,
        "thread_environment": dict(THREAD_ENV),
        "unit_execution_batches": [
            ["100__seed1", "100__seed2"],
            ["25000__seed1"],
        ],
        "views": list(VIEWS),
        "reported_arm": REPORTED_ARM,
        "call_path": [
            "scout_three_mechanisms_20260803_runner.fleet_worker",
            "run_formal_fleet_levels_xb_20260802.run_unit",
            "run_formal_fleet_levels_xb_20260802._run_arm",
            "route_pool_sp.run_hgs_route_pool_recombination",
            "epochal_hgs._run_exact_epoch",
        ],
        "reused_source_files_sha256": source_hashes_before,
        "reused_source_files_sha256_after": source_hashes_after,
        "reused_source_hashes_unchanged": (
            source_hashes_before == source_hashes_after
        ),
        "reused_source_tree_sha256": hashlib.sha256(
            canonical_bytes(source_hashes_before)
        ).hexdigest(),
        "observation_acquisition": acquisition_methods(),
        "patch_restoration": "ObservationPatch.__exit__",
        "pre_unit_startup_events": PRE_UNIT_STARTUP_EVENTS,
        "observed_status_by_unit": unit_statuses(rows),
        "completed_row_count": len(rows),
        "expected_row_count": 9,
    }


def markdown(value: Any) -> str:
    rendered = csv_value(value)
    if rendered == "":
        return "取不到"
    return str(rendered).replace("|", "\\|").replace("\n", "<br>")


def build_report(rows: list[dict[str, Any]]) -> str:
    ordered = sorted(
        rows,
        key=lambda row: (
            UNITS.index((int(row["iterations"]), int(row["seed"]))),
            VIEWS.index(str(row["view"])),
        ),
    )
    chain = config_chain()
    lines = [
        "# SEEDPROBE3 候选池测量记录",
        "",
        "## 测量范围",
        "",
        (
            f"固定算例 `{INSTANCE_ID}`、level={LEVEL}，运行 100×seed1、"
            "100×seed2、25000×seed1 三个单元。每个单元沿 "
            "`fleet_worker → run_unit → _run_arm → run_hgs_route_pool_recombination "
            "→ _run_exact_epoch` 路径运行；下表每行对应一个单元与一个视角。"
        ),
        "",
        "## 单元开始前的启动记录",
        "",
        (
            "首次父进程使用 `/opt/anaconda3/bin/python3.13` 启动，在任何单元开始前因 "
            "`ModuleNotFoundError: No module named 'pyvrp'` 退出；当时完成单元数为 0，"
            "没有生成 `raw_pool.csv`。随后使用系统 Python 3.13，并从仓库冻结的 "
            "`build/python_envs/pyvrp-hgs-0.12.2` 补充 PyVRP 0.12.2 包路径。"
        ),
        "",
        "## 配置链五问",
        "",
    ]
    for key in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        item = chain[key]
        lines.extend([f"### {key}", "", item["fact"], ""])
        for evidence in item["evidence"]:
            lines.extend(
                [
                    f"`{evidence['location']}`",
                    "",
                    "```python",
                    evidence["text"],
                    "```",
                    "",
                ]
            )
    lines.extend(
        [
            "### Q5 连续代码段",
            "",
            f"`{EPOCHAL_REL.as_posix()}:411-825`",
            "",
            "```text",
            numbered_source_block(EPOCHAL_REL, 411, 825),
            "```",
            "",
            "## 9 行实测数据",
            "",
            "| 迭代 | 种子 | 视角 | 状态 | 截断前候选 | 生效上限 | 发起补全 | 补全成功 | 补全失败 | 失败原文计数 | archive 数 | elite 数 | 成功目标不同值数 | 成功目标值 hex |",
            "|---:|---:|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|",
        ]
    )
    for row in ordered:
        lines.append(
            "| "
            + " | ".join(
                markdown(row.get(field))
                for field in RAW_FIELDS[:14]
            )
            + " |"
        )
    lines.extend(["", "## 各量取得方式", ""])
    for name, method in acquisition_methods().items():
        lines.append(
            f"`{name}`：{method['method']}；{method['detail']}。"
        )
        lines.append("")
    unavailable = missing_quantities(ordered)
    lines.extend(["## 取不到的量", ""])
    if unavailable:
        lines.extend(f"- `{item}`" for item in unavailable)
    else:
        lines.append("无。")
    failures = [row for row in ordered if row.get("unit_failure_text")]
    lines.extend(["", "## 单元异常原文", ""])
    if failures:
        seen: set[tuple[int, int]] = set()
        for row in failures:
            unit = (int(row["iterations"]), int(row["seed"]))
            if unit in seen:
                continue
            seen.add(unit)
            lines.extend(
                [
                    f"### {unit[0]}__seed{unit[1]}",
                    "",
                    "```text",
                    str(row["unit_failure_text"]),
                    "```",
                    "",
                ]
            )
    else:
        lines.append("无。")
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
            "refusing to overwrite existing SEEDPROBE3 artifacts: "
            + ", ".join(str(path) for path in forbidden)
        )


def inspect_payload() -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "units": [f"{iterations}__seed{seed}" for iterations, seed in UNITS],
        "views": list(VIEWS),
        "reported_arm": REPORTED_ARM,
        "max_parallel_worker_processes": MAX_WORKERS,
        "thread_environment": dict(THREAD_ENV),
        "config_chain": config_chain(),
        "output": str(OUTPUT),
    }


def run_parent() -> int:
    ensure_fresh_output()
    started_at = now_utc()
    _, formal = load_scientific_modules()
    source_hashes_before = current_reused_hashes(formal)
    rows = run_units()
    if len(rows) != 9:
        raise RuntimeError(f"unexpected row count: {len(rows)}")
    source_hashes_after = current_reused_hashes(formal)
    findings = build_findings(rows)
    completed_at = now_utc()
    metadata = build_metadata(
        rows,
        started_at,
        completed_at,
        source_hashes_before,
        source_hashes_after,
    )
    write_json(OUTPUT / "metadata.json", metadata)
    write_json(OUTPUT / "findings.json", findings)
    write_text(OUTPUT / "report.md", build_report(rows))

    hash_targets = (
        SCRIPT,
        OUTPUT / "raw_pool.csv",
        OUTPUT / "metadata.json",
        OUTPUT / "findings.json",
        OUTPUT / "report.md",
    )
    artifacts = {
        "schema": "resetp.poolprobe.artifacts.v1",
        "task_id": TASK_ID,
        "excluded_patterns": ["._*", "__pycache__", ".pytest_cache"],
        "files": {
            str(path.relative_to(OUTPUT)): sha256_path(path)
            for path in hash_targets
        },
    }
    write_json(OUTPUT / "artifact_hashes.json", artifacts)

    statuses = unit_statuses(rows)
    passed_units = [unit for unit, status in statuses.items() if status == "PASS"]
    failed_units = [unit for unit, status in statuses.items() if status != "PASS"]
    done = {
        "task_id": TASK_ID,
        "status": "COMPLETE" if not failed_units else "TECHNICAL_HALT",
        "completed_units": len(passed_units),
        "expected_units": 3,
        "halt_reason": "" if not failed_units else "; ".join(failed_units),
    }
    write_json(OUTPUT / "done.json", done)
    print(json.dumps(done, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if not failed_units else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--iterations", type=int, choices=(100, 25_000))
    parser.add_argument("--seed", type=int, choices=(1, 2))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.inspect_only:
        print(json.dumps(inspect_payload(), ensure_ascii=False, indent=2))
        return 0
    if args.worker:
        if args.iterations is None or args.seed is None:
            raise SystemExit("worker requires --iterations and --seed")
        if (args.iterations, args.seed) not in UNITS:
            raise SystemExit("worker unit is outside the registered three units")
        return execute_worker(args.iterations, args.seed)
    if args.iterations is not None or args.seed is not None:
        raise SystemExit("parent mode does not accept --iterations or --seed")
    return run_parent()


if __name__ == "__main__":
    raise SystemExit(main())
