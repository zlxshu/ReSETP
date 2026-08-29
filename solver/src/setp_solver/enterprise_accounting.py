"""Serialize the existing depot ledger without changing its semantics.

declared_identity=PROJECT_ADAPTER
code_role=THIN_ADAPTER
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from .china81 import China81Bundle
from .profit import calculate_depot_profits
from .solution import Solution


def build_enterprise_ledger(
    *,
    instance_id: str,
    solution: Solution,
    bundle: China81Bundle,
    prior_profit: Mapping[str, float],
    carbon_quota_kg: float,
    expected_total_cost: float,
) -> dict[str, Any]:
    """Build one auditable ledger and require cost closure."""

    rows = calculate_depot_profits(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        customer_home_depot=dict(bundle.customer_home_depot),
        prior_profit=dict(prior_profit),
        carbon_quota_kg=float(carbon_quota_kg),
    )
    ledger_total = sum(row.cost_total for row in rows.values())
    if not math.isclose(
        ledger_total,
        float(expected_total_cost),
        rel_tol=1.0e-12,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError(
            "HALT_ACCOUNTING_MISMATCH: depot ledger cost does not equal "
            "the complete evaluation total"
        )
    return {
        "schema": "resetp.enterprise_ledger.v1",
        "instance_id": str(instance_id),
        "rows": {
            depot_id: asdict(row)
            for depot_id, row in sorted(rows.items())
        },
    }
