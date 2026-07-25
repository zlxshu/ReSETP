"""Frozen paths, loading, hashing, and artifact helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[2]
REGISTRATION = PACKAGE / "g0_registration_v1.json"
ENGINEERING_OUT = PACKAGE / "engineering_gate_v1"
G0_OUT = PACKAGE / "g0_gate_v1"
CONTRACT = (
    REPO
    / "docs/handoff/e2_joint_route_charge_exact_neighborhood_contract_20260725.md"
)
FORMAL_ROOT = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
    / "full_gate"
)
FLEET_ROOT = (
    REPO
    / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"
)
STATIC_ROOT = (
    REPO
    / "data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723"
)
ROAD_ROOT = (
    REPO
    / "data/ChinaInstances/china81_local_directed_matrices_corrected_v10_20260723"
)
RUNTIME_ROOT = (
    REPO
    / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
)
SCENARIO_DATE = "2025-02-12"
PYTHON = (
    REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
)


def install_import_paths() -> None:
    """Install only the frozen solver and genuine-decoder paths."""

    paths = (
        REPO / "solver/src",
        REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724",
        REPO,
    )
    for path in reversed(paths):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


install_import_paths()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def load_solution(payload: dict[str, Any]) -> Any:
    from setp_solver.solution import (
        ChargingAction,
        CrossSiteService,
        Route,
        Solution,
    )

    return Solution(
        routes=[Route(**row) for row in payload["routes"]],
        charging_actions=[
            ChargingAction(**row)
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row)
            for row in payload.get("cross_site_services", [])
        ],
    )


def solution_payload(solution: Any) -> dict[str, Any]:
    from dataclasses import asdict

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
    from setp_solver.china81 import load_china81_bundle

    return load_china81_bundle(
        REPO,
        instance_id,
        date=SCENARIO_DATE,
        static_input_authority=STATIC_ROOT,
        road_matrix_authority=ROAD_ROOT,
        runtime_parameter_authority=RUNTIME_ROOT,
        fleet_authority=FLEET_ROOT,
    )


def exact_replay(solution: Any, bundle: Any, label: str) -> float:
    from setp_solver.check import check_solution
    from setp_solver.china81_completion import exact_china81_score

    objective, _, exact_violations = exact_china81_score(solution, bundle)
    direct_violations = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    if exact_violations or direct_violations:
        raise RuntimeError(
            f"{label} infeasible: exact={len(exact_violations)}, "
            f"direct={len(direct_violations)}"
        )
    return float(objective)


def set_single_thread_environment() -> None:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[name] = "1"


def artifact_manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".monitor" not in path.parts
        and path.name != "artifact_hashes.json"
    }


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    if registration.get("schema") != "resetp.jrc-exact-nh-g0.v1":
        raise RuntimeError("unexpected registration schema")
    for relative, expected in registration["protected_sha256"].items():
        path = REPO / relative
        if not path.is_file():
            raise RuntimeError(f"protected file missing: {relative}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"protected hash drift: {relative}: {actual} != {expected}"
            )
    return registration

