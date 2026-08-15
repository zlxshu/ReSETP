from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import pytest
import setp_solver.china81 as china81_module
from setp_solver.algorithms.resetp_alns.support.carbon_charging import (
    ChargeOption,
    integrated_charge_carbon_kg,
    score_charge_option,
)
from setp_solver.charging_action import _curve_aware_action
from setp_solver.charging_curve import (
    M17_FAST_SHAPE_SCALED_60KW_PWL,
)
from setp_solver.china81 import (
    CHINA81_HORIZON_END_SECOND,
    CHINA81_HORIZON_START_SECOND,
    FLEET_CAP_SEMANTICS,
    _china_prices,
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
from setp_solver.instance_loader import Instance, Node
from setp_solver.model_config import (
    DEPOT_CHARGER_CAPACITY_FINITE_INSTANCE,
    DEPOT_CHARGER_CAPACITY_UNBOUNDED,
    ModelConfig,
)
from setp_solver.prices import (
    DEFAULT_PRICES,
    UK_2025_PRICES,
    PriceParameters,
)
from setp_solver.private_instance_rebuild_20260811 import (
    evaluate_rebuild_solution,
    load_private_instance_rebuild,
)
from setp_solver.solution import Route, Solution

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


def test_vehicle_fixed_cost_authority_is_cv_170_ev_220() -> None:
    authority = (
        REPO_ROOT
        / "data/ChinaInstances/"
        "china81_private_rebuild_v1_20260811/vehicle_costs.csv"
    )
    with authority.open(newline="", encoding="utf-8-sig") as handle:
        rows = {
            row["vehicle_type"]: row
            for row in csv.DictReader(handle)
        }

    assert set(rows) == {"cv", "ev"}
    assert float(rows["cv"]["effective_daily_fixed_cost_cny"]) == 170.0
    assert float(rows["ev"]["effective_daily_fixed_cost_cny"]) == 220.0
    assert float(rows["ev"]["daily_fixed_premium_cny"]) == 50.0
    assert "Chen et al. 2023 Table 7" in rows["ev"]["source"]


def test_vehicle_fixed_cost_loader_drives_profiles_and_compatibility_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        china81_module,
        "_load_vehicle_fixed_costs",
        lambda _path: {"cv": 171.0, "ev": 223.0},
    )

    bundle = load_china81_bundle(
        REPO_ROOT,
        "cn-prd-10c-01-V2-LOCATIONS",
    )

    assert bundle.instance.vehicle_fixed_cost_per_day(
        "cv",
        fallback=-1.0,
    ) == pytest.approx(171.0)
    assert bundle.instance.vehicle_fixed_cost_per_day(
        "ev",
        fallback=-1.0,
    ) == pytest.approx(223.0)
    assert bundle.prices.vehicle_fixed_cost == pytest.approx(171.0)


def test_exact_cost_uses_profiled_fixed_cost_once_per_physical_vehicle() -> None:
    bundle = load_china81_bundle(REPO_ROOT, "cn-prd-10c-01-V2-LOCATIONS")
    depot = next(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    )
    customers = [
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    ]
    mixed = Solution(
        routes=[
            Route("CV1", "cv", depot, [depot, customers[0], depot]),
            Route("EV1", "ev", depot, [depot, customers[1], depot]),
        ]
    )
    ev_multitrip = Solution(
        routes=[
            Route("EV1#T1", "ev", depot, [depot, customers[0], depot]),
            Route("EV1#T2", "ev", depot, [depot, customers[1], depot]),
        ]
    )
    mismatched_fallback = replace(bundle.prices, vehicle_fixed_cost=999.0)

    mixed_cost = evaluate(
        mixed,
        bundle.instance,
        bundle.time_profile,
        mismatched_fallback,
    )
    ev_multitrip_cost = evaluate(
        ev_multitrip,
        bundle.instance,
        bundle.time_profile,
        mismatched_fallback,
    )

    assert mixed_cost["cost_fix"] == 390.0
    assert ev_multitrip_cost["n_veh_ev"] == 1
    assert ev_multitrip_cost["cost_fix"] == 220.0


