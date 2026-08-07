"""Independent-depot outside-option construction tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from duty_hgs.evaluation import DutyFullEvaluator
from duty_hgs.independent import (
    independent_bundle,
    independent_context,
    independent_individual,
)
from duty_hgs.operators import RelocateMove
from run_real_input_technical_trial import (
    _build_context,
    _parameters,
    _policy,
    _prepare_population,
)
from setp_solver.china81_completion import annotate_cross_site_services
from setp_solver.cost import evaluate
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.multitrip_schedule import prepare_multitrip_solution

REPO = Path(__file__).resolve().parents[4]


def test_independent_subproblems_preserve_current_china81_semantics(
    evaluated_fixture,
) -> None:
    individual, evaluator = evaluated_fixture
    full_bundle = evaluator.context.bundle
    total_customers = 0
    for depot_id, caps in full_bundle.fleet_caps_by_depot.items():
        subbundle = independent_bundle(full_bundle, depot_id)
        subindividual = independent_individual(
            individual,
            full_bundle,
            depot_id,
        )
        result = DutyFullEvaluator(
            independent_context(subbundle, depot_id)
        ).evaluate(subindividual)

        assert result.feasible
        assert not result.violations
        assert set(subbundle.fleet_caps_by_depot) == {depot_id}
        assert subbundle.instance.num_cv == int(caps["num_cv"])
        assert subbundle.instance.num_ev == int(caps["num_ev"])
        assert subbundle.instance.vehicle_parameters is not None
        assert subbundle.instance.road_profiles is not None
        assert set(subbundle.customer_home_depot.values()) == {depot_id}
        represented = {
            customer
            for duty in subindividual.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }
        assert represented == set(subbundle.customer_home_depot)
        total_customers += len(represented)

        first = subbundle.instance.nodes[0].node_id
        last = subbundle.instance.nodes[-1].node_id
        for vehicle_type in ("cv", "ev"):
            assert subbundle.instance.arc_metrics(
                first,
                last,
                vehicle_type,
                fallback_speed_mps=float(subbundle.prices.v_speed_ms),
            ) == pytest.approx(
                full_bundle.instance.arc_metrics(
                    first,
                    last,
                    vehicle_type,
                    fallback_speed_mps=float(full_bundle.prices.v_speed_ms),
                )
            )

    assert total_customers == len(full_bundle.customer_home_depot)


def test_independent_initial_rejects_cross_depot_contamination() -> None:
    bundle, individual, _pi0, _context = _build_context(
        REPO,
        "cn-jjj-50c-01-V2-LOCATIONS",
    )
    depots = sorted(bundle.fleet_caps_by_depot)
    left = next(
        duty
        for duty in individual.duties
        if duty.home_depot_id == depots[0] and duty.trips
    )
    right_customer = next(
        customer
        for customer, owner in bundle.customer_home_depot.items()
        if owner == depots[1]
    )
    right = next(
        (duty, trip)
        for duty in individual.duties
        for trip in duty.trips
        if right_customer in trip.customer_ids
    )
    contaminated = RelocateMove(
        action_id="cross-depot-contamination-test",
        channel="technical-test",
        source_duty_id=right[0].physical_vehicle_id,
        source_trip_index=right[1].trip_index,
        customer_id=right_customer,
        target_duty_id=left.physical_vehicle_id,
        target_trip_index=left.trips[0].trip_index,
        target_position=0,
    ).apply(
        individual
    )

    with pytest.raises(ValueError, match="responsibility-pure"):
        independent_individual(contaminated, bundle, depots[0])


@pytest.mark.parametrize(
    "instance_id",
    (
        "cn-cy-50c-01-V2-LOCATIONS",
        "cn-jjj-50c-01-V2-LOCATIONS",
        "cn-prd-50c-01-V2-LOCATIONS",
    ),
)
def test_independent_slice_matches_full_bundle_componentwise(
    instance_id: str,
) -> None:
    bundle, individual, _pi0, _context = _build_context(REPO, instance_id)
    depot_id = sorted(bundle.fleet_caps_by_depot)[0]
    subbundle = independent_bundle(bundle, depot_id)
    subindividual = independent_individual(individual, bundle, depot_id)
    decoded = subindividual.to_solution()

    full_prepared, _ = prepare_multitrip_solution(
        decoded,
        bundle.instance,
        bundle.prices,
    )
    sliced_prepared, _ = prepare_multitrip_solution(
        decoded,
        subbundle.instance,
        subbundle.prices,
    )
    full_prepared = annotate_cross_site_services(
        full_prepared,
        bundle.customer_home_depot,
    )
    sliced_prepared = annotate_cross_site_services(
        sliced_prepared,
        subbundle.customer_home_depot,
    )
    assert sliced_prepared == full_prepared

    full_cost = evaluate(
        full_prepared,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        carbon_quota_kg=0.0,
    )
    sliced_cost = evaluate(
        sliced_prepared,
        subbundle.instance,
        subbundle.time_profile,
        subbundle.prices,
        carbon_quota_kg=0.0,
    )
    assert sliced_cost == pytest.approx(full_cost, abs=1.0e-9)

    full_profit = calculate_depot_profits(
        full_prepared,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        customer_home_depot=dict(bundle.customer_home_depot),
        carbon_quota_kg=0.0,
    )[depot_id].to_dict()
    sliced_profit = calculate_depot_profits(
        sliced_prepared,
        subbundle.instance,
        subbundle.time_profile,
        subbundle.prices,
        customer_home_depot=dict(subbundle.customer_home_depot),
        carbon_quota_kg=0.0,
    )[depot_id].to_dict()
    assert sliced_profit.pop("depot_id") == full_profit.pop("depot_id")
    assert sliced_profit == pytest.approx(full_profit, abs=1.0e-9)


def test_independent_trial_can_record_same_parent_selection() -> None:
    bundle, individual, _pi0, _context = _build_context(
        REPO,
        "cn-jjj-50c-01-V2-LOCATIONS",
    )
    depot_id = "D_tianjin"
    subbundle = independent_bundle(bundle, depot_id)
    initial = independent_individual(individual, bundle, depot_id)
    evaluator = DutyFullEvaluator(independent_context(subbundle, depot_id))

    candidates, _evaluation, _reverse, _attempts, selected, _evaluations = (
        _prepare_population(
            initial,
            evaluator,
            _policy(evaluator),
            _parameters(),
            require_distinct_selection=False,
        )
    )

    assert candidates[0].fingerprint != candidates[1].fingerprint
    assert not selected["distinct"]
