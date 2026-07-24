#!/usr/bin/env python3
"""Zero-search six-worker resource probe for the genuine-hybrid G1 gate."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, wait
from time import perf_counter
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
REGISTRATION = PACKAGE / "g1_six_worker_resource_probe_registration_v1.json"
OUT = PACKAGE / "g1_six_worker_resource_probe_v1"
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

for key, value in THREAD_ENV.items():
    os.environ[key] = value

for path in (
    REPO,
    REPO / "solver/src",
    REPO / "models/src",
    REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720",
    PACKAGE,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def memory_free_percent() -> int:
    output = subprocess.check_output(
        ["memory_pressure", "-Q"],
        text=True,
    )
    marker = "System-wide memory free percentage:"
    for line in output.splitlines():
        if line.startswith(marker):
            return int(line.removeprefix(marker).strip().rstrip("%"))
    raise RuntimeError("cannot read macOS memory pressure percentage")


def peak_rss_mb() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw / (1024.0 * 1024.0) if sys.platform == "darwin" else raw / 1024.0


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    if (
        registration.get("schema")
        != "resetp.genuine-hybrid-g1-worker-probe-registration.v1"
    ):
        raise RuntimeError("unexpected worker-probe registration schema")
    if registration.get("status") != "FROZEN_BEFORE_G1_RESULTS":
        raise RuntimeError("worker-probe registration status drift")
    for relative, expected in registration["source_hashes"].items():
        path = REPO / str(relative)
        if not path.is_file():
            raise RuntimeError(f"worker-probe source missing: {relative}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"worker-probe source hash mismatch: {relative}:{expected}:{actual}"
            )
    return registration


def run_probe_task(spec: dict[str, Any]) -> dict[str, Any]:
    import run_g0_real_bundle_preflight as g0

    registration = g0.load_preregistration()
    registered = next(
        row
        for row in registration["instances"]
        if row["instance_id"] == spec["instance_id"]
    )
    started = perf_counter()
    row = g0.run_instance(registered, registration)
    return {
        "task_id": spec["task_id"],
        "instance_id": spec["instance_id"],
        "replicate": spec["replicate"],
        "status": row["status"],
        "elapsed_seconds": perf_counter() - started,
        "peak_rss_mb": peak_rss_mb(),
        "detail": row["detail"],
    }


def execute() -> int:
    registration = verify_registration()
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite worker probe: {OUT}")
    OUT.mkdir(parents=True)
    specs = [
        {
            "task_id": f"{instance['instance_id']}__replicate{replicate}",
            "instance_id": instance["instance_id"],
            "replicate": replicate,
        }
        for instance in registration["instances"]
        for replicate in (1, 2)
    ]
    before = memory_free_percent()
    minimum = before
    results: list[dict[str, Any]] = []
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=6, mp_context=context) as pool:
        pending = {pool.submit(run_probe_task, spec) for spec in specs}
        while pending:
            done, pending = wait(pending, timeout=1.0)
            for future in done:
                results.append(future.result())
            minimum = min(minimum, memory_free_percent())
    after = memory_free_percent()
    results.sort(key=lambda row: row["task_id"])
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(results[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(results)

    all_pass = len(results) == 6 and all(row["status"] == "PASS" for row in results)
    aggregate_peak = sum(float(row["peak_rss_mb"]) for row in results)
    pass_resource = (
        all_pass
        and minimum >= int(registration["minimum_memory_free_percent"])
        and aggregate_peak <= float(registration["maximum_aggregate_peak_rss_mb"])
    )
    decision = {
        "schema": "resetp.genuine-hybrid-g1-worker-probe-decision.v1",
        "decision": (
            "PASS_G1_SIX_WORKERS_RESOURCE_PROBE"
            if pass_resource
            else "FALLBACK_G1_THREE_WORKERS"
        ),
        "all_six_tasks_passed": all_pass,
        "memory_free_percent_before": before,
        "minimum_memory_free_percent": minimum,
        "memory_free_percent_after": after,
        "aggregate_worker_peak_rss_mb": aggregate_peak,
        "maximum_aggregate_peak_rss_mb": registration["maximum_aggregate_peak_rss_mb"],
        "search_iterations": 0,
        "objective_values_disclosed": False,
        "claim_boundary": registration["claim_boundary"],
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.genuine-hybrid-g1-worker-probe-metadata.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO,
                text=True,
            ).strip(),
            "platform": platform.platform(),
            "python": sys.version,
            "registration_sha256": sha256(REGISTRATION),
            "thread_environment": THREAD_ENV,
            "task_count": len(results),
            "workers": 6,
            "source_hashes": registration["source_hashes"],
        },
    )
    report = "\n".join(
        [
            "# G1 six-worker resource probe",
            "",
            f"Decision: `{decision['decision']}`.",
            "",
            "Six zero-search real-bundle wiring tasks ran concurrently.",
            "No objective value is included in this resource decision.",
            "",
            f"- All tasks passed: {all_pass}",
            f"- Minimum free-memory percentage: {minimum}%",
            f"- Aggregate worker peak RSS: {aggregate_peak:.3f} MB",
            "",
            (
                "This gate only selects six or three parallel independent G1 "
                "tasks. It does not change any task's algorithm, random stream, "
                "budget, evaluator, or acceptance threshold."
            ),
            "",
        ]
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")
    targets = (
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "report.md",
    )
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": {path.name: sha256(path) for path in targets},
        },
    )
    print(decision["decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(execute())
