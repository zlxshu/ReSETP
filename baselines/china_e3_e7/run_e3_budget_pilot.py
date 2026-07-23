#!/usr/bin/env python3
"""Run the preregistered result-blind E3 budget throughput pilot.

The pilot intentionally does not serialize, compare, or branch on any
objective value. It observes only candidate-attempt accounting, completion
success/failure counts, elapsed time, MIP status class, and safety-cap state.
"""

from __future__ import annotations

import csv
import hashlib
from importlib.metadata import version
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pyvrp  # noqa: E402
from route_pool_sp import run_hgs_route_pool_recombination  # noqa: E402
import numpy  # noqa: E402
import scipy  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.solution import Route, Solution  # noqa: E402


OUT = (
    REPO
    / "baselines/china_e3_e7/"
    "e3_budget_pilot_v3_20260723"
)
FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
CONTRACT = (
    REPO
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v4_20260723.json"
)
INSTANCES = (
    "cn-prd-10c-01-V2-LOCATIONS",
    "cn-prd-75c-01-V2-LOCATIONS",
    "cn-prd-200c-01-V2-LOCATIONS",
)
ARMS = (
    ("status_quo_responsibility", True),
    ("optimized_responsibility_cooperation", False),
)
SEED = 1
PILOT_HGS_ITERATIONS_PER_VIEW = 100
ARCHIVE_CANDIDATES_PER_VIEW = 24
EXACT_ELITES_PER_VIEW = 8
EXPECTED_COMPLETE_BUDGET = 80
MIP_SECONDS = 5.0
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


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _load_initial(instance_id: str) -> Solution:
    payload = json.loads(
        (FLEET / "witnesses" / f"{instance_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return Solution(
        routes=[
            Route(
                vehicle_id=row["vehicle_id"],
                vehicle_type=row["vehicle_type"],
                home_depot_id=row["home_depot_id"],
                node_sequence=list(row["node_sequence"]),
            )
            for row in payload["routes"]
        ]
    )


def _finalize_existing_partial_pilot() -> dict[str, Any]:
    """Finish metadata after a post-run packaging-only interruption."""

    raw_path = OUT / "raw_runs.csv"
    decision_path = OUT / "decision.json"
    if (
        not raw_path.is_file()
        or not decision_path.is_file()
        or (OUT / "metadata.json").exists()
    ):
        raise RuntimeError(f"refusing to overwrite pilot: {OUT}")
    with raw_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if (
        len(rows) != len(INSTANCES) * len(ARMS)
        or any(row["status"] != "PASS" for row in rows)
        or decision.get("verdict") != "PASS_RESULT_BLIND_BUDGET_80"
    ):
        raise RuntimeError("partial pilot is not safe to finalize")
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.china-e3-budget-pilot.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "builder": str(Path(__file__).relative_to(REPO)),
            "python": sys.version,
            "platform": platform.platform(),
            "pyvrp_version": version("pyvrp"),
            "numpy_version": numpy.__version__,
            "numpy_path": str(Path(numpy.__file__).resolve()),
            "scipy_version": scipy.__version__,
            "scipy_path": str(Path(scipy.__file__).resolve()),
            "thread_environment": {
                key: os.environ.get(key)
                for key in REQUIRED_THREAD_ENV
            },
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    Path(__file__).resolve(),
                    CONTRACT,
                    PROTOTYPE / "pyvrp_adapter.py",
                    PROTOTYPE / "epochal_hgs.py",
                    PROTOTYPE / "route_pool_sp.py",
                    REPO / "solver/src/setp_solver/china81.py",
                    REPO / "solver/src/setp_solver/cost.py",
                    REPO / "solver/src/setp_solver/check.py",
                    FLEET / "artifact_hashes.json",
                )
            },
            "formal_search_allowed": False,
            "pilot_search_only": True,
            "packaging_resume": (
                "metadata-only resume after pyvrp version attribute error; "
                "raw pilot tasks were not rerun"
            ),
        },
    )
    (OUT / "report.md").write_text(
        "# E3 完整候选预算 result-blind pilot\n\n"
        "预注册的 6 个 pilot 单元均完整消费 80 次候选提交，墙钟安全上限"
        "均未触发。预算选择器未记录、读取或比较任何目标函数值，只使用"
        "候选提交数、补全成功/失败数、耗时与 MIP 状态。首次封装在全部"
        "任务完成后因 PyVRP 版本字段接口差异中止；本次仅补写 metadata、"
        "report 和哈希，未重跑任何任务。正式结果搜索仍未放行。\n",
        encoding="utf-8",
    )
    artifacts: dict[str, str] = {}
    for path in sorted(OUT.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        ):
            artifacts[str(path.relative_to(OUT))] = sha256(path)
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    return decision


