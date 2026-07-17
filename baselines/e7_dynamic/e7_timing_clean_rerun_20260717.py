#!/usr/bin/env python3
"""Rerun only the nine E7 stages contaminated by the recorded external SIGSTOP.

The historical parent and child packages are read-only.  Four contaminated
tasks are rerun with the registered parent probe and five with the already
registered child probe.  Each checkpoint keeps its original contract lineage;
this runner never assembles or overwrites the formal package.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baselines.e7_dynamic import audit_e7_external_pause_timing_20260716 as timing_audit
from baselines.e7_dynamic import e7_formal_resumable_runner_20260715 as formal


PARENT_OUTPUT = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
CHILD_OUTPUT = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_recovery_child_20260716"
OUTPUT = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_timing_clean_rerun_20260717"
INCIDENT = ROOT / "baselines/e7_dynamic/monitor_configs/e7_external_pause_incident_20260716.json"
PROBE_RELATIVE = "baselines/e7_dynamic/e7_full_mechanism_probe_20260714.py"
PARENT_PROBE_COMMIT = "17df1cd255acd0b5846a06d683a520aa46a8cdbf"
PARENT_PROBE_SHA256 = "0212c344024f95c9d13f7226f7b9ac7cfaab11f9e4244577d8191d37b5a629ed"
CHILD_PROBE_SHA256 = "8b2de29659a1460020f3be4ad50cf34baa0b4badc340fbe31ceb98b6c288959f"
PARENT_CONTRACT_SHA256 = "bffdc512b8b39fe5c11bb80b63204a39f2a529d7810741354c401644cc3be16f"
CHILD_CONTRACT_SHA256 = "b703492d88d5a4db69f4302c709767871a8743ddef853e7be1d8b4ca956c0721"
EXPECTED_PAUSE_SECONDS = 13934.0
EXPECTED_EVALUATIONS = 50
EXPECTED_WORKERS = 6

PARENT_CONTAMINATED = {
    "N322__geographic__stream2__full",
    "N322__geographic__stream2__no_cooperation",
    "N322__geographic__stream2__no_participation",
    "N322__geographic__stream2__simple_insertion",
}
CHILD_CONTAMINATED = {
    "N322__geographic__stream5__no_cooperation",
    "N322__historical_mixed__stream2__full",
    "N322__historical_mixed__stream2__no_cooperation",
    "N322__historical_mixed__stream2__no_participation",
    "N322__historical_mixed__stream2__simple_insertion",
}


class RerunContractError(RuntimeError):
    """The evidence-preserving rerun cannot be safely performed."""


_PROBES: dict[str, types.ModuleType] = {}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(payload: Any) -> str:
    return sha256_bytes(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RerunContractError(f"JSON object required: {path}")
    return value


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_file(commit: str, relative: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), "show", f"{commit}:{relative}"],
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        raise RerunContractError(
            f"cannot recover registered source {commit}:{relative}: "
            f"{exc.output.decode(errors='replace')}"
        ) from exc


def load_probe(lineage: str) -> types.ModuleType:
    """Load a frozen probe with repository-root semantics and no worktree edit."""
    if lineage in _PROBES:
        return _PROBES[lineage]
    if lineage == "parent":
        source = git_file(PARENT_PROBE_COMMIT, PROBE_RELATIVE)
        expected = PARENT_PROBE_SHA256
    elif lineage == "child":
        source = (ROOT / PROBE_RELATIVE).read_bytes()
        expected = CHILD_PROBE_SHA256
    else:
        raise RerunContractError(f"unknown lineage: {lineage}")
    if sha256_bytes(source) != expected:
        raise RerunContractError(f"{lineage} probe source hash differs")
    module = types.ModuleType(f"setp_e7_registered_{lineage}_probe")
    module.__file__ = str(ROOT / PROBE_RELATIVE)
    module.__package__ = "baselines.e7_dynamic"
    exec(compile(source, str(ROOT / PROBE_RELATIVE), "exec"), module.__dict__)
    _PROBES[lineage] = module
    return module


def verify_contract(
    contract: Mapping[str, Any], expected_contract_sha: str, lineage: str
) -> None:
    if contract.get("contract_sha256") != expected_contract_sha:
        raise RerunContractError(f"{lineage} contract hash differs")
    source_hashes = dict(contract.get("source_file_hashes", {}))
    expected_probe = PARENT_PROBE_SHA256 if lineage == "parent" else CHILD_PROBE_SHA256
    if source_hashes.get(PROBE_RELATIVE) != expected_probe:
        raise RerunContractError(f"{lineage} contract probe hash differs")
    for relative, expected in source_hashes.items():
        path = ROOT / relative
        actual = (
            sha256_bytes(git_file(PARENT_PROBE_COMMIT, relative))
            if lineage == "parent" and relative == PROBE_RELATIVE
            else sha256(path) if path.is_file() else None
        )
        if actual != expected:
            raise RerunContractError(
                f"{lineage} protected source drift: {relative}: "
                f"expected {expected}, got {actual}"
            )
    for relative, expected in dict(contract.get("input_file_hashes", {})).items():
        path = ROOT / relative
        actual = sha256(path) if path.is_file() else None
        if actual != expected:
            raise RerunContractError(
                f"{lineage} protected input drift: {relative}: "
                f"expected {expected}, got {actual}"
            )


def snapshot_task_dir(root: Path) -> dict[str, str]:
    task_dir = root / ".tasks"
    paths = sorted(path for path in task_dir.glob("*.json") if not path.name.startswith("._"))
    return {str(path.relative_to(root)): sha256(path) for path in paths}


def verify_historical_package(parent_contract: Mapping[str, Any], child_contract: Mapping[str, Any]) -> dict[str, str]:
    manifest = read_json(PARENT_OUTPUT / "artifact_hashes.json")
    if formal._artifact_hashes(PARENT_OUTPUT) != manifest:
        raise RerunContractError("historical formal artifact manifest has drifted")
    parent_tasks = snapshot_task_dir(PARENT_OUTPUT)
    child_tasks = snapshot_task_dir(CHILD_OUTPUT)
    if len(parent_tasks) != 102 or len(child_tasks) != 18:
        raise RerunContractError(
            f"historical checkpoint inventory differs: parent={len(parent_tasks)}, child={len(child_tasks)}"
        )
    return {
        **{f"parent/{key}": value for key, value in parent_tasks.items()},
        **{f"child/{key}": value for key, value in child_tasks.items()},
    }


def identify_contaminated_tasks() -> tuple[dict[str, Any], float, list[dict[str, Any]]]:
    incident = read_json(INCIDENT)
    pause = float(incident.get("pause_duration_seconds", 0.0))
    if abs(pause - EXPECTED_PAUSE_SECONDS) > 1e-6:
        raise RerunContractError(f"pause duration differs: {pause}")
    sessions = json.loads((PARENT_OUTPUT / "sessions.json").read_text(encoding="utf-8"))
    stages = timing_audit.contaminated_stages(sessions, pause)
    observed_ids = {str(item["task_id"]) for item in stages}
    expected_ids = PARENT_CONTAMINATED | CHILD_CONTAMINATED
    if observed_ids != expected_ids:
        raise RerunContractError(
            f"contaminated identities differ: expected {sorted(expected_ids)}, got {sorted(observed_ids)}"
        )
    lineage_by_id: dict[str, str] = {}
    with (PARENT_OUTPUT / "task_lineage.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            lineage_by_id[str(row["task_id"])] = str(row["lineage"])
    for task_id in expected_ids:
        expected_lineage = "parent" if task_id in PARENT_CONTAMINATED else "child"
        if lineage_by_id.get(task_id) != expected_lineage:
            raise RerunContractError(f"historical lineage differs for {task_id}")
    tasks = {str(task["task_id"]): dict(task) for task in formal._expected_tasks(EXPECTED_EVALUATIONS)}
    return incident, pause, [
        {**dict(stage), "lineage": lineage_by_id[str(stage["task_id"])]}
        for stage in stages
    ]


def task_path(root: Path, task: Mapping[str, Any]) -> Path:
    return root / ".tasks" / f"{task['task_id']}.json"


def without_elapsed(value: Any) -> Any:
    """Remove only wall-clock measurements before comparing same-contract payloads."""
    if isinstance(value, Mapping):
        return {
            str(key): without_elapsed(item)
            for key, item in value.items()
            if str(key) != "elapsed_seconds"
        }
    if isinstance(value, list):
        return [without_elapsed(item) for item in value]
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def ensure_output_contracts(parent_path: Path, child_path: Path) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "rerun_contracts.json"
    payload = {
        "schema": "setp.e7.timing_clean_rerun.contracts.v1",
        "parent": read_json(parent_path),
        "child": read_json(child_path),
    }
    expected = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if target.is_file():
        if target.read_text(encoding="utf-8") != expected:
            raise RerunContractError("timing-clean contract snapshot differs")
        return
    visible = [item for item in OUTPUT.iterdir() if not item.name.startswith("._")]
    if visible:
        raise RerunContractError("timing-clean output is non-empty without contracts")
    target.write_text(expected, encoding="utf-8")


def run_one(task: Mapping[str, Any], lineage: str) -> dict[str, Any]:
    probe = load_probe(lineage)
    try:
        return probe.run_probe_arm(
            str(task["arm"]),
            condition=str(task["condition"]),
            stream_seed=int(task["stream"]),
            evaluations=int(task["evaluations"]),
            max_stages=int(task["max_stages"]),
            network=str(task["network"]),
        )
    except probe.base.NoExecutableContinuation as exc:
        events, _, event_path, owner_path = probe._stream_for_condition(
            int(task["stream"]), str(task["condition"]), str(task["network"])
        )
        batches = probe._validated_multinetwork_trigger_batches(
            str(task["network"]), int(task["stream"]), events
        )
        return {
            "execution_status": "HALT_NO_EXECUTABLE_CONTINUATION",
            "network": task["network"],
            "arm": task["arm"],
            "responsibility_condition": task["condition"],
            "stream_seed": task["stream"],
            "available_stages": len(batches),
            "stages": int(exc.completed_stage_count),
            "rows": [],
            "failed_stage": exc.stage,
            "failed_trigger_second": exc.trigger_second,
            "failure_error": str(exc),
            "evaluations": int(task["evaluations"]),
            "event_path": str(event_path.relative_to(ROOT)),
            "event_sha256": sha256(event_path),
            "owner_path": str(owner_path.relative_to(ROOT)),
            "owner_sha256": sha256(owner_path),
        }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise RerunContractError("PYTHONHASHSEED must be exactly 0")
    if args.evaluations != EXPECTED_EVALUATIONS or args.workers != EXPECTED_WORKERS:
        raise RerunContractError("rerun requires exactly 50 evaluations and 6 workers")

    parent_contract_path = PARENT_OUTPUT / "contract.json"
    child_contract_path = CHILD_OUTPUT / "contract.json"
    parent_contract = read_json(parent_contract_path)
    child_contract = read_json(child_contract_path)
    verify_contract(parent_contract, PARENT_CONTRACT_SHA256, "parent")
    verify_contract(child_contract, CHILD_CONTRACT_SHA256, "child")
    if {
        key: value for key, value in parent_contract.items()
        if key not in {"contract_sha256", "source_file_hashes", "source_commit_at_start"}
    } != {
        key: value for key, value in child_contract.items()
        if key not in {"contract_sha256", "source_file_hashes", "source_commit_at_start"}
    }:
        raise RerunContractError("parent and child contracts differ beyond the scheduler source")
    verify_historical_package(parent_contract, child_contract)
    incident, pause, contaminated = identify_contaminated_tasks()
    ensure_output_contracts(parent_contract_path, child_contract_path)

    lineage_by_id = {str(item["task_id"]): str(item["lineage"]) for item in contaminated}
    task_by_id = {str(task["task_id"]): dict(task) for task in formal._expected_tasks(args.evaluations)}
    tasks = [task_by_id[task_id] for task_id in sorted(lineage_by_id)]
    before_all = verify_historical_package(parent_contract, child_contract)
    pending: list[tuple[dict[str, Any], str]] = []
    payloads: dict[str, dict[str, Any]] = {}
    contract_by_lineage = {"parent": PARENT_CONTRACT_SHA256, "child": CHILD_CONTRACT_SHA256}
    historical_payloads: dict[str, dict[str, Any]] = {}
    historical_roots = {"parent": PARENT_OUTPUT, "child": CHILD_OUTPUT}
    for task in tasks:
        task_id = str(task["task_id"])
        lineage = lineage_by_id[task_id]
        historical_payloads[task_id] = formal._load_task_checkpoint(
            task_path(historical_roots[lineage], task), contract_by_lineage[lineage], task
        )
        path = task_path(OUTPUT, task)
        if path.is_file():
            payloads[task_id] = formal._load_task_checkpoint(path, contract_by_lineage[lineage], task)
        else:
            pending.append((task, lineage))

    started_at = now_utc()
    started = time.perf_counter()
    if pending:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(run_one, task, lineage): (task, lineage)
                for task, lineage in pending
            }
            for future in as_completed(futures):
                task, lineage = futures[future]
                payload = future.result()
                failures = formal.validate_task_payload(task, payload)
                if failures:
                    raise RerunContractError("; ".join(failures))
                formal._save_task_checkpoint(
                    task_path(OUTPUT, task), contract_by_lineage[lineage], task, payload
                )
                payloads[str(task["task_id"])] = dict(payload)
    if set(payloads) != set(lineage_by_id):
        raise RerunContractError("timing-clean rerun did not close all nine task identities")

    semantic_mismatches: list[str] = []
    contaminated_timing_failures: list[str] = []
    for task_id, payload in sorted(payloads.items()):
        if payload.get("execution_status") != "PASS":
            semantic_mismatches.append(f"{task_id}: rerun did not return PASS")
            continue
        for row in payload.get("rows", []):
            if float(row.get("elapsed_seconds", float("inf"))) >= pause:
                contaminated_timing_failures.append(
                    f"{task_id}/stage{row.get('stage')}: elapsed_seconds >= pause"
                )
        if canonical_sha256(without_elapsed(payload)) != canonical_sha256(
            without_elapsed(historical_payloads[task_id])
        ):
            semantic_mismatches.append(
                f"{task_id}: non-timing payload differs from the same-contract historical payload"
            )
    if contaminated_timing_failures:
        raise RerunContractError("; ".join(contaminated_timing_failures))
    if semantic_mismatches:
        raise RerunContractError("; ".join(semantic_mismatches))

    after_all = verify_historical_package(parent_contract, child_contract)
    if after_all != before_all:
        raise RerunContractError("historical parent/child checkpoints changed")
    checkpoint_hashes = {
        task_id: sha256(task_path(OUTPUT, task_by_id[task_id]))
        for task_id in sorted(payloads)
    }
    result = {
        "schema": "setp.e7.timing_clean_rerun.v1",
        "status": "PASS_E7_TIMING_CLEAN_RERUN_COMPLETE",
        "started_at_utc": started_at,
        "finished_at_utc": now_utc(),
        "elapsed_seconds": time.perf_counter() - started,
        "evaluations": args.evaluations,
        "workers": args.workers,
        "parent_contract_sha256": PARENT_CONTRACT_SHA256,
        "child_contract_sha256": CHILD_CONTRACT_SHA256,
        "parent_probe_commit": PARENT_PROBE_COMMIT,
        "parent_probe_sha256": PARENT_PROBE_SHA256,
        "child_probe_sha256": CHILD_PROBE_SHA256,
        "incident_sha256": sha256(INCIDENT),
        "pause_duration_seconds": pause,
        "contaminated_stage_count": len(contaminated),
        "contaminated_stages": contaminated,
        "task_ids": sorted(payloads),
        "task_lineage": lineage_by_id,
        "task_checkpoint_sha256": checkpoint_hashes,
        "historical_checkpoint_inventory_before": before_all,
        "historical_checkpoint_inventory_after": after_all,
        "historical_packages_unchanged": before_all == after_all,
        "result_direction_used_for_inclusion": False,
        "replacement_reason": "external_pause_timing_contamination",
        "semantic_non_timing_match": True,
        "all_new_stage_elapsed_below_pause": True,
        "output_root": str(OUTPUT.relative_to(ROOT)),
    }
    write_json(OUTPUT / "RERUN_FINISHED.json", result)
    write_json(
        OUTPUT / "rerun_manifest.json",
        {
            **result,
            "payload_sha256": {
                task_id: canonical_sha256(payload)
                for task_id, payload in sorted(payloads.items())
            },
        },
    )
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluations", type=int, default=EXPECTED_EVALUATIONS)
    parser.add_argument("--workers", type=int, default=EXPECTED_WORKERS)
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        answer = run(parse_args())
    except Exception as exc:
        print(f"HALT_E7_TIMING_CLEAN_RERUN: {exc}", file=sys.stderr)
        raise
    print(json.dumps(answer, ensure_ascii=False, indent=2, sort_keys=True))
