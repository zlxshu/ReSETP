"""Result-direction tests that never filter or replace an E3 cell."""

from __future__ import annotations

import json

import pytest

from baselines.china_e3_e7.e3_exhibits import (
    CUSTOMER_SIZES,
    REGIONS,
)
from baselines.china_e3_e7.run_e3_result_audit import (
    summarize_e3_results,
)


def _rows(
    treatment_multiplier: float,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for region_index, region in enumerate(REGIONS):
        for size in CUSTOMER_SIZES:
            for map_index in (1, 2, 3):
                instance_id = (
                    f"cn-{region}-{size}c-{map_index:02d}-"
                    "V2-LOCATIONS"
                )
                for seed in (1, 2, 3, 4, 5):
                    pair_id = f"E3__{instance_id}__seed{seed}"
                    control = (
                        1000.0
                        + 10.0 * size
                        + 100.0 * region_index
                        + map_index
                        + seed / 10.0
                    )
                    for arm, cost, cross_site in (
                        (
                            "status_quo_responsibility",
                            control,
                            0.0,
                        ),
                        (
                            "optimized_responsibility_cooperation",
                            control * treatment_multiplier,
                            2.0,
                        ),
                    ):
                        rows.append(
                            {
                                "record_type": "formal_run",
                                "family": "E3",
                                "status": "PASS",
                                "feasible": "true",
                                "task_id": f"{pair_id}__{arm}",
                                "pair_id": pair_id,
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
                                "cross_depot_candidate_directions_json": (
                                    json.dumps(
                                        {
                                            "D1->D2": 1,
                                            "D2->D1": 1,
                                        }
                                        if arm
                                        == "optimized_responsibility_cooperation"
                                        else {}
                                    )
                                ),
                                "service_level": "1",
                                "complete_candidate_attempts": "80",
                                "wallclock_safety_triggered": "false",
                            }
                        )
    return rows


def _summary(
    treatment_multiplier: float,
) -> dict[str, str]:
    delta = 100.0 * (1.0 - treatment_multiplier)
    return {
        "status": "PASS_DATA_COMPLETE",
        "n_cells": "27",
        "mean_delta": str(delta),
        "median_delta": str(delta),
        "mean_reduction_percent": str(delta),
        "median_reduction_percent": str(delta),
        "randomization_p": (
            "0.00001" if delta > 0 else "0.75"
        ),
        "wilcoxon_p": "0.00001",
        "sign_p": "0.00001",
        "ci_low": str(delta * 0.8),
        "ci_high": str(delta * 1.2),
    }


def _preregistration() -> dict:
    return {
        "mechanism_exposure_gate": {
            "treatment_cross_site_active_cells_minimum": 27,
            "reciprocal_candidate_directions_required_in_each_region": True,
            "treatment_service_level_percent_minimum": 100.0,
        },
        "paper_strength_gate": {
            "mean_cell_cost_reduction_percent_minimum": 1.0,
            "positive_cell_count_minimum": 22,
            "cell_loss_count_maximum": 5,
            "positive_region_scale_layer_count_minimum": 9,
            "single_family_randomization_p_maximum_before_full_holm": 0.01,
        },
    }


def test_positive_e3_result_is_complete_but_holm_remains_pending() -> None:
    result = summarize_e3_results(
        _rows(0.99),
        _summary(0.99),
        _preregistration(),
    )
    assert result["formal_rows"] == 810
    assert result["paired_tasks"] == 405
    assert result["paired_cells"] == 27
    assert result["pair_counts"] == {
        "wins": 405,
        "ties": 0,
        "losses": 0,
    }
    assert result["cell_counts"] == {
        "wins": 27,
        "ties": 0,
        "losses": 0,
    }
    assert result["effect_pattern"] == (
        "POSITIVE_SINGLE_FAMILY_PENDING_FIVE_FAMILY_HOLM"
    )
    assert result["holm_adjusted_p"] is None
    assert result["paper_numeric_fill_allowed"] is True
    assert result["paper_headline_claim_allowed"] is False
    assert result["pre_registered_result_gate"]["status"] == (
        "PASS_E3_PROVISIONAL_PAPER_STRENGTH_PENDING_FIVE_FAMILY_HOLM"
    )
    assert result["pre_registered_result_gate"]["passed"] is True


def test_adverse_e3_result_is_preserved_and_not_called_success() -> None:
    result = summarize_e3_results(
        _rows(1.01),
        _summary(1.01),
        _preregistration(),
    )
    assert result["pair_counts"]["losses"] == 405
    assert result["cell_counts"]["losses"] == 27
    assert result["effect_pattern"] == "ADVERSE_RESULT"
    assert result["paper_numeric_fill_allowed"] is True
    assert result["paper_headline_claim_allowed"] is False
    assert result["pre_registered_result_gate"]["status"] == (
        "HOLD_E3_RESULT_NOT_PAPER_STRONG"
    )


def test_control_cross_site_service_fails_closed() -> None:
    rows = _rows(0.99)
    rows[0]["cross_site_service_count"] = "1"
    with pytest.raises(
        ValueError,
        match="control contains cross-site",
    ):
        summarize_e3_results(rows, _summary(0.99))