def build() -> dict[str, Any]:
    if OUT.exists():
        return _finalize_existing_partial_pilot()
    if any(os.environ.get(key) != value for key, value in REQUIRED_THREAD_ENV.items()):
        raise RuntimeError("single-thread environment is not fully locked")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    prereg = contract["formal_execution"]["budget_pilot"]
    if (
        prereg["instances"] != list(INSTANCES)
        or prereg["seed"] != SEED
        or prereg["objective_values_visible_to_selector"] is not False
    ):
        raise RuntimeError("machine pilot preregistration disagrees")
    OUT.mkdir(parents=True)

    raw_rows: list[dict[str, Any]] = []
    for instance_id in INSTANCES:
        bundle = load_china81_bundle(REPO, instance_id)
        customer_count = sum(
            node.node_type.lower() == "c"
            for node in bundle.instance.nodes
        )
        safety_seconds = max(180.0, 2.0 * customer_count)
        initial = _load_initial(instance_id)
        for arm_id, hard_lock in ARMS:
            run = run_hgs_route_pool_recombination(
                bundle,
                initial,
                seed=SEED,
                hgs_seconds_per_view=None,
                exact_elites_per_view=EXACT_ELITES_PER_VIEW,
                max_archive_candidates_per_view=(
                    ARCHIVE_CANDIDATES_PER_VIEW
                ),
                sp_time_limit_seconds=MIP_SECONDS,
                hard_home_depot_lock=hard_lock,
                max_hgs_iterations_per_view=(
                    PILOT_HGS_ITERATIONS_PER_VIEW
                ),
                wallclock_safety_seconds_per_view=safety_seconds,
            )
            view_stats = [
                epoch.stats
                for epoch in run.view_epochs.values()
            ]
            attempts = int(
                run.stats["complete_candidate_evaluation_attempts"]
            )
            raw_rows.append(
                {
                    "instance_id": instance_id,
                    "customer_count": customer_count,
                    "seed": SEED,
                    "arm_id": arm_id,
                    "hard_home_depot_lock": hard_lock,
                    "pilot_hgs_iterations_per_view": (
                        PILOT_HGS_ITERATIONS_PER_VIEW
                    ),
                    "complete_candidate_attempts": attempts,
                    "expected_complete_candidate_budget": (
                        EXPECTED_COMPLETE_BUDGET
                    ),
                    "archive_completion_attempts": sum(
                        int(row["archive_completion_attempts"])
                        for row in view_stats
                    ),
                    "archive_completion_successes": sum(
                        int(row["archive_completion_attempts"])
                        - len(row["archive_completion_failures"])
                        for row in view_stats
                    ),
                    "archive_completion_failures": sum(
                        len(row["archive_completion_failures"])
                        for row in view_stats
                    ),
                    "wallclock_safety_seconds_per_view": safety_seconds,
                    "wallclock_safety_triggered": (
                        run.stats["wallclock_safety_triggered"]
                    ),
                    "elapsed_seconds": round(
                        float(run.elapsed_seconds),
                        6,
                    ),
                    "mip_status_class": (
                        run.stats["route_pool_mip"]["status_class"]
                    ),
                    "mip_incumbent_available": (
                        run.stats["route_pool_mip"][
                            "incumbent_available"
                        ]
                    ),
                    "objective_values_recorded": False,
                    "status": (
                        "PASS"
                        if (
                            attempts == EXPECTED_COMPLETE_BUDGET
                            and not run.stats[
                                "wallclock_safety_triggered"
                            ]
                        )
                        else "HALT"
                    ),
                }
            )

    pass_all = all(row["status"] == "PASS" for row in raw_rows)
    write_csv(OUT / "raw_runs.csv", raw_rows)
    decision = {
        "schema": "resetp.china-e3-budget-pilot.v1",
        "verdict": (
            "PASS_RESULT_BLIND_BUDGET_80"
            if pass_all
            else "HALT_RESULT_BLIND_BUDGET_PILOT"
        ),
        "approval_id": "CHINA-E3-FORMAL-RELEASE-001",
        "task_count": len(raw_rows),
        "complete_candidate_budget_selected": (
            EXPECTED_COMPLETE_BUDGET if pass_all else None
        ),
        "selection_inputs": [
            "candidate attempt count",
            "completion success/failure count",
            "elapsed time",
            "wallclock safety state",
            "MIP status/incumbent presence",
        ],
        "objective_values_visible_to_selector": False,
        "objective_values_recorded": False,
        "formal_search_allowed": False,
        "pilot_search_only": True,
        "search_evaluations": sum(
            int(row["complete_candidate_attempts"])
            for row in raw_rows
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.china-e3-budget-pilot.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "builder": str(Path(__file__).relative_to(REPO)),
            "python": sys.version,
            "platform": platform.platform(),
            "pyvrp_version": version("pyvrp"),
            "numpy_version": numpy.__version__,
            "numpy_path": str(Path(numpy.__file__).resolve()),
            "scipy_version": scipy.__version__,
            "scipy_path": str(Path(scipy.__file__).resolve()),
            "thread_environment": {
                key: os.environ.get(key)
                for key in REQUIRED_THREAD_ENV
            },
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    Path(__file__).resolve(),
                    CONTRACT,
                    PROTOTYPE / "pyvrp_adapter.py",
                    PROTOTYPE / "epochal_hgs.py",
                    PROTOTYPE / "route_pool_sp.py",
                    REPO / "solver/src/setp_solver/china81.py",
                    REPO / "solver/src/setp_solver/cost.py",
                    REPO / "solver/src/setp_solver/check.py",
                    FLEET / "artifact_hashes.json",
                )
            },
            "formal_search_allowed": False,
            "pilot_search_only": True,
        },
    )
    (OUT / "report.md").write_text(
        "# E3 完整候选预算 result-blind pilot\n\n"
        "本 pilot 按预注册的珠三角 10/75/200 三档、地图 01、共同种子 1"
        "和两个 E3 臂执行。预算选择器未记录、读取或比较任何目标函数值；"
        "只检查每单元能否完整消费 80 次候选提交、补全成功/失败、耗时、"
        "MIP 状态与墙钟安全上限。正式结果搜索仍未放行。\n",
        encoding="utf-8",
    )
    artifacts: dict[str, str] = {}
    for path in sorted(OUT.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        ):
            artifacts[str(path.relative_to(OUT))] = sha256(path)
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    return decision


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True))
