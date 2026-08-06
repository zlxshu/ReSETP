from __future__ import annotations

from setp_solver.algorithms.resetp_alns.support import charging as formal_charging
from setp_solver.charging_action import _curve_aware_action as shared_action
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search import charging as historical_charging


def test_formal_and_historical_charging_use_one_neutral_action_builder() -> None:
    assert formal_charging._curve_aware_action is shared_action
    assert historical_charging._curve_aware_action is shared_action


def test_shared_action_preserves_energy_and_ledger_fields() -> None:
    action = shared_action(
        vehicle_id="ev-1",
        station_id="f-1",
        start_energy_kwh=5.0,
        energy_kwh=10.0,
        reference_power_kw=22.0,
        prices=DEFAULT_PRICES,
    )
    assert action.vehicle_id == "ev-1"
    assert action.station_id == "f-1"
    assert action.energy_kwh == 10.0
    assert action.start_energy_kwh == 5.0
    assert action.end_energy_kwh == 15.0
    assert action.occupancy_minutes > 0.0
    assert action.charging_curve_id
