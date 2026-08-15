from __future__ import annotations

from dataclasses import replace
import math
import unittest

from setp_solver.cost import charging_slot_breakdown, evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters, UK_2025_PRICES
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution


def _toy_instance() -> Instance:
    nodes = [
        Node("D0", "d", 0.0, 0.0, demand=0.0),
        Node("C1", "c", 10000.0, 0.0, demand=500.0),
        Node("C2", "c", 6000.0, 0.0, demand=200.0),
        Node("F1", "f", 10000.0, 0.0, demand=0.0, charge_power_kw=60.0),
    ]
    matrix = [
        [0.0, 10000.0, 6000.0, 5000.0],
        [10000.0, 0.0, 7000.0, 6000.0],
        [6000.0, 7000.0, 0.0, 4000.0],
        [5000.0, 6000.0, 4000.0, 0.0],
    ]
    return Instance(nodes=nodes, distance_matrix=matrix)


def _toy_solution(charge_start_second: float = 0.0, energy_kwh: float = 20.0) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id="CV1",
                vehicle_type="cv",
                home_depot_id="D0",
                node_sequence=["D0", "C1", "D0"],
            ),
            Route(
                vehicle_id="EV1",
                vehicle_type="ev",
                home_depot_id="D0",
                node_sequence=["D0", "C2", "F1", "D0"],
            ),
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id="EV1",
                station_id="F1",
                energy_kwh=energy_kwh,
                occupancy_minutes=30.0,
                charge_start_second=charge_start_second,
            )
        ],
        cross_site_services=[CrossSiteService(customer_id="C2", served_by_depot_id="D0")],
    )


def _mechanical_power_w(load_kg: float, prices: PriceParameters) -> float:
    drag_force = 0.5 * prices.c_d * prices.rho_a * prices.A_frontal * prices.v_speed_ms**2
    rolling_force = (prices.m_curb + prices.m_unit * load_kg) * prices.g0 * prices.c_r
    return (drag_force + rolling_force) * prices.v_speed_ms


def _fuel_liters(distance_m: float, load_kg: float, prices: PriceParameters) -> float:
    power_kw = _mechanical_power_w(load_kg, prices) / 1000.0
    time_s = distance_m / prices.v_speed_ms
    fuel_rate_lps = (
        prices.xi_fuel_air
        / (prices.kappa_heat * prices.psi_conv)
        * (prices.k_engine * prices.N_engine * prices.D_displace + power_kw / (prices.eta_diesel * prices.eta_tf))
    )
    return max(fuel_rate_lps, 0.0) * time_s


def _ev_drive_kwh(distance_m: float, load_kg: float, prices: PriceParameters) -> float:
    time_s = distance_m / prices.v_speed_ms
    return prices.alpha_e * _mechanical_power_w(load_kg, prices) * time_s / 3_600_000.0


