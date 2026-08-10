from types import SimpleNamespace

from setp_solver.algorithms.problem_hgs.readiness import (
    advance_idle_ev_readiness,
    observed_single_order_envelope,
    observed_single_order_reserves_kwh,
)
from setp_solver.charging_curve import NL90_MILD
from setp_solver.instance_loader import Instance, Node
from setp_solver.search.dynamic_multitrip_schedule import DynamicAssetState
from setp_solver.check import BATTERY, CAPACITY, Violation
from setp_solver.algorithms.problem_hgs.evaluation import (
    _remove_certified_dynamic_battery_duplicates,
)


def _prices():
    return SimpleNamespace(
        B_battery_kwh=40.0,
        depot_charge_power_kw=20.0,
        charging_curve_id=NL90_MILD.curve_id,
        charging_soc_breakpoints=NL90_MILD.soc_breakpoints,
        charging_relative_powers=NL90_MILD.relative_powers,
        v_speed_ms=10.0,
        alpha_e=1.0,
        c_d=0.7,
        rho_a=1.225,
        A_frontal=3.0,
        m_curb=2000.0,
        m_unit=1.0,
        g0=9.81,
        c_r=0.01,
    )


def _bundle():
    instance = Instance(
        nodes=[
            Node("D1", "d", 0, 0, 0, 0, 100000, 0),
            Node("C1", "c", 1, 0, 100, 0, 100000, 0),
            Node("C2", "c", 2, 0, 200, 0, 100000, 0),
        ],
        distance_matrix=[
            [0.0, 1000.0, 2000.0],
            [1000.0, 0.0, 1000.0],
            [2000.0, 1000.0, 0.0],
        ],
    )
    return SimpleNamespace(
        instance=instance,
        prices=_prices(),
        customer_home_depot={"C1": "D1", "C2": "D1"},
    )


def test_observed_reserve_uses_visible_customers_only() -> None:
    bundle = _bundle()
    one = observed_single_order_reserves_kwh(bundle, {"C1"})
    two = observed_single_order_reserves_kwh(bundle, {"C1", "C2"})

    assert one["D1"] > 0.0
    assert two["D1"] > one["D1"]


def test_observed_envelope_reports_orders_beyond_one_battery() -> None:
    bundle = _bundle()
    bundle.prices.B_battery_kwh = 0.001

    envelope = observed_single_order_envelope(bundle, {"C2"})

    assert envelope.target_by_depot_kwh["D1"] == 0.001
    assert envelope.over_capacity_customer_ids_by_depot == {"D1": ("C2",)}


def test_idle_ev_charge_advances_nonlinear_battery_without_touching_cv() -> None:
    states = {
        "EV_D1_1": DynamicAssetState("EV_D1_1", "ev", "D1", 100.0, 0.0, 1),
        "CV_D1_1": DynamicAssetState("CV_D1_1", "cv", "D1", 100.0, 0.0, 1),
    }
    advanced, intervals = advance_idle_ev_readiness(
        states,
        idle_asset_ids={"EV_D1_1"},
        target_by_depot_kwh={"D1": 10.0},
        interval_start_second=100.0,
        interval_end_second=1000.0,
        instance=_bundle().instance,
        prices=_prices(),
    )

    assert len(intervals) == 1
    assert advanced["EV_D1_1"].remaining_battery_kwh == 5.0
    assert advanced["CV_D1_1"] == states["CV_D1_1"]
    action = intervals[0].as_reserved_action()
    assert action.vehicle_id == "EV_D1_1"
    assert action.start_energy_kwh == 0.0
    assert action.end_energy_kwh == 5.0


def test_only_certified_future_battery_duplicates_are_removed() -> None:
    violations = [
        Violation(BATTERY, "EV_D1_1#T2", "D1->C1", "static zero-start"),
        Violation(BATTERY, "EV_D1_1#T1", "D1->C0", "historical defect"),
        Violation(CAPACITY, "EV_D1_1#T2", "C1", "real capacity defect"),
    ]

    kept = _remove_certified_dynamic_battery_duplicates(
        violations,
        {"EV_D1_1#T2"},
    )

    assert kept == [violations[1], violations[2]]
