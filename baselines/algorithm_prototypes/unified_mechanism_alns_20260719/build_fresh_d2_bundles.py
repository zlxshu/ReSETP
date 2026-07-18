#!/usr/bin/env python3
"""Build new-composite D2 bundles and prelocked saturation backups."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MODEL_SCRIPTS = REPO / "models/scripts"
for path in (
    MODEL_SCRIPTS,
    REPO / "models/src",
    REPO / "solver/src",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_e2_benchmark_instances import (  # noqa: E402
    _build_three_shift_from_child_counts,
    _raw_meta,
)
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.algorithms.resetp_alns.support.fleet import (  # noqa: E402
    infer_fleet_limits,
    normalize_solution_vehicle_trips,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.cost import (  # noqa: E402
    route_next_day_departure_second,
    route_return_arrival_without_charging,
)
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    CrossSiteService,
    Route,
    Solution,
)


OUTPUT = HERE / "fresh_d2_bundles"
SOURCE_GROUPS = {
    10: ("04", "05", "06"),
    15: ("07", "08", "09"),
}
BACKUP_SOURCE_GROUPS = {
    20: ("04", "05", "06"),
    75: ("07", "08", "09"),
}
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
CONTRACT = (
    REPO
    / "docs/handoff/dual_basin_mechanism_alns_fresh_gate_contract_20260719.md"
)
GENERATOR = REPO / "models/scripts/build_e2_benchmark_instances.py"
ALLOWED_PRIOR_SOURCE_OCCURRENCES = {
    "baselines/e2_alns/source_bound_operational_mix_map_data/"
    "raw_goeke_fleet_counts.csv",
    "baselines/e2_alns/goeke_public_benchmark_feasibility_20260716/"
    "raw_runs.csv",
    "baselines/e2_alns/fleet_cap_operational_gate_data/"
    "raw_goeke_fleet_counts.csv",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def prior_occurrences(source_id: str) -> list[str]:
    """Return non-raw repo occurrences before the new D2 bundle exists."""

    completed = subprocess.run(
        [
            "rg",
            "-l",
            "--fixed-strings",
            source_id,
            str(REPO),
            "--glob",
            "!models/data_bundle/raw_instances/**",
            "--glob",
            "!**/.git/**",
            "--glob",
            "!**/._*",
            "--glob",
            "!**/__pycache__/**",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError(
            f"freshness rg failed for {source_id}: {completed.stderr}"
        )
    rows: list[str] = []
    for raw in completed.stdout.splitlines():
        path = Path(raw)
        try:
            relative = str(path.resolve().relative_to(REPO.resolve()))
        except ValueError:
            continue
        if relative.startswith(
            "models/data_bundle/raw_instances/"
        ) or relative.startswith(
            str(OUTPUT.relative_to(REPO))
        ):
            continue
        rows.append(relative)
    return sorted(set(rows))


def _annotate_cross_site(
    solution: Solution,
    owners: dict[str, str],
) -> Solution:
    services = [
        CrossSiteService(
            customer_id=node_id,
            served_by_depot_id=route.home_depot_id,
        )
        for route in solution.routes
        for node_id in route.node_sequence[1:-1]
        if owners.get(node_id) is not None
        and owners[node_id] != route.home_depot_id
    ]
    return replace(solution, cross_site_services=services)


def _cross_depot_feasible_witness(
    bundle_dir: Path,
    bundle: Any,
    owners: dict[str, str],
    depots: list[Any],
) -> dict[str, Any] | None:
    limits = infer_fleet_limits(bundle_dir)
    warm = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        fleet_limits=limits,
        introduce_ev=False,
        require_charging_signal=False,
    )
    depot_ids = sorted(node.node_id for node in depots)
    for customer_id, owner in sorted(owners.items()):
        for alternate in depot_ids:
            if alternate == owner:
                continue
            changed_routes: list[Route] = []
            removed = False
            for route in warm.routes:
                changed_sequence = [
                    node_id
                    for node_id in route.node_sequence
                    if node_id != customer_id
                ]
                if len(changed_sequence) != len(route.node_sequence):
                    removed = True
                if len(changed_sequence) > 2:
                    changed_routes.append(
                        replace(
                            route,
                            node_sequence=changed_sequence,
                        )
                    )
            if not removed:
                continue
            changed_routes.append(
                Route(
                    vehicle_id="CV_CROSS_WITNESS",
                    vehicle_type="cv",
                    home_depot_id=alternate,
                    node_sequence=[
                        alternate,
                        customer_id,
                        alternate,
                    ],
                )
            )
            try:
                candidate = normalize_solution_vehicle_trips(
                    Solution(routes=changed_routes),
                    bundle.instance,
                    max_cv=limits.cv,
                    max_ev=limits.ev,
                )
                candidate = _annotate_cross_site(candidate, owners)
                violations = check_solution(
                    candidate,
                    bundle.instance,
                    PRICES,
                )
            except Exception:
                continue
            if not violations:
                return {
                    "customer_id": customer_id,
                    "nearest_owner_depot": owner,
                    "feasible_alternate_depot": alternate,
                    "cross_site_service_count": len(
                        candidate.cross_site_services
                    ),
                    "full_solution_feasible": True,
                }
    return None


def _movable_charge_witness(
    bundle_dir: Path,
    bundle: Any,
) -> dict[str, Any] | None:
    limits = infer_fleet_limits(bundle_dir)
    seed = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        fleet_limits=limits,
        introduce_ev=True,
        require_charging_signal=False,
    )
    routes = {route.vehicle_id: route for route in seed.routes}
    witnesses: list[dict[str, Any]] = []
    for action in seed.charging_actions:
        route = routes.get(action.vehicle_id)
        if route is None:
            continue
        earliest = route_return_arrival_without_charging(
            route,
            bundle.instance,
            PRICES,
        )
        latest = route_next_day_departure_second(
            route,
            bundle.instance,
            PRICES,
        ) - float(action.occupancy_minutes) * 60.0
        slack = float(latest - earliest)
        if slack > 1.0e-6:
            witnesses.append(
                {
                    "vehicle_id": action.vehicle_id,
                    "station_id": action.station_id,
                    "energy_kwh": float(action.energy_kwh),
                    "earliest_start_second": float(earliest),
                    "latest_start_second": float(latest),
                    "movable_slack_seconds": slack,
                }
            )
    return max(
        witnesses,
        key=lambda item: item["movable_slack_seconds"],
        default=None,
    )


def structural_checks(bundle_dir: Path) -> dict[str, Any]:
    bundle = load_search_bundle(bundle_dir)
    nodes = list(bundle.instance.nodes)
    customers = [
        node for node in nodes if node.node_type.lower() == "c"
    ]
    depots = [
        node for node in nodes if node.node_type.lower() == "d"
    ]
    stations = [
        node for node in nodes if node.node_type.lower() == "f"
    ]
    owners = infer_customer_home_depots(bundle.instance)
    owner_depots = sorted(set(owners.values()))
    cross_witness = _cross_depot_feasible_witness(
        bundle_dir,
        bundle,
        owners,
        depots,
    )
    charge_witness = _movable_charge_witness(
        bundle_dir,
        bundle,
    )
    carbon_values = [
        float(row["actual_gco2_per_kwh"])
        for row in bundle.carbon_profile
    ]
    checks = {
        "actual_customer_count": len(customers),
        "actual_depot_count": len(depots),
        "actual_station_count": len(stations),
        "num_cv": int(bundle.instance.num_cv or 0),
        "num_ev": int(bundle.instance.num_ev or 0),
        "carbon_slot_count": len(carbon_values),
        "carbon_distinct_values": len(
            {round(value, 9) for value in carbon_values}
        ),
        "carbon_min_gco2_per_kwh": min(carbon_values),
        "carbon_max_gco2_per_kwh": max(carbon_values),
        "nearest_owner_depots": owner_depots,
        "cross_depot_feasible_witness": cross_witness,
        "movable_charge_witness": charge_witness,
    }
    checks["structure_pass"] = bool(
        len(depots) == 2
        and int(bundle.instance.num_cv or 0) > 0
        and int(bundle.instance.num_ev or 0) > 0
        and len(carbon_values) > 1
        and checks["carbon_distinct_values"] > 1
        and len(owner_depots) == 2
        and len(stations) > 0
        and cross_witness is not None
        and charge_witness is not None
    )
    return checks


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(
            f"refusing to overwrite frozen D2 bundles: {OUTPUT}"
        )
    if not CONTRACT.is_file():
        raise FileNotFoundError(CONTRACT)

    all_groups = {
        **SOURCE_GROUPS,
        **BACKUP_SOURCE_GROUPS,
    }
    source_audit: dict[str, list[str]] = {}
    for source_scale, source_donors in all_groups.items():
        for donor in source_donors:
            source_id = f"E-UK{source_scale}_{donor}"
            occurrences = prior_occurrences(source_id)
            unexpected = sorted(
                set(occurrences) - ALLOWED_PRIOR_SOURCE_OCCURRENCES
            )
            if unexpected:
                raise RuntimeError(
                    f"{source_id} is not fresh for full-model synthesis: "
                    f"{unexpected}"
                )
            source_audit[source_id] = occurrences

    OUTPUT.mkdir(parents=True)
    primary_rows: list[dict[str, Any]] = []
    backup_rows: list[dict[str, Any]] = []
    for source_scale, source_donors in all_groups.items():
        is_backup = source_scale in BACKUP_SOURCE_GROUPS
        metas = [
            _raw_meta(f"E-UK{source_scale}_{donor}")
            for donor in source_donors
        ]
        stage = OUTPUT / f".stage-src{source_scale}"
        group_label = "".join(
            donor.lstrip("0") for donor in source_donors
        )
        role = "BACKUP-" if is_backup else ""
        prefix = (
            f"DEV-DUAL-D2-{role}GROUP{group_label}-SRC{source_scale}"
        )
        build_row = _build_three_shift_from_child_counts(
            metas,
            source_scale,
            source_donors[0],
            prefix,
            stage,
            child_counts=tuple(
                int(meta.customer_count) for meta in metas
            ),
            count_policy={
                "policy": (
                    f"fresh_group{group_label}_full_source_"
                    "natural_24h_tail_cut"
                ),
                "source_scale": int(source_scale),
                "source_donors": list(source_donors),
                "input_customer_counts": [
                    int(meta.customer_count) for meta in metas
                ],
                "forbidden": [
                    "target_count_planning",
                    "prefix_truncation",
                    "algorithm_result_based_selection",
                ],
            },
            formal_v3=True,
        )
        checks = structural_checks(stage)
        if not checks["structure_pass"]:
            raise RuntimeError(
                f"D2 structure failed before scores for SRC{source_scale}: "
                f"{checks}"
            )
        instance_id = (
            f"{prefix}-N{checks['actual_customer_count']}"
            f"-DEP{checks['actual_depot_count']}"
        )
        final_dir = OUTPUT / instance_id
        stage.replace(final_dir)
        row = {
            "instance_id": instance_id,
            "role": "saturation_backup" if is_backup else "primary",
            "source_scale": int(source_scale),
            "source_ids": [
                meta.base_id for meta in metas
            ],
            "source_paths_repo_relative": [
                str(meta.path.relative_to(REPO))
                for meta in metas
            ],
            "source_sha256": {
                meta.base_id: sha256(meta.path)
                for meta in metas
            },
            "builder_reported_customer_count": int(
                build_row.n_customers_actual
            ),
            **checks,
            "bundle_files": {
                path.name: sha256(path)
                for path in sorted(final_dir.iterdir())
                if path.is_file()
                and not path.name.startswith("._")
            },
        }
        if is_backup:
            backup_rows.append(row)
        else:
            primary_rows.append(row)

    manifest = {
        "schema_version": "resetp.dual-basin-alns.d2-dataset.v1",
        "purpose": (
            "stage1_isolated_fresh_development_gate_only_not_formal_benchmark"
        ),
        "repo_search_found_no_prior_current_candidate_score": True,
        "raw_sources_previously_used_only_for_public_feasibility_inventory": True,
        "freshness_label": "NEW_COMPOSITE_BUNDLE_NOT_RAW_PRISTINE",
        "formal_l_main_activated": False,
        "stage2_activated": False,
        "source_groups": {
            str(scale): list(donors)
            for scale, donors in SOURCE_GROUPS.items()
        },
        "backup_source_groups": {
            str(scale): list(donors)
            for scale, donors in BACKUP_SOURCE_GROUPS.items()
        },
        "prior_occurrence_allowlist": sorted(
            ALLOWED_PRIOR_SOURCE_OCCURRENCES
        ),
        "prior_source_occurrences": source_audit,
        "generator_repo_relative": str(
            GENERATOR.relative_to(REPO)
        ),
        "generator_sha256": sha256(GENERATOR),
        "builder_repo_relative": str(
            Path(__file__).resolve().relative_to(REPO)
        ),
        "builder_sha256": sha256(Path(__file__).resolve()),
        "contract_repo_relative": str(CONTRACT.relative_to(REPO)),
        "contract_sha256": sha256(CONTRACT),
        "instances": primary_rows,
        "backup_instances": backup_rows,
    }
    atomic_json(OUTPUT / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
