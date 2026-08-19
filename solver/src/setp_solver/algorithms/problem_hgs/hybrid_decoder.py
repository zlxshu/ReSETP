"""Route-layer customer-order crossover and feasibility-bounded decoding.

The decoder deliberately has no per-vehicle trip-count parameter.  A split
label advances only when a contiguous customer segment is feasible under the
registered route contract.  Physical vehicle slots are then selected from the
canonical fleet registry; the registry bounds the number of physical assets,
not the number of trips a selected asset may carry.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any

from setp_solver.search.multitrip_schedule import TripTiming, route_timing
from setp_solver.solution import Route, Solution, route_trip_vehicle_id

from .fleet_registry import register_all_vehicle_slots
from .model import DutyIndividual


class HybridDecodeStatus(StrEnum):
    READY = "READY"
    BEST_EFFORT = "BEST_EFFORT"
    REJECTED = "REJECTED"


class HybridGapKind(StrEnum):
    TIME_WINDOW = "TIME_WINDOW"
    CHARGING_WINDOW = "CHARGING_WINDOW"
    FLEET_SLOT = "FLEET_SLOT"
    INTERFACE = "INTERFACE"


@dataclass(frozen=True)
class HybridDecodeGap:
    kind: HybridGapKind
    detail: str


@dataclass(frozen=True)
class PhysicalVehicleSlot:
    """One canonical physical slot available to the materializer.

    There is intentionally no trip-count field.  The slot may receive any
    number of non-overlapping trips; downstream C2 scheduling and the complete
    evaluator decide whether the resulting day is executable.
    """

    physical_vehicle_id: str
    vehicle_type: str
    home_depot_id: str
    available_shift_ids: tuple[str, ...]


@dataclass(frozen=True)
class SplitSegment:
    customer_ids: tuple[str, ...]
    vehicle_type: str
    home_depot_id: str
    shift_id: str | None
    earliest_departure_second: float | None = None
    return_second: float | None = None
    drive_energy_kwh: float | None = None
    preferred_physical_vehicle_id: str | None = None


@dataclass(frozen=True)
class HybridDecoderSpec:
    """Facts needed by the offline route-order decoder."""

    bundle: Any
    instance: Any
    prices: Any
    fleet_caps_by_depot: Mapping[str, Mapping[str, int]]
    customer_home_depot_by_id: Mapping[str, str]
    customer_shift_by_id: Mapping[str, str]
    customer_volume_m3_by_id: Mapping[str, float]
    shift_window_second_by_id: Mapping[str, tuple[float, float]]
    vehicle_volume_capacity_m3: float
    available_shift_ids_by_slot: Mapping[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class HybridDecodeOutcome:
    status: HybridDecodeStatus
    candidate: DutyIndividual | None
    customer_order: tuple[str, ...]
    segments: tuple[SplitSegment, ...]
    changed_duty_ids: frozenset[str]
    gaps: tuple[HybridDecodeGap, ...]
    wall_seconds: float

    @property
    def decoded(self) -> bool:
        return self.candidate is not None

    @property
    def ready_for_charging_rebuild(self) -> bool:
        return self.status == HybridDecodeStatus.READY and self.candidate is not None

    @property
    def trip_counts_by_vehicle(self) -> dict[str, int]:
        if self.candidate is None:
            return {}
        return {
            duty.physical_vehicle_id: len(duty.trips)
            for duty in self.candidate.duties
            if duty.trips
        }


@dataclass(frozen=True)
class DecoderBlockStructureStats:
    block_index: int
    length: int
    labels_created: int
    labels_surviving: int
    labels_pruned: int
    peak_labels_at_position: int
    final_position_labels: int
    probe_segment_calls: int
    d2_cache_hits: int
    d2_cache_misses: int


@dataclass(frozen=True)
class DecoderCallStructureStats:
    decode_index: int
    wall_seconds: float
    status: str
    block_count: int
    block_lengths: tuple[int, ...]
    blocks: tuple[DecoderBlockStructureStats, ...]


@dataclass(frozen=True)
class DecoderStructureStatsSnapshot:
    decoder_calls: tuple[DecoderCallStructureStats, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "decode_count": len(self.decoder_calls),
            "decoder_calls": [
                {
                    "decode_index": call.decode_index,
                    "wall_seconds": call.wall_seconds,
                    "status": call.status,
                    "block_count": call.block_count,
                    "block_lengths": list(call.block_lengths),
                    "blocks": [
                        {
                            "block_index": block.block_index,
                            "length": block.length,
                            "labels_created": block.labels_created,
                            "labels_surviving": block.labels_surviving,
                            "labels_pruned": block.labels_pruned,
                            "peak_labels_at_position": (
                                block.peak_labels_at_position
                            ),
                            "final_position_labels": (
                                block.final_position_labels
                            ),
                            "probe_segment_calls": block.probe_segment_calls,
                            "d2_cache_hits": block.d2_cache_hits,
                            "d2_cache_misses": block.d2_cache_misses,
                        }
                        for block in call.blocks
                    ],
                }
                for call in self.decoder_calls
            ],
        }


class _DecoderStructureStatsRecorder:
    def __init__(self) -> None:
        self.decoder_calls: list[DecoderCallStructureStats] = []

    def record(
        self,
        outcome: HybridDecodeOutcome,
        blocks: list[DecoderBlockStructureStats],
    ) -> None:
        block_tuple = tuple(blocks)
        self.decoder_calls.append(
            DecoderCallStructureStats(
                decode_index=len(self.decoder_calls) + 1,
                wall_seconds=float(outcome.wall_seconds),
                status=outcome.status.value,
                block_count=len(block_tuple),
                block_lengths=tuple(block.length for block in block_tuple),
                blocks=block_tuple,
            )
        )


_ACTIVE_DECODER_STRUCTURE_STATS: _DecoderStructureStatsRecorder | None = None


def begin_decoder_structure_stats() -> None:
    """Enable in-memory decoder statistics for one serial diagnostic run."""

    global _ACTIVE_DECODER_STRUCTURE_STATS
    if _ACTIVE_DECODER_STRUCTURE_STATS is not None:
        raise RuntimeError("decoder structure statistics are already active")
    _ACTIVE_DECODER_STRUCTURE_STATS = _DecoderStructureStatsRecorder()


def end_decoder_structure_stats() -> DecoderStructureStatsSnapshot:
    """Disable statistics and return the complete in-memory snapshot."""

    global _ACTIVE_DECODER_STRUCTURE_STATS
    recorder = _ACTIVE_DECODER_STRUCTURE_STATS
    if recorder is None:
        raise RuntimeError("decoder structure statistics are not active")
    _ACTIVE_DECODER_STRUCTURE_STATS = None
    return DecoderStructureStatsSnapshot(tuple(recorder.decoder_calls))


def decoder_structure_stats_enabled() -> bool:
    return _ACTIVE_DECODER_STRUCTURE_STATS is not None


def _record_decoder_structure_outcome(
    outcome: HybridDecodeOutcome,
    recorder: _DecoderStructureStatsRecorder | None,
    blocks: list[DecoderBlockStructureStats] | None,
) -> HybridDecodeOutcome:
    if recorder is not None:
        assert blocks is not None
        recorder.record(outcome, blocks)
    return outcome


@dataclass(frozen=True)
class _SegmentProbe:
    timing: TripTiming
    gap: HybridDecodeGap | None = None


def build_physical_vehicle_slot_table(
    spec: HybridDecoderSpec,
) -> tuple[PhysicalVehicleSlot, ...]:
    """Build slots from the real fleet-cap authority only."""

    all_shift_ids = tuple(sorted(spec.shift_window_second_by_id))
    slots: list[PhysicalVehicleSlot] = []
    for depot_id, caps in sorted(spec.fleet_caps_by_depot.items()):
        for vehicle_type, field_name in (("cv", "num_cv"), ("ev", "num_ev")):
            for index in range(1, int(caps[field_name]) + 1):
                physical_id = f"{vehicle_type.upper()}_{depot_id}_{index}"
                available = (
                    tuple(spec.available_shift_ids_by_slot[physical_id])
                    if spec.available_shift_ids_by_slot is not None
                    and physical_id in spec.available_shift_ids_by_slot
                    else all_shift_ids
                )
                slots.append(
                    PhysicalVehicleSlot(
                        physical_vehicle_id=physical_id,
                        vehicle_type=vehicle_type,
                        home_depot_id=str(depot_id),
                        available_shift_ids=available,
                    )
                )
    return tuple(slots)


def customer_order(individual: DutyIndividual) -> tuple[str, ...]:
    """Encode a Duty individual as one deterministic customer permutation."""

    order: list[str] = []
    for duty in sorted(individual.duties, key=lambda item: item.physical_vehicle_id):
        for trip in sorted(duty.trips, key=lambda item: int(item.trip_index)):
            order.extend(trip.customer_ids)
    if len(order) != len(set(order)):
        raise ValueError("customer order encoding found a duplicate customer")
    return tuple(order)


def order_crossover(
    first: Iterable[str],
    second: Iterable[str],
    rng: Any,
) -> tuple[str, ...]:
    """OX-style permutation crossover with no route separators."""

    left = tuple(str(item) for item in first)
    right = tuple(str(item) for item in second)
    if len(left) != len(right) or set(left) != set(right):
        raise ValueError("route-layer parents do not encode the same customers")
    if not left:
        return ()
    start = int(rng.randrange(len(left)))
    stop = start + 1 + int(rng.randrange(len(left) - start))
    child: list[str | None] = [None] * len(left)
    child[start:stop] = left[start:stop]
    fill = [customer for customer in right if customer not in child]
    fill_index = 0
    for index in range(len(child)):
        if child[index] is None:
            child[index] = fill[fill_index]
            fill_index += 1
    return tuple(str(customer) for customer in child)


def customer_vehicle_type_hints(
    individual: DutyIndividual,
) -> dict[str, str]:
    """Carry physical type identity as a hint; slots remain authoritative."""

    hints: dict[str, str] = {}
    for duty in individual.duties:
        vehicle_type = str(duty.vehicle_type).lower()
        for trip in duty.trips:
            for customer_id in trip.customer_ids:
                previous = hints.setdefault(customer_id, vehicle_type)
                if previous != vehicle_type:
                    raise ValueError(
                        f"customer {customer_id} has inconsistent parent vehicle types"
                    )
    return hints


def customer_home_depot_hints(
    individual: DutyIndividual,
) -> dict[str, str]:
    """Carry the parent physical home-depot identity into route decoding."""

    hints: dict[str, str] = {}
    for duty in individual.duties:
        for trip in duty.trips:
            for customer_id in trip.customer_ids:
                previous = hints.setdefault(customer_id, duty.home_depot_id)
                if previous != duty.home_depot_id:
                    raise ValueError(
                        f"customer {customer_id} has inconsistent parent home depots"
                    )
    return hints


def customer_physical_slot_hints(
    individual: DutyIndividual,
) -> dict[str, str]:
    """Carry a parent slot as an assignment preference, never as a limit."""

    hints: dict[str, str] = {}
    for duty in individual.duties:
        for trip in duty.trips:
            for customer_id in trip.customer_ids:
                previous = hints.setdefault(
                    customer_id,
                    duty.physical_vehicle_id,
                )
                if previous != duty.physical_vehicle_id:
                    raise ValueError(
                        f"customer {customer_id} has inconsistent parent physical slots"
                    )
    return hints


def route_layer_order_from_parents(
    first: DutyIndividual,
    second: DutyIndividual,
    rng: Any,
) -> tuple[tuple[str, ...], dict[str, str]]:
    """Return the OX child order plus first-parent type hints."""

    first_order = customer_order(first)
    second_order = customer_order(second)
    hints = customer_vehicle_type_hints(first)
    if set(hints) != set(first_order):
        second_hints = customer_vehicle_type_hints(second)
        hints.update(second_hints)
    return order_crossover(first_order, second_order, rng), hints


def decode_customer_order(
    order: Iterable[str],
    *,
    spec: HybridDecoderSpec,
    vehicle_type_hints: Mapping[str, str],
    physical_slot_hints: Mapping[str, str] | None = None,
    source: str = "hybrid_route_layer_split",
) -> HybridDecodeOutcome:
    """Split, assign canonical slots, and return a raw best-effort candidate.

    The only finite enumeration boundary is that every extension consumes at
    least one customer and the customer permutation is finite.  Labels are
    removed only by time/energy dominance at the same permutation position.
    No label is removed because a vehicle has accumulated a particular number
    of trips.
    """

    started = perf_counter()
    structure_recorder = _ACTIVE_DECODER_STRUCTURE_STATS
    block_structure_stats = (
        [] if structure_recorder is not None else None
    )
    customer_order_tuple = tuple(str(customer) for customer in order)
    gaps: list[HybridDecodeGap] = []
    known_customers = set(spec.customer_home_depot_by_id)
    if len(customer_order_tuple) != len(set(customer_order_tuple)):
        return _record_decoder_structure_outcome(
            HybridDecodeOutcome(
                HybridDecodeStatus.REJECTED,
                None,
                customer_order_tuple,
                (),
                frozenset(),
                (
                    HybridDecodeGap(
                        HybridGapKind.INTERFACE,
                        "customer permutation has duplicates",
                    ),
                ),
                perf_counter() - started,
            ),
            structure_recorder,
            block_structure_stats,
        )
    missing = known_customers.difference(customer_order_tuple)
    unknown = set(customer_order_tuple).difference(known_customers)
    if missing or unknown:
        detail = (
            f"missing={sorted(missing)} unknown={sorted(unknown)}"
        )
        return _record_decoder_structure_outcome(
            HybridDecodeOutcome(
                HybridDecodeStatus.REJECTED,
                None,
                customer_order_tuple,
                (),
                frozenset(),
                (HybridDecodeGap(HybridGapKind.INTERFACE, detail),),
                perf_counter() - started,
            ),
            structure_recorder,
            block_structure_stats,
        )

    segments: list[SplitSegment] = []
    position = 0
    while position < len(customer_order_tuple):
        first_customer = customer_order_tuple[position]
        first_type = str(vehicle_type_hints.get(first_customer, "")).lower()
        if first_type not in {"cv", "ev"}:
            gaps.append(
                HybridDecodeGap(
                    HybridGapKind.INTERFACE,
                    f"no canonical vehicle type for {first_customer}",
                )
            )
            first_type = "cv"
        first_depot = str(spec.customer_home_depot_by_id[first_customer])
        first_shift = (
            None
            if not spec.customer_shift_by_id
            else str(spec.customer_shift_by_id[first_customer])
        )
        block_end = position + 1
        while block_end < len(customer_order_tuple):
            customer = customer_order_tuple[block_end]
            key = (
                str(spec.customer_home_depot_by_id[customer]),
                str(vehicle_type_hints.get(customer, first_type)).lower(),
                None
                if not spec.customer_shift_by_id
                else str(spec.customer_shift_by_id[customer]),
            )
            if key != (first_depot, first_type, first_shift):
                break
            block_end += 1
        block = customer_order_tuple[position:block_end]
        block_segments, block_gaps = _split_block(
            block,
            vehicle_type=first_type,
            home_depot_id=first_depot,
            shift_id=first_shift,
            spec=spec,
            physical_slot_hints=physical_slot_hints or {},
            structure_stats=block_structure_stats,
        )
        segments.extend(block_segments)
        gaps.extend(block_gaps)
        position = block_end

    slots = build_physical_vehicle_slot_table(spec)
    if not slots:
        gaps.append(
            HybridDecodeGap(
                HybridGapKind.FLEET_SLOT,
                "fleet_caps_by_depot contains no physical slots",
            )
        )
        return _record_decoder_structure_outcome(
            HybridDecodeOutcome(
                HybridDecodeStatus.REJECTED,
                None,
                customer_order_tuple,
                tuple(segments),
                frozenset(),
                tuple(gaps),
                perf_counter() - started,
            ),
            structure_recorder,
            block_structure_stats,
        )

    candidate, assignment_gaps, changed_ids = _materialize_segments(
        segments,
        slots=slots,
        spec=spec,
        known_customers=known_customers,
        source=source,
    )
    gaps.extend(assignment_gaps)
    status = HybridDecodeStatus.READY if not gaps else HybridDecodeStatus.BEST_EFFORT
    return _record_decoder_structure_outcome(
        HybridDecodeOutcome(
            status,
            candidate,
            customer_order_tuple,
            tuple(segments),
            frozenset(changed_ids),
            tuple(gaps),
            perf_counter() - started,
        ),
        structure_recorder,
        block_structure_stats,
    )


def _split_block(
    block: tuple[str, ...],
    *,
    vehicle_type: str,
    home_depot_id: str,
    shift_id: str | None,
    spec: HybridDecoderSpec,
    physical_slot_hints: Mapping[str, str],
    structure_stats: list[DecoderBlockStructureStats] | None = None,
) -> tuple[tuple[SplitSegment, ...], tuple[HybridDecodeGap, ...]]:
    """Split one fixed-attribute block without enumerating split histories.

    The legacy implementation retained every feasible split history, then
    applied energy dominance among histories sharing the same final segment.
    Here each interval is probed once and the same dominance semantics are
    reconstructed from the minimum energy at each DAG position.  A greedy
    predecessor reconstruction uses a suffix-completion DP to preserve the
    legacy longest-first final key exactly.
    """

    segment_by_bounds: dict[
        tuple[int, int],
        tuple[SplitSegment | None, HybridDecodeGap | None],
    ] = {}
    failures: list[HybridDecodeGap] = []
    labels_created = 0
    d2_cache_hits = 0
    d2_cache_misses = 0

    def segment_for_bounds(
        position: int,
        end: int,
    ) -> tuple[SplitSegment | None, HybridDecodeGap | None]:
        nonlocal d2_cache_hits, d2_cache_misses
        bounds = (position, end)
        cached = segment_by_bounds.get(bounds)
        if cached is not None:
            if structure_stats is not None:
                d2_cache_hits += 1
            return cached
        if structure_stats is not None:
            d2_cache_misses += 1
        customers = block[position:end]
        probe = _probe_segment(
            customers,
            vehicle_type=vehicle_type,
            home_depot_id=home_depot_id,
            shift_id=shift_id,
            spec=spec,
        )
        if probe.gap is not None:
            cached = (None, probe.gap)
        else:
            timing = probe.timing
            cached = (
                SplitSegment(
                    customers,
                    vehicle_type,
                    home_depot_id,
                    shift_id,
                    float(timing.earliest_departure_second),
                    float(timing.return_second),
                    float(timing.drive_energy_kwh),
                    _preferred_slot_id(customers, physical_slot_hints),
                ),
                None,
            )
        segment_by_bounds[bounds] = cached
        return cached

    # Match the legacy probe order: an interval is inspected only when its
    # start position is reachable, with both starts and ends increasing.
    reachable_positions = {0}
    for position in range(len(block)):
        if position not in reachable_positions:
            continue
        for end in range(position + 1, len(block) + 1):
            segment, gap = segment_for_bounds(position, end)
            if gap is not None:
                failures.append(gap)
            else:
                assert segment is not None
                reachable_positions.add(end)

    # One scalar state per position reproduces the global minimum cumulative
    # energy that the old label set necessarily contained.  The second cache
    # access is intentional: it remains a real D2 hit and keeps the existing
    # structure-stat field semantics unchanged.
    minimum_energy_by_position = {0: 0.0}
    for position in range(len(block)):
        if position not in minimum_energy_by_position:
            continue
        for end in range(position + 1, len(block) + 1):
            segment, gap = segment_for_bounds(position, end)
            if gap is not None:
                continue
            assert segment is not None
            labels_created += 1
            candidate_energy = float(
                minimum_energy_by_position[position]
                + float(segment.drive_energy_kwh)
            )
            previous = minimum_energy_by_position.get(end)
            if previous is None or candidate_energy < previous:
                minimum_energy_by_position[end] = candidate_energy

    final_position_reachable = len(block) in minimum_energy_by_position
    if structure_stats is not None:
        labels_surviving = len(minimum_energy_by_position) - 1
        structure_stats.append(
            DecoderBlockStructureStats(
                block_index=len(structure_stats) + 1,
                length=len(block),
                labels_created=labels_created,
                labels_surviving=labels_surviving,
                labels_pruned=labels_created - labels_surviving,
                peak_labels_at_position=1 if labels_surviving else 0,
                final_position_labels=1 if final_position_reachable else 0,
                probe_segment_calls=d2_cache_misses,
                d2_cache_hits=d2_cache_hits,
                d2_cache_misses=d2_cache_misses,
            )
        )
    if final_position_reachable:
        return (
            _select_legacy_split_chain(
                block_length=len(block),
                segment_by_bounds=segment_by_bounds,
                minimum_energy_by_position=minimum_energy_by_position,
            ),
            (),
        )

    # Keep a raw best effort so C2/full evaluation can report the real failure
    # category.  This is a fallback representation, not an artificial trip
    # limit: every customer remains present and no vehicle count is invented.
    fallback = tuple(
        SplitSegment(
            (customer,),
            vehicle_type,
            home_depot_id,
            shift_id,
            preferred_physical_vehicle_id=physical_slot_hints.get(customer),
        )
        for customer in block
    )
    if not failures:
        failures = [
            HybridDecodeGap(
                HybridGapKind.TIME_WINDOW,
                "no feasible split label reached the end of the block",
            )
        ]
    return fallback, tuple(failures[-1:])


def _select_legacy_split_chain(
    *,
    block_length: int,
    segment_by_bounds: Mapping[
        tuple[int, int],
        tuple[SplitSegment | None, HybridDecodeGap | None],
    ],
    minimum_energy_by_position: Mapping[int, float],
) -> tuple[SplitSegment, ...]:
    """Rebuild the old dominance-filtered, longest-first split path."""

    selected: list[SplitSegment] = []
    position = 0
    accumulated_energy = 0.0
    while position < block_length:
        for end in range(block_length, position, -1):
            segment, gap = segment_by_bounds.get((position, end), (None, None))
            if gap is not None or segment is None:
                continue
            survives, candidate_energy = _legacy_split_extension_survives(
                position=position,
                accumulated_energy=accumulated_energy,
                segment=segment,
                minimum_energy_by_position=minimum_energy_by_position,
            )
            if survives and _legacy_split_can_complete(
                start=end,
                accumulated_energy=candidate_energy,
                block_length=block_length,
                segment_by_bounds=segment_by_bounds,
                minimum_energy_by_position=minimum_energy_by_position,
            ):
                selected.append(segment)
                position = end
                accumulated_energy = candidate_energy
                break
        else:
            raise RuntimeError(
                "reachable split endpoint has no reconstructable predecessor chain"
            )
    return tuple(selected)


def _legacy_split_extension_survives(
    *,
    position: int,
    accumulated_energy: float,
    segment: SplitSegment,
    minimum_energy_by_position: Mapping[int, float],
) -> tuple[bool, float]:
    """Return the exact energy-dominance decision used by the old labels."""

    segment_energy = float(segment.drive_energy_kwh)
    candidate_energy = float(accumulated_energy + segment_energy)
    group_minimum_energy = float(
        minimum_energy_by_position[position] + segment_energy
    )
    dominated = (
        group_minimum_energy <= candidate_energy + 1.0e-9
        and group_minimum_energy < candidate_energy - 1.0e-9
    )
    return not dominated, candidate_energy


def _legacy_split_can_complete(
    *,
    start: int,
    accumulated_energy: float,
    block_length: int,
    segment_by_bounds: Mapping[
        tuple[int, int],
        tuple[SplitSegment | None, HybridDecodeGap | None],
    ],
    minimum_energy_by_position: Mapping[int, float],
) -> bool:
    """Test suffix reachability while preserving legacy energy dominance."""

    best_energy = {start: float(accumulated_energy)}
    for position in range(start, block_length):
        position_energy = best_energy.get(position)
        if position_energy is None:
            continue
        for end in range(position + 1, block_length + 1):
            segment, gap = segment_by_bounds.get((position, end), (None, None))
            if gap is not None or segment is None:
                continue
            survives, candidate_energy = _legacy_split_extension_survives(
                position=position,
                accumulated_energy=position_energy,
                segment=segment,
                minimum_energy_by_position=minimum_energy_by_position,
            )
            if not survives:
                continue
            previous = best_energy.get(end)
            if previous is None or candidate_energy < previous:
                best_energy[end] = candidate_energy
    return block_length in best_energy


def _preferred_slot_id(
    customers: tuple[str, ...],
    physical_slot_hints: Mapping[str, str],
) -> str | None:
    counts: dict[str, int] = {}
    for customer in customers:
        slot_id = physical_slot_hints.get(customer)
        if slot_id is not None:
            counts[slot_id] = counts.get(slot_id, 0) + 1
    if not counts:
        return None
    return min(counts, key=lambda slot_id: (-counts[slot_id], slot_id))


def _probe_segment(
    customers: tuple[str, ...],
    *,
    vehicle_type: str,
    home_depot_id: str,
    shift_id: str | None,
    spec: HybridDecoderSpec,
) -> _SegmentProbe:
    volume = sum(
        float(spec.customer_volume_m3_by_id.get(customer, 0.0))
        for customer in customers
    )
    if volume > float(spec.vehicle_volume_capacity_m3) + 1.0e-9:
        return _SegmentProbe(
            TripTiming("SPLIT_PROBE", vehicle_type, home_depot_id, 0.0, 0.0, 0.0),
            HybridDecodeGap(
                HybridGapKind.TIME_WINDOW,
                f"volume {volume:.12g} exceeds Q_volume={spec.vehicle_volume_capacity_m3:.12g}",
            ),
        )
    route = Route(
        vehicle_id="SPLIT_PROBE",
        vehicle_type=vehicle_type,
        home_depot_id=home_depot_id,
        node_sequence=[home_depot_id, *customers, home_depot_id],
    )
    shift_start = None
    shift_end = None
    if shift_id is not None:
        try:
            shift_start, shift_end = spec.shift_window_second_by_id[shift_id]
        except KeyError:
            return _SegmentProbe(
                TripTiming("SPLIT_PROBE", vehicle_type, home_depot_id, 0.0, 0.0, 0.0),
                HybridDecodeGap(
                    HybridGapKind.TIME_WINDOW,
                    f"shift {shift_id} has no registered time window",
                ),
            )
    try:
        timing = route_timing(
            route,
            spec.instance,
            spec.prices,
            validate_battery=False,
            minimum_departure_second=(
                None if shift_start is None else float(shift_start)
            ),
        )
    except (TypeError, ValueError) as error:
        return _SegmentProbe(
            TripTiming("SPLIT_PROBE", vehicle_type, home_depot_id, 0.0, 0.0, 0.0),
            HybridDecodeGap(HybridGapKind.TIME_WINDOW, str(error)),
        )
    if shift_id is not None:
        assert shift_start is not None and shift_end is not None
        if float(timing.earliest_departure_second) < float(shift_start) - 1.0e-6:
            return _SegmentProbe(
                timing,
                HybridDecodeGap(
                    HybridGapKind.TIME_WINDOW,
                    f"departure before {shift_id} start",
                ),
            )
        if float(timing.return_second) > float(shift_end) + 1.0e-6:
            return _SegmentProbe(
                timing,
                HybridDecodeGap(
                    HybridGapKind.TIME_WINDOW,
                    f"return after {shift_id} end",
                ),
            )
    if vehicle_type == "ev":
        fallback_battery = (
            float(spec.prices.get("B_battery_kwh", 0.0))
            if isinstance(spec.prices, Mapping)
            else float(getattr(spec.prices, "B_battery_kwh", 0.0))
        )
        battery = float(
            spec.instance.battery_capacity_kwh(fallback=fallback_battery)
        )
        if float(timing.drive_energy_kwh) > battery + 1.0e-6:
            return _SegmentProbe(
                timing,
                HybridDecodeGap(
                    HybridGapKind.CHARGING_WINDOW,
                    f"route energy {timing.drive_energy_kwh:.12g} exceeds battery",
                ),
            )
    return _SegmentProbe(timing)


def _materialize_segments(
    segments: tuple[SplitSegment, ...],
    *,
    slots: tuple[PhysicalVehicleSlot, ...],
    spec: HybridDecoderSpec,
    known_customers: set[str],
    source: str,
) -> tuple[DutyIndividual | None, tuple[HybridDecodeGap, ...], frozenset[str]]:
    """Assign segments to registered physical slots and decode via the model."""

    assigned: dict[str, list[SplitSegment]] = {
        slot.physical_vehicle_id: [] for slot in slots
    }
    last_return: dict[str, float] = {
        slot.physical_vehicle_id: 0.0 for slot in slots
    }
    gaps: list[HybridDecodeGap] = []
    # The customer permutation is a route-order object, not a dispatch clock.
    # Slot assignment therefore schedules the already split trips in their
    # feasible clock order before assigning physical trip indices.
    ordered_segments = tuple(
        segment
        for _index, segment in sorted(
            enumerate(segments),
            key=lambda item: (
                float(
                    "inf"
                    if item[1].earliest_departure_second is None
                    else item[1].earliest_departure_second
                ),
                float(
                    "inf"
                    if item[1].return_second is None
                    else item[1].return_second
                ),
                item[0],
            ),
        )
    )
    for segment in ordered_segments:
        matching = [
            slot
            for slot in slots
            if slot.vehicle_type == segment.vehicle_type
            and slot.home_depot_id == segment.home_depot_id
            and (
                not slot.available_shift_ids
                or segment.shift_id is None
                or segment.shift_id in slot.available_shift_ids
            )
        ]
        if not matching:
            matching = [
                slot
                for slot in slots
                if slot.home_depot_id == segment.home_depot_id
            ]
            gaps.append(
                HybridDecodeGap(
                    HybridGapKind.FLEET_SLOT,
                    f"no compatible {segment.vehicle_type} slot at {segment.home_depot_id}",
                )
            )
        if not matching:
            matching = list(slots)
            gaps.append(
                HybridDecodeGap(
                    HybridGapKind.FLEET_SLOT,
                    "no slot at the segment home depot",
                )
            )
        timing_return = (
            float(segment.return_second)
            if segment.return_second is not None
            else float("inf")
        )
        eligible = [
            slot
            for slot in matching
            if float(last_return[slot.physical_vehicle_id])
            <= float(segment.earliest_departure_second or 0.0) + 1.0e-6
        ]
        if eligible:
            selected = min(
                eligible,
                key=lambda slot: (
                    0
                    if slot.physical_vehicle_id
                    == segment.preferred_physical_vehicle_id
                    else 1,
                    float(last_return[slot.physical_vehicle_id]),
                    slot.physical_vehicle_id,
                ),
            )
        else:
            selected = min(
                matching,
                key=lambda slot: (
                    float(last_return[slot.physical_vehicle_id]),
                    slot.physical_vehicle_id,
                ),
            )
            gaps.append(
                HybridDecodeGap(
                    HybridGapKind.CHARGING_WINDOW,
                    f"physical slot {selected.physical_vehicle_id} has an inter-trip overlap",
                )
            )
        physical_id = selected.physical_vehicle_id
        assigned[physical_id].append(segment)
        last_return[physical_id] = max(
            float(last_return[physical_id]), timing_return
        )

    routes: list[Route] = []
    for slot in slots:
        for trip_index, segment in enumerate(assigned[slot.physical_vehicle_id], start=1):
            routes.append(
                Route(
                    vehicle_id=route_trip_vehicle_id(
                        slot.physical_vehicle_id,
                        trip_index,
                    ),
                    vehicle_type=slot.vehicle_type,
                    home_depot_id=slot.home_depot_id,
                    node_sequence=[
                        slot.home_depot_id,
                        *segment.customer_ids,
                        slot.home_depot_id,
                    ],
                )
            )
    try:
        raw = DutyIndividual.from_solution(
            Solution(routes=routes),
            customer_node_ids=known_customers,
            source=source,
        )
        registered = register_all_vehicle_slots(raw, spec.bundle)
    except (TypeError, ValueError, RuntimeError) as error:
        gaps.append(HybridDecodeGap(HybridGapKind.INTERFACE, str(error)))
        return (
            None,
            tuple(gaps),
            frozenset(assigned),
        )
    return registered, tuple(gaps), frozenset(
        physical_id for physical_id, items in assigned.items() if items
    )
