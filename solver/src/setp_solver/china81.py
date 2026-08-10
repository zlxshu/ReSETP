"""Fail-closed loader for the frozen China81 model inputs.

The historical text-instance loader remains unchanged.  This module joins the
China81 order, facility, road, vehicle, tariff, carbon, and nonlinear charging
contracts into one explicit runtime bundle.  It does not authorize formal
search: the current fleet counts are deliberately loose algorithmic upper
bounds, and every source/scenario boundary stays visible in the bundle.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .charging_curve import (
    M17_22KW_NORMAL_PWL,
    M17_FAST_SHAPE_SCALED_60KW_PWL,
)
from .instance_loader import (
    Instance,
    Node,
    VehicleTypeParameters,
    load_profiled_road_matrices,
)
from .model_config import (
    DEPOT_CHARGER_CAPACITY_FINITE_INSTANCE,
    DEPOT_CHARGER_CAPACITY_UNBOUNDED,
    ModelConfig,
)
from .prices import PriceParameters

DEFAULT_CHINA81_DATE = "2025-02-12"
CHINA81_HORIZON_START_SECOND = 6 * 60 * 60
CHINA81_HORIZON_END_SECOND = 22 * 60 * 60
FLEET_CAP_SEMANTICS = (
    "FINITE_CONSTRUCTED_FLEET_AUTHORITY_REQUIRED_FOR_FORMAL_SEARCH"
)

_STATIC_INPUT_RELATIVE = Path(
    "data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723"
)
_MATRIX_RELATIVE = Path(
    "data/ChinaInstances/china81_local_directed_matrices_corrected_v10_20260723"
)
_ORDER_RELATIVE = Path(
    "data/ChinaInstances/china81_order_attributes_gis_v2_20260723/orders.csv"
)
_VEHICLE_LOCK_RELATIVE = Path(
    "data/ChinaInstances/china_parameter_lock_v2_20260718.json"
)
_RUNTIME_PARAMETER_AUTHORITY_RELATIVE = Path(
    "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
FLEET_AUTHORITY_V1_RELATIVE = Path(
    "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
FLEET_AUTHORITY_V2_RELATIVE = Path(
    "data/ChinaInstances/"
    "china81_finite_fleet_authority_v2_20260731"
)
FLEET_AUTHORITY_V3_RELATIVE = Path(
    "data/ChinaInstances/"
    "china81_finite_fleet_authority_v3_20260802"
)
_FLEET_AUTHORITY_RELATIVE = FLEET_AUTHORITY_V3_RELATIVE

_DIESEL_PRICE_CNY_PER_L_BY_CITY = {
    "beijing": 7.48,
    "tianjin": 7.43,
    "shijiazhuang": 7.43,
    "guangzhou": 7.44,
    "shenzhen": 7.44,
    "dongguan": 7.44,
    "foshan": 7.44,
    "chengdu": 7.48,
    "chongqing": 7.50,
}

_CITY_RUNTIME_MAPPING = {
    "beijing": {
        "region": "jjj",
        "price_area_id": "beijing",
        "carbon_source_column": "Beijing",
        "diesel_zone": "beijing",
    },
    "tianjin": {
        "region": "jjj",
        "price_area_id": "tianjin",
        "carbon_source_column": "Tianjin",
        "diesel_zone": "tianjin",
    },
    "shijiazhuang": {
        "region": "jjj",
        "price_area_id": "hebei_south",
        "carbon_source_column": "Hebei",
        "diesel_zone": "hebei",
    },
    "guangzhou": {
        "region": "prd",
        "price_area_id": "guangdong_prd_five_city",
        "carbon_source_column": "Guangdong",
        "diesel_zone": "guangdong",
    },
    "shenzhen": {
        "region": "prd",
        "price_area_id": "shenzhen",
        "carbon_source_column": "Guangdong",
        "diesel_zone": "guangdong",
    },
    "dongguan": {
        "region": "prd",
        "price_area_id": "guangdong_prd_five_city",
        "carbon_source_column": "Guangdong",
        "diesel_zone": "guangdong",
    },
    "foshan": {
        "region": "prd",
        "price_area_id": "guangdong_prd_five_city",
        "carbon_source_column": "Guangdong",
        "diesel_zone": "guangdong",
    },
    "chengdu": {
        "region": "cy",
        "price_area_id": "sichuan",
        "carbon_source_column": "Sichuan",
        "diesel_zone": "sichuan",
    },
    "chongqing": {
        "region": "cy",
        "price_area_id": "chongqing",
        "carbon_source_column": "Chongqing",
        "diesel_zone": "chongqing",
    },
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
    price_area_by_city: Mapping[str, str]
    carbon_source_column_by_city: Mapping[str, str]
    diesel_zone_by_city: Mapping[str, str]
    diesel_price_by_city: Mapping[str, float]
    fleet_caps_by_depot: Mapping[str, Mapping[str, int]]
    charger_scenario_by_node: Mapping[str, Mapping[str, float | int | str]]
    fleet_cap_semantics: str
    diesel_price_source_id: str
    static_input_authority: str
    road_matrix_authority: str
    runtime_parameter_authority: str
    fleet_authority: str
    model_config: Mapping[str, object]
    formal_search_allowed: bool = False


def load_china81_bundle(
    repo_root: str | Path,
    instance_id: str,
    *,
    date: str = DEFAULT_CHINA81_DATE,
    static_input_authority: str | Path | None = None,
    road_matrix_authority: str | Path | None = None,
    runtime_parameter_authority: str | Path | None = None,
    fleet_authority: str | Path | None = None,
    model_config: ModelConfig | None = None,
) -> China81Bundle:
    """Join one frozen China81 instance, rejecting missing or mixed inputs."""

    root = Path(repo_root).resolve()
    resolved_model_config = model_config or ModelConfig()
    static_root = _resolve_authority(
        root,
        static_input_authority,
        _STATIC_INPUT_RELATIVE,
    )
    matrix_authority = _resolve_authority(
        root,
        road_matrix_authority,
        _MATRIX_RELATIVE,
    )
    matrix_root = matrix_authority / "instances" / instance_id
    nodes_path = static_root / "instances" / instance_id / "nodes.csv"
    catalog_path = static_root / "instance_catalog.csv"
    static_metadata_path = static_root / "metadata.json"
    static_metadata = (
        json.loads(static_metadata_path.read_text(encoding="utf-8"))
        if static_metadata_path.is_file()
        else {}
    )
    orders_reference = static_metadata.get("orders")
    orders_path = (
        root / str(orders_reference)
        if isinstance(orders_reference, str) and orders_reference.endswith(".csv")
        else root / _ORDER_RELATIVE
    )
    if runtime_parameter_authority is None:
        parameter_root = _resolve_authority(
            root,
            None,
            _RUNTIME_PARAMETER_AUTHORITY_RELATIVE,
        )
        authority_id = str(parameter_root.relative_to(root))
        require_explicit_mapping = True
    else:
        parameter_root = Path(runtime_parameter_authority)
        if not parameter_root.is_absolute():
            parameter_root = root / parameter_root
        parameter_root = parameter_root.resolve()
        authority_id = str(parameter_root.relative_to(root))
        require_explicit_mapping = True
    calendar_path = parameter_root / "tariff_carbon_48slot_calendar.csv"
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
    if region not in {"jjj", "prd", "cy"}:
        raise ValueError(f"unsupported China81 region {region!r}")
    fleet_root = _resolve_authority(
        root,
        fleet_authority,
        _FLEET_AUTHORITY_RELATIVE,
    )
    fleet_rows = [
        row
        for row in _read_csv(fleet_root / "fleet_caps.csv")
        if row["instance_id"] == instance_id
    ]
    fleet_by_depot = {
        row["depot_id"]: row
        for row in fleet_rows
    }
    if len(fleet_by_depot) != len(fleet_rows) or not fleet_by_depot:
        raise ValueError(
            f"China81 finite fleet authority is incomplete for {instance_id}"
        )

    node_rows = _read_csv(nodes_path)
    if static_input_authority is not None:
        _validate_node_city_membership(
            static_root / "node_city_membership.csv",
            instance_id=instance_id,
            node_rows=node_rows,
        )
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

    facility_rows = {
        row["city"].strip().lower(): row
        for row in _read_csv(static_root / "facilities.csv")
    }
    nodes = [
        _node_from_rows(
            row,
            orders_by_customer,
            fleet_by_depot=fleet_by_depot,
            facility_rows=facility_rows,
            depot_charger_capacity_mode=(
                resolved_model_config.depot_charger_capacity_mode
            ),
        )
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
    depots_in_nodes = {
        node.node_id
        for node in nodes
        if node.node_type == "d"
    }
    if set(fleet_by_depot) != depots_in_nodes:
        raise ValueError(
            f"China81 finite fleet depots disagree for {instance_id}"
        )
    num_cv = sum(int(row["num_cv"]) for row in fleet_rows)
    num_ev = sum(int(row["num_ev"]) for row in fleet_rows)
    if num_cv < 1 or num_ev < 1:
        raise ValueError(
            f"China81 finite fleet has a nonpositive type cap for {instance_id}"
        )
    instance = Instance(
        nodes=nodes,
        distance_matrix=[
            list(row)
            for row in road_profiles["cv"].distance_m
        ],
        num_cv=num_cv,
        num_ev=num_ev,
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
        require_explicit_mapping=require_explicit_mapping,
    )
    city_runtime_binding = _city_runtime_binding_from_profile(
        time_profile,
        cities=cities,
        date=date,
    )
    diesel_price_values = _diesel_price_map_from_profile(
        time_profile,
        cities=cities,
        date=date,
    )
    prices = _china_prices(
        time_profile,
        diesel_price_by_city=diesel_price_values,
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
    price_area_by_city = MappingProxyType(
        {
            city: city_runtime_binding[city]["price_area_id"]
            for city in sorted(cities)
        }
    )
    carbon_source_column_by_city = MappingProxyType(
        {
            city: city_runtime_binding[city]["carbon_source_column"]
            for city in sorted(cities)
        }
    )
    diesel_zone_by_city = MappingProxyType(
        {
            city: city_runtime_binding[city]["diesel_zone"]
            for city in sorted(cities)
        }
    )
    diesel_price_by_city = MappingProxyType(
        diesel_price_values
    )
    fleet_caps_by_depot = MappingProxyType(
        {
            depot_id: MappingProxyType(
                {
                    "num_cv": int(row["num_cv"]),
                    "num_ev": int(row["num_ev"]),
                    "total_fleet_cap": int(row["total_fleet_cap"]),
                }
            )
            for depot_id, row in sorted(fleet_by_depot.items())
        }
    )
    charger_scenario_by_node = MappingProxyType(
        {
            node.node_id: MappingProxyType(
                {
                    "charger_count": (
                        int(fleet_by_depot[node.node_id]["depot_charger_count"])
                        if node.node_type == "d"
                        else int(node.station_chargers or 0)
                    ),
                    "active_concurrency_limit": (
                        DEPOT_CHARGER_CAPACITY_UNBOUNDED
                        if node.node_type == "d"
                        and resolved_model_config.depot_charger_capacity_mode
                        == DEPOT_CHARGER_CAPACITY_UNBOUNDED
                        else int(node.station_chargers or 0)
                    ),
                    "capacity_mode": (
                        resolved_model_config.depot_charger_capacity_mode
                        if node.node_type == "d"
                        else "finite_instance"
                    ),
                    "charge_power_kw": float(node.charge_power_kw),
                    "parameter_class": (
                        fleet_by_depot[node.node_id][
                            "charger_parameter_class"
                        ]
                        if node.node_type == "d"
                        else facility_rows[str(node.city)][
                            "station_parameter_class"
                        ]
                    ),
                }
            )
            for node in nodes
            if node.node_type in {"d", "f"}
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
            "finite_fleet_authority": str(
                (fleet_root / "fleet_caps.csv").relative_to(root)
            ),
            "facilities": str(
                (static_root / "facilities.csv").relative_to(root)
            ),
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
        price_area_by_city=price_area_by_city,
        carbon_source_column_by_city=carbon_source_column_by_city,
        diesel_zone_by_city=diesel_zone_by_city,
        diesel_price_by_city=diesel_price_by_city,
        fleet_caps_by_depot=fleet_caps_by_depot,
        charger_scenario_by_node=charger_scenario_by_node,
        fleet_cap_semantics=FLEET_CAP_SEMANTICS,
        diesel_price_source_id=(
            "CHINA-E3-FORMAL-RELEASE-001__2025-02-12_CITY_DEPOT_PRICE"
        ),
        static_input_authority=str(static_root.relative_to(root)),
        road_matrix_authority=str(matrix_authority.relative_to(root)),
        runtime_parameter_authority=authority_id,
        fleet_authority=str(fleet_root.relative_to(root)),
        model_config=MappingProxyType(resolved_model_config.as_metadata()),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"required China81 input is missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _resolve_authority(
    root: Path,
    supplied: str | Path | None,
    default_relative: Path,
) -> Path:
    path = root / default_relative if supplied is None else Path(supplied)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"China81 authority must be inside the repository: {resolved}"
        ) from exc
    if not resolved.is_dir():
        raise ValueError(f"China81 authority directory is missing: {resolved}")
    return resolved


def _validate_node_city_membership(
    path: Path,
    *,
    instance_id: str,
    node_rows: list[dict[str, str]],
) -> None:
    rows = [
        row
        for row in _read_csv(path)
        if row["instance_id"] == instance_id
    ]
    if len(rows) != len(node_rows):
        raise ValueError(
            f"China81 node-city certificate count disagrees for {instance_id}"
        )
    certificates = {row["node_id"]: row for row in rows}
    if len(certificates) != len(rows):
        raise ValueError(
            f"China81 node-city certificate contains duplicates for {instance_id}"
        )
    for node in node_rows:
        try:
            certificate = certificates[node["node_id"]]
        except KeyError as exc:
            raise ValueError(
                f"China81 node has no city certificate: "
                f"{instance_id}/{node['node_id']}"
            ) from exc
        expected = (
            node["city"].strip().lower(),
            round(float(node["latitude"]), 7),
            round(float(node["longitude"]), 7),
        )
        observed = (
            certificate["declared_city"].strip().lower(),
            round(float(certificate["latitude"]), 7),
            round(float(certificate["longitude"]), 7),
        )
        if expected != observed:
            raise ValueError(
                f"China81 node-city certificate binding disagrees for "
                f"{instance_id}/{node['node_id']}"
            )
        if certificate["gis_status"] != "PASS_DECLARED_CITY_BOUNDARY":
            raise ValueError(
                f"China81 node is outside its declared city: "
                f"{instance_id}/{node['node_id']}"
            )


def _node_from_rows(
    row: dict[str, str],
    orders_by_customer: dict[str, dict[str, str]],
    *,
    fleet_by_depot: dict[str, dict[str, str]],
    facility_rows: dict[str, dict[str, str]],
    depot_charger_capacity_mode: str,
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
        try:
            fleet = fleet_by_depot[node_id]
            facility = facility_rows[city]
        except KeyError as exc:
            raise ValueError(
                f"China81 depot scenario binding is missing for {node_id!r}"
            ) from exc
        return Node(
            node_type="d",
            ready_time=float(CHINA81_HORIZON_START_SECOND),
            due_time=float(CHINA81_HORIZON_END_SECOND),
            charge_power_kw=float(fleet["depot_charge_power_kw"]),
            station_chargers=(
                int(fleet["depot_charger_count"])
                if depot_charger_capacity_mode
                == DEPOT_CHARGER_CAPACITY_FINITE_INSTANCE
                else None
            ),
            **common,
        )
    if node_type == "station":
        try:
            facility = facility_rows[city]
        except KeyError as exc:
            raise ValueError(
                f"China81 station scenario binding is missing for {node_id!r}"
            ) from exc
        return Node(
            node_type="f",
            ready_time=float(CHINA81_HORIZON_START_SECOND),
            due_time=float(CHINA81_HORIZON_END_SECOND),
            charge_power_kw=float(facility["station_power_kw"]),
            station_chargers=int(facility["station_gun_count"]),
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
            vehicle_type_id="FOTON-AUMARK-ES1-EXPRESS-STAKE",
            fuel_type="electric",
            payload_capacity_kg=1_700.0,
            curb_mass_kg=2_600.0,
            gross_mass_kg=4_495.0,
            # HEIGHT_ASSUMED_SYMMETRIC_WITH_CV_FIELD_INCOMPLETE:
            # the official ES1 express sheet identifies the 1700 kg stake
            # configuration but does not publish a configuration-specific
            # overall height. The main scenario transfers the matched CV field
            # height (2.480 m); 3.05/3.25 m are preregistered sensitivities.
            frontal_area_m2=0.85 * 2.2 * 2.48,
            battery_kwh=77.28,
            drag_coefficient=0.45,
            rolling_resistance_coefficient=0.01,
            non_energy_distance_cost_per_km=0.67,
            engine_friction_kj_per_rev_l=None,
            engine_speed_rev_per_s=None,
            engine_displacement_l=None,
            traction_energy_multiplier=1.184692 * 1.112434,
            source_ids=(
                "FOTON_OFFICIAL_AUMARK_ES1_EXPRESS_STAKE_V04",
                "HEIGHT_ASSUMED_SYMMETRIC_WITH_CV_FIELD_INCOMPLETE",
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
    require_explicit_mapping: bool = False,
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
        try:
            expected_mapping = _CITY_RUNTIME_MAPPING[city]
        except KeyError as exc:
            raise ValueError(
                f"China81 calendar uses an unregistered city {city!r}"
            ) from exc
        for row in rows:
            slot = int(row["half_hour_slot"])
            minute = int(row["minute_of_day"])
            expected_minute = (slot - 1) * 30
            if minute != expected_minute:
                raise ValueError(
                    "China81 calendar slot and minute_of_day disagree for "
                    f"{city!r} on {date}: slot={slot}, minute={minute}, "
                    f"expected={expected_minute}"
                )
            if row["region"].strip().lower() != expected_mapping["region"]:
                raise ValueError(
                    f"China81 calendar city-region mapping disagrees for {city!r}"
                )
            if (
                row["carbon_source_column"].strip()
                != expected_mapping["carbon_source_column"]
            ):
                raise ValueError(
                    "China81 calendar city-carbon mapping disagrees for "
                    f"{city!r}: observed={row['carbon_source_column']!r}, "
                    f"expected={expected_mapping['carbon_source_column']!r}"
                )
            if require_explicit_mapping:
                if (
                    row.get("price_area_id", "").strip()
                    != expected_mapping["price_area_id"]
                ):
                    raise ValueError(
                        "China81 calendar city-price-area mapping disagrees "
                        f"for {city!r}"
                    )
                if (
                    row.get("diesel_zone", "").strip()
                    != expected_mapping["diesel_zone"]
                ):
                    raise ValueError(
                        "China81 calendar city-diesel-zone mapping disagrees "
                        f"for {city!r}"
                    )
                if (
                    row.get("joint_key_status", "").strip()
                    != "PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY"
                ):
                    raise ValueError(
                        "China81 calendar joint-key approval is missing "
                        f"for {city!r} on {date}, slot {slot}"
                    )
                if (
                    row.get("diesel_parameter_status", "").strip()
                    != "APPROVED_CHINA_E3_FORMAL_RELEASE_001"
                ):
                    raise ValueError(
                        "China81 calendar diesel approval is missing "
                        f"for {city!r} on {date}, slot {slot}"
                    )
            energy = float(row["public_energy_cny_per_kwh"])
            service = float(row["public_service_fee_cny_per_kwh"])
            total = float(row["public_total_cny_per_kwh"])
            values = (
                float(row["depot_energy_cny_per_kwh"]),
                energy,
                service,
                total,
                float(row["carbon_factor_kgco2e_per_kwh"]),
            )
            if not all(math.isfinite(value) and value >= 0.0 for value in values):
                raise ValueError(
                    f"China81 calendar has invalid numeric values for {city!r}"
                )
            if not math.isclose(
                energy + service,
                total,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    f"China81 public charging price components do not close for {city!r}"
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
                "price_area_id": row.get("price_area_id", ""),
                "diesel_zone": row.get("diesel_zone", ""),
                "diesel_price_candidate_cny_per_l": row.get(
                    "diesel_price_candidate_cny_per_l",
                    "",
                ),
                "diesel_candidate_status": row.get(
                    "diesel_candidate_status",
                    "",
                ),
                "diesel_price_cny_per_l": row.get(
                    "diesel_price_cny_per_l",
                    "",
                ),
                "diesel_parameter_status": row.get(
                    "diesel_parameter_status",
                    "",
                ),
                "joint_key_status": row.get(
                    "joint_key_status",
                    "",
                ),
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
    time_profile: list[dict[str, Any]],
    *,
    diesel_price_by_city: Mapping[str, float],
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
        # Compatibility field for legacy code paths; the per-type EV contract
        # above remains authoritative.
        B_battery_kwh=77.28,
        initial_ev_battery_kwh=0.0,
        diesel_price=(
            sum(float(value) for value in diesel_price_by_city.values())
            / len(diesel_price_by_city)
        ),
        diesel_price_by_city=tuple(
            sorted(diesel_price_by_city.items())
        ),
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
        # Compatibility triple for code that only ever constructs depot
        # charging.  New charging code resolves the explicit technology
        # triples below.  Montoya et al. (2017), Fig. 8, p. 13 supplies both
        # normalized shapes; the public fast shape is transparently scaled
        # from its 44 kW source to the preserved China81 60 kW station power.
        charging_curve_id=M17_22KW_NORMAL_PWL.curve_id,
        charging_soc_breakpoints=M17_22KW_NORMAL_PWL.soc_breakpoints,
        charging_relative_powers=M17_22KW_NORMAL_PWL.relative_powers,
        depot_charging_curve_id=M17_22KW_NORMAL_PWL.curve_id,
        depot_charging_soc_breakpoints=M17_22KW_NORMAL_PWL.soc_breakpoints,
        depot_charging_relative_powers=M17_22KW_NORMAL_PWL.relative_powers,
        public_charging_curve_id=M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id,
        public_charging_soc_breakpoints=(
            M17_FAST_SHAPE_SCALED_60KW_PWL.soc_breakpoints
        ),
        public_charging_relative_powers=(
            M17_FAST_SHAPE_SCALED_60KW_PWL.relative_powers
        ),
    )


def _city_runtime_binding_from_profile(
    time_profile: list[dict[str, Any]],
    *,
    cities: set[str],
    date: str,
) -> dict[str, dict[str, str]]:
    """Return the single approved runtime identity for every active city."""

    binding: dict[str, dict[str, str]] = {}
    fields = (
        "region",
        "price_area_id",
        "carbon_source_column",
        "diesel_zone",
    )
    for city in sorted(cities):
        rows = [
            row
            for row in time_profile
            if str(row["city"]).strip().lower() == city
        ]
        if len(rows) != 48:
            raise ValueError(
                f"China81 runtime binding is incomplete for "
                f"{city!r} on {date}"
            )
        observed: dict[str, str] = {}
        for field in fields:
            values = {
                str(row.get(field, "")).strip()
                for row in rows
            }
            if len(values) != 1 or not next(iter(values)):
                raise ValueError(
                    f"China81 runtime field {field!r} is not constant and "
                    f"complete for {city!r} on {date}"
                )
            observed[field] = values.pop()
        expected = _CITY_RUNTIME_MAPPING.get(city)
        if expected is None or any(
            observed[field].lower() != str(expected[field]).lower()
            for field in fields
        ):
            raise ValueError(
                f"China81 runtime joint identity disagrees for "
                f"{city!r} on {date}"
            )
        binding[city] = observed
    return binding


def _diesel_price_map_from_profile(
    time_profile: list[dict[str, Any]],
    *,
    cities: set[str],
    date: str,
) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for city in sorted(cities):
        rows = [
            row
            for row in time_profile
            if str(row["city"]).strip().lower() == city
        ]
        values = {
            float(row["diesel_price_cny_per_l"])
            for row in rows
            if row.get("diesel_parameter_status")
            == "APPROVED_CHINA_E3_FORMAL_RELEASE_001"
        }
        if len(rows) != 48 or len(values) != 1:
            raise ValueError(
                f"China81 approved diesel binding is incomplete for "
                f"{city!r} on {date}"
            )
        value = values.pop()
        expected = _DIESEL_PRICE_CNY_PER_L_BY_CITY.get(city)
        if expected is None or not math.isclose(
            value,
            expected,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                f"China81 approved diesel value disagrees for {city!r}"
            )
        mapping[city] = value
    return mapping
