from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import pytest

from setp_solver.check import CAPACITY, check_solution
from setp_solver.cost import (
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    charging_curve_for_action,
    cv_instance_arc_fuel_liters,
    ev_instance_arc_energy_kwh,
    evaluate,
    route_node_schedule,
    time_profile_rows_for_node,
)
from setp_solver.instance_loader import (
    Instance,
    Node,
    RoadProfileMatrices,
    VehicleTypeParameters,
    load_profiled_road_matrices,
)
from setp_solver.prices import PriceParameters, UK_2025_PRICES
from setp_solver.search.dynamic import _rebuild_instance_matrix
from setp_solver.search.multitrip_schedule import build_multitrip_certificate
from setp_solver.solution import ChargingAction, Route, Solution


REPO_ROOT = Path(__file__).resolve().parents[2]
CHINA_MATRIX_ROOT = (
    REPO_ROOT
    / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718"
    / "instances/cn-cy-10c-01-V2-LOCATIONS"
)
CHINA_NODES = (
    REPO_ROOT
    / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
    / "instances/cn-cy-10c-01-V2-LOCATIONS/nodes.csv"
)


def _nodes() -> list[Node]:
    return [
        Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
        Node(
            "C1",
            "c",
            1.0,
            0.0,
            demand=250.0,
            due_time=100_000.0,
        ),
    ]


def _matrix(
    distance_m: float,
    duration_s: float,
    sum_v2d_m3_s2: float,
) -> RoadProfileMatrices:
    return RoadProfileMatrices(
        distance_m=((0.0, distance_m), (distance_m, 0.0)),
        duration_s=((0.0, duration_s), (duration_s, 0.0)),
        sum_v2d_m3_s2=(
            (0.0, sum_v2d_m3_s2),
            (sum_v2d_m3_s2, 0.0),
        ),
    )


def _vehicles() -> dict[str, VehicleTypeParameters]:
    return {
        "cv": VehicleTypeParameters(
            vehicle_type_id="test-cv",
            fuel_type="diesel",
            payload_capacity_kg=3_650.0,
            curb_mass_kg=6_350.0,
            gross_mass_kg=10_000.0,
            frontal_area_m2=3.912,
            battery_kwh=None,
            drag_coefficient=0.7,
            rolling_resistance_coefficient=0.01,
            non_energy_distance_cost_per_km=0.35,
            engine_friction_kj_per_rev_l=0.2,
            engine_speed_rev_per_s=33.0,
            engine_displacement_l=5.0,
            traction_energy_multiplier=None,
            source_ids=("test",),
        ),
        "ev": VehicleTypeParameters(
            vehicle_type_id="test-ev",
            fuel_type="electric",
            payload_capacity_kg=3_650.0,
            curb_mass_kg=6_350.0,
            gross_mass_kg=10_000.0,
            frontal_area_m2=3.912,
            battery_kwh=80.0,
            drag_coefficient=0.7,
            rolling_resistance_coefficient=0.01,
            non_energy_distance_cost_per_km=0.35,
            engine_friction_kj_per_rev_l=None,
            engine_speed_rev_per_s=None,
            engine_displacement_l=None,
            traction_energy_multiplier=1.184692 * 1.112434,
            source_ids=("test",),
        ),
    }


def _profiled_instance(
    *,
    distance_m: float = 1_000.0,
    duration_s: float = 100.0,
    sum_v2d_m3_s2: float = 100_000.0,
) -> Instance:
    profile = _matrix(
        distance_m,
        duration_s,
        sum_v2d_m3_s2,
    )
    return Instance(
        nodes=_nodes(),
        distance_matrix=[[0.0, distance_m], [distance_m, 0.0]],
        road_profiles={"cv": profile, "ev": profile},
        vehicle_parameters=_vehicles(),
        demand_mass_per_unit_kg=1.0,
    )


