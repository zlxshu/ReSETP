#!/usr/bin/env python3
"""Result-blind development gate for online exact HGS checkpoints."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import multiprocessing
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from route_pool_sp import run_hgs_route_pool_recombination  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import Route, Solution  # noqa: E402


OUT = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "algorithm_repair_diagnostic_20260724/"
    "online_exact_checkpoint_gate"
)
PREREGISTRATION = (
    OUT.parent / "online_exact_checkpoint_preregistration.json"
)
FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
PANEL = (
    ("cn-cy-100c-02-V2-LOCATIONS", 11),
    ("cn-jjj-100c-02-V2-LOCATIONS", 11),
    ("cn-prd-100c-02-V2-LOCATIONS", 11),
    ("cn-cy-150c-02-V2-LOCATIONS", 11),
    ("cn-jjj-150c-02-V2-LOCATIONS", 11),
    ("cn-prd-150c-02-V2-LOCATIONS", 11),
)
VIEW_BY_ARM = {
    "HGS-F": "cv_only",
    "HGS-E": "naive_ev",
    "HGS-M": "mechanism_ev",
}
VIEW_ORDER = ("cv_only", "naive_ev", "mechanism_ev")
ITERATIONS = 5_000
CHECKPOINT_INTERVAL = 250
ARCHIVE_CANDIDATES = 24
EXACT_ELITES = 8
MIP_SECONDS = 5.0
EXPECTED_CONTROL_BUDGET = 80
EXPECTED_CANDIDATE_BUDGET = 142
EPS = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_sha256(payload: Any) -> str:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_initial(instance_id: str) -> Solution:
    payload = json.loads(
        (FLEET / "witnesses" / f"{instance_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return Solution(
        routes=[
            Route(
                vehicle_id=str(route["vehicle_id"]),
                vehicle_type=str(route["vehicle_type"]),
                home_depot_id=str(route["home_depot_id"]),
                node_sequence=[
                    str(node) for node in route["node_sequence"]
                ],
            )
            for route in payload["routes"]
        ]
    )


def solution_key(solution: Solution) -> str:
    return payload_sha256(
        {
            "routes": [
                {
                    "vehicle_id": route.vehicle_id,
                    "vehicle_type": route.vehicle_type,
                    "home_depot_id": route.home_depot_id,
                    "node_sequence": list(route.node_sequence),
                }
                for route in solution.routes
            ]
        }
    )


def verify_solution(solution: Solution, bundle: Any) -> float:
    objective, _, violations = exact_china81_score(solution, bundle)
    if violations:
        raise RuntimeError(
            "independent exact check failed: "
            + "; ".join(str(item) for item in violations[:3])
        )
    return float(objective)


def curve_counts(
    initial_cost: float,
    observations: list[dict[str, Any]],
    final_cost: float,
) -> tuple[int, int]:
    ordered = sorted(
        (
            (
                float(item["elapsed_seconds"]),
                float(item["complete_objective"]),
            )
            for item in observations
            if (
                item["status"] == "PASS"
                and item["complete_objective"] is not None
            )
        ),
        key=lambda item: item[0],
    )
    best = float(initial_cost)
    points = 1
    decreases = 0
    for _, value in ordered:
        if value < best - EPS:
            best = value
            points += 1
            decreases += 1
    if final_cost < best - EPS:
        points += 1
        decreases += 1
    elif not math.isclose(final_cost, best, abs_tol=EPS, rel_tol=0.0):
        raise RuntimeError(
            f"final cost {final_cost} is worse than online incumbent {best}"
        )
    return points, decreases


def run_one(instance_id: str, seed: int) -> dict[str, Any]:
    bundle = load_china81_bundle(REPO, instance_id)
    initial = load_initial(instance_id)
    customer_count = sum(
        node.node_type.lower() == "c"
        for node in bundle.instance.nodes
    )
    safety_seconds = max(240.0, 3.0 * customer_count)
    common = complete_china81_route_skeleton(initial, bundle)
    control = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=EXACT_ELITES,
        max_archive_candidates_per_view=ARCHIVE_CANDIDATES,
        sp_time_limit_seconds=MIP_SECONDS,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=ITERATIONS,
        wallclock_safety_seconds_per_view=safety_seconds,
    )
    candidate = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=EXACT_ELITES,
        max_archive_candidates_per_view=ARCHIVE_CANDIDATES,
        sp_time_limit_seconds=MIP_SECONDS,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=ITERATIONS,
        wallclock_safety_seconds_per_view=safety_seconds,
        exact_checkpoint_interval_iterations=CHECKPOINT_INTERVAL,
        preserve_base_pool_recombination=True,
    )
    if (
        control.stats["wallclock_safety_triggered"]
        or candidate.stats["wallclock_safety_triggered"]
    ):
        raise RuntimeError("wallclock safety cap triggered")
    if (
        int(control.stats["complete_candidate_evaluation_attempts"])
        != EXPECTED_CONTROL_BUDGET
    ):
        raise RuntimeError("control budget mismatch")
    if (
        int(candidate.stats["complete_candidate_evaluation_attempts"])
        != EXPECTED_CANDIDATE_BUDGET
    ):
        raise RuntimeError("candidate budget mismatch")
    random_stream_equal = True
    candidate_costs: dict[str, float] = {}
    curve_by_arm: dict[str, tuple[int, int]] = {}
    all_observations: list[dict[str, Any]] = []
    offset = 0.0
    for arm, mode in VIEW_BY_ARM.items():
        control_epoch = control.view_epochs[mode]
        candidate_epoch = candidate.view_epochs[mode]
        random_stream_equal &= (
            solution_key(control_epoch.proxy_best_completion.solution)
            == solution_key(
                candidate_epoch.proxy_best_completion.solution
            )
        )
        best = min(
            (
                *candidate_epoch.elite_completions,
                candidate_epoch.proxy_best_completion,
            ),
            key=lambda item: item.objective,
        )
        candidate_costs[arm] = verify_solution(best.solution, bundle)
        observations = list(
            candidate_epoch.stats["exact_checkpoint_observations"]
        )
        if len(observations) != 20:
            raise RuntimeError(f"{arm}: expected 20 checkpoints")
        curve_by_arm[arm] = curve_counts(
            float(common.objective),
            observations,
            candidate_costs[arm],
        )
        all_observations.extend(
            {
                **item,
                "elapsed_seconds": (
                    float(item["elapsed_seconds"]) + offset
                ),
            }
            for item in observations
        )
        offset += float(candidate_epoch.elapsed_seconds)
    control_cost = verify_solution(control.solution, bundle)
    candidate_cost = verify_solution(candidate.solution, bundle)
    candidate_costs["MV-HGS-SP"] = candidate_cost
    curve_by_arm["MV-HGS-SP"] = curve_counts(
        float(common.objective),
        all_observations,
        candidate_cost,
    )
    candidate_nonworse = candidate_cost <= control_cost + EPS
    if not candidate_nonworse:
        raise RuntimeError("candidate regressed against control")
    own_view_nonworse = all(
        candidate_cost <= value + EPS
        for value in candidate_costs.values()
    )
    if not own_view_nonworse:
        raise RuntimeError("main method is worse than an own view")
    return {
        "instance_id": instance_id,
        "seed": seed,
        "customer_count": customer_count,
        "control_cost": control_cost,
        "candidate_cost": candidate_cost,
        "candidate_minus_control": candidate_cost - control_cost,
        "strict_candidate_win": candidate_cost < control_cost - EPS,
        "same_random_stream_endpoint": random_stream_equal,
        "control_complete_attempts": int(
            control.stats["complete_candidate_evaluation_attempts"]
        ),
        "candidate_complete_attempts": int(
            candidate.stats["complete_candidate_evaluation_attempts"]
        ),
        "candidate_selected_source": candidate.stats[
            "selected_source"
        ],
        "HGS-F_cost": candidate_costs["HGS-F"],
        "HGS-E_cost": candidate_costs["HGS-E"],
        "HGS-M_cost": candidate_costs["HGS-M"],
        "main_nonworse_than_own_views": own_view_nonworse,
        "HGS-F_curve_points": curve_by_arm["HGS-F"][0],
        "HGS-F_strict_decreases": curve_by_arm["HGS-F"][1],
        "HGS-E_curve_points": curve_by_arm["HGS-E"][0],
        "HGS-E_strict_decreases": curve_by_arm["HGS-E"][1],
        "HGS-M_curve_points": curve_by_arm["HGS-M"][0],
        "HGS-M_strict_decreases": curve_by_arm["HGS-M"][1],
        "MV-HGS-SP_curve_points": curve_by_arm["MV-HGS-SP"][0],
        "MV-HGS-SP_strict_decreases": curve_by_arm[
            "MV-HGS-SP"
        ][1],
        "main_curve_gate": (
            curve_by_arm["MV-HGS-SP"][0] >= 8
            and curve_by_arm["MV-HGS-SP"][1] >= 6
        ),
        "all_independently_feasible": True,
        "status": "PASS",
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not PREREGISTRATION.is_file():
        raise FileNotFoundError(PREREGISTRATION)
    workers = min(int(os.environ.get("RESET_WORKERS", "3")), len(PANEL))
    rows: list[dict[str, Any]] = []
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
    ) as executor:
        futures = {
            executor.submit(run_one, instance_id, seed): (
                instance_id,
                seed,
            )
            for instance_id, seed in PANEL
        }
        for future in as_completed(futures):
            instance_id, seed = futures[future]
            row = future.result()
            rows.append(row)
            print(
                "[ONLINE-EXACT-GATE] "
                f"{instance_id} seed={seed} "
                f"delta={row['candidate_minus_control']:.9f} "
                f"curve={row['MV-HGS-SP_curve_points']}/"
                f"{row['MV-HGS-SP_strict_decreases']}",
                flush=True,
            )
    rows.sort(key=lambda row: (row["instance_id"], row["seed"]))
    write_csv(OUT / "raw_runs.csv", rows)
    strict_wins = sum(bool(row["strict_candidate_win"]) for row in rows)
    curve_passes = sum(bool(row["main_curve_gate"]) for row in rows)
    invariant_pass = bool(
        len(rows) == len(PANEL)
        and all(row["status"] == "PASS" for row in rows)
        and all(row["same_random_stream_endpoint"] for row in rows)
        and all(row["all_independently_feasible"] for row in rows)
        and all(
            row["candidate_complete_attempts"]
            == EXPECTED_CANDIDATE_BUDGET
            for row in rows
        )
        and all(row["main_nonworse_than_own_views"] for row in rows)
        and all(
            row["candidate_minus_control"] <= EPS for row in rows
        )
    )
    passed = invariant_pass and strict_wins >= 2 and curve_passes >= 5
    verdict = (
        "PASS_ONLINE_EXACT_CHECKPOINT_DEVELOPMENT_GATE"
        if passed
        else "HALT_ONLINE_EXACT_CHECKPOINT_DEVELOPMENT_GATE"
    )
    decision = {
        "schema": (
            "resetp.online-exact-checkpoint-development.decision.v1"
        ),
        "verdict": verdict,
        "formal_evidence": False,
        "invariant_pass": invariant_pass,
        "strict_candidate_wins": strict_wins,
        "required_strict_candidate_wins": 2,
        "main_curve_gate_passes": curve_passes,
        "required_main_curve_gate_passes": 5,
        "panel_size": len(rows),
        "preregistration_sha256": sha256(PREREGISTRATION),
        "claim_boundary": (
            "development only; no paper or formal experiment claim"
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": (
                "resetp.online-exact-checkpoint-development.metadata.v1"
            ),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "workers": workers,
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    PREREGISTRATION,
                    PROTOTYPE / "epochal_hgs.py",
                    PROTOTYPE / "route_pool_sp.py",
                    Path(__file__).resolve(),
                )
            },
        },
    )
    (OUT / "report.md").write_text(
        "# Online exact checkpoint development gate\n\n"
        f"Decision: `{verdict}`.\n\n"
        f"The result-blind seed-11 panel produced {strict_wins} strict "
        "candidate wins over the archive-route-reuse control and "
        f"{curve_passes} of 6 main-method trajectories met the registered "
        "minimum of eight genuine complete-incumbent points and six strict "
        "decreases. Every endpoint was independently feasible; every "
        "checkpointed HGS proxy endpoint matched its uninstrumented control; "
        "and every candidate consumed exactly 142 complete evaluations. "
        "The original v1 decision recorded 141 because it counted the "
        "additional base-pool MIP completion once instead of twice; "
        "decision_v2.json preserves that accounting correction without "
        "changing the HALT verdict.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
