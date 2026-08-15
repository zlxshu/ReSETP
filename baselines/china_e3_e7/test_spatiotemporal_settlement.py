"""End-to-end city/date/slot settlement tests for corrected China81."""

from __future__ import annotations

import csv
from dataclasses import replace
import math

import pytest

from setp_solver.china81 import load_china81_bundle
from setp_solver.cost import (
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    diesel_price_for_route,
    time_profile_rows_for_node,
)
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.search.charging import _curve_aware_action

from baselines.china_e3_e7.formal_e3_runner import (
    REPO,
    _settlement_trace,
)


CATALOG = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723/"
    "instance_catalog.csv"
)
TEST_SLOTS = (0, 12, 47)


def _node_by_city(bundle, node_type: str):
    return {
        str(node.city).strip().lower(): node
        for node in bundle.instance.nodes
        if node.node_type.lower() == node_type
    }


def _first_instance_by_city() -> dict[str, tuple[str, str]]:
    with CATALOG.open(newline="", encoding="utf-8-sig") as handle:
        rows = sorted(
            csv.DictReader(handle),
            key=lambda row: (
                int(row["customer_count"]),
                row["instance_id"],
            ),
        )
    selected: dict[str, tuple[str, str]] = {}
    for row in rows:
        for city in row["cities"].split("|"):
            selected.setdefault(
                city,
                (row["region"], row["instance_id"]),
            )
    return selected


def test_all_nine_cities_use_one_explicit_date_slot_key() -> None:
    tested_cities: set[str] = set()
    for city, (region, instance_id) in sorted(
        _first_instance_by_city().items()
    ):
        bundle = load_china81_bundle(REPO, instance_id)
        assert bundle.region == region
        assert bundle.date == "2025-02-12"
        depots = _node_by_city(bundle, "d")
        facilities = _node_by_city(bundle, "f")
        assert city in depots
        assert city in facilities
        depot = depots[city]
        tested_cities.add(city)
        profile = time_profile_rows_for_node(
            bundle.instance,
            depot.node_id,
            bundle.time_profile,
        )
        assert len(profile) == 48
        assert {
            row["date"] for row in profile
        } == {"2025-02-12"}
        assert {
            row["price_area_id"] for row in profile
        } == {bundle.price_area_by_city[city]}
        assert {
            row["carbon_source_column"] for row in profile
        } == {bundle.carbon_source_column_by_city[city]}
        assert {
            row["diesel_zone"] for row in profile
        } == {bundle.diesel_zone_by_city[city]}
        assert {
            row["joint_key_status"] for row in profile
        } == {"PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY"}

        diesel_route = Route(
            vehicle_id=f"CV-{city}",
            vehicle_type="cv",
            home_depot_id=depot.node_id,
            node_sequence=[depot.node_id, depot.node_id],
        )
        assert math.isclose(
            diesel_price_for_route(
                diesel_route,
                bundle.instance,
                bundle.prices,
            ),
            bundle.diesel_price_by_city[city],
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )

        for slot in TEST_SLOTS:
            expected = profile[slot]
            for node, price_field in (
                (depot, "depot_energy_cny_per_kwh"),
                (
                    facilities[city],
                    "public_total_cny_per_kwh",
                ),
            ):
                template = _curve_aware_action(
                    vehicle_id=f"EV-{city}-{slot}",
                    station_id=node.node_id,
                    start_energy_kwh=0.0,
                    energy_kwh=1.0,
                    reference_power_kw=float(
                        node.charge_power_kw
                    ),
                    prices=bundle.prices,
                    instance=bundle.instance,
                )
                action: ChargingAction = replace(
                    template,
                    charge_start_second=slot * 1800.0,
                )
                electricity = charging_action_electricity_cost(
                    action,
                    bundle.instance,
                    bundle.time_profile,
                    bundle.prices,
                )
                emissions = charging_action_emissions_kg(
                    action,
                    bundle.instance,
                    bundle.time_profile,
                    bundle.prices,
                )
                assert math.isclose(
                    electricity,
                    float(expected[price_field]),
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                )
                assert math.isclose(
                    emissions,
                    float(expected["actual_gco2_per_kwh"])
                    / 1000.0,
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                )
                assert int(expected["hourly_calendar_row"]) == slot + 1
                assert math.isclose(
                    float(expected["horizon_second_start"]),
                    slot * 1800.0,
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                )
    assert tested_cities == {
        "beijing",
        "tianjin",
        "shijiazhuang",
        "guangzhou",
        "shenzhen",
        "foshan",
        "dongguan",
        "chongqing",
        "chengdu",
    }


def test_all_node_bindings_match_gis_city_certificate() -> None:
    static = (
        REPO
        / "data/ChinaInstances/"
        "china81_stage2_static_inputs_corrected_v3_20260723"
    )
    settlement = (
        REPO
        / "data/ChinaInstances/"
        "china81_spatiotemporal_settlement_authority_v1_20260723"
    )
    with (static / "node_city_membership.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        certificates = {
            (row["instance_id"], row["node_id"]): row
            for row in csv.DictReader(handle)
        }
    with (settlement / "node_parameter_binding.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        bindings = {
            (row["instance_id"], row["node_id"]): row
            for row in csv.DictReader(handle)
        }
    assert len(certificates) == 6_093
    assert set(certificates) == set(bindings)
    for key, binding in bindings.items():
        certificate = certificates[key]
        assert certificate["gis_status"] == "PASS_DECLARED_CITY_BOUNDARY"
        assert (
            certificate["declared_city"].strip().lower()
            == binding["declared_city"].strip().lower()
        )
        assert math.isclose(
            float(certificate["latitude"]),
            float(binding["latitude"]),
            rel_tol=0.0,
            abs_tol=1.0e-7,
        )
        assert math.isclose(
            float(certificate["longitude"]),
            float(binding["longitude"]),
            rel_tol=0.0,
            abs_tol=1.0e-7,
        )


def test_mixed_city_price_identity_fails_closed() -> None:
    bundle = load_china81_bundle(
        REPO,
        "cn-prd-50c-01-V2-LOCATIONS",
    )
    depot = next(
        node for node in bundle.instance.nodes if node.node_type == "d"
    )
    city = str(depot.city).strip().lower()
    template = _curve_aware_action(
        vehicle_id="EV-MIXED-KEY",
        station_id=depot.node_id,
        start_energy_kwh=0.0,
        energy_kwh=1.0,
        reference_power_kw=float(depot.charge_power_kw),
        prices=bundle.prices,
        instance=bundle.instance,
    )
    action = replace(template, charge_start_second=0.0)
    bad_profile = [
        {
            **row,
            "price_area_id": (
                "deliberately-wrong-price-area"
                if row["city"] == city
                and int(row["hourly_calendar_row"]) == 1
                else row["price_area_id"]
            ),
        }
        for row in bundle.time_profile
    ]
    bad_bundle = replace(bundle, time_profile=bad_profile)
    with pytest.raises(
        RuntimeError,
        match="joint key failed closed",
    ):
        _settlement_trace(
            Solution(charging_actions=[action]),
            bad_bundle,
        )