def _china_vehicles() -> dict[str, VehicleTypeParameters]:
    alpha_e = 1.184692 * 1.112434
    return {
        "cv": VehicleTypeParameters(
            vehicle_type_id="JAC-WL-K7-G12J8-G12K8-box",
            fuel_type="diesel",
            payload_capacity_kg=1_735.0,
            curb_mass_kg=2_565.0,
            gross_mass_kg=4_495.0,
            frontal_area_m2=4.6376,
            battery_kwh=None,
            drag_coefficient=0.45,
            rolling_resistance_coefficient=0.01,
            non_energy_distance_cost_per_km=0.78,
            engine_friction_kj_per_rev_l=0.2,
            engine_speed_rev_per_s=33.0,
            engine_displacement_l=5.0,
            traction_energy_multiplier=None,
            source_ids=("JAC_OFFICIAL", "GOEKE_2015_TRANSFER"),
        ),
        "ev": VehicleTypeParameters(
            vehicle_type_id="FOTON-AUMARK-ES1-140-box",
            fuel_type="electric",
            payload_capacity_kg=1_000.0,
            curb_mass_kg=3_300.0,
            gross_mass_kg=4_495.0,
            frontal_area_m2=6.0775,
            battery_kwh=140.41,
            drag_coefficient=0.45,
            rolling_resistance_coefficient=0.01,
            non_energy_distance_cost_per_km=0.67,
            engine_friction_kj_per_rev_l=None,
            engine_speed_rev_per_s=None,
            engine_displacement_l=None,
            traction_energy_multiplier=alpha_e,
            source_ids=("FOTON_OFFICIAL", "GOEKE_2015_TRANSFER"),
        ),
    }


def _china_profiled_instance(*, demand: float = 250.0) -> Instance:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
        Node(
            "C1",
            "c",
            1.0,
            0.0,
            demand=demand,
            due_time=100_000.0,
        ),
    ]
    profile = _matrix(1_000.0, 100.0, 100_000.0)
    return Instance(
        nodes=nodes,
        distance_matrix=[[0.0, 1_000.0], [1_000.0, 0.0]],
        road_profiles={"cv": profile, "ev": profile},
        vehicle_parameters=_china_vehicles(),
        demand_mass_per_unit_kg=1.0,
    )


def _solution() -> Solution:
    return Solution(
        routes=[
            Route("CV1", "cv", "D0", ["D0", "C1", "D0"]),
            Route("EV1", "ev", "D0", ["D0", "C1", "D0"]),
        ]
    )


def test_constant_speed_profile_reproduces_legacy_cost_and_clock() -> None:
    prices = replace(UK_2025_PRICES, v_speed_ms=10.0)
    legacy = Instance(
        nodes=_nodes(),
        distance_matrix=[[0.0, 1_000.0], [1_000.0, 0.0]],
    )
    profiled = _profiled_instance()

    legacy_metrics = evaluate(_solution(), legacy, [], prices)
    profile_metrics = evaluate(_solution(), profiled, [], prices)
    for key in (
        "distance_total",
        "fuel_liters",
        "ev_drive_kwh",
        "cost_fuel",
        "total_cost",
    ):
        assert profile_metrics[key] == pytest.approx(
            legacy_metrics[key],
            rel=1e-12,
            abs=1e-12,
        )

    route = _solution().routes[1]
    assert route_node_schedule(
        route,
        profiled,
        prices,
    ) == route_node_schedule(route, legacy, prices)
    assert legacy.arc_metrics(
        "D0",
        "C1",
        "ev",
        fallback_speed_mps=10.0,
    ) == pytest.approx((1_000.0, 100.0, 100_000.0))


def test_public_cv_arc_helper_closes_to_route_fuel() -> None:
    prices = replace(UK_2025_PRICES, v_speed_ms=10.0)
    instance = _profiled_instance()
    route_solution = Solution(
        routes=[Route("CV1", "cv", "D0", ["D0", "C1", "D0"])]
    )
    expected = evaluate(
        route_solution,
        instance,
        [],
        prices,
    )["fuel_liters"]
    observed = cv_instance_arc_fuel_liters(
        instance,
        "D0",
        "C1",
        250.0,
        prices,
    ) + cv_instance_arc_fuel_liters(
        instance,
        "C1",
        "D0",
        0.0,
        prices,
    )
    assert observed == pytest.approx(expected, rel=1e-12, abs=1e-12)


