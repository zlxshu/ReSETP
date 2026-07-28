from __future__ import annotations

import csv
from pathlib import Path

import pytest

from setp_solver.charging_curve import NL90_MILD
from setp_solver.china81 import (
    CHINA81_HORIZON_END_SECOND,
    CHINA81_HORIZON_START_SECOND,
    FLEET_CAP_SEMANTICS,
    _load_time_profile,
    _validate_node_city_membership,
    load_china81_bundle,
)
from setp_solver.cost import (
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    diesel_price_for_route,
    evaluate,
)
from setp_solver.algorithms.resetp_alns.support.carbon_charging import (
    ChargeOption,
    integrated_charge_carbon_kg,
    score_charge_option,
)
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.solution import ChargingAction, Route, Solution


REPO_ROOT = Path(__file__).resolve().parents[2]
CORRECTED_STATIC = (
    "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
CORRECTED_MATRICES = (
    "data/ChinaInstances/"
    "china81_local_directed_matrices_corrected_v10_20260723"
)
CORRECTED_PARAMETERS = (
    "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)


@pytest.mark.parametrize(
    ("instance_id", "region", "diesel_price", "num_cv", "num_ev"),
    [
        ("cn-jjj-10c-01-V2-LOCATIONS", "jjj", 7.48, 2, 1),
        ("cn-prd-10c-01-V2-LOCATIONS", "prd", 7.44, 3, 1),
        ("cn-cy-10c-01-V2-LOCATIONS", "cy", 7.50, 2, 1),
    ],
)
def test_real_china81_bundle_joins_region_vehicle_and_road_contracts(
    instance_id: str,
    region: str,
    diesel_price: float,
    num_cv: int,
    num_ev: int,
) -> None:
    bundle = load_china81_bundle(REPO_ROOT, instance_id)

    assert bundle.region == region
    assert bundle.date == "2025-02-12"
    assert bundle.formal_search_allowed is False
    assert bundle.fleet_cap_semantics == FLEET_CAP_SEMANTICS
    assert bundle.prices.diesel_price == pytest.approx(diesel_price)
    assert bundle.diesel_price_by_city
    assert all(
        value == pytest.approx(diesel_price)
        for value in bundle.diesel_price_by_city.values()
    )
    assert bundle.prices.charging_curve_id == NL90_MILD.curve_id
    assert bundle.prices.B_battery_kwh == pytest.approx(77.28)
    assert len(bundle.instance.nodes) == 12
    assert bundle.instance.num_cv == num_cv
    assert bundle.instance.num_ev == num_ev
    assert sum(
        int(caps["num_cv"])
        for caps in bundle.fleet_caps_by_depot.values()
    ) == num_cv
    assert sum(
        int(caps["num_ev"])
        for caps in bundle.fleet_caps_by_depot.values()
    ) == num_ev
    assert bundle.instance.road_profiles is not None
    assert bundle.instance.vehicle_parameters is not None
    assert bundle.instance.payload_capacity_kg(
        "cv",
        fallback=-1.0,
    ) == pytest.approx(1_735.0)
    assert bundle.instance.payload_capacity_kg(
        "ev",
        fallback=-1.0,
    ) == pytest.approx(1_700.0)
    assert bundle.instance.battery_capacity_kwh(
        fallback=-1.0,
    ) == pytest.approx(77.28)
    ev = bundle.instance.vehicle_parameters["ev"]
    assert ev.vehicle_type_id == "FOTON-AUMARK-ES1-EXPRESS-STAKE"
    assert ev.curb_mass_kg == pytest.approx(2_600.0)
    assert ev.gross_mass_kg == pytest.approx(4_495.0)
    assert ev.frontal_area_m2 == pytest.approx(0.85 * 2.2 * 2.48)
    assert "HEIGHT_ASSUMED_SYMMETRIC_WITH_CV_FIELD_INCOMPLETE" in ev.source_ids
    customers = [
        node
        for node in bundle.instance.nodes
        if node.node_type == "c"
    ]
    node_lookup = {
        node.node_id: node
        for node in bundle.instance.nodes
    }
    assert set(bundle.customer_home_depot) == {
        node.node_id
        for node in customers
    }
    assert all(
        node_lookup[bundle.customer_home_depot[node.node_id]].city
        == node.city
        for node in customers
    )
    assert len(bundle.time_profile) == 48
    assert {
        int(row["half_hour_slot"])
        for row in bundle.time_profile
    } == set(range(1, 49))
    facilities = [
        node
        for node in bundle.instance.nodes
        if node.node_type in {"d", "f"}
    ]
    assert facilities
    assert all(
        node.ready_time == CHINA81_HORIZON_START_SECOND
        and node.due_time == CHINA81_HORIZON_END_SECOND
        for node in facilities
    )

    first = bundle.instance.nodes[0].node_id
    second = bundle.instance.nodes[1].node_id
    for vehicle_type in ("cv", "ev"):
        distance, duration, sum_v2d = bundle.instance.arc_metrics(
            first,
            second,
            vehicle_type,
            fallback_speed_mps=25.0,
        )
        assert distance > 0.0
        assert duration > 0.0
        assert sum_v2d > 0.0


def test_diesel_cost_uses_route_origin_depot_city() -> None:
    instance = Instance(
        nodes=[
            Node("D_A", "d", 0.0, 0.0, city="a"),
            Node("D_B", "d", 0.0, 0.0, city="b"),
            Node("C_A", "c", 0.0, 0.0, demand=1.0, city="a"),
            Node("C_B", "c", 0.0, 0.0, demand=1.0, city="b"),
        ],
        distance_matrix=[
            [0.0, 0.0, 1_000.0, 1_000.0],
            [0.0, 0.0, 1_000.0, 1_000.0],
            [1_000.0, 1_000.0, 0.0, 0.0],
            [1_000.0, 1_000.0, 0.0, 0.0],
        ],
    )
    prices = PriceParameters(
        diesel_price=99.0,
        diesel_price_by_city=(("a", 7.0), ("b", 8.0)),
    )
    route_a = Route("CV-A", "cv", "D_A", ["D_A", "C_A", "D_A"])
    route_b = Route("CV-B", "cv", "D_B", ["D_B", "C_B", "D_B"])

    assert diesel_price_for_route(route_a, instance, prices) == 7.0
    assert diesel_price_for_route(route_b, instance, prices) == 8.0
    fuel_a = evaluate(
        Solution(routes=[route_a]),
        instance,
        [],
        prices,
        carbon_quota_kg=float("inf"),
    )
    fuel_b = evaluate(
        Solution(routes=[route_b]),
        instance,
        [],
        prices,
        carbon_quota_kg=float("inf"),
    )
    assert fuel_b["fuel_liters"] == pytest.approx(fuel_a["fuel_liters"])
    assert fuel_b["cost_fuel"] / fuel_a["cost_fuel"] == pytest.approx(8.0 / 7.0)


def test_china81_customer_order_and_city_tariff_are_runtime_inputs() -> None:
    bundle = load_china81_bundle(
        REPO_ROOT,
        "cn-cy-10c-01-V2-LOCATIONS",
    )
    customer = next(
        node
        for node in bundle.instance.nodes
        if node.node_type == "c"
    )
    assert customer.demand > 0.0
    assert customer.ready_time > 0.0
    assert customer.due_time > customer.ready_time
    assert customer.service_time > 0.0
    assert customer.city == "chongqing"

    depot = next(
        node
        for node in bundle.instance.nodes
        if node.node_type == "d"
    )
    profile_row = min(
        bundle.time_profile,
        key=lambda row: float(row["horizon_second_start"]),
    )
    action = ChargingAction(
        vehicle_id="EV1",
        station_id=depot.node_id,
        energy_kwh=11.0,
        occupancy_minutes=30.0,
        charge_start_second=0.0,
        start_energy_kwh=0.0,
        end_energy_kwh=11.0,
        charging_curve_id=NL90_MILD.curve_id,
    )
    assert charging_action_electricity_cost(
        action,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    ) == pytest.approx(
        11.0 * float(profile_row["depot_energy_cny_per_kwh"])
    )
    assert charging_action_emissions_kg(
        action,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    ) == pytest.approx(
        11.0
        * float(profile_row["actual_gco2_per_kwh"])
        / 1_000.0
    )


def test_china81_bundle_fails_closed_for_unknown_instance_or_date() -> None:
    with pytest.raises(ValueError, match="exactly one row"):
        load_china81_bundle(REPO_ROOT, "not-a-china81-instance")

    with pytest.raises(ValueError, match="48 unique slots"):
        load_china81_bundle(
            REPO_ROOT,
            "cn-cy-10c-01-V2-LOCATIONS",
            date="2025-03-01",
        )


def _write_calendar_fixture(
    path: Path,
    *,
    corrupt_slot: int | None = None,
    carbon_source_column: str = "Beijing",
    price_area_id: str = "beijing",
    diesel_zone: str = "beijing",
    joint_key_status: str = "PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY",
    diesel_parameter_status: str = (
        "APPROVED_CHINA_E3_FORMAL_RELEASE_001"
    ),
) -> None:
    rows = []
    for slot in range(1, 49):
        minute = (slot - 1) * 30
        if slot == corrupt_slot:
            minute += 30
        rows.append(
            {
                "city": "beijing",
                "region": "jjj",
                "date": "2025-02-12",
                "half_hour_slot": slot,
                "minute_of_day": minute,
                "tariff_period": "flat",
                "depot_energy_cny_per_kwh": 0.5,
                "public_energy_cny_per_kwh": 0.5,
                "public_service_fee_cny_per_kwh": 0.4,
                "public_total_cny_per_kwh": 0.9,
                "carbon_factor_kgco2e_per_kwh": 0.6,
                "tariff_row_class": "TEST",
                "service_fee_class": "TEST",
                "carbon_source_column": carbon_source_column,
                "price_area_id": price_area_id,
                "diesel_zone": diesel_zone,
                "diesel_price_cny_per_l": 7.48,
                "diesel_parameter_status": diesel_parameter_status,
                "joint_key_status": joint_key_status,
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_china81_calendar_rejects_slot_minute_disagreement(
    tmp_path: Path,
) -> None:
    path = tmp_path / "calendar.csv"
    _write_calendar_fixture(path, corrupt_slot=17)

    with pytest.raises(ValueError, match="slot and minute_of_day disagree"):
        _load_time_profile(
            path,
            cities={"beijing"},
            date="2025-02-12",
        )


def test_china81_calendar_rejects_wrong_carbon_column(
    tmp_path: Path,
) -> None:
    path = tmp_path / "calendar.csv"
    _write_calendar_fixture(path, carbon_source_column="Chongqing")

    with pytest.raises(ValueError, match="city-carbon mapping disagrees"):
        _load_time_profile(
            path,
            cities={"beijing"},
            date="2025-02-12",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "price_area_id",
            "tianjin",
            "city-price-area mapping disagrees",
        ),
        (
            "diesel_zone",
            "hebei",
            "city-diesel-zone mapping disagrees",
        ),
        (
            "joint_key_status",
            "",
            "joint-key approval is missing",
        ),
        (
            "diesel_parameter_status",
            "",
            "diesel approval is missing",
        ),
    ],
)
def test_china81_calendar_rejects_broken_joint_parameter_key(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    path = tmp_path / "calendar.csv"
    _write_calendar_fixture(path, **{field: value})

    with pytest.raises(ValueError, match=message):
        _load_time_profile(
            path,
            cities={"beijing"},
            date="2025-02-12",
            require_explicit_mapping=True,
        )


def test_china81_mechanism_scoring_uses_the_station_city() -> None:
    bundle = load_china81_bundle(
        REPO_ROOT,
        "cn-cy-10c-01-V2-LOCATIONS",
    )
    depot = next(
        node
        for node in bundle.instance.nodes
        if node.node_type == "d"
    )
    profile_row = min(
        bundle.time_profile,
        key=lambda row: float(row["horizon_second_start"]),
    )

    with pytest.raises(ValueError, match="requires a station id"):
        integrated_charge_carbon_kg(
            0.0,
            1_800.0,
            11.0,
            bundle.instance,
            bundle.time_profile,
        )
    observed_carbon = integrated_charge_carbon_kg(
        0.0,
        1_800.0,
        11.0,
        bundle.instance,
        bundle.time_profile,
        station_id=depot.node_id,
    )
    assert observed_carbon == pytest.approx(
        11.0
        * float(profile_row["actual_gco2_per_kwh"])
        / 1_000.0
    )

    scored = score_charge_option(
        ChargeOption(
            station_id=depot.node_id,
            node_type="d",
            earliest_start_second=0.0,
            latest_start_second=0.0,
            energy_kwh=11.0,
            power_kw=22.0,
            occupancy_seconds_override=1_800.0,
            start_energy_kwh=0.0,
            end_energy_kwh=11.0,
            charging_curve_id=NL90_MILD.curve_id,
        ),
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        carbon_weight=0.0,
    )
    assert scored.electricity_cost == pytest.approx(
        11.0 * float(profile_row["depot_energy_cny_per_kwh"])
    )


def test_corrected_china81_bundle_binds_explicit_authorities_and_city_maps() -> None:
    bundle = load_china81_bundle(
        REPO_ROOT,
        "cn-prd-50c-01-V2-LOCATIONS",
        static_input_authority=CORRECTED_STATIC,
        road_matrix_authority=CORRECTED_MATRICES,
        runtime_parameter_authority=CORRECTED_PARAMETERS,
    )

    assert bundle.static_input_authority == CORRECTED_STATIC
    assert bundle.road_matrix_authority == CORRECTED_MATRICES
    assert bundle.runtime_parameter_authority == CORRECTED_PARAMETERS
    assert bundle.formal_search_allowed is False
    assert bundle.price_area_by_city == {
        "guangzhou": "guangdong_prd_five_city",
        "shenzhen": "shenzhen",
    }
    assert bundle.carbon_source_column_by_city == {
        "guangzhou": "Guangdong",
        "shenzhen": "Guangdong",
    }
    assert bundle.diesel_zone_by_city == {
        "guangzhou": "guangdong",
        "shenzhen": "guangdong",
    }
    assert {
        (row["city"], row["price_area_id"], row["carbon_source_column"])
        for row in bundle.time_profile
    } == {
        ("guangzhou", "guangdong_prd_five_city", "Guangdong"),
        ("shenzhen", "shenzhen", "Guangdong"),
    }
    assert bundle.prices.diesel_price == pytest.approx(7.44)
    assert bundle.diesel_price_by_city == {
        "guangzhou": pytest.approx(7.44),
        "shenzhen": pytest.approx(7.44),
    }
    assert dict(bundle.prices.diesel_price_by_city) == pytest.approx(
        bundle.diesel_price_by_city
    )
    assert {
        row["diesel_parameter_status"]
        for row in bundle.time_profile
    } == {"APPROVED_CHINA_E3_FORMAL_RELEASE_001"}


def test_node_city_certificate_rejects_coordinate_or_city_drift(
    tmp_path: Path,
) -> None:
    certificate = tmp_path / "node_city_membership.csv"
    certificate.write_text(
        (
            "instance_id,node_id,node_type,declared_city,latitude,longitude,"
            "source_identity,gis_status,boundary_memberships,"
            "boundary_source_date,boundary_source_class\n"
            "demo,C001,customer,shenzhen,22.5431000,114.0579000,"
            "fixture,PASS_DECLARED_CITY_BOUNDARY,shenzhen,2026-07-16,"
            "COMPUTATIONAL_VALIDATION_BOUNDARY_NOT_OFFICIAL_CHINA_SURVEY\n"
        ),
        encoding="utf-8",
    )
    node_rows = [
        {
            "node_id": "C001",
            "node_type": "customer",
            "city": "guangzhou",
            "latitude": "23.1291000",
            "longitude": "113.2644000",
        }
    ]

    with pytest.raises(
        ValueError,
        match="node-city certificate binding disagrees",
    ):
        _validate_node_city_membership(
            certificate,
            instance_id="demo",
            node_rows=node_rows,
        )
