from __future__ import annotations

from dataclasses import replace

import pytest

import setp_solver.algorithms.resetp_alns.support.charging as charging_module
from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging_candidates,
)
from setp_solver.charge_timing import (
    ChargeTimingContexts,
    charge_timing_objective_value,
    select_charge_timing_start,
)
from setp_solver.charging_action import _curve_aware_action
from setp_solver.charging_curve import M17_FAST_SHAPE_SCALED_60KW_PWL
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters, UK_2025_PRICES
from setp_solver.solution import ChargingAction, Route


def _prices() -> PriceParameters:
    curve = M17_FAST_SHAPE_SCALED_60KW_PWL
    return replace(
        UK_2025_PRICES,
        B_battery_kwh=77.28,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=60.0,
        charging_curve_id=curve.curve_id,
        charging_soc_breakpoints=curve.soc_breakpoints,
        charging_relative_powers=curve.relative_powers,
        depot_charging_curve_id=curve.curve_id,
        depot_charging_soc_breakpoints=curve.soc_breakpoints,
        depot_charging_relative_powers=curve.relative_powers,
        public_charging_curve_id=curve.curve_id,
        public_charging_soc_breakpoints=curve.soc_breakpoints,
        public_charging_relative_powers=curve.relative_powers,
    )


def _instance() -> Instance:
    return Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=80_000.0, city="gz"),
            Node(
                "C1",
                "c",
                0.0,
                0.0,
                demand=100.0,
                due_time=50_000.0,
                city="gz",
            ),
            Node(
                "F1",
                "f",
                0.0,
                0.0,
                due_time=50_000.0,
                charge_power_kw=60.0,
                city="gz",
            ),
            Node(
                "F2",
                "f",
                0.0,
                0.0,
                due_time=50_000.0,
                charge_power_kw=60.0,
                city="fs",
            ),
        ],
        distance_matrix=[
            [0.0, 100_000.0, 20_000.0, 25_000.0],
            [100_000.0, 0.0, 20_000.0, 25_000.0],
            [20_000.0, 20_000.0, 0.0, 10_000.0],
            [25_000.0, 25_000.0, 10_000.0, 0.0],
        ],
        num_ev=1,
        num_cv=0,
    )


def _profile() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for city, offset in (("gz", 0.0), ("fs", 25.0)):
        for slot in range(48):
            rows.append(
                {
                    "city": city,
                    "time_index": slot,
                    "horizon_second_start": float(slot * 1_800),
                    "actual_gco2_per_kwh": float(
                        420.0 + offset - 9.0 * (slot % 7)
                    ),
                    "forecast_gco2_per_kwh": float(
                        420.0 + offset - 9.0 * (slot % 7)
                    ),
                    "depot_energy_cny_per_kwh": float(
                        0.55 + 0.08 * (slot % 4)
                    ),
                    "public_total_cny_per_kwh": float(
                        1.10 + 0.07 * (slot % 5)
                    ),
                }
            )
    return rows


def _action_signature(
    candidates: list[tuple[str, Route, list[ChargingAction]]],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            label,
            tuple(route.node_sequence),
            tuple(
                (
                    float(action.charge_start_second),
                    float(action.energy_kwh),
                    int(action.charge_day_offset),
                    action.station_id,
                )
                for action in actions
            ),
        )
        for label, route, actions in candidates
    )


@pytest.mark.parametrize(
    ("station_id", "start_energy", "energy", "earliest", "latest"),
    (
        ("D0", 0.0, 58.0, 0.0, 12_000.0),
        ("F1", 18.0, 42.0, 900.0, 15_000.0),
        ("F2", 31.0, 34.0, 2_700.0, 18_000.0),
    ),
)
@pytest.mark.parametrize(
    "policy",
    ("asap", "carbon_min", "cost_min", "cost_plus_carbon"),
)
def test_precomputed_timing_is_bitwise_identical_to_reference(
    station_id: str,
    start_energy: float,
    energy: float,
    earliest: float,
    latest: float,
    policy: str,
) -> None:
    instance = _instance()
    prices = _prices()
    profile = _profile()
    power = (
        float(prices.depot_charge_power_kw)
        if station_id == "D0"
        else 60.0
    )
    action = _curve_aware_action(
        vehicle_id="EV1",
        station_id=station_id,
        start_energy_kwh=start_energy,
        energy_kwh=energy,
        reference_power_kw=power,
        prices=prices,
        instance=instance,
    )
    contexts = ChargeTimingContexts(instance, prices)

    reference_start = select_charge_timing_start(
        action,
        earliest_start_second=earliest,
        latest_start_second=latest,
        instance=instance,
        carbon_profile=profile,
        prices=prices,
        charge_timing_policy=policy,
    )
    optimized_start = select_charge_timing_start(
        action,
        earliest_start_second=earliest,
        latest_start_second=latest,
        instance=instance,
        carbon_profile=profile,
        prices=prices,
        charge_timing_policy=policy,
        timing_contexts=contexts,
    )
    assert optimized_start == reference_start

    reference_action = replace(
        action,
        charge_start_second=reference_start,
    )
    optimized_action = replace(
        action,
        charge_start_second=optimized_start,
    )
    assert charge_timing_objective_value(
        optimized_action,
        instance,
        profile,
        prices,
        charge_timing_policy=policy,
        timing_contexts=contexts,
    ) == charge_timing_objective_value(
        reference_action,
        instance,
        profile,
        prices,
        charge_timing_policy=policy,
    )