class CostEvaluatorTests(unittest.TestCase):
    def test_multitrip_fixed_cost_is_charged_once_per_physical_vehicle(self) -> None:
        prices = replace(UK_2025_PRICES, vehicle_fixed_cost=170.0)
        solution = Solution(
            routes=[
                Route("CV1#T1", "cv", "D0", ["D0", "C1", "D0"]),
                Route("CV1#T2", "cv", "D0", ["D0", "C2", "D0"]),
            ]
        )

        result = evaluate(solution, _toy_instance(), [], prices)

        self.assertEqual(result["n_veh_cv"], 1)
        self.assertEqual(result["n_veh_ev"], 0)
        self.assertEqual(result["cost_fix"], 170.0)

    def test_manual_two_vehicle_bill_matches_cmem_hand_calculation(self) -> None:
        prices = UK_2025_PRICES
        carbon_profile = [{"horizon_second_start": 0.0, "actual_gco2_per_kwh": 86.0}]
        result = evaluate(
            _toy_solution(),
            _toy_instance(),
            carbon_profile,
            prices,
            carbon_quota_kg=1.0,
        )

        cv_fuel = _fuel_liters(10_000.0, 500.0, prices) + _fuel_liters(10_000.0, 0.0, prices)
        ev_drive = _ev_drive_kwh(6_000.0, 200.0, prices) + _ev_drive_kwh(4_000.0, 0.0, prices) + _ev_drive_kwh(5_000.0, 0.0, prices)
        expected_cv_direct = cv_fuel * prices.diesel_ef
        expected_ev_indirect = 20.0 * 86.0 / 1000.0
        expected_distance_total = 35_000.0
        expected = {
            "cost_fix": 2.0 * prices.vehicle_fixed_cost,
            "cost_km": (expected_distance_total / 1000.0) * prices.c_km,
            "cost_fuel": cv_fuel * prices.diesel_price,
            "cost_elec": 20.0 * prices.electricity_price,
            "cost_occ": 30.0 * prices.occupancy_fee,
            "cost_transship": 1.0 * prices.cross_site_cost,
            "cost_carbon": (expected_cv_direct + expected_ev_indirect - 1.0) * prices.carbon_price,
            "E_cv_direct": expected_cv_direct,
            "E_ev_indirect": expected_ev_indirect,
            "E_total": expected_cv_direct + expected_ev_indirect,
            "n_veh_cv": 1.0,
            "n_veh_ev": 1.0,
            "distance_total": expected_distance_total,
            "distance_cv": 20_000.0,
            "distance_ev": 15_000.0,
            "electricity_kwh": 20.0,
            "fuel_liters": cv_fuel,
            "ev_drive_kwh": ev_drive,
        }
        expected["total_cost"] = sum(
            expected[key]
            for key in [
                "cost_fix",
                "cost_km",
                "cost_fuel",
                "cost_elec",
                "cost_occ",
                "cost_transship",
                "cost_carbon",
            ]
        )

        for key, value in expected.items():
            self.assertAlmostEqual(result[key], value, places=6, msg=key)

    def test_carbon_lookup_uses_previous_hold_between_slots(self) -> None:
        prices = UK_2025_PRICES
        # v2026-06-11: carbon slot lookup now uses the shared route schedule at the charging station.
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, demand=0.0),
                Node("F1", "f", 0.0, 0.0, demand=0.0),
            ],
            distance_matrix=[
                [0.0, 44_975.0],
                [44_975.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "F1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=10.0, occupancy_minutes=1.0, charge_start_second=0.0)
            ],
        )
        carbon_profile = [
            {"horizon_second_start": 0.0, "actual_gco2_per_kwh": 86.0},
            {"horizon_second_start": 1800.0, "actual_gco2_per_kwh": 300.0},
        ]
        result = evaluate(
            solution,
            instance,
            carbon_profile,
            prices,
        )
        self.assertAlmostEqual(result["E_ev_indirect"], 10.0 * 86.0 / 1000.0, places=6)

    def test_carbon_allowance_can_make_carbon_cost_negative(self) -> None:
        prices = UK_2025_PRICES
        carbon_profile = [{"horizon_second_start": 0.0, "actual_gco2_per_kwh": 50.0}]
        result = evaluate(
            _toy_solution(energy_kwh=1.0),
            _toy_instance(),
            carbon_profile,
            prices,
            carbon_quota_kg=100.0,
        )
        self.assertLess(result["cost_carbon"], 0.0)
        self.assertAlmostEqual(result["cost_carbon"], (result["E_total"] - 100.0) * prices.carbon_price, places=6)

    # v2026-06-12: Z0a CE=inf is the no-quota baseline used to derive the
    # formal 80% allowance; finite CE still keeps buy/sell signs.
    def test_infinite_carbon_allowance_zeroes_carbon_trading_cost(self) -> None:
        prices = UK_2025_PRICES
        carbon_profile = [{"horizon_second_start": 0.0, "actual_gco2_per_kwh": 50.0}]

        result = evaluate(
            _toy_solution(energy_kwh=1.0),
            _toy_instance(),
            carbon_profile,
            prices,
            carbon_quota_kg=math.inf,
        )

        self.assertGreater(result["E_total"], 0.0)
        self.assertEqual(result["carbon_quota_kg"], math.inf)
        self.assertAlmostEqual(result["cost_carbon"], 0.0, places=9)

    def test_unit_conversions_and_ev_drive_not_billed_as_electricity(self) -> None:
        prices = UK_2025_PRICES
        carbon_profile = [{"horizon_second_start": 0.0, "actual_gco2_per_kwh": 1000.0}]
        result = evaluate(
            _toy_solution(energy_kwh=1.0),
            _toy_instance(),
            carbon_profile,
            prices,
        )
        self.assertAlmostEqual(result["cost_km"], 35.0 * prices.c_km, places=6)
        self.assertAlmostEqual(result["E_ev_indirect"], 1.0, places=6)
        self.assertGreater(result["ev_drive_kwh"], 0.0)
        self.assertAlmostEqual(result["cost_elec"], prices.electricity_price, places=6)
        self.assertFalse(math.isclose(result["cost_elec"], (1.0 + result["ev_drive_kwh"]) * prices.electricity_price, rel_tol=1e-9))

    # v2026-06-11: verify B-full multi-slot charging emissions use uniform y_skt construction.
    def test_charging_cross_slot_carbon(self) -> None:
        prices = UK_2025_PRICES
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, demand=0.0),
                Node("F1", "f", 0.0, 0.0, demand=0.0, charge_power_kw=60.0),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "F1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=10.0, occupancy_minutes=200.0 / 60.0, charge_start_second=1700.0)
            ],
        )
        carbon_profile = [
            {"horizon_second_start": 0.0, "actual_gco2_per_kwh": 100.0},
            {"horizon_second_start": 1800.0, "actual_gco2_per_kwh": 300.0},
        ]

        result = evaluate(solution, instance, carbon_profile, prices)

        self.assertAlmostEqual(result["E_ev_indirect"], (5.0 * 100.0 + 5.0 * 300.0) / 1000.0, delta=1e-9)

    # v2026-06-12: Q2 depot pre-departure charging uses the same slot carbon split as station charging.
    def test_depot_charging_cross_slot_carbon_and_depot_price(self) -> None:
        prices = UK_2025_PRICES
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, demand=0.0, due_time=10_000.0),
                Node("C1", "c", 0.0, 0.0, demand=0.0, due_time=10_000.0),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "C1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "D0", energy_kwh=10.0, occupancy_minutes=200.0 / 60.0, charge_start_second=1700.0)
            ],
        )
        carbon_profile = [
            {"horizon_second_start": 0.0, "actual_gco2_per_kwh": 100.0},
            {"horizon_second_start": 1800.0, "actual_gco2_per_kwh": 300.0},
        ]

        result = evaluate(solution, instance, carbon_profile, prices)

        self.assertAlmostEqual(result["E_ev_indirect"], (5.0 * 100.0 + 5.0 * 300.0) / 1000.0, delta=1e-9)
        self.assertAlmostEqual(result["cost_elec"], 10.0 * prices.depot_electricity_price, delta=1e-9)
        self.assertAlmostEqual(result["cost_occ"], 0.0, delta=1e-9)

    # v2026-06-12: S0 overnight depot charging wraps across the 48-slot day boundary.
    def test_depot_charging_cross_midnight_carbon_uses_cyclic_48_slot_split(self) -> None:
        prices = UK_2025_PRICES
        instance = Instance(
            nodes=[
                Node("D0", "d", 0.0, 0.0, demand=0.0, due_time=86_400.0),
                Node("C1", "c", 0.0, 0.0, demand=0.0, due_time=86_400.0),
            ],
            distance_matrix=[
                [0.0, 0.0],
                [0.0, 0.0],
            ],
        )
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "C1", "D0"])],
            charging_actions=[
                ChargingAction(
                    "EV1",
                    "D0",
                    energy_kwh=18.0,
                    occupancy_minutes=30.0,
                    charge_start_second=86_400.0 - 900.0,
                )
            ],
        )
        carbon_profile = [
            {"horizon_second_start": float(idx * 1800), "actual_gco2_per_kwh": 0.0}
            for idx in range(48)
        ]
        carbon_profile[47]["actual_gco2_per_kwh"] = 200.0
        carbon_profile[0]["actual_gco2_per_kwh"] = 100.0

        result = evaluate(solution, instance, carbon_profile, prices)
        rows = charging_slot_breakdown(
            86_400.0 - 900.0,
            1800.0,
            18.0,
            instance,
            n_slots=48,
            cyclic=True,
        )

        self.assertEqual([(row.slot_index, row.g_skt_sec, row.y_skt_kwh) for row in rows], [(47, 900.0, 9.0), (0, 900.0, 9.0)])
        self.assertAlmostEqual(result["E_ev_indirect"], (9.0 * 200.0 + 9.0 * 100.0) / 1000.0, delta=1e-9)

    # v2026-06-11: lock slot split invariants used by cost and check.
    def test_slot_split_sums(self) -> None:
        instance = Instance(nodes=[], distance_matrix=[])
        rows = charging_slot_breakdown(
            charge_start_sec=1700.0,
            occupancy_sec=200.0,
            energy_kwh=10.0,
            instance=instance,
        )

        self.assertEqual([(row.slot_index, row.g_skt_sec, row.y_skt_kwh) for row in rows], [(0, 100.0, 5.0), (1, 100.0, 5.0)])
        self.assertAlmostEqual(sum(row.g_skt_sec for row in rows), 200.0, delta=1e-9)
        self.assertAlmostEqual(sum(row.y_skt_kwh for row in rows), 10.0, delta=1e-9)


if __name__ == "__main__":
    unittest.main()
