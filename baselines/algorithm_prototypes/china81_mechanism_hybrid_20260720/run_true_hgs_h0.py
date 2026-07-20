#!/usr/bin/env python3
"""Verify the genuine PyVRP 0.12.2 HGS China81 adapter."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pyvrp


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
PREREG = PACKAGE / "h0_true_hgs_preregistration.json"
OUT = PACKAGE / "h0_true_hgs_adapter_gate"
for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pyvrp_adapter import run_pyvrp_hgs_skeleton  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)


def main() -> int:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    _remove_appledouble(PACKAGE)
    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    for instance_id in prereg["cases"]:
        bundle = load_china81_bundle(ROOT, str(instance_id))
        common = complete_china81_route_skeleton(
            build_initial_solution(
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                introduce_ev=False,
                require_charging_signal=False,
            ),
            bundle,
        )
        for mode in prereg["route_proxy_modes"]:
            run = run_pyvrp_hgs_skeleton(
                bundle,
                common.solution,
                seed=int(prereg["seed"]),
                runtime_seconds=float(prereg["seconds_per_run"]),
                route_proxy_mode=str(mode),
            )
            objective, breakdown, violations = exact_china81_score(
                run.completion.solution,
                bundle,
            )
            rows.append(
                {
                    "instance_id": instance_id,
                    "route_proxy_mode": mode,
                    "seed": prereg["seed"],
                    "runtime_seconds": prereg["seconds_per_run"],
                    "elapsed_seconds": run.elapsed_seconds,
                    "pyvrp_version": run.stats["pyvrp_version"],
                    "engine_family": run.stats["engine_family"],
                    "warm_start_supported": run.stats[
                        "warm_start_supported"
                    ],
                    "objective": objective,
                    "initial_objective": common.objective,
                    "protected_initial": objective
                    <= common.objective + 1.0e-9,
                    "feasible": not violations,
                    "violation_count": len(violations),
                    "route_count": len(run.completion.solution.routes),
                    "ev_route_count": sum(
                        route.vehicle_type.lower() == "ev"
                        for route in run.completion.solution.routes
                    ),
                    "solution_sha256": _solution_hash(
                        run.completion.solution
                    ),
                }
            )
            witnesses[f"{instance_id}::{mode}"] = {
                "stats": run.stats,
                "completion_activity": run.completion.activity,
                "solution": asdict(run.completion.solution),
                "independent_breakdown": breakdown,
            }
    tests = _test_commands()
    engine_ok = (
        version("pyvrp") == "0.12.2"
        and hasattr(pyvrp, "GeneticAlgorithm")
        and all(row["engine_family"] == "HGS" for row in rows)
    )
    all_feasible = all(bool(row["feasible"]) for row in rows)
    all_protected = all(bool(row["protected_initial"]) for row in rows)
    tests_passed = all(item["returncode"] == 0 for item in tests)
    passed = engine_ok and all_feasible and all_protected and tests_passed
    decision = {
        "schema_version": "resetp.china81-h0-true-hgs-decision.v1",
        "decision": (
            "PASS_TRUE_PYVRP_HGS_CHINA81_ADAPTER"
            if passed
            else "HOLD_TRUE_PYVRP_HGS_CHINA81_ADAPTER"
        ),
        "passed": passed,
        "engine_ok": engine_ok,
        "all_feasible": all_feasible,
        "all_initial_incumbents_protected": all_protected,
        "tests_passed": tests_passed,
        "pyvrp_version": version("pyvrp"),
        "engine_family": (
            "HGS" if hasattr(pyvrp, "GeneticAlgorithm") else "ILS"
        ),
        "run_count": len(rows),
        "objectives": {
            f"{row['instance_id']}::{row['route_proxy_mode']}": row[
                "objective"
            ]
            for row in rows
        },
        "claim_boundary": prereg["claim_boundary"],
        "next_gate": (
            "true_hgs_multiview_design"
            if passed
            else "repair_adapter_before_search"
        ),
    }
    metadata = {
        "schema_version": "resetp.china81-h0-true-hgs-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_executable": sys.executable,
        "preregistration": str(PREREG.relative_to(ROOT)),
        "preregistration_sha256": _sha256(PREREG),
        "formal_search_allowed": False,
        "test_commands": tests,
    }
    _write_csv(OUT / "raw_runs.csv", rows)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    _write_json(OUT / "solution_witnesses.json", witnesses)
    (OUT / "report.md").write_text(
        "\n".join(
            [
                "# China81 H0：真实 PyVRP HGS 接线门",
                "",
                f"机器结论：`{decision['decision']}`。",
                "",
                "本门只纠正引擎身份并验证公共完成器。PyVRP 0.12.2",
                "才是带种群、交叉和多样性管理的 HGS；0.13.4 是 ILS。",
                "九次输出均由完整 ReSETP 计分器重新检查。",
                "",
                f"边界：{decision['claim_boundary']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _remove_appledouble(PACKAGE)
    files = [
        Path(__file__),
        PREREG,
        PACKAGE / "pyvrp_adapter.py",
        ROOT / "solver/src/setp_solver/china81_completion.py",
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "solution_witnesses.json",
        OUT / "report.md",
    ]
    _write_json(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {
                str(path.relative_to(ROOT)): _sha256(path)
                for path in sorted(files)
            },
        },
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def _test_commands() -> list[dict[str, Any]]:
    return [
        _run_command(
            [
                "/opt/anaconda3/bin/python3.13",
                "-m",
                "pytest",
                "-q",
                "solver/tests/test_china81_bundle_20260720.py",
                "solver/tests/test_china81_profiled_road_matrices_nl3b_20260720.py",
                "solver/tests/test_china81_shared_completion_20260720.py",
            ]
        ),
        _run_command(
            [
                "/opt/anaconda3/bin/ruff",
                "check",
                "solver/src/setp_solver/china81.py",
                "solver/src/setp_solver/china81_completion.py",
                str(PACKAGE.relative_to(ROOT)),
            ]
        ),
    ]


def _run_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _solution_hash(solution: Any) -> str:
    payload = json.dumps(
        asdict(solution),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _remove_appledouble(path: Path) -> None:
    for sidecar in path.rglob("._*"):
        if sidecar.is_file():
            sidecar.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