@pytest.mark.parametrize(
    ("strategy", "timing_policy", "amount_strategy"),
    (
        ("integrated", "cost_plus_carbon", "just_enough"),
        ("integrated", "cost_min", "soc_85"),
        ("legacy", "carbon_min", "max_coverage"),
    ),
)
def test_route_repair_actions_match_reference_exactly(
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
    timing_policy: str,
    amount_strategy: str,
) -> None:
    instance = _instance()
    prices = _prices()
    profile = _profile()
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
    kwargs = {
        "strategy": strategy,
        "charge_timing_policy": timing_policy,
        "charge_amount_strategy": amount_strategy,
        "public_station_candidate_mode": "parallel",
    }

    with monkeypatch.context() as reference_patch:
        reference_patch.setattr(
            charging_module,
            "_get_charging_repair_runtime",
            lambda *args, **kwargs: None,
        )
        reference = repair_route_charging_candidates(
            route,
            instance,
            profile,
            prices,
            **kwargs,
        )

    charging_module._CHARGING_REPAIR_RUNTIMES.clear()
    optimized = repair_route_charging_candidates(
        route,
        instance,
        profile,
        prices,
        **kwargs,
    )
    assert _action_signature(optimized) == _action_signature(reference)


def test_route_cache_is_deterministic_and_returns_isolated_copies() -> None:
    instance = _instance()
    prices = _prices()
    profile = _profile()
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
    charging_module._CHARGING_REPAIR_RUNTIMES.clear()

    first = repair_route_charging_candidates(
        route,
        instance,
        profile,
        prices,
        strategy="integrated",
        charge_timing_policy="cost_plus_carbon",
        public_station_candidate_mode="parallel",
    )
    expected = _action_signature(first)
    first[0][1].node_sequence.append("MUTATED")
    second = repair_route_charging_candidates(
        route,
        instance,
        profile,
        prices,
        strategy="integrated",
        charge_timing_policy="cost_plus_carbon",
        public_station_candidate_mode="parallel",
    )

    runtime = charging_module._get_charging_repair_runtime(
        instance,
        profile,
        prices,
        None,
    )
    assert runtime.hits == 1
    assert runtime.misses == 1
    assert _action_signature(second) == expected
    assert all("MUTATED" not in item[1].node_sequence for item in second)


def test_parallel_repair_skips_forced_paths_that_cannot_be_fully_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _instance()
    prices = _prices()
    profile = _profile()
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
    seen_paths: list[tuple[str, ...]] = []

    def fake_candidate(*args, forced_station_path=(), **kwargs):
        del args, kwargs
        seen_paths.append(tuple(forced_station_path))
        if not forced_station_path:
            raise ValueError("default path failed")
        station_id = forced_station_path[0]
        return (
            Route("EV1", "ev", "D0", ["D0", station_id, "C1", "D0"]),
            [ChargingAction("EV1", station_id, 1.0, 1.0, 100.0)],
        )

    monkeypatch.setattr(
        charging_module,
        "_repair_route_charging_candidate",
        fake_candidate,
    )
    charging_module._CHARGING_REPAIR_RUNTIMES.clear()

    candidates = repair_route_charging_candidates(
        route,
        instance,
        profile,
        prices,
        public_station_candidate_mode="parallel",
    )

    assert seen_paths == [(), ("F1",), ("F2",)]
    assert [label for label, _, _ in candidates] == [
        "public_path_F1",
        "public_path_F2",
    ]


def test_precomputed_timing_preserves_reference_edge_semantics() -> None:
    instance = _instance()
    prices = _prices()
    action = _curve_aware_action(
        vehicle_id="EV1",
        station_id="D0",
        start_energy_kwh=0.0,
        energy_kwh=20.0,
        reference_power_kw=float(prices.depot_charge_power_kw),
        prices=prices,
        instance=instance,
    )
    empty_profile: list[dict[str, object]] = []
    contexts = ChargeTimingContexts(instance, prices)

    assert select_charge_timing_start(
        action,
        earliest_start_second=120.0,
        latest_start_second=2_000.0,
        instance=instance,
        carbon_profile=empty_profile,
        prices=prices,
        charge_timing_policy="carbon_min",
        timing_contexts=contexts,
    ) == select_charge_timing_start(
        action,
        earliest_start_second=120.0,
        latest_start_second=2_000.0,
        instance=instance,
        carbon_profile=empty_profile,
        prices=prices,
        charge_timing_policy="carbon_min",
    )

    with pytest.raises(
        ValueError,
        match="only accepts the actual registered carbon field",
    ):
        select_charge_timing_start(
            action,
            earliest_start_second=120.0,
            latest_start_second=2_000.0,
            instance=instance,
            carbon_profile=_profile(),
            prices=prices,
            charge_timing_policy="cost_min",
            intensity_field="forecast_gco2_per_kwh",
            timing_contexts=contexts,
        )
