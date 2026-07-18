"""Real E7 event passport for the mechanism-specific insertion decoder."""

from __future__ import annotations

import pytest

from dynamic_event_decoder import run_real_single_event_insertion_decoder


def test_real_event_decoder_improves_and_preserves_history() -> None:
    result = run_real_single_event_insertion_decoder()
    activity = result.activity

    assert activity["complete_route_search_evaluations"] == 0
    assert activity["complete_dynamic_candidate_evaluations"] == 57
    assert activity["dynamically_feasible_candidates"] == 8
    assert activity["improvements"] == 1
    assert activity["exact_decoder_updates"] == 1
    assert result.selected_cost < result.baseline_cost - 1.0e-9
    assert activity["route_count_delta"] == -1
    assert activity["future_customer_coverage_preserved"]
    assert activity["event_served_exactly_once"]
    assert activity["cross_depot_event_service"]
    assert activity["completed_routes_frozen"] > 0
    assert activity["in_progress_routes_frozen"] > 0
    assert activity["editable_routes"] > 0
    assert activity["selected_physical_assets"] <= activity[
        "inherited_physical_assets"
    ]
    assert activity["objective_delta"] == pytest.approx(
        -29.675378723731683,
        abs=1.0e-7,
    )
