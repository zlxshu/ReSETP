#!/usr/bin/env python3
"""Detached, idempotent serial driver for the 2026-08-19 synergy batch.

Role: PROJECT_DOMAIN orchestration script.  It owns scheduling and driver logs;
the existing technical runner owns experiment configuration and result content.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
REPORT_ROOT = REPO / "solver/reports/synergy_formal_20260819"
DRIVER_LOG = REPORT_ROOT / "driver.log"
PYTHON = Path("/opt/anaconda3/bin/python3.13")
RUNNER = Path("solver/scripts/run_problem_hgs_private_technical.py")
LOG_LOCK = threading.Lock()
STOP = threading.Event()


@dataclass(frozen=True)
class Unit:
    name: str
    output: Path
    seed: int
    enterprise_id: str | None


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(line: str) -> None:
    with LOG_LOCK:
        DRIVER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DRIVER_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{now()} {line}\n")
            handle.flush()
            os.fsync(handle.fileno())


def accepted(output: Path) -> bool:
    try:
        return json.loads((output / "decision.json").read_text())["accepted"] is True
    except (FileNotFoundError, KeyError, json.JSONDecodeError, TypeError):
        return False


def units() -> list[Unit]:
    result: list[Unit] = []
    for enterprise_id in ("ENT_A", "ENT_B"):
        for seed in range(1, 11):
            output = REPORT_ROOT / "standalone" / enterprise_id / f"seed_{seed}"
            result.append(Unit(f"standalone/{enterprise_id}/seed_{seed}", output, seed, enterprise_id))
    for seed in range(1, 11):
        output = REPORT_ROOT / "joint" / f"seed_{seed}"
        result.append(Unit(f"joint/seed_{seed}", output, seed, None))
    return result


def command(unit: Unit, *, runtime_seconds: int = 600) -> list[str]:
    try:
        output_arg = str(unit.output.relative_to(REPO))
    except ValueError:
        output_arg = str(unit.output)
    argv = [
        str(PYTHON), str(RUNNER), output_arg,
        "--instance-id", "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd",
    ]
    if unit.enterprise_id is not None:
        argv += ["--enterprise-id", unit.enterprise_id]
    argv += [
        "--seed", str(unit.seed), "--carbon-price", "0.07502",
        "--iterations", "1000000000", "--max-runtime-seconds", str(runtime_seconds),
        "--stagnation-patience", "500",
        "--fleet-parameter-class", "endogenous", "--population-mode", "copied_hgs_defaults",
        "--trajectory", "off", "--charge-timing-policy", "cost_plus_carbon",
        "--frvcpy-charging",
        "--run-kind", "formal",
        "--arm", (f"synergy_formal_standalone_{unit.enterprise_id}" if unit.enterprise_id else "synergy_formal_joint"),
        "--stderr-capture-state", "combined_stdout_stderr_in_unit_log",
    ]
    return argv


def runner_environment() -> dict[str, str]:
    environment = os.environ.copy()
    required = "solver/src:models/src:third_party/setp_hgs_kernel:."
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = f"{required}:{existing}" if existing else required
    return environment


def write_failure_package(unit: Unit, reason: str, exit_code: int) -> None:
    unit.output.mkdir(parents=True, exist_ok=True)
    decision = unit.output / "decision.json"
    if not decision.exists():
        decision.write_text(json.dumps({"accepted": False, "failure_reason": reason}, indent=2) + "\n")
    metadata = unit.output / "metadata.json"
    if not metadata.exists():
        metadata.write_text(json.dumps({
            "status": "FAILED", "unit": unit.name, "random_seed": unit.seed,
            "fairness_enabled": False if unit.enterprise_id is None else None,
            "driver_failure_reason": reason, "exit_code": exit_code,
        }, indent=2) + "\n")
    raw = unit.output / "raw_runs.csv"
    if not raw.exists():
        with raw.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["unit", "seed", "exit_code", "accepted", "failure_reason"])
            writer.writerow([unit.name, unit.seed, exit_code, False, reason])
    report = unit.output / "report.md"
    if not report.exists():
        report.write_text(f"# Failed unit\n\n- Unit: `{unit.name}`\n- Exit code: `{exit_code}`\n- Reason: {reason}\n")
def validate_joint(unit: Unit, *, require_accepted: bool = True) -> str | None:
    if unit.enterprise_id is not None or (require_accepted and not accepted(unit.output)):
        return None
    try:
        value = json.loads((unit.output / "metadata.json").read_text())["fairness_enabled"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError, TypeError):
        return "accepted joint package lacks readable fairness_enabled"
    return None if value is False else f"joint fairness_enabled is {value!r}, expected False"


def prepare_output(unit: Unit) -> Path:
    if unit.output.exists():
        relative = unit.output.relative_to(REPORT_ROOT)
        archive = REPORT_ROOT / "interrupted_before_driver" / relative
        if archive.exists():
            archive = archive.with_name(f"{archive.name}_{int(time.time())}")
        archive.parent.mkdir(parents=True, exist_ok=True)
        unit.output.rename(archive)
    side_log = REPORT_ROOT / ".driver_unit_logs" / f"{unit.name.replace('/', '__')}.log"
    side_log.parent.mkdir(parents=True, exist_ok=True)
    return side_log


def run_unit(unit: Unit) -> tuple[str, bool, int, float, str | None]:
    if STOP.is_set():
        return unit.name, False, -2, 0.0, "batch halted before start"
    side_log = prepare_output(unit)
    started = time.monotonic()
    log(f"unit={unit.name} event=START exit_code=- wall_seconds=0")
    with side_log.open("a", encoding="utf-8") as output_log:
        completed = subprocess.run(command(unit), cwd=REPO, env=runner_environment(), stdin=subprocess.DEVNULL,
                                   stdout=output_log, stderr=subprocess.STDOUT, check=False)
    if unit.output.exists():
        with side_log.open("rb") as source, (unit.output / "unit.log").open("ab") as destination:
            shutil.copyfileobj(source, destination)
    wall = time.monotonic() - started
    fairness_error = validate_joint(unit)
    ok = completed.returncode == 0 and accepted(unit.output) and fairness_error is None
    reason = fairness_error
    if not ok and reason is None:
        reason = f"runner exit_code={completed.returncode}, accepted={accepted(unit.output)}"
    if not ok:
        write_failure_package(unit, reason or "unknown failure", completed.returncode)
    if fairness_error is not None:
        STOP.set()
    log(f"unit={unit.name} event=END exit_code={completed.returncode} wall_seconds={wall:.3f} status={'SUCCESS' if ok else 'FAILED'}")
    return unit.name, ok, completed.returncode, wall, reason


def run_probe() -> int:
    probe_output = Path(os.environ.get("TMPDIR", "/tmp")) / f"resetp_synergy_driver_probe_{os.getpid()}"
    probe = Unit("probe/joint/seed_1", probe_output, 1, None)
    probe_log = probe.output.with_suffix(".log")
    with probe_log.open("a", encoding="utf-8") as output_log:
        completed = subprocess.run(command(probe, runtime_seconds=1), cwd=REPO, env=runner_environment(), stdin=subprocess.DEVNULL,
                                   stdout=output_log, stderr=subprocess.STDOUT, check=False)
    fairness_error = validate_joint(probe, require_accepted=False)
    print(json.dumps({"probe_output": str(probe.output), "exit_code": completed.returncode,
                      "accepted": accepted(probe.output), "fairness_error": fairness_error}))
    return 0 if completed.returncode == 0 and fairness_error is None else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help="run one 1-second joint probe under TMPDIR")
    args = parser.parse_args()
    if args.probe:
        return run_probe()
    missing = [unit for unit in units() if not accepted(unit.output)]
    log(f"batch event=START missing={len(missing)} workers=1")
    results = [run_unit(unit) for unit in missing]
    success = sum(ok for _, ok, _, _, _ in results)
    failed = len(results) - success
    skipped_after_halt = sum(code == -2 for _, _, code, _, _ in results)
    summary = {"finished_at": now(), "initial_missing": len(missing), "success": success,
               "failed": failed, "skipped_after_halt": skipped_after_halt, "results": results}
    (REPORT_ROOT / "driver_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    log(f"batch event=END success={success} failed={failed} skipped_after_halt={skipped_after_halt}")
    return 1 if STOP.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(main())
