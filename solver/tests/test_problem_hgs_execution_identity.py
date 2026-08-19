"""Effective Problem-HGS identity follows the objects that actually run."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from types import SimpleNamespace

import pytest
from setp_hgs_kernel._setp_hgs_kernel import PopulationParams

from setp_solver.algorithms.problem_hgs.charging import ChargingRepairPolicy
from setp_solver.algorithms.problem_hgs.execution_identity import (
    EffectiveExecutionBundle,
    build_effective_execution_bundle,
    proposal_stage_configuration,
)
from setp_solver.algorithms.problem_hgs.integrated_genetic_algorithm import (
    IntegratedGeneticAlgorithm,
)
from setp_solver.algorithms.problem_hgs.integrated_private import (
    build_integrated_private_hgs,
)
from setp_solver.algorithms.problem_hgs.kernel_proposals import (
    IndependentKernelDutyRouteProposalEngine,
)
from setp_solver.algorithms.problem_hgs.population import (
    PenaltyParameters,
    PopulationParameters,
)
from setp_solver.algorithms.problem_hgs.proposals import (
    MechanismProposalEngine,
    SequentialProposalEngine,
)
from setp_solver.algorithms.problem_hgs.runner import (
    FrozenPopulationIdentity,
    ProblemHGSSearchParameters,
    population_sha256,
    run_integrated_problem_hgs,
    search_configuration_sha256,
)
from tests.test_problem_hgs_charging_gap import sc3_case


def _policy(**changes) -> ChargingRepairPolicy:
    values = {
        "strategy": "minimum_carbon",
        "carbon_weight": 1.0,
        "depot_charge_window_mode": "full_gap",
        "charge_timing_policy": "time_varying_carbon",
        "charge_amount_strategy": "minimum_required",
        "public_station_candidate_mode": "registered_only",
        "carbon_profiles_by_day_offset": None,
        "first_trip_prev_night_enabled": False,
        "frvcpy_enabled": False,
        "charging_gap_enabled": True,
    }
    values.update(changes)
    return ChargingRepairPolicy(**values)


def _penalties() -> PenaltyParameters:
    return PenaltyParameters(
        initial_penalty_per_unit=100.0,
        solutions_between_updates=50,
        penalty_increase=1.34,
        penalty_decrease=0.32,
        target_feasible=0.43,
        feasibility_tolerance=0.05,
        minimum_penalty=0.1,
        maximum_penalty=100_000.0,
        initial_penalty_by_type=(("z", 3.0), ("a", 2.0)),
    )


def _population(tournament_size: int = 2) -> PopulationParameters:
    return PopulationParameters(
        min_pop_size=2,
        generation_size=1,
        num_elite=1,
        num_close=1,
        tournament_size=tournament_size,
        lb_diversity=0.1,
        ub_diversity=0.5,
    )


def _identity_route(runtime_sha256: str = "a" * 64):
    engine = object.__new__(IndependentKernelDutyRouteProposalEngine)
    engine.source_id = "stable-route-source"
    engine.identity_sha256 = runtime_sha256
    return engine


def _effective(
    *,
    policy: ChargingRepairPolicy | None = None,
    context=None,
    population: object | None = None,
    route_runtime_sha256: str = "a" * 64,
    **switch_changes,
) -> EffectiveExecutionBundle:
    policy = policy or _policy()
    context = context or SimpleNamespace(
        bundle=SimpleNamespace(
            instance_id="I0",
            prices=SimpleNamespace(carbon_price=0.07502),
        ),
        fairness_enabled=True,
        theta=0.8,
        incremental_full_truth_sentinel_enabled=True,
        shift_aware_departure_enabled=False,
    )
    route = _identity_route(route_runtime_sha256)
    switches = {
        "include_mechanism_refinement": True,
        "include_whole_duty_type_exchange": True,
        "include_charging_candidates": True,
        "schedule_cross_repair_fallback": False,
        "schedule_all_changed_move_evaluation": False,
        "fleet_activation_enabled": True,
        "objective_mode": "single_objective",
        "charging_prescreen_enabled": False,
        "charging_prescreen_audit_limit": 0,
        "cross_depot_enabled": True,
        "multi_trip_enabled": True,
        "type_exchange_enabled": True,
        "route_layer_crossover_enabled": False,
        "education_depth_limit": None,
    }
    switches.update(switch_changes)
    route_stage = SequentialProposalEngine((route,), source_id="stable-route-stage")
    mechanism = MechanismProposalEngine(
        context,
        policy,
        include_charging_candidates=switches["include_charging_candidates"],
        cross_depot_enabled=switches["cross_depot_enabled"],
        multi_trip_enabled=switches["multi_trip_enabled"],
        type_exchange_enabled=switches["type_exchange_enabled"],
    )
    mechanism_stage = SequentialProposalEngine((mechanism,), source_id="stable-mechanism-stage")
    if not switches["include_mechanism_refinement"]:
        mechanism_stage = None
    return build_effective_execution_bundle(
        policy=policy,
        route_engine=route,
        route_stage_engine=route_stage,
        mechanism_stage_engine=mechanism_stage,
        context=context,
        population_parameters=population or _population(),
        penalty_parameters=_penalties(),
        repair_probability=0.8,
        repair_booster=12,
        num_iters_no_improvement=500,
        live_switches=switches,
    )


def _real_route(case, seed: int = 1):
    return IndependentKernelDutyRouteProposalEngine(
        case["context"], case["initial"], random_seed=seed
    )


def _parameters(**changes) -> ProblemHGSSearchParameters:
    values = {
        "random_seed": 1,
        "population": _population(),
        "penalties": _penalties(),
        "stagnation_patience": 5,
    }
    values.update(changes)
    return ProblemHGSSearchParameters(**values)


def _run(case, *, proposal_engine=None, expected=None, **switches):
    initial = case["initial"]
    evaluation = case["evaluator"].evaluate(initial)
    return run_integrated_problem_hgs(
        (initial,),
        evaluator=case["evaluator"],
        charging_policy=case["policy_off"],
        parameters=_parameters(),
        initial_population_identity=FrozenPopulationIdentity(
            "execution-identity-test", population_sha256((initial,))
        ),
        stop=lambda _state: True,
        arm="execution-identity-test",
        route_engine=_real_route(case),
        proposal_engine=proposal_engine,
        initial_evaluations=(evaluation,),
        initialization_full_evaluation_count=1,
        retain_trajectory=False,
        expected_search_configuration_sha256=expected,
        **switches,
    )


def test_default_runner_records_the_same_two_stages_that_builder_executes(
    sc3_case,
) -> None:
    result = _run(sc3_case)
    execution = result.effective_execution

    assert execution.route_stage_configuration == proposal_stage_configuration(
        execution.route_stage_engine
    )
    assert execution.mechanism_stage_configuration == (
        proposal_stage_configuration(execution.mechanism_stage_engine)
    )
    assert execution.route_stage_engine.providers == (execution.route_engine,)


def test_gap_off_static_request_hashes_effective_gap_on_policy(sc3_case) -> None:
    built = build_integrated_private_hgs(
        (sc3_case["initial"],),
        evaluator=sc3_case["evaluator"],
        charging_policy=sc3_case["policy_off"],
        route_engine=_real_route(sc3_case),
        penalty_parameters=_penalties(),
        stagnation_patience=5,
    )

    assert not sc3_case["policy_off"].charging_gap_enabled
    assert built.effective_execution.charging_gap_enabled
    assert built.effective_execution.algorithm_configuration_payload()["charging_policy"][
        "charging_gap_enabled"
    ]


@pytest.mark.parametrize(
    ("name", "changed"),
    (
        ("include_mechanism_refinement", False),
        ("include_whole_duty_type_exchange", False),
        ("include_charging_candidates", False),
        ("schedule_cross_repair_fallback", True),
        ("schedule_all_changed_move_evaluation", True),
        ("fleet_activation_enabled", False),
        ("objective_mode", "bi_objective"),
        ("charging_prescreen_enabled", True),
        ("charging_prescreen_audit_limit", 1),
        ("cross_depot_enabled", False),
        ("multi_trip_enabled", False),
        ("type_exchange_enabled", False),
        ("route_layer_crossover_enabled", True),
        ("education_depth_limit", 1),
    ),
)
def test_each_live_execution_switch_changes_effective_hash(name, changed) -> None:
    baseline = search_configuration_sha256(_effective())
    assert search_configuration_sha256(_effective(**{name: changed})) != baseline


def test_requested_dead_fields_do_not_change_effective_hash() -> None:
    left = _parameters()
    right = replace(
        left,
        crossover_mode="hybrid",
        population=replace(left.population, tournament_size=9),
    )
    left_execution = _effective(population=left.population)
    right_execution = _effective(population=right.population)
    payload = json.dumps(left_execution.algorithm_configuration_payload())

    assert "crossover_mode" not in payload
    assert "tournament_size" not in payload
    assert search_configuration_sha256(left_execution) == (
        search_configuration_sha256(right_execution)
    )


def test_system_charge_timing_off_reaches_actual_mechanism_stage(sc3_case) -> None:
    built = build_integrated_private_hgs(
        (sc3_case["initial"],),
        evaluator=sc3_case["evaluator"],
        charging_policy=sc3_case["policy_off"],
        route_engine=_real_route(sc3_case),
        penalty_parameters=_penalties(),
        stagnation_patience=5,
        include_charging_candidates=False,
    )
    mechanism = built.effective_execution.mechanism_stage_engine.providers[0]

    assert not mechanism.include_charging_candidates
    assert not built.effective_execution.include_charging_candidates


def test_seed_instance_and_dynamic_state_change_runtime_identity_not_search_hash() -> None:
    left_context = SimpleNamespace(
        bundle=SimpleNamespace(
            instance_id="I-left",
            prices=SimpleNamespace(carbon_price=0.07502),
        ),
        fairness_enabled=True,
        theta=0.8,
        incremental_full_truth_sentinel_enabled=True,
        shift_aware_departure_enabled=False,
        dynamic_state=SimpleNamespace(name="left"),
    )
    right_context = SimpleNamespace(
        bundle=SimpleNamespace(
            instance_id="I-right",
            prices=SimpleNamespace(carbon_price=0.07502),
        ),
        fairness_enabled=True,
        theta=0.8,
        incremental_full_truth_sentinel_enabled=True,
        shift_aware_departure_enabled=False,
        dynamic_state=SimpleNamespace(name="right"),
    )
    left = _effective(context=left_context, route_runtime_sha256="a" * 64)
    right = _effective(context=right_context, route_runtime_sha256="b" * 64)

    assert left.runtime_identity_payload() != right.runtime_identity_payload()
    assert search_configuration_sha256(left) == search_configuration_sha256(right)


def test_charge_timing_policy_changes_search_hash() -> None:
    left = _effective(policy=_policy(charge_timing_policy="price"))
    right = _effective(policy=_policy(charge_timing_policy="carbon"))
    assert search_configuration_sha256(left) != search_configuration_sha256(right)


def test_carbon_price_changes_search_hash() -> None:
    left = _effective()
    right = replace(left, carbon_price_cny_per_kg=0.20)
    assert search_configuration_sha256(left) != search_configuration_sha256(right)


def test_fairness_on_and_theta_change_search_hash_but_disabled_theta_does_not() -> None:
    def context(enabled: bool, theta: float):
        return SimpleNamespace(
            bundle=SimpleNamespace(
                instance_id="I0",
                prices=SimpleNamespace(carbon_price=0.07502),
            ),
            fairness_enabled=enabled,
            theta=theta,
            incremental_full_truth_sentinel_enabled=True,
            shift_aware_departure_enabled=False,
        )

    on_left = _effective(context=context(True, 0.7))
    on_right = _effective(context=context(True, 0.8))
    off_left = _effective(context=context(False, 0.7))
    off_right = _effective(context=context(False, 0.8))

    assert search_configuration_sha256(on_left) != search_configuration_sha256(on_right)
    assert search_configuration_sha256(off_left) == search_configuration_sha256(off_right)


def test_truth_sentinel_switch_changes_effective_hash_and_formal_override_rejects(
    sc3_case,
) -> None:
    enabled = _effective()
    disabled_context = SimpleNamespace(
        bundle=SimpleNamespace(
            instance_id="I0",
            prices=SimpleNamespace(carbon_price=0.07502),
        ),
        fairness_enabled=True,
        theta=0.8,
        incremental_full_truth_sentinel_enabled=False,
        shift_aware_departure_enabled=False,
    )
    disabled = _effective(context=disabled_context)
    assert search_configuration_sha256(enabled) != search_configuration_sha256(disabled)

    with pytest.raises(ValueError, match="expected formal profile"):
        _run(sc3_case, expected="0" * 64)


def test_shift_aware_departure_switch_changes_effective_hash() -> None:
    disabled = _effective()
    context = SimpleNamespace(
        bundle=SimpleNamespace(
            instance_id="I0",
            prices=SimpleNamespace(carbon_price=0.07502),
        ),
        fairness_enabled=True,
        theta=0.8,
        incremental_full_truth_sentinel_enabled=True,
        shift_aware_departure_enabled=True,
    )
    enabled = _effective(context=context)
    assert search_configuration_sha256(disabled) != search_configuration_sha256(enabled)


def test_route_only_dynamic_ablation_reaches_builder_with_mechanism_refinement_false(
    sc3_case,
) -> None:
    built = build_integrated_private_hgs(
        (sc3_case["initial"],),
        evaluator=sc3_case["evaluator"],
        charging_policy=sc3_case["policy_off"],
        route_engine=_real_route(sc3_case),
        penalty_parameters=_penalties(),
        stagnation_patience=5,
        include_mechanism_refinement=False,
    )

    assert not built.effective_execution.include_mechanism_refinement
    assert built.effective_execution.mechanism_stage_engine is None
    assert built.effective_execution.mechanism_stage_configuration is None


def test_expected_search_hash_mismatch_raises_before_algorithm_run(sc3_case, monkeypatch) -> None:
    calls = 0

    def forbidden_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("algorithm.run must not execute")

    monkeypatch.setattr(IntegratedGeneticAlgorithm, "run", forbidden_run)
    with pytest.raises(ValueError, match="expected formal profile"):
        _run(sc3_case, expected="0" * 64)
    assert calls == 0


@dataclass(frozen=True)
class _OneBatchEngine:
    source_id: str = "technical-custom-engine"
    identity_sha256: str = "c" * 64

    def propose(self, *_args, **_kwargs):
        return ()


def test_unknown_custom_engine_runs_technical_with_null_formal_identity_but_formal_rejects_before_run(
    sc3_case, monkeypatch
) -> None:
    technical = _run(sc3_case, proposal_engine=_OneBatchEngine())
    assert not technical.effective_execution.formal_identity_eligible
    assert technical.provenance.effective_algorithm_configuration is None
    assert technical.provenance.search_configuration_sha256 is None

    calls = 0

    def forbidden_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("algorithm.run must not execute")

    monkeypatch.setattr(IntegratedGeneticAlgorithm, "run", forbidden_run)
    with pytest.raises(ValueError, match="expected formal profile"):
        _run(
            sc3_case,
            proposal_engine=_OneBatchEngine(),
            expected="0" * 64,
        )
    assert calls == 0


def test_caller_stop_result_contains_effective_execution_and_primitive_provenance(
    sc3_case,
) -> None:
    result = _run(sc3_case)
    payload = json.loads(json.dumps(asdict(result.provenance), allow_nan=False, sort_keys=True))

    assert result.effective_execution.schema_version.endswith(".v1")
    assert len(result.provenance.search_configuration_sha256) == 64
    assert payload["effective_algorithm_configuration"] == (
        result.effective_execution.algorithm_configuration_payload()
    )
    assert payload["effective_runtime_identity"] == (
        result.effective_execution.runtime_identity_payload()
    )
