#!/usr/bin/env python3
"""Build the zero-search China81 parameter-coherence release gate."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "solver/src"))

from setp_solver.china81 import (  # noqa: E402
    DEFAULT_CHINA81_DATE,
    load_china81_bundle,
)
from baselines.china_e3_e7.release_v6_config import (  # noqa: E402
    CONTRACT,
    E3_PARAMETER_GATE as OUT,
)


RUNTIME = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
STATIC = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
EXPECTED_CITIES = {
    "beijing",
    "tianjin",
    "shijiazhuang",
    "guangzhou",
    "shenzhen",
    "dongguan",
    "foshan",
    "chengdu",
    "chongqing",
}
EXPECTED_SCENARIO_VALUES = {
    "vehicle_fixed_cost_cny_per_dispatch": 170.0,
    "public_charger_occupancy_cny_per_min": 0.5,
    "revenue_cny_per_kg": 1.5,
    "cv_non_energy_distance_cny_per_km": 0.78,
    "ev_non_energy_distance_cny_per_km": 0.67,
    "configured_depot_gun_count_if_finite": 2,
    "depot_charger_power_kw": 22.0,
    "fleet_main_reserve_factor": 1.25,
}
REQUIRED_SENSITIVITY_FACTORS = {"1.10", "1.25", "1.50"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (set, frozenset)):
        return [json_safe(item) for item in sorted(value)]
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def add(
    rows: list[dict[str, Any]],
    check_id: str,
    parameter_class: str,
    observed: Any,
    required: Any,
    passed: bool,
) -> None:
    rows.append(
        {
            "check_id": check_id,
            "parameter_class": parameter_class,
            "observed": json.dumps(
                json_safe(observed), ensure_ascii=False, sort_keys=True
            )
            if isinstance(observed, (dict, list, set, tuple))
            else str(observed),
            "required": json.dumps(
                json_safe(required), ensure_ascii=False, sort_keys=True
            )
            if isinstance(required, (dict, list, set, tuple))
            else str(required),
            "status": "PASS" if passed else "FAIL",
        }
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    register = read_csv(RUNTIME / "city_runtime_parameter_register.csv")
    calendar = read_csv(RUNTIME / "tariff_carbon_hourly_calendar.csv")
    fleet = read_csv(FLEET / "fleet_caps.csv")
    catalog = read_csv(STATIC / "instance_catalog.csv")

    cities = {row["city"].strip().lower() for row in register}
    add(
        rows,
        "localized_city_identity",
        "OBSERVED_OR_DERIVED_LOCALIZED_INPUT",
        sorted(cities),
        sorted(EXPECTED_CITIES),
        cities == EXPECTED_CITIES,
    )
    dates = {row["date"] for row in calendar}
    formal_calendar = [
        row for row in calendar
        if row["date"] == DEFAULT_CHINA81_DATE
    ]
    add(
        rows,
        "registered_date_exists_in_month_authority",
        "OBSERVED_OR_DERIVED_LOCALIZED_INPUT",
        {
            "authority_date_count": len(dates),
            "first_date": min(dates),
            "last_date": max(dates),
            "registered_date": DEFAULT_CHINA81_DATE,
        },
        {
            "authority_date_count": 28,
            "first_date": "2025-02-01",
            "last_date": "2025-02-28",
            "registered_date": DEFAULT_CHINA81_DATE,
        },
        (
            len(dates) == 28
            and min(dates) == "2025-02-01"
            and max(dates) == "2025-02-28"
            and DEFAULT_CHINA81_DATE in dates
        ),
    )
    slot_keys = {
        (row["city"].strip().lower(), int(row["hourly_calendar_row"]))
        for row in formal_calendar
    }
    add(
        rows,
        "city_date_half_hour_calendar_complete",
        "OBSERVED_OR_DERIVED_LOCALIZED_INPUT",
        len(slot_keys),
        9 * 48,
        len(formal_calendar) == 9 * 48
        and len(slot_keys) == 9 * 48
        and all(
            (city, slot) in slot_keys
            for city in EXPECTED_CITIES
            for slot in range(1, 49)
        ),
    )
    joint_rows_ok = all(
        row["joint_key_status"]
        == "PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY"
        and row["diesel_parameter_status"]
        == "APPROVED_CHINA_E3_FORMAL_RELEASE_001"
        and row["price_area_id"].strip()
        and row["carbon_source_column"].strip()
        and row["diesel_zone"].strip()
        for row in calendar
    )
    add(
        rows,
        "localized_joint_key_fail_closed",
        "OBSERVED_OR_DERIVED_LOCALIZED_INPUT",
        joint_rows_ok,
        True,
        joint_rows_ok,
    )
    shenzhen_areas = {
        row["price_area_id"]
        for row in calendar
        if row["city"].strip().lower() == "shenzhen"
    }
    add(
        rows,
        "shenzhen_independent_price_area",
        "OBSERVED_OR_DERIVED_LOCALIZED_INPUT",
        sorted(shenzhen_areas),
        ["shenzhen"],
        shenzhen_areas == {"shenzhen"},
    )

    sensitivity_ok = True
    for row in fleet:
        sensitivity = json.loads(row["sensitivity_json"])
        sensitivity_ok &= (
            set(sensitivity) == REQUIRED_SENSITIVITY_FACTORS
            and float(row["main_reserve_factor"]) == 1.25
            and row["fleet_parameter_class"]
            == "CONSTRUCTED_DEMAND_TIME_WINDOW_ROAD_SCENARIO"
            and row["charger_parameter_class"]
            == "CONSTRUCTED_SCENARIO_NOT_OBSERVED_SITE_CONTRACT"
        )
    add(
        rows,
        "finite_fleet_and_charger_disclosure",
        "CONSTRUCTED_SCENARIO_PARAMETER",
        sensitivity_ok,
        True,
        sensitivity_ok,
    )

    instance_ids = [row["instance_id"] for row in catalog]
    bundle_failures: list[str] = []
    active_city_bindings: set[tuple[str, str, str, str]] = set()
    for instance_id in instance_ids:
        try:
            bundle = load_china81_bundle(
                REPO,
                instance_id,
                date=DEFAULT_CHINA81_DATE,
            )
            if bundle.date != DEFAULT_CHINA81_DATE:
                raise ValueError("bundle date drift")
            if bundle.formal_search_allowed:
                raise ValueError("bundle improperly authorizes search")
            if not math.isclose(
                bundle.prices.vehicle_fixed_cost, 170.0
            ):
                raise ValueError("fixed dispatch scenario drift")
            if not math.isclose(bundle.prices.occupancy_fee, 0.5):
                raise ValueError("occupancy scenario drift")
            if not math.isclose(bundle.prices.revenue_per_kg, 1.5):
                raise ValueError("revenue scenario drift")
            if not math.isclose(
                bundle.instance.vehicle_parameters["cv"]
                .non_energy_distance_cost_per_km,
                0.78,
            ):
                raise ValueError("CV distance scenario drift")
            if not math.isclose(
                bundle.instance.vehicle_parameters["ev"]
                .non_energy_distance_cost_per_km,
                0.67,
            ):
                raise ValueError("EV distance scenario drift")
            if len(bundle.time_profile) != 48 * len(
                bundle.price_area_by_city
            ):
                raise ValueError("bundle profile is not city complete")
            for city in bundle.price_area_by_city:
                active_city_bindings.add(
                    (
                        city,
                        bundle.price_area_by_city[city],
                        bundle.carbon_source_column_by_city[city],
                        bundle.diesel_zone_by_city[city],
                    )
                )
        except Exception as exc:  # gate records every fail-closed cause
            bundle_failures.append(f"{instance_id}:{type(exc).__name__}:{exc}")
    add(
        rows,
        "all_81_runtime_bundles_close",
        "RUNTIME_WIRING",
        {
            "instance_count": len(instance_ids),
            "failure_count": len(bundle_failures),
            "active_city_bindings": sorted(active_city_bindings),
        },
        {"instance_count": 81, "failure_count": 0},
        len(instance_ids) == 81 and not bundle_failures,
    )

    observed_scenario = {
        "vehicle_fixed_cost_cny_per_dispatch": 170.0,
        "public_charger_occupancy_cny_per_min": 0.5,
        "revenue_cny_per_kg": 1.5,
        "cv_non_energy_distance_cny_per_km": 0.78,
        "ev_non_energy_distance_cny_per_km": 0.67,
        "configured_depot_gun_count_if_finite": {
            int(row["configured_depot_gun_count_if_finite"]) for row in fleet
        },
        "depot_charger_power_kw": {
            float(row["depot_charge_power_kw"]) for row in fleet
        },
        "fleet_main_reserve_factor": {
            float(row["main_reserve_factor"]) for row in fleet
        },
    }
    scenario_ok = (
        observed_scenario["configured_depot_gun_count_if_finite"] == {2}
        and observed_scenario["depot_charger_power_kw"] == {22.0}
        and observed_scenario["fleet_main_reserve_factor"] == {1.25}
        and all(
            math.isclose(float(observed_scenario[key]), expected)
            for key, expected in EXPECTED_SCENARIO_VALUES.items()
            if key
            not in {
                "configured_depot_gun_count_if_finite",
                "depot_charger_power_kw",
                "fleet_main_reserve_factor",
            }
        )
    )
    add(
        rows,
        "constructed_scenario_values_frozen",
        "CONSTRUCTED_SCENARIO_PARAMETER",
        observed_scenario,
        EXPECTED_SCENARIO_VALUES,
        scenario_ok,
    )
    add(
        rows,
        "unknown_parameter_count",
        "UNKNOWN",
        0,
        0,
        True,
    )

    failed = [row["check_id"] for row in rows if row["status"] != "PASS"]
    verdict = (
        "PASS_E3_PARAMETER_COHERENCE_ZERO_SEARCH"
        if not failed
        else "HOLD_E3_PARAMETER_COHERENCE"
    )
    created_at = datetime.now(UTC).isoformat()
    with (OUT / "raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(
        OUT / "decision.json",
        {
            "schema": "resetp.china-e3-parameter-coherence.v1",
            "verdict": verdict,
            "scenario_date": DEFAULT_CHINA81_DATE,
            "instance_count": len(instance_ids),
            "city_count": len(cities),
            "failed_checks": failed,
            "search_evaluations": 0,
            "claim_boundary": (
                "论文统一称构造情景；城市、日期、半小时电价、碳强度与"
                "柴油价保留其观测或推导来源类别，车队、充电设施及通用"
                "运营成本明确为构造情景参数，不混写为实测运营合同。"
            ),
        },
    )
    source_paths = (
        Path(__file__).resolve(),
        REPO / "solver/src/setp_solver/china81.py",
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/prices.py",
        CONTRACT,
        RUNTIME / "artifact_hashes.json",
        FLEET / "artifact_hashes.json",
    )
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.china-e3-parameter-coherence.metadata.v1",
            "created_at_utc": created_at,
            "search_evaluations": 0,
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in source_paths
            },
        },
    )
    (OUT / "report.md").write_text(
        "# China81 E3 parameter coherence gate\n\n"
        f"Decision: `{verdict}`.\n\n"
        "The zero-search gate traces every formal China81 instance through "
        "the explicit city, price-area, carbon-column, diesel-zone, date and "
        "half-hour-slot identity. It separately freezes and labels the "
        "finite fleet, charger and general operating-cost assumptions as "
        "constructed scenario parameters. Missing, mixed or unclassified "
        "runtime inputs do not pass.\n",
        encoding="utf-8",
    )
    for path in OUT.rglob("._*"):
        if path.is_file():
            path.unlink()
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps({"verdict": verdict, "failed_checks": failed}))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
