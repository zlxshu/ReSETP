"""System-level proposal streams for Problem-HGS.

The complete model remains the only acceptance authority. Proposal engines
only decide the order in which reversible Duty moves are presented. The
active algorithm uses one serial stream: route proposals first, then private
problem proposals.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from setp_solver.instance_loader import Instance

from .charging import (
    ChargingRepairPolicy,
    build_dynamic_ev_duty_charging_candidates,
    build_ev_duty_charging_candidates,
)
from .evaluation import DutyEvaluationContext, FullEvaluation
from .model import DutyIndividual
from .operators import (
    ChargingScheduleMove,
    DutyMove,
    WholeDutyTypeExchangeMove,
    WholeTripExchangeMove,
    generate_problem_moves,
)


DEFAULT_SERIAL_PROPOSAL_SOURCE_ID = (
    "integrated-private-serial-complete-duty-neighbourhood-v1"
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

    source_id: str = "problem-hgs-legacy-complete-neighbourhood-v1"

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
    include_charging_candidates: bool = True
    include_non_charging_candidates: bool = True
    include_structural_channels: bool = False
    cross_depot_enabled: bool = True
    multi_trip_enabled: bool = True
    type_exchange_enabled: bool = True
    source_id: str = "problem-hgs-problem-mechanism-actions-v1"

    @property
    def identity_sha256(self) -> str:
        payload = (
            self.source_id
            + "\n"
            + self.context.bundle.instance_id
            + "\n"
            + repr(self.charging_policy)
            + "\n"
            + repr(self.include_charging_candidates)
            + "\n"
            + repr(self.include_non_charging_candidates)
        )
        if self.include_structural_channels:
            payload += "\nstructural_channels=depot,fairness,multi_trip"
        disabled = tuple(
            name
            for name, enabled in (
                ("cross_depot", self.cross_depot_enabled),
                ("multi_trip", self.multi_trip_enabled),
                ("type_exchange", self.type_exchange_enabled),
            )
            if not enabled
        )
        if disabled:
            payload += "\nmechanism_off=" + ",".join(disabled)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def propose(
        self,
        individual: DutyIndividual,
        evaluation: FullEvaluation,
        instance: Instance,
        *,
        include_whole_duty_type_exchange: bool,
    ) -> Iterable[DutyMove]:
        duties = tuple(individual.duties)
        if (
            self.include_non_charging_candidates
            and self.include_structural_channels
        ):
            structural_channels = set()
            if self.cross_depot_enabled:
                structural_channels.update(
                    {"depot_collaboration", "fairness_cross_depot"}
                )
            if self.multi_trip_enabled:
                structural_channels.add("multi_trip")
            for move in generate_problem_moves(
                individual,
                evaluation,
                instance,
                include_whole_duty_type_exchange=False,
            ):
                if move.channel in structural_channels:
                    yield move

        if (
            self.include_non_charging_candidates
            and include_whole_duty_type_exchange
            and self.type_exchange_enabled
        ):
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
            if duty.vehicle_type == "ev" and self.include_charging_candidates:
                if self.context.dynamic_state is None:
                    charging_candidates = build_ev_duty_charging_candidates(
                        duty,
                        context=self.context,
                        policy=self.charging_policy,
                        other_session_end_seconds_by_station=(
                            _other_session_end_seconds_by_station(
                                individual,
                                excluded_duty_id=duty.physical_vehicle_id,
                            )
                        ),
                    )
                else:
                    charging_candidates = (
                        build_dynamic_ev_duty_charging_candidates(
                            duty,
                            context=self.context,
                            policy=self.charging_policy,
                        )
                    )
                for candidate in charging_candidates:
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

        if not self.include_non_charging_candidates:
            return

        if not self.cross_depot_enabled:
            return

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


@dataclass(frozen=True)
class ExactDynamicSuffixProposalEngine:
    """Keep certified execution history fixed and search only future Duty."""

    context: DutyEvaluationContext
    source_id: str = "problem-hgs-exact-dynamic-future-neighbourhood-v1"

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
class SequentialProposalEngine:
    """Present each proposal stage to one education loop in serial order."""

    providers: tuple[DutyProposalEngine, ...]
    source_id: str = "problem-hgs-serial-route-then-mechanism-v1"

    def __post_init__(self) -> None:
        if not self.providers:
            raise ValueError("sequential proposal engine needs a provider")

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
            provider.propose(
                individual,
                evaluation,
                instance,
                include_whole_duty_type_exchange=(
                    include_whole_duty_type_exchange
                ),
            )
            for provider in self.providers
        )
        return _sequential_unique(streams)


def _sequential_unique(
    streams: tuple[Iterable[DutyMove], ...],
) -> Iterator[DutyMove]:
    """Yield every unique move stage by stage, preserving provider order."""

    seen: set[str] = set()
    for stream in streams:
        for move in stream:
            if move.action_id in seen:
                continue
            seen.add(move.action_id)
            yield move


@dataclass(frozen=True)
class InterleavedProposalEngine:
    """Keep route exploration and incumbent intensification separate."""

    providers: tuple[DutyProposalEngine, ...]
    elite_route_engine: DutyProposalEngine | None = None
    post_mechanism_route_engine: DutyProposalEngine | None = None
    mechanisms_on_final_incumbent_only: bool = False
    source_id: str = "problem-hgs-route-population-incumbent-intensification-v5"

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
                *(
                    ()
                    if self.elite_route_engine is None
                    else (
                        "elite_route_engine",
                        self.elite_route_engine.source_id,
                        self.elite_route_engine.identity_sha256,
                    )
                ),
                *(
                    ()
                    if self.post_mechanism_route_engine is None
                    else (
                        "post_mechanism_route_engine",
                        self.post_mechanism_route_engine.source_id,
                        self.post_mechanism_route_engine.identity_sha256,
                    )
                ),
                (
                    "mechanisms_on_final_incumbent_only="
                    f"{self.mechanisms_on_final_incumbent_only}"
                ),
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


def proposal_stages(
    engine: DutyProposalEngine,
) -> tuple[DutyProposalEngine, ...]:
    """Expose route exploration first and problem intensification afterwards."""

    if isinstance(engine, InterleavedProposalEngine):
        if engine.mechanisms_on_final_incumbent_only:
            return engine.providers[:1]
        return engine.providers
    return (engine,)


def proposal_final_stages(
    engine: DutyProposalEngine,
) -> tuple[DutyProposalEngine, ...]:
    """Return problem mechanisms reserved for the converged incumbent."""

    if (
        isinstance(engine, InterleavedProposalEngine)
        and engine.mechanisms_on_final_incumbent_only
    ):
        return engine.providers[1:]
    return ()


def proposal_elite_route(
    engine: DutyProposalEngine,
) -> DutyProposalEngine | None:
    """Return the independent route stream run on each new route incumbent."""

    if (
        isinstance(engine, InterleavedProposalEngine)
        and engine.elite_route_engine is not None
    ):
        return engine.elite_route_engine
    return None


def proposal_post_mechanism_route(
    engine: DutyProposalEngine,
) -> DutyProposalEngine | None:
    """Return the independent route stream used only after mechanism moves."""

    if (
        isinstance(engine, InterleavedProposalEngine)
        and engine.post_mechanism_route_engine is not None
    ):
        return engine.post_mechanism_route_engine
    return None


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
