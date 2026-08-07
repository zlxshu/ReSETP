"""System-level proposal streams for Duty-HGS.

The complete model remains the only acceptance authority.  Proposal engines
only decide the order in which reversible Duty moves are presented.  Multiple
problem channels are interleaved without a candidate-count cutoff, so no
mechanism is silently removed by a route-only proxy.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from setp_solver.instance_loader import Instance

from .evaluation import DutyEvaluationContext, FullEvaluation
from .charging import (
    ChargingRepairPolicy,
    build_ev_duty_charging_candidates,
)
from .model import DutyIndividual
from .operators import (
    ChargingScheduleMove,
    DutyMove,
    WholeDutyTypeExchangeMove,
    WholeTripExchangeMove,
    generate_problem_moves,
)


class DutyProposalEngine(Protocol):
    """Produce ordered Duty moves without accepting any of them."""

    source_id: str
    identity_sha256: str

    def propose(
        self,
        individual: DutyIndividual,
        evaluation: FullEvaluation,
        instance: Instance,
        *,
        include_whole_duty_type_exchange: bool,
    ) -> Iterable[DutyMove]: ...


@dataclass(frozen=True)
class LegacyCompleteProposalEngine:
    """Compatibility engine for the original exhaustive neighbourhood."""

    source_id: str = "duty-hgs-legacy-complete-neighbourhood-v1"

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.source_id.encode("utf-8")).hexdigest()

    def propose(
        self,
        individual: DutyIndividual,
        evaluation: FullEvaluation,
        instance: Instance,
        *,
        include_whole_duty_type_exchange: bool,
    ) -> Iterable[DutyMove]:
        return generate_problem_moves(
            individual,
            evaluation,
            instance,
            include_whole_duty_type_exchange=(
                include_whole_duty_type_exchange
            ),
        )


@dataclass(frozen=True)
class MechanismProposalEngine:
    """Generate only actions that carry private-problem model information."""

    context: DutyEvaluationContext
    charging_policy: ChargingRepairPolicy
    source_id: str = "duty-hgs-problem-mechanism-actions-v1"

    @property
    def identity_sha256(self) -> str:
        payload = (
            self.source_id
            + "\n"
            + self.context.bundle.instance_id
            + "\n"
            + repr(self.charging_policy)
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def propose(
        self,
        individual: DutyIndividual,
        evaluation: FullEvaluation,
        instance: Instance,
        *,
        include_whole_duty_type_exchange: bool,
    ) -> Iterable[DutyMove]:
        del evaluation, instance
        duties = tuple(individual.duties)
        if include_whole_duty_type_exchange:
            for left_index, left in enumerate(duties):
                for right in duties[left_index + 1 :]:
                    if left.home_depot_id != right.home_depot_id:
                        continue
                    if {left.vehicle_type, right.vehicle_type} != {"ev", "cv"}:
                        continue
                    if _duty_locked(left) or _duty_locked(right):
                        continue
                    if _task_chain(left) == _task_chain(right):
                        continue
                    yield WholeDutyTypeExchangeMove(
                        action_id=(
                            "whole-duty-type-exchange:"
                            f"{left.physical_vehicle_id}<->"
                            f"{right.physical_vehicle_id}"
                        ),
                        channel="whole_duty_type_exchange",
                        left_duty_id=left.physical_vehicle_id,
                        right_duty_id=right.physical_vehicle_id,
                    )

        for duty in duties:
            if (
                duty.vehicle_type == "ev"
                and self.context.dynamic_state is None
            ):
                for candidate in build_ev_duty_charging_candidates(
                    duty,
                    context=self.context,
                    policy=self.charging_policy,
                ):
                    payload = repr(
                        (
                            candidate.charging_sessions,
                            tuple(
                                trip.effective_route_visits
                                for trip in candidate.trips
                            ),
                        )
                    )
                    yield ChargingScheduleMove(
                        action_id=(
                            f"charge-search:{duty.physical_vehicle_id}:"
                            + hashlib.sha256(
                                payload.encode("utf-8")
                            ).hexdigest()[:16]
                        ),
                        channel="time_varying_carbon_charge",
                        duty_id=duty.physical_vehicle_id,
                        charging_sessions=candidate.charging_sessions,
                        route_visits_by_trip=tuple(
                            (
                                trip.trip_index,
                                trip.effective_route_visits,
                            )
                            for trip in candidate.trips
                        ),
                    )

        for left_index, left in enumerate(duties):
            for right in duties[left_index + 1 :]:
                if left.home_depot_id == right.home_depot_id:
                    continue
                for left_trip in left.trips:
                    if not _trip_fully_unlocked(left, left_trip.trip_index):
                        continue
                    for right_trip in right.trips:
                        if not _trip_fully_unlocked(
                            right,
                            right_trip.trip_index,
                        ):
                            continue
                        if left_trip.customer_ids == right_trip.customer_ids:
                            continue
                        yield WholeTripExchangeMove(
                            action_id=(
                                "whole-trip-exchange:"
                                f"{left.physical_vehicle_id}#T"
                                f"{left_trip.trip_index}<->"
                                f"{right.physical_vehicle_id}#T"
                                f"{right_trip.trip_index}"
                            ),
                            channel="depot_collaboration",
                            left_duty_id=left.physical_vehicle_id,
                            left_trip_index=left_trip.trip_index,
                            right_duty_id=right.physical_vehicle_id,
                            right_trip_index=right_trip.trip_index,
                        )


@dataclass(frozen=True)
class ExactDynamicSuffixProposalEngine:
    """Keep certified execution history fixed and search only future Duty."""

    context: DutyEvaluationContext
    source_id: str = "duty-hgs-exact-dynamic-future-neighbourhood-v1"

    def __post_init__(self) -> None:
        if self.context.dynamic_state is None:
            raise ValueError("dynamic suffix proposals require a dynamic state")

    @property
    def identity_sha256(self) -> str:
        state = self.context.dynamic_state
        payload = (
            self.source_id,
            self.context.bundle.instance_id,
            float(state.cut.trigger_second),
            tuple(sorted(state.future_customer_ids)),
        )
        return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()

    def propose(
        self,
        individual: DutyIndividual,
        evaluation: FullEvaluation,
        instance: Instance,
        *,
        include_whole_duty_type_exchange: bool,
    ) -> Iterable[DutyMove]:
        return generate_problem_moves(
            individual,
            evaluation,
            instance,
            include_whole_duty_type_exchange=(
                include_whole_duty_type_exchange
            ),
        )


@dataclass(frozen=True)
class InterleavedProposalEngine:
    """Interleave independent route/mechanism streams one action at a time."""

    providers: tuple[DutyProposalEngine, ...]
    source_id: str = "duty-hgs-interleaved-system-proposals-v1"

    def __post_init__(self) -> None:
        if not self.providers:
            raise ValueError("interleaved proposal engine needs a provider")

    @property
    def identity_sha256(self) -> str:
        payload = "\n".join(
            (
                self.source_id,
                *(provider.source_id for provider in self.providers),
                *(provider.identity_sha256 for provider in self.providers),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def propose(
        self,
        individual: DutyIndividual,
        evaluation: FullEvaluation,
        instance: Instance,
        *,
        include_whole_duty_type_exchange: bool,
    ) -> Iterable[DutyMove]:
        streams = tuple(
            iter(
                provider.propose(
                    individual,
                    evaluation,
                    instance,
                    include_whole_duty_type_exchange=(
                        include_whole_duty_type_exchange
                    ),
                )
            )
            for provider in self.providers
        )
        return _round_robin_unique(streams)


def _round_robin_unique(
    streams: tuple[Iterator[DutyMove], ...],
) -> Iterator[DutyMove]:
    """Yield one move per live stream, preserving every unique action."""

    active = list(streams)
    seen: set[str] = set()
    while active:
        next_active: list[Iterator[DutyMove]] = []
        for stream in active:
            try:
                move = next(stream)
            except StopIteration:
                continue
            next_active.append(stream)
            if move.action_id in seen:
                continue
            seen.add(move.action_id)
            yield move
        active = next_active


def _task_chain(duty) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(trip.customer_ids) for trip in duty.trips)


def _duty_locked(duty) -> bool:
    return bool(
        duty.has_dynamic_commitment
        or any(trip.locked_customer_prefix for trip in duty.trips)
        or any(session.locked for session in duty.charging_sessions)
    )


def _trip_fully_unlocked(duty, trip_index: int) -> bool:
    trip = next(
        item for item in duty.trips if item.trip_index == trip_index
    )
    return bool(
        not trip.locked_customer_prefix
        and trip.trip_index not in duty.locked_charging_trip_indices
    )
