from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import replace
from unittest.mock import patch

import pytest

import setp_solver.check as check_module
from setp_solver.algorithms.problem_hgs.charging import (
    ChargingRepairFailure,
    ChargingRepairPolicy,
    repair_changed_duties,
)
from setp_solver.algorithms.problem_hgs.contracts import SearchAccounting
from setp_solver.algorithms.problem_hgs.evaluation import (
    DutyEvaluationContext,
)
from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.algorithms.problem_hgs.schedule_oracle import (
    OracleStatus,
    ScheduleCoordinator,
    ScheduleOracleContext,
    SingleDutyScheduleOracle,
    build_capacity_calendar,
)
from setp_solver.charging_action import _curve_aware_action
from setp_solver.china81 import (
    CHINA81_CARBON_PRICE_CNY_PER_KG,
    CHINA81_CARBON_PRICE_LOW_CNY_PER_KG,
    CHINA81_DIESEL_EF_KG_PER_L,
    China81Bundle,
)
from setp_solver.cost import evaluate as evaluate_cost
from setp_solver.instance_loader import Instance, Node
from setp_solver.solution import Solution
from solver.tests.china_test_prices import CHINA_TEST_PRICES


def _profile() -> list[dict[str, float]]:
    return [
        {
            "horizon_second_start": float(index * 1800),
            "actual_gco2_per_kwh": float(100 + index),
            "depot_energy_cny_per_kwh": float(1 + index % 3),
            "public_total_cny_per_kwh": float(3 + index % 2),
        }
        for index in range(48)
    ]


def _linear_prices(**changes):
    return replace(
        CHINA_TEST_PRICES,
        charging_curve_id="L100_control",
        charging_soc_breakpoints=(0.0, 1.0),
        charging_relative_powers=(1.0,),
        depot_charging_curve_id=None,
        depot_charging_soc_breakpoints=None,
        depot_charging_relative_powers=None,
        public_charging_curve_id=None,
        public_charging_soc_breakpoints=None,
        public_charging_relative_powers=None,
        **changes,
    )


def _minimum_context() -> DutyEvaluationContext:
    nodes = [
        Node(
            "D",
            "d",
            0.0,
            0.0,
            city="beijing",
            ready_time=0.0,
            due_time=12_000.0,
            station_chargers=1,
        ),
        Node("E", "c", 0.0, 0.0, demand=1.0, ready_time=0.0, due_time=2_000.0),
        Node("L", "c", 0.0, 0.0, demand=1.0, ready_time=5_000.0, due_time=7_000.0),
        Node("T", "c", 0.0, 0.0, demand=1.0, ready_time=7_500.0, due_time=9_500.0),
    ]
    instance = Instance(
        nodes=nodes,
        distance_matrix=[
            [0.0, 600.0, 600.0, 600.0],
            [600.0, 0.0, 100.0, 100.0],
            [600.0, 100.0, 0.0, 100.0],
            [600.0, 100.0, 100.0, 0.0],
        ],
        num_cv=1,
        num_ev=1,
    )
    prices = _linear_prices(
        v_speed_ms=1.0,
        B_battery_kwh=1.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=1.0,
        diesel_price=7.48,
        diesel_price_by_city=(("beijing", 7.48),),
        carbon_price=CHINA81_CARBON_PRICE_CNY_PER_KG,
        carbon_price_low=CHINA81_CARBON_PRICE_LOW_CNY_PER_KG,
        diesel_ef=CHINA81_DIESEL_EF_KG_PER_L,
    )
    bundle = China81Bundle(
        instance_id="minimum-dss-counterexample",
        region="test",
        date="2026-08-10",
        instance=instance,
        time_profile=_profile(),
        prices=prices,
        source_paths={},
        customer_home_depot={"E": "D", "L": "D", "T": "D"},
        price_area_by_city={},
        carbon_source_column_by_city={},
        diesel_zone_by_city={},
        diesel_price_by_city={"beijing": 7.48},
        fleet_caps_by_depot={
            "D": {"num_cv": 1, "num_ev": 1, "total_fleet_cap": 2}
        },
        fleet_parameter_class_id="minimum-test",
        has_additional_total_fleet_cap=True,
        charger_scenario_by_node={},
        fleet_cap_semantics="minimum-test",
        diesel_price_source_id="minimum-test",
        static_input_authority="minimum-test",
        road_matrix_authority="minimum-test",
        runtime_parameter_authority="minimum-test",
        fleet_authority="minimum-test",
        model_config={},
        formal_search_allowed=False,
    )
    pi0 = {"D": 1.0}
    return DutyEvaluationContext(
        bundle=bundle,
        independent_profit=pi0,
        prior_profit={"D": 0.0},
        theta=1.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode="same_day_predeparture",
        fairness_enabled=False,
    )


