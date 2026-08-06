#!/opt/anaconda3/bin/python3.13
"""ProcessPool-free orchestration recovery for SCOUT-D.

The frozen scientific runner remains unchanged.  This file only replaces the
blocked ``ProcessPoolExecutor`` launcher with four ordinary ``Popen`` child
processes, each of which calls the frozen runner's ``run_unit`` function.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run_scout_d as scout


RECOVERY_METADATA = HERE / "execution_recovery_metadata.json"
RECOVERY_MONITOR = HERE / "monitor_recovery.json"
OLD_MONITOR_STATUS = (
    HERE / ".scout-d-depot-ownership-20260803.monitor/status.json"
)
OLD_MONITOR_LOG = (
    HERE / ".scout-d-depot-ownership-20260803.monitor/experiment.stdout.log"
)


def recovery_payload() -> dict[str, Any]:
    return {
        "schema": "resetp.scout-d-execution-recovery.v1",
        "task_id": "SCOUT-D",
        "created_at_utc": scout.utc_now(),
        "trigger": (
            "ProcessPoolExecutor initialization failed before any HGS unit: "
            "PermissionError [Errno 1] at os.sysconf(SC_SEM_NSEMS_MAX)"
        ),
        "failed_monitor_status": (
            json.loads(OLD_MONITOR_STATUS.read_text(encoding="utf-8"))[
                "state"
            ]
        ),
        "failed_search_units": 0,
        "recovery_scope": "orchestration_only",
        "scientific_contract_changed": False,
        "recovery_launcher": (
            "four ordinary Popen children calling frozen "
            "run_scout_d.run_unit"
        ),
        "frozen_scientific_runner_sha256": scout.sha256_path(
            HERE / "run_scout_d.py"
        ),
        "frozen_metadata_sha256": scout.sha256_path(HERE / "metadata.json"),
        "recovery_launcher_sha256": scout.sha256_path(Path(__file__)),
        "recovery_monitor_sha256": scout.sha256_path(RECOVERY_MONITOR),
        "failed_monitor_status_sha256": scout.sha256_path(OLD_MONITOR_STATUS),
        "failed_experiment_log_sha256": scout.sha256_path(OLD_MONITOR_LOG),
        "unchanged_contract": {
            "instance_id": scout.INSTANCE_ID,
            "seeds": list(scout.SEEDS),
            "arms": list(scout.ARMS),
            "iterations_per_view": scout.ITERATIONS_PER_VIEW,
            "max_no_improvement_iterations_per_view": None,
            "strict_multitrip": True,
            "vehicle_fixed_cost_cny": 170.0,
            "depot_charger_capacity_mode": "unbounded",
            "fleet_authority": scout.relative(scout.FLEET_AUTHORITY),
        },
    }


def prepare_recovery() -> None:
    scout.verify_environment()
    scout.verify_frozen_sources()
    if not OLD_MONITOR_STATUS.is_file() or not OLD_MONITOR_LOG.is_file():
        raise RuntimeError("failed monitor evidence is missing")
    if RECOVERY_METADATA.exists():
        existing = json.loads(RECOVERY_METADATA.read_text(encoding="utf-8"))
        expected = recovery_payload()
        for key in (
            "scientific_contract_changed",
            "frozen_scientific_runner_sha256",
            "frozen_metadata_sha256",
            "recovery_launcher_sha256",
            "recovery_monitor_sha256",
            "failed_monitor_status_sha256",
            "failed_experiment_log_sha256",
            "unchanged_contract",
        ):
            if existing.get(key) != expected.get(key):
                raise RuntimeError(f"recovery metadata drift at {key}")
        return
    scout.write_json_atomic(
        RECOVERY_METADATA,
        recovery_payload(),
        replace_ok=False,
    )
    print("SCOUT-D orchestration recovery frozen", flush=True)


def child_command(spec: dict[str, Any]) -> list[str]:
    code = (
        "import json,sys; "
        "from run_scout_d import run_unit; "
        "row=run_unit({'seed':int(sys.argv[1]),'arm':sys.argv[2]}); "
        "print(json.dumps({'seed':row['seed'],'arm':row['arm'],"
        "'status':row['status']},sort_keys=True))"
    )
    return [
        sys.executable,
        "-c",
        code,
        str(spec["seed"]),
        str(spec["arm"]),
    ]


def consolidate(last_spec: dict[str, Any] | None = None) -> None:
    nearest = scout.add_pair_differences(scout.load_nearest_results())
    random_rows = scout.load_csv_rows(HERE / "baseline_random/raw_runs.csv")
    scout.write_csv_atomic(HERE / "baseline_nearest/raw_runs.csv", nearest)
    scout.write_csv_atomic(HERE / "raw_runs.csv", [*random_rows, *nearest])
    status: dict[str, Any] = {
        "status": "RUNNING_NEAREST_POPEN_RECOVERY",
        "completed_units": len(nearest),
        "expected_nearest_units": len(scout.task_specs()),
        "updated_at_utc": scout.utc_now(),
        "scientific_contract_changed": False,
    }
    if last_spec is not None:
        status["last_completed"] = last_spec
    scout.write_json_atomic(HERE / "status.json", status)


def run_recovery(workers: int) -> None:
    if workers < 1 or workers > 4:
        raise ValueError("recovery workers must be between 1 and 4")
    prepare_recovery()
    scout.verify_frozen_sources()
    if (HERE / "done.json").exists():
        raise FileExistsError("SCOUT-D already has terminal completion evidence")
    pending = [
        spec
        for spec in scout.task_specs()
        if scout.completed_result(spec) is None
    ]
    active: dict[subprocess.Popen[str], tuple[dict[str, Any], Any]] = {}
    consolidate()
    while pending or active:
        while pending and len(active) < workers:
            spec = pending.pop(0)
            unit_dir = scout.result_path(int(spec["seed"]), str(spec["arm"])).parent
            unit_dir.mkdir(parents=True, exist_ok=True)
            launcher_log = (unit_dir / "launcher.log").open(
                "a",
                encoding="utf-8",
            )
            process = subprocess.Popen(
                child_command(spec),
                cwd=HERE,
                env=os.environ.copy(),
                stdout=launcher_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            active[process] = (spec, launcher_log)
        completed: list[subprocess.Popen[str]] = []
        for process, (spec, launcher_log) in active.items():
            return_code = process.poll()
            if return_code is None:
                continue
            launcher_log.close()
            if return_code != 0:
                raise RuntimeError(
                    f"child launcher failed for {spec} with rc={return_code}"
                )
            result = scout.completed_result(spec)
            if result is None:
                raise RuntimeError(f"child exited without result for {spec}")
            consolidate(spec)
            print(
                f"completed seed={spec['seed']} arm={spec['arm']} "
                f"status={result['status']}",
                flush=True,
            )
            completed.append(process)
        for process in completed:
            active.pop(process)
        if active and not completed:
            time.sleep(2)
    scout.finalize()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.prepare_only:
        prepare_recovery()
    else:
        run_recovery(int(args.workers))


if __name__ == "__main__":
    main()
