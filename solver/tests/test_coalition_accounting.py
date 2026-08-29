from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from coalition_accounting_adapter import (
    TwoEnterpriseCoalitionCosts,
    TwoEnterpriseParticipationInputs,
    allocate_two_enterprise_costs,
    coalition_value_rows,
)


def test_two_enterprise_rows_and_stdlib_upstream_shapley_allocation() -> None:
    costs = TwoEnterpriseCoalitionCosts("ENT_A", "ENT_B", 80.0, 120.0, 150.0)
    rows = coalition_value_rows(costs)

    allocation = allocate_two_enterprise_costs(
        costs,
        TwoEnterpriseParticipationInputs(
            joint_revenue={"ENT_A": 100.0, "ENT_B": 180.0},
            joint_cost_total={"ENT_A": 60.0, "ENT_B": 90.0},
            joint_profit={"ENT_A": 40.0, "ENT_B": 90.0},
            pi0_profit={"ENT_A": 35.0, "ENT_B": 45.0},
        ),
        repo_root=Path(__file__).resolve().parents[2],
    )

    assert rows == [
        {"coalition": [], "value": 0.0},
        {"coalition": ["ENT_A"], "value": 80.0},
        {"coalition": ["ENT_B"], "value": 120.0},
        {"coalition": ["ENT_A", "ENT_B"], "value": 150.0},
    ]
    assert allocation.allocated_cost == {"ENT_A": 55.0, "ENT_B": 95.0}
    assert allocation.allocated_total == 150.0
    assert allocation.allocated_profit == {"ENT_A": 60.0, "ENT_B": 70.0}
    assert allocation.operational_participation_margin == {
        "ENT_A": 5.0,
        "ENT_B": 45.0,
    }
    assert allocation.allocated_participation_margin == {
        "ENT_A": 25.0,
        "ENT_B": 25.0,
    }
