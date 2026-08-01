"""Small runtime shared by the E3 ownership-transfer runner."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from setp_solver.china81 import China81Bundle, load_china81_bundle
from setp_solver.china81_completion import (
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import Route, Solution

from baselines.china_instances.build_china81_finite_fleet_authority_v1_20260723 import (
    _pack_depot,
)

REPO = Path(__file__).resolve().parents[3]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def canonical_sha256(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def solution_sha256(solution: Solution) -> str:
    return canonical_sha256(asdict(solution))


def load_bundle(instance_id: str) -> China81Bundle:
    data = REPO / "data/ChinaInstances"
    return load_china81_bundle(
        REPO,
        instance_id,
        static_input_authority=data / "china81_stage2_static_inputs_corrected_v3_20260723",
        road_matrix_authority=data / "china81_local_directed_matrices_corrected_v10_20260723",
        runtime_parameter_authority=data / "china81_runtime_parameter_authority_v4_20260723",
        fleet_authority=REPO / "baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a",
    )


def build_common_initial(bundle: China81Bundle) -> tuple[Solution, dict[str, int]]:
    routes: list[Route] = []
    counts: dict[str, int] = {}
    for depot in sorted(set(bundle.customer_home_depot.values())):
        groups = _pack_depot(bundle, depot)
        counts[depot] = len(groups)
        if len(groups) > int(bundle.fleet_caps_by_depot[depot]["total_fleet_cap"]):
            raise RuntimeError(f"initial fleet exceeded at {depot}")
        routes.extend(
            Route(f"INIT-{depot}-CV-{i:03d}", "cv", depot, [depot, *group, depot])
            for i, group in enumerate(groups, start=1)
        )
    solution = complete_china81_route_skeleton(Solution(routes=routes), bundle).solution
    _, _, violations = exact_china81_score(solution, bundle)
    if violations or solution.cross_site_services:
        raise RuntimeError("common initial solution is infeasible or crosses owners")
    return solution, counts