@pytest.mark.parametrize(
    ("instance_id", "region", "diesel_price", "num_cv", "num_ev"),
    [
        ("cn-jjj-10c-01-V2-LOCATIONS", "jjj", 7.48, 1, 1),
        ("cn-prd-10c-01-V2-LOCATIONS", "prd", 7.44, 1, 1),
        ("cn-cy-10c-01-V2-LOCATIONS", "cy", 7.50, 1, 1),
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
    assert bundle.prices.depot_charge_power_kw == pytest.approx(60.0)
    assert bundle.prices.carbon_price == pytest.approx(0.07502)
    assert bundle.prices.carbon_price_low == pytest.approx(0.05632)
    assert bundle.prices.diesel_ef == pytest.approx(2.6419028944)
    assert bundle.prices.vehicle_fixed_cost == pytest.approx(170.0)
    assert bundle.instance.vehicle_fixed_cost_per_day(
        "cv",
        fallback=-1.0,
    ) == pytest.approx(170.0)
    assert bundle.instance.vehicle_fixed_cost_per_day(
        "ev",
        fallback=-1.0,
    ) == pytest.approx(220.0)
    assert bundle.source_paths["vehicle_cost_authority"] == (
        "data/ChinaInstances/"
        "china81_private_rebuild_v1_20260811/vehicle_costs.csv"
    )
    assert bundle.prices.charging_curve_id == (
        M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id
    )
    assert bundle.prices.depot_charging_curve_id == (
        M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id
    )
    assert bundle.prices.public_charging_curve_id == (
        M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id
    )
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
    assert bundle.prices.alpha_e == pytest.approx(
        ev.traction_energy_multiplier
    )
    assert ev.vehicle_type_id == "FOTON-AUMARK-ES1-EXPRESS-STAKE"
    assert ev.curb_mass_kg == pytest.approx(2_600.0)
    assert ev.gross_mass_kg == pytest.approx(4_495.0)
    assert ev.frontal_area_m2 == pytest.approx(0.85 * 2.2 * 2.48)
    assert ev.non_energy_distance_cost_per_km == pytest.approx(0.9145)
    assert "HEIGHT_ASSUMED_SYMMETRIC_WITH_CV_FIELD_INCOMPLETE" in ev.source_ids
    assert ev.source_ids.count(
        "BATTERY_DEPRECIATION_CHANGJIANG_2024_GOEKE_SCHNEIDER_2015"
    ) == 1
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
        int(row["hourly_calendar_row"])
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
    depots = [node for node in facilities if node.node_type == "d"]
    public_stations = [node for node in facilities if node.node_type == "f"]
    assert depots and all(node.station_chargers is None for node in depots)
    assert public_stations and all(
        node.station_chargers is not None and node.station_chargers > 0
        for node in public_stations
    )
    assert bundle.model_config["depot_charger_capacity_mode"] == (
        DEPOT_CHARGER_CAPACITY_UNBOUNDED
    )

    legacy_finite_bundle = load_china81_bundle(
        REPO_ROOT,
        instance_id,
        model_config=ModelConfig(
            depot_charger_capacity_mode=(
                DEPOT_CHARGER_CAPACITY_FINITE_INSTANCE
            )
        ),
    )
    legacy_depots = [
        node
        for node in legacy_finite_bundle.instance.nodes
        if node.node_type == "d"
    ]
    legacy_public_stations = [
        node
        for node in legacy_finite_bundle.instance.nodes
        if node.node_type == "f"
    ]
    assert legacy_depots and all(
        node.station_chargers == 2 for node in legacy_depots
    )
    assert [node.station_chargers for node in legacy_public_stations] == [
        node.station_chargers for node in public_stations
    ]

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


def test_depot_time_windows_are_default_off_and_explicitly_overridable() -> None:
    instance_id = "cn-prd-10c-01-V2-LOCATIONS"
    default_bundle = load_china81_bundle(REPO_ROOT, instance_id)
    default_depots = {
        node.node_id: (node.ready_time, node.due_time)
        for node in default_bundle.instance.nodes
        if node.node_type.lower() == "d"
    }
    assert default_depots
    assert set(default_depots.values()) == {
        (CHINA81_HORIZON_START_SECOND, CHINA81_HORIZON_END_SECOND)
    }

    explicit_windows = {
        depot_id: (28_800.0, 68_400.0)
        for depot_id in default_depots
    }
    overridden_bundle = load_china81_bundle(
        REPO_ROOT,
        instance_id,
        depot_time_windows=explicit_windows,
    )
    overridden_depots = {
        node.node_id: (node.ready_time, node.due_time)
        for node in overridden_bundle.instance.nodes
        if node.node_type.lower() == "d"
    }
    assert overridden_depots == explicit_windows


def test_scenario_sensitive_defaults_fail_closed_and_uk_values_are_named() -> None:
    for field_name in (
        "diesel_price",
        "carbon_price",
        "carbon_price_low",
        "diesel_ef",
    ):
        with pytest.raises(ValueError, match="requires an explicit scenario"):
            float(getattr(DEFAULT_PRICES, field_name))

    assert float(UK_2025_PRICES.diesel_price) == 1.4331
    assert float(UK_2025_PRICES.carbon_price) == 0.05034
    assert float(UK_2025_PRICES.carbon_price_low) == 0.04184
    assert float(UK_2025_PRICES.diesel_ef) == 2.57082

    bundle = load_china81_bundle(
        REPO_ROOT,
        "cn-prd-10c-01-V2-LOCATIONS",
    )
    with pytest.raises(ValueError, match="explicit city diesel price map"):
        replace(bundle, prices=UK_2025_PRICES)
    with pytest.raises(ValueError, match="explicit diesel_price"):
        replace(
            bundle,
            prices=replace(
                bundle.prices,
                diesel_price=float(UK_2025_PRICES.diesel_price),
            ),
        )

    depot = next(
        node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    )
    customer = next(
        node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    route = Route(
        "EV_DEFAULT_GUARD",
        "ev",
        depot.node_id,
        [depot.node_id, customer.node_id, depot.node_id],
    )
    with pytest.raises(ValueError, match="requires an explicit scenario"):
        evaluate(
            Solution(routes=[route]),
            bundle.instance,
            bundle.time_profile,
        )


def test_private_rebuild_does_not_double_apply_battery_depreciation() -> None:
    bundle = load_private_instance_rebuild(REPO_ROOT)
    ev = bundle.instance.vehicle_parameters["ev"]

    assert ev.non_energy_distance_cost_per_km == pytest.approx(0.9145)
    assert ev.source_ids.count(
        "BATTERY_DEPRECIATION_CHANGJIANG_2024_GOEKE_SCHNEIDER_2015"
    ) == 1


def test_private_rebuild_reports_ev_premium_without_double_charging() -> None:
    bundle = load_private_instance_rebuild(REPO_ROOT)
    depot = next(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    )
    customer = next(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    solution = Solution(
        routes=[Route("EV1", "ev", depot, [depot, customer, depot])]
    )

    direct = evaluate(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    wrapped = evaluate_rebuild_solution(solution, bundle)

    assert direct["cost_fix"] == 220.0
    assert wrapped["cost_fix_ev_premium"] == 50.0
    assert wrapped["cost_fix"] == direct["cost_fix"]
    assert wrapped["total_cost"] == direct["total_cost"]


def test_china81_ev_profile_is_evaluator_authority_and_divergence_fails() -> None:
    bundle = load_china81_bundle(
        REPO_ROOT,
        "cn-prd-10c-01-V2-LOCATIONS",
    )
    assert bundle.instance.vehicle_parameters is not None
    vehicle_parameters = dict(bundle.instance.vehicle_parameters)
    original_ev = vehicle_parameters["ev"]
    changed_multiplier = (
        float(original_ev.traction_energy_multiplier) * 1.125
    )
    vehicle_parameters["ev"] = replace(
        original_ev,
        traction_energy_multiplier=changed_multiplier,
    )
    changed_prices = _china_prices(
        bundle.time_profile,
        diesel_price_by_city=bundle.diesel_price_by_city,
        vehicle_parameters=vehicle_parameters,
    )
    assert changed_prices.alpha_e == pytest.approx(changed_multiplier)

    with pytest.raises(
        ValueError,
        match="traction multiplier disagrees with prices.alpha_e",
    ):
        replace(
            bundle,
            prices=replace(
                bundle.prices,
                alpha_e=float(bundle.prices.alpha_e) + 0.01,
            ),
        )


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
        carbon_price=0.0,
        carbon_price_low=0.0,
        diesel_ef=1.0,
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
    action = _curve_aware_action(
        vehicle_id="EV1",
        station_id=depot.node_id,
        start_energy_kwh=0.0,
        energy_kwh=10.0,
        reference_power_kw=bundle.prices.depot_charge_power_kw,
        prices=bundle.prices,
        instance=bundle.instance,
    )
    assert charging_action_electricity_cost(
        action,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    ) == pytest.approx(
        10.0 * float(profile_row["depot_energy_cny_per_kwh"])
    )
    assert charging_action_emissions_kg(
        action,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    ) == pytest.approx(
        10.0
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
                "hourly_calendar_row": slot,
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
            energy_kwh=10.0,
            power_kw=bundle.prices.depot_charge_power_kw,
            occupancy_seconds_override=(
                M17_FAST_SHAPE_SCALED_60KW_PWL.scale(
                    capacity_kwh=77.28,
                    reference_power_kw=(
                        bundle.prices.depot_charge_power_kw
                    ),
                ).duration_seconds(0.0, 10.0)
            ),
            start_energy_kwh=0.0,
            end_energy_kwh=10.0,
            charging_curve_id=(
                M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id
            ),
        ),
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        carbon_weight=0.0,
    )
    assert scored.electricity_cost == pytest.approx(
        10.0 * float(profile_row["depot_energy_cny_per_kwh"])
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
