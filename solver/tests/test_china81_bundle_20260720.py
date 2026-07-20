from __future__ import annotations

from pathlib import Path

import pytest

from setp_solver.charging_curve import NL90_MILD
from setp_solver.china81 import (
    CHINA81_HORIZON_END_SECOND,
    CHINA81_HORIZON_START_SECOND,
    FLEET_CAP_SEMANTICS,
    load_china81_bundle,
)
from setp_solver.cost import (
    charging_action_electricity_cost,
    charging_action_emissions_kg,
)
from setp_solver.algorithms.resetp_alns.support.carbon_charging import (
    ChargeOption,
    integrated_charge_carbon_kg,
    score_charge_option,
)
from setp_solver.solution import ChargingAction


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("instance_id", "region", "diesel_price"),
    [
        ("cn-jjj-10c-01-V2-LOCATIONS", "jjj", 6.87),
        ("cn-prd-10c-01-V2-LOCATIONS", "prd", 6.83),
        ("cn-cy-10c-01-V2-LOCATIONS", "cy", 6.90),
    ],
)
def test_real_china81_bundle_joins_region_vehicle_and_road_contracts(
    instance_id: str,
    region: str,
    diesel_price: float,
) -> None:
    bundle = load_china81_bundle(REPO_ROOT, instance_id)

    assert bundle.region == region
    assert bundle.date == "2025-02-12"
    assert bundle.formal_search_allowed is False
    assert bundle.fleet_cap_semantics == FLEET_CAP_SEMANTICS
    assert bundle.prices.diesel_price == pytest.approx(diesel_price)
    assert bundle.prices.charging_curve_id == NL90_MILD.curve_id
    assert bundle.prices.B_battery_kwh == pytest.approx(140.41)
    assert len(bundle.instance.nodes) == 12
    assert bundle.instance.num_cv == 10
    assert bundle.instance.num_ev == 10
    assert bundle.instance.road_profiles is not None
    assert bundle.instance.vehicle_parameters is not None
    assert bundle.instance.payload_capacity_kg(
        "cv",
        fallback=-1.0,
    ) == pytest.approx(1_735.0)
    assert bundle.instance.payload_capacity_kg(
        "ev",
        fallback=-1.0,
    ) == pytest.approx(1_000.0)
    assert bundle.instance.battery_capacity_kwh(
        fallback=-1.0,
    ) == pytest.approx(140.41)
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
