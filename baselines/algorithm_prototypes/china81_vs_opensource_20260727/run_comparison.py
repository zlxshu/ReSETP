#!/usr/bin/env python3
"""Run only the new distance-only O arm and join sealed F/E/M/MV evidence.

The four historical arms are imported read-only from the protected corrected
China81 v7 full gate.  Only O is searched in this campaign.  O terminates on
``NoImprovement(3000)`` without a wall-clock algorithm stop, as required by
the frozen 2026-07-27 design.  Results are atomically persisted after every
completed unit and can be resumed by ``(instance_id, seed, arm)``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import multiprocessing as mp
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from time import perf_counter, process_time, sleep
from typing import Any

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CAMPAIGN_ROOT = REPO / "baselines/e2_final_campaign_20260720"
FROZEN_RUNNER = CAMPAIGN_ROOT / "run_corrected_china81_d6.py"
ARCHIVE = (
    CAMPAIGN_ROOT
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724/full_gate"
)
ARCHIVE_RAW = ARCHIVE / "raw_runs.csv"
ARCHIVE_DECISION = ARCHIVE / "decision.json"
ARCHIVE_HASHES = ARCHIVE / "artifact_hashes.json"
DESIGN = REPO / "docs/handoff/china81_vs_opensource_design_20260727.md"
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
INSTANCE_DIR = (
    REPO
    / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718/instances"
)
RAW_RUNS = HERE / "raw_runs.json"
PROGRESS = HERE / "progress.json"
O_ARM = "O"
ARCHIVE_ARMS = ("F", "E", "M", "MV")
ARCHIVE_LABELS = {
    "F": "HGS-F",
    "E": "HGS-E",
    "M": "HGS-M",
    "MV": "MV-HGS-SP",
}
NO_IMPROVEMENT = 3_000
EPS = 1.0e-9
DEVELOPMENT_INSTANCES = tuple(
    f"cn-{region}-{size}c-01-V2-LOCATIONS"
    for region in ("jjj", "prd", "cy")
    for size in (25, 100, 200)
)
DEVELOPMENT_SEEDS = (1, 2, 3)
CONFIRMATION_SEEDS = (1, 2, 3, 4, 5)
REQUIRED_ENV = {
    "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

_IMPORT_PATHS = (HERE, CAMPAIGN_ROOT, REPO / "solver/src", PROTOTYPE)
for path in _IMPORT_PATHS:
    while str(path) in sys.path:
        sys.path.remove(str(path))
for path in reversed(_IMPORT_PATHS):
    sys.path.insert(0, str(path))

import run_corrected_china81_d6 as corrected_base
from pyvrp.stop import NoImprovement
from pyvrp_adapter import (
    _project_initial_solution,
    _translate_solution,
    build_pyvrp_problem,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import (
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)


def _canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_canonical_bytes(payload))
    temporary.replace(path)


def _read_json_rows() -> list[dict[str, Any]]:
    if not RAW_RUNS.is_file():
        return []
    payload = json.loads(RAW_RUNS.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError("raw_runs.json must contain a list")
    return [dict(row) for row in payload]


def _source_hashes() -> dict[str, str]:
    paths = (
        DESIGN,
        Path(__file__).resolve(),
        HERE / "pyvrp_adapter.py",
        FROZEN_RUNNER,
        PROTOTYPE / "pyvrp_adapter.py",
        REPO / "solver/src/setp_solver/china81.py",
        REPO / "solver/src/setp_solver/china81_completion.py",
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/check.py",
        ARCHIVE_RAW,
        ARCHIVE_DECISION,
        ARCHIVE_HASHES,
    )
    return {
        str(path.relative_to(REPO)): _file_sha256(path)
        for path in paths
    }


def _all_instance_ids() -> tuple[str, ...]:
    values = tuple(
        sorted(path.name for path in INSTANCE_DIR.iterdir() if path.is_dir())
    )
    if len(values) != 81:
        raise RuntimeError(f"expected 81 China81 instances, found {len(values)}")
    return values


def _scope(confirmation: bool) -> tuple[tuple[str, ...], tuple[int, ...]]:
    if confirmation:
        return _all_instance_ids(), CONFIRMATION_SEEDS
    missing = [
        instance_id
        for instance_id in DEVELOPMENT_INSTANCES
        if not (INSTANCE_DIR / instance_id).is_dir()
    ]
    if missing:
        raise RuntimeError(f"development instances missing: {missing}")
    return DEVELOPMENT_INSTANCES, DEVELOPMENT_SEEDS


def _archive_rows(
    instance_ids: tuple[str, ...],
    seeds: tuple[int, ...],
) -> list[dict[str, Any]]:
    decision = json.loads(ARCHIVE_DECISION.read_text(encoding="utf-8"))
    if decision.get("verdict") != (
        "PASS_D6_CORRECTED_CHINA81_E2_STAGED_V7_SMALL_ARCHIVE_LEDGER"
    ):
        raise RuntimeError("sealed v7 archive decision is not PASS")
    with ARCHIVE_RAW.open(newline="", encoding="utf-8-sig") as handle:
        source = list(csv.DictReader(handle))
    wanted = set(instance_ids)
    wanted_seeds = set(seeds)
    selected = [
        row
        for row in source
        if row["instance_id"] in wanted and int(row["seed"]) in wanted_seeds
    ]
    expected = len(instance_ids) * len(seeds)
    if len(selected) != expected:
        raise RuntimeError(
            f"sealed archive selection has {len(selected)} rows, expected {expected}"
        )
    rows: list[dict[str, Any]] = []
    archive_sha = _file_sha256(ARCHIVE_RAW)
    for source_row in selected:
        instance_id = source_row["instance_id"]
        seed = int(source_row["seed"])
        witness_path = (
            ARCHIVE
            / "tasks"
            / f"D6-E2-STAGED__{instance_id}__seed{seed}"
            / "solution_witnesses.json"
        )
        witnesses = json.loads(witness_path.read_text(encoding="utf-8"))
        for arm in ARCHIVE_ARMS:
            label = ARCHIVE_LABELS[arm]
            witness = witnesses[label]
            routes = list(witness["routes"])
            rows.append(
                {
                    "instance_id": instance_id,
                    "seed": seed,
                    "arm": arm,
                    "final_cost": float(source_row[f"{label}_cost"]),
                    "feasible": bool(
                        source_row["all_independently_feasible"] == "True"
                    ),
                    "violation_count": 0,
                    "violations": [],
                    "cpu_seconds": float(
                        source_row[f"{label}_cpu_seconds"]
                    ),
                    "wallclock_seconds": None,
                    "route_count": len(routes),
                    "ev_route_count": sum(
                        str(route["vehicle_type"]).lower() == "ev"
                        for route in routes
                    ),
                    "data_source": "SEALED_V7_ARCHIVE_20260724",
                    "budget_rule": "V7_FIXED_25000_ITERATIONS_PER_VIEW",
                    "source_path": str(ARCHIVE_RAW.relative_to(REPO)),
                    "source_sha256": archive_sha,
                    "witness_path": str(witness_path.relative_to(REPO)),
                    "witness_sha256": _file_sha256(witness_path),
                    "stop_iterations": int(
                        source_row["total_iterations_per_view"]
                    ),
                    "selected_source": source_row["selected_source"],
                    "runner_sha256": None,
                    "adapter_sha256": None,
                    "status": "PASS",
                }
            )
    return rows


def _run_o_unit(spec: tuple[str, int]) -> dict[str, Any]:
    instance_id, seed = spec
    for key, value in REQUIRED_ENV.items():
        if os.environ.get(key) != value:
            raise RuntimeError(f"required environment mismatch: {key}")
    if version("pyvrp") != "0.12.2":
        raise RuntimeError("O arm requires PyVRP 0.12.2 HGS")

    bundle = load_china81_bundle(REPO, instance_id)
    initial = corrected_base._load_initial(instance_id)
    initial_completion = complete_china81_route_skeleton(initial, bundle)
    problem = build_pyvrp_problem(bundle, route_proxy_mode="distance_only")
    data = problem.model.data()
    projected = _project_initial_solution(initial, data, problem)
    solve_kwargs: dict[str, Any] = {
        "seed": int(seed),
        "display": False,
        "collect_stats": True,
    }
    if "initial_solution" in inspect.signature(problem.model.solve).parameters:
        solve_kwargs["initial_solution"] = projected

    wall_started = perf_counter()
    cpu_started = process_time()
    result = problem.model.solve(
        NoImprovement(NO_IMPROVEMENT),
        **solve_kwargs,
    )
    cpu_seconds = process_time() - cpu_started
    wallclock_seconds = perf_counter() - wall_started
    searched_skeleton = _translate_solution(result.best, problem)
    searched_failure: str | None = None
    try:
        searched_completion = complete_china81_route_skeleton(
            searched_skeleton,
            bundle,
        )
    except (IndexError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        searched_failure = f"{type(exc).__name__}: {exc}"
        searched_completion = None
    if (
        searched_completion is not None
        and searched_completion.objective
        < initial_completion.objective - EPS
    ):
        selected_source = "distance_only_hgs_search"
        completion = searched_completion
    else:
        selected_source = "common_initial_incumbent"
        completion = initial_completion
    solution = annotate_cross_site_services(
        completion.solution,
        bundle.customer_home_depot,
    )
    objective, _breakdown, violations = exact_china81_score(solution, bundle)
    if abs(float(objective) - float(completion.objective)) > EPS:
        raise RuntimeError(
            f"exact scorer mismatch for {instance_id} seed={seed}"
        )
    witness = corrected_base._solution_payload(solution)
    routes = list(witness["routes"])
    return {
        "row": {
            "instance_id": instance_id,
            "seed": int(seed),
            "arm": O_ARM,
            "final_cost": float(objective),
            "feasible": not violations,
            "violation_count": len(violations),
            "violations": [str(item) for item in violations],
            "cpu_seconds": float(cpu_seconds),
            "wallclock_seconds": float(wallclock_seconds),
            "route_count": len(routes),
            "ev_route_count": sum(
                str(route["vehicle_type"]).lower() == "ev"
                for route in routes
            ),
            "data_source": "NEW_DISTANCE_ONLY_O_20260727",
            "budget_rule": f"NoImprovement({NO_IMPROVEMENT})",
            "source_path": str(Path(__file__).resolve().relative_to(REPO)),
            "source_sha256": _file_sha256(Path(__file__).resolve()),
            "witness_path": None,
            "witness_sha256": _payload_sha256(witness),
            "stop_iterations": int(result.num_iterations),
            "selected_source": selected_source,
            "searched_completion_failure": searched_failure,
            "runner_sha256": _file_sha256(Path(__file__).resolve()),
            "adapter_sha256": _file_sha256(HERE / "pyvrp_adapter.py"),
            "status": "PASS" if not violations else "FAIL",
        },
        "witness": witness,
    }


def _probe_worker(index: int) -> dict[str, Any]:
    import pyvrp
    import pyvrp_adapter as active_adapter

    # Keep every submitted probe occupied long enough for the spawn executor
    # to materialise all requested workers instead of recycling early PIDs.
    sleep(1.0)
    return {
        "index": int(index),
        "pid": os.getpid(),
        "pyvrp_hgs": hasattr(pyvrp, "GeneticAlgorithm"),
        "pyvrp_version": version("pyvrp"),
        "adapter_path": str(Path(active_adapter.__file__).resolve()),
        "python": str(Path(sys.executable).resolve()),
    }


def _resource_preflight(workers: int) -> dict[str, Any]:
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        rows = list(pool.map(_probe_worker, range(workers)))
    distinct_pids = len({row["pid"] for row in rows})
    passed = (
        len(rows) == workers
        and distinct_pids == workers
        and all(row["pyvrp_hgs"] for row in rows)
        and all(row["pyvrp_version"] == "0.12.2" for row in rows)
        and all(
            row["adapter_path"] == str((HERE / "pyvrp_adapter.py").resolve())
            for row in rows
        )
    )
    payload = {
        "schema": "resetp.china81-vs-opensource.resource-preflight.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "workers": workers,
        "distinct_pids": distinct_pids,
        "passed": passed,
        "rows": rows,
    }
    _write_json(HERE / "resource_preflight.json", payload)
    if not passed:
        raise RuntimeError("HALT_RESOURCE_PREFLIGHT")
    return payload


def _outcome(left: float, right: float) -> str:
    delta = left - right
    return "win" if delta < -EPS else ("loss" if delta > EPS else "tie")


def _finalize(
    rows: list[dict[str, Any]],
    instance_ids: tuple[str, ...],
    seeds: tuple[int, ...],
    confirmation: bool,
) -> dict[str, Any]:
    by_key = {
        (row["instance_id"], int(row["seed"]), row["arm"]): row
        for row in rows
    }
    expected = len(instance_ids) * len(seeds) * 5
    complete = len(by_key) == expected
    pairs: list[dict[str, Any]] = []
    stairs: list[dict[str, Any]] = []
    outcomes = {"win": 0, "tie": 0, "loss": 0}
    transition_counts = {
        "O_to_F": {"improve": 0, "tie": 0, "regress": 0},
        "F_to_E": {"improve": 0, "tie": 0, "regress": 0},
        "E_to_M": {"improve": 0, "tie": 0, "regress": 0},
        "M_to_MV": {"improve": 0, "tie": 0, "regress": 0},
    }
    improvements: list[float] = []
    for instance_id in instance_ids:
        for seed in seeds:
            unit = {
                arm: by_key.get((instance_id, seed, arm))
                for arm in ("O", "F", "E", "M", "MV")
            }
            if any(value is None for value in unit.values()):
                continue
            costs = {arm: float(unit[arm]["final_cost"]) for arm in unit}
            result = _outcome(costs["MV"], costs["O"])
            outcomes[result] += 1
            improvement = 100.0 * (costs["O"] - costs["MV"]) / costs["O"]
            improvements.append(improvement)
            pairs.append(
                {
                    "instance_id": instance_id,
                    "seed": seed,
                    "O_cost": costs["O"],
                    "MV_cost": costs["MV"],
                    "MV_vs_O": result,
                    "MV_improvement_percent_vs_O": improvement,
                }
            )
            chain = ("O", "F", "E", "M", "MV")
            monotone = all(
                costs[right] <= costs[left] + EPS
                for left, right in pairwise(chain)
            )
            stairs.append(
                {
                    "instance_id": instance_id,
                    "seed": seed,
                    "monotone_nonincreasing": monotone,
                    **{f"{arm}_cost": costs[arm] for arm in chain},
                }
            )
            for left, right in pairwise(chain):
                transition = _outcome(costs[right], costs[left])
                bucket = (
                    "improve" if transition == "win"
                    else "regress" if transition == "loss"
                    else "tie"
                )
                transition_counts[f"{left}_to_{right}"][bucket] += 1

    decision = {
        "schema": "resetp.china81-vs-opensource.decision.v1",
        "verdict": (
            "DEVELOPMENT_COMPLETE" if complete and not confirmation
            else "CONFIRMATION_COMPLETE" if complete
            else "PARTIAL"
        ),
        "scope": "confirmation" if confirmation else "development",
        "expected_rows": expected,
        "actual_rows": len(by_key),
        "O_new_rows": sum(row["arm"] == "O" for row in rows),
        "sealed_rows_reused": sum(row["arm"] != "O" for row in rows),
        "MV_vs_O": outcomes,
        "mean_MV_improvement_percent_vs_O": (
            sum(improvements) / len(improvements) if improvements else None
        ),
        "monotone_staircase_units": sum(
            bool(row["monotone_nonincreasing"]) for row in stairs
        ),
        "paired_units": len(pairs),
        "transition_counts": transition_counts,
        "protocol_disclosure": {
            "O": f"new NoImprovement({NO_IMPROVEMENT}) run",
            "F_E_M_MV": "sealed v7 fixed-iteration archive reuse",
            "same_batch_or_same_machine_claim_allowed": False,
            "archive_wallclock_available": False,
        },
    }
    _write_json(HERE / "decision.json", decision)
    _write_json(HERE / "paired_mv_vs_o.json", pairs)
    _write_json(HERE / "staircase_units.json", stairs)
    metadata = {
        "schema": "resetp.china81-vs-opensource.metadata.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": decision["scope"],
        "instances": list(instance_ids),
        "seeds": list(seeds),
        "arms": ["O", "F", "E", "M", "MV"],
        "python": sys.version,
        "python_executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "pyvrp_version": version("pyvrp"),
        "environment": {key: os.environ.get(key) for key in REQUIRED_ENV},
        "source_hashes": _source_hashes(),
    }
    _write_json(HERE / "metadata.json", metadata)
    report = [
        "# China81 MV-HGS-SP vs open-source distance-only HGS",
        "",
        f"Decision: `{decision['verdict']}`.",
        "",
        f"Scope: {decision['scope']}; rows {len(by_key)}/{expected}.",
        (
            f"New O rows: {decision['O_new_rows']}; sealed F/E/M/MV rows: "
            f"{decision['sealed_rows_reused']}."
        ),
        "",
        "## Required disclosure",
        "",
        (
            "O was newly run with `NoImprovement(3000)` and no wall-clock "
            "algorithm stop. F/E/M/MV were imported from the sealed 2026-07-24 "
            "v7 fixed-iteration batch. They were not rerun in the O batch, and "
            "the historical batch has CPU but no separately recoverable wall-clock "
            "field. This evidence must not be described as same-batch, same-machine, "
            "same-stop-rule, or equal-compute."
        ),
        "",
        "## Frozen readings",
        "",
        f"MV vs O: {outcomes}.",
        (
            "Mean MV improvement vs O: "
            f"{decision['mean_MV_improvement_percent_vs_O']}%."
        ),
        (
            "Monotone O→F→E→M→MV units: "
            f"{decision['monotone_staircase_units']}/{len(stairs)}."
        ),
        f"Transition counts: `{json.dumps(transition_counts, sort_keys=True)}`.",
        "",
    ]
    (HERE / "report.md").write_text("\n".join(report), encoding="utf-8")
    artifact_paths = (
        RAW_RUNS,
        HERE / "metadata.json",
        HERE / "decision.json",
        HERE / "report.md",
        HERE / "paired_mv_vs_o.json",
        HERE / "staircase_units.json",
        HERE / "resource_preflight.json",
    )
    _write_json(
        HERE / "artifact_hashes.json",
        {
            "schema": "resetp.china81-vs-opensource.artifact-hashes.v1",
            "algorithm": "sha256",
            "artifacts": {
                str(path.relative_to(HERE)): _file_sha256(path)
                for path in artifact_paths
                if path.is_file()
            },
        },
    )
    return decision


def _run(
    *,
    workers: int,
    confirmation: bool,
    preflight_only: bool,
    finalize_only: bool,
) -> dict[str, Any]:
    if workers < 1 or workers > 6:
        raise ValueError("workers must be between 1 and 6")
    for key, value in REQUIRED_ENV.items():
        if os.environ.get(key) != value:
            raise RuntimeError(f"required environment mismatch: {key}")
    instance_ids, seeds = _scope(confirmation)
    archive_rows = _archive_rows(instance_ids, seeds)
    current = _read_json_rows()
    existing_o = {
        (row["instance_id"], int(row["seed"])): row
        for row in current
        if row.get("arm") == "O"
    }
    runner_hash = _file_sha256(Path(__file__).resolve())
    adapter_hash = _file_sha256(HERE / "pyvrp_adapter.py")
    for row in existing_o.values():
        if (
            row.get("runner_sha256") != runner_hash
            or row.get("adapter_sha256") != adapter_hash
        ):
            raise RuntimeError("existing O row source hash mismatch")
    rows = [*archive_rows, *existing_o.values()]
    rows.sort(key=lambda row: (row["instance_id"], int(row["seed"]), row["arm"]))
    _write_json(RAW_RUNS, rows)
    if finalize_only:
        return _finalize(rows, instance_ids, seeds, confirmation)
    preflight = _resource_preflight(workers)
    if preflight_only:
        return {"verdict": "PASS_RESOURCE_PREFLIGHT", **preflight}
    pending = [
        (instance_id, seed)
        for instance_id in instance_ids
        for seed in seeds
        if (instance_id, seed) not in existing_o
    ]
    _write_json(
        PROGRESS,
        {
            "status": "RUNNING",
            "scope": "confirmation" if confirmation else "development",
            "completed_O": len(existing_o),
            "remaining_O": len(pending),
            "updated_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    context = mp.get_context("spawn")
    try:
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
        ) as executor:
            futures = {
                executor.submit(_run_o_unit, task): task
                for task in pending
            }
            for future in as_completed(futures):
                instance_id, seed = futures[future]
                payload = future.result()
                task_dir = HERE / "tasks" / f"{instance_id}__seed{seed}__O"
                witness_path = task_dir / "solution_witness.json"
                _write_json(witness_path, payload["witness"])
                row = dict(payload["row"])
                row["witness_path"] = str(witness_path.relative_to(REPO))
                if _file_sha256(witness_path) != row["witness_sha256"]:
                    raise RuntimeError("persisted O witness hash mismatch")
                existing_o[(instance_id, seed)] = row
                rows = [*archive_rows, *existing_o.values()]
                rows.sort(
                    key=lambda item: (
                        item["instance_id"],
                        int(item["seed"]),
                        item["arm"],
                    )
                )
                _write_json(RAW_RUNS, rows)
                _write_json(
                    PROGRESS,
                    {
                        "status": "RUNNING",
                        "scope": (
                            "confirmation" if confirmation else "development"
                        ),
                        "completed_O": len(existing_o),
                        "remaining_O": (
                            len(instance_ids) * len(seeds) - len(existing_o)
                        ),
                        "last_task": f"{instance_id}__seed{seed}__O",
                        "updated_at_utc": datetime.now(UTC).isoformat(),
                    },
                )
                print(
                    f"[O] {instance_id} seed={seed} PASS "
                    f"({len(existing_o)}/{len(instance_ids) * len(seeds)})",
                    flush=True,
                )
    except Exception as exc:
        _write_json(
            PROGRESS,
            {
                "status": "HALT",
                "completed_O": len(existing_o),
                "failure": f"{type(exc).__name__}: {exc}",
                "updated_at_utc": datetime.now(UTC).isoformat(),
            },
        )
        raise
    decision = _finalize(rows, instance_ids, seeds, confirmation)
    _write_json(
        PROGRESS,
        {
            "status": "COMPLETED",
            "completed_O": len(existing_o),
            "remaining_O": 0,
            "verdict": decision["verdict"],
            "updated_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--confirmation", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--finalize-only", action="store_true")
    args = parser.parse_args()
    decision = _run(
        workers=args.workers,
        confirmation=bool(args.confirmation),
        preflight_only=bool(args.preflight_only),
        finalize_only=bool(args.finalize_only),
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
