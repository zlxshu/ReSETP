#!/usr/bin/env python3
"""Zero-search consistency gate for the China81 three-arm pipeline."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pyvrp_adapter import (  # noqa: E402
    _project_initial_solution,
    _translate_solution,
    build_pyvrp_problem,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    run_winner_kernel_in_memory,
)
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.model_config import legacy_model_config_from_environment  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)


INSTANCE_ID = "cn-jjj-10c-01-V2-LOCATIONS"
OUT = PACKAGE / "adapter_g0_zero_search_gate"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    _remove_appledouble(OUT)
    bundle = load_china81_bundle(ROOT, INSTANCE_ID)
    common = build_initial_solution(
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        introduce_ev=False,
        require_charging_signal=False,
    )

    direct = complete_china81_route_skeleton(common, bundle)
    problem = build_pyvrp_problem(bundle)
    projected = _project_initial_solution(
        direct.solution,
        problem.model.data(),
        problem,
        bundle,
    )
    pyvrp_roundtrip = _translate_solution(projected, problem)
    pyvrp_completion = complete_china81_route_skeleton(
        pyvrp_roundtrip,
        bundle,
    )

    alns_zero = run_winner_kernel_in_memory(
        common,
        bundle.instance,
        bundle.time_profile,
        config=WinnerKernelConfig(
            seed=1,
            eval_budget=0,
            max_runtime_seconds=0.1,
            require_charging_signal=False,
        ),
        prices=bundle.prices,
        model_config=legacy_model_config_from_environment(),
        customer_home_depot=dict(bundle.customer_home_depot),
    )
    alns_completion = complete_china81_route_skeleton(
        alns_zero.best_solution,
        bundle,
    )

    hybrid_zero = run_winner_kernel_in_memory(
        pyvrp_roundtrip,
        bundle.instance,
        bundle.time_profile,
        config=WinnerKernelConfig(
            seed=1,
            eval_budget=0,
            max_runtime_seconds=0.1,
            require_charging_signal=False,
        ),
        prices=bundle.prices,
        model_config=legacy_model_config_from_environment(),
        customer_home_depot=dict(bundle.customer_home_depot),
    )
    hybrid_completion = complete_china81_route_skeleton(
        hybrid_zero.best_solution,
        bundle,
    )

    arms = {
        "common_direct": direct,
        "pyvrp_adapter_zero_search": pyvrp_completion,
        "project_alns_zero_search": alns_completion,
        "hybrid_zero_search": hybrid_completion,
    }
    raw_rows: list[dict[str, Any]] = []
    for arm, result in arms.items():
        objective, breakdown, violations = exact_china81_score(
            result.solution,
            bundle,
        )
        raw_rows.append(
            {
                "instance_id": INSTANCE_ID,
                "arm": arm,
                "search_evaluations": 0,
                "objective": objective,
                "feasible": not violations,
                "violation_count": len(violations),
                "solution_sha256": _solution_hash(result.solution),
                "route_count": len(result.solution.routes),
                "ev_route_count": sum(
                    route.vehicle_type.lower() == "ev"
                    for route in result.solution.routes
                ),
                "charging_action_count": len(
                    result.solution.charging_actions
                ),
                "total_distance_m": breakdown["distance_total"],
                "total_emissions_kg": breakdown["E_total"],
                "mechanism_query_count": len(
                    result.activity["mechanism_experts_queried"]
                ),
            }
        )

    test_commands = [
        [
            "/opt/anaconda3/bin/python3.13",
            "-m",
            "pytest",
            "-q",
            "solver/tests/test_china81_bundle_20260720.py",
            "solver/tests/test_china81_profiled_road_matrices_nl3b_20260720.py",
            "solver/tests/test_china81_shared_completion_20260720.py",
            "solver/tests/test_china81_in_memory_winner_20260720.py",
        ],
        [
            "/opt/anaconda3/bin/ruff",
            "check",
            "solver/src/setp_solver/china81.py",
            "solver/src/setp_solver/china81_completion.py",
            "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
            str(PACKAGE.relative_to(ROOT)),
        ],
    ]
    command_results = [
        _run_command(command)
        for command in test_commands
    ]

    objectives = {round(float(row["objective"]), 9) for row in raw_rows}
    solution_hashes = {
        str(row["solution_sha256"])
        for row in raw_rows
    }
    passed = (
        len(objectives) == 1
        and len(solution_hashes) == 1
        and all(bool(row["feasible"]) for row in raw_rows)
        and all(result["returncode"] == 0 for result in command_results)
        and int(alns_zero.evaluations) == 0
        and int(hybrid_zero.evaluations) == 0
    )
    decision = {
        "schema_version": "resetp.china81-adapter-g0-decision.v1",
        "decision": (
            "PASS_CHINA81_THREE_ARM_ZERO_SEARCH_EQUIVALENCE"
            if passed
            else "HOLD_CHINA81_THREE_ARM_ZERO_SEARCH_EQUIVALENCE"
        ),
        "passed": passed,
        "instance_id": INSTANCE_ID,
        "arm_count": len(raw_rows),
        "objective_count": len(objectives),
        "solution_hash_count": len(solution_hashes),
        "all_feasible": all(bool(row["feasible"]) for row in raw_rows),
        "alns_search_evaluations": int(alns_zero.evaluations),
        "hybrid_search_evaluations": int(hybrid_zero.evaluations),
        "formal_search_allowed": False,
        "next_gate": (
            "three-arm-small-pipeline-smoke"
            if passed
            else "repair-adapter-before-any-performance-run"
        ),
    }
    metadata = {
        "schema_version": "resetp.china81-adapter-g0-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "instance_id": INSTANCE_ID,
        "purpose": (
            "Prove that direct, PyVRP-adapted, ALNS-adapted, and staged "
            "hybrid paths use the same China81 physics before search."
        ),
        "search_evaluations": 0,
        "formal_search_allowed": False,
        "completion_schema": direct.activity["schema_version"],
        "commands": command_results,
        "sources": {
            "loader": str(
                (ROOT / "solver/src/setp_solver/china81.py").relative_to(
                    ROOT
                )
            ),
            "completion": str(
                (
                    ROOT
                    / "solver/src/setp_solver/china81_completion.py"
                ).relative_to(ROOT)
            ),
            "pyvrp_adapter": str(
                (PACKAGE / "pyvrp_adapter.py").relative_to(ROOT)
            ),
            "hybrid": str((PACKAGE / "hybrid.py").relative_to(ROOT)),
        },
    }
    _write_csv(OUT / "raw_runs.csv", raw_rows)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    (OUT / "report.md").write_text(
        _report(decision, raw_rows),
        encoding="utf-8",
    )
    _remove_appledouble(OUT)
    hashes = {
        str(path.relative_to(ROOT)): _sha256(path)
        for path in sorted(
            [
                Path(__file__),
                PACKAGE / "pyvrp_adapter.py",
                PACKAGE / "hybrid.py",
                ROOT / "solver/src/setp_solver/china81.py",
                ROOT / "solver/src/setp_solver/china81_completion.py",
                ROOT
                / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
                OUT / "metadata.json",
                OUT / "raw_runs.csv",
                OUT / "decision.json",
                OUT / "report.md",
            ]
        )
    }
    _write_json(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": hashes,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if passed else 1


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


def _report(
    decision: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    objective = rows[0]["objective"]
    solution_hash = rows[0]["solution_sha256"]
    return f"""# China81 三臂适配器 G0：零搜索同值门

结论：`{decision["decision"]}`。

四条路径均从 `{INSTANCE_ID}` 的同一初始路线出发，搜索次数均为零。
直接补全、PyVRP 往返适配、项目 ALNS 适配和两阶段混合适配得到完全
相同的完整解哈希 `{solution_hash}`，完整模型成本均为
`{objective:.9f}`，且均通过同一个项目可行性检查。

这一步只证明“同一把尺”和接线正确，不证明任何算法更强。下一步只
允许做小规模三臂管道冒烟；在该门通过前不得跑 China81 性能结论。
"""


if __name__ == "__main__":
    raise SystemExit(main())