def test_duration_drives_clock_and_cv_idle_fuel_but_not_ev_traction() -> None:
    prices = replace(UK_2025_PRICES, v_speed_ms=10.0)
    fast = _profiled_instance(duration_s=100.0)
    slow = _profiled_instance(duration_s=200.0)
    cv = Solution(
        routes=[Route("CV1", "cv", "D0", ["D0", "C1", "D0"])]
    )
    ev = Solution(
        routes=[Route("EV1", "ev", "D0", ["D0", "C1", "D0"])]
    )

    fast_cv = evaluate(cv, fast, [], prices)
    slow_cv = evaluate(cv, slow, [], prices)
    fast_ev = evaluate(ev, fast, [], prices)
    slow_ev = evaluate(ev, slow, [], prices)

    assert slow_cv["fuel_liters"] > fast_cv["fuel_liters"]
    assert slow_ev["ev_drive_kwh"] == pytest.approx(
        fast_ev["ev_drive_kwh"],
    )
    fast_schedule = route_node_schedule(cv.routes[0], fast, prices)
    slow_schedule = route_node_schedule(cv.routes[0], slow, prices)
    assert slow_schedule[1].t_arrive - fast_schedule[1].t_arrive == pytest.approx(
        100.0
    )


def test_profile_contract_is_immutable_and_fails_closed() -> None:
    profile = _matrix(1_000.0, 100.0, 100_000.0)
    instance = _profiled_instance()
    with pytest.raises(TypeError):
        instance.road_profiles["cv"] = profile  # type: ignore[index]

    with pytest.raises(ValueError, match="exactly CV and EV"):
        Instance(
            nodes=_nodes(),
            distance_matrix=[[0.0, 1_000.0], [1_000.0, 0.0]],
            road_profiles={"cv": profile},
            vehicle_parameters=_vehicles(),
            demand_mass_per_unit_kg=1.0,
        )

    invalid = RoadProfileMatrices(
        distance_m=((1.0, 1_000.0), (1_000.0, 0.0)),
        duration_s=profile.duration_s,
        sum_v2d_m3_s2=profile.sum_v2d_m3_s2,
    )
    with pytest.raises(ValueError, match="diagonal"):
        Instance(
            nodes=_nodes(),
            distance_matrix=[[0.0, 1_000.0], [1_000.0, 0.0]],
            road_profiles={"cv": invalid, "ev": profile},
            vehicle_parameters=_vehicles(),
            demand_mass_per_unit_kg=1.0,
        )


def test_real_china81_two_profile_six_matrix_package_loads() -> None:
    kind = {"depot": "d", "station": "f", "customer": "c"}
    with CHINA_NODES.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    nodes = [
        Node(
            row["node_id"],
            kind[row["node_type"]],
            float(row["longitude"]),
            float(row["latitude"]),
        )
        for row in rows
    ]
    profiles = load_profiled_road_matrices(CHINA_MATRIX_ROOT, nodes)
    instance = Instance(
        nodes=nodes,
        distance_matrix=[
            list(row)
            for row in profiles["cv"].distance_m
        ],
        road_profiles=profiles,
        vehicle_parameters=_vehicles(),
        demand_mass_per_unit_kg=1.0,
    )

    assert set(instance.road_profiles) == {"cv", "ev"}
    assert len(instance.road_profiles["cv"].distance_m) == 12
    distance, duration, sum_v2d = instance.arc_metrics(
        nodes[0].node_id,
        nodes[1].node_id,
        "cv",
        fallback_speed_mps=25.0,
    )
    assert distance > 0.0
    assert duration > 0.0
    assert sum_v2d > 0.0


