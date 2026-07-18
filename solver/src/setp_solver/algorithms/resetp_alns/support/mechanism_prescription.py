"""Context-gated prescriptions for the ReSETP mechanism ALNS.

The generic ALNS selector remains responsible for ordinary route search.  This
module only answers a narrower question: does the current complete solution
show an observable model-specific symptom for which a dedicated expert
already exists?

The design follows the current-state conditioning principle studied by Johnn
et al. (2023, arXiv:2302.14678) and the contextual-state interface documented
by Wouda and Lan (2023, doi:10.21105/joss.05028).  The pressure formulae and
the symptom-to-prescription mapping below are project-specific hypotheses.
They carry no theoretical performance guarantee and must pass isolated
behaviour and paired performance gates before promotion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any

from setp_solver.algorithms.resetp_alns.operators.carbon_operators import (
    low_carbon_charging_share,
)
from setp_solver.solution import Solution, physical_vehicle_id


TOL = 1.0e-9

RESPONSIBILITY = "multi_depot_responsibility"
FLEET_CHARGE = "fleet_charge"
CARBON_TIME = "carbon_time"

MECHANISM_ORDER = (RESPONSIBILITY, FLEET_CHARGE, CARBON_TIME)

@dataclass(frozen=True)
class MechanismSignal:
    """One cheap, complete-solution symptom measurement."""

    mechanism_id: str
    eligible: bool
    pressure: float
    threshold: float
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MechanismPrescription:
    """One model-specific expert selected for the current solution."""

    mechanism_id: str
    pressure: float
    signal: MechanismSignal


@dataclass(frozen=True)
class PrescriptionControllerConfig:
    """Frozen low-cost scheduling controls for the stage-one probe."""

    assessment_interval: int = 20
    per_mechanism_cooldown: int = 60
    enabled_mechanisms: tuple[str, ...] = MECHANISM_ORDER
    responsibility_threshold: float = 0.75
    fleet_charge_threshold: float = 0.75
    carbon_time_threshold: float = 0.50

    def __post_init__(self) -> None:
        if int(self.assessment_interval) < 1:
            raise ValueError("assessment_interval must be positive")
        if int(self.per_mechanism_cooldown) < 0:
            raise ValueError("per_mechanism_cooldown must be non-negative")
        unknown = set(self.enabled_mechanisms) - set(MECHANISM_ORDER)
        if unknown:
            raise ValueError(
                f"unknown enabled mechanisms: {sorted(unknown)}"
            )
        for name, value in (
            ("responsibility_threshold", self.responsibility_threshold),
            ("fleet_charge_threshold", self.fleet_charge_threshold),
            ("carbon_time_threshold", self.carbon_time_threshold),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must lie in [0, 1]")


class MechanismPrescriptionController:
    """Sparse deterministic controller over three static online mechanisms.

    The controller does not score candidates, repair routes, inspect future
    solutions, or draw random numbers.  It only reads the current complete
    solution and input context.  Ordinary ALNS remains active whenever no
    prescription is due.
    """

    def __init__(
        self,
        config: PrescriptionControllerConfig | None = None,
    ) -> None:
        self.config = config or PrescriptionControllerConfig()
        self._next_assessment_eval = 0
        self._last_attempt_eval = {
            mechanism_id: -10**18 for mechanism_id in MECHANISM_ORDER
        }
        self._assessment_count = 0
        self._eligible_observations = {
            mechanism_id: 0 for mechanism_id in MECHANISM_ORDER
        }
        self._attempts = {mechanism_id: 0 for mechanism_id in MECHANISM_ORDER}
        self._changed = {mechanism_id: 0 for mechanism_id in MECHANISM_ORDER}
        self._accepted = {mechanism_id: 0 for mechanism_id in MECHANISM_ORDER}
        self._best_improved = {
            mechanism_id: 0 for mechanism_id in MECHANISM_ORDER
        }
        self._no_op = {mechanism_id: 0 for mechanism_id in MECHANISM_ORDER}
        self._complete_candidate_evaluations = {
            mechanism_id: 0 for mechanism_id in MECHANISM_ORDER
        }
        self._scope_violations = {
            mechanism_id: 0 for mechanism_id in MECHANISM_ORDER
        }
        self._last_signals: list[MechanismSignal] = []
        self._event_log: list[dict[str, Any]] = []

    def choose(
        self,
        solution: Solution,
        context: Any,
        *,
        eval_count: int,
        move_count: int,
        moves_since_best_improvement: int,
    ) -> MechanismPrescription | None:
        """Return at most one due prescription without consuming evaluation."""

        del move_count, moves_since_best_improvement
        current_eval = int(eval_count)
        if current_eval < int(self._next_assessment_eval):
            return None
        self._next_assessment_eval = (
            current_eval + int(self.config.assessment_interval)
        )
        self._assessment_count += 1

        signals = assess_static_mechanisms(
            solution,
            context,
            config=self.config,
        )
        self._last_signals = signals
        eligible: list[MechanismSignal] = []
        for signal in signals:
            if signal.mechanism_id not in self.config.enabled_mechanisms:
                continue
            if signal.eligible:
                self._eligible_observations[signal.mechanism_id] += 1
            cooldown_ready = (
                current_eval - int(
                    self._last_attempt_eval[signal.mechanism_id]
                )
                >= int(self.config.per_mechanism_cooldown)
            )
            if signal.eligible and cooldown_ready:
                eligible.append(signal)
        if not eligible:
            return None

        order = {
            mechanism_id: index
            for index, mechanism_id in enumerate(MECHANISM_ORDER)
        }
        selected = min(
            eligible,
            key=lambda signal: (
                -float(signal.pressure),
                order[signal.mechanism_id],
            ),
        )
        self._last_attempt_eval[selected.mechanism_id] = current_eval
        self._attempts[selected.mechanism_id] += 1
        self._event_log.append(
            {
                "eval_before": current_eval,
                "mechanism_id": selected.mechanism_id,
                "pressure": float(selected.pressure),
                "signal_reason": selected.reason,
                "signal_metrics": dict(selected.metrics),
            }
        )
        return MechanismPrescription(
            mechanism_id=selected.mechanism_id,
            pressure=float(selected.pressure),
            signal=selected,
        )

    def record_no_candidate(
        self,
        prescription: MechanismPrescription,
        *,
        activity: dict[str, Any],
    ) -> None:
        """Record a diagnosed symptom whose exact expert found no improvement."""

        mechanism_id = prescription.mechanism_id
        self._no_op[mechanism_id] += 1
        self._event_log[-1].update(
            {
                "proposal_built": False,
                "changed": False,
                "accepted": False,
                "best_improved": False,
                "evaluations_added": 0,
                "expert_activity": dict(activity),
            }
        )

    def record_outcome(
        self,
        prescription: MechanismPrescription,
        *,
        source_solution: Solution,
        candidate_solution: Solution,
        changed: bool,
        accepted: bool,
        best_improved: bool,
        evaluations_added: int,
        candidate_objective: float,
        previous_objective: float,
        expert_activity: dict[str, Any] | None = None,
    ) -> None:
        """Record attributable behaviour after the common ALNS decision."""

        mechanism_id = prescription.mechanism_id
        self._complete_candidate_evaluations[mechanism_id] += int(
            evaluations_added
        )
        if changed:
            self._changed[mechanism_id] += 1
        else:
            self._no_op[mechanism_id] += 1
        if accepted:
            self._accepted[mechanism_id] += 1
        if best_improved:
            self._best_improved[mechanism_id] += 1

        scope = _decision_scope(
            mechanism_id,
            source_solution,
            candidate_solution,
        )
        if not bool(scope["scope_respected"]):
            self._scope_violations[mechanism_id] += 1
        self._event_log[-1].update(
            {
                "changed": bool(changed),
                "accepted": bool(accepted),
                "best_improved": bool(best_improved),
                "evaluations_added": int(evaluations_added),
                "candidate_objective": float(candidate_objective),
                "previous_objective": float(previous_objective),
                "objective_delta": float(
                    candidate_objective - previous_objective
                ),
                "proposal_built": True,
                "expert_activity": dict(expert_activity or {}),
                **scope,
            }
        )

    def diagnostics(self) -> dict[str, Any]:
        """Return a JSON-safe, attribution-ready audit record."""

        return {
            "controller": "deterministic_context_gated_prescriptions_v1",
            "config": asdict(self.config),
            "assessment_count": int(self._assessment_count),
            "eligible_observations": dict(self._eligible_observations),
            "attempts": dict(self._attempts),
            "changed": dict(self._changed),
            "accepted": dict(self._accepted),
            "best_improved": dict(self._best_improved),
            "no_op": dict(self._no_op),
            "complete_candidate_evaluations": dict(
                self._complete_candidate_evaluations
            ),
            "scope_violations": dict(self._scope_violations),
            "last_signals": [
                _signal_payload(signal) for signal in self._last_signals
            ],
            "events": list(self._event_log),
            "deferred_static_ineligible_mechanisms": {
                "fairness": (
                    "requires a binding profit floor and cached independent "
                    "depot profit baselines"
                ),
                "dynamic_demand": (
                    "requires an event time, frozen executed prefix, and "
                    "inherited vehicle state"
                ),
            },
        }


def assess_static_mechanisms(
    solution: Solution,
    context: Any,
    *,
    config: PrescriptionControllerConfig | None = None,
) -> list[MechanismSignal]:
    """Measure the three static symptoms without evaluating a candidate."""

    cfg = config or PrescriptionControllerConfig()
    return [
        _responsibility_signal(
            solution,
            context,
            threshold=float(cfg.responsibility_threshold),
        ),
        _fleet_charge_signal(
            solution,
            context,
            threshold=float(cfg.fleet_charge_threshold),
        ),
        _carbon_time_signal(
            solution,
            context,
            threshold=float(cfg.carbon_time_threshold),
        ),
    ]


def _responsibility_signal(
    solution: Solution,
    context: Any,
    *,
    threshold: float,
) -> MechanismSignal:
    mechanism_id = RESPONSIBILITY
    owners = dict(getattr(context, "customer_home_depot", None) or {})
    depots = sorted(
        node.node_id
        for node in context.instance.nodes
        if str(node.node_type).lower() == "d"
    )
    if (
        not bool(getattr(context, "allow_cross_depot", False))
        or not owners
        or len(depots) < 2
    ):
        return _ineligible(
            mechanism_id,
            threshold,
            "multi_depot_owner_context_absent",
            {
                "depot_count": len(depots),
                "owner_count": len(owners),
                "allow_cross_depot": bool(
                    getattr(context, "allow_cross_depot", False)
                ),
            },
        )

    node_types = {
        node.node_id: str(node.node_type).lower()
        for node in context.instance.nodes
    }
    boundary_scores: list[tuple[float, str]] = []
    misassignment_scores: list[tuple[float, str]] = []
    home_served = 0
    cross_served = 0
    for route in solution.routes:
        for customer_id in route.node_sequence:
            if node_types.get(customer_id) != "c":
                continue
            owner = owners.get(customer_id)
            if owner is None or owner not in depots:
                continue
            if route.home_depot_id != owner:
                cross_served += 1
                owner_distance = float(
                    context.instance.distance(owner, customer_id)
                )
                served_distance = float(
                    context.instance.distance(
                        route.home_depot_id,
                        customer_id,
                    )
                )
                denominator = max(
                    owner_distance,
                    served_distance,
                    1.0,
                )
                misassignment_scores.append(
                    (
                        max(
                            0.0,
                            min(
                                1.0,
                                (
                                    served_distance - owner_distance
                                )
                                / denominator,
                            ),
                        ),
                        str(customer_id),
                    )
                )
                continue
            home_served += 1
            owner_distance = float(
                context.instance.distance(owner, customer_id)
            )
            alternate_distance = min(
                float(context.instance.distance(depot, customer_id))
                for depot in depots
                if depot != owner
            )
            denominator = max(
                owner_distance,
                alternate_distance,
                1.0,
            )
            boundary_score = 1.0 - min(
                1.0,
                abs(alternate_distance - owner_distance) / denominator,
            )
            boundary_scores.append(
                (float(boundary_score), str(customer_id))
            )
    diagnosed_scores = [
        *boundary_scores,
        *misassignment_scores,
    ]
    pressure = max(
        (score for score, _ in diagnosed_scores),
        default=0.0,
    )
    diagnosed_count = sum(
        score + TOL >= float(threshold)
        for score, _ in diagnosed_scores
    )
    metrics = {
        "depot_count": len(depots),
        "home_served_customer_count": int(home_served),
        "cross_served_customer_count": int(cross_served),
        "boundary_candidate_count": int(
            sum(
                score + TOL >= float(threshold)
                for score, _ in boundary_scores
            )
        ),
        "cross_site_misassignment_candidate_count": int(
            sum(
                score + TOL >= float(threshold)
                for score, _ in misassignment_scores
            )
        ),
        "best_boundary_customer": (
            max(diagnosed_scores)[1] if diagnosed_scores else None
        ),
        "best_responsibility_pressure": float(pressure),
    }
    return MechanismSignal(
        mechanism_id=mechanism_id,
        eligible=bool(diagnosed_count > 0 and pressure + TOL >= threshold),
        pressure=float(max(0.0, min(1.0, pressure))),
        threshold=float(threshold),
        reason=(
            "responsibility_mismatch_or_boundary_present"
            if diagnosed_count > 0
            else "no_responsibility_mismatch_or_near_boundary_customer"
        ),
        metrics=metrics,
    )


def _fleet_charge_signal(
    solution: Solution,
    context: Any,
    *,
    threshold: float,
) -> MechanismSignal:
    mechanism_id = FLEET_CHARGE
    physical_types: dict[str, str] = {}
    for route in solution.routes:
        physical_types.setdefault(
            physical_vehicle_id(route.vehicle_id),
            str(route.vehicle_type).lower(),
        )
    cv_count = sum(value == "cv" for value in physical_types.values())
    ev_count = sum(value == "ev" for value in physical_types.values())
    route_count = len(solution.routes)
    max_cv = _nonnegative_limit(
        getattr(context.instance, "num_cv", None)
    )
    max_ev = _nonnegative_limit(
        getattr(context.instance, "num_ev", None)
    )
    cv_to_ev_possible = cv_count > 0 and (
        max_ev is None or ev_count < max_ev
    )
    ev_to_cv_possible = ev_count > 0 and (
        max_cv is None or cv_count < max_cv
    )
    homogeneous_mixed_fleet = (
        route_count > 0
        and ((cv_count > 0) ^ (ev_count > 0))
        and (max_cv is None or max_cv > 0)
        and (max_ev is None or max_ev > 0)
        and (cv_to_ev_possible or ev_to_cv_possible)
    )
    pressure = 1.0 if homogeneous_mixed_fleet else 0.0
    metrics = {
        "route_count": int(route_count),
        "physical_cv_count": int(cv_count),
        "physical_ev_count": int(ev_count),
        "available_cv_limit": max_cv,
        "available_ev_limit": max_ev,
        "cv_to_ev_possible": bool(cv_to_ev_possible),
        "ev_to_cv_possible": bool(ev_to_cv_possible),
        "positive_charge_action_count": sum(
            float(action.energy_kwh) > TOL
            for action in solution.charging_actions
        ),
        "homogeneous_solution_with_both_fleet_types_available": bool(
            homogeneous_mixed_fleet
        ),
    }
    return MechanismSignal(
        mechanism_id=mechanism_id,
        eligible=bool(pressure + TOL >= threshold),
        pressure=float(pressure),
        threshold=float(threshold),
        reason=(
            "homogeneous_solution_in_mixed_fleet"
            if homogeneous_mixed_fleet
            else "no_homogeneous_mixed_fleet_mismatch"
        ),
        metrics=metrics,
    )


def _carbon_time_signal(
    solution: Solution,
    context: Any,
    *,
    threshold: float,
) -> MechanismSignal:
    mechanism_id = CARBON_TIME
    positive_actions = [
        action
        for action in solution.charging_actions
        if float(action.energy_kwh) > TOL
    ]
    profile = list(getattr(context, "carbon_profile", None) or [])
    gammas = [_gamma(row) for row in profile]
    spread = max(gammas) - min(gammas) if gammas else 0.0
    if not positive_actions or spread <= TOL:
        return _ineligible(
            mechanism_id,
            threshold,
            (
                "no_positive_charging_action"
                if not positive_actions
                else "flat_or_missing_carbon_profile"
            ),
            {
                "positive_charge_action_count": len(positive_actions),
                "carbon_profile_row_count": len(profile),
                "carbon_intensity_spread": float(spread),
            },
        )
    low_share = float(
        low_carbon_charging_share(
            solution,
            context.instance,
            profile,
            context.prices,
        )
    )
    pressure = max(0.0, min(1.0, 1.0 - low_share))
    metrics = {
        "positive_charge_action_count": len(positive_actions),
        "total_positive_charge_kwh": float(
            sum(float(action.energy_kwh) for action in positive_actions)
        ),
        "carbon_profile_row_count": len(profile),
        "carbon_intensity_spread": float(spread),
        "lowest_quartile_charging_share": float(low_share),
        "non_low_carbon_charging_share": float(pressure),
    }
    return MechanismSignal(
        mechanism_id=mechanism_id,
        eligible=bool(pressure + TOL >= threshold),
        pressure=float(pressure),
        threshold=float(threshold),
        reason=(
            "charging_outside_low_carbon_quartile"
            if pressure + TOL >= threshold
            else "charging_already_concentrated_in_low_carbon_quartile"
        ),
        metrics=metrics,
    )


def _decision_scope(
    mechanism_id: str,
    source: Solution,
    candidate: Solution,
) -> dict[str, Any]:
    station_ids = {
        action.station_id
        for solution in (source, candidate)
        for action in solution.charging_actions
    }
    route_order_changed = _route_order_fingerprint(
        source,
        ignored_node_ids=station_ids,
    ) != _route_order_fingerprint(
        candidate,
        ignored_node_ids=station_ids,
    )
    responsibility_changed = _responsibility_fingerprint(
        source
    ) != _responsibility_fingerprint(candidate)
    vehicle_type_changed = _vehicle_type_fingerprint(
        source
    ) != _vehicle_type_fingerprint(candidate)
    charging_changed = _charging_fingerprint(
        source
    ) != _charging_fingerprint(candidate)

    if mechanism_id == RESPONSIBILITY:
        respected = (
            responsibility_changed
            and not vehicle_type_changed
            and not charging_changed
        )
    elif mechanism_id == FLEET_CHARGE:
        respected = (
            not route_order_changed
            and not responsibility_changed
            and (vehicle_type_changed or charging_changed)
        )
    elif mechanism_id == CARBON_TIME:
        respected = (
            not route_order_changed
            and not responsibility_changed
            and not vehicle_type_changed
            and charging_changed
        )
    else:
        respected = False
    unchanged = source == candidate
    return {
        "route_customer_order_changed": bool(route_order_changed),
        "responsibility_changed": bool(responsibility_changed),
        "vehicle_type_changed": bool(vehicle_type_changed),
        "charging_changed": bool(charging_changed),
        "scope_respected": bool(unchanged or respected),
    }


def _route_order_fingerprint(
    solution: Solution,
    *,
    ignored_node_ids: set[str],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        sorted(
            (
                str(route.home_depot_id),
                tuple(
                    node_id
                    for node_id in route.node_sequence
                    if node_id not in ignored_node_ids
                ),
            )
            for route in solution.routes
        )
    )


def _responsibility_fingerprint(
    solution: Solution,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                str(service.customer_id),
                str(service.served_by_depot_id),
            )
            for service in solution.cross_site_services
        )
    )


def _vehicle_type_fingerprint(
    solution: Solution,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                physical_vehicle_id(route.vehicle_id),
                str(route.vehicle_type).lower(),
            )
            for route in solution.routes
        )
    )


def _charging_fingerprint(
    solution: Solution,
) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        sorted(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.energy_kwh), 9),
                round(float(action.occupancy_minutes), 9),
                round(float(action.charge_start_second), 9),
                int(action.charge_day_offset),
            )
            for action in solution.charging_actions
        )
    )


def _ineligible(
    mechanism_id: str,
    threshold: float,
    reason: str,
    metrics: dict[str, Any] | None = None,
) -> MechanismSignal:
    return MechanismSignal(
        mechanism_id=mechanism_id,
        eligible=False,
        pressure=0.0,
        threshold=float(threshold),
        reason=str(reason),
        metrics=dict(metrics or {}),
    )


def _nonnegative_limit(value: Any) -> int | None:
    if value is None:
        return None
    numeric = int(float(value))
    return max(0, numeric)


def _gamma(row: dict[str, Any]) -> float:
    return float(
        row.get(
            "actual_gco2_per_kwh",
            row.get("forecast_gco2_per_kwh", 0.0),
        )
    )


def _signal_payload(signal: MechanismSignal) -> dict[str, Any]:
    payload = asdict(signal)
    pressure = float(payload["pressure"])
    payload["pressure"] = pressure if math.isfinite(pressure) else 0.0
    return payload
