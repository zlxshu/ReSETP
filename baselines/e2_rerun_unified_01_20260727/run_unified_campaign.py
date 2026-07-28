#!/usr/bin/env python3
"""Same-batch China81 five-arm convergence campaign with starvation reruns."""

from __future__ import annotations

import argparse
import csv
import gzip
import importlib.util
import inspect
import json
import math
import multiprocessing as mp
import os
import platform
import re
import signal
import subprocess
import sys
import threading
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from statistics import mean, median
from time import perf_counter, process_time
from typing import Any

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PREFLIGHT = HERE / "vehicle_feasibility_preflight"
CAMPAIGN = REPO / "baselines/e2_final_campaign_20260720"
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
OPEN_SOURCE = REPO / "baselines/algorithm_prototypes/china81_vs_opensource_20260727"
PYVRP_SITE = REPO / "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages"
INSTANCE_ROOT = (
    REPO
    / "data/ChinaInstances/china81_local_directed_matrices_corrected_v10_20260723/instances"
)
for path in reversed(
    (PYVRP_SITE, PREFLIGHT, PROTOTYPE, CAMPAIGN, OPEN_SOURCE, REPO / "solver/src")
):
    while str(path) in sys.path:
        sys.path.remove(str(path))
    sys.path.insert(0, str(path))

import run_preflight as common  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402

_O_SPEC = importlib.util.spec_from_file_location(
    "_unified_open_source_adapter", OPEN_SOURCE / "pyvrp_adapter.py"
)
if _O_SPEC is None or _O_SPEC.loader is None:
    raise RuntimeError("cannot load isolated O adapter")
_O_ADAPTER = importlib.util.module_from_spec(_O_SPEC)
sys.modules[_O_SPEC.name] = _O_ADAPTER
_O_SPEC.loader.exec_module(_O_ADAPTER)

WORKERS = 4
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("O", "F", "E", "M", "MV")
VIEW_BY_ARM = {"F": "cv_only", "E": "naive_ev", "M": "mechanism_ev"}
BASE_K = 3_000
MAX_K_DOUBLINGS = 2
STARVATION_THRESHOLD = 0.5
STARVATION_FRACTION = 0.20
OUTER_ROUND_LIMIT = 3
OUTER_NO_IMPROVEMENT_PATIENCE = 2
SP_SECONDS = 5.0
EXACT_ELITES = 8
ARCHIVE_CANDIDATES = 24
EPS = 1.0e-9
ISOLATION_POLL_SECONDS = 5
CONTAMINATED_ARCHIVE = "contaminated_partial_run_oversubscribed"
REQUIRED_ENV = common.REQUIRED_ENV
PROTECTED = common.PROTECTED
CONTRACT_FILES = common.CONTRACT_FILES
RAW_FIELDS = (
    "instance_id", "region", "size_layer", "customer_count", "seed", "arm",
    "attempt", "k", "selected_final_attempt", "status", "final_cost",
    "feasible", "violation_count", "independent_violation_count",
    "route_count", "ev_route_count", "ev_customer_share",
    "charging_action_count", "stop_iterations", "last_strict_improvement_iteration",
    "l_over_s", "view_round_count", "view_stop_iterations_json",
    "view_last_improvements_json", "view_l_over_s_json", "outer_rounds",
    "outer_stop_reason", "route_pool_size", "selected_source",
    "trajectory_path", "trajectory_sha256", "witness_path", "witness_sha256",
    "cpu_seconds", "wallclock_seconds", "peak_rss_mib", "pid", "start_method",
    "price_binding_json", "error_type", "error_message",
)


def _external_experiment_python_processes() -> list[dict[str, Any]]:
    """Return ReSETP experiment Python processes outside this campaign group."""
    own_pgid = os.getpgrp()
    completed = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,pgid=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    findings: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        fields = line.strip().split(maxsplit=3)
        if len(fields) != 4:
            continue
        pid_text, ppid_text, pgid_text, command = fields
        executable = Path(command.split(maxsplit=1)[0]).name.lower()
        if int(pgid_text) == own_pgid or not executable.startswith("python"):
            continue
        resetp_experiment = (
            re.match(
                r"^\S*python\S*\s+(?:\S*/)?run_[^/ ]+\.py(?:\s|$)",
                command,
            )
            is not None
            or (
                re.match(r"^\S*python\S*\s+-c(?:\s|$)", command) is not None
                and (
                    "multiprocessing.spawn" in command
                    or "multiprocessing.resource_tracker" in command
                )
            )
        )
        if resetp_experiment:
            findings.append(
                {
                    "pid": int(pid_text),
                    "ppid": int(ppid_text),
                    "pgid": int(pgid_text),
                    "command": command,
                }
            )
    return findings


