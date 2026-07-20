"""Fail-closed loader for the frozen China81 model inputs.

The historical text-instance loader remains unchanged.  This module joins the
China81 order, facility, road, vehicle, tariff, carbon, and nonlinear charging
contracts into one explicit runtime bundle.  It does not authorize formal
search: the current fleet counts are deliberately loose algorithmic upper
bounds, and every source/scenario boundary stays visible in the bundle.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .charging_curve import NL90_MILD
from .instance_loader import (
    Instance,
    Node,
    VehicleTypeParameters,
    load_profiled_road_matrices,
)
from .prices import PriceParameters


DEFAULT_CHINA81_DATE = "2025-02-12"
CHINA81_HORIZON_START_SECOND = 6 * 60 * 60
CHINA81_HORIZON_END_SECOND = 22 * 60 * 60
FLEET_CAP_SEMANTICS = (
    "NONBINDING_ALGORITHMIC_UPPER_BOUND_ONE_VEHICLE_PER_CUSTOMER_PER_TYPE"
)

_STATIC_INPUT_RELATIVE = Path(
    "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
)
_MATRIX_RELATIVE = Path(
    "data/ChinaInstances/china81_local_directed_matrices_v9_20260718"
)
_ORDER_RELATIVE = Path(
    "data/ChinaInstances/china81_order_attributes_mc001_v1_20260718/orders.csv"
)
_VEHICLE_LOCK_RELATIVE = Path(
    "data/ChinaInstances/china_parameter_lock_v2_20260718.json"
)

_DIESEL_PRICE_CNY_PER_L = {
    "jjj": 6.87,
    "prd": 6.83,
    "cy": 6.90,
}
_DIESEL_PRICE_SOURCE = {
    "jjj": "BEIJING_OFFICIAL_2026-07-03_0_DIESEL_6.87_CNY_PER_L",
    "prd": "GUANGDONG_OFFICIAL_2026-07-03_0_DIESEL_6.83_CNY_PER_L",
    "cy": "CHONGQING_OFFICIAL_2026-07-04_0_DIESEL_6.90_CNY_PER_L",
}


@dataclass(frozen=True)
class China81Bundle:
    """One completely joined China81 runtime input."""

    instance_id: str
    region: str
    date: str
    instance: Instance
    time_profile: list[dict[str, Any]]
    prices: PriceParameters
    source_paths: Mapping[str, str]
    customer_home_depot: Mapping[str, str]
    fleet_cap_semantics: str
    diesel_price_source_id: str
    formal_search_allowed: bool = False


def load_china81_bundle(
    repo_root: str | Path,
    instance_id: str,
    *,
    date: str = DEFAULT_CHINA81_DATE,
) -> China81Bundle:
    """Join one frozen China81 instance, rejecting missing or mixed inputs."""

    root = Path(repo_root).resolve()
    static_root = root / _STATIC_INPUT_RELATIVE
    matrix_root = root / _MATRIX_RELATIVE / "instances" / instance_id
    nodes_path = static_root / "instances" / instance_id / "nodes.csv"
    catalog_path = static_root / "instance_catalog.csv"
    orders_path = root / _ORDER_RELATIVE
    calendar_path = static_root / "tariff_carbon_48slot_calendar.csv"

    catalog_matches = [
        row
        for row in _read_csv(catalog_path)
        if row["instance_id"] == instance_id
    ]
    if len(catalog_matches) != 1:
        raise ValueError(
            f"China81 catalog must contain exactly one row for {instance_id!r}"
        )
    catalog = catalog_matches[0]
    region = catalog["region"].strip().lower()
    if region not in _DIESEL_PRICE_CNY_PER_L:
        raise ValueError(f"unsupported China81 region {region!r}")

    node_rows = _read_csv(nodes_path)
    order_rows = [
        row
        for row in _read_csv(orders_path)
        if row["instance_id"] == instance_id
    ]
    expected_customers = int(catalog["customer_count"])
    if len(order_rows) != expected_customers:
        raise ValueError(
            f"China81 order count disagrees with catalog for {instance_id}"
        )
    orders_by_customer = {
        row["customer_id"]: row
        for row in order_rows
    }
    if len(orders_by_customer) != len(order_rows):
        raise ValueError(f"duplicate customer orders in {instance_id}")

    nodes = [
        _node_from_rows(row, orders_by_customer)
        for row in node_rows
    ]
    customer_nodes = [
        node
        for node in nodes
        if node.node_type == "c"
    ]
    if len(customer_nodes) != expected_customers:
        raise ValueError(
            f"China81 customer-node count disagrees with catalog for "
            f"{instance_id}"
        )
    if len(nodes) != int(catalog["node_count"]):
        raise ValueError(
            f"China81 node count disagrees with catalog for {instance_id}"
        )
    if set(orders_by_customer) != {
        node.node_id
        for node in customer_nodes
    }:
        raise ValueError(
            f"China81 customer nodes and order rows disagree for {instance_id}"
        )

    road_profiles = load_profiled_road_matrices(matrix_root, nodes)
    vehicle_parameters = _china_vehicle_parameters()
    # One vehicle per customer per type is a deliberately loose algorithmic
    # ceiling.  It prevents accidental fleet shortage without claiming any
    # observed depot fleet.
    instance = Instance(
        nodes=nodes,
        distance_matrix=[
            list(row)
            for row in road_profiles["cv"].distance_m
        ],
        num_cv=expected_customers,
        num_ev=expected_customers,
        road_profiles=road_profiles,
        vehicle_parameters=vehicle_parameters,
        demand_mass_per_unit_kg=1.0,
    )

    cities = {
        str(node.city).strip().lower()
        for node in nodes
        if node.city is not None
    }
    time_profile = _load_time_profile(
        calendar_path,
        cities=cities,
        date=date,
    )
    prices = _china_prices(
        region,
        time_profile,
    )
    depots_by_city: dict[str, str] = {}
    for node in nodes:
        if node.node_type != "d":
            continue
        assert node.city is not None
        city = str(node.city).strip().lower()
        if city in depots_by_city:
            raise ValueError(
                f"China81 instance {instance_id} has multiple depots for {city}"
            )
        depots_by_city[city] = node.node_id
    if set(depots_by_city) != cities:
        raise ValueError(
            f"China81 instance {instance_id} has no unique depot for every city"
        )
    customer_home_depot = MappingProxyType(
        {
            node.node_id: depots_by_city[str(node.city).strip().lower()]
            for node in customer_nodes
        }
    )
    source_paths = MappingProxyType(
        {
            "catalog": str(catalog_path.relative_to(root)),
            "nodes": str(nodes_path.relative_to(root)),
            "orders": str(orders_path.relative_to(root)),
            "road_matrices": str(matrix_root.relative_to(root)),
            "tariff_carbon_calendar": str(calendar_path.relative_to(root)),
            "vehicle_parameter_lock": str(_VEHICLE_LOCK_RELATIVE),
        }
    )
    return China81Bundle(
        instance_id=instance_id,
        region=region,
        date=date,
        instance=instance,
        time_profile=time_profile,
        prices=prices,
        source_paths=source_paths,
        customer_home_depot=customer_home_depot,
        fleet_cap_semantics=FLEET_CAP_SEMANTICS,
        diesel_price_source_id=_DIESEL_PRICE_SOURCE[region],
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"required China81 input is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _node_from_rows(
    row: dict[str, str],
    orders_by_customer: dict[str, dict[str, str]],
) -> Node:
    node_id = row["node_id"]
    node_type = row["node_type"].strip().lower()
    city = row["city"].strip().lower()
    common = {
        "node_id": node_id,
        "x": float(row["longitude"]),
        "y": float(row["latitude"]),
        "city": city,
    }
    if node_type == "depot":
        return Node(
            node_type="d",
            ready_time=float(CHINA81_HORIZON_START_SECOND),
            due_time=float(CHINA81_HORIZON_END_SECOND),
            charge_power_kw=22.0,
            station_chargers=2,
            **common,
        )
    if node_type == "station":
        return Node(
            node_type="f",
            ready_time=float(CHINA81_HORIZON_START_SECOND),
            due_time=float(CHINA81_HORIZON_END_SECOND),
            charge_power_kw=60.0,
            station_chargers=1,
            **common,
        )
    if node_type != "customer":
        raise ValueError(
            f"unsupported China81 node type {node_type!r} for {node_id}"
        )
    try:
        order = orders_by_customer[node_id]
    except KeyError as exc:
        raise ValueError(
            f"China81 customer {node_id!r} has no order row"
        ) from exc
    if order["city"].strip().lower() != city:
        raise ValueError(
            f"China81 customer {node_id!r} city disagrees with order row"
        )
    demand = float(order["demand_kg"])
    ready = float(order["time_window_early_minute"]) * 60.0
    due = float(order["time_window_late_minute"]) * 60.0
    service = float(order["service_minutes"]) * 60.0
    if (
        demand <= 0.0
        or service < 0.0
        or ready < CHINA81_HORIZON_START_SECOND
        or due > CHINA81_HORIZON_END_SECOND
        or due < ready
    ):
        raise ValueError(
            f"China81 customer {node_id!r} has invalid demand/time data"
        )
    return Node(
        node_type="c",
        demand=demand,
        ready_time=ready,
        due_time=due,
        service_time=service,
        **common,
    )


def _china_vehicle_parameters() -> dict[str, VehicleTypeParameters]:
    """Return the frozen vehicle facts plus declared literature transfers."""

    return {
        "cv": VehicleTypeParameters(
            vehicle_type_id="JAC-WL-K7-G12J8-G12K8-box",
            fuel_type="diesel",
            payload_capacity_kg=1_735.0,
            curb_mass_kg=2_565.0,
            gross_mass_kg=4_495.0,
            frontal_area_m2=0.85 * 2.2 * 2.48,
            battery_kwh=None,
            drag_coefficient=0.45,
            rolling_resistance_coefficient=0.01,
            non_energy_distance_cost_per_km=0.78,
            engine_friction_kj_per_rev_l=0.2,
            engine_speed_rev_per_s=33.0,
            engine_displacement_l=5.0,
            traction_energy_multiplier=None,
            source_ids=(
                "JAC_OFFICIAL_WL_K7_FIRST_COLUMN_BOX",
                "AF_0.85_WH_SCENARIO_TRIP_2026_102123",
                "CD_0.45_EPA_SMARTWAY_CLASS2B_SCENARIO",
                "CMEM_DEMIR2012_GOEKE2015_TRANSFER",
            ),
        ),
        "ev": VehicleTypeParameters(
            vehicle_type_id="FOTON-AUMARK-ES1-140-box",
            fuel_type="electric",
            payload_capacity_kg=1_000.0,
            curb_mass_kg=3_300.0,
            gross_mass_kg=4_495.0,
            frontal_area_m2=0.85 * 2.2 * 3.25,
            battery_kwh=140.41,
            drag_coefficient=0.45,
            rolling_resistance_coefficient=0.01,
            non_energy_distance_cost_per_km=0.67,
            engine_friction_kj_per_rev_l=None,
            engine_speed_rev_per_s=None,
            engine_displacement_l=None,
            traction_energy_multiplier=1.184692 * 1.112434,
            source_ids=(
                "FOTON_OFFICIAL_AUMARK_ES1_140_BOX",
                "AF_0.85_WH_SCENARIO_TRIP_2026_102123",
                "CD_0.45_EPA_SMARTWAY_CLASS2B_SCENARIO",
                "EV_EFFICIENCY_GOEKE2015_TRANSFER",
            ),
        ),
    }


def _load_time_profile(
    calendar_path: Path,
    *,
    cities: set[str],
    date: str,
) -> list[dict[str, Any]]:
    selected = [
        row
        for row in _read_csv(calendar_path)
        if row["date"] == date
        and row["city"].strip().lower() in cities
    ]
    by_city: dict[str, list[dict[str, str]]] = {
        city: []
        for city in cities
    }
    for row in selected:
        by_city[row["city"].strip().lower()].append(row)
    for city, rows in by_city.items():
        slots = sorted(int(row["half_hour_slot"]) for row in rows)
        if slots != list(range(1, 49)):
            raise ValueError(
                f"China81 calendar must contain 48 unique slots for "
                f"{city!r} on {date}"
            )

    profile = []
    for row in selected:
        gamma_kg = float(row["carbon_factor_kgco2e_per_kwh"])
        profile.append(
            {
                "city": row["city"].strip().lower(),
                "region": row["region"].strip().lower(),
                "date": row["date"],
                "time_index": int(row["half_hour_slot"]),
                "half_hour_slot": int(row["half_hour_slot"]),
                "horizon_second_start": (
                    float(row["minute_of_day"]) * 60.0
                ),
                "actual_gco2_per_kwh": gamma_kg * 1_000.0,
                "forecast_gco2_per_kwh": gamma_kg * 1_000.0,
                "depot_energy_cny_per_kwh": float(
                    row["depot_energy_cny_per_kwh"]
                ),
                "public_energy_cny_per_kwh": float(
                    row["public_energy_cny_per_kwh"]
                ),
                "public_service_fee_cny_per_kwh": float(
                    row["public_service_fee_cny_per_kwh"]
                ),
                "public_total_cny_per_kwh": float(
                    row["public_total_cny_per_kwh"]
                ),
                "tariff_period": row["tariff_period"],
                "tariff_row_class": row["tariff_row_class"],
                "service_fee_class": row["service_fee_class"],
                "carbon_source_column": row["carbon_source_column"],
            }
        )
    profile.sort(
        key=lambda row: (
            str(row["city"]),
            float(row["horizon_second_start"]),
        )
    )
    if len(profile) != 48 * len(cities):
        raise ValueError(
            f"China81 calendar row count is incomplete for {date}"
        )
    return profile


def _china_prices(
    region: str,
    time_profile: list[dict[str, Any]],
) -> PriceParameters:
    depot_mean = sum(
        float(row["depot_energy_cny_per_kwh"])
        for row in time_profile
    ) / len(time_profile)
    public_mean = sum(
        float(row["public_total_cny_per_kwh"])
        for row in time_profile
    ) / len(time_profile)
    return PriceParameters(
        c_d=0.45,
        c_r=0.01,
        A_frontal=0.85 * 2.2 * 2.48,
        m_curb=2_565.0,
        m_unit=1.0,
        Q_capacity=1_735.0,
        B_battery_kwh=140.41,
        initial_ev_battery_kwh=0.0,
        diesel_price=_DIESEL_PRICE_CNY_PER_L[region],
        electricity_price=public_mean,
        station_electricity_price=public_mean,
        depot_electricity_price=depot_mean,
        depot_charge_power_kw=22.0,
        carbon_price=0.07502,
        carbon_price_low=0.05632,
        diesel_ef=2.70480534,
        vehicle_fixed_cost=170.0,
        occupancy_fee=0.5,
        cross_site_cost=0.0,
        revenue_per_kg=1.5,
        fairness_theta=1.0,
        c_km=0.78,
        charging_curve_id=NL90_MILD.curve_id,
        charging_soc_breakpoints=NL90_MILD.soc_breakpoints,
        charging_relative_powers=NL90_MILD.relative_powers,
    )
