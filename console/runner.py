"""Execute planned jobs (dry-run safe by default)."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import abs_under, resolve_repo_root
from .registry import Job


@dataclass
class JobResult:
    job_id: str
    experiment: str
    artifact: str
    kind: str
    status: str
    message: str = ""
    outputs: list[str] = field(default_factory=list)
    seconds: float = 0.0


def ensure_io_tree(repo: Path, params: dict[str, Any]) -> dict[str, Path]:
    paths = params.get("paths") or {}
    input_root = abs_under(repo, paths.get("input_root", "input"))
    output_root = abs_under(repo, paths.get("output_root", "output"))
    for sub in (
        "instances",
        "configs",
        "styles",
        "data_csv",
        "data_json",
        "data_xlsx",
        "data_other",
    ):
        (input_root / sub).mkdir(parents=True, exist_ok=True)
    for exp in ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "PAPER"):
        (output_root / "by_experiment" / exp).mkdir(parents=True, exist_ok=True)
    for kind in ("tables", "figures", "logs", "raw_csv", "reports", "checkpoints"):
        (output_root / "by_type" / kind).mkdir(parents=True, exist_ok=True)
    return {"input_root": input_root, "output_root": output_root}


def formal_instance_names(params: dict[str, Any]) -> list[str]:
    inst = params.get("instances") or {}
    sizes = inst.get("sizes") or [10, 15, 20, 25, 50, 75, 100, 150, 200]
    donor = str(inst.get("donor", "01"))
    template = str(inst.get("name_template", "L-main-threeshift-{size}c-{donor}"))
    return [template.format(size=s, donor=donor) for s in sizes]


def preflight(repo: Path, params: dict[str, Any]) -> list[str]:
    """Return human-readable preflight messages; raise on hard failures."""
    notes: list[str] = []
    paths = params.get("paths") or {}
    formal_root = abs_under(repo, paths.get("formal_instances_root", "models/data_bundle/generated_instances/L-main"))
    if not formal_root.is_dir():
        notes.append(f"WARN formal_instances_root missing: {formal_root}")
    else:
        missing = []
        for name in formal_instance_names(params):
            if not (formal_root / name).is_dir():
                missing.append(name)
        if missing:
            notes.append(f"WARN missing formal instances ({len(missing)}): {', '.join(missing[:5])}...")
        else:
            notes.append(f"OK formal 9-step threeshift present under {formal_root}")

    safety = params.get("safety") or {}
    for rel in safety.get("never_modify") or []:
        p = abs_under(repo, rel)
        if not p.is_file():
            notes.append(f"WARN protected file missing: {rel}")
        else:
            notes.append(f"OK protected: {rel}")

    runtime = params.get("runtime") or {}
    py = runtime.get("python") or sys.executable
    notes.append(f"runtime.python={py}")
    notes.append(f"host={platform.node()} platform={platform.platform()}")
    return notes


def _job_output_dirs(repo: Path, params: dict[str, Any], job: Job) -> dict[str, Path]:
    paths = params.get("paths") or {}
    output_root = abs_under(repo, paths.get("output_root", "output"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    exp_dir = output_root / "by_experiment" / job.experiment / f"{job.artifact}_{stamp}"
    exp_dir.mkdir(parents=True, exist_ok=True)
    kind_dir = output_root / "by_type" / ("tables" if job.kind == "table" else "figures" if job.kind == "figure" else "reports")
    kind_dir.mkdir(parents=True, exist_ok=True)
    log_dir = output_root / "by_type" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return {"exp_dir": exp_dir, "kind_dir": kind_dir, "log_dir": log_dir}


def run_job(repo: Path, params: dict[str, Any], job: Job, *, dry_run: bool) -> JobResult:
    t0 = time.perf_counter()
    outs = _job_output_dirs(repo, params, job)
    plan_path = outs["exp_dir"] / "job_plan.json"
    instances = list(job.instances) if job.instances else formal_instance_names(params)
    plan = {
        "job_id": job.job_id,
        "experiment": job.experiment,
        "artifact": job.artifact,
        "kind": job.kind,
        "instances": instances,
        "dry_run": dry_run,
        "algorithm_main": (params.get("algorithms") or {}).get("main"),
        "runtime": params.get("runtime"),
        "figures": params.get("figures"),
        "tables": params.get("tables"),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    if dry_run:
        stub = outs["exp_dir"] / "DRY_RUN.txt"
        stub.write_text(
            f"Dry-run only. Planned {job.experiment}/{job.artifact} on {len(instances)} instance(s).\n"
            f"Set CONTROL_CONSOLE.yaml dry_run: false to execute hooks.\n",
            encoding="utf-8",
        )
        # mirror pointer into by_type
        pointer = outs["kind_dir"] / f"{job.experiment}_{job.artifact}_latest_plan.json"
        pointer.write_text(plan_path.read_text(encoding="utf-8"), encoding="utf-8")
        return JobResult(
            job_id=job.job_id,
            experiment=job.experiment,
            artifact=job.artifact,
            kind=job.kind,
            status="DRY_RUN",
            message=f"planned {len(instances)} instances",
            outputs=[str(plan_path), str(stub), str(pointer)],
            seconds=time.perf_counter() - t0,
        )

    # Live hooks: dispatch by experiment. Keep failures explicit.
    try:
        produced = _dispatch_live(repo, params, job, instances, outs)
        return JobResult(
            job_id=job.job_id,
            experiment=job.experiment,
            artifact=job.artifact,
            kind=job.kind,
            status="OK",
            message="live hook finished",
            outputs=[str(plan_path), *produced],
            seconds=time.perf_counter() - t0,
        )
    except NotImplementedError as exc:
        note = outs["exp_dir"] / "HOOK_NOT_IMPLEMENTED.md"
        note.write_text(
            f"# Hook not implemented\n\n{job.experiment}/{job.artifact}\n\n{exc}\n",
            encoding="utf-8",
        )
        return JobResult(
            job_id=job.job_id,
            experiment=job.experiment,
            artifact=job.artifact,
            kind=job.kind,
            status="NOT_IMPLEMENTED",
            message=str(exc),
            outputs=[str(plan_path), str(note)],
            seconds=time.perf_counter() - t0,
        )
    except Exception as exc:  # noqa: BLE001 — surface to console decision log
        err = outs["exp_dir"] / "ERROR.txt"
        err.write_text(traceback.format_exc(), encoding="utf-8")
        return JobResult(
            job_id=job.job_id,
            experiment=job.experiment,
            artifact=job.artifact,
            kind=job.kind,
            status="ERROR",
            message=str(exc),
            outputs=[str(plan_path), str(err)],
            seconds=time.perf_counter() - t0,
        )


def _dispatch_live(
    repo: Path,
    params: dict[str, Any],
    job: Job,
    instances: list[str],
    outs: dict[str, Path],
) -> list[str]:
    """Live execution hooks.

    Currently implements a lightweight self-check smoke for E2/T3 that imports
    the independent ALNS package. Heavy formal runners remain explicit opt-in
    via future handlers to avoid accidental multi-hour runs from one-click.
    """
    produced: list[str] = []
    if job.experiment == "E2" and job.artifact in {"T3", "F2"}:
        return _e2_smoke_import(repo, params, job, instances, outs)
    raise NotImplementedError(
        f"No live handler for {job.experiment}/{job.artifact} yet. "
        "Use dry_run: true for planning, or extend console/runner.py handlers."
    )


def _e2_smoke_import(
    repo: Path,
    params: dict[str, Any],
    job: Job,
    instances: list[str],
    outs: dict[str, Path],
) -> list[str]:
    runtime = params.get("runtime") or {}
    py = str(runtime.get("python") or sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(abs_under(repo, (params.get("paths") or {}).get("solver_src", "solver/src"))) + os.pathsep + env.get(
        "PYTHONPATH", ""
    )
    env["PYTHONHASHSEED"] = str(runtime.get("pythonhashseed", "0"))
    code = (
        "from setp_solver.algorithms.resetp_alns import run_winner_kernel, WinnerKernelConfig; "
        "print('ALNS_OK', callable(run_winner_kernel), WinnerKernelConfig)"
    )
    proc = subprocess.run([py, "-c", code], cwd=str(repo), env=env, capture_output=True, text=True, check=False)
    report = outs["exp_dir"] / "e2_import_smoke.txt"
    report.write_text(
        f"returncode={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}\ninstances={instances}\n",
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"E2 import smoke failed: {proc.stderr or proc.stdout}")
    pointer = outs["kind_dir"] / f"{job.experiment}_{job.artifact}_import_smoke.txt"
    pointer.write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
    return [str(report), str(pointer)]


def write_run_report(repo: Path, params: dict[str, Any], results: list[JobResult], meta: dict[str, Any]) -> Path:
    paths = params.get("paths") or {}
    log_dir = abs_under(repo, paths.get("logs_dir", "output/by_type/logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = log_dir / f"control_console_run_{stamp}.json"
    payload = {
        "schema": "resetp-control-console-run.v1",
        "meta": meta,
        "results": [asdict(r) for r in results],
        "summary": {
            "total": len(results),
            "ok": sum(1 for r in results if r.status == "OK"),
            "dry_run": sum(1 for r in results if r.status == "DRY_RUN"),
            "not_implemented": sum(1 for r in results if r.status == "NOT_IMPLEMENTED"),
            "error": sum(1 for r in results if r.status == "ERROR"),
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = log_dir / "control_console_run_latest.json"
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path