def test_capacity_calendar_matches_checker_randomized_multisolution() -> None:
    nodes = [
        Node("D", "d", 0.0, 0.0, due_time=86_400.0, station_chargers=2),
        Node(
            "F",
            "f",
            0.0,
            0.0,
            due_time=86_400.0,
            charge_power_kw=20.0,
            station_chargers=1,
        ),
        Node(
            "F_COPY",
            "f",
            0.0,
            0.0,
            due_time=86_400.0,
            charge_power_kw=20.0,
            station_chargers=1,
            physical_station_id="F",
        ),
        Node("C", "c", 0.0, 0.0, demand=1.0, due_time=86_400.0),
    ]
    instance = Instance(
        nodes=nodes,
        distance_matrix=[[0.0] * 4 for _ in range(4)],
    )
    prices = _linear_prices(
        B_battery_kwh=10.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=10.0,
    )
    rng = random.Random(20260810)
    node_lookup = {node.node_id: node for node in nodes}
    customer_count = 1

    for _ in range(40):
        actions = []
        for action_index in range(rng.randint(1, 12)):
            station_id = rng.choice(("D", "F", "F_COPY"))
            node = node_lookup[station_id]
            start_energy = rng.uniform(0.0, 7.0)
            energy = rng.uniform(0.1, 10.0 - start_energy)
            action = _curve_aware_action(
                vehicle_id=f"EV_{action_index % 5}#T{1 + action_index % 3}",
                station_id=station_id,
                start_energy_kwh=start_energy,
                energy_kwh=energy,
                reference_power_kw=(
                    10.0 if node.node_type == "d" else 20.0
                ),
                prices=prices,
                instance=instance,
            )
            duration = action.occupancy_minutes * 60.0
            action = replace(
                action,
                charge_start_second=rng.uniform(0.0, 86_400.0 - duration),
                charge_day_offset=rng.choice((-1, 0, 1)),
            )
            actions.append(action)
        solution = Solution(charging_actions=actions)
        captured = {}

        def capture_defaultdict(*args, **kwargs):
            value = defaultdict(*args, **kwargs)
            captured["occupied"] = value
            return value

        with patch.object(check_module, "defaultdict", capture_defaultdict):
            check_module._check_station_capacity(
                solution,
                node_lookup,
                instance,
                prices,
            )
        actual = build_capacity_calendar(solution, instance, prices)
        assert {
            key: set(entry.occupied_action_vehicle_ids)
            for key, entry in actual.items()
        } == dict(captured["occupied"])
        for key, entry in actual.items():
            assert entry.capacity == check_module._station_chargers(
                node_lookup[key[0]],
                customer_count,
            )


def test_every_terminal_label_is_differentially_priced_and_mismatch_rejected() -> None:
    context = _minimum_context()
    compiled = ScheduleOracleContext.from_evaluation_context(context)
    duty = PhysicalVehicleDuty(
        "EV_D_1",
        "ev",
        "D",
        (DutyTrip(1, ("E",)),),
    )
    result = SingleDutyScheduleOracle(compiled).solve(duty)
    assert result.status == OracleStatus.FEASIBLE
    assert result.frontier
    assert result.accounting["schedule_oracle_pricing_mismatches"] == 0

    station = compiled.stations["D"]
    bad_station = replace(
        station,
        price_by_slot=tuple(value + 1.0 for value in station.price_by_slot),
    )
    bad_context = replace(
        compiled,
        stations={**compiled.stations, "D": bad_station},
    )
    rejected = SingleDutyScheduleOracle(bad_context).solve(duty)
    assert rejected.status == OracleStatus.INFEASIBLE
    assert rejected.failure_reason == "CURVE_MISMATCH"
    assert rejected.accounting["schedule_oracle_pricing_mismatches"] > 0


