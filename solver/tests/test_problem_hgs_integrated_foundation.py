from __future__ import annotations

import itertools
from dataclasses import dataclass
from types import SimpleNamespace

import setp_solver.algorithms.problem_hgs.charging as charging_module
import setp_solver.algorithms.problem_hgs.integrated_private as integrated_module
from setp_solver.algorithms.problem_hgs.charging import (
    ChargingRepairPolicy,
    _coordinate_timing_variants,
    repair_changed_duties_candidates,
)
from setp_solver.algorithms.problem_hgs.contracts import SearchAccounting
from setp_solver.algorithms.problem_hgs.education import educate_best_improvement
from setp_solver.algorithms.problem_hgs.model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.algorithms.problem_hgs.integrated_private import (
    build_integrated_private_hgs,
)
from setp_solver.algorithms.problem_hgs.population import PenaltyParameters
from setp_solver.algorithms.problem_hgs.proposals import (
    SequentialProposalEngine,
)
from setp_solver.prices import PriceParameters
from setp_hgs_kernel.stop import MaxIterations
from setp_hgs_kernel._setp_hgs_kernel import PopulationParams
from setp_hgs_kernel.ExternalPopulation import (
    EvaluatedSolution,
    ExternalPopulation,
)


@dataclass(frozen=True)
class _Solution:
    name: str


@dataclass(frozen=True)
class _Evaluation:
    full_cost: float
    feasible: bool


class _Rng:
    def __init__(self, draws: tuple[int, ...]):
        self._draws = itertools.cycle(draws)

    def randint(self, high: int) -> int:
        return next(self._draws) % high


class _KernelRng:
    def randint(self, high: int) -> int:
        return 0 % high

    def rand(self) -> float:
        return 1.0


@dataclass(frozen=True)
class _FullEvaluation:
    individual_fingerprint: str
    total_cost: float
    violations: tuple = ()
    violation_magnitudes: tuple[float, ...] = ()

    @property
    def feasible(self) -> bool:
        return not self.violations


class _FullEvaluator:
    def __init__(self) -> None:
        self.context = SimpleNamespace(
            bundle=SimpleNamespace(
                instance=SimpleNamespace(nodes=()),
                instance_id="complete-duty-test",
            ),
            dynamic_state=None,
        )

    def evaluate(self, individual: DutyIndividual) -> _FullEvaluation:
        return _FullEvaluation(
            individual_fingerprint=individual.fingerprint,
            total_cost=10.0,
        )


class _RouteProposalEngine:
    source_id = "test-route-proposals"
    identity_sha256 = "0" * 64

    def __init__(self) -> None:
        self.rng = _KernelRng()
        self.data = object()
        self.penalty_manager = object()
        self.local_search = object()

    def propose(self, *args, **kwargs):
        return ()


@dataclass(frozen=True)
class _Move:
    action_id: str


@dataclass(frozen=True)
class _Provider:
    source_id: str
    moves: tuple[_Move, ...]

    @property
    def identity_sha256(self) -> str:
        return self.source_id

    def propose(self, *args, **kwargs):
        return self.moves


def _population() -> ExternalPopulation[_Solution, _Evaluation]:
    return ExternalPopulation(
        lambda left, right: float(left.name != right.name),
        is_feasible=lambda evaluation: evaluation.feasible,
        penalised_cost=lambda evaluation: evaluation.full_cost,
        fingerprint=lambda solution: solution.name,
        params=PopulationParams(
            min_pop_size=2,
            generation_size=1,
            num_elite=1,
            num_close=1,
            lb_diversity=0.1,
            ub_diversity=1.0,
        ),
    )


def test_complete_cost_controls_survival_instead_of_route_proxy() -> None:
    population = _population()
    candidates = (
        EvaluatedSolution(_Solution("route-proxy-best"), _Evaluation(100, True)),
        EvaluatedSolution(_Solution("complete-best"), _Evaluation(10, True)),
        EvaluatedSolution(_Solution("middle"), _Evaluation(50, True)),
        EvaluatedSolution(_Solution("worst"), _Evaluation(500, True)),
    )
    for candidate in candidates:
        population.add(candidate)

    retained = {candidate.solution.name for candidate in population}
    assert retained == {"complete-best", "middle"}
    assert population.best_feasible().solution.name == "complete-best"


