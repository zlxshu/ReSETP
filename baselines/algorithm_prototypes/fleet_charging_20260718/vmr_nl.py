"""FC-C05 model-neutral VMR-NL interface stub and manual micro case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from contracts import (
    ChargingOracle,
    ChargingOracleResult,
    CompleteEvaluationBudget,
    FixedRouteChargingRequest,
    ProbeCounters,
)


@dataclass(frozen=True)
class ModeCandidate:
    candidate_id: str
    customer_id: str
    route_id: str
    insertion_position: int
    vehicle_mode: str
    screen_priority: int
    abstract_base_score: float
    screen_feasible: bool
    charging_request: FixedRouteChargingRequest | None = None


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: ModeCandidate
    score: float
    oracle_result: ChargingOracleResult | None


@dataclass(frozen=True)
class VMRNLResult:
    selected: CandidateEvaluation | None
    regret: float | None
    evaluated: tuple[CandidateEvaluation, ...]
    active: bool


ScoreFunction = Callable[[ModeCandidate, ChargingOracleResult | None], float]


class VMRNLSelector:
    """A deterministic interface stub; formal objectives remain injected."""

    def __init__(self, oracle: ChargingOracle, score_function: ScoreFunction):
        self.oracle = oracle
        self.score_function = score_function

    def select(
        self,
        candidates: tuple[ModeCandidate, ...],
        budget: CompleteEvaluationBudget,
        counters: ProbeCounters,
        top_b: int,
    ) -> VMRNLResult:
        if top_b <= 0:
            raise ValueError("top_b must be positive")
        if budget.limit == 0:
            return VMRNLResult(None, None, (), False)

        screened: list[ModeCandidate] = []
        for candidate in sorted(candidates, key=lambda item: item.screen_priority):
            counters.screen_evaluations += 1
            if candidate.screen_feasible:
                screened.append(candidate)
            if len(screened) >= top_b:
                break

        evaluated: list[CandidateEvaluation] = []
        for candidate in screened:
            if not budget.reserve():
                break
            oracle_result = None
            if candidate.charging_request is not None:
                oracle_result = self.oracle.solve(candidate.charging_request, counters)
                if not oracle_result.feasible:
                    score = float("inf")
                else:
                    score = self.score_function(candidate, oracle_result)
            else:
                score = self.score_function(candidate, None)
            evaluated.append(CandidateEvaluation(candidate, float(score), oracle_result))

        if not evaluated:
            return VMRNLResult(None, None, (), False)
        ranked = sorted(evaluated, key=lambda item: (item.score, item.candidate.candidate_id))
        selected = ranked[0]
        best_by_mode: dict[str, float] = {}
        for item in ranked:
            mode = item.candidate.vehicle_mode
            best_by_mode[mode] = min(best_by_mode.get(mode, float("inf")), item.score)
        alternative_mode_scores = sorted(
            score for mode, score in best_by_mode.items()
            if mode != selected.candidate.vehicle_mode
        )
        regret = (
            alternative_mode_scores[0] - selected.score
            if alternative_mode_scores
            else None
        )
        return VMRNLResult(
            selected=selected,
            regret=regret,
            evaluated=tuple(evaluated),
            active=len({item.candidate.vehicle_mode for item in evaluated}) > 1,
        )


def abstract_probe_score(
    candidate: ModeCandidate,
    oracle_result: ChargingOracleResult | None,
) -> float:
    """Injected demonstration score, explicitly not the ReSETP objective."""

    return candidate.abstract_base_score + (
        0.0 if oracle_result is None else oracle_result.objective
    )


def build_fc_c05_manual_candidates(
    charging_request: FixedRouteChargingRequest,
) -> tuple[ModeCandidate, ...]:
    """A hand-auditable candidate set with no formal parameter claim."""

    return (
        ModeCandidate(
            "M1", "customer-A", "route-1", 1, "EV_WITH_CHARGE", 1, 1.0, True,
            charging_request,
        ),
        ModeCandidate(
            "M2", "customer-A", "route-1", 1, "CV_DIRECT", 2, 7.0, True,
        ),
        ModeCandidate(
            "M3", "customer-A", "route-2", 1, "EV_DIRECT", 3, 0.0, False,
        ),
        ModeCandidate(
            "M4", "customer-A", "route-2", 1, "EV_WITH_CHARGE", 4, 3.0, True,
            charging_request,
        ),
        ModeCandidate(
            "M5", "customer-A", "route-3", 2, "CV_DIRECT", 5, 9.0, True,
        ),
        ModeCandidate(
            "M6", "customer-A", "route-3", 2, "EV_DIRECT", 6, 8.0, True,
        ),
    )


def independently_select_manual_reference(
    candidates: tuple[ModeCandidate, ...],
    oracle_objective: float,
    evaluated_candidate_ids: set[str],
) -> tuple[str | None, float | None]:
    """Independent direct enumeration for the manual micro case."""

    scored: list[tuple[float, str, str]] = []
    for candidate in candidates:
        if candidate.candidate_id not in evaluated_candidate_ids:
            continue
        score = candidate.abstract_base_score
        if candidate.charging_request is not None:
            score += oracle_objective
        scored.append((score, candidate.candidate_id, candidate.vehicle_mode))
    if not scored:
        return None, None
    scored.sort()
    selected_score, selected_id, selected_mode = scored[0]
    alternative_modes: dict[str, float] = {}
    for score, _, mode in scored:
        if mode != selected_mode:
            alternative_modes[mode] = min(alternative_modes.get(mode, float("inf")), score)
    regret = min(alternative_modes.values()) - selected_score if alternative_modes else None
    return selected_id, regret