def test_matrix_loader_rejects_any_missing_matrix(tmp_path: Path) -> None:
    nodes = _nodes()
    header = "node_id,D0,C1\n"
    body = "D0,0,1\nC1,1,0\n"
    for profile in ("cv", "ev"):
        root = tmp_path / profile
        root.mkdir()
        for name in (
            "road_distance_m.csv",
            "road_duration_s.csv",
            "road_sum_v2d_m3_s2.csv",
        ):
            (root / name).write_text(
                header + body,
                encoding="utf-8",
            )
    (tmp_path / "ev/road_duration_s.csv").unlink()

    with pytest.raises(ValueError, match="required road matrix is missing"):
        load_profiled_road_matrices(tmp_path, nodes)


def test_china_vehicle_capacity_and_cost_are_type_specific() -> None:
    instance = _china_profiled_instance(demand=1_200.0)
    cv = Solution(
        routes=[Route("CV1", "cv", "D0", ["D0", "C1", "D0"])]
    )
    ev = Solution(
        routes=[Route("EV1", "ev", "D0", ["D0", "C1", "D0"])]
    )

    assert not any(
        violation.type == CAPACITY
        for violation in check_solution(cv, instance)
    )
    assert any(
        violation.type == CAPACITY
        for violation in check_solution(ev, instance)
    )

    both = evaluate(
        Solution(routes=[*cv.routes, *ev.routes]),
        instance,
        [],
        UK_2025_PRICES,
    )
    assert both["cost_km"] == pytest.approx(
        2.0 * 0.78 + 2.0 * 0.67,
    )


def test_china_ev_battery_scales_curve_and_certificate_identity() -> None:
    instance = _china_profiled_instance()
    prices = PriceParameters(initial_ev_battery_kwh=140.41)
    action = ChargingAction(
        vehicle_id="EV1",
        station_id="D0",
        energy_kwh=140.41,
        occupancy_minutes=140.41 / 22.0 * 60.0,
        charge_start_second=0.0,
        start_energy_kwh=0.0,
        end_energy_kwh=140.41,
        charging_curve_id="L100_control",
    )
    curve_state = charging_curve_for_action(action, instance, prices)
    assert curve_state is not None
    curve, _, _ = curve_state
    assert curve.capacity_kwh == pytest.approx(140.41)

    certificate = build_multitrip_certificate(
        [Route("EV1", "ev", "D0", ["D0", "C1", "D0"])],
        instance,
        prices,
    )
    assert certificate.battery_capacity_kwh == pytest.approx(140.41)
    assert (
        certificate.charging_curve_physical_sha256
        == curve.physical_parameter_sha256
    )


def test_china_ev_energy_matches_independent_vehicle_formula() -> None:
    instance = _china_profiled_instance()
    prices = PriceParameters()
    load_kg = 250.0
    observed = ev_instance_arc_energy_kwh(
        instance,
        "D0",
        "C1",
        load_kg,
        prices,
    )
    vehicle = _china_vehicles()["ev"]
    mechanical_j = (
        0.5
        * vehicle.drag_coefficient
        * prices.rho_a
        * vehicle.frontal_area_m2
        * 100_000.0
        + (
            vehicle.curb_mass_kg
            + load_kg
        )
        * prices.g0
        * vehicle.rolling_resistance_coefficient
        * 1_000.0
    )
    expected = (
        float(vehicle.traction_energy_multiplier)
        * mechanical_j
        / 3_600_000.0
    )
    assert observed == pytest.approx(expected, rel=1e-12)


def test_profiled_dynamic_rebuild_preserves_subsets_and_rejects_new_nodes() -> None:
    instance = _china_profiled_instance()
    subset = _rebuild_instance_matrix(instance, [instance.nodes[0]])
    assert subset.road_profiles is not None
    assert subset.vehicle_parameters is not None
    assert subset.demand_mass_per_unit_kg == 1.0

    with pytest.raises(
        ValueError,
        match="precomputed CV/EV road metrics",
    ):
        _rebuild_instance_matrix(
            instance,
            [
                *instance.nodes,
                Node("N1", "c", 2.0, 0.0, demand=1.0),
            ],
        )


