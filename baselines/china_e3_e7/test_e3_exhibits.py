"""Result-blind unit tests for E3 paper exhibit reductions."""

from __future__ import annotations

import pytest

from baselines.china_e3_e7.charts import _axis_limits
from baselines.china_e3_e7.e3_exhibits import (
    CUSTOMER_SIZES,
    REGIONS,
    build_e3_cell_rows,
    build_e3_layer_rows,
)


def _rows(
    *,
    treatment_multiplier: float = 0.99,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for region_index, region in enumerate(REGIONS):
        for size in CUSTOMER_SIZES:
            for map_index in range(1, 4):
                instance_id = (
                    f"cn-{region}-{size}c-{map_index:02d}-"
                    "V2-LOCATIONS"
                )
                for seed in range(1, 6):
                    control = (
                        1_000.0
                        + 10.0 * size
                        + 100.0 * region_index
                    )
                    for arm, cost, cross_site in (
                        (
                            "status_quo_responsibility",
                            control,
                            0,
                        ),
                        (
                            "optimized_responsibility_cooperation",
                            control * treatment_multiplier,
                            region_index + 1,
                        ),
                    ):
                        rows.append(
                            {
                                "record_type": "formal_run",
                                "family": "E3",
                                "status": "PASS",
                                "feasible": "true",
                                "instance_id": instance_id,
                                "region": region,
                                "customer_size": str(size),
                                "map_index": str(map_index),
                                "seed": str(seed),
                                "arm": arm,
                                "arm_id": arm,
                                "total_cost": str(cost),
                                "cross_site_service_count": str(
                                    cross_site
                                ),
                                "service_level": "1",
                                "complete_candidate_attempts": "80",
                                "wallclock_safety_triggered": "false",
                            }
                        )
    return rows


def test_e3_exhibits_reduce_810_rows_to_27_cells_and_10_table_rows() -> None:
    cells = build_e3_cell_rows(_rows())
    layers = build_e3_layer_rows(cells)
    assert len(cells) == 27
    assert len(layers) == 10
    assert all(
        row["cost_reduction_percent"]
        == pytest.approx(1.0)
        for row in cells
    )
    assert layers[-1]["region"] == "overall"
    assert layers[-1]["cell_count"] == 27


def test_e3_exhibits_preserve_an_unfavourable_treatment_direction() -> None:
    cells = build_e3_cell_rows(
        _rows(treatment_multiplier=1.01)
    )
    assert all(
        row["cost_reduction_percent"] < 0.0
        for row in cells
    )
    lower, upper = _axis_limits(
        [
            float(row["cost_reduction_percent"])
            for row in cells
        ]
    )
    assert lower < 0.0
    assert upper == 0.0


def test_e3_exhibits_fail_closed_on_missing_row_or_wrong_budget() -> None:
    rows = _rows()
    with pytest.raises(ValueError, match="exactly 810"):
        build_e3_cell_rows(rows[:-1])
    rows[0]["complete_candidate_attempts"] = "79"
    with pytest.raises(ValueError, match="non-80"):
        build_e3_cell_rows(rows)
