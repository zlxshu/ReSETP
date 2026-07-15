#!/usr/bin/env python3
"""Resumable formal runner for the three-network, two-condition E7 experiment.

The scientific work remains in ``run_probe_arm``.  This module only freezes a
contract, runs the full condition-by-stream-by-arm matrix, checkpoints each
finished task atomically, and assembles the evidence package without selecting
or interpreting result directions.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as probe


OUT = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
CONTRACT_ID = "E7_MULTINETWORK_FORMAL_V1_THREE_NETWORKS_TWO_CONDITIONS"
TASK_SCHEMA = "setp.e7.formal.task.v1"
RUN_SCHEMA = "setp.e7.formal.run.v1"
STREAMS = (1, 2, 3, 4, 5)
CONDITIONS = tuple(probe.CONDITIONS)
NETWORKS = tuple(probe.NETWORKS)
ARMS = tuple(probe.ARMS)
DEFAULT_WORKERS = 6
ALL_STAGES_SENTINEL = 10_000
TOL = 1e-6
REQUIRED_PROBE_CAPABILITY = "setp.e7.full_day_execution.v2"


class FormalRunError(RuntimeError):
    """Base class for evidence-preserving formal-run failures."""


class ContractMismatchError(FormalRunError):
    """Raised when an existing output belongs to another frozen contract."""


class TaskCheckpointError(FormalRunError):
    """Raised when a task checkpoint is incomplete, corrupt, or inconsistent."""


def verify_probe_capability() -> None:
    if (
        getattr(probe, "FULL_DAY_EXECUTION_SCHEMA", None)
        != REQUIRED_PROBE_CAPABILITY
    ):
        raise FormalRunError(
            "run_probe_arm does not yet expose the frozen full-day merged execution "
            "ledger required by the formal wrapper"
        )


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, payload: Any) -> None:
    _atomic_write_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
    )


def atomic_write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write_text(path, buffer.getvalue())


def _source_paths() -> tuple[Path, ...]:
    candidates = {
        Path(__file__).resolve(),
        Path(probe.__file__).resolve(),
        Path(probe.base.__file__).resolve(),
        Path(probe.base.gate.__file__).resolve(),
        Path(probe.base.p2.__file__).resolve(),
        Path(probe.e4.__file__).resolve(),
        ROOT / "solver/src/setp_solver/search/bundle.py",
        ROOT / "solver/src/setp_solver/solution.py",
        *probe.SOURCE_FILES,
    }
    missing = sorted(str(path) for path in candidates if not path.is_file())
    if missing:
        raise FileNotFoundError(f"formal source file is missing: {missing}")
    return tuple(sorted(candidates))


def _serializable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    return value


def build_contract(evaluations: int) -> dict[str, Any]:
    if evaluations <= 0:
        raise ValueError("evaluations must be positive")
    source_hashes = {
        str(path.relative_to(ROOT)): sha256(path) for path in _source_paths()
    }
    input_hashes: dict[str, str] = {}
    condition_inputs: dict[str, Any] = {}
    for network in NETWORKS:
      for condition in CONDITIONS:
        sources, profiles = probe._sources_for_day(condition, network)
        input_hashes[str(sources["solution_path"].relative_to(ROOT))] = sha256(
            sources["solution_path"]
        )
        input_hashes[str(sources["certificate_path"].relative_to(ROOT))] = sha256(
            sources["certificate_path"]
        )
        condition_inputs[f"{network}__{condition}"] = {
            "network": network,
            "case": sources["case"],
            "instance_sha256": canonical_sha256(
                _serializable(sources["bundle"].instance)
            ),
            "prices_sha256": canonical_sha256(_serializable(sources["prices"])),
            "carbon_profiles_sha256": canonical_sha256(_serializable(profiles)),
        }
        for stream in STREAMS:
            _events, _owners, event_path, owner_path = probe._stream_for_condition(
                stream, condition, network
            )
            input_hashes[str(event_path.relative_to(ROOT))] = sha256(event_path)
            input_hashes[str(owner_path.relative_to(ROOT))] = sha256(owner_path)
    carbon_source = Path(probe.e4.CARBON_SOURCE).resolve()
    input_hashes[str(carbon_source.relative_to(ROOT))] = sha256(carbon_source)
    body = {
        "schema": RUN_SCHEMA,
        "contract_id": CONTRACT_ID,
        "conditions": list(CONDITIONS),
        "networks": list(NETWORKS),
        "streams": list(STREAMS),
        "arms": list(ARMS),
        "evaluations_per_search_call": int(evaluations),
        "search_calls_per_arm_stage": 2,
        "stage_scope": "all_available_trigger_batches",
        "operating_day": probe.OPERATING_DAY.isoformat(),
        "condition_inputs": condition_inputs,
        "input_file_hashes": dict(sorted(input_hashes.items())),
        "source_file_hashes": dict(sorted(source_hashes.items())),
        "physical_rules": {
            "new_orders_enter_only_editable_future_trips": True,
            "inherited_vehicle_availability_and_battery_are_preserved": True,
            "locked_routes_and_charging_actions_are_not_rewritten": True,
        },
        "evidence_boundary": (
            "All condition, stream, and arm results are retained. Result direction "
            "does not decide task execution, inclusion, or aggregation."
        ),
    }
    return {**body, "contract_sha256": canonical_sha256(body)}


def _visible_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return [
        item
        for item in path.iterdir()
        if not item.name.startswith("._") and ".tmp-" not in item.name
    ]


def ensure_contract(
    output: Path,
    contract: Mapping[str, Any],
    *,
    source_commit_at_start: str,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    path = output / "contract.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        comparable = {
            key: value
            for key, value in existing.items()
            if key != "source_commit_at_start"
        }
        if comparable != contract:
            raise ContractMismatchError(
                "existing output contract differs from the requested formal contract"
            )
        if not existing.get("source_commit_at_start"):
            raise ContractMismatchError(
                "existing output contract has no source commit at start"
            )
        return existing
    if _visible_files(output):
        raise ContractMismatchError(
            "output directory is non-empty but has no formal contract"
        )
    stored = {**contract, "source_commit_at_start": source_commit_at_start}
    atomic_write_json(path, stored)
    return stored


def task_id(network: str, condition: str, stream: int, arm: str) -> str:
    return f"{network}__{condition}__stream{stream}__{arm}"


def _expected_tasks(evaluations: int) -> list[dict[str, Any]]:
    return [
        {
            "task_id": task_id(network, condition, stream, arm),
            "network": network,
            "condition": condition,
            "stream": stream,
            "arm": arm,
            "evaluations": evaluations,
            "max_stages": ALL_STAGES_SENTINEL,
        }
        for network in NETWORKS
        for condition in CONDITIONS
        for stream in STREAMS
        for arm in ARMS
    ]


def _task_path(output: Path, task: Mapping[str, Any]) -> Path:
    return output / ".tasks" / f"{task['task_id']}.json"


def _run_task(task: Mapping[str, Any]) -> dict[str, Any]:
    return probe.run_probe_arm(
        str(task["arm"]),
        condition=str(task["condition"]),
        stream_seed=int(task["stream"]),
        evaluations=int(task["evaluations"]),
        max_stages=int(task["max_stages"]),
        network=str(task["network"]),
    )


def validate_task_payload(
    task: Mapping[str, Any], payload: Mapping[str, Any]
) -> list[str]:
    failures: list[str] = []
    identity = {
        "network": task["network"],
        "arm": task["arm"],
        "responsibility_condition": task["condition"],
        "stream_seed": task["stream"],
    }
    for key, expected in identity.items():
        if payload.get(key) != expected:
            failures.append(f"{task['task_id']}: payload {key} differs")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return [*failures, f"{task['task_id']}: rows are missing"]
    stages = int(payload.get("stages", -1))
    available = int(payload.get("available_stages", -1))
    if stages <= 0 or stages != available or len(rows) != stages:
        failures.append(
            f"{task['task_id']}: did not complete every available stage"
        )
    if [int(row.get("stage", -1)) for row in rows] != list(
        range(1, stages + 1)
    ):
        failures.append(f"{task['task_id']}: stage sequence is incomplete")
    evaluations = int(task["evaluations"])
    for row in rows:
        stage = row.get("stage")
        prefix = f"{task['task_id']}/stage{stage}"
        if row.get("arm") != task["arm"]:
            failures.append(f"{prefix}: arm differs")
        if row.get("responsibility_condition") != task["condition"]:
            failures.append(f"{prefix}: condition differs")
        if int(row.get("stream_seed", -1)) != int(task["stream"]):
            failures.append(f"{prefix}: stream differs")
        expected_main = 1 if task["arm"] == "simple_insertion" else evaluations
        if int(row.get("main_evaluations", -1)) != expected_main:
            failures.append(f"{prefix}: main budget differs")
        if int(row.get("shadow_evaluations", -1)) != evaluations:
            failures.append(f"{prefix}: comparison budget differs")
        if task["arm"] != "simple_insertion" and int(row.get("main_search_seed", -1)) == int(
            row.get("shadow_search_seed", -1)
        ):
            failures.append(f"{prefix}: search call identities are not distinct")
        if task["arm"] != "simple_insertion" and row.get("second_start_sha256") != row.get("baseline_output_sha256"):
            failures.append(f"{prefix}: paired searches did not share one start")
        if row.get("customer_accounting_pass") is not True:
            failures.append(f"{prefix}: customer accounting failed")
        if float(row.get("predicted_charging_saving_kg", -math.inf)) < -TOL:
            failures.append(f"{prefix}: predicted charging emissions worsened")
        if task["arm"] == "no_cooperation" and int(
            row.get("cross_site_customer_count", -1)
        ) != 0:
            failures.append(f"{prefix}: no-cooperation arm crossed depots")
        if task["arm"] == "full" and float(
            row.get("minimum_profit_margin", -math.inf)
        ) < -TOL:
            failures.append(f"{prefix}: participation floor failed")
    initial = payload.get("initial_timing", {})
    if float(initial.get("predicted_charging_saving_kg", -math.inf)) < -TOL:
        failures.append(f"{task['task_id']}: initial predicted emissions worsened")
    final_running = payload.get("final_running")
    required_final = {
        "total_profit",
        "total_revenue",
        "total_cost",
        "direct_emissions_kg",
        "predicted_charging_emissions_kg",
        "actual_charging_emissions_kg",
        "total_actual_emissions_kg",
        "depot_profit",
    }
    if not isinstance(final_running, Mapping) or not required_final.issubset(
        final_running
    ):
        failures.append(f"{task['task_id']}: final full-day ledger is incomplete")
    execution = payload.get("full_day_execution")
    required_execution = {
        "completed_customer_ids",
        "completed_customer_count",
        "completed_demand",
        "cross_site_customer_ids",
        "cross_site_customer_count",
        "solution_sha256",
    }
    if not isinstance(execution, Mapping) or not required_execution.issubset(execution):
        failures.append(
            f"{task['task_id']}: full-day merged execution ledger is incomplete"
        )
    else:
        completed_ids = list(execution["completed_customer_ids"])
        cross_ids = list(execution["cross_site_customer_ids"])
        if len(completed_ids) != len(set(completed_ids)) or int(
            execution["completed_customer_count"]
        ) != len(completed_ids):
            failures.append(
                f"{task['task_id']}: completed-customer ledger does not close"
            )
        if len(cross_ids) != len(set(cross_ids)) or int(
            execution["cross_site_customer_count"]
        ) != len(cross_ids):
            failures.append(f"{task['task_id']}: cross-site ledger does not close")
        if not set(cross_ids).issubset(completed_ids):
            failures.append(
                f"{task['task_id']}: cross-site customers are not completed work"
            )
        completed_demand = float(execution["completed_demand"])
        if not math.isfinite(completed_demand) or completed_demand < -TOL:
            failures.append(f"{task['task_id']}: completed demand is invalid")
    full_day_solution = payload.get("full_day_solution")
    full_day_nodes = payload.get("full_day_instance_nodes")
    if not isinstance(full_day_solution, Mapping):
        failures.append(f"{task['task_id']}: full-day replay solution is missing")
    elif isinstance(execution, Mapping) and execution.get("solution_sha256") != canonical_sha256(
        full_day_solution
    ):
        failures.append(f"{task['task_id']}: full-day replay solution hash differs")
    if not isinstance(full_day_nodes, list) or not full_day_nodes:
        failures.append(f"{task['task_id']}: full-day replay node set is missing")
    return failures


def _task_envelope(
    contract_sha256: str,
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": TASK_SCHEMA,
        "contract_sha256": contract_sha256,
        "task": dict(task),
        "status": "completed",
        "completed_at_utc": _now_utc(),
        "payload_sha256": canonical_sha256(payload),
        "payload": payload,
    }


def _load_task_checkpoint(
    path: Path,
    contract_sha256: str,
    task: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskCheckpointError(f"cannot read task checkpoint {path}: {exc}") from exc
    if envelope.get("schema") != TASK_SCHEMA:
        raise TaskCheckpointError(f"task checkpoint schema differs: {path}")
    if envelope.get("contract_sha256") != contract_sha256:
        raise ContractMismatchError(f"task checkpoint contract differs: {path}")
    if envelope.get("task") != dict(task) or envelope.get("status") != "completed":
        raise TaskCheckpointError(f"task checkpoint identity differs: {path}")
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise TaskCheckpointError(f"task checkpoint payload is missing: {path}")
    if envelope.get("payload_sha256") != canonical_sha256(payload):
        raise TaskCheckpointError(f"task checkpoint payload hash differs: {path}")
    failures = validate_task_payload(task, payload)
    if failures:
        raise TaskCheckpointError("; ".join(failures))
    return dict(payload)


def _save_task_checkpoint(
    path: Path,
    contract_sha256: str,
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> None:
    atomic_write_json(path, _task_envelope(contract_sha256, task, payload))


def run_or_resume_tasks(
    output: Path,
    contract: Mapping[str, Any],
    *,
    evaluations: int,
    workers: int,
) -> list[dict[str, Any]]:
    tasks = _expected_tasks(evaluations)
    expected_paths = {_task_path(output, task) for task in tasks}
    task_dir = output / ".tasks"
    if task_dir.exists():
        unexpected = {
            path
            for path in task_dir.glob("*.json")
            if not path.name.startswith("._") and path not in expected_paths
        }
        if unexpected:
            raise ContractMismatchError(
                f"unexpected task checkpoints exist: {sorted(map(str, unexpected))}"
            )
    contract_sha256 = str(contract["contract_sha256"])
    payloads: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for task in tasks:
        path = _task_path(output, task)
        if path.is_file():
            payloads[str(task["task_id"])] = _load_task_checkpoint(
                path, contract_sha256, task
            )
        else:
            pending.append(task)
    if pending:
        pool = ProcessPoolExecutor(max_workers=min(workers, len(pending)))
        futures = {pool.submit(_run_task, task): task for task in pending}
        try:
            for future in as_completed(futures):
                task = futures[future]
                payload = future.result()
                failures = validate_task_payload(task, payload)
                _save_task_checkpoint(
                    _task_path(output, task), contract_sha256, task, payload
                )
                if failures:
                    raise TaskCheckpointError("; ".join(failures))
                payloads[str(task["task_id"])] = payload
        except BaseException:
            for future in futures:
                future.cancel()
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)
    return [payloads[str(task["task_id"])] for task in tasks]


def validate_complete_matrix(
    payloads: Sequence[Mapping[str, Any]], evaluations: int
) -> list[str]:
    failures: list[str] = []
    expected = {
        (network, condition, stream, arm)
        for network in NETWORKS
        for condition in CONDITIONS
        for stream in STREAMS
        for arm in ARMS
    }
    observed = {
        (
            str(payload.get("network")),
            str(payload.get("responsibility_condition")),
            int(payload.get("stream_seed", -1)),
            str(payload.get("arm")),
        )
        for payload in payloads
    }
    if observed != expected or len(payloads) != len(expected):
        failures.append("condition-by-stream-by-arm matrix is incomplete")
    by_network_condition_stream: dict[tuple[str, str, int], list[Mapping[str, Any]]] = {}
    for payload in payloads:
        task = {
            "task_id": task_id(
                str(payload.get("network")),
                str(payload.get("responsibility_condition")),
                int(payload.get("stream_seed", -1)),
                str(payload.get("arm")),
            ),
            "network": payload.get("network"),
            "condition": payload.get("responsibility_condition"),
            "stream": payload.get("stream_seed"),
            "arm": payload.get("arm"),
            "evaluations": evaluations,
        }
        failures.extend(validate_task_payload(task, payload))
        key = (
            str(payload.get("network")),
            str(payload.get("responsibility_condition")),
            int(payload.get("stream_seed", -1)),
        )
        by_network_condition_stream.setdefault(key, []).append(payload)
    for key, group in by_network_condition_stream.items():
        route_hashes = {
            str(payload.get("initial_timing", {}).get("route_sha256"))
            for payload in group
        }
        energy_hashes = {
            str(payload.get("initial_timing", {}).get("energy_sha256"))
            for payload in group
        }
        event_hashes = {str(payload.get("event_sha256")) for payload in group}
        owner_hashes = {str(payload.get("owner_sha256")) for payload in group}
        stage_counts = {
            (int(payload.get("available_stages", -1)), int(payload.get("stages", -1)))
            for payload in group
        }
        if len(route_hashes) != 1 or len(energy_hashes) != 1:
            failures.append(f"{key}: arms did not share route and energy starts")
        if len(event_hashes) != 1 or len(owner_hashes) != 1:
            failures.append(f"{key}: arms did not share frozen inputs")
        if len(stage_counts) != 1:
            failures.append(f"{key}: arms completed different stage counts")
    for network in NETWORKS:
      for stream in STREAMS:
        event_hashes = {
            str(payload.get("event_sha256"))
            for payload in payloads
            if payload.get("network") == network
            if int(payload.get("stream_seed", -1)) == stream
        }
        if len(event_hashes) != 1:
            failures.append(
                f"{network} stream {stream}: conditions did not share one event stream"
            )
    return sorted(set(failures))


def build_session_summaries(
    payloads: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        stages = list(payload["rows"])
        final = payload["final_running"]
        execution = payload["full_day_execution"]
        depot_profit = {str(key): float(value) for key, value in final["depot_profit"].items()}
        rows.append(
            {
                "network": payload["network"],
                "responsibility_condition": payload["responsibility_condition"],
                "stream_seed": int(payload["stream_seed"]),
                "arm": payload["arm"],
                "completed_stage_count": int(payload["stages"]),
                "full_day_total_revenue": float(final["total_revenue"]),
                "full_day_total_cost": float(final["total_cost"]),
                "full_day_net_profit": float(final["total_profit"]),
                "full_day_actual_total_emissions_kg": float(
                    final["total_actual_emissions_kg"]
                ),
                "full_day_predicted_total_emissions_kg": float(
                    final["direct_emissions_kg"]
                    + final["predicted_charging_emissions_kg"]
                ),
                "full_day_depot_profit_json": json.dumps(
                    depot_profit, ensure_ascii=False, sort_keys=True
                ),
                "full_day_completed_customer_count": int(
                    execution["completed_customer_count"]
                ),
                "full_day_completed_demand": float(execution["completed_demand"]),
                "full_day_cross_site_customer_count": int(
                    execution["cross_site_customer_count"]
                ),
                "full_day_execution_solution_sha256": execution["solution_sha256"],
                "minimum_stage_bilateral_profit_ratio": min(
                    float(row["minimum_profit_ratio"]) for row in stages
                ),
                "feasible_cross_candidate_count": sum(
                    int(row["feasible_cross_candidate_count"]) for row in stages
                ),
            }
        )
    network_order = {value: index for index, value in enumerate(NETWORKS)}
    order = {value: index for index, value in enumerate(CONDITIONS)}
    arm_order = {value: index for index, value in enumerate(ARMS)}
    return sorted(
        rows,
        key=lambda row: (
            network_order[str(row["network"])],
            order[str(row["responsibility_condition"])],
            int(row["stream_seed"]),
            arm_order[str(row["arm"])],
        ),
    )


def build_group_summaries(
    session_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in session_rows:
        key = (
            str(row["network"]),
            str(row["responsibility_condition"]),
            str(row["arm"]),
        )
        groups.setdefault(key, []).append(row)
    summaries: list[dict[str, Any]] = []
    for network in NETWORKS:
      for condition in CONDITIONS:
        for arm in ARMS:
            rows = groups.get((network, condition, arm), [])
            if len(rows) != len(STREAMS):
                raise TaskCheckpointError(
                    f"group {(network, condition, arm)} does not contain all streams"
                )
            profits = [float(row["full_day_net_profit"]) for row in rows]
            emissions = [
                float(row["full_day_actual_total_emissions_kg"]) for row in rows
            ]
            ratios = [
                float(row["minimum_stage_bilateral_profit_ratio"]) for row in rows
            ]
            cross = [
                int(row["full_day_cross_site_customer_count"]) for row in rows
            ]
            summaries.append(
                {
                    "network": network,
                    "responsibility_condition": condition,
                    "arm": arm,
                    "stream_count": len(rows),
                    "full_day_net_profit_mean": sum(profits) / len(profits),
                    "full_day_net_profit_min": min(profits),
                    "full_day_net_profit_max": max(profits),
                    "full_day_actual_total_emissions_kg_mean": sum(emissions)
                    / len(emissions),
                    "full_day_actual_total_emissions_kg_min": min(emissions),
                    "full_day_actual_total_emissions_kg_max": max(emissions),
                    "minimum_stage_bilateral_profit_ratio": min(ratios),
                    "full_day_cross_site_customer_count_sum": sum(cross),
                    "full_day_cross_site_customer_count_mean": sum(cross)
                    / len(cross),
                    "feasible_cross_candidate_count_sum": sum(
                        int(row["feasible_cross_candidate_count"]) for row in rows
                    ),
                }
            )
    return summaries


def build_policy_comparisons(
    session_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    indexed = {
        (
            str(row["network"]),
            str(row["responsibility_condition"]),
            int(row["stream_seed"]),
            str(row["arm"]),
        ): row
        for row in session_rows
    }
    comparisons: list[dict[str, Any]] = []
    for network in NETWORKS:
      for condition in CONDITIONS:
        for stream in STREAMS:
            full = indexed[(network, condition, stream, "full")]
            independent = indexed[(network, condition, stream, "no_cooperation")]
            simple = indexed[(network, condition, stream, "simple_insertion")]
            unconstrained = indexed[(network, condition, stream, "no_participation")]
            full_depots = json.loads(str(full["full_day_depot_profit_json"]))
            independent_depots = json.loads(
                str(independent["full_day_depot_profit_json"])
            )
            unconstrained_depots = json.loads(
                str(unconstrained["full_day_depot_profit_json"])
            )
            depot_ids = sorted(full_depots)
            if set(depot_ids) != {"D0", "D1"} or set(depot_ids) != set(
                independent_depots
            ) or set(depot_ids) != set(unconstrained_depots):
                raise TaskCheckpointError(
                    f"{(condition, stream)} depot profit ledgers differ"
                )
            participation_margins = {
                depot: float(full_depots[depot])
                - float(independent_depots[depot])
                for depot in depot_ids
            }
            participation_ratios = {
                depot: (
                    float(full_depots[depot]) / float(independent_depots[depot])
                    if float(independent_depots[depot]) > TOL
                    else None
                )
                for depot in depot_ids
            }
            rows = {
                "network": network,
                "responsibility_condition": condition,
                "stream_seed": stream,
                "full_minus_no_cooperation_net_profit": float(
                    full["full_day_net_profit"]
                )
                - float(independent["full_day_net_profit"]),
                "full_minus_no_cooperation_revenue": float(
                    full["full_day_total_revenue"]
                )
                - float(independent["full_day_total_revenue"]),
                "full_minus_no_cooperation_cost": float(full["full_day_total_cost"])
                - float(independent["full_day_total_cost"]),
                "full_minus_no_cooperation_completed_customer_count": int(
                    full["full_day_completed_customer_count"]
                )
                - int(independent["full_day_completed_customer_count"]),
                "full_minus_no_cooperation_completed_demand": float(
                    full["full_day_completed_demand"]
                )
                - float(independent["full_day_completed_demand"]),
                "full_day_participation_margin_d0": participation_margins.get("D0"),
                "full_day_participation_margin_d1": participation_margins.get("D1"),
                "full_day_participation_ratio_d0": participation_ratios.get("D0"),
                "full_day_participation_ratio_d1": participation_ratios.get("D1"),
                "full_day_participation_floor_met": all(
                    value >= -TOL for value in participation_margins.values()
                ),
                "simple_insertion_minus_full_actual_total_emissions_kg": float(
                    simple["full_day_actual_total_emissions_kg"]
                )
                - float(full["full_day_actual_total_emissions_kg"]),
                "simple_insertion_minus_full_predicted_total_emissions_kg": float(
                    simple["full_day_predicted_total_emissions_kg"]
                )
                - float(full["full_day_predicted_total_emissions_kg"]),
                "full_minus_simple_insertion_completed_customer_count": int(
                    full["full_day_completed_customer_count"]
                )
                - int(simple["full_day_completed_customer_count"]),
                "full_minus_simple_insertion_completed_demand": float(
                    full["full_day_completed_demand"]
                )
                - float(simple["full_day_completed_demand"]),
                "full_minus_no_participation_system_cost": float(
                    full["full_day_total_cost"]
                )
                - float(unconstrained["full_day_total_cost"]),
                "full_minus_no_participation_net_profit": float(
                    full["full_day_net_profit"]
                )
                - float(unconstrained["full_day_net_profit"]),
                "full_minus_no_participation_profit_d0": float(full_depots["D0"])
                - float(unconstrained_depots["D0"]),
                "full_minus_no_participation_profit_d1": float(full_depots["D1"])
                - float(unconstrained_depots["D1"]),
                "full_minus_no_participation_completed_customer_count": int(
                    full["full_day_completed_customer_count"]
                )
                - int(unconstrained["full_day_completed_customer_count"]),
                "full_minus_no_participation_completed_demand": float(
                    full["full_day_completed_demand"]
                )
                - float(unconstrained["full_day_completed_demand"]),
                "full_minimum_stage_bilateral_profit_ratio": float(
                    full["minimum_stage_bilateral_profit_ratio"]
                ),
                "no_participation_minimum_stage_bilateral_profit_ratio": float(
                    unconstrained["minimum_stage_bilateral_profit_ratio"]
                ),
            }
            comparisons.append(rows)
    return comparisons


def build_comparison_summaries(
    comparisons: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    numeric_fields = (
        "full_minus_no_cooperation_net_profit",
        "simple_insertion_minus_full_actual_total_emissions_kg",
        "simple_insertion_minus_full_predicted_total_emissions_kg",
        "full_minus_no_participation_system_cost",
        "full_minus_no_participation_net_profit",
    )
    result: list[dict[str, Any]] = []
    for network in NETWORKS:
      for condition in CONDITIONS:
        rows = [
            row
            for row in comparisons
            if row["network"] == network
            if row["responsibility_condition"] == condition
        ]
        if len(rows) != len(STREAMS):
            raise TaskCheckpointError(
                f"paired comparison for {(network, condition)} does not contain all streams"
            )
        summary: dict[str, Any] = {
            "network": network,
            "responsibility_condition": condition,
            "stream_count": len(rows),
            "full_day_participation_floor_met_count": sum(
                bool(row["full_day_participation_floor_met"]) for row in rows
            ),
        }
        for field in numeric_fields:
            values = [float(row[field]) for row in rows]
            summary[f"{field}_mean"] = sum(values) / len(values)
            summary[f"{field}_min"] = min(values)
            summary[f"{field}_max"] = max(values)
        result.append(summary)
    return result


def _artifact_hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and ".tmp-" not in path.name
    }


def verify_completed_output(output: Path, contract_sha256: str) -> dict[str, Any] | None:
    marker = output / "RUN_FINISHED.json"
    hashes_path = output / "artifact_hashes.json"
    if not marker.is_file() or not hashes_path.is_file():
        return None
    finished = json.loads(marker.read_text(encoding="utf-8"))
    if finished.get("contract_sha256") != contract_sha256:
        raise ContractMismatchError("completion marker belongs to another contract")
    hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
    current_hashes = _artifact_hashes(output)
    if current_hashes != hashes:
        changed = sorted(set(current_hashes) ^ set(hashes))
        for relative in sorted(set(current_hashes) & set(hashes)):
            if current_hashes[relative] != hashes[relative]:
                changed.append(relative)
        raise TaskCheckpointError(
            f"completed artifact inventory or hash differs: {sorted(set(changed))}"
        )
    decision = json.loads((output / "decision.json").read_text(encoding="utf-8"))
    return decision


def write_final_evidence(
    output: Path,
    contract: Mapping[str, Any],
    payloads: Sequence[Mapping[str, Any]],
    *,
    evaluations: int,
    workers: int,
    started_at_utc: str,
    elapsed_seconds: float,
) -> dict[str, Any]:
    failures = validate_complete_matrix(payloads, evaluations)
    stage_rows = [row for payload in payloads for row in payload["rows"]]
    session_rows = build_session_summaries(payloads)
    group_rows = build_group_summaries(session_rows)
    policy_comparisons = build_policy_comparisons(session_rows)
    comparison_summaries = build_comparison_summaries(policy_comparisons)
    verdict = (
        "E7_FORMAL_EVIDENCE_COMPLETE"
        if not failures
        else "HALT_E7_FORMAL_EVIDENCE"
    )
    metadata = {
        "schema": RUN_SCHEMA,
        "contract_id": CONTRACT_ID,
        "contract_sha256": contract["contract_sha256"],
        "source_commit_at_start": contract.get("source_commit_at_start"),
        "source_commit_at_finish": git_head(),
        "started_at_utc": started_at_utc,
        "finished_at_utc": _now_utc(),
        "elapsed_seconds": elapsed_seconds,
        "workers": workers,
        "evaluations_per_search_call": evaluations,
        "task_count": len(payloads),
        "stage_row_count": len(stage_rows),
        "networks": list(NETWORKS),
        "conditions": list(CONDITIONS),
        "streams": list(STREAMS),
        "arms": list(ARMS),
        "physical_rules": contract["physical_rules"],
        "input_file_hashes": contract["input_file_hashes"],
        "source_file_hashes": contract["source_file_hashes"],
        "interpretation_boundary": (
            "This package reports every frozen condition, stream, and arm. It does "
            "not decide a paper claim or select results by direction. Full-day policy "
            "comparisons use net profit because completed work and therefore revenue "
            "may differ after dynamic cancellations; timing-comparison rows are not "
            "summed across stages because future plans overlap. Cross-site counts come "
            "from the merged full-day execution ledger, not the last future plan."
        ),
    }
    decision = {
        "verdict": verdict,
        "failures": failures,
        "mechanical_checks": {
            "expected_task_count": len(NETWORKS) * len(CONDITIONS) * len(STREAMS) * len(ARMS),
            "observed_task_count": len(payloads),
            "all_conditions_complete": {
                condition: sum(
                    payload["responsibility_condition"] == condition
                    for payload in payloads
                )
                == len(NETWORKS) * len(STREAMS) * len(ARMS)
                for condition in CONDITIONS
            },
            "all_streams_complete": {
                str(stream): sum(
                    int(payload["stream_seed"]) == stream for payload in payloads
                )
                == len(NETWORKS) * len(CONDITIONS) * len(ARMS)
                for stream in STREAMS
            },
            "equal_budget_and_shared_start_pass": not any(
                "budget" in failure or "start" in failure for failure in failures
            ),
            "customer_accounting_pass": not any(
                "customer accounting" in failure for failure in failures
            ),
            "predicted_charging_nonworsening_pass": not any(
                "predicted" in failure for failure in failures
            ),
        },
        "summary_file": "summary_by_condition_arm.csv",
        "paired_comparison_file": "paired_policy_comparisons.csv",
        "scientific_interpretation_status": "PENDING_INDEPENDENT_AUDIT",
        "result_direction_used_for_inclusion": False,
    }
    atomic_write_csv(output / "raw_runs.csv", stage_rows)
    atomic_write_json(output / "sessions.json", list(payloads))
    atomic_write_csv(output / "session_summary.csv", session_rows)
    atomic_write_csv(output / "summary_by_condition_arm.csv", group_rows)
    atomic_write_csv(output / "paired_policy_comparisons.csv", policy_comparisons)
    atomic_write_csv(
        output / "paired_policy_comparison_summary.csv", comparison_summaries
    )
    atomic_write_json(output / "metadata.json", metadata)
    atomic_write_json(output / "decision.json", decision)
    report = [
        "# E7正式运行证据包",
        "",
        f"运行状态：`{verdict}`。",
        "",
        f"三个网络、两种客户责任情形、五条冻结订单流和四组方案共{len(payloads)}个任务。除顺序插单基线仅保留一次可行性核验外，每个阶段先形成同状态、禁跨场的继续经营方案，再用相同次数比较被检验方案；全部任务均原样进入汇总，不按结果方向筛选。",
        "",
        "`session_summary.csv`逐网络、逐订单流报告全日经营净收益、总排放、阶段内最低双方收益比、完成客户与货量以及全日累计跨场客户数；`summary_by_condition_arm.csv`按网络、责任情形和方案汇总五条订单流。`paired_policy_comparisons.csv`逐网络、逐情形、逐订单流给出完整方案相对禁止合作、顺序插单和不设参与底线方案的差值。低碳充电与有空即充的28日同路线零搜索核算另由独立证据包报告。",
        "",
        "相邻阶段的未来计划重叠，阶段充电差值不累加为全日减排。动态取消可能使最终完成工作量和收入不同，因此经济比较使用经营净收益，并同时保留收入、成本、完成客户数和完成货量。全日双方参与情况直接把完整方案与同情形、同订单流的禁止合作方案逐场比较，不以阶段内同状态保底替代。",
        "",
        "本报告只说明正式证据是否完整，不给出论文结论。",
    ]
    if failures:
        report.extend(["", "未通过项：" + "；".join(failures)])
    _atomic_write_text(output / "report.md", "\n".join(report) + "\n")
    marker = {
        "schema": "setp.e7.formal.finished.v1",
        "contract_sha256": contract["contract_sha256"],
        "verdict": verdict,
        "finished_at_utc": _now_utc(),
        "task_count": len(payloads),
    }
    atomic_write_json(output / "RUN_FINISHED.json", marker)
    atomic_write_json(output / "artifact_hashes.json", _artifact_hashes(output))
    return decision


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evaluations",
        type=int,
        required=True,
        help="frozen evaluations per search call; must be chosen by the timing gate",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.evaluations <= 0:
        parser.error("--evaluations must be positive")
    if args.workers <= 0 or args.workers > 8:
        parser.error("--workers must be between 1 and 8; use 6-8 when resources allow")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    import time

    args = parse_args(argv)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    started_at_utc = _now_utc()
    started = time.perf_counter()
    try:
        verify_probe_capability()
        requested_contract = build_contract(args.evaluations)
        contract = ensure_contract(
            output,
            requested_contract,
            source_commit_at_start=git_head(),
        )
        completed = verify_completed_output(
            output, str(contract["contract_sha256"])
        )
        if completed is not None:
            print(json.dumps(completed, ensure_ascii=False, indent=2))
            return 0 if not completed.get("failures") else 2
        payloads = run_or_resume_tasks(
            output,
            contract,
            evaluations=args.evaluations,
            workers=args.workers,
        )
        current_contract = build_contract(args.evaluations)
        comparable_contract = {
            key: value
            for key, value in contract.items()
            if key != "source_commit_at_start"
        }
        if current_contract != comparable_contract:
            raise ContractMismatchError(
                "source code or frozen inputs changed while the formal run was active"
            )
        decision = write_final_evidence(
            output,
            contract,
            payloads,
            evaluations=args.evaluations,
            workers=min(args.workers, len(payloads)),
            started_at_utc=started_at_utc,
            elapsed_seconds=time.perf_counter() - started,
        )
    except FormalRunError as exc:
        print(
            json.dumps(
                {"verdict": "HALT_E7_FORMAL_RUNNER", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not decision["failures"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
