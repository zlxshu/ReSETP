#!/usr/bin/env python3
"""Materialize the approved China E3 release-candidate machine contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "data/ChinaInstances/"
    "china_e3_e7_foundation_contract_v1_20260723.json"
)
OUT = (
    ROOT
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v2_20260723.json"
)


def _write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build() -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    source["schema"] = "resetp.china.e3-e7-formal-release-contract.v2"
    source["contract_id"] = "CHINA-E3-FORMAL-RELEASE-001"
    source["created_date"] = "2026-07-23"
    source["status"] = "RELEASE_CANDIDATE_ZERO_SEARCH_GATES_OPEN"
    source["formal_search_allowed"] = False
    source["search_evaluations"] = 0
    source["purpose"] = (
        "D1--D6 approved implementation contract. Formal E3 search remains "
        "fail-closed until the independent GO_E3 evidence package passes."
    )
    source["source_contracts"]["formal_release"] = (
        "docs/handoff/china_e3_formal_release_contract_20260723.md"
    )
    source["source_contracts"]["runtime_parameters"] = (
        "data/ChinaInstances/"
        "china81_runtime_parameter_authority_v4_20260723/decision.json"
    )
    source["source_contracts"]["finite_fleet"] = (
        "data/ChinaInstances/"
        "china81_finite_fleet_authority_v1_20260723/decision.json"
    )
    source["source_contracts"]["spatiotemporal_settlement"] = (
        "data/ChinaInstances/"
        "china81_spatiotemporal_settlement_authority_v1_20260723/"
        "decision.json"
    )
    source["data"].update(
        {
            "catalog": (
                "data/ChinaInstances/"
                "china81_stage2_static_inputs_corrected_v3_20260723/"
                "instance_catalog.csv"
            ),
            "static_root": (
                "data/ChinaInstances/"
                "china81_stage2_static_inputs_corrected_v3_20260723"
            ),
            "orders": (
                "data/ChinaInstances/"
                "china81_order_attributes_gis_v2_20260723/orders.csv"
            ),
            "road_matrix_root": (
                "data/ChinaInstances/"
                "china81_local_directed_matrices_corrected_v10_20260723"
            ),
            "runtime_parameter_root": (
                "data/ChinaInstances/"
                "china81_runtime_parameter_authority_v4_20260723"
            ),
            "fleet_authority_root": (
                "data/ChinaInstances/"
                "china81_finite_fleet_authority_v1_20260723"
            ),
            "runtime_date": "2025-02-12",
        }
    )
    source["data"]["calendar"].update(
        {
            "formal_status": "PASS_COMMON_MONTH_AND_EXHIBIT_DATE_REGISTERED",
            "timezone": "Asia/Shanghai",
            "common_default_exhibit_day": "2025-02-12",
        }
    )
    source["spatiotemporal_settlement_key"] = {
        "fields": [
            "instance_id",
            "node_id",
            "city",
            "price_area_id",
            "carbon_source_column",
            "diesel_zone",
            "scenario_date",
            "half_hour_slot",
        ],
        "coordinate_role": "validate_city_membership_only",
        "electricity_selector": "node_city_to_price_area_id",
        "carbon_selector": "node_city_to_carbon_source_column",
        "diesel_selector": "route_origin_depot_city_to_diesel_zone",
        "common_date": "2025-02-12",
        "slot_count": 48,
        "fallback_allowed": False,
    }
    source["finite_fleet_scenario"] = {
        "authority": source["data"]["fleet_authority_root"],
        "base_rule": (
            "home-depot EDF deterministic first-feasible all-CV packing"
        ),
        "main_reserve_factor": 1.25,
        "sensitivity_factors": [1.10, 1.25, 1.50],
        "main_num_cv": "R_d",
        "main_num_ev": "max(1,ceil(0.25*R_d))",
        "depot_chargers": 2,
        "depot_charge_power_kw": 22.0,
        "charger_parameter_class": (
            "CONSTRUCTED_SCENARIO_NOT_OBSERVED_SITE_CONTRACT"
        ),
    }
    source["algorithm"].update(
        {
            "frozen_name_zh": (
                "多视角混合遗传搜索—限时MIP路线池重组算法"
            ),
            "route_pool_layer": "time-limited MIP route-pool recombination",
            "route_pool_claim": (
                "incumbent may be used only after complete-model feasibility "
                "recheck; optimality is claimed only when solver status proves it"
            ),
        }
    )
    source["formal_execution"] = {
        "primary_budget_unit": "complete_candidate_evaluation_attempt",
        "complete_candidate_budget": 80,
        "budget_decomposition": {
            "views": 3,
            "archive_candidates_per_view": 24,
            "common_initial_per_view": 1,
            "proxy_best_per_view": 1,
            "mip_or_parent_independent_recheck": 1,
            "final_shared_completion": 1,
        },
        "budget_pilot": {
            "instances": [
                "cn-prd-10c-01-V2-LOCATIONS",
                "cn-prd-75c-01-V2-LOCATIONS",
                "cn-prd-200c-01-V2-LOCATIONS",
            ],
            "seed": 1,
            "arms": [
                "status_quo_responsibility",
                "optimized_responsibility_cooperation",
            ],
            "objective_values_visible_to_selector": False,
            "status": "PREREGISTERED_NOT_YET_RUN",
        },
        "hgs_route_generation_iterations_per_view": 5000,
        "hgs_iteration_role": "candidate_generation_cap_not_primary_budget",
        "wallclock_role": "safety_cap_only",
        "wallclock_safety_seconds_per_view": "max(180,2*n)",
        "mip_time_limit_seconds": 5.0,
        "thread_count": 1,
        "required_environment": {
            "python": "build/python_envs/pyvrp-hgs-0.12.2/bin/python",
            "pyvrp": "0.12.2",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
        },
        "task_hash_fields": [
            "input_manifest_sha256",
            "spatiotemporal_crosswalk_sha256",
            "responsibility_map_sha256",
            "initial_solution_sha256",
            "algorithm_source_sha256",
            "evaluator_source_sha256",
            "solution_sha256",
            "certificate_sha256",
            "independent_recompute_sha256",
        ],
    }
    e3 = next(item for item in source["families"] if item["id"] == "E3")
    for arm in e3["arms"]:
        if arm["id"] == "status_quo_responsibility":
            arm["mechanism_config"] = {
                "hard_home_depot_lock": True,
                "reciprocal_cross_depot_neighborhood": False,
                "cross_site_service_allowed": False,
            }
        else:
            arm["mechanism_config"] = {
                "hard_home_depot_lock": False,
                "reciprocal_cross_depot_neighborhood": True,
                "cross_site_service_allowed": True,
            }
    source["rerun_boundary"] = {
        "private_china81_e2": "FULL_RERUN_NEW_DIRECTORY",
        "s3_to_s5": "FULL_RERUN_NEW_DIRECTORY",
        "public_p1": "NO_SEARCH_SEALED_WITNESS_REPLAY_ONLY",
        "historical_artifacts_overwrite_allowed": False,
    }
    _write_json(OUT, source)
    return {
        "path": str(OUT.relative_to(ROOT)),
        "status": source["status"],
        "formal_search_allowed": source["formal_search_allowed"],
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True))
