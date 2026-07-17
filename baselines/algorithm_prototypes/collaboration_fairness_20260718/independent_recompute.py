"""Independent arithmetic replay for the collaboration/fairness micro-probe."""

from __future__ import annotations


def recompute(
    *,
    customer_rows: list[dict[str, object]],
    assignment: dict[str, str],
    standalone_profit: dict[str, float],
    theta: float,
) -> dict[str, object]:
    depots = tuple(sorted(standalone_profit))
    expected = {str(row["customer_id"]) for row in customer_rows}
    if set(assignment) != expected or any(depot not in depots for depot in assignment.values()):
        return {"feasible": False}

    profit = {depot: 0.0 for depot in depots}
    cost_total = 0.0
    indexed = {str(row["customer_id"]): row for row in customer_rows}
    for customer_id in sorted(assignment):
        depot = assignment[customer_id]
        row = indexed[customer_id]
        service_cost = dict(row["service_cost"])
        cost = float(service_cost[depot])
        revenue = float(row["revenue"])
        cost_total += cost
        profit[depot] += revenue - cost

    deficit = {
        depot: max(0.0, theta * standalone_profit[depot] - profit[depot])
        for depot in depots
    }
    return {
        "feasible": True,
        "total_cost": cost_total,
        "profit": profit,
        "deficit": deficit,
        "total_deficit": sum(deficit.values()),
    }
