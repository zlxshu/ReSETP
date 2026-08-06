#!/usr/bin/env python3
"""SEEDPROBE2: observe proxy HGS and route-pool quantities without source edits."""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import hashlib
import importlib.metadata
import json
import math
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

TASK_ID = "SEEDPROBE2"
INSTANCE_ID = "cn-cy-100c-01-V2-LOCATIONS"
LEVEL = 25
ITERATION_BUDGETS = (100, 1_000, 25_000)
SEEDS = (1, 2)
VIEWS = ("cv_only", "naive_ev", "mechanism_ev")
REPORTED_ARM = "COST_PLUS_CARBON"
MAX_WORKERS = 2
ROUND1_OBJECTIVE = 4562.024573963715

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
    "proxy_best_cost",
    "proxy_best_is_feasible",
    "proxy_initial_best_cost",
    "proxy_improvement",
    "min_pop_size",
    "warm_native_count",
    "random_count",
    "archive_candidate_count",
    "exact_elite_count",
    "sp_route_pool_size",
    "sp_improved_over_parent",
    "selected_source",
    "objective_float_hex",
    "total_cost_cny",
    "route_structure_sha256",
    "charging_structure_sha256",
    "dispatched_cv",
    "dispatched_ev",
    "route_count",
    "complete_candidate_evaluation_attempts",
    "hgs_iterations_by_view",
    "stop_reasons_by_view",
    "elapsed_seconds",
    "failure_reason",
)

DELIVERABLES_BEFORE_DONE = (
    "raw_probe2.csv",
    "metadata.json",
    "findings.json",
    "report.md",
    "artifact_hashes.json",
)

ROUND1_REL = Path(
    "baselines/china_e3_e7/seed_determinism_probe_20260803/probe_seed.py"
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
EPOCHAL_REL = PROTOTYPE_REL / "epochal_hgs.py"
ROUTE_POOL_REL = PROTOTYPE_REL / "route_pool_sp.py"

WORKER_SENTINEL = "SEEDPROBE2_RESULT_JSON="


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
            int(row["iterations"]),
            int(row["seed"]),
            VIEWS.index(str(row["view"])),
        ),
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=OUTPUT,
        prefix=".raw_probe2.csv.",
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
    temporary.replace(OUTPUT / "raw_probe2.csv")


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


def float_hex(value: float) -> str:
    value = float(value)
    if value == 0.0:
        return "0x0p+0"
    return value.hex()


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
    failure_reason: str,
) -> dict[str, Any]:
    return {
        field: (
            int(iterations)
            if field == "iterations"
            else int(seed)
            if field == "seed"
            else view
            if field == "view"
            else status
            if field == "status"
            else failure_reason
            if field == "failure_reason"
            else None
        )
        for field in RAW_FIELDS
    }