def test_complete_feasibility_controls_subpopulation_and_selection() -> None:
    population = _population()
    population.add(
        EvaluatedSolution(_Solution("cheap-but-invalid"), _Evaluation(1, False))
    )
    population.add(
        EvaluatedSolution(_Solution("valid"), _Evaluation(10, True))
    )

    assert population.best_feasible().solution.name == "valid"
    first, second = population.select(_Rng((0, 1, 0, 1)))
    assert {first.solution.name, second.solution.name}.issubset(
        {"cheap-but-invalid", "valid"}
    )


def test_accepted_action_effects_are_attributed_to_one_serial_channel() -> None:
    before = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1",
                "cv",
                "D0",
                trips=(DutyTrip(1, ("C1",)),),
            ),
        ),
    )
    after = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "EV_D0_1",
                "ev",
                "D0",
                trips=(DutyTrip(1, ("C1",)),),
            ),
        ),
    )
    before_evaluation = SimpleNamespace(
        total_cost=100.0,
        breakdown={"cost_carbon": 5.0, "E_total": 20.0},
        participation_margin={"D0": 10.0, "D1": 8.0},
    )
    after_evaluation = SimpleNamespace(
        total_cost=90.0,
        breakdown={"cost_carbon": 4.0, "E_total": 15.0},
        participation_margin={"D0": 11.0, "D1": 9.0},
    )
    accounting = SearchAccounting()

    accounting.record_acceptance("whole_duty_type_exchange")
    accounting.record_accepted_effect(
        "whole_duty_type_exchange",
        before,
        before_evaluation,
        after,
        after_evaluation,
    )

    payload = accounting.to_dict()
    assert payload["accepted_actions"] == {"whole_duty_type_exchange": 1}
    assert payload["accepted_cost_reduction"] == {
        "whole_duty_type_exchange": 10.0
    }
    assert payload["accepted_carbon_cost_reduction"] == {
        "whole_duty_type_exchange": 1.0
    }
    assert payload["accepted_emissions_reduction"] == {
        "whole_duty_type_exchange": 5.0
    }
    assert payload["accepted_ev_customer_delta"] == {
        "whole_duty_type_exchange": 1
    }
    assert payload["accepted_minimum_margin_delta"] == {
        "whole_duty_type_exchange": 1.0
    }


def test_static_charging_clocks_are_serial_not_a_cartesian_product() -> None:
    duty = PhysicalVehicleDuty(
        "EV_D0_1",
        "ev",
        "D0",
        trips=(DutyTrip(1, ("C1",)), DutyTrip(2, ("C2",))),
        charging_sessions=(
            DutyChargingSession(1, "D0", 5.0, 10.0, 0.0),
            DutyChargingSession(2, "D0", 5.0, 10.0, 3600.0),
        ),
    )

    candidates = tuple(
        _coordinate_timing_variants(
            duty,
            ((0, (0.0, 1800.0)), (1, (3600.0, 5400.0))),
        )
    )

    assert len(candidates) == 2
    assert {
        tuple(
            session.charge_start_second
            for session in candidate.charging_sessions
        )
        for candidate in candidates
    } == {(1800.0, 3600.0), (0.0, 5400.0)}




def test_private_common_loop_keeps_complete_duty_as_population_gene() -> None:
    individual = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1",
                "cv",
                "D0",
                trips=(DutyTrip(1, ()),),
            ),
        ),
        source="complete-duty-test",
    )
    bundle = build_integrated_private_hgs(
        (individual,),
        evaluator=_FullEvaluator(),
        charging_policy=ChargingRepairPolicy(
            strategy="integrated",
            carbon_weight=1.0,
            depot_charge_window_mode="same_day_predeparture",
            charge_timing_policy="cost_plus_carbon",
            charge_amount_strategy="just_enough",
            public_station_candidate_mode="parallel",
            carbon_profiles_by_day_offset=None,
        ),
        route_engine=_RouteProposalEngine(),
        penalty_parameters=PenaltyParameters(
            initial_penalty_per_unit=100.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        ),
        stagnation_patience=10,
        include_mechanism_refinement=False,
    )

    result = bundle.algorithm.run(MaxIterations(1))

    assert result.best.solution is individual
    assert result.best.evaluation.individual is individual
    assert result.best.evaluation.full.total_cost == 10.0
    assert bundle.accounting.crossover_noops == 1


def test_sequential_proposals_finish_route_stage_before_mechanisms() -> None:
    engine = SequentialProposalEngine(
        (
            _Provider("route", (_Move("r1"), _Move("shared"), _Move("r2"))),
            _Provider("mechanism", (_Move("shared"), _Move("m1"))),
        )
    )

    moves = tuple(
        engine.propose(
            object(),
            object(),
            object(),
            include_whole_duty_type_exchange=True,
        )
    )

    assert tuple(move.action_id for move in moves) == (
        "r1",
        "shared",
        "r2",
        "m1",
    )


