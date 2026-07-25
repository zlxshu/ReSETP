#!/usr/bin/env python3
"""Independently verify the preregistered E3 control/treatment semantics.

This is a zero-search structural gate. It does not compare objectives or
generate treatment outcomes. The control proof checks the multidimensional
home-depot lock and replays the finite-fleet witness. The treatment proof
checks that the lock is absent and that PyVRP 0.12.2's reciprocal Exchange11
operator is active on the actual problem data.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
for path in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pyvrp.solve import SolveParams  # noqa: E402
from pyvrp_adapter import build_pyvrp_problem  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.solution import Route, Solution  # noqa: E402
from baselines.china_e3_e7.release_v6_config import (  # noqa: E402
    CONTRACT,
    E3_ARM_GATE as OUT,
)


STATIC = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
APPROVAL_ID = "CHINA-E3-FORMAL-RELEASE-001"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _solution_from_witness(path: Path) -> Solution:
    payload = json.loads(path.read_text(encoding="utf-8"))
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


def _verify_control_encoding(bundle: Any, data: Any) -> None:
    depots = list(data.depots())
    depot_index = {
        depot.name: index
        for index, depot in enumerate(depots)
    }
    if data.num_load_dimensions != 1 + len(depots):
        raise RuntimeError("control arm lacks home-depot load dimensions")
    for client in data.clients():
        owner = bundle.customer_home_depot[client.name]
        dimensions = list(client.delivery[1:])
        if sum(dimensions) != 1:
            raise RuntimeError("control customer owner marker is not one-hot")
        if dimensions[depot_index[owner]] != 1:
            raise RuntimeError("control customer owner marker is wrong")
    for vehicle_type in data.vehicle_types():
        home = depots[vehicle_type.start_depot].name
        if vehicle_type.start_depot != vehicle_type.end_depot:
            raise RuntimeError("control vehicle has different start/end depots")
        for depot_id, index in depot_index.items():
            admitted = vehicle_type.capacity[1 + index] > 0
            if admitted != (depot_id == home):
                raise RuntimeError("control vehicle owner capacity is wrong")


def build() -> dict[str, Any]:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite existing gate: {OUT}")
    OUT.mkdir(parents=True)

    params = SolveParams()
    raw_rows: list[dict[str, Any]] = []
    instance_ids = sorted(
        row["instance_id"]
        for row in read_csv(STATIC / "instance_catalog.csv")
    )
    for instance_id in instance_ids:
        bundle = load_china81_bundle(REPO, instance_id)
        control = build_pyvrp_problem(
            bundle,
            hard_home_depot_lock=True,
        )
        treatment = build_pyvrp_problem(
            bundle,
            hard_home_depot_lock=False,
        )
        control_data = control.model.data()
        treatment_data = treatment.model.data()
        _verify_control_encoding(bundle, control_data)
        if treatment_data.num_load_dimensions != 1:
            raise RuntimeError("treatment arm retained an ownership dimension")
        active_node_operators = [
            operator.__name__
            for operator in params.node_ops
            if operator.supports(treatment_data)
        ]
        if "Exchange11" not in active_node_operators:
            raise RuntimeError(
                f"treatment reciprocal swap is inactive for {instance_id}"
            )

        witness_path = FLEET / "witnesses" / f"{instance_id}.json"
        witness = annotate_cross_site_services(
            _solution_from_witness(witness_path),
            bundle.customer_home_depot,
        )
        _, _, violations = exact_china81_score(witness, bundle)
        if violations or witness.cross_site_services:
            raise RuntimeError(
                f"control witness replay failed for {instance_id}"
            )
        raw_rows.append(
            {
                "instance_id": instance_id,
                "control_load_dimensions": (
                    control_data.num_load_dimensions
                ),
                "treatment_load_dimensions": (
                    treatment_data.num_load_dimensions
                ),
                "control_full_model_violation_count": len(violations),
                "control_cross_site_service_count": 0,
                "treatment_reciprocal_operator": "Exchange11",
                "treatment_active_node_operators": "|".join(
                    active_node_operators
                ),
                "treatment_lock_removed": True,
                "status": "PASS",
                "search_evaluations": 0,
            }
        )

    write_csv(OUT / "raw_runs.csv", raw_rows)
    decision = {
        "schema": "resetp.china-e3-arm-semantics-gate.v1",
        "verdict": "PASS_E3_ARM_SEMANTICS_ZERO_SEARCH",
        "approval_id": APPROVAL_ID,
        "instance_count": len(raw_rows),
        "control": {
            "home_depot_lock": "HARD_SEARCH_SPACE_CONSTRAINT",
            "full_model_witness_replay": "81/81 PASS",
            "cross_site_service_count": 0,
        },
        "treatment": {
            "home_depot_lock": "REMOVED",
            "reciprocal_cross_depot_operator": "Exchange11",
            "operator_source": "PyVRP 0.12.2 SolveParams.node_ops",
            "result_claim": "STRUCTURAL_ADMISSIBILITY_ONLY",
        },
        "formal_search_allowed": False,
        "search_evaluations": 0,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.china-e3-arm-semantics.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "builder": str(Path(__file__).relative_to(REPO)),
            "approval_id": APPROVAL_ID,
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    Path(__file__).resolve(),
                    PROTOTYPE / "pyvrp_adapter.py",
                    PROTOTYPE / "epochal_hgs.py",
                    REPO / "solver/src/setp_solver/china81.py",
                    REPO
                    / "solver/src/setp_solver/"
                    "china81_completion.py",
                    REPO / "solver/src/setp_solver/cost.py",
                    REPO / "solver/src/setp_solver/check.py",
                    FLEET / "decision.json",
                    FLEET / "artifact_hashes.json",
                    CONTRACT,
                )
            },
            "formal_search_allowed": False,
            "search_evaluations": 0,
        },
    )
    (OUT / "report.md").write_text(
        "# E3 双臂机制零搜索验收\n\n"
        "控制臂在 HGS 问题中增加按车场划分的所有权容量维度，非所属车场"
        "车辆的对应容量为零，因此跨场服务在搜索空间内被硬性排除；81 个"
        "有限车队 witness 经完整模型重放均为零违约、零跨场。处理臂删除"
        "所有权维度，并确认 PyVRP 0.12.2 默认教育阶段的 Exchange11"
        "（两条路线各交换一个客户）对实际 81 个问题全部启用。该结论只"
        "证明双向跨场邻域在结构上可达，不含任何效果主张，也未执行搜索。\n",
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
