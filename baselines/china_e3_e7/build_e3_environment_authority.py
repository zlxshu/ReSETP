#!/usr/bin/env python3
"""Build a fail-closed formal Python/PyVRP/SciPy environment authority."""

from __future__ import annotations

import csv
import hashlib
from importlib import import_module
from importlib.metadata import distribution, version
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
# Running a script by path places its directory first on sys.path. This
# directory also contains the project post-processing module statistics.py,
# which must never shadow Python's standard-library statistics module during
# PyVRP import.
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
OUT = (
    REPO
    / "baselines/china_e3_e7/"
    "e3_environment_authority_20260723"
)
EXPECTED = {
    "pyvrp": "0.12.2",
    "numpy": "2.5.1",
    "scipy": "1.16.3",
}
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def distribution_tree_sha256(name: str) -> str:
    """Hash all installed distribution bytes except generated caches."""

    dist = distribution(name)
    prefix = Path(sys.prefix).resolve()
    rows: list[str] = []
    for relative in sorted(
        dist.files or (),
        key=lambda item: str(item),
    ):
        text = str(relative)
        if (
            "__pycache__" in relative.parts
            or text.endswith((".pyc", ".pyo"))
        ):
            continue
        path = Path(dist.locate_file(relative)).resolve()
        if not path.is_file() or not path.is_relative_to(prefix):
            continue
        rows.append(f"{text}\0{sha256(path)}")
    if not rows:
        raise RuntimeError(f"no in-prefix files for distribution {name}")
    return hashlib.sha256(
        ("\n".join(rows) + "\n").encode("utf-8")
    ).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build() -> dict[str, Any]:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite environment gate: {OUT}")
    OUT.mkdir(parents=True)
    prefix = Path(sys.prefix).resolve()
    rows: list[dict[str, Any]] = []
    for name, expected_version in EXPECTED.items():
        module = import_module(name)
        module_path = Path(module.__file__).resolve()
        observed_version = version(name)
        in_prefix = module_path.is_relative_to(prefix)
        rows.append(
            {
                "package": name,
                "expected_version": expected_version,
                "observed_version": observed_version,
                "module_path": str(module_path),
                "inside_formal_prefix": in_prefix,
                "distribution_tree_sha256": (
                    distribution_tree_sha256(name)
                    if in_prefix
                    else ""
                ),
                "status": (
                    "PASS"
                    if observed_version == expected_version and in_prefix
                    else "HALT"
                ),
            }
        )

    from scipy.optimize import (  # type: ignore[import-not-found]
        Bounds,
        LinearConstraint,
        milp,
    )
    import numpy as np

    result = milp(
        c=np.array([1.0]),
        integrality=np.array([1]),
        bounds=Bounds(np.array([0.0]), np.array([2.0])),
        constraints=[
            LinearConstraint(
                np.array([[1.0]]),
                lb=np.array([1.0]),
                ub=np.array([2.0]),
            )
        ],
    )
    milp_pass = bool(
        result.success
        and result.x is not None
        and abs(float(result.x[0]) - 1.0) <= 1.0e-12
        and abs(float(result.fun) - 1.0) <= 1.0e-12
    )
    pip_check = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    thread_pass = all(
        os.environ.get(key) == value
        for key, value in REQUIRED_THREAD_ENV.items()
    )
    package_pass = all(row["status"] == "PASS" for row in rows)
    passed = (
        package_pass
        and milp_pass
        and pip_check.returncode == 0
        and thread_pass
    )
    write_csv(OUT / "raw_runs.csv", rows)
    decision = {
        "schema": "resetp.e3-environment-authority.decision.v1",
        "verdict": (
            "PASS_E3_FORMAL_ENVIRONMENT_AUTHORITY"
            if passed
            else "HALT_E3_FORMAL_ENVIRONMENT_AUTHORITY"
        ),
        "python_executable": sys.executable,
        "python_prefix": str(prefix),
        "all_packages_inside_formal_prefix": package_pass,
        "package_tree_hashes": {
            row["package"]: row["distribution_tree_sha256"]
            for row in rows
        },
        "thread_environment_locked": thread_pass,
        "pip_check_pass": pip_check.returncode == 0,
        "milp_smoke_pass": milp_pass,
        "milp_solver": "scipy.optimize.milp/HiGHS",
        "formal_search_allowed": False,
        "search_evaluations": 0,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.e3-environment-authority.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "builder": str(Path(__file__).relative_to(REPO)),
            "builder_sha256": sha256(Path(__file__).resolve()),
            "python": sys.version,
            "platform": platform.platform(),
            "thread_environment": {
                key: os.environ.get(key)
                for key in REQUIRED_THREAD_ENV
            },
            "pip_check_output": pip_check.stdout.strip(),
        },
    )
    (OUT / "report.md").write_text(
        "# E3 formal environment authority\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        "The gate requires PyVRP, NumPy and SciPy to resolve inside the "
        "formal Python prefix, hashes their installed distribution trees, "
        "locks single-thread environment variables, runs `pip check`, and "
        "solves a one-variable integer HiGHS smoke model. It performs no "
        "ReSETP search.\n",
        encoding="utf-8",
    )
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": {
                path.name: sha256(path)
                for path in sorted(OUT.iterdir())
                if (
                    path.is_file()
                    and path.name != "artifact_hashes.json"
                    and not path.name.startswith("._")
                )
            },
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return decision


if __name__ == "__main__":
    build()