def test_education_no_improvement_return_keeps_the_three_part_contract() -> None:
    individual = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1",
                "cv",
                "D0",
                trips=(DutyTrip(1, ()),),
            ),
        ),
    )
    evaluator = _FullEvaluator()
    initial_evaluation = evaluator.evaluate(individual)

    result = educate_best_improvement(
        individual,
        evaluator=evaluator,
        charging_policy=ChargingRepairPolicy(
            strategy="integrated",
            carbon_weight=1.0,
            depot_charge_window_mode="same_day_predeparture",
            charge_timing_policy="cost_plus_carbon",
            charge_amount_strategy="just_enough",
            public_station_candidate_mode="parallel",
            carbon_profiles_by_day_offset=None,
        ),
        arm="contract-test",
        iteration=1,
        accounting=SearchAccounting(),
        penalized_cost=lambda evaluation: evaluation.total_cost,
        initial_evaluation=initial_evaluation,
        proposal_engine=_Provider("empty", ()),
    )

    assert result == (individual, initial_evaluation, ())


def test_private_refinement_admits_only_the_final_educated_duty(
    monkeypatch,
) -> None:
    initial = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1",
                "cv",
                "D0",
                trips=(DutyTrip(1, ()),),
            ),
        ),
        source="initial",
    )
    improved = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1",
                "cv",
                "D0",
                trips=(DutyTrip(1, ("C1",)),),
            ),
        ),
        source="improved",
    )
    improved_evaluation = _FullEvaluation(
        individual_fingerprint=improved.fingerprint,
        total_cost=5.0,
    )
    monkeypatch.setattr(
        integrated_module,
        "educate_best_improvement",
        lambda *args, **kwargs: (improved, improved_evaluation, ()),
    )
    bundle = build_integrated_private_hgs(
        (initial,),
        evaluator=_FullEvaluator(),
        charging_policy=ChargingRepairPolicy(
            strategy="integrated",
            carbon_weight=1.0,
            depot_charge_window_mode="same_day_predeparture",
            charge_timing_policy="cost_plus_carbon",
            charge_amount_strategy="just_enough",
            public_station_candidate_mode="parallel",
            carbon_profiles_by_day_offset=None,
        ),
        route_engine=_RouteProposalEngine(),
        penalty_parameters=PenaltyParameters(
            initial_penalty_per_unit=100.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        ),
        stagnation_patience=10,
        include_mechanism_refinement=False,
    )
    evaluated = bundle.algorithm._adapter.evaluate(initial)
    assert evaluated is not None

    children = bundle.algorithm._adapter.refine(evaluated)

    assert len(children) == 1
    assert children[0].solution is improved
    assert children[0].evaluation.full is improved_evaluation


def test_private_mechanisms_run_once_on_the_final_feasible_incumbent(
    monkeypatch,
) -> None:
    individual = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1",
                "cv",
                "D0",
                trips=(DutyTrip(1, ()),),
            ),
        ),
    )
    calls: list[str] = []

    def educate(*args, **kwargs):
        calls.append(kwargs["proposal_engine"].source_id)
        return individual, kwargs["initial_evaluation"], ()

    monkeypatch.setattr(
        integrated_module,
        "educate_best_improvement",
        educate,
    )
    bundle = build_integrated_private_hgs(
        (individual,),
        evaluator=_FullEvaluator(),
        charging_policy=ChargingRepairPolicy(
            strategy="integrated",
            carbon_weight=1.0,
            depot_charge_window_mode="same_day_predeparture",
            charge_timing_policy="cost_plus_carbon",
            charge_amount_strategy="just_enough",
            public_station_candidate_mode="parallel",
            carbon_profiles_by_day_offset=None,
        ),
        route_engine=_RouteProposalEngine(),
        penalty_parameters=PenaltyParameters(
            initial_penalty_per_unit=100.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        ),
        stagnation_patience=10,
    )
    evaluated = bundle.algorithm._adapter.evaluate(individual)
    assert evaluated is not None

    bundle.algorithm._adapter.refine(evaluated)
    bundle.algorithm._adapter.refine(evaluated)
    finalised = bundle.algorithm._adapter.finalise(evaluated)

    assert sum("mechanism" in source_id for source_id in calls) == 1
    assert finalised is evaluated


