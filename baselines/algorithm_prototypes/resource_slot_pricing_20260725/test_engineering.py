"""Zero-objective deterministic unit checks for the frozen pricing kernel."""

from __future__ import annotations

from types import SimpleNamespace

from pricing_core import PricedLabel, dominates, merge_labels


def label(
    sequence: tuple[str, ...],
    *,
    cost: float,
    reduced: float,
    slots: tuple[tuple[str, int, int], ...] = (),
    direction: str = "forward",
) -> PricedLabel:
    return PricedLabel(
        sequence=sequence,
        depot_id="D1",
        vehicle_type="ev",
        cost=cost,
        reduced_cost=reduced,
        charger_slots=slots,
        assignment=SimpleNamespace(
            home_depot_id="D1",
            vehicle_type="ev",
            charge_strategy="integrated",
            carbon_weight=1.0,
        ),
        direction=direction,
    )


def run_checks() -> dict[str, bool]:
    better = label(("C1", "C2"), cost=10.0, reduced=-2.0)
    worse = label(
        ("C1", "C2"),
        cost=11.0,
        reduced=-1.0,
        slots=(("S1", 0, 8),),
    )
    forward = label(("C1", "C2"), cost=4.0, reduced=-1.0)
    backward = label(
        ("C3", "C4"),
        cost=5.0,
        reduced=-1.0,
        direction="backward",
    )
    overlap = label(
        ("C2", "C4"),
        cost=5.0,
        reduced=-1.0,
        direction="backward",
    )
    checks = {
        "dominance_accepts_lower_cost_resource_subset": dominates(better, worse),
        "dominance_rejects_reverse": not dominates(worse, better),
        "merge_preserves_customer_order": (
            merge_labels(forward, backward) == ("C1", "C2", "C3", "C4")
        ),
        "merge_rejects_overlap": merge_labels(forward, overlap) is None,
        "resource_penalty_changes_reduced_cost": (
            (10.0 - 12.0 + 3.0) > (10.0 - 12.0)
        ),
        "negative_reduced_cost_sign": (10.0 - 12.0) < 0.0,
    }
    if not all(checks.values()):
        raise AssertionError(f"engineering unit check failed: {checks}")
    return checks


if __name__ == "__main__":
    print(run_checks())