def test_minimum_counterexample_reordering_and_charge_clock_remove_diesel() -> None:
    context = _minimum_context()
    policy = ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode="same_day_predeparture",
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )
    distance_order = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "EV_D_1",
                "ev",
                "D",
                (DutyTrip(1, ("L",)), DutyTrip(2, ("E",))),
            ),
            PhysicalVehicleDuty(
                "CV_D_1",
                "cv",
                "D",
                (DutyTrip(1, ("T",)),),
            ),
        ),
        source="minimum-distance-order",
    )
    reordered_all_ev = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "EV_D_1",
                "ev",
                "D",
                (
                    DutyTrip(1, ("E",)),
                    DutyTrip(2, ("L",)),
                    DutyTrip(3, ("T",)),
                ),
            ),
            PhysicalVehicleDuty("CV_D_1", "cv", "D", ()),
        ),
        source="minimum-reordered-all-ev",
    )
    # 2026-09-03 (model alignment): the repair may now let a later trip wait
    # at the depot for its charge to end (paper: t_ce <= tau at d^+, the
    # departure is free), so the three-trip EV duty the schedule oracle
    # already certified feasible below is repairable as well.  Before the
    # alignment the repair bounded every window by the natural departure
    # and raised "no feasible depot charging window" here.
    repaired = repair_changed_duties(
        distance_order,
        reordered_all_ev,
        changed_duty_ids={"EV_D_1", "CV_D_1"},
        context=context,
        policy=policy,
    )
    repaired_ev = next(duty for duty in repaired.duties if duty.physical_vehicle_id == "EV_D_1")
    assert len(repaired_ev.trips) == 3
    assert any(int(session.trip_index) >= 2 for session in repaired_ev.charging_sessions)

    compiled = ScheduleOracleContext.from_evaluation_context(context)
    oracle = SingleDutyScheduleOracle(compiled)
    assert oracle.solve(distance_order.duties[0]).status == OracleStatus.INFEASIBLE
    coordinated = ScheduleCoordinator(compiled, oracle).coordinate(
        distance_order,
        reordered_all_ev,
        changed_duty_ids={"EV_D_1", "CV_D_1"},
    )
    assert coordinated.status == OracleStatus.FEASIBLE
    assert coordinated.frontier
    rescued = coordinated.frontier[0]
    assert rescued.duties[0].schedule is not None
    assert not rescued.duties[1].trips
    assert rescued.duties[1].schedule is None

    fallback = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "EV_D_1",
                "ev",
                "D",
                (DutyTrip(1, ("E",)), DutyTrip(2, ("L",))),
            ),
            PhysicalVehicleDuty(
                "CV_D_1",
                "cv",
                "D",
                (DutyTrip(1, ("T",)),),
            ),
        ),
        source="minimum-diesel-fallback",
    )
    fallback_result = ScheduleCoordinator(compiled, oracle).coordinate(
        fallback,
        fallback,
        changed_duty_ids={"EV_D_1", "CV_D_1"},
    )
    assert fallback_result.status == OracleStatus.FEASIBLE
    fallback_solution = fallback_result.frontier[0].to_solution()
    rescued_solution = rescued.to_solution()
    fallback_cost = evaluate_cost(
        fallback_solution,
        context.bundle.instance,
        context.bundle.time_profile,
        context.bundle.prices,
        carbon_quota_kg=0.0,
    )
    rescued_cost = evaluate_cost(
        rescued_solution,
        context.bundle.instance,
        context.bundle.time_profile,
        context.bundle.prices,
        carbon_quota_kg=0.0,
    )
    assert fallback_cost["n_veh_cv"] == 1
    assert rescued_cost["n_veh_cv"] == 0
    assert rescued_cost["total_cost"] < fallback_cost["total_cost"]


def test_oracle_three_states_cache_identity_and_accounting() -> None:
    context = _minimum_context()
    compiled = ScheduleOracleContext.from_evaluation_context(context)
    oracle = SingleDutyScheduleOracle(compiled)
    feasible = PhysicalVehicleDuty(
        "EV_D_1",
        "ev",
        "D",
        (DutyTrip(1, ("E",)),),
    )
    cold = oracle.solve(feasible)
    hot = oracle.solve(feasible)
    assert cold.status == OracleStatus.FEASIBLE
    assert not cold.cache_hit
    assert hot.cache_hit
    assert [item.schedule_fingerprint for item in cold.frontier] == [
        item.schedule_fingerprint for item in hot.frontier
    ]

    impossible = PhysicalVehicleDuty(
        "CV_D_1",
        "cv",
        "D",
        (DutyTrip(1, ("L",)), DutyTrip(2, ("E",))),
    )
    assert oracle.solve(impossible).status == OracleStatus.INFEASIBLE
    locked = replace(
        feasible,
        has_dynamic_commitment=True,
    )
    assert oracle.solve(locked).status == OracleStatus.SEARCH_EXHAUSTED

    accounting = SearchAccounting()
    accounting.record_schedule_oracle_result(cold)
    accounting.record_schedule_oracle_result(hot)
    payload = accounting.to_dict()
    assert payload["schedule_oracle_calls"] == 2
    assert payload["schedule_oracle_cache_hits"] == 1
    assert payload["schedule_oracle_cache_misses"] == 1
    assert payload["schedule_oracle_wall_seconds"]["samples"] == 2
