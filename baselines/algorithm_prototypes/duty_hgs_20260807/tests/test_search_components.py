"""v1 2026-08-07: runnable Duty-HGS component and closed-loop tests."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import replace

import pytest
from duty_hgs.charging import ChargingRepairPolicy
from duty_hgs.contracts import SearchAccounting
from duty_hgs.crossover import (
    canonical_fleet_registry,
    selective_duty_exchange,
)
from duty_hgs.education import educate_best_improvement
from duty_hgs.feedback import RelocateCustomerMove
from duty_hgs.model import DutyChargingSession, DutyIndividual
from duty_hgs.population import (
    AdaptivePenaltyManager,
    PenaltyParameters,
    PopulationParameters,
    broken_pairs_distance,
)
from duty_hgs.runner import (
    DutyHGSSearchParameters,
    FrozenPopulationIdentity,
    population_sha256,
    run_duty_hgs,
)
from run_real_input_technical_trial import _write_failure_package


def _charging_policy(evaluator) -> ChargingRepairPolicy:
    return ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=evaluator.context.depot_charge_window_mode,
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )


def _feasible_parents(individual: DutyIndividual) -> tuple[DutyIndividual, ...]:
    first = RelocateCustomerMove(
        action_id="parent-one",
        source_duty_id="CV_D0_1",
        source_trip_index=1,
        customer_id="C1",
        target_duty_id="CV_D0_2",
        target_trip_index=1,
        target_position=0,
        predicted_remaining_overflow_kg=0.0,
        predicted_relief_kg=2.0,
    ).apply(individual)
    second = RelocateCustomerMove(
        action_id="parent-two",
        source_duty_id="CV_D0_1",
        source_trip_index=1,
        customer_id="C2",
        target_duty_id="CV_D0_2",
        target_trip_index=1,
        target_position=1,
        predicted_remaining_overflow_kg=0.0,
        predicted_relief_kg=2.0,
    ).apply(individual)
    return first, second


def _search_parameters(*, restart_after: int = 20_000) -> DutyHGSSearchParameters:
    return DutyHGSSearchParameters(
        random_seed=11,
        population=PopulationParameters(
            min_pop_size=2,
            generation_size=2,
            num_elite=1,
            num_close=1,
            tournament_size=2,
            lb_diversity=0.0,
            ub_diversity=1.0,
        ),
        penalties=PenaltyParameters(
            initial_penalty_per_unit=100.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        ),
        restart_after_iterations_without_improvement=restart_after,
    )


def test_selective_duty_exchange_preserves_registry_and_partition(
    feedback_fixture,
) -> None:
    overloaded, _ = feedback_fixture
    parents = _feasible_parents(overloaded)

    crossed = selective_duty_exchange(parents, random.Random(7))

    assert canonical_fleet_registry(crossed.child) == canonical_fleet_registry(
        parents[0]
    )
    represented = {
        customer
        for duty in crossed.child.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }.union(crossed.child.unserved_customers)
    assert represented == {"C1", "C2", "C3"}
    assert len(represented) == 3


def test_best_improvement_accepts_complete_model_feasible_move(
    feedback_fixture,
) -> None:
    overloaded, evaluator = feedback_fixture
    accounting = SearchAccounting()
    penalties = AdaptivePenaltyManager(
        PenaltyParameters(
            initial_penalty_per_unit=100.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        )
    )
    penalties.register(evaluator.evaluate(overloaded))

    educated, result, rows = educate_best_improvement(
        overloaded,
        evaluator=evaluator,
        charging_policy=_charging_policy(evaluator),
        arm="technical",
        iteration=0,
        accounting=accounting,
        penalized_cost=penalties.cost,
    )

    assert result.feasible
    assert educated != overloaded
    assert any(row.accepted for row in rows)
    assert accounting.incremental_evaluations > 0
    assert (
        accounting.incremental_evaluations
        == accounting.sentinel_evaluations
    )
    assert accounting.cache_seedings == accounting.education_rounds


def test_best_improvement_streaming_preserves_rows_and_choice(
    feedback_fixture,
) -> None:
    overloaded, evaluator = feedback_fixture
    penalties = AdaptivePenaltyManager(
        PenaltyParameters(
            initial_penalty_per_unit=100.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        )
    )
    penalties.register(evaluator.evaluate(overloaded))

    expected, expected_evaluation, expected_rows = educate_best_improvement(
        overloaded,
        evaluator=evaluator,
        charging_policy=_charging_policy(evaluator),
        arm="technical-stream-equivalence",
        iteration=0,
        accounting=SearchAccounting(),
        penalized_cost=penalties.cost,
    )
    streamed = []
    actual, actual_evaluation, retained_rows = educate_best_improvement(
        overloaded,
        evaluator=evaluator,
        charging_policy=_charging_policy(evaluator),
        arm="technical-stream-equivalence",
        iteration=0,
        accounting=SearchAccounting(),
        penalized_cost=penalties.cost,
        trajectory_sink=lambda rows: streamed.extend(rows),
    )

    assert actual == expected
    assert actual_evaluation == expected_evaluation
    assert tuple(streamed) == expected_rows
    assert retained_rows == ()


def test_penalized_education_accepts_an_infeasible_intermediate(
    multi_step_infeasible_fixture,
) -> None:
    individual, evaluator = multi_step_infeasible_fixture
    accounting = SearchAccounting()
    penalties = AdaptivePenaltyManager(
        PenaltyParameters(
            initial_penalty_per_unit=1_000.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        )
    )
    before = evaluator.evaluate(individual)
    penalties.register(before)

    educated, after, rows = educate_best_improvement(
        individual,
        evaluator=evaluator,
        charging_policy=_charging_policy(evaluator),
        arm="technical-penalized-education",
        iteration=0,
        accounting=accounting,
        penalized_cost=penalties.cost,
    )

    assert not before.feasible
    assert educated != individual
    assert penalties.cost(after) < penalties.cost(before)
    assert any(
        row.accepted
        and row.after_violations is not None
        and row.after_violations > 0
        for row in rows
    )


def test_runnable_duty_hgs_executes_crossover_repair_and_education(
    feedback_fixture,
) -> None:
    overloaded, evaluator = feedback_fixture
    parents = _feasible_parents(overloaded)
    assert all(evaluator.evaluate(parent).feasible for parent in parents)
    parameters = DutyHGSSearchParameters(
        random_seed=11,
        population=PopulationParameters(
            min_pop_size=2,
            generation_size=2,
            num_elite=1,
            num_close=1,
            tournament_size=2,
            lb_diversity=0.0,
            ub_diversity=1.0,
        ),
        penalties=PenaltyParameters(
            initial_penalty_per_unit=100.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        ),
        restart_after_iterations_without_improvement=20_000,
    )

    result = run_duty_hgs(
        parents,
        evaluator=evaluator,
        charging_policy=_charging_policy(evaluator),
        parameters=parameters,
        initial_population_identity=FrozenPopulationIdentity(
            source_id="technical-feasible-parents",
            value_sha256=population_sha256(parents),
        ),
        stop=lambda state: state.iterations >= 1,
        arm="one-cycle-wiring-trial",
    )

    assert result.iterations == 1
    assert result.best_evaluation.feasible
    assert result.accounting.crossover_calls == 1
    assert result.accounting.sentinel_evaluations > 0
    assert (
        result.accounting.full_evaluations
        + result.accounting.sentinel_evaluations
        == result.accounting.to_dict()["actual_full_model_evaluations"]
    )
    assert result.accounting.cache_seedings > 0
    assert result.accounting.duty_slice_preparations > 0
    assert result.accounting.candidate_assemblies > 0
    assert result.termination_status == "STOPPED_BY_CALLER"
    assert any(row.phase == "crossover" for row in result.trajectory)
    assert not any(
        row.phase == "crossover" and row.accepted
        for row in result.trajectory
    )
    assert any(
        row.phase == "population" and row.accepted
        for row in result.trajectory
    )
    assert result.accounting.population_admission_attempts == 1
    assert result.accounting.population_admissions == 1
    assert result.accounting.accepted_actions["hgs_population"] == 1
    assert result.provenance.random_seed == 11
    assert result.provenance.initial_population_sha256 == population_sha256(
        parents
    )
    assert result.provenance.independent_profit_sha256 == (
        evaluator.context.independent_profit_identity.value_sha256
    )
    assert result.provenance.fairness_enabled
    assert result.provenance.fairness_theta == evaluator.context.theta
    assert len(result.provenance.search_configuration_sha256) == 64
    assert result.trajectory

    with pytest.raises(ValueError, match="frozen population identity"):
        run_duty_hgs(
            parents,
            evaluator=evaluator,
            charging_policy=_charging_policy(evaluator),
            parameters=parameters,
            initial_population_identity=FrozenPopulationIdentity(
                source_id="tampered-technical-population",
                value_sha256="0" * 64,
            ),
            stop=lambda state: True,
            arm="tampered-provenance",
        )


def test_runnable_duty_hgs_reports_an_all_infeasible_initial_population(
    multi_step_infeasible_fixture,
) -> None:
    individual, evaluator = multi_step_infeasible_fixture
    initial = (individual,)
    parameters = DutyHGSSearchParameters(
        random_seed=17,
        population=PopulationParameters(
            min_pop_size=1,
            generation_size=1,
            num_elite=0,
            num_close=1,
            tournament_size=1,
            lb_diversity=0.0,
            ub_diversity=1.0,
        ),
        penalties=PenaltyParameters(
            initial_penalty_per_unit=1_000.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        ),
        restart_after_iterations_without_improvement=20_000,
    )

    result = run_duty_hgs(
        initial,
        evaluator=evaluator,
        charging_policy=_charging_policy(evaluator),
        parameters=parameters,
        initial_population_identity=FrozenPopulationIdentity(
            source_id="technical-infeasible-parent",
            value_sha256=population_sha256(initial),
        ),
        stop=lambda state: state.iterations == 0,
        arm="infeasible-start-wiring-trial",
    )

    assert result.termination_status == "NO_FEASIBLE_SOLUTION"
    assert not result.best_evaluation.feasible
    assert result.provenance.incremental_full_truth_sentinel_enabled


def test_runnable_duty_hgs_streams_without_retaining_full_trajectory(
    feedback_fixture,
) -> None:
    overloaded, evaluator = feedback_fixture
    parents = _feasible_parents(overloaded)
    streamed = []

    result = run_duty_hgs(
        parents,
        evaluator=evaluator,
        charging_policy=_charging_policy(evaluator),
        parameters=_search_parameters(),
        initial_population_identity=FrozenPopulationIdentity(
            source_id="technical-streaming-parents",
            value_sha256=population_sha256(parents),
        ),
        stop=lambda state: state.iterations >= 1,
        arm="streaming-wiring-trial",
        trajectory_sink=lambda rows: streamed.extend(rows),
        retain_trajectory=False,
    )

    assert result.trajectory == ()
    assert streamed
    assert any(row.phase == "population" for row in streamed)
    assert result.provenance.trajectory_sink_enabled
    assert not result.provenance.trajectory_retained_in_memory
    assert result.accounting.crossover_calls == 1
    assert result.best_evaluation.source == "full"

    with pytest.raises(ValueError, match="trajectory_sink is required"):
        run_duty_hgs(
            parents,
            evaluator=evaluator,
            charging_policy=_charging_policy(evaluator),
            parameters=_search_parameters(),
            initial_population_identity=FrozenPopulationIdentity(
                source_id="technical-invalid-streaming-parents",
                value_sha256=population_sha256(parents),
            ),
            stop=lambda state: True,
            arm="invalid-streaming-wiring-trial",
            retain_trajectory=False,
        )


def test_runnable_duty_hgs_records_a_population_restart(feedback_fixture) -> None:
    overloaded, evaluator = feedback_fixture
    parents = _feasible_parents(overloaded)

    result = run_duty_hgs(
        parents,
        evaluator=evaluator,
        charging_policy=_charging_policy(evaluator),
        parameters=_search_parameters(restart_after=1),
        initial_population_identity=FrozenPopulationIdentity(
            source_id="technical-restart-parents",
            value_sha256=population_sha256(parents),
        ),
        stop=lambda state: state.iterations >= 3,
        arm="restart-wiring-trial",
    )

    assert result.accounting.restarts >= 1
    assert any(
        row.phase == "control" and row.status == "RESTARTED"
        for row in result.trajectory
    )
    assert result.termination_status == "STOPPED_BY_CALLER"
    assert result.best_evaluation.feasible


def test_technical_runner_preserves_an_owned_failure_directory(tmp_path) -> None:
    output = tmp_path / "failed-trial"
    output.mkdir()
    (output / "metadata.json").write_text(
        json.dumps({"status": "RUNNING"}),
        encoding="utf-8",
    )

    try:
        raise RuntimeError("deliberate packaging test")
    except RuntimeError as error:
        assert _write_failure_package(output, error)

    decision = json.loads((output / "decision.json").read_text())
    assert decision["verdict"] == "TECHNICAL_TRIAL_FAILED"
    assert "RuntimeError" in decision["failure_reasons"][0]
    hashes = json.loads((output / "artifact_hashes.json").read_text())
    assert set(hashes) == {
        "decision.json",
        "metadata.json",
        "raw_runs.csv",
        "report.md",
    }
    for name, expected in hashes.items():
        actual = hashlib.sha256((output / name).read_bytes()).hexdigest()
        assert actual == expected


def test_registry_mismatch_fails_before_crossover(feedback_fixture) -> None:
    overloaded, _ = feedback_fixture
    first, second = _feasible_parents(overloaded)
    mismatched = DutyIndividual(
        duties=second.duties[:-1],
        unserved_customers=("C3",),
        source="mismatched-registry",
    )

    with pytest.raises(ValueError, match="different canonical fleets"):
        selective_duty_exchange((first, mismatched), random.Random(1))


def test_duty_diversity_sees_charging_state(feedback_fixture) -> None:
    individual, _ = feedback_fixture
    duty = individual.duties[0]
    first = DutyChargingSession(
        trip_index=1,
        station_id="D0",
        energy_kwh=1.0,
        occupancy_minutes=2.0,
        charge_start_second=100.0,
    )
    second = DutyChargingSession(
        trip_index=1,
        station_id="D0",
        energy_kwh=1.0,
        occupancy_minutes=2.0,
        charge_start_second=200.0,
    )
    left = DutyIndividual(
        duties=(
            replace(duty, charging_sessions=(first,)),
            *individual.duties[1:],
        )
    )
    right = DutyIndividual(
        duties=(
            replace(duty, charging_sessions=(second,)),
            *individual.duties[1:],
        )
    )

    assert broken_pairs_distance(left, right) > 0.0
