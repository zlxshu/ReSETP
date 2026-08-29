from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from setp_solver.enterprise_accounting import build_enterprise_ledger
from setp_solver.profit import DepotProfitBreakdown
from setp_solver.solution import Solution


def _row(cost: float) -> DepotProfitBreakdown:
    return DepotProfitBreakdown(
        depot_id="D0",
        revenue=100.0,
        cost_fixed=cost,
        cost_km=0.0,
        cost_fuel=0.0,
        cost_electricity=0.0,
        cost_carbon=0.0,
        cost_total=cost,
        profit=100.0 - cost,
        customers_served=1,
        demand_kg=10.0,
        emissions_kg=0.0,
        cv_direct_emissions_kg=0.0,
        ev_indirect_emissions_kg=0.0,
        depot_charging_kwh=0.0,
        station_charging_kwh=0.0,
    )


def test_ledger_serializes_existing_route_owner_accounting() -> None:
    bundle = SimpleNamespace(
        instance=object(),
        time_profile=[],
        prices=object(),
        customer_home_depot={"C0": "D0"},
    )
    with patch(
        "setp_solver.enterprise_accounting.calculate_depot_profits",
        return_value={"D0": _row(40.0)},
    ) as calculator:
        ledger = build_enterprise_ledger(
            instance_id="instance",
            solution=Solution(),
            bundle=bundle,
            prior_profit={"D0": 0.0},
            carbon_quota_kg=0.0,
            expected_total_cost=40.0,
        )

    assert ledger["rows"]["D0"]["profit"] == 60.0
    assert calculator.call_count == 1


def test_ledger_rejects_cost_that_does_not_close() -> None:
    bundle = SimpleNamespace(
        instance=object(),
        time_profile=[],
        prices=object(),
        customer_home_depot={},
    )
    with patch(
        "setp_solver.enterprise_accounting.calculate_depot_profits",
        return_value={"D0": _row(40.0)},
    ), pytest.raises(RuntimeError, match="HALT_ACCOUNTING_MISMATCH"):
        build_enterprise_ledger(
            instance_id="instance",
            solution=Solution(),
            bundle=bundle,
            prior_profit={"D0": 0.0},
            carbon_quota_kg=0.0,
            expected_total_cost=41.0,
        )
