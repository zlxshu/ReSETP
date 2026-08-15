from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from setp_solver.china81 import (
    ENDOGENOUS_FLEET_PARAMETERS,
    load_china81_bundle,
)
from setp_solver.potential_pool_dynamic import (
    QIU_TRIGGER_PROTOCOL,
    TriggerEvent,
    algorithm_visible_information,
    build_trigger_batches,
    generate_constructed_dynamic_day,
    sample_algorithm_internal_scenario,
    validate_day_serviceability,
)


REPO = Path(__file__).resolve().parents[2]
REGIONS = ("cy", "jjj", "prd")


@lru_cache(maxsize=None)
def _bundles(region: str):
    potential_pool = load_china81_bundle(
        REPO,
        f"cn-{region}-150c-01-V2-LOCATIONS",
    )
    fleet_authority = load_china81_bundle(
        REPO,
        f"cn-{region}-50c-01-V2-LOCATIONS",
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    return potential_pool, fleet_authority


@lru_cache(maxsize=None)
def _day(region: str, scenario_seed: int = 3):
    potential_pool, fleet_authority = _bundles(region)
    return generate_constructed_dynamic_day(
        potential_pool,
        fleet_authority,
        customer_count=50,
        market_sampling_seed=1,
        true_order_stream_seed=2,
        algorithm_scenario_seed=scenario_seed,
    )


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(
            *(_nested_keys(item) for item in value.values())
        )
    if isinstance(value, (list, tuple)):
        return set().union(*(_nested_keys(item) for item in value))
    return set()


def test_subtraction_attack_cannot_reconstruct_future_order_list() -> None:
    day = _day("cy")
    as_of = day.actual_orders[9].appearance_second
    view = algorithm_visible_information(day, as_of_second=as_of)

    potential_ids = {
        position.potential_customer_id
        for position in view.potential_positions
    }
    revealed_ids = {
        str(order["customer_id"]) for order in view.revealed_orders
    }
    actual_ids = {order.customer_id for order in day.actual_orders}
    true_future_ids = actual_ids - revealed_ids
    subtraction_attack = potential_ids - revealed_ids

    assert len(revealed_ids) == 40
    assert len(true_future_ids) == 10
    assert len(subtraction_attack) == 110
    assert subtraction_attack != true_future_ids
    assert subtraction_attack - true_future_ids == potential_ids - actual_ids
    assert len(subtraction_attack - true_future_ids) == 100

    public_keys = _nested_keys(view.as_dict())
    assert {
        "constructed_day_instance_id",
        "market_sampling_seed",
        "true_order_stream_seed",
        "truth_stream_sha256",
        "algorithm_scenario_customer_ids",
    }.isdisjoint(public_keys)


@pytest.mark.parametrize("region", REGIONS)
def test_every_generated_order_is_directly_serviceable_at_reveal_and_trigger(
    region: str,
) -> None:
    day = _day(region)
    validations = validate_day_serviceability(day)

    assert len(validations) == 50
    assert all(item.reveal_pass for item in validations)
    assert all(item.trigger_pass for item in validations)
    for order in day.actual_orders:
        assert (
            order.appearance_second + order.direct_travel_second
            <= order.due_second + 1.0e-9
        )
        assert (
            order.trigger_second + order.direct_travel_second
            <= order.due_second + 1.0e-9
        )
        assert order.trigger_second >= order.appearance_second - 1.0e-9
        assert (
            order.trigger_second - order.appearance_second
            <= QIU_TRIGGER_PROTOCOL.interval_seconds + 1.0e-9
        )


def test_scenario_seed_cannot_change_private_actual_order_stream() -> None:
    first = _day("jjj", scenario_seed=3)
    changed_scenario = _day("jjj", scenario_seed=97)

    assert first.constructed_day_instance_id == (
        changed_scenario.constructed_day_instance_id
    )
    assert first.actual_orders == changed_scenario.actual_orders
    assert first.trigger_batches == changed_scenario.trigger_batches
    assert first.truth_stream_sha256 == changed_scenario.truth_stream_sha256
    assert first.algorithm_scenario_customer_ids != (
        changed_scenario.algorithm_scenario_customer_ids
    )
    assert first.algorithm_scenario_sha256 != (
        changed_scenario.algorithm_scenario_sha256
    )
    public_view = algorithm_visible_information(
        first,
        as_of_second=QIU_TRIGGER_PROTOCOL.reception_start_second,
    )
    assert sample_algorithm_internal_scenario(public_view) == (
        first.algorithm_scenario_orders
    )


def test_qiu_rule_triggers_on_demand_or_thirty_minute_wait_whichever_first() -> None:
    hour = 3600.0
    minute = 60.0
    events = (
        TriggerEvent("E1", "C1", 8 * hour + 5 * minute, 200.0),
        TriggerEvent("E2", "C2", 8 * hour + 10 * minute, 350.0),
        TriggerEvent("E3", "C3", 8 * hour + 20 * minute, 100.0),
        TriggerEvent("E4", "C4", 8 * hour + 45 * minute, 450.0),
        TriggerEvent("E5", "C5", 9 * hour, 100.0),
    )

    batches = build_trigger_batches(events)

    assert [batch.cause for batch in batches] == [
        "demand_threshold",
        "maximum_wait",
        "demand_threshold",
    ]
    assert [batch.trigger_second for batch in batches] == [
        8 * hour + 10 * minute,
        8 * hour + 40 * minute,
        9 * hour,
    ]
    assert [batch.event_ids for batch in batches] == [
        ("E1", "E2"),
        ("E3",),
        ("E4", "E5"),
    ]
    assert [batch.demand_kg for batch in batches] == [550.0, 100.0, 550.0]