def test_profiled_instance_requires_explicit_demand_mass_unit() -> None:
    profile = _matrix(1_000.0, 100.0, 100_000.0)
    with pytest.raises(ValueError, match="demand-mass unit"):
        Instance(
            nodes=_nodes(),
            distance_matrix=[[0.0, 1_000.0], [1_000.0, 0.0]],
            road_profiles={"cv": profile, "ev": profile},
            vehicle_parameters=_china_vehicles(),
        )


def test_city_specific_tariff_and_carbon_follow_charging_node() -> None:
    instance = Instance(
        nodes=[
            Node(
                "D_beijing",
                "d",
                0.0,
                0.0,
                due_time=100_000.0,
                city="beijing",
            ),
            Node(
                "S_chongqing",
                "f",
                1.0,
                0.0,
                due_time=100_000.0,
                city="chongqing",
            ),
        ],
        distance_matrix=[[0.0, 1_000.0], [1_000.0, 0.0]],
    )
    time_profile = [
        {
            "city": "beijing",
            "horizon_second_start": 0.0,
            "actual_gco2_per_kwh": 100.0,
            "depot_energy_cny_per_kwh": 0.4,
            "public_total_cny_per_kwh": 1.4,
        },
        {
            "city": "beijing",
            "horizon_second_start": 1_800.0,
            "actual_gco2_per_kwh": 200.0,
            "depot_energy_cny_per_kwh": 0.5,
            "public_total_cny_per_kwh": 1.5,
        },
        {
            "city": "chongqing",
            "horizon_second_start": 0.0,
            "actual_gco2_per_kwh": 800.0,
            "depot_energy_cny_per_kwh": 0.8,
            "public_total_cny_per_kwh": 1.8,
        },
        {
            "city": "chongqing",
            "horizon_second_start": 1_800.0,
            "actual_gco2_per_kwh": 900.0,
            "depot_energy_cny_per_kwh": 0.9,
            "public_total_cny_per_kwh": 1.9,
        },
    ]
    depot_action = ChargingAction(
        vehicle_id="EV1",
        station_id="D_beijing",
        energy_kwh=10.0,
        occupancy_minutes=30.0,
        charge_start_second=0.0,
    )
    station_action = ChargingAction(
        vehicle_id="EV2",
        station_id="S_chongqing",
        energy_kwh=10.0,
        occupancy_minutes=30.0,
        charge_start_second=0.0,
    )

    assert charging_action_electricity_cost(
        depot_action,
        instance,
        time_profile,
    ) == pytest.approx(4.0)
    assert charging_action_emissions_kg(
        depot_action,
        instance,
        time_profile,
    ) == pytest.approx(1.0)
    assert charging_action_electricity_cost(
        station_action,
        instance,
        time_profile,
    ) == pytest.approx(18.0)
    assert charging_action_emissions_kg(
        station_action,
        instance,
        time_profile,
    ) == pytest.approx(8.0)


def test_city_profile_fails_closed_but_legacy_shared_profile_still_works() -> None:
    missing_city = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
        ],
        distance_matrix=[[0.0]],
    )
    city_profile = [
        {
            "city": "beijing",
            "horizon_second_start": 0.0,
            "actual_gco2_per_kwh": 100.0,
        }
    ]
    with pytest.raises(ValueError, match="has no city"):
        time_profile_rows_for_node(
            missing_city,
            "D0",
            city_profile,
        )

    shared_profile = [
        {
            "horizon_second_start": 0.0,
            "actual_gco2_per_kwh": 100.0,
        }
    ]
    assert (
        time_profile_rows_for_node(
            missing_city,
            "D0",
            shared_profile,
        )
        is shared_profile
    )