def test_private_common_loop_rejects_incomplete_customer_service() -> None:
    complete = DutyIndividual(
        duties=(PhysicalVehicleDuty("CV_D0_1", "cv", "D0", trips=()),),
        source="complete-duty-test",
    )
    bundle = build_integrated_private_hgs(
        (complete,),
        evaluator=_FullEvaluator(),
        charging_policy=ChargingRepairPolicy(
            strategy="integrated",
            carbon_weight=1.0,
            depot_charge_window_mode="same_day_predeparture",
            charge_timing_policy="cost_plus_carbon",
            charge_amount_strategy="just_enough",
            public_station_candidate_mode="parallel",
            carbon_profiles_by_day_offset=None,
        ),
        route_engine=_RouteProposalEngine(),
        penalty_parameters=PenaltyParameters(
            initial_penalty_per_unit=100.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        ),
        stagnation_patience=10,
        include_mechanism_refinement=False,
    )
    incomplete = DutyIndividual(
        duties=complete.duties,
        unserved_customers=("C1",),
        source="incomplete-duty-test",
    )

    assert bundle.algorithm._adapter.evaluate(incomplete) is None
    assert bundle.accounting.rejection_reasons == {
        "incomplete customer service": 1
    }


def test_unchanged_primary_ev_repair_is_not_deduplicated_away(
    monkeypatch,
) -> None:
    duty = PhysicalVehicleDuty("EV_D0_1", "ev", "D0", trips=())
    individual = DutyIndividual((duty,), source="test")
    context = SimpleNamespace(
        depot_charge_window_mode="same_day_predeparture",
        bundle=SimpleNamespace(prices=PriceParameters()),
        dynamic_state=None,
    )
    policy = ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode="same_day_predeparture",
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )
    monkeypatch.setattr(
        charging_module,
        "_repair_one_ev_duty",
        lambda reference, candidate, **kwargs: candidate,
    )
    monkeypatch.setattr(
        charging_module,
        "_repair_one_ev_duty_candidates",
        lambda *args, **kwargs: iter(()),
    )

    candidates = tuple(
        repair_changed_duties_candidates(
            individual,
            individual,
            changed_duty_ids={duty.physical_vehicle_id},
            context=context,
            policy=policy,
        )
    )

    assert candidates == (individual,)


def test_ev_duty_charge_options_are_generated_only_when_consumed(
    monkeypatch,
) -> None:
    duty = PhysicalVehicleDuty(
        "EV_D0_1",
        "ev",
        "D0",
        trips=(
            DutyTrip(1, ("C1",)),
            DutyTrip(2, ("C2",)),
        ),
    )
    context = SimpleNamespace(
        bundle=SimpleNamespace(
            instance=SimpleNamespace(nodes=()),
            time_profile=(),
            prices=PriceParameters(),
        ),
    )
    policy = ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode="same_day_predeparture",
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )
    calls: list[tuple[str, str]] = []
    rebuilt_order: list[tuple[str, ...]] = []

    def fake_route_candidates(
        route,
        *args,
        charge_amount_strategy,
        **kwargs,
    ):
        calls.append((route.vehicle_id, charge_amount_strategy))
        labelled_route = type(route)(
            vehicle_id=route.vehicle_id,
            vehicle_type=route.vehicle_type,
            home_depot_id=route.home_depot_id,
            node_sequence=[
                *route.node_sequence,
                charge_amount_strategy,
            ],
        )
        return (("fake", labelled_route, ()),)

    def fake_rebuild(*args, **kwargs):
        routes = args[2]
        rebuilt_order.append(
            tuple(route.node_sequence[-1] for route in routes)
        )
        return duty

    monkeypatch.setattr(
        charging_module,
        "repair_route_charging_candidates",
        fake_route_candidates,
    )
    monkeypatch.setattr(
        charging_module,
        "_assert_customer_order",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        charging_module,
        "_rebuild_ev_duty",
        fake_rebuild,
    )

    candidates = charging_module._repair_one_ev_duty_candidates(
        duty,
        duty,
        context=context,
        policy=policy,
        amount_strategies=("first", "second"),
    )

    assert next(candidates) == duty
    assert calls == [
        (duty.route_id(1), "first"),
        (duty.route_id(2), "first"),
    ]
    tuple(candidates)
    assert rebuilt_order == [
        ("first", "first"),
        ("first", "second"),
        ("second", "first"),
        ("second", "second"),
    ]