class ObservationPatch:
    """Observe one worker process and restore every patched symbol on exit."""

    def __init__(self, formal: Any) -> None:
        self.formal = formal
        self.epochal = formal.epochal_hgs
        self.route_pool = formal.route_pool_sp
        self.current_arm: str | None = None
        self.current_view: str | None = None
        self.ga_observations: dict[tuple[str, str], dict[str, Any]] = {}
        self.epoch_observations: dict[tuple[str, str], dict[str, Any]] = {}
        self.route_pool_observations: dict[str, dict[str, Any]] = {}
        self.unobtainable: list[str] = []
        self._original_run_arm: Any = None
        self._original_ga: Any = None
        self._original_exact_epoch: Any = None
        self._original_route_pool_run: Any = None

    def _key(self) -> tuple[str, str]:
        if self.current_arm is None or self.current_view is None:
            raise RuntimeError("observation context has no active arm/view")
        return self.current_arm, self.current_view

    def __enter__(self) -> "ObservationPatch":
        observer = self
        self._original_run_arm = self.formal._run_arm
        self._original_ga = self.epochal.GeneticAlgorithm
        self._original_exact_epoch = self.route_pool._run_exact_epoch
        self._original_route_pool_run = (
            self.route_pool.run_hgs_route_pool_recombination
        )
        original_ga = self._original_ga
        original_run_arm = self._original_run_arm
        original_exact_epoch = self._original_exact_epoch
        original_route_pool_run = self._original_route_pool_run

        from pyvrp._pyvrp import CostEvaluator

        def proxy_objective(solution: Any) -> float:
            if not bool(solution.is_feasible()):
                return math.inf
            evaluator = CostEvaluator(
                [0] * len(solution.excess_load()),
                0,
                0,
            )
            return float(evaluator.cost(solution))

        class ObservedGeneticAlgorithm(original_ga):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                initial_solutions = (
                    args[6]
                    if len(args) >= 7
                    else kwargs["initial_solutions"]
                )
                population = (
                    args[3]
                    if len(args) >= 4
                    else kwargs["population"]
                )
                initial_tuple = tuple(initial_solutions)
                super().__init__(*args, **kwargs)
                key = observer._key()
                if key in observer.ga_observations:
                    raise RuntimeError(f"duplicate GA observation for {key}")
                initial_cost = min(
                    (proxy_objective(item) for item in initial_tuple),
                    default=math.inf,
                )
                observer.ga_observations[key] = {
                    "proxy_initial_best_cost_value": float(initial_cost),
                    "initial_solution_count": len(initial_tuple),
                    "min_pop_size": int(population._params.min_pop_size),
                }

            def run(self, *args: Any, **kwargs: Any) -> Any:
                result = super().run(*args, **kwargs)
                key = observer._key()
                record = observer.ga_observations[key]
                record.update(
                    {
                        "proxy_best_cost_value": float(result.cost()),
                        "proxy_best_is_feasible": bool(
                            result.best.is_feasible()
                        ),
                    }
                )
                return result

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

        def observed_exact_epoch(
            bundle: Any,
            problem: Any,
            common_initial_solution: Any,
            **kwargs: Any,
        ) -> Any:
            previous = observer.current_view
            observer.current_view = str(problem.route_proxy_mode)
            key = observer._key()
            try:
                epoch = original_exact_epoch(
                    bundle,
                    problem,
                    common_initial_solution,
                    **kwargs,
                )
                archive = (
                    epoch.archive_completions
                    if epoch.archive_completions
                    else epoch.elite_completions
                )
                observer.epoch_observations[key] = {
                    "warm_native_count": int(
                        epoch.stats["warm_elite_count"]
                    ),
                    "archive_candidate_count": len(archive),
                    "exact_elite_count": len(epoch.elite_completions),
                }
                return epoch
            finally:
                observer.current_view = previous

        def observed_route_pool_run(*args: Any, **kwargs: Any) -> Any:
            run = original_route_pool_run(*args, **kwargs)
            if observer.current_arm is None:
                raise RuntimeError("route-pool observation has no active arm")
            observer.route_pool_observations[observer.current_arm] = {
                "sp_route_pool_size": int(run.stats["route_pool_size"]),
                "sp_improved_over_parent": bool(
                    run.stats["strict_recombination_improvement"]
                ),
                "selected_source": str(run.stats["selected_source"]),
            }
            return run

        self.formal._run_arm = observed_run_arm
        self.epochal.GeneticAlgorithm = ObservedGeneticAlgorithm
        self.route_pool._run_exact_epoch = observed_exact_epoch
        self.route_pool.run_hgs_route_pool_recombination = (
            observed_route_pool_run
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.formal._run_arm = self._original_run_arm
        self.epochal.GeneticAlgorithm = self._original_ga
        self.route_pool._run_exact_epoch = self._original_exact_epoch
        self.route_pool.run_hgs_route_pool_recombination = (
            self._original_route_pool_run
        )
        self.current_arm = None
        self.current_view = None

    def view_observation(self, arm: str, view: str) -> dict[str, Any]:
        key = (arm, view)
        ga = dict(self.ga_observations.get(key, {}))
        epoch = dict(self.epoch_observations.get(key, {}))
        route_pool = dict(self.route_pool_observations.get(arm, {}))
        merged = {**ga, **epoch, **route_pool}
        warm_count = merged.get("warm_native_count")
        initial_count = merged.get("initial_solution_count")
        if warm_count is not None and initial_count is not None:
            merged["random_count"] = int(initial_count) - int(warm_count)
        initial_cost = merged.get("proxy_initial_best_cost_value")
        best_cost = merged.get("proxy_best_cost_value")
        if initial_cost is not None:
            merged["proxy_initial_best_cost"] = float_hex(initial_cost)
        if best_cost is not None:
            merged["proxy_best_cost"] = float_hex(best_cost)
        if (
            initial_cost is not None
            and best_cost is not None
            and math.isfinite(float(initial_cost))
            and math.isfinite(float(best_cost))
        ):
            merged["proxy_improvement"] = float_hex(
                float(initial_cost) - float(best_cost)
            )
        return merged


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
            for row in rows:
                row["elapsed_seconds"] = enriched.get("elapsed_seconds")
        else:
            aware = result["payload"]["arms"][REPORTED_ARM]
            objective = float(aware["objective"])
            common = {
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
                "route_count": int(aware["route_count"]),
                "complete_candidate_evaluation_attempts": int(
                    aware["search_stats"][
                        "complete_candidate_evaluation_attempts"
                    ]
                ),
                "hgs_iterations_by_view": {
                    key: int(value)
                    for key, value in aware[
                        "hgs_iterations_by_view"
                    ].items()
                },
                "stop_reasons_by_view": dict(
                    aware["stop_reasons_by_view"]
                ),
                "elapsed_seconds": float(enriched["elapsed_seconds"]),
                "failure_reason": "",
            }
            rows = []
            for view in VIEWS:
                observed = observer.view_observation(REPORTED_ARM, view)
                row = {
                    "iterations": int(iterations),
                    "seed": int(seed),
                    "view": view,
                    **common,
                    **{
                        field: observed.get(field)
                        for field in (
                            "proxy_best_cost",
                            "proxy_best_is_feasible",
                            "proxy_initial_best_cost",
                            "proxy_improvement",
                            "min_pop_size",
                            "warm_native_count",
                            "random_count",
                            "archive_candidate_count",
                            "exact_elite_count",
                            "sp_route_pool_size",
                            "sp_improved_over_parent",
                            "selected_source",
                        )
                    },
                }
                rows.append(row)
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
                    raise ValueError(
                        f"worker returned {len(rows)} view rows"
                    )
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


def index_rows(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row_key(row): row for row in rows}


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
    required = (
        "proxy_best_cost",
        "proxy_best_is_feasible",
        "proxy_initial_best_cost",
        "proxy_improvement",
        "min_pop_size",
        "warm_native_count",
        "random_count",
        "archive_candidate_count",
        "exact_elite_count",
        "sp_route_pool_size",
        "sp_improved_over_parent",
        "selected_source",
    )
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
    indexed = index_rows(rows)
    expected_keys = [
        f"{iterations}__seed{seed}__{view}"
        for iterations in ITERATION_BUDGETS
        for seed in SEEDS
        for view in VIEWS
    ]
    proxy_best = {
        key: indexed[key].get("proxy_best_cost") or ""
        for key in expected_keys
    }
    improvement = {
        key: indexed[key].get("proxy_improvement") or ""
        for key in expected_keys
    }
    identical_seeds: dict[str, bool] = {}
    for iterations in ITERATION_BUDGETS:
        for view in VIEWS:
            values = [
                indexed[f"{iterations}__seed{seed}__{view}"].get(
                    "proxy_best_cost"
                )
                for seed in SEEDS
            ]
            identical_seeds[f"{iterations}__{view}"] = bool(
                all(values) and len(set(values)) == 1
            )
    identical_iterations: dict[str, bool] = {}
    for seed in SEEDS:
        for view in VIEWS:
            values = [
                indexed[f"{iterations}__seed{seed}__{view}"].get(
                    "proxy_best_cost"
                )
                for iterations in ITERATION_BUDGETS
            ]
            identical_iterations[f"seed{seed}__{view}"] = bool(
                all(values) and len(set(values)) == 1
            )
    population = {
        key: {
            "min_pop_size": indexed[key].get("min_pop_size"),
            "warm_native_count": indexed[key].get("warm_native_count"),
            "random_count": indexed[key].get("random_count"),
        }
        for key in expected_keys
    }
    sp = {
        key: {
            "sp_route_pool_size": indexed[key].get("sp_route_pool_size"),
            "sp_improved_over_parent": indexed[key].get(
                "sp_improved_over_parent"
            ),
            "selected_source": indexed[key].get("selected_source") or "",
        }
        for key in expected_keys
    }
    unit_objectives = {
        (
            int(row["iterations"]),
            int(row["seed"]),
        ): row.get("objective_float_hex")
        for row in rows
        if row["view"] == VIEWS[0]
    }
    all_unit_objectives = list(unit_objectives.values())
    full_identical = bool(
        len(all_unit_objectives) == 6
        and all(all_unit_objectives)
        and len(set(all_unit_objectives)) == 1
    )
    round1_hex = float(ROUND1_OBJECTIVE).hex()
    reproduces_round1 = all(
        unit_objectives.get((25_000, seed)) == round1_hex
        for seed in SEEDS
    )
    return {
        "schema": "resetp.seedprobe2.findings.v1",
        "task_id": TASK_ID,
        "proxy_best_cost_by_unit_view": proxy_best,
        "proxy_identical_across_seeds_by_iters_view": identical_seeds,
        "proxy_identical_across_iters_by_seed_view": identical_iterations,
        "proxy_improvement_by_unit_view": improvement,
        "population_composition_by_unit_view": population,
        "sp_by_unit_view": sp,
        "full_model_identical_across_all_six_units": full_identical,
        "reproduces_round1_4562_024573963715": reproduces_round1,
        "unobtainable_quantities": missing_quantities(rows),
    }


def acquisition_methods() -> dict[str, dict[str, str]]:
    return {
        "proxy_best_cost": {
            "method": "打补丁取",
            "detail": "GeneticAlgorithm.run 返回后直接调用 Result.cost() 并转 float.hex",
        },
        "proxy_best_is_feasible": {
            "method": "打补丁取",
            "detail": "GeneticAlgorithm.run 返回后直接调用 result.best.is_feasible()",
        },
        "proxy_initial_best_cost": {
            "method": "打补丁取",
            "detail": "GeneticAlgorithm 构造时对 initial_solutions 中可行解按零罚 CostEvaluator 取最小值",
        },
        "proxy_improvement": {
            "method": "打补丁取值后计算",
            "detail": "proxy_initial_best_cost 减 proxy_best_cost，零值写为 0x0p+0",
        },
        "min_pop_size": {
            "method": "打补丁取",
            "detail": "GeneticAlgorithm 构造时读取 Population._params.min_pop_size",
        },
        "warm_native_count": {
            "method": "直接读",
            "detail": "HgsExactEpoch.stats.warm_elite_count",
        },
        "random_count": {
            "method": "打补丁取值后计算",
            "detail": "GeneticAlgorithm 实收 initial_solutions 数减直接读取的 warm_elite_count",
        },
        "archive_candidate_count": {
            "method": "直接读",
            "detail": "实际传入 _route_pool_records 的 HgsExactEpoch.archive_completions 长度",
        },
        "exact_elite_count": {
            "method": "直接读",
            "detail": "HgsExactEpoch.elite_completions 长度",
        },
        "sp_route_pool_size": {
            "method": "直接读",
            "detail": "HgsRoutePoolRun.stats.route_pool_size；同一单元三视角共用一次集合划分",
        },
        "sp_improved_over_parent": {
            "method": "直接读",
            "detail": "HgsRoutePoolRun.stats.strict_recombination_improvement",
        },
        "selected_source": {
            "method": "直接读",
            "detail": "HgsRoutePoolRun.stats.selected_source",
        },
        "round1_quantities": {
            "method": "直接读",
            "detail": "COST_PLUS_CARBON arm 返回对象和 scout._enrich_fleet_row",
        },
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
    source_hashes_after: dict[str, str],
    git_status_before: str,
    git_status_after: str,
    scout: Any,
    formal: Any,
) -> dict[str, Any]:
    return {
        "schema": "resetp.seedprobe2.metadata.v1",
        "task_id": TASK_ID,
        "instance_id": INSTANCE_ID,
        "level": LEVEL,
        "git_commit": git_text("rev-parse", "HEAD"),
        "git_status_porcelain_before": git_status_before.splitlines(),
        "git_status_porcelain_after": git_status_after.splitlines(),
        "started_at": started_at,
        "completed_at": completed_at,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "pyvrp_version": importlib.metadata.version("pyvrp"),
        "platform": platform.platform(),
        "max_parallel_processes": MAX_WORKERS,
        "unit_execution_order": [
            f"{iterations}__seed{seed}"
            for iterations in ITERATION_BUDGETS
            for seed in SEEDS
        ],
        "reported_data_scope": REPORTED_ARM,
        "reused_source_files_sha256": source_hashes,
        "reused_source_files_sha256_after": source_hashes_after,
        "reused_source_hashes_unchanged": source_hashes == source_hashes_after,
        "reused_source_tree_sha256": hashlib.sha256(
            canonical_bytes(source_hashes)
        ).hexdigest(),
        "observation_acquisition": acquisition_methods(),
        "units": [
            unit_config(iterations, seed, scout, formal)
            for iterations in ITERATION_BUDGETS
            for seed in SEEDS
        ],
        "observed_status_by_unit": unit_statuses(rows),
        "completed_row_count": len(rows),
        "expected_row_count": 18,
    }


def markdown(value: Any) -> str:
    rendered = csv_value(value)
    if rendered == "":
        return "取不到"
    return str(rendered).replace("|", "\\|").replace("\n", "<br>")


def build_report(rows: list[dict[str, Any]]) -> str:
    rows = sorted(
        rows,
        key=lambda row: (
            int(row["iterations"]),
            int(row["seed"]),
            VIEWS.index(str(row["view"])),
        ),
    )
    lines = [
        "# SEEDPROBE2 诊断记录",
        "",
        "## 运行内容",
        "",
        (
            f"固定算例 `{INSTANCE_ID}`、电动车占比档位 {LEVEL}，迭代预算为 "
            "100、1000、25000，种子为 1、2，共执行 6 个单元。每个单元沿第一轮"
            "同一 `fleet_worker → run_unit → _run_arm → MV-HGS-SP` 路径运行；"
            "下表每行是一个单元与一个视角的组合，共 18 行。完整模型字段读取 "
            "`COST_PLUS_CARBON` arm。"
        ),
        "",
        "## 取得方式",
        "",
        (
            "`proxy_best_cost` 与 `proxy_best_is_feasible` 在 PyVRP "
            "`GeneticAlgorithm.run()` 返回后，从 `Result.cost()` 和 "
            "`result.best.is_feasible()` 打补丁取得。"
        ),
        "",
        (
            "`proxy_initial_best_cost` 在 `GeneticAlgorithm` 构造时、迭代开始前，"
            "对实际 `initial_solutions` 中可行解用零罚 `CostEvaluator` 取最小值；"
            "`proxy_improvement` 是该值减最终代理值。"
        ),
        "",
        (
            "`min_pop_size` 从实际 `Population._params` 打补丁读取；"
            "`warm_native_count` 直接读 `HgsExactEpoch.stats.warm_elite_count`；"
            "`random_count` 用构造器实际收到的初始解数减热启动数。"
        ),
        "",
        (
            "`archive_candidate_count` 直接取该视角实际送入 `_route_pool_records` "
            "的 `archive_completions` 数；该集合含归档完成解和共同初始完成解。"
            "`exact_elite_count` 直接取 `elite_completions` 数。"
        ),
        "",
        (
            "`sp_route_pool_size`、`sp_improved_over_parent`、`selected_source` "
            "直接读 `HgsRoutePoolRun.stats`。集合划分由三个视角共同生成，"
            "所以同一单元的三行重复记录同一组集合划分字段。"
        ),
        "",
        (
            "完整模型目标值、成本、结构哈希、派车数、路线数、完整候选评价次数、"
            "迭代数、停止原因和用时均直接读第一轮相同返回对象。所有补丁在 worker "
            "上下文退出时还原。"
        ),
        "",
        "## 代理值与种群构成",
        "",
        "| 迭代 | 种子 | 视角 | 状态 | 初始代理值 | 最终代理值 | 可行 | 改进值 | min_pop | warm | random |",
        "|---:|---:|---|---|---|---|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                markdown(row.get(field))
                for field in (
                    "iterations",
                    "seed",
                    "view",
                    "status",
                    "proxy_initial_best_cost",
                    "proxy_best_cost",
                    "proxy_best_is_feasible",
                    "proxy_improvement",
                    "min_pop_size",
                    "warm_native_count",
                    "random_count",
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 路线池与集合划分",
            "",
            "| 迭代 | 种子 | 视角 | 归档候选数 | 精英数 | SP 路线数 | 严格优于父解 | 入选来源 |",
            "|---:|---:|---|---:|---:|---:|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                markdown(row.get(field))
                for field in (
                    "iterations",
                    "seed",
                    "view",
                    "archive_candidate_count",
                    "exact_elite_count",
                    "sp_route_pool_size",
                    "sp_improved_over_parent",
                    "selected_source",
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 完整模型交叉记录",
            "",
            "| 迭代 | 种子 | 视角 | 目标值 hex | 总成本 | 路线 SHA-256 | 充电 SHA-256 | CV | EV | 路线数 | 完整评价次数 | 三视角迭代数 | 三视角停止原因 | 用时秒 |",
            "|---:|---:|---|---|---:|---|---|---:|---:|---:|---:|---|---|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                markdown(row.get(field))
                for field in (
                    "iterations",
                    "seed",
                    "view",
                    "objective_float_hex",
                    "total_cost_cny",
                    "route_structure_sha256",
                    "charging_structure_sha256",
                    "dispatched_cv",
                    "dispatched_ev",
                    "route_count",
                    "complete_candidate_evaluation_attempts",
                    "hgs_iterations_by_view",
                    "stop_reasons_by_view",
                    "elapsed_seconds",
                )
            )
            + " |"
        )
    unavailable = missing_quantities(rows)
    lines.extend(["", "## 取不到的量", ""])
    if unavailable:
        lines.extend(f"- `{item}`" for item in unavailable)
    else:
        lines.append("无。")
    failures = [row for row in rows if row.get("failure_reason")]
    lines.extend(["", "## 异常文本", ""])
    if failures:
        for row in failures:
            lines.extend(
                [
                    f"### {row_key(row)}",
                    "",
                    "```text",
                    str(row["failure_reason"]),
                    "```",
                    "",
                ]
            )
    else:
        lines.append("无。")
    return "\n".join(lines).rstrip() + "\n"


def current_source_hashes(formal: Any) -> dict[str, str]:
    hashes = formal.source_hashes()
    for relative in (SCOUT_REL, ROUND1_REL):
        hashes[relative.as_posix()] = sha256_path(REPO / relative)
    return dict(sorted(hashes.items()))


def ensure_fresh_output() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    forbidden = [
        OUTPUT / name
        for name in (*DELIVERABLES_BEFORE_DONE, "done.json")
        if (OUTPUT / name).exists()
    ]
    if forbidden:
        raise FileExistsError(
            "refusing to overwrite existing SEEDPROBE2 artifacts: "
            + ", ".join(str(path) for path in forbidden)
        )


def inspect_payload() -> dict[str, Any]:
    return {
        "direct_from_HgsExactEpoch": [
            "warm_native_count",
            "archive_candidate_count",
            "exact_elite_count",
        ],
        "direct_from_HgsRoutePoolRun_stats": [
            "sp_route_pool_size",
            "sp_improved_over_parent",
            "selected_source",
        ],
        "monkeypatch_GeneticAlgorithm": [
            "proxy_best_cost",
            "proxy_best_is_feasible",
            "proxy_initial_best_cost",
            "min_pop_size",
            "random_count",
        ],
        "patch_restoration": "ObservationPatch.__exit__",
    }


def run_parent() -> int:
    ensure_fresh_output()
    started_at = now_utc()
    scout, formal = load_scientific_modules()
    source_hashes = current_source_hashes(formal)
    git_status_before = git_text("status", "--porcelain=v1")
    rows = run_units()
    if len(rows) != 18:
        raise RuntimeError(f"unexpected row count: {len(rows)}")
    source_hashes_after = current_source_hashes(formal)
    git_status_after = git_text("status", "--porcelain=v1")
    findings = build_findings(rows)
    completed_at = now_utc()
    metadata = build_metadata(
        rows,
        started_at,
        completed_at,
        source_hashes,
        source_hashes_after,
        git_status_before,
        git_status_after,
        scout,
        formal,
    )
    write_json(OUTPUT / "metadata.json", metadata)
    write_json(OUTPUT / "findings.json", findings)
    write_text(OUTPUT / "report.md", build_report(rows))

    hash_targets = (
        SCRIPT,
        OUTPUT / "raw_probe2.csv",
        OUTPUT / "metadata.json",
        OUTPUT / "findings.json",
        OUTPUT / "report.md",
    )
    artifact_hashes = {
        "schema": "resetp.seedprobe2.artifacts.v1",
        "task_id": TASK_ID,
        "excluded_patterns": ["._*", "__pycache__", ".pytest_cache"],
        "files": {
            str(path.relative_to(OUTPUT)): sha256_path(path)
            for path in hash_targets
        },
    }
    write_json(OUTPUT / "artifact_hashes.json", artifact_hashes)

    statuses = unit_statuses(rows)
    failed_units = [
        unit for unit, status in statuses.items() if status != "PASS"
    ]
    status = "COMPLETE" if not failed_units else "TECHNICAL_HALT"
    halt_reason = (
        "" if not failed_units else "; ".join(failed_units)
    )
    done = {
        "task_id": TASK_ID,
        "status": status,
        "completed_units": len(statuses),
        "expected_units": 6,
        "halt_reason": halt_reason,
    }
    write_json(OUTPUT / "done.json", done)
    print(json.dumps(done, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if status == "COMPLETE" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--iterations", type=int, choices=ITERATION_BUDGETS)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.inspect_only:
        if args.worker or args.iterations is not None or args.seed is not None:
            raise ValueError("--inspect-only cannot be combined")
        load_scientific_modules()
        print(
            json.dumps(
                inspect_payload(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.worker:
        if args.iterations is None or args.seed is None:
            raise ValueError("worker requires --iterations and --seed")
        return execute_worker(args.iterations, args.seed)
    if args.iterations is not None or args.seed is not None:
        raise ValueError("--iterations and --seed are worker-only arguments")
    return run_parent()


if __name__ == "__main__":
    raise SystemExit(main())
