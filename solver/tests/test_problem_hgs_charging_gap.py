"""SC3 charging-gap outcomes, A2 assembly, and pool separation."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import _build_context, _policy  # noqa: E402
import setp_solver.algorithms.problem_hgs.charging as charging_module  # noqa: E402
from setp_solver.algorithms.problem_hgs.charging import (  # noqa: E402
    ChargingRepairFailure,
    repair_changed_duties,
    repair_changed_duties_outcome,
)
from setp_solver.algorithms.problem_hgs.contracts import (  # noqa: E402
    CHARGING_ENERGY_GAP,
    CHARGING_WINDOW_GAP,
    CandidateOutcome,
    CandidateStatus,
    ChargingCandidateStatus,
    SearchAccounting,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
)
from setp_solver.algorithms.problem_hgs.model import (  # noqa: E402
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.algorithms.problem_hgs.population import (  # noqa: E402
    AdaptivePenaltyManager,
    DutyPopulation,
    PenaltyParameters,
    PopulationParameters,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402


INSTANCE_ID = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
SNAPSHOT = Path(__file__).parents[2] / (
    "solver/reports/design_probe_death_survey2_20260815/"
    "run2_reason_codes/charging_diagnosis/"
    "duty_crossover_rejected_candidates.jsonl"
)


def _individual_from_payload(payload: Mapping[str, Any]) -> DutyIndividual:
    duties = []
    for duty_row in payload["duties"]:
        assert duty_row.get("schedule") is None
        duties.append(
            PhysicalVehicleDuty(
                physical_vehicle_id=str(duty_row["physical_vehicle_id"]),
                vehicle_type=str(duty_row["vehicle_type"]),
                home_depot_id=str(duty_row["home_depot_id"]),
                trips=tuple(
                    DutyTrip(
                        trip_index=int(row["trip_index"]),
                        customer_ids=tuple(row["customer_ids"]),
                        locked_customer_prefix=tuple(
                            row.get("locked_customer_prefix", ())
                        ),
                        route_visits=tuple(row.get("route_visits", ())),
                    )
                    for row in duty_row["trips"]
                ),
                charging_sessions=tuple(
                    DutyChargingSession(**row)
                    for row in duty_row.get("charging_sessions", ())
                ),
                has_dynamic_commitment=bool(
                    duty_row.get("has_dynamic_commitment", False)
                ),
            )
        )
    return DutyIndividual(
        duties=tuple(duties),
        unserved_customers=tuple(payload.get("unserved_customers", ())),
        version=int(payload.get("version", 1)),
        source=str(payload.get("source", "sc3-snapshot")),
    )


@pytest.fixture(scope="module")
def sc3_case():
    repo = Path(__file__).parents[2]
    with SNAPSHOT.open(encoding="utf-8") as handle:
        payload = json.loads(next(handle))
    reference = _individual_from_payload(payload["reference"])
    candidate = _individual_from_payload(payload["raw_candidate"])
    assert reference.fingerprint == payload["reference_fingerprint"]
    assert candidate.fingerprint == payload["raw_candidate_fingerprint"]
    _bundle, initial, _pi0, context = _build_context(
        repo,
        INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
        depot_charging_scenario_name="60kw",
    )
    context = replace(context, depot_charge_window_mode="full_gap")
    evaluator = DutyFullEvaluator(context)
    policy = _policy(
        evaluator,
        first_trip_prev_night_enabled=True,
    )
    return {
        "payload": payload,
        "reference": reference,
        "candidate": candidate,
        "initial": initial,
        "context": context,
        "evaluator": evaluator,
        "policy_off": replace(policy, charging_gap_enabled=False),
        "policy_on": replace(policy, charging_gap_enabled=True),
    }


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
    )


def test_sc3_switch_is_off_by_default_and_recordable(sc3_case) -> None:
    policy = sc3_case["policy_off"]

    assert not policy.charging_gap_enabled
    assert asdict(policy)["charging_gap_enabled"] is False


def test_sc3_off_preserves_original_hard_rejection(sc3_case) -> None:
    with pytest.raises(ChargingRepairFailure) as caught:
        repair_changed_duties(
            sc3_case["reference"],
            sc3_case["candidate"],
            changed_duty_ids=set(sc3_case["payload"]["changed_duty_ids"]),
            context=sc3_case["context"],
            policy=sc3_case["policy_off"],
        )

    assert caught.value.charging_rejection_reason_code == "NO_FEASIBLE_WINDOW"


def test_sc3_three_typed_returns_are_covered(sc3_case) -> None:
    ready = repair_changed_duties_outcome(
        sc3_case["initial"],
        sc3_case["initial"],
        changed_duty_ids=set(),
        context=sc3_case["context"],
        policy=sc3_case["policy_on"],
    )
    best_effort = repair_changed_duties_outcome(
        sc3_case["reference"],
        sc3_case["candidate"],
        changed_duty_ids=set(sc3_case["payload"]["changed_duty_ids"]),
        context=sc3_case["context"],
        policy=sc3_case["policy_on"],
    )
    rejected = repair_changed_duties_outcome(
        sc3_case["initial"],
        sc3_case["initial"],
        changed_duty_ids={"EV_MISSING_1"},
        context=sc3_case["context"],
        policy=sc3_case["policy_on"],
    )

    assert ready.status == ChargingCandidateStatus.READY
    assert ready.gap.values == (0.0, 0.0)
    assert best_effort.status == ChargingCandidateStatus.BEST_EFFORT
    assert best_effort.gap.active
    assert best_effort.reason_code == "NO_FEASIBLE_WINDOW"
    assert rejected.status == ChargingCandidateStatus.REJECTED_INTERFACE
    assert rejected.candidate is None


def test_sc3_unsafe_gap_is_rejected_with_original_reason(
    sc3_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_unsafe_gap(*args, **kwargs):
        del args, kwargs
        raise ValueError("cannot safely materialise charging gap")

    monkeypatch.setattr(
        charging_module,
        "_best_effort_ev_duty_with_gap",
        reject_unsafe_gap,
    )
    rejected = repair_changed_duties_outcome(
        sc3_case["reference"],
        sc3_case["candidate"],
        changed_duty_ids=set(sc3_case["payload"]["changed_duty_ids"]),
        context=sc3_case["context"],
        policy=sc3_case["policy_on"],
    )

    assert rejected.status == ChargingCandidateStatus.REJECTED_CHARGING
    assert rejected.reason_code == "NO_FEASIBLE_WINDOW"
    assert rejected.gap.values == (0.0, 0.0)
    assert rejected.candidate is None


def test_sc3_snapshot_gap_is_recomputed_term_by_term(sc3_case) -> None:
    outcome = repair_changed_duties_outcome(
        sc3_case["reference"],
        sc3_case["candidate"],
        changed_duty_ids=set(sc3_case["payload"]["changed_duty_ids"]),
        context=sc3_case["context"],
        policy=sc3_case["policy_on"],
    )

    energy = sum(
        max(
            0.0,
            row.required_departure_energy_kwh - row.reachable_energy_kwh,
        )
        for row in outcome.clock_witnesses
    )
    window = sum(
        max(
            0.0,
            row.required_window_seconds - row.available_window_seconds,
        )
        for row in outcome.clock_witnesses
    )

    assert energy == outcome.gap.missing_energy_kwh
    assert window == outcome.gap.window_shortage_seconds
    assert outcome.gap.missing_energy_kwh == 20.548830452123916
    assert outcome.gap.window_shortage_seconds == 1236.5560913248687


def test_sc3_best_effort_enters_a2_but_not_feasible_pool(sc3_case) -> None:
    outcome = repair_changed_duties_outcome(
        sc3_case["reference"],
        sc3_case["candidate"],
        changed_duty_ids=set(sc3_case["payload"]["changed_duty_ids"]),
        context=sc3_case["context"],
        policy=sc3_case["policy_on"],
    )
    assert outcome.candidate is not None
    full = sc3_case["evaluator"].evaluate(outcome.candidate)
    violation_by_type = {
        violation.type: magnitude
        for violation, magnitude in zip(
            full.violations,
            full.violation_magnitudes,
            strict=True,
        )
    }
    manager = AdaptivePenaltyManager(_penalties())
    population = DutyPopulation(
        PopulationParameters.copied_hgs_defaults(),
        manager,
    )
    admission = population.add(outcome.candidate, full)
    manager.register(full)

    assert admission.inserted
    assert full.charging_candidate_status == ChargingCandidateStatus.BEST_EFFORT
    assert not full.feasible
    assert violation_by_type[CHARGING_ENERGY_GAP] == (
        outcome.gap.missing_energy_kwh
    )
    assert violation_by_type[CHARGING_WINDOW_GAP] == (
        outcome.gap.window_shortage_seconds
    )
    assert manager.registration_counts[CHARGING_ENERGY_GAP] == 1
    assert manager.registration_counts[CHARGING_WINDOW_GAP] == 1
    assert population.best_feasible() is None
    assert population.best_penalized() is not None


def test_sc3_gap_ledger_keeps_status_feasibility_and_raw_units(sc3_case) -> None:
    outcome = repair_changed_duties_outcome(
        sc3_case["reference"],
        sc3_case["candidate"],
        changed_duty_ids=set(sc3_case["payload"]["changed_duty_ids"]),
        context=sc3_case["context"],
        policy=sc3_case["policy_on"],
    )
    assert outcome.candidate is not None
    full = sc3_case["evaluator"].evaluate(outcome.candidate)
    accounting = SearchAccounting()
    accounting.record_outcome(
        CandidateOutcome(
            action_id="sc3-snapshot",
            channel="duty_crossover",
            status=CandidateStatus.EVALUATED,
            changed_duty_ids=frozenset(outcome.affected_duty_ids),
            candidate=outcome.candidate,
            evaluation=full,
            charging_rejection_reason=outcome.reason_code,
        )
    )
    recorded = accounting.to_dict()
    row = recorded["charging_gap_ledger"][0]

    assert row["candidate_status"] == "BEST_EFFORT"
    assert row["complete_feasible"] is False
    assert row["missing_energy_kwh"] == outcome.gap.missing_energy_kwh
    assert row["window_shortage_seconds"] == (
        outcome.gap.window_shortage_seconds
    )
    assert row["charging_rejection_reason"] == "NO_FEASIBLE_WINDOW"
    assert recorded["charging_gap_a2_evaluations"] == 1
    assert recorded["charging_gap_a2_violation_counts"] == {
        CHARGING_ENERGY_GAP: 1,
        CHARGING_WINDOW_GAP: 1,
    }


def test_sc3_best_effort_preserves_service_and_physical_assets(sc3_case) -> None:
    outcome = repair_changed_duties_outcome(
        sc3_case["reference"],
        sc3_case["candidate"],
        changed_duty_ids=set(sc3_case["payload"]["changed_duty_ids"]),
        context=sc3_case["context"],
        policy=sc3_case["policy_on"],
    )
    assert outcome.candidate is not None
    before_ids = tuple(
        duty.physical_vehicle_id for duty in sc3_case["candidate"].duties
    )
    after_ids = tuple(
        duty.physical_vehicle_id for duty in outcome.candidate.duties
    )
    served = {
        customer
        for duty in outcome.candidate.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }

    assert after_ids == before_ids
    assert len(served) == 50
    assert not outcome.candidate.unserved_customers
