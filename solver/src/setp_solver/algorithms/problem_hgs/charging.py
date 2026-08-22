"""Safe charging reconstruction for changed physical-vehicle duties.

v1 2026-08-07: wrap the existing nonlinear route repair and multi-trip
certificate without changing either upstream module.  Every scientific choice
is an explicit input; identity, customer order, dynamic locks, and the final
battery ledger are checked after reconstruction.

v2 2026-08-07: use local pre-horizon time for a first depot charge and the
actual inter-trip gap for later depot charges in all registered window modes.

v3 2026-08-07: anchor every depot action to the preceding trip's actual end
energy before certificate validation.  Locked trips retain their complete
registered charging ledger; unlocked later trips may be repaired without
rewriting an earlier dynamic commitment.

v4 2026-08-10: search static charging clocks as serial one-session moves.
Repeated education can combine accepted shifts, while one round grows with the
sum rather than the Cartesian product of legal start times.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from itertools import chain
from typing import Any

from setp_solver.charge_timing import (
    charge_timing_objective_value,
    select_charge_timing_start,
)
from setp_solver.algorithms.resetp_alns.support.charging import (
    curve_knee_strategies,
    repair_route_charging,
    repair_route_charging_candidates,
)
from setp_solver.charging_action import _curve_aware_action
from setp_solver.cost import route_departure_second, time_profile_rows_for_node
from setp_solver.search.multitrip_schedule import (
    STATIC_PREHORIZON_SECONDS,
    certified_depot_charge_window,
    prepare_multitrip_solution,
    route_timing,
    select_certified_depot_charge_start,
)
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id

from .evaluation import DutyEvaluationContext, evaluation_context_sha256
from .frvcpy_adapter import solve_fixed_route_charging
from .contracts import (
    ChargingCandidateStatus,
    ChargingRepairOutcome,
)
from .model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
    assert_locks_preserved,
)


DYNAMIC_DEPOT_ONLY_CANDIDATE_MODE = "dynamic_depot_only"
PRESCREEN_CHANNELS = frozenset({"depot_collaboration", "multi_trip"})
PRESCREEN_NO_DEPARTURE = "no_feasible_departure"
PRESCREEN_TIME_WINDOW = "time_window"
PRESCREEN_UNCERTAIN = "uncertain"

CHARGING_REASON_NO_FEASIBLE_WINDOW = "NO_FEASIBLE_WINDOW"
CHARGING_REASON_INSUFFICIENT_ENERGY = "INSUFFICIENT_ENERGY"
CHARGING_REASON_NO_FEASIBLE_INSERT = "NO_FEASIBLE_INSERT_FOUND"
CHARGING_REASON_REPAIR_ATTEMPT_CAP = "REPAIR_ATTEMPT_CAP"
CHARGING_REASON_SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"
CHARGING_REASON_PRESCREEN_REJECT = "PRESCREEN_REJECT"
CHARGING_REASON_OTHER = "CHARGING_REPAIR_OTHER"


def charging_rejection_reason(error: Exception) -> str:
    """Classify an observed charging failure without changing its decision."""

    explicit = getattr(error, "charging_rejection_reason_code", None)
    if explicit is not None:
        return str(explicit)
    cause = getattr(error, "cause", None)
    if isinstance(cause, Exception) and cause is not error:
        return charging_rejection_reason(cause)

    message = str(error).lower()
    if any(
        token in message
        for token in (
            "attempt cap",
            "attempt limit",
            "repair iteration limit",
            "repair search exhausted",
        )
    ):
        return CHARGING_REASON_REPAIR_ATTEMPT_CAP
    if any(
        token in message
        for token in (
            "no feasible charging insert",
            "no charging stations available",
            "forced public-station path was not fully used",
            "no charging path",
        )
    ):
        return CHARGING_REASON_NO_FEASIBLE_INSERT
    if any(
        token in message
        for token in (
            "requires more energy than",
            "requires more than the battery",
            "requires ",
            "battery below zero",
            "battery falls below zero",
            "exceeds battery energy bounds",
            "insufficient energy",
            "frvcpy found no energy-feasible charging plan",
        )
    ) and any(
        token in message
        for token in ("battery", " kwh", " b=")
    ):
        return CHARGING_REASON_INSUFFICIENT_ENERGY
    if any(
        token in message
        for token in (
            "no certified depot charging window",
            "no feasible fixed-route charging window",
            "latest charging start precedes earliest start",
            "depot charge does not fit before departure",
            "no feasible depot charging window",
        )
    ):
        return CHARGING_REASON_NO_FEASIBLE_WINDOW
    if any(
        token in message
        for token in (
            "no feasible departure time",
            "time window",
            "turnaround",
            "trip overlap",
            "charging overlap",
            "overlap or incomplete recharge",
            "schedule conflict",
            "no time-feasible charging schedule",
            "does not fit customer windows",
        )
    ):
        return CHARGING_REASON_SCHEDULE_CONFLICT
    return CHARGING_REASON_OTHER


class ChargingRepairFailure(ValueError):
    """Identify the physical duty whose exact charging repair failed."""

    def __init__(
        self,
        duty_id: str,
        cause: Exception,
        *,
        reason_code: str | None = None,
    ) -> None:
        self.duty_id = str(duty_id)
        self.cause = cause
        self.charging_rejection_reason_code = (
            charging_rejection_reason(cause)
            if reason_code is None
            else str(reason_code)
        )
        super().__init__(f"{self.duty_id}: {cause}")


class ChargingPrescreenEquivalenceError(RuntimeError):
    """Stop immediately if a prescreen rejection survives full repair."""


@dataclass
class ChargingFeasibilityPrescreen:
    """Reject only route clocks that the full repair itself rejects first.

    The full charging path starts each unlocked EV trip by calling
    ``route_timing(..., charging_actions=[], validate_battery=False)``.  CV
    ledger replay uses that same function.  Reusing it here preserves the
    exact floating-point time-window and departure-time standard; any other
    failure is deliberately treated as unknown and sent to full repair.
    """

    context: DutyEvaluationContext
    policy: ChargingRepairPolicy
    audit_limit: int = 0
    checked_by_channel: Counter[str] = field(default_factory=Counter)
    rejected_by_channel: Counter[str] = field(default_factory=Counter)
    passed_by_channel: Counter[str] = field(default_factory=Counter)
    rejected_by_channel_and_reason: Counter[str] = field(
        default_factory=Counter
    )
    route_cache_hits: int = 0
    route_cache_misses: int = 0
    audit_sampled: int = 0
    audit_same_rejection: int = 0
    _route_cache: dict[
        tuple[str, str, str, int, tuple[str, ...]],
        tuple[str, str] | None,
    ] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if int(self.audit_limit) < 0:
            raise ValueError("charging prescreen audit limit cannot be negative")

    def screen(
        self,
        reference: DutyIndividual,
        candidate: DutyIndividual,
        *,
        changed_duty_ids: frozenset[str],
        channel: str,
        preserve_explicit_charging_duty_ids: frozenset[str] = frozenset(),
    ) -> ChargingRepairFailure | None:
        """Return the exact full-repair failure, or ``None`` when uncertain."""

        if (
            channel not in PRESCREEN_CHANNELS
            or self.context.dynamic_state is not None
            or self.policy.frvcpy_enabled
            or preserve_explicit_charging_duty_ids
        ):
            return None

        self.checked_by_channel[channel] += 1
        for duty in candidate.duties:
            duty_id = duty.physical_vehicle_id
            if duty_id not in changed_duty_ids:
                continue
            for trip in duty.trips:
                if (
                    duty.vehicle_type == "ev"
                    and trip.trip_index in duty.locked_charging_trip_indices
                ):
                    continue
                failure = self._screen_trip(duty, trip)
                if failure is None:
                    continue
                reason, message = failure
                if reason == PRESCREEN_UNCERTAIN:
                    self.passed_by_channel[channel] += 1
                    return None
                wrapped = ChargingRepairFailure(
                    duty_id,
                    ValueError(message),
                    reason_code=CHARGING_REASON_PRESCREEN_REJECT,
                )
                self._audit_rejection(
                    reference,
                    candidate,
                    changed_duty_ids=changed_duty_ids,
                    expected=wrapped,
                )
                self.rejected_by_channel[channel] += 1
                self.rejected_by_channel_and_reason[
                    f"{channel}:{reason}"
                ] += 1
                return wrapped

        self.passed_by_channel[channel] += 1
        return None

    def _screen_trip(
        self,
        duty: PhysicalVehicleDuty,
        trip: DutyTrip,
    ) -> tuple[str, str] | None:
        route = Route(
            vehicle_id=duty.route_id(trip.trip_index),
            vehicle_type=duty.vehicle_type,
            home_depot_id=duty.home_depot_id,
            node_sequence=[
                duty.home_depot_id,
                *trip.effective_route_visits,
                duty.home_depot_id,
            ],
        )
        key = (
            duty.physical_vehicle_id,
            duty.vehicle_type,
            duty.home_depot_id,
            int(trip.trip_index),
            tuple(route.node_sequence),
        )
        if key in self._route_cache:
            self.route_cache_hits += 1
            return self._route_cache[key]

        self.route_cache_misses += 1
        failure: tuple[str, str] | None = None
        try:
            route_timing(
                route,
                self.context.bundle.instance,
                self.context.bundle.prices,
                charging_actions=[],
                validate_battery=False,
            )
        except ValueError as exc:
            message = str(exc)
            if " has no feasible departure time" in message:
                failure = (PRESCREEN_NO_DEPARTURE, message)
            elif " misses " in message and "'s time window" in message:
                failure = (PRESCREEN_TIME_WINDOW, message)
            else:
                # Unknown means full repair.  A later trip must not mask the
                # earlier non-target failure that full repair would report.
                failure = (PRESCREEN_UNCERTAIN, message)
        self._route_cache[key] = failure
        return failure

    def _audit_rejection(
        self,
        reference: DutyIndividual,
        candidate: DutyIndividual,
        *,
        changed_duty_ids: frozenset[str],
        expected: ChargingRepairFailure,
    ) -> None:
        if self.audit_sampled >= int(self.audit_limit):
            return
        self.audit_sampled += 1
        try:
            repair_changed_duties(
                reference,
                candidate,
                changed_duty_ids=set(changed_duty_ids),
                context=self.context,
                policy=self.policy,
                cache=None,
            )
        except (TypeError, ValueError) as actual:
            if type(actual) is not type(expected) or str(actual) != str(expected):
                raise ChargingPrescreenEquivalenceError(
                    "charging prescreen and full repair rejected differently: "
                    f"prescreen={type(expected).__name__}: {expected}; "
                    f"full={type(actual).__name__}: {actual}"
                ) from actual
            self.audit_same_rejection += 1
            return
        raise ChargingPrescreenEquivalenceError(
            "charging prescreen rejected a candidate that full repair accepted: "
            f"{expected}"
        )

    def statistics(self) -> dict[str, Any]:
        checked = sum(self.checked_by_channel.values())
        rejected = sum(self.rejected_by_channel.values())
        passed = sum(self.passed_by_channel.values())
        channels = sorted(
            set(self.checked_by_channel)
            | set(self.rejected_by_channel)
            | set(self.passed_by_channel)
        )
        return {
            "enabled": True,
            "eligible_candidates": int(checked),
            "rejected_candidates": int(rejected),
            "rejected_fraction": (
                0.0 if checked == 0 else float(rejected) / float(checked)
            ),
            "entered_full_repair": int(passed),
            "by_channel": {
                channel: {
                    "eligible_candidates": int(
                        self.checked_by_channel[channel]
                    ),
                    "rejected_candidates": int(
                        self.rejected_by_channel[channel]
                    ),
                    "entered_full_repair": int(self.passed_by_channel[channel]),
                    "reasons": {
                        reason: int(
                            self.rejected_by_channel_and_reason[
                                f"{channel}:{reason}"
                            ]
                        )
                        for reason in (
                            PRESCREEN_TIME_WINDOW,
                            PRESCREEN_NO_DEPARTURE,
                        )
                    },
                }
                for channel in channels
            },
            "route_cache_hits": int(self.route_cache_hits),
            "route_cache_misses": int(self.route_cache_misses),
            "audit": {
                "requested_limit": int(self.audit_limit),
                "sampled": int(self.audit_sampled),
                "same_rejection": int(self.audit_same_rejection),
                "prescreen_false_rejections": 0,
            },
        }


@dataclass(frozen=True)
class ChargingRepairPolicy:
    """All externally selected charging semantics; no hidden defaults."""

    strategy: str
    carbon_weight: float
    depot_charge_window_mode: str
    charge_timing_policy: str
    charge_amount_strategy: str
    public_station_candidate_mode: str
    carbon_profiles_by_day_offset: Mapping[
        int, list[dict[str, Any]]
    ] | None
    first_trip_prev_night_enabled: bool = False
    frvcpy_enabled: bool = False


def _route_repair_window_modes(
    duty: PhysicalVehicleDuty,
    trip: DutyTrip,
    policy: ChargingRepairPolicy,
) -> tuple[str, ...]:
    """Expose the preceding-day alternative only for an unlocked first trip."""

    if policy.first_trip_prev_night_enabled and trip == duty.trips[0]:
        return ("same_day_predeparture", "prev_night")
    return ("same_day_predeparture",)


def _select_depot_charge_start_from_windows(
    action: ChargingAction,
    windows: tuple[tuple[str, float, float], ...],
    *,
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> tuple[float, int]:
    """Select once after merging already certified calendar windows."""

    candidates: list[tuple[float, float, float, int]] = []
    for mode, earliest, latest in windows:
        start, offset = select_certified_depot_charge_start(
            action,
            earliest,
            latest,
            context.bundle.instance,
            context.bundle.prices,
            context.bundle.time_profile,
            mode=mode,
            strategy=policy.strategy,
            carbon_weight=float(policy.carbon_weight),
            charge_timing_policy=policy.charge_timing_policy,
            carbon_profiles_by_day_offset=(
                policy.carbon_profiles_by_day_offset
            ),
        )
        if policy.carbon_profiles_by_day_offset is None:
            profile = context.bundle.time_profile
        else:
            try:
                profile = policy.carbon_profiles_by_day_offset[int(offset)]
            except KeyError as exc:
                raise ValueError(
                    "missing registered carbon/price profile for depot "
                    f"day offset {offset}"
                ) from exc
        placed = replace(
            action,
            charge_start_second=float(start),
            charge_day_offset=int(offset),
        )
        score = charge_timing_objective_value(
            placed,
            context.bundle.instance,
            profile,
            context.bundle.prices,
            charge_timing_policy=policy.charge_timing_policy,
        )
        absolute_start = (
            float(offset) * STATIC_PREHORIZON_SECONDS + float(start)
        )
        candidates.append(
            (float(score), absolute_start, float(start), int(offset))
        )
    if not candidates:
        raise ValueError("no certified depot charging window candidates")
    _, _, start, offset = min(candidates)
    return start, offset


@dataclass
class ChargingRepairCache:
    """Reuse deterministic EV-duty repairs within one search context."""

    context: DutyEvaluationContext
    policy: ChargingRepairPolicy
    repaired: dict[
        tuple[
            str,
            str,
            PhysicalVehicleDuty,
            PhysicalVehicleDuty,
        ],
        PhysicalVehicleDuty,
    ] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    context_identity: str = field(init=False, repr=False)
    policy_identity: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.context_identity = evaluation_context_sha256(self.context)
        self.policy_identity = hashlib.sha256(
            repr(self.policy).encode("utf-8")
        ).hexdigest()

    def repair(
        self,
        reference: PhysicalVehicleDuty,
        candidate: PhysicalVehicleDuty,
        *,
        context: DutyEvaluationContext,
        policy: ChargingRepairPolicy,
    ) -> PhysicalVehicleDuty:
        if context is not self.context or policy is not self.policy:
            raise ValueError(
                "charging repair cache was reused with another context or policy"
            )
        key = (
            self.context_identity,
            self.policy_identity,
            reference,
            candidate,
        )
        cached = self.repaired.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        result = _repair_one_ev_duty(
            reference,
            candidate,
            context=context,
            policy=policy,
        )
        self.repaired[key] = result
        return result


def repair_changed_duties(
    reference: DutyIndividual,
    candidate: DutyIndividual,
    *,
    changed_duty_ids: set[str],
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
    cache: ChargingRepairCache | None = None,
    preserve_explicit_charging_duty_ids: set[str] | None = None,
) -> DutyIndividual:
    """Rebuild only changed EV ledgers and preserve every locked decision."""

    if policy.depot_charge_window_mode != context.depot_charge_window_mode:
        raise ValueError(
            "charging repair and full evaluation use different depot windows"
        )

    if context.dynamic_state is not None:
        node_types = {
            node.node_id: node.node_type.lower()
            for node in context.bundle.instance.nodes
        }
        for duty in candidate.duties:
            visits_by_trip = {
                trip.trip_index: set(trip.effective_route_visits)
                for trip in duty.trips
            }
            for session in duty.charging_sessions:
                if (
                    session.locked
                    or node_types.get(session.station_id) != "f"
                    or session.station_id
                    not in visits_by_trip.get(session.trip_index, set())
                ):
                    raise ValueError(
                        "dynamic explicit charging must be an unlocked public "
                        "station visited by the same future trip"
                    )
        assert_locks_preserved(reference, candidate)
        return candidate

    candidate_by_id = {
        duty.physical_vehicle_id: duty for duty in candidate.duties
    }
    reference_by_id = {
        duty.physical_vehicle_id: duty for duty in reference.duties
    }
    unknown = set(changed_duty_ids).difference(candidate_by_id)
    if unknown:
        raise ValueError(f"charging repair received unknown duties: {sorted(unknown)}")

    preserved_ids = set(preserve_explicit_charging_duty_ids or ())
    if not preserved_ids.issubset(changed_duty_ids):
        raise ValueError("explicit charging scope must be part of changed duties")
    rebuilt: list[PhysicalVehicleDuty] = []
    for duty in candidate.duties:
        if duty.physical_vehicle_id not in changed_duty_ids:
            rebuilt.append(duty)
            continue
        if duty.vehicle_type == "cv":
            if duty.charging_sessions:
                raise ValueError("CV duty cannot retain charging sessions")
            try:
                _verify_prepared_ledger(duty, context)
            except (TypeError, ValueError) as error:
                raise ChargingRepairFailure(
                    duty.physical_vehicle_id,
                    error,
                ) from error
            rebuilt.append(duty)
            continue
        if duty.physical_vehicle_id in preserved_ids:
            _verify_prepared_ledger(duty, context)
            rebuilt.append(duty)
            continue
        reference_duty = reference_by_id.get(
            duty.physical_vehicle_id,
            duty,
        )
        try:
            repaired = (
                _repair_one_ev_duty(
                    reference_duty,
                    duty,
                    context=context,
                    policy=policy,
                )
                if cache is None
                else cache.repair(
                    reference_duty,
                    duty,
                    context=context,
                    policy=policy,
                )
            )
        except (TypeError, ValueError) as error:
            raise ChargingRepairFailure(
                duty.physical_vehicle_id,
                error,
            ) from error
        rebuilt.append(repaired)

    result = replace(candidate, duties=tuple(rebuilt))
    assert_locks_preserved(reference, result)
    return result


def repair_changed_duties_outcome(
    reference: DutyIndividual,
    candidate: DutyIndividual,
    *,
    changed_duty_ids: set[str],
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
    cache: ChargingRepairCache | None = None,
    preserve_explicit_charging_duty_ids: set[str] | None = None,
) -> ChargingRepairOutcome:
    """Return READY or a typed rejection for one candidate."""

    try:
        result = repair_changed_duties(
            reference,
            candidate,
            changed_duty_ids=changed_duty_ids,
            context=context,
            policy=policy,
            cache=cache,
            preserve_explicit_charging_duty_ids=(
                preserve_explicit_charging_duty_ids
            ),
        )
    except ChargingRepairFailure as error:
        return ChargingRepairOutcome(
            status=ChargingCandidateStatus.REJECTED_CHARGING,
            candidate=None,
            reason_code=charging_rejection_reason(error),
            affected_duty_ids=(error.duty_id,),
            error=error,
        )
    except (TypeError, ValueError) as error:
        return ChargingRepairOutcome(
            status=ChargingCandidateStatus.REJECTED_INTERFACE,
            candidate=None,
            reason_code=type(error).__name__,
            affected_duty_ids=tuple(sorted(changed_duty_ids)),
            error=error,
        )
    return ChargingRepairOutcome(
        status=ChargingCandidateStatus.READY,
        candidate=result,
        affected_duty_ids=tuple(sorted(changed_duty_ids)),
    )

def repair_changed_duties_candidates(
    reference: DutyIndividual,
    candidate: DutyIndividual,
    *,
    changed_duty_ids: set[str],
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
    stop_requested: Callable[[], bool] | None = None,
    failed_duty_id: str | None = None,
) -> Iterator[DutyIndividual]:
    """Yield existing charging alternatives when singular repair fails."""

    if context.dynamic_state is not None:
        return
    if policy.depot_charge_window_mode != context.depot_charge_window_mode:
        raise ValueError(
            "charging repair and full evaluation use different depot windows"
        )
    candidate_by_id = {
        duty.physical_vehicle_id: duty for duty in candidate.duties
    }
    reference_by_id = {
        duty.physical_vehicle_id: duty for duty in reference.duties
    }
    unknown = set(changed_duty_ids).difference(candidate_by_id)
    if unknown:
        raise ValueError(
            f"charging repair received unknown duties: {sorted(unknown)}"
        )
    ordered_ids = tuple(
        duty.physical_vehicle_id
        for duty in candidate.duties
        if duty.physical_vehicle_id in changed_duty_ids
    )
    if failed_duty_id is not None:
        if failed_duty_id not in ordered_ids:
            raise ValueError("failed charging duty is outside the changed scope")
        ordered_ids = (
            failed_duty_id,
            *(duty_id for duty_id in ordered_ids if duty_id != failed_duty_id),
        )

    ev_option_cache: dict[str, list[PhysicalVehicleDuty]] = {}
    ev_option_seen: dict[str, set[PhysicalVehicleDuty]] = {}
    ev_option_sources: dict[str, Iterator[PhysicalVehicleDuty]] = {}

    def raw_ev_options(duty_id: str) -> Iterator[PhysicalVehicleDuty]:
        duty = candidate_by_id[duty_id]
        reference_duty = reference_by_id.get(duty_id, duty)
        if duty_id != failed_duty_id:
            try:
                yield _repair_one_ev_duty(
                    reference_duty,
                    duty,
                    context=context,
                    policy=policy,
                )
            except (TypeError, ValueError):
                pass
        amount_strategies = tuple(
            dict.fromkeys(
                (
                    policy.charge_amount_strategy,
                    "just_enough",
                    "max_coverage",
                    *curve_knee_strategies(context.bundle.prices),
                    "full",
                )
            )
        )
        yield from _repair_one_ev_duty_candidates(
            reference_duty,
            duty,
            context=context,
            policy=policy,
            amount_strategies=amount_strategies,
            stop_requested=stop_requested,
        )

    def prepared_ev_options(
        duty_id: str,
    ) -> Iterator[PhysicalVehicleDuty]:
        cache = ev_option_cache.setdefault(duty_id, [])
        seen = ev_option_seen.setdefault(duty_id, set())
        for option in cache:
            yield option
        source = ev_option_sources.setdefault(
            duty_id,
            raw_ev_options(duty_id),
        )
        while stop_requested is None or not stop_requested():
            try:
                option = next(source)
            except StopIteration:
                return
            if option in seen:
                continue
            seen.add(option)
            cache.append(option)
            yield option

    def replace_duty(
        individual: DutyIndividual,
        repaired: PhysicalVehicleDuty,
    ) -> DutyIndividual:
        return replace(
            individual,
            duties=tuple(
                repaired
                if duty.physical_vehicle_id
                == repaired.physical_vehicle_id
                else duty
                for duty in individual.duties
            ),
        )

    def recurse(
        index: int,
        current: DutyIndividual,
    ) -> Iterator[DutyIndividual]:
        if stop_requested is not None and stop_requested():
            return
        if index == len(ordered_ids):
            assert_locks_preserved(reference, current)
            yield current
            return
        duty_id = ordered_ids[index]
        duty = next(
            duty
            for duty in current.duties
            if duty.physical_vehicle_id == duty_id
        )
        if duty.vehicle_type == "cv":
            if duty.charging_sessions:
                return
            yield from recurse(index + 1, current)
            return
        other_session_ends = _other_session_end_seconds_by_station(
            current,
            excluded_duty_id=duty_id,
        )
        seen: set[PhysicalVehicleDuty] = (
            {duty} if duty_id == failed_duty_id else set()
        )
        for repaired in prepared_ev_options(duty_id):
            for alternative in chain(
                (repaired,),
                _static_timing_variants(
                    repaired,
                    context=context,
                    stop_requested=stop_requested,
                    other_session_end_seconds_by_station=other_session_ends,
                ),
            ):
                if alternative in seen:
                    continue
                seen.add(alternative)
                yield from recurse(
                    index + 1,
                    replace_duty(current, alternative),
                )

    yield from recurse(0, candidate)


def build_ev_duty_charging_candidates(
    duty: PhysicalVehicleDuty,
    *,
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
    reference: PhysicalVehicleDuty | None = None,
    other_session_end_seconds_by_station: Mapping[
        str, tuple[float, ...]
    ] | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> Iterator[PhysicalVehicleDuty]:
    """Build exact whole-duty amount and timing alternatives for one EV."""

    if duty.vehicle_type != "ev" or not duty.trips:
        return
    reference_duty = duty if reference is None else reference
    amount_strategies = tuple(
        dict.fromkeys(
            (
                policy.charge_amount_strategy,
                "just_enough",
                "max_coverage",
                *curve_knee_strategies(context.bundle.prices),
                "full",
            )
        )
    )
    seen = {duty}
    for repaired in _repair_one_ev_duty_candidates(
        reference_duty,
        duty,
        context=context,
        policy=policy,
        amount_strategies=amount_strategies,
        stop_requested=stop_requested,
    ):
        if stop_requested is not None and stop_requested():
            return
        for candidate in chain(
            (repaired,),
            _static_timing_variants(
                repaired,
                context=context,
                stop_requested=stop_requested,
                other_session_end_seconds_by_station=(
                    other_session_end_seconds_by_station
                ),
            ),
        ):
            if candidate in seen:
                continue
            seen.add(candidate)
            yield candidate


def _other_session_end_seconds_by_station(
    individual: DutyIndividual,
    *,
    excluded_duty_id: str,
) -> dict[str, tuple[float, ...]]:
    ends: dict[str, list[float]] = {}
    for duty in individual.duties:
        if duty.physical_vehicle_id == excluded_duty_id:
            continue
        for session in duty.charging_sessions:
            if int(session.charge_day_offset) != 0:
                continue
            ends.setdefault(session.station_id, []).append(
                float(session.charge_start_second)
                + float(session.occupancy_minutes) * 60.0
            )
    return {
        station_id: tuple(sorted(set(values)))
        for station_id, values in ends.items()
    }


def build_dynamic_ev_duty_charging_candidates(
    duty: PhysicalVehicleDuty,
    *,
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> Iterator[PhysicalVehicleDuty]:
    """Expose public-station route, amount, and clock choices after a cut.

    The exact dynamic scheduler rebuilds any required depot charge from the
    inherited battery state.  This generator therefore carries only public
    station actions.  One future trip is changed at a time so the normal
    best-improvement loop can combine useful changes without constructing a
    cross-product of every trip and station choice.
    """

    if (
        context.dynamic_state is None
        or duty.vehicle_type != "ev"
        or not duty.trips
    ):
        return
    bundle = context.bundle
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    trigger = float(context.dynamic_state.cut.trigger_second)
    amount_strategies = tuple(
        dict.fromkeys(
            (
                policy.charge_amount_strategy,
                "just_enough",
                "max_coverage",
                *curve_knee_strategies(bundle.prices),
                "full",
            )
        )
    )
    seen = {duty}
    for trip in duty.trips:
        route_id = duty.route_id(trip.trip_index)
        route = Route(
            vehicle_id=route_id,
            vehicle_type="ev",
            home_depot_id=duty.home_depot_id,
            node_sequence=[
                duty.home_depot_id,
                *trip.effective_route_visits,
                duty.home_depot_id,
            ],
        )
        for amount_strategy in amount_strategies:
            try:
                candidates = repair_route_charging_candidates(
                    route,
                    bundle.instance,
                    bundle.time_profile,
                    bundle.prices,
                    strategy=policy.strategy,
                    carbon_weight=float(policy.carbon_weight),
                    depot_charge_window_mode="same_day_predeparture",
                    charge_timing_policy=policy.charge_timing_policy,
                    charge_amount_strategy=amount_strategy,
                    carbon_profiles_by_day_offset=(
                        policy.carbon_profiles_by_day_offset
                    ),
                    public_station_candidate_mode="parallel",
                )
            except (TypeError, ValueError):
                continue
            for _label, repaired_route, repaired_actions in candidates:
                public_actions = tuple(
                    action
                    for action in repaired_actions
                    if node_lookup[action.station_id].node_type.lower() == "f"
                )
                if not public_actions or any(
                    float(action.charge_start_second) < trigger - 1.0e-9
                    for action in public_actions
                ):
                    continue
                _assert_customer_order(
                    trip.customer_ids,
                    repaired_route,
                    node_lookup,
                )
                sessions = tuple(
                    session
                    for session in duty.charging_sessions
                    if session.trip_index != trip.trip_index
                ) + tuple(
                    DutyChargingSession(
                        trip_index=trip.trip_index,
                        station_id=action.station_id,
                        energy_kwh=float(action.energy_kwh),
                        occupancy_minutes=float(action.occupancy_minutes),
                        charge_start_second=float(action.charge_start_second),
                        charge_day_offset=int(action.charge_day_offset),
                        start_energy_kwh=action.start_energy_kwh,
                        end_energy_kwh=action.end_energy_kwh,
                        charging_curve_id=action.charging_curve_id,
                    )
                    for action in public_actions
                )
                rebuilt = replace(
                    duty,
                    trips=tuple(
                        replace(
                            item,
                            route_visits=tuple(
                                repaired_route.node_sequence[1:-1]
                            ),
                        )
                        if item.trip_index == trip.trip_index
                        else item
                        for item in duty.trips
                    ),
                    charging_sessions=sessions,
                )
                if rebuilt in seen:
                    continue
                seen.add(rebuilt)
                yield rebuilt


def _repair_one_ev_duty_candidates(
    reference: PhysicalVehicleDuty,
    duty: PhysicalVehicleDuty,
    *,
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
    amount_strategies: tuple[str, ...],
    stop_requested: Callable[[], bool] | None = None,
) -> Iterator[PhysicalVehicleDuty]:
    """Expose route/site/amount alternatives to the whole-duty evaluator."""

    if not duty.trips:
        return
    if policy.frvcpy_enabled:
        if stop_requested is not None and stop_requested():
            return
        try:
            yield _repair_one_ev_duty(
                reference,
                duty,
                context=context,
                policy=policy,
            )
        except (TypeError, ValueError):
            return
        return
    bundle = context.bundle
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    reference_sessions_by_trip: dict[int, list[DutyChargingSession]] = {}
    for session in reference.charging_sessions:
        reference_sessions_by_trip.setdefault(
            int(session.trip_index), []
        ).append(session)
    locked_trip_indices = reference.locked_charging_trip_indices
    for trip_index in locked_trip_indices:
        sessions = reference_sessions_by_trip.get(trip_index, [])
        if any(not session.locked for session in sessions):
            raise ValueError(
                "one trip cannot mix locked and unlocked charging sessions"
            )

    option_sources: list[
        Iterator[tuple[Route, tuple[ChargingAction, ...]]]
    ] = []

    def trip_options(
        trip: DutyTrip,
    ) -> Iterator[tuple[Route, tuple[ChargingAction, ...]]]:
        if stop_requested is not None and stop_requested():
            return
        temporary_id = duty.route_id(trip.trip_index)
        route = Route(
            vehicle_id=temporary_id,
            vehicle_type="ev",
            home_depot_id=duty.home_depot_id,
            node_sequence=[
                duty.home_depot_id,
                *trip.effective_route_visits,
                duty.home_depot_id,
            ],
        )
        if int(trip.trip_index) in locked_trip_indices:
            yield (
                route,
                tuple(
                    _session_to_action(session, temporary_id)
                    for session in reference_sessions_by_trip[trip.trip_index]
                ),
            )
            return

        seen_trip_options: list[
            tuple[Route, tuple[ChargingAction, ...]]
        ] = []
        for amount_strategy in amount_strategies:
            if stop_requested is not None and stop_requested():
                return
            for window_mode in _route_repair_window_modes(duty, trip, policy):
                try:
                    route_candidates = repair_route_charging_candidates(
                        route,
                        bundle.instance,
                        bundle.time_profile,
                        bundle.prices,
                        strategy=policy.strategy,
                        carbon_weight=float(policy.carbon_weight),
                        depot_charge_window_mode=window_mode,
                        charge_timing_policy=policy.charge_timing_policy,
                        charge_amount_strategy=amount_strategy,
                        carbon_profiles_by_day_offset=(
                            policy.carbon_profiles_by_day_offset
                        ),
                        public_station_candidate_mode=(
                            "fallback"
                            if policy.public_station_candidate_mode
                            == DYNAMIC_DEPOT_ONLY_CANDIDATE_MODE
                            else policy.public_station_candidate_mode
                        ),
                    )
                except (TypeError, ValueError):
                    continue
                for _label, repaired_route, repaired_actions in route_candidates:
                    if stop_requested is not None and stop_requested():
                        return
                    if (
                        policy.public_station_candidate_mode
                        == DYNAMIC_DEPOT_ONLY_CANDIDATE_MODE
                        and _uses_public_station(
                            repaired_route,
                            repaired_actions,
                            node_lookup,
                        )
                    ):
                        continue
                    _assert_customer_order(
                        trip.customer_ids,
                        repaired_route,
                        node_lookup,
                    )
                    normalized = (repaired_route, tuple(repaired_actions))
                    if normalized in seen_trip_options:
                        continue
                    seen_trip_options.append(normalized)
                    yield normalized

    for trip in duty.trips:
        option_sources.append(trip_options(trip))

    option_caches: list[
        list[tuple[Route, tuple[ChargingAction, ...]]]
    ] = [[] for _ in duty.trips]
    exhausted = [False for _ in duty.trips]

    def replayable_options(
        trip_position: int,
    ) -> Iterator[tuple[Route, tuple[ChargingAction, ...]]]:
        yield from option_caches[trip_position]
        if exhausted[trip_position]:
            return
        source = option_sources[trip_position]
        while True:
            try:
                option = next(source)
            except StopIteration:
                exhausted[trip_position] = True
                return
            option_caches[trip_position].append(option)
            yield option

    def combinations(
        trip_position: int,
        prefix: tuple[tuple[Route, tuple[ChargingAction, ...]], ...],
    ) -> Iterator[
        tuple[tuple[Route, tuple[ChargingAction, ...]], ...]
    ]:
        if trip_position == len(option_sources):
            yield prefix
            return
        for option in replayable_options(trip_position):
            yield from combinations(trip_position + 1, (*prefix, option))

    seen_duties: set[PhysicalVehicleDuty] = set()
    for combination in combinations(0, ()):
        if stop_requested is not None and stop_requested():
            return
        routes = [route for route, _ in combination]
        actions = [
            action
            for _, route_actions in combination
            for action in route_actions
        ]
        try:
            rebuilt = _rebuild_ev_duty(
                reference,
                duty,
                routes,
                actions,
                locked_trip_indices=locked_trip_indices,
                context=context,
                policy=policy,
            )
        except (TypeError, ValueError):
            continue
        if rebuilt in seen_duties:
            continue
        seen_duties.add(rebuilt)
        yield rebuilt


def _static_timing_variants(
    duty: PhysicalVehicleDuty,
    *,
    context: DutyEvaluationContext,
    other_session_end_seconds_by_station: Mapping[
        str, tuple[float, ...]
    ] | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> Iterator[PhysicalVehicleDuty]:
    """Expose only shared-charger release instants around the exact local best.

    The normal repair has already minimised electricity plus carbon cost over
    every exact tariff/carbon breakpoint for each fixed action. Re-evaluating
    those dominated clocks in the complete model only repeats the same
    additive objective. Other duties' release instants remain necessary
    because shared-charger occupancy is a system-level interaction.
    """

    if context.depot_charge_window_mode != "same_day_predeparture":
        return
    solution = DutyIndividual(
        duties=(duty,),
        source="charging-timing-candidates",
    ).to_solution()
    route_by_trip = {
        int(route.vehicle_id.rsplit("#T", 1)[1]): route
        for route in solution.routes
    }
    actions_by_trip: dict[int, list[ChargingAction]] = {}
    for action in solution.charging_actions:
        trip_index = int(action.vehicle_id.rsplit("#T", 1)[1])
        actions_by_trip.setdefault(trip_index, []).append(action)
    start_options: list[tuple[int, tuple[float, ...]]] = []
    previous_return: float | None = None
    for trip in duty.trips:
        if stop_requested is not None and stop_requested():
            return
        route = route_by_trip[trip.trip_index]
        route_actions = actions_by_trip.get(trip.trip_index, [])
        timing = route_timing(
            route,
            context.bundle.instance,
            context.bundle.prices,
            charging_actions=route_actions,
            validate_battery=False,
        )
        for session_index, session in enumerate(duty.charging_sessions):
            if (
                session.trip_index != trip.trip_index
                or session.locked
                or int(session.charge_day_offset) != 0
            ):
                continue
            external_starts = tuple(
                float(start)
                for start in (
                    other_session_end_seconds_by_station or {}
                ).get(session.station_id, ())
            )
            if not external_starts:
                continue
            if session.station_id != duty.home_depot_id:
                all_starts = tuple(
                    dict.fromkeys(
                        (
                            float(session.charge_start_second),
                            *external_starts,
                        )
                    )
                )
                if len(all_starts) > 1:
                    start_options.append((session_index, all_starts))
                continue
            action = _session_to_action(session, route.vehicle_id)
            duration = float(action.occupancy_minutes) * 60.0
            earliest = 0.0 if previous_return is None else previous_return
            latest = (
                float(
                    route_departure_second(
                        route,
                        context.bundle.instance,
                        context.bundle.prices,
                    )
                )
                - duration
            )
            all_starts = tuple(
                dict.fromkeys(
                    (
                        float(session.charge_start_second),
                        *(
                            float(start)
                            for start in external_starts
                            if earliest - 1e-9
                            <= float(start)
                            <= latest + 1e-9
                        ),
                    )
                )
            )
            start_options.append((session_index, all_starts))
        previous_return = float(timing.return_second)
    if not start_options:
        return

    for candidate in _coordinate_timing_variants(duty, tuple(start_options)):
        if stop_requested is not None and stop_requested():
            return
        try:
            _verify_prepared_ledger(candidate, context)
        except (TypeError, ValueError):
            continue
        yield candidate


def _coordinate_timing_variants(
    duty: PhysicalVehicleDuty,
    start_options: tuple[tuple[int, tuple[float, ...]], ...],
) -> Iterator[PhysicalVehicleDuty]:
    """Change exactly one legal charging clock in each serial candidate."""

    for session_index, starts in start_options:
        original = float(
            duty.charging_sessions[session_index].charge_start_second
        )
        for start in starts:
            selected = float(start)
            if selected == original:
                continue
            sessions = list(duty.charging_sessions)
            sessions[session_index] = replace(
                sessions[session_index],
                charge_start_second=selected,
            )
            yield replace(duty, charging_sessions=tuple(sessions))


def _repair_one_ev_duty(
    reference: PhysicalVehicleDuty,
    duty: PhysicalVehicleDuty,
    *,
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> PhysicalVehicleDuty:
    if not duty.trips:
        if duty.charging_sessions:
            raise ValueError("an idle EV duty cannot retain charging sessions")
        return duty
    if policy.frvcpy_enabled:
        return _repair_one_ev_duty_with_frvcpy(
            reference,
            duty,
            context=context,
            policy=policy,
        )

    bundle = context.bundle
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    reference_sessions_by_trip: dict[int, list[DutyChargingSession]] = {}
    for session in reference.charging_sessions:
        reference_sessions_by_trip.setdefault(
            int(session.trip_index), []
        ).append(session)
    locked_trip_indices = reference.locked_charging_trip_indices
    for trip_index in locked_trip_indices:
        sessions = reference_sessions_by_trip.get(trip_index, [])
        if any(not session.locked for session in sessions):
            raise ValueError(
                "one trip cannot mix locked and unlocked charging sessions"
            )

    routes: list[Route] = []
    actions: list[ChargingAction] = []
    # The single-route repair builds a provisional, same-day local action.
    # The physical-duty certificate below places and re-times that action in
    # the approved first-trip or inter-trip calendar window.
    for trip in duty.trips:
        temporary_id = duty.route_id(trip.trip_index)
        route = Route(
            vehicle_id=temporary_id,
            vehicle_type="ev",
            home_depot_id=duty.home_depot_id,
            node_sequence=[
                duty.home_depot_id,
                *trip.effective_route_visits,
                duty.home_depot_id,
            ],
        )
        if int(trip.trip_index) in locked_trip_indices:
            routes.append(route)
            actions.extend(
                _session_to_action(session, temporary_id)
                for session in reference_sessions_by_trip[trip.trip_index]
            )
            continue
        repair_error: TypeError | ValueError | None = None
        for window_mode in _route_repair_window_modes(duty, trip, policy):
            try:
                repaired_route, repaired_actions = repair_route_charging(
                    route,
                    bundle.instance,
                    bundle.time_profile,
                    bundle.prices,
                    strategy=policy.strategy,
                    carbon_weight=float(policy.carbon_weight),
                    depot_charge_window_mode=window_mode,
                    charge_timing_policy=policy.charge_timing_policy,
                    charge_amount_strategy=policy.charge_amount_strategy,
                    carbon_profiles_by_day_offset=(
                        policy.carbon_profiles_by_day_offset
                    ),
                    public_station_candidate_mode=(
                        "fallback"
                        if policy.public_station_candidate_mode
                        == DYNAMIC_DEPOT_ONLY_CANDIDATE_MODE
                        else policy.public_station_candidate_mode
                    ),
                )
            except (TypeError, ValueError) as exc:
                repair_error = exc
                continue
            break
        else:
            if repair_error is None:
                raise AssertionError("charging repair had no registered window mode")
            raise repair_error
        if (
            policy.public_station_candidate_mode
            == DYNAMIC_DEPOT_ONLY_CANDIDATE_MODE
            and _uses_public_station(
                repaired_route,
                repaired_actions,
                node_lookup,
            )
        ):
            raise ValueError(
                "dynamic depot-only charging cannot use a public station"
            )
        _assert_customer_order(
            trip.customer_ids,
            repaired_route,
            node_lookup,
        )
        routes.append(repaired_route)
        actions.extend(repaired_actions)

    return _rebuild_ev_duty(
        reference,
        duty,
        routes,
        actions,
        locked_trip_indices=locked_trip_indices,
        context=context,
        policy=policy,
    )


def _repair_one_ev_duty_with_frvcpy(
    reference: PhysicalVehicleDuty,
    duty: PhysicalVehicleDuty,
    *,
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> PhysicalVehicleDuty:
    """Use frvcpy for sites/amounts and existing code for charging clocks."""

    bundle = context.bundle
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    reference_sessions_by_trip: dict[int, list[DutyChargingSession]] = {}
    for session in reference.charging_sessions:
        reference_sessions_by_trip.setdefault(
            int(session.trip_index), []
        ).append(session)
    locked_trip_indices = reference.locked_charging_trip_indices
    for trip_index in locked_trip_indices:
        sessions = reference_sessions_by_trip.get(trip_index, [])
        if any(not session.locked for session in sessions):
            raise ValueError(
                "one trip cannot mix locked and unlocked charging sessions"
            )

    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for trip in duty.trips:
        temporary_id = duty.route_id(trip.trip_index)
        route = Route(
            vehicle_id=temporary_id,
            vehicle_type="ev",
            home_depot_id=duty.home_depot_id,
            node_sequence=[
                duty.home_depot_id,
                *trip.effective_route_visits,
                duty.home_depot_id,
            ],
        )
        if int(trip.trip_index) in locked_trip_indices:
            routes.append(route)
            actions.extend(
                _session_to_action(session, temporary_id)
                for session in reference_sessions_by_trip[trip.trip_index]
            )
            continue
        plan = solve_fixed_route_charging(
            route,
            bundle.instance,
            bundle.prices,
            initial_energy_kwh=float(
                bundle.prices.initial_ev_battery_kwh
            ),
        )
        if (
            policy.public_station_candidate_mode
            == DYNAMIC_DEPOT_ONLY_CANDIDATE_MODE
            and any(
                decision.node_type == "f"
                for decision in plan.charging_decisions
            )
        ):
            raise ValueError(
                "dynamic depot-only charging cannot use a public station"
            )
        _assert_customer_order(
            trip.customer_ids,
            plan.route,
            node_lookup,
        )
        route_actions = _place_frvcpy_charging_actions(
            plan.route,
            plan.charging_decisions,
            context=context,
            policy=policy,
        )
        routes.append(plan.route)
        actions.extend(route_actions)

    return _rebuild_ev_duty(
        reference,
        duty,
        routes,
        actions,
        locked_trip_indices=locked_trip_indices,
        context=context,
        policy=policy,
    )


def _place_frvcpy_charging_actions(
    route: Route,
    decisions,
    *,
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> list[ChargingAction]:
    """Place fixed frvcpy amounts with the registered project timing policy."""

    instance = context.bundle.instance
    prices = context.bundle.prices
    node_lookup = instance.node_lookup
    actions: list[ChargingAction] = []
    public_by_station: dict[str, ChargingAction] = {}
    depot_action: ChargingAction | None = None
    for decision in decisions:
        station = node_lookup[decision.station_id]
        power = (
            float(prices.depot_charge_power_kw)
            if decision.node_type == "d"
            else float(station.charge_power_kw)
            if station.charge_power_kw is not None
            else None
        )
        if power is None:
            raise ValueError(
                f"public station {station.node_id!r} has no registered power"
            )
        action = _curve_aware_action(
            vehicle_id=route.vehicle_id,
            station_id=decision.station_id,
            start_energy_kwh=float(decision.start_energy_kwh),
            energy_kwh=float(decision.energy_kwh),
            reference_power_kw=power,
            prices=prices,
            instance=instance,
        )
        if decision.node_type == "d":
            if depot_action is not None:
                raise ValueError("frvcpy returned multiple depot charges")
            depot_action = action
        else:
            if decision.station_id in public_by_station:
                raise ValueError("frvcpy repeated a public station")
            public_by_station[decision.station_id] = action

    base_timing = route_timing(
        route,
        instance,
        prices,
        charging_actions=[],
        validate_battery=False,
    )
    sequence = route.node_sequence
    latest_event_start = [0.0 for _ in sequence]
    latest = float(node_lookup[sequence[-1]].due_time)
    latest_event_start[-1] = latest
    for index in range(len(sequence) - 2, -1, -1):
        node_id = sequence[index]
        next_id = sequence[index + 1]
        _, travel, _ = instance.arc_metrics(
            node_id,
            next_id,
            "ev",
            fallback_speed_mps=float(prices.v_speed_ms),
        )
        public = public_by_station.get(node_id)
        processing = (
            float(public.occupancy_minutes) * 60.0
            if public is not None
            else float(node_lookup[node_id].service_time)
        )
        latest = min(
            float(node_lookup[node_id].due_time),
            latest - processing - float(travel),
        )
        latest_event_start[index] = latest

    origin = node_lookup[sequence[0]]
    latest_departure = latest_event_start[0] + float(origin.service_time)
    departure = min(
        float(base_timing.earliest_departure_second),
        latest_departure,
    )
    earliest_departure = float(origin.ready_time) + float(origin.service_time)
    if departure < earliest_departure - 1.0e-7:
        raise ValueError("frvcpy route has no time-feasible charging schedule")

    if depot_action is not None:
        duration = float(depot_action.occupancy_minutes) * 60.0
        start = departure - duration
        if start < -1.0e-7:
            raise ValueError("frvcpy depot charge does not fit before departure")
        depot_action = replace(
            depot_action,
            charge_start_second=max(0.0, start),
        )
        actions.append(depot_action)

    current_departure = departure
    for index, (from_id, to_id) in enumerate(
        zip(sequence, sequence[1:]),
        start=1,
    ):
        _, travel, _ = instance.arc_metrics(
            from_id,
            to_id,
            "ev",
            fallback_speed_mps=float(prices.v_speed_ms),
        )
        node = node_lookup[to_id]
        arrival = current_departure + float(travel)
        event_start = max(arrival, float(node.ready_time))
        public = public_by_station.get(to_id)
        if public is None:
            current_departure = event_start + float(node.service_time)
            continue
        latest_start = latest_event_start[index]
        if latest_start < event_start - 1.0e-7:
            raise ValueError("frvcpy public charge does not fit customer windows")
        profile = (
            context.bundle.time_profile
            if policy.carbon_profiles_by_day_offset is None
            else policy.carbon_profiles_by_day_offset[0]
        )
        profile = time_profile_rows_for_node(instance, to_id, profile)
        selected = select_charge_timing_start(
            public,
            earliest_start_second=event_start,
            latest_start_second=latest_start,
            instance=instance,
            carbon_profile=profile,
            prices=prices,
            charge_timing_policy=policy.charge_timing_policy,
        )
        public = replace(public, charge_start_second=float(selected))
        actions.append(public)
        current_departure = (
            float(selected) + float(public.occupancy_minutes) * 60.0
        )

    route_timing(
        route,
        instance,
        prices,
        charging_actions=actions,
        validate_battery=False,
    )
    return actions


def _uses_public_station(
    route: Route,
    actions: tuple[ChargingAction, ...] | list[ChargingAction],
    node_lookup,
) -> bool:
    return any(
        node_lookup[node_id].node_type.lower() == "f"
        for node_id in route.node_sequence
    ) or any(action.station_id != route.home_depot_id for action in actions)


def _rebuild_ev_duty(
    reference: PhysicalVehicleDuty,
    duty: PhysicalVehicleDuty,
    routes: list[Route],
    actions: list[ChargingAction],
    *,
    locked_trip_indices: frozenset[int],
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> PhysicalVehicleDuty:
    """Close one route-option combination on the exact whole-day ledger."""

    bundle = context.bundle
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    anchored = _anchor_duty_depot_actions(
        routes,
        actions,
        locked_trip_indices=locked_trip_indices,
        context=context,
        policy=policy,
    )
    prepared, _certificate = prepare_multitrip_solution(
        Solution(routes=routes, charging_actions=anchored),
        bundle.instance,
        bundle.prices,
        depot_charge_window_mode=policy.depot_charge_window_mode,
    )
    physical_ids = {
        physical_vehicle_id(route.vehicle_id) for route in prepared.routes
    }
    if len(physical_ids) != 1:
        raise ValueError(
            "one Duty was split across physical vehicles during charging repair"
        )
    prepared_routes = sorted(
        prepared.routes,
        key=lambda route: int(route.vehicle_id.rsplit("#T", 1)[1]),
    )
    if len(prepared_routes) != len(duty.trips):
        raise ValueError("charging repair changed the number of duty trips")
    rebuilt_trips: list[DutyTrip] = []
    for expected, route in zip(duty.trips, prepared_routes, strict=True):
        trip_index = int(route.vehicle_id.rsplit("#T", 1)[1])
        if trip_index != int(expected.trip_index):
            raise ValueError("charging repair reordered the duty trip chain")
        customers = tuple(
            node_id
            for node_id in route.node_sequence[1:-1]
            if node_lookup[node_id].node_type.lower() == "c"
        )
        if customers != expected.customer_ids:
            raise ValueError("charging repair changed customer order")
        rebuilt_trips.append(
            DutyTrip(
                trip_index=trip_index,
                customer_ids=customers,
                locked_customer_prefix=expected.locked_customer_prefix,
                route_visits=tuple(route.node_sequence[1:-1]),
            )
        )

    rebuilt_sessions = tuple(
        sorted(
            (
                _action_to_session(action, reference)
                for action in prepared.charging_actions
            ),
            key=lambda session: (
                session.trip_index,
                session.station_id,
                session.charge_start_second,
                session.energy_kwh,
            ),
        )
    )
    _assert_locked_sessions_exact(reference, rebuilt_sessions)
    rebuilt = replace(
        duty,
        trips=tuple(rebuilt_trips),
        charging_sessions=rebuilt_sessions,
    )
    _verify_prepared_ledger(rebuilt, context)
    return rebuilt


def _anchor_duty_depot_actions(
    routes: list[Route],
    actions: list[ChargingAction],
    *,
    locked_trip_indices: frozenset[int],
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> list[ChargingAction]:
    """Rebase provisional route actions onto one continuous vehicle ledger."""

    instance = context.bundle.instance
    prices = context.bundle.prices
    inherited = float(prices.initial_ev_battery_kwh)
    ordered_routes = sorted(
        routes,
        key=lambda route: int(route.vehicle_id.rsplit("#T", 1)[1]),
    )
    by_route: dict[str, list[ChargingAction]] = {
        route.vehicle_id: [
            action
            for action in actions
            if action.vehicle_id == route.vehicle_id
        ]
        for route in ordered_routes
    }
    anchored: list[ChargingAction] = []
    previous_end = inherited
    previous_return: float | None = None

    for position, route in enumerate(ordered_routes):
        trip_index = int(route.vehicle_id.rsplit("#T", 1)[1])
        route_actions = by_route[route.vehicle_id]
        depot_actions = [
            action
            for action in route_actions
            if action.station_id == route.home_depot_id
        ]
        public_actions = [
            action
            for action in route_actions
            if action.station_id != route.home_depot_id
        ]
        if len(depot_actions) > 1:
            raise ValueError("one duty trip has multiple depot charge actions")

        timing = route_timing(
            route,
            instance,
            prices,
            charging_actions=route_actions,
            validate_battery=False,
        )
        depot_action = depot_actions[0] if depot_actions else None
        if trip_index in locked_trip_indices:
            selected_depot = depot_action
            departure_energy = previous_end + sum(
                float(action.energy_kwh) for action in depot_actions
            )
        else:
            provisional_target = previous_end
            if depot_action is not None:
                provisional_target = float(
                    depot_action.end_energy_kwh
                    if depot_action.end_energy_kwh is not None
                    else inherited + float(depot_action.energy_kwh)
                )
            required_departure = timing.required_departure_battery_kwh
            if required_departure is not None:
                if previous_end > float(required_departure) + 1e-7:
                    raise ValueError(
                        "continuous duty energy exceeds the fixed public-charge "
                        "departure state"
                    )
                target = float(required_departure)
            else:
                minimum = max(
                    0.0,
                    float(timing.drive_energy_kwh)
                    - sum(float(action.energy_kwh) for action in public_actions),
                )
                target = max(previous_end, provisional_target, minimum)
            energy = max(0.0, target - previous_end)
            selected_depot = None
            if energy > 1e-9:
                selected_depot = _curve_aware_action(
                    vehicle_id=route.vehicle_id,
                    station_id=route.home_depot_id,
                    start_energy_kwh=previous_end,
                    energy_kwh=energy,
                    reference_power_kw=float(prices.depot_charge_power_kw),
                    prices=prices,
                    instance=instance,
                )
                duration = float(selected_depot.occupancy_minutes) * 60.0
                if position == 0 and policy.first_trip_prev_night_enabled:
                    windows: list[tuple[str, float, float]] = []
                    for mode in ("same_day_predeparture", "prev_night"):
                        local_earliest, local_latest, day_offset = (
                            certified_depot_charge_window(
                                route,
                                instance,
                                prices,
                                occupancy_seconds=duration,
                                mode=mode,
                                charging_actions=route_actions,
                            )
                        )
                        day_start = (
                            float(day_offset) * STATIC_PREHORIZON_SECONDS
                        )
                        windows.append(
                            (
                                mode,
                                day_start + float(local_earliest),
                                day_start + float(local_latest),
                            )
                        )
                    start, offset = _select_depot_charge_start_from_windows(
                        selected_depot,
                        tuple(windows),
                        context=context,
                        policy=policy,
                    )
                elif position == 0:
                    if policy.depot_charge_window_mode == "same_day_predeparture":
                        earliest = 0.0
                        latest = (
                            float(route_departure_second(route, instance, prices))
                            - duration
                        )
                        mode = "same_day_predeparture"
                    else:
                        earliest = -STATIC_PREHORIZON_SECONDS
                        latest = -duration
                        mode = "prev_night"
                else:
                    if previous_return is None:
                        raise AssertionError("missing preceding trip return")
                    earliest = previous_return
                    latest = (
                        float(route_departure_second(route, instance, prices))
                        - duration
                    )
                    mode = "full_gap"
                if not (
                    position == 0 and policy.first_trip_prev_night_enabled
                ):
                    start, offset = select_certified_depot_charge_start(
                        selected_depot,
                        earliest,
                        latest,
                        instance,
                        prices,
                        context.bundle.time_profile,
                        mode=mode,
                        strategy=policy.strategy,
                        carbon_weight=float(policy.carbon_weight),
                        charge_timing_policy=policy.charge_timing_policy,
                        carbon_profiles_by_day_offset=(
                            policy.carbon_profiles_by_day_offset
                        ),
                    )
                selected_depot = replace(
                    selected_depot,
                    charge_start_second=float(start),
                    charge_day_offset=int(offset),
                )
            departure_energy = previous_end + energy

        if selected_depot is not None:
            anchored.append(selected_depot)
        anchored.extend(public_actions)
        previous_end = (
            departure_energy
            + sum(float(action.energy_kwh) for action in public_actions)
            - float(timing.drive_energy_kwh)
        )
        if previous_end < -1e-7:
            raise ValueError("continuous duty battery falls below zero")
        previous_return = float(timing.return_second)

    return anchored


def _verify_prepared_ledger(
    duty: PhysicalVehicleDuty,
    context: DutyEvaluationContext,
) -> None:
    solution = DutyIndividual(duties=(duty,), source="charging-ledger-check").to_solution()
    repeated, _ = prepare_multitrip_solution(
        solution,
        context.bundle.instance,
        context.bundle.prices,
        depot_charge_window_mode=context.depot_charge_window_mode,
    )
    if repeated != solution:
        raise ValueError("charging repair did not close under full ledger replay")


def _assert_customer_order(
    expected: tuple[str, ...],
    route: Route,
    node_lookup: Mapping[str, Any],
) -> None:
    actual = tuple(
        node_id
        for node_id in route.node_sequence
        if node_lookup[node_id].node_type.lower() == "c"
    )
    if actual != expected:
        raise ValueError("route charging repair changed customer order")


def _session_to_action(
    session: DutyChargingSession,
    vehicle_id: str,
) -> ChargingAction:
    return ChargingAction(
        vehicle_id=vehicle_id,
        station_id=session.station_id,
        energy_kwh=float(session.energy_kwh),
        occupancy_minutes=float(session.occupancy_minutes),
        charge_start_second=float(session.charge_start_second),
        charge_day_offset=int(session.charge_day_offset),
        start_energy_kwh=session.start_energy_kwh,
        end_energy_kwh=session.end_energy_kwh,
        charging_curve_id=session.charging_curve_id,
    )


def _action_to_session(
    action: ChargingAction,
    reference: PhysicalVehicleDuty,
) -> DutyChargingSession:
    trip_index = int(action.vehicle_id.rsplit("#T", 1)[1])
    key = _action_value_key(action, trip_index)
    locked = any(
        session.locked and _session_value_key(session) == key
        for session in reference.charging_sessions
    )
    return DutyChargingSession(
        trip_index=trip_index,
        station_id=action.station_id,
        energy_kwh=float(action.energy_kwh),
        occupancy_minutes=float(action.occupancy_minutes),
        charge_start_second=float(action.charge_start_second),
        charge_day_offset=int(action.charge_day_offset),
        start_energy_kwh=action.start_energy_kwh,
        end_energy_kwh=action.end_energy_kwh,
        charging_curve_id=action.charging_curve_id,
        locked=locked,
    )


def _assert_locked_sessions_exact(
    reference: PhysicalVehicleDuty,
    rebuilt: tuple[DutyChargingSession, ...],
) -> None:
    expected = {
        _session_value_key(session)
        for session in reference.charging_sessions
        if session.locked
    }
    actual = {
        _session_value_key(session)
        for session in rebuilt
        if session.locked
    }
    if actual != expected:
        raise ValueError("charging repair changed a locked charging session")


def _session_value_key(session: DutyChargingSession) -> tuple[object, ...]:
    return (
        int(session.trip_index),
        session.station_id,
        float(session.energy_kwh),
        float(session.occupancy_minutes),
        float(session.charge_start_second),
        int(session.charge_day_offset),
        session.start_energy_kwh,
        session.end_energy_kwh,
        session.charging_curve_id,
    )


def _action_value_key(
    action: ChargingAction,
    trip_index: int,
) -> tuple[object, ...]:
    return (
        int(trip_index),
        action.station_id,
        float(action.energy_kwh),
        float(action.occupancy_minutes),
        float(action.charge_start_second),
        int(action.charge_day_offset),
        action.start_energy_kwh,
        action.end_energy_kwh,
        action.charging_curve_id,
    )