def _start_isolation_guard() -> None:
    """Pause the campaign if another experiment Python pool appears."""
    def watch() -> None:
        while True:
            try:
                findings = _external_experiment_python_processes()
                if findings:
                    common._write_json(
                        HERE / "isolation_guard_anomaly.json",
                        {
                            "status": "PAUSED_EXTERNAL_EXPERIMENT_POOL_DETECTED",
                            "detected_at_utc": datetime.now(UTC).isoformat(),
                            "campaign_pgid": os.getpgrp(),
                            "external_processes": findings,
                        },
                    )
                    os.killpg(os.getpgrp(), signal.SIGSTOP)
                    return
            except Exception as exc:
                common._write_json(
                    HERE / "isolation_guard_error.json",
                    {
                        "status": "PAUSED_ISOLATION_GUARD_ERROR",
                        "detected_at_utc": datetime.now(UTC).isoformat(),
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                os.killpg(os.getpgrp(), signal.SIGSTOP)
                return
            threading.Event().wait(ISOLATION_POLL_SECONDS)

    threading.Thread(
        target=watch,
        name="e2-experiment-isolation-guard",
        daemon=True,
    ).start()


def _instance_specs() -> tuple[tuple[str, str, str, int], ...]:
    values: list[tuple[str, str, str, int]] = []
    for path in sorted(INSTANCE_ROOT.iterdir()):
        if not path.is_dir():
            continue
        match = re.search(r"^cn-(jjj|prd|cy)-(\d+)c-", path.name)
        if not match:
            continue
        count = int(match.group(2))
        layer = "small" if count <= 25 else ("medium" if count <= 100 else "large")
        values.append((path.name, match.group(1), layer, count))
    if len(values) != 81:
        raise RuntimeError(f"expected 81 China81 instances, found {len(values)}")
    return tuple(values)


def _write_gzip_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(temporary, "wb", compresslevel=6) as handle:
        handle.write(common._canonical(payload))
    temporary.replace(path)


def _criterion_payload(criterion: common.AuditedNoImprovement) -> dict[str, Any]:
    return {
        "K": criterion.maximum,
        "stop_iterations": criterion.stop_iterations,
        "last_strict_improvement_iteration": criterion.last_improvement,
        "l_over_s": criterion.last_improvement / criterion.stop_iterations,
        "observations": criterion._observations,
    }


def _independent_verify(solution: Any, bundle: Any, expected: float) -> tuple[float, list[Any]]:
    annotated = annotate_cross_site_services(solution, bundle.customer_home_depot)
    objective, _breakdown, violations = exact_china81_score(annotated, bundle)
    independent_violations = check_solution(annotated, bundle.instance, bundle.prices)
    independent_breakdown = evaluate(
        annotated, bundle.instance, bundle.time_profile, bundle.prices
    )
    independent_objective = float(independent_breakdown["total_cost"])
    if violations != independent_violations:
        raise RuntimeError("exact and independent violation ledgers disagree")
    if not math.isclose(objective, independent_objective, rel_tol=0.0, abs_tol=EPS):
        raise RuntimeError("exact and independent objectives disagree")
    if not math.isclose(objective, expected, rel_tol=0.0, abs_tol=EPS):
        raise RuntimeError("reported completion objective does not close")
    return objective, violations


def _run_o(bundle: Any, initial: Any, seed: int, k: int) -> tuple[Any, str, list[dict[str, Any]], dict[str, Any]]:
    initial_completion = complete_china81_route_skeleton(initial, bundle)
    problem = _O_ADAPTER.build_pyvrp_problem(bundle, route_proxy_mode="distance_only")
    data = problem.model.data()
    projected = _O_ADAPTER._project_initial_solution(initial, data, problem)
    kwargs: dict[str, Any] = {"seed": seed, "display": False, "collect_stats": True}
    if "initial_solution" in inspect.signature(problem.model.solve).parameters:
        kwargs["initial_solution"] = projected
    criterion = common.AuditedNoImprovement(k)
    result = problem.model.solve(criterion, **kwargs)
    searched = _O_ADAPTER._translate_solution(result.best, problem)
    try:
        searched_completion = complete_china81_route_skeleton(searched, bundle)
    except (IndexError, KeyError, RuntimeError, TypeError, ValueError):
        searched_completion = None
    if (
        searched_completion is not None
        and searched_completion.objective < initial_completion.objective - EPS
    ):
        completion = searched_completion
        source = "distance_only_hgs_search"
    else:
        completion = initial_completion
        source = "common_initial_incumbent"
    payload = _criterion_payload(criterion)
    return completion, source, [{"round": 1, "view": "distance_only", **payload}], {
        "outer_rounds": 1,
        "outer_stop_reason": "single_view_converged",
        "route_pool_size": 0,
    }


def _run_single_view(
    bundle: Any, initial: Any, seed: int, mode: str, k: int
) -> tuple[Any, str, list[dict[str, Any]], dict[str, Any]]:
    common.K = k
    criteria: list[common.AuditedNoImprovement] = []
    old = common._patch_stop(criteria)
    try:
        problem = common.epochal_hgs.build_pyvrp_problem(bundle, route_proxy_mode=mode)
        epoch = common.epochal_hgs._run_exact_epoch(
            bundle,
            problem,
            initial,
            seed=seed,
            runtime_seconds=None,
            warm_elites=(),
            exact_elite_count=EXACT_ELITES,
            max_archive_candidates=ARCHIVE_CANDIDATES,
            max_hgs_iterations=k,
            wallclock_safety_seconds=1.0,
        )
    finally:
        common._restore_stop(old)
    if len(criteria) != 1:
        raise RuntimeError("single view did not create one stop criterion")
    completion = min(
        (*epoch.elite_completions, epoch.proxy_best_completion),
        key=lambda item: item.objective,
    )
    payload = _criterion_payload(criteria[0])
    return completion, "best_complete_single_view_candidate", [
        {"round": 1, "view": mode, **payload}
    ], {
        "outer_rounds": 1,
        "outer_stop_reason": "single_view_converged",
        "route_pool_size": 0,
    }


def _record_key(record: Any) -> tuple[Any, ...]:
    return (
        record.route.vehicle_type.lower(),
        record.route.home_depot_id,
        record.customers,
        tuple(
            (
                action.station_id,
                round(float(action.energy_kwh), 9),
                round(float(action.charge_start_second), 9),
                action.charging_curve_id,
            )
            for action in record.actions
        ),
    )


def _run_mv(
    bundle: Any, initial: Any, seed: int, k: int
) -> tuple[Any, str, list[dict[str, Any]], dict[str, Any]]:
    incumbent = complete_china81_route_skeleton(initial, bundle)
    records_by_key: dict[tuple[Any, ...], Any] = {}
    traces: list[dict[str, Any]] = []
    no_improvement = 0
    selected_source = "common_initial_incumbent"
    stop_reason = "outer_round_limit"
    modes = ("cv_only", "naive_ev", "mechanism_ev")
    executed_rounds = 0
    for round_index in range(1, OUTER_ROUND_LIMIT + 1):
        executed_rounds = round_index
        common.K = k
        criteria: list[common.AuditedNoImprovement] = []
        old = common._patch_stop(criteria)
        view_epochs: dict[str, Any] = {}
        try:
            for view_index, mode in enumerate(modes):
                problem = common.epochal_hgs.build_pyvrp_problem(
                    bundle, route_proxy_mode=mode
                )
                view_epochs[mode] = common.epochal_hgs._run_exact_epoch(
                    bundle,
                    problem,
                    incumbent.solution,
                    seed=seed + 10_009 * (round_index - 1) + 1_009 * view_index,
                    runtime_seconds=None,
                    warm_elites=(),
                    exact_elite_count=EXACT_ELITES,
                    max_archive_candidates=ARCHIVE_CANDIDATES,
                    max_hgs_iterations=k,
                    wallclock_safety_seconds=1.0,
                )
        finally:
            common._restore_stop(old)
        if len(criteria) != 3:
            raise RuntimeError("MV round did not create three independent criteria")
        for mode, criterion in zip(modes, criteria):
            traces.append(
                {"round": round_index, "view": mode, **_criterion_payload(criterion)}
            )
        new_records = common.route_pool_sp._route_pool_records(bundle, view_epochs)
        for record in new_records:
            key = _record_key(record)
            old_record = records_by_key.get(key)
            if old_record is None or record.route_cost < old_record.route_cost:
                records_by_key[key] = record
        parent_candidates = [
            completion
            for epoch in view_epochs.values()
            for completion in (*epoch.elite_completions, epoch.proxy_best_completion)
        ]
        candidates: list[tuple[str, Any]] = [
            ("outer_incumbent", incumbent),
            ("best_exact_hgs_parent", min(parent_candidates, key=lambda item: item.objective)),
        ]
        mip_solution, mip_stats = common.route_pool_sp._solve_set_partitioning(
            bundle,
            tuple(records_by_key.values()),
            time_limit_seconds=SP_SECONDS,
            hard_home_depot_lock=False,
        )
        if mip_solution is not None:
            candidates.append(
                (
                    "cumulative_time_limited_mip_route_pool",
                    common.route_pool_sp._accepted_mip_completion(
                        mip_solution, bundle, mip_stats
                    ),
                )
            )
        source, best = min(candidates, key=lambda item: item[1].objective)
        strict = best.objective < incumbent.objective - EPS
        if strict:
            incumbent = best
            selected_source = source
            no_improvement = 0
        else:
            no_improvement += 1
        if no_improvement >= OUTER_NO_IMPROVEMENT_PATIENCE:
            stop_reason = "consecutive_outer_rounds_without_strict_improvement"
            break
    return incumbent, selected_source, traces, {
        "outer_rounds": executed_rounds,
        "outer_stop_reason": stop_reason,
        "route_pool_size": len(records_by_key),
    }


def _row_template(spec: tuple[str, str, str, int, int, str, int, int]) -> dict[str, Any]:
    instance_id, region, layer, count, seed, arm, attempt, k = spec
    row = {field: "" for field in RAW_FIELDS}
    row.update(
        {
            "instance_id": instance_id,
            "region": region,
            "size_layer": layer,
            "customer_count": count,
            "seed": seed,
            "arm": arm,
            "attempt": attempt,
            "k": k,
            "selected_final_attempt": False,
        }
    )
    return row


def _run_unit(spec: tuple[str, str, str, int, int, str, int, int]) -> dict[str, Any]:
    row = _row_template(spec)
    instance_id, _region, _layer, _count, seed, arm, attempt, k = spec
    task_key = f"{instance_id}__seed{seed}__{arm}__attempt{attempt}__k{k}"
    task_dir = HERE / "tasks" / task_key
    result_path = task_dir / "result.json"
    if result_path.is_file():
        return json.loads(result_path.read_text(encoding="utf-8"))
    started_wall = perf_counter()
    started_cpu = process_time()
    try:
        if any(os.environ.get(key) != value for key, value in REQUIRED_ENV.items()):
            raise RuntimeError("deterministic thread environment mismatch")
        if version("pyvrp") != "0.12.2":
            raise RuntimeError("PyVRP 0.12.2 is required")
        bundle = load_china81_bundle(REPO, instance_id)
        initial = common.corrected._load_initial(instance_id)
        if arm == "O":
            completion, source, traces, extra = _run_o(bundle, initial, seed, k)
        elif arm in VIEW_BY_ARM:
            completion, source, traces, extra = _run_single_view(
                bundle, initial, seed, VIEW_BY_ARM[arm], k
            )
        elif arm == "MV":
            completion, source, traces, extra = _run_mv(bundle, initial, seed, k)
        else:
            raise ValueError(f"unknown arm {arm}")
        objective, violations = _independent_verify(
            completion.solution, bundle, completion.objective
        )
        solution = annotate_cross_site_services(
            completion.solution, bundle.customer_home_depot
        )
        customers = {
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type == "c"
        }
        served = {
            node_id
            for route in solution.routes
            for node_id in route.node_sequence[1:-1]
            if node_id in customers
        }
        ev_served = {
            node_id
            for route in solution.routes
            if route.vehicle_type.lower() == "ev"
            for node_id in route.node_sequence[1:-1]
            if node_id in customers
        }
        trajectory_path = task_dir / "best_so_far_trajectory.json.gz"
        _write_gzip_json(
            trajectory_path,
            {
                "schema": "resetp.e2-rerun-unified-01.trajectory.v1",
                "instance_id": instance_id,
                "seed": seed,
                "arm": arm,
                "attempt": attempt,
                "k": k,
                "views_and_rounds": traces,
            },
        )
        witness_path = task_dir / "solution_witness.json"
        common._write_json(
            witness_path,
            {
                "schema": "resetp.e2-rerun-unified-01.witness.v1",
                "instance_id": instance_id,
                "seed": seed,
                "arm": arm,
                "attempt": attempt,
                "k": k,
                "solution": common.corrected._solution_payload(solution),
                "objective": objective,
                "violations": [vars(item) for item in violations],
            },
        )
        stop_iterations = [int(item["stop_iterations"]) for item in traces]
        last_improvements = [
            int(item["last_strict_improvement_iteration"]) for item in traces
        ]
        l_over_s = [float(item["l_over_s"]) for item in traces]
        critical = max(range(len(traces)), key=lambda index: l_over_s[index])
        row.update(
            {
                "status": "PASS" if not violations else "INFEASIBLE",
                "final_cost": objective,
                "feasible": not violations,
                "violation_count": len(violations),
                "independent_violation_count": len(violations),
                "route_count": len(solution.routes),
                "ev_route_count": sum(
                    route.vehicle_type.lower() == "ev" for route in solution.routes
                ),
                "ev_customer_share": len(ev_served) / len(served) if served else 0.0,
                "charging_action_count": len(solution.charging_actions),
                "stop_iterations": stop_iterations[critical],
                "last_strict_improvement_iteration": last_improvements[critical],
                "l_over_s": l_over_s[critical],
                "view_round_count": len(traces),
                "view_stop_iterations_json": json.dumps(stop_iterations),
                "view_last_improvements_json": json.dumps(last_improvements),
                "view_l_over_s_json": json.dumps(l_over_s),
                "outer_rounds": extra["outer_rounds"],
                "outer_stop_reason": extra["outer_stop_reason"],
                "route_pool_size": extra["route_pool_size"],
                "selected_source": source,
                "trajectory_path": str(trajectory_path.relative_to(REPO)),
                "trajectory_sha256": common._sha256(trajectory_path),
                "witness_path": str(witness_path.relative_to(REPO)),
                "witness_sha256": common._sha256(witness_path),
                "price_binding_json": json.dumps(
                    dict(bundle.prices.diesel_price_by_city), sort_keys=True
                ),
            }
        )
    except Exception as exc:
        row.update(
            {
                "status": "ERROR",
                "feasible": False,
                "violation_count": "",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        )
        common._write_json(
            task_dir / "error.json",
            {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
    row.update(
        {
            "cpu_seconds": process_time() - started_cpu,
            "wallclock_seconds": perf_counter() - started_wall,
            "peak_rss_mib": common._peak_rss_mib(),
            "pid": os.getpid(),
            "start_method": mp.get_start_method(),
        }
    )
    common._write_json(result_path, row)
    return row


def _read_task_rows() -> list[dict[str, Any]]:
    rows = []
    for path in sorted((HERE / "tasks").glob("*/result.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def _write_raw_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _aggregate_write(rows: list[dict[str, Any]], final_keys: dict[tuple[str, int, str], int]) -> None:
    output = []
    for source in rows:
        row = dict(source)
        key = (row["instance_id"], int(row["seed"]), row["arm"])
        row["selected_final_attempt"] = int(row["attempt"]) == final_keys.get(key, -1)
        output.append(row)
    output.sort(
        key=lambda row: (
            row["instance_id"], int(row["seed"]), ARMS.index(row["arm"]), int(row["attempt"])
        )
    )
    _write_raw_csv(HERE / "raw_runs.csv", output)


def _run_specs(specs: list[tuple[str, str, str, int, int, str, int, int]]) -> list[dict[str, Any]]:
    existing = _read_task_rows()
    existing_keys = {
        (
            row["instance_id"],
            int(row["seed"]),
            row["arm"],
            int(row["attempt"]),
            int(row["k"]),
        )
        for row in existing
    }
    pending = [
        spec
        for spec in specs
        if (spec[0], spec[4], spec[5], spec[6], spec[7]) not in existing_keys
    ]
    rows = list(existing)
    context = mp.get_context("spawn")
    pool = ProcessPoolExecutor(
        max_workers=WORKERS, mp_context=context, max_tasks_per_child=1
    )
    try:
        futures = {pool.submit(_run_unit, spec): spec for spec in pending}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            common._write_json(
                HERE / "progress.json",
                {
                    "completed_attempt_rows": len(rows),
                    "pending_in_current_wave": sum(not item.done() for item in futures),
                    "updated_at_utc": datetime.now(UTC).isoformat(),
                },
            )
            if row["status"] != "PASS":
                for item in futures:
                    item.cancel()
                raise RuntimeError(
                    "campaign unit failed; queued work cancelled: "
                    f"{row['instance_id']} seed={row['seed']} arm={row['arm']} "
                    f"status={row['status']}"
                )
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return _read_task_rows()


def _starved_cells(final_rows: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    cells: dict[tuple[str, str], float] = {}
    for arm in ARMS:
        for layer in ("small", "medium", "large"):
            selected = [
                row for row in final_rows
                if row["arm"] == arm and row["size_layer"] == layer
            ]
            if not selected:
                continue
            cells[(arm, layer)] = sum(
                float(row["l_over_s"]) > STARVATION_THRESHOLD for row in selected
            ) / len(selected)
    return {
        key: value for key, value in cells.items() if value > STARVATION_FRACTION
    }


def _paper_outputs(final_rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary_rows: list[dict[str, Any]] = []
    for region in ("jjj", "prd", "cy"):
        for layer in ("small", "medium", "large"):
            for arm in ARMS:
                selected = [
                    row for row in final_rows
                    if row["region"] == region
                    and row["size_layer"] == layer
                    and row["arm"] == arm
                ]
                summary_rows.append(
                    {
                        "region": region,
                        "size_layer": layer,
                        "arm": arm,
                        "units": len(selected),
                        "feasible_units": sum(row["status"] == "PASS" for row in selected),
                        "mean_cost": mean(float(row["final_cost"]) for row in selected),
                        "median_cost": median(float(row["final_cost"]) for row in selected),
                        "mean_cpu_seconds": mean(float(row["cpu_seconds"]) for row in selected),
                        "mean_wallclock_seconds": mean(float(row["wallclock_seconds"]) for row in selected),
                        "median_stop_iterations": median(int(row["stop_iterations"]) for row in selected),
                    }
                )
    with (HERE / "paper_table_city_size_five_arms.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)
    lookup = {
        (row["instance_id"], int(row["seed"]), row["arm"]): float(row["final_cost"])
        for row in final_rows
    }
    paired_rows = []
    wins = ties = losses = 0
    improvements = []
    for instance_id, _region, _layer, _count in _instance_specs():
        for seed in SEEDS:
            o = lookup[(instance_id, seed, "O")]
            mv = lookup[(instance_id, seed, "MV")]
            improvement = 100.0 * (o - mv) / o
            outcome = "win" if mv < o - EPS else ("loss" if mv > o + EPS else "tie")
            wins += outcome == "win"
            ties += outcome == "tie"
            losses += outcome == "loss"
            improvements.append(improvement)
            paired_rows.append(
                {
                    "instance_id": instance_id,
                    "seed": seed,
                    "O_cost": o,
                    "MV_cost": mv,
                    "MV_outcome": outcome,
                    "MV_improvement_percent_vs_O": improvement,
                }
            )
    with (HERE / "paper_table_mv_vs_o_pairs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(paired_rows[0]))
        writer.writeheader()
        writer.writerows(paired_rows)
    return {
        "paired_units": len(paired_rows),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "mean_improvement_percent": mean(improvements),
    }


def _finalize(
    all_rows: list[dict[str, Any]],
    final_keys: dict[tuple[str, int, str], int],
    starvation_history: list[dict[str, Any]],
    frozen_hashes: dict[str, str],
) -> None:
    _aggregate_write(all_rows, final_keys)
    final_rows = [
        row for row in all_rows
        if int(row["attempt"]) == final_keys[(row["instance_id"], int(row["seed"]), row["arm"])]
    ]
    expected = 81 * 5 * 5
    unique = {(row["instance_id"], int(row["seed"]), row["arm"]) for row in final_rows}
    integrity_pass = (
        len(final_rows) == expected
        and len(unique) == expected
        and all(row["status"] == "PASS" for row in final_rows)
        and all(int(row["violation_count"]) == 0 for row in final_rows)
    )
    mv_vs_o = _paper_outputs(final_rows) if integrity_pass else None
    size_medians = {
        layer: {
            arm: median(
                int(row["stop_iterations"])
                for row in final_rows
                if row["size_layer"] == layer and row["arm"] == arm
            )
            for arm in ARMS
        }
        for layer in ("small", "medium", "large")
    }
    hunger_fingerprints = [
        arm
        for arm in ARMS
        if size_medians["large"][arm] < size_medians["small"][arm]
    ]
    verdict = (
        "PASS_E2_RERUN_UNIFIED_01_COMPLETE"
        if integrity_pass
        else "HALT_UNIFIED_RERUN_INTEGRITY_FAILURE"
    )
    common._write_json(
        HERE / "decision.json",
        {
            "schema": "resetp.e2-rerun-unified-01.decision.v1",
            "verdict": verdict,
            "expected_final_units": expected,
            "actual_final_units": len(final_rows),
            "all_final_units_feasible": integrity_pass,
            "starvation_history": starvation_history,
            "stop_iteration_medians_by_size_and_arm": size_medians,
            "large_below_small_hunger_fingerprint_arms": hunger_fingerprints,
            "mv_vs_o": mv_vs_o,
            "equal_compute_claim_allowed": False,
            "protected_files_modified": [],
        },
    )
    common._write_json(
        HERE / "metadata.json",
        {
            "schema": "resetp.e2-rerun-unified-01.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.executable,
            "python_version": sys.version,
            "platform": platform.platform(),
            "pyvrp_version": version("pyvrp"),
            "workers": WORKERS,
            "restart_type": "clean_restart_after_oversubscription_contamination",
            "contaminated_completed_attempt_rows_archived": 165,
            "contaminated_archive": CONTAMINATED_ARCHIVE,
            "worker_rationale": "reduced from 6 to 4 after measured throughput degradation under oversubscription; preserve stable wall-clock work for time-limited MIP",
            "start_method": "spawn",
            "instances": 81,
            "seeds": list(SEEDS),
            "arms": list(ARMS),
            "base_k": BASE_K,
            "starvation_rule": "cell fraction with L/S > 0.5 exceeds 20%; double K for that arm-size cell, at most twice",
            "mv_outer_round_limit": OUTER_ROUND_LIMIT,
            "mv_outer_no_improvement_patience": OUTER_NO_IMPROVEMENT_PATIENCE,
            "mv_route_pool": "full-model feasible routes accumulate across rounds",
            "mv_acceptance": "time-limited MIP incumbent accepted only through min() safety net",
            "equal_compute_claim_allowed": False,
            "frozen_hashes_before": frozen_hashes,
        },
    )
    report_lines = [
        "# E2-RERUN-UNIFIED-01 China81 全量统一重跑",
        "",
        f"裁决：`{verdict}`。最终单元 {len(final_rows)}/{expected}，完整模型与独立验解违约为零={integrity_pass}。",
        "",
        "本批是洁净重启批。发现时旧批约完成 163 行；安全停止落盘时为 165 个完整尝试行，"
        f"已整体归档至 `{CONTAMINATED_ARCHIVE}/`。旧行因双池超订使限时 MIP 的墙钟求解工作不可比，"
        "全部作废，不得用于论文数字或臂间比较。",
        f"并发固定为 {WORKERS} workers：依据项目实验手册在总吞吐恶化时按证据降级，"
        "并为限时 MIP 保留稳定的墙钟求解质量；没有将旧 6-worker 受污染数据复用进本批。",
        "每个尝试单元的 S、L、L/S、CPU 秒、墙钟秒与峰值 RSS 均保存在 `raw_runs.csv`；"
        "MV 的逐视角逐轮 S、L、L/S 另保存在对应 JSON 字段与轨迹文件。",
        "",
        "五臂同批、同机、同一 NoImprovement(K) 规则；MV 的三个视角每轮各自完整收敛，路线池跨轮累积。",
        "MV 预注册额外 CPU 为方法组成，报告分臂 CPU，不作等算力主张。",
        "",
        f"K 饥饿重跑记录：`{json.dumps(starvation_history, ensure_ascii=False, sort_keys=True)}`。",
        f"大规模停机迭代中位数低于小规模的臂：{hunger_fingerprints or '无'}。",
    ]
    if mv_vs_o is not None:
        report_lines.extend(
            [
                "",
                f"MV 对 O：{mv_vs_o['wins']} 胜 / {mv_vs_o['ties']} 平 / {mv_vs_o['losses']} 负；"
                f"全量配对平均改进 {mv_vs_o['mean_improvement_percent']:.6f}%。",
                "论文表源：`paper_table_city_size_five_arms.csv` 与 `paper_table_mv_vs_o_pairs.csv`。",
            ]
        )
    (HERE / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    current_hashes = {
        str(path.relative_to(REPO)): common._sha256(path)
        for path in (*PROTECTED, *CONTRACT_FILES)
    }
    if current_hashes != frozen_hashes:
        raise RuntimeError("protected or experiment-contract drift")
    files = {}
    for path in sorted(HERE.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and not path.name.endswith(".tmp")
            and not any(part.endswith(".monitor") for part in path.parts)
            and CONTAMINATED_ARCHIVE not in path.parts
            and "__pycache__" not in path.parts
        ):
            files[str(path.relative_to(REPO))] = common._sha256(path)
    common._write_json(
        HERE / "artifact_hashes.json",
        {
            "schema": "resetp.e2-rerun-unified-01.hashes.v1",
            "algorithm": "sha256",
            "self_excluded": True,
            "appledouble_files_included": False,
            "monitor_directories_excluded": True,
            "contaminated_partial_run_excluded": True,
            "files": files,
            "frozen_hashes_after": current_hashes,
        },
    )
    common._write_json(
        HERE / "done.json",
        {
            "status": "COMPLETED",
            "verdict": verdict,
            "final_units": len(final_rows),
            "created_at_utc": datetime.now(UTC).isoformat(),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()
    if args.workers != WORKERS:
        raise SystemExit(f"clean-restart contract requires exactly {WORKERS} workers")
    preflight_decision = json.loads(
        (PREFLIGHT / "decision.json").read_text(encoding="utf-8")
    )
    if preflight_decision.get("verdict") != "PASS_NEW_VEHICLE_PAIR_FEASIBILITY_PREFLIGHT":
        raise SystemExit("vehicle feasibility preflight did not pass")
    external = _external_experiment_python_processes()
    if external:
        common._write_json(
            HERE / "isolation_guard_anomaly.json",
            {
                "status": "HALT_EXTERNAL_EXPERIMENT_POOL_DETECTED_BEFORE_START",
                "detected_at_utc": datetime.now(UTC).isoformat(),
                "external_processes": external,
            },
        )
        raise SystemExit("external experiment Python pool detected; campaign not started")
    _start_isolation_guard()
    frozen_hashes = {
        str(path.relative_to(REPO)): common._sha256(path)
        for path in (*PROTECTED, *CONTRACT_FILES)
    }
    instances = _instance_specs()
    final_keys: dict[tuple[str, int, str], int] = {}
    base_specs = [
        (*instance, seed, arm, 0, BASE_K)
        for instance in instances
        for seed in SEEDS
        for arm in ARMS
    ]
    all_rows = _run_specs(base_specs)
    final_keys.update(
        {
            (instance[0], seed, arm): 0
            for instance in instances
            for seed in SEEDS
            for arm in ARMS
        }
    )
    starvation_history: list[dict[str, Any]] = []
    for doubling in range(1, MAX_K_DOUBLINGS + 1):
        final_rows = [
            row for row in all_rows
            if int(row["attempt"])
            == final_keys[(row["instance_id"], int(row["seed"]), row["arm"])]
        ]
        if any(row["status"] != "PASS" for row in final_rows):
            break
        cells = _starved_cells(final_rows)
        starvation_history.append(
            {
                "after_attempt": doubling - 1,
                "triggered_cells": {
                    f"{arm}:{layer}": fraction
                    for (arm, layer), fraction in sorted(cells.items())
                },
            }
        )
        if not cells:
            break
        next_k = BASE_K * (2 ** doubling)
        rerun_specs = [
            (*instance, seed, arm, doubling, next_k)
            for instance in instances
            for seed in SEEDS
            for arm, layer in cells
            if instance[2] == layer
        ]
        all_rows = _run_specs(rerun_specs)
        for spec in rerun_specs:
            final_keys[(spec[0], spec[4], spec[5])] = doubling
    else:
        final_rows = [
            row for row in all_rows
            if int(row["attempt"])
            == final_keys[(row["instance_id"], int(row["seed"]), row["arm"])]
        ]
        final_cells = _starved_cells(final_rows)
        starvation_history.append(
            {
                "after_attempt": MAX_K_DOUBLINGS,
                "triggered_cells_after_max_doublings": {
                    f"{arm}:{layer}": fraction
                    for (arm, layer), fraction in sorted(final_cells.items())
                },
            }
        )
    _finalize(all_rows, final_keys, starvation_history, frozen_hashes)


if __name__ == "__main__":
    main()
