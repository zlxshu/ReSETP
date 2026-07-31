#!/usr/bin/env python3
"""E3: scattered historical ownership versus joint routing."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[3]
PROTOTYPE = (
    REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
for path in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from route_pool_sp import run_hgs_route_pool_recombination
from setp_solver.china81_completion import exact_china81_score

from baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime import (
    CV_PER_DEPOT,
    EV_PER_DEPOT,
    build_common_initial,
    canonical_sha256,
    load_bundle,
    solution_sha256,
    write_csv,
    write_json,
)

SOURCE = HERE / "source_p_sequences.csv"
PILOT = HERE / "pilot"

FAMILIES = ("Uniform_Balanced", "Uniform_Unbalanced")
INSTANCES = tuple(
    f"cn-prd-{size}c-{rep}-V2-LOCATIONS"
    for size in (150, 200)
    for rep in ("01", "02", "03")
)
FORMAL_STATUS = "FORMAL_PENDING_USER_APPROVAL"


def sequences() -> dict[tuple[str, str], tuple[int, ...]]:
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        rows = {
            (row["source_family"], row["replicate"]): tuple(
                map(int, row["p_sequence"].split())
            )
            for row in csv.DictReader(handle)
        }
    if len(rows) != 6 or any(len(values) != 200 for values in rows.values()):
        raise ValueError("source_p_sequences.csv must contain six 200-label rows")
    return rows


def replicate(instance_id: str) -> str:
    return next(rep for rep in ("01", "02", "03") if f"c-{rep}-" in instance_id)


def prepare(instance_id: str, family: str) -> tuple[Any, Any, dict[str, Any]]:
    base = load_bundle(instance_id)
    customers = sorted(base.customer_home_depot)
    depots = sorted(set(base.customer_home_depot.values()))
    if family not in FAMILIES or len(depots) != 4 or len(customers) not in {150, 200}:
        raise ValueError("E3 transfer requires an approved family and 4-depot 150/200c input")

    labels = sequences()[(family, replicate(instance_id))][: len(customers)]
    mapping = {
        customer: depots[label]
        for customer, label in zip(customers, labels, strict=True)
    }
    caps = MappingProxyType(
        {
            depot: MappingProxyType(
                {"num_cv": CV_PER_DEPOT, "num_ev": EV_PER_DEPOT,
                 "total_fleet_cap": CV_PER_DEPOT + EV_PER_DEPOT}
            )
            for depot in depots
        }
    )
    bundle = replace(base, customer_home_depot=MappingProxyType(mapping))
    bundle = replace(
        bundle,
        instance=replace(
            bundle.instance,
            num_cv=CV_PER_DEPOT * 4,
            num_ev=EV_PER_DEPOT * 4,
        ),
        fleet_caps_by_depot=caps,
        fleet_cap_semantics=(
            "Soriano 40 CV per depot plus temporary ceil(0.25*R_d) EV rule"
        ),
        fleet_authority="E3_SCATTERED_REFERENCE_TRANSFER_20260801",
        formal_search_allowed=True,
    )
    initial, route_counts = build_common_initial(bundle)
    info = {
        "instance_id": instance_id,
        "source_family": family,
        "source_replicate": replicate(instance_id),
        "mapping_rule": "sorted customers + sorted depots; 150c uses first 150 labels",
        "owner_counts": {
            depot: sum(owner == depot for owner in mapping.values())
            for depot in depots
        },
        "initial_route_counts": route_counts,
        "mapping_sha256": canonical_sha256(mapping),
        "initial_sha256": solution_sha256(initial),
    }
    return bundle, initial, info


def preflight() -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    for instance_id in INSTANCES:
        for family in FAMILIES:
            bundle, _, info = prepare(instance_id, family)
            summaries.append(
                {
                    **info,
                    "owner_counts": json.dumps(info["owner_counts"], sort_keys=True),
                    "initial_route_counts": json.dumps(
                        info["initial_route_counts"], sort_keys=True
                    ),
                    "status": "PASS_INPUT_CONSTRUCTED",
                }
            )
            assignments.extend(
                {
                    "instance_id": instance_id,
                    "source_family": family,
                    "customer_id": customer,
                    "historical_owner_depot": owner,
                }
                for customer, owner in sorted(bundle.customer_home_depot.items())
            )
    write_csv(PILOT / "preflight_runs.csv", summaries)
    write_csv(PILOT / "input_assignments.csv", assignments)
    decision = {
        "status": "PASS_12_INPUTS_CONSTRUCTED",
        "scientific_result": False,
        "formal_status": FORMAL_STATUS,
        "inputs": len(summaries),
        "source": "https://data.mendeley.com/datasets/rhgk26ngs8/1",
        "source_archive_sha256": (
            "b7c217d2af44506138b8c536c989a5758461534471daf3b3c002214d8609fea3"
        ),
    }
    write_json(PILOT / "preflight_decision.json", decision)
    return decision


def run_arm(
    bundle: Any,
    initial: Any,
    arm: str,
    seed: int,
    iterations: int,
    archive: int,
) -> dict[str, Any]:
    run = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=min(8, archive),
        max_archive_candidates_per_view=archive,
        sp_time_limit_seconds=5.0,
        hard_home_depot_lock=arm == "HISTORICAL_STANDALONE",
        max_hgs_iterations_per_view=iterations,
        wallclock_safety_seconds_per_view=max(180.0, iterations * 0.5),
        exact_checkpoint_interval_iterations=None,
    )
    objective, breakdown, violations = exact_china81_score(run.solution, bundle)
    if violations or (
        arm == "HISTORICAL_STANDALONE" and run.solution.cross_site_services
    ):
        raise RuntimeError(f"invalid {arm} solution")
    return {
        "arm": arm,
        "total_cost_cny": objective,
        "total_emissions_kg": breakdown["E_total"],
        "route_count": len(run.solution.routes),
        "cross_site_service_count": len(run.solution.cross_site_services),
        "complete_candidate_evaluations": run.stats[
            "complete_candidate_evaluation_attempts"
        ],
        "elapsed_seconds": run.elapsed_seconds,
        "solution_sha256": solution_sha256(run.solution),
        "status": "PASS_SMOKE",
    }


def smoke(
    instance_id: str, family: str, seed: int, iterations: int, archive: int
) -> dict[str, Any]:
    bundle, initial, info = prepare(instance_id, family)
    rows = [
        {
            **info,
            "seed": seed,
            "iterations_per_view": iterations,
            "archive_candidates_per_view": archive,
            **run_arm(bundle, initial, arm, seed, iterations, archive),
        }
        for arm in ("HISTORICAL_STANDALONE", "JOINT_OPTIMIZED")
    ]
    costs = {row["arm"]: row["total_cost_cny"] for row in rows}
    baseline = costs["HISTORICAL_STANDALONE"]
    decision = {
        "status": "PASS_SMOKE_BOTH_ARMS",
        "scientific_role": "MECHANISM_SMOKE_NOT_FORMAL_RESULT",
        "formal_status": FORMAL_STATUS,
        "instance_id": instance_id,
        "source_family": family,
        "seed": seed,
        "joint_cost_change_pct": 100
        * (costs["JOINT_OPTIMIZED"] - baseline)
        / baseline,
        "common_initial_solution_sha256": info["initial_sha256"],
    }
    stem = f"{instance_id}__{family}__seed-{seed:02d}"
    write_csv(PILOT / f"{stem}__raw_runs.csv", rows)
    write_json(PILOT / f"{stem}__decision.json", decision)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    run = commands.add_parser("smoke")
    run.add_argument("--instance", default=INSTANCES[0], choices=INSTANCES)
    run.add_argument("--family", default=FAMILIES[0], choices=FAMILIES)
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--iterations", type=int, default=300)
    run.add_argument("--archive", type=int, default=8)
    args = parser.parse_args()
    result = preflight() if args.command == "preflight" else smoke(
        args.instance, args.family, args.seed, args.iterations, args.archive
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
