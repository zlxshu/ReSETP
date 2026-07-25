"""Shared frozen-input and artifact helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import resource
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from setp_solver.china81 import load_china81_bundle
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
REGISTRATION = PACKAGE / "g0_registration_v1.json"
ENGINEERING = PACKAGE / "engineering_gate_v1"
OUTPUT = PACKAGE / "g0_gate_v1"
AUTHORITY = (
    REPO
    / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
    / "g0_real_bundle_preregistration_v1.json"
)
V7_ROOT = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
    / "full_gate"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.name.startswith("._")
        and path.name != "artifact_hashes.json"
        and not any(part in {"__pycache__", ".pytest_cache"} for part in path.parts)
    }


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload["routes"]],
        charging_actions=[
            ChargingAction(**row) for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row) for row in payload.get("cross_site_services", [])
        ],
    )


def solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [
            asdict(action) for action in solution.charging_actions
        ],
        "cross_site_services": [
            asdict(service) for service in solution.cross_site_services
        ],
    }


def load_bundle(instance_id: str) -> Any:
    authority = read_json(AUTHORITY)
    inputs = authority["authorities"]
    return load_china81_bundle(
        REPO,
        instance_id,
        date=authority["scenario_date"],
        static_input_authority=inputs["static_inputs"]["path"],
        road_matrix_authority=inputs["road_matrices"]["path"],
        runtime_parameter_authority=inputs["runtime_parameters"]["path"],
        fleet_authority=inputs["finite_fleet"]["path"],
    )


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    if registration["status"] != "FROZEN_BEFORE_ENGINEERING_AND_G0":
        raise RuntimeError("registration status is not frozen")
    for relative, expected in registration["source_hashes"].items():
        path = REPO / relative
        if not path.exists() or sha256(path) != expected:
            raise RuntimeError(f"registered source drift: {relative}")
    authority = registration["authority"]
    if sha256(REPO / authority["path"]) != authority["sha256"]:
        raise RuntimeError("authority registration drift")
    for spec in registration["inputs"]:
        for parent in spec["parents"]:
            path = REPO / parent["witness_path"]
            if sha256(path) != parent["witness_sha256"]:
                raise RuntimeError(
                    f"witness drift: {spec['instance_id']} seed {parent['seed']}"
                )
    return registration


def load_registered_solutions(
    spec: dict[str, Any],
) -> tuple[Solution, tuple[Solution, ...]]:
    parents: list[Solution] = []
    start: Solution | None = None
    for parent in spec["parents"]:
        payload = read_json(REPO / parent["witness_path"])
        solution = load_solution(payload[parent["witness_key"]])
        parents.append(solution)
        if int(parent["seed"]) == int(spec["start_seed"]):
            start = solution
    if start is None:
        raise RuntimeError("registered start witness is missing")
    return start, tuple(parents)


def set_single_thread_environment() -> None:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[name] = "1"


def peak_rss_bytes() -> int:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(raw) if sys.platform == "darwin" else int(raw) * 1024


def memory_snapshot() -> dict[str, float]:
    """Return a conservative macOS/Linux available-memory snapshot."""

    if sys.platform == "darwin":
        total = int(
            subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"],
                text=True,
            ).strip()
        )
        text = subprocess.check_output(["vm_stat"], text=True)
        page_size = 4096
        if "page size of" in text.splitlines()[0]:
            page_size = int(text.split("page size of", 1)[1].split("bytes", 1)[0])
        values: dict[str, int] = {}
        for line in text.splitlines()[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            values[name.strip()] = int(value.strip().rstrip("."))
        available_pages = sum(
            values.get(name, 0)
            for name in (
                "Pages free",
                "Pages inactive",
                "Pages speculative",
                "Pages purgeable",
            )
        )
        available = available_pages * page_size
    else:
        rows = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, value = line.split(":", 1)
            rows[name] = int(value.strip().split()[0]) * 1024
        total = rows["MemTotal"]
        available = rows["MemAvailable"]
    return {
        "total_bytes": float(total),
        "available_bytes": float(available),
        "available_percent": 100.0 * float(available) / float(total),
    }

