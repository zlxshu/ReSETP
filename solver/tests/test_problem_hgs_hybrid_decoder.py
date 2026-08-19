from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import importlib.util
import itertools
import math
from pathlib import Path
import random
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from setp_solver.algorithms.problem_hgs import hybrid_decoder
from setp_solver.algorithms.problem_hgs.hybrid_decoder import (
    HybridDecoderSpec,
    build_physical_vehicle_slot_table,
    order_crossover,
)


_ORACLE_PATH = (
    Path(__file__).parents[1]
    / "reports/fix_decoder_dag_20260817/oracle_hybrid_decoder_pre_rewrite.py"
)
_ORACLE_SHA256 = "0ce1f49ac8671f23b9adcee80d895db527ed1e96d5a530213ee7c7d4aa1d0270"


def _load_oracle_module() -> Any:
    module_name = (
        "setp_solver.algorithms.problem_hgs."
        "_oracle_hybrid_decoder_pre_rewrite"
    )
    spec = importlib.util.spec_from_file_location(module_name, _ORACLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _run_split_with_arc_table(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    block: tuple[str, ...],
    energy_by_bounds: dict[tuple[int, int], float],
    *,
    structure_stats: list[Any] | None = None,
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    position_by_customer = {
        customer: position for position, customer in enumerate(block)
    }

    def fake_probe(
        customers: tuple[str, ...],
        *,
        vehicle_type: str,
        home_depot_id: str,
        shift_id: str | None,
        spec: object,
    ) -> Any:
        del vehicle_type, home_depot_id, shift_id, spec
        start = position_by_customer[customers[0]]
        end = start + len(customers)
        assert block[start:end] == customers
        energy = energy_by_bounds.get((start, end))
        if energy is None:
            return module._SegmentProbe(
                SimpleNamespace(
                    earliest_departure_second=0.0,
                    return_second=float(len(customers)),
                    drive_energy_kwh=0.0,
                ),
                module.HybridDecodeGap(
                    module.HybridGapKind.TIME_WINDOW,
                    f"infeasible bounds {start}:{end}",
                ),
            )
        return module._SegmentProbe(
            SimpleNamespace(
                earliest_departure_second=float(start),
                return_second=float(end),
                drive_energy_kwh=float(energy),
            )
        )

    monkeypatch.setattr(module, "_probe_segment", fake_probe)
    return module._split_block(
        block,
        vehicle_type="ev",
        home_depot_id="D0",
        shift_id="AM",
        spec=object(),
        physical_slot_hints={
            customer: f"EV_D0_{1 + position % 2}"
            for position, customer in enumerate(block)
        },
        structure_stats=structure_stats,
    )


def _split_signature(
    result: tuple[tuple[Any, ...], tuple[Any, ...]],
) -> tuple[tuple[tuple[Any, ...], ...], tuple[tuple[str, str], ...]]:
    segments, gaps = result
    return (
        tuple(
            (
                tuple(segment.customer_ids),
                segment.vehicle_type,
                segment.home_depot_id,
                segment.shift_id,
                segment.earliest_departure_second,
                segment.return_second,
                segment.drive_energy_kwh,
                segment.preferred_physical_vehicle_id,
            )
            for segment in segments
        ),
        tuple((gap.kind.value, gap.detail) for gap in gaps),
    )


def test_route_layer_ox_and_slot_registry_have_no_trip_limit() -> None:
    spec = HybridDecoderSpec(
        bundle=object(),
        instance=object(),
        prices={},
        fleet_caps_by_depot={
            "D0": {"num_cv": 1, "num_ev": 2, "total_fleet_cap": 3},
        },
        customer_home_depot_by_id={},
        customer_shift_by_id={"AM": "AM"},
        customer_volume_m3_by_id={},
        shift_window_second_by_id={"AM": (0.0, 1.0)},
        vehicle_volume_capacity_m3=1.0,
    )

    slots = build_physical_vehicle_slot_table(spec)
    assert [slot.physical_vehicle_id for slot in slots] == [
        "CV_D0_1",
        "EV_D0_1",
        "EV_D0_2",
    ]
    assert all(not hasattr(slot, "max_trips_per_vehicle") for slot in slots)

    first = ("C1", "C2", "C3", "C4")
    second = ("C3", "C1", "C4", "C2")
    child = order_crossover(first, second, random.Random(11))
    assert len(child) == len(first)
    assert set(child) == set(first)


def test_split_block_probes_each_contiguous_segment_once(monkeypatch) -> None:
    calls: dict[tuple[str, ...], int] = {}
    structure_stats: list[hybrid_decoder.DecoderBlockStructureStats] = []

    def fake_probe(
        customers: tuple[str, ...],
        *,
        vehicle_type: str,
        home_depot_id: str,
        shift_id: str | None,
        spec: object,
    ) -> hybrid_decoder._SegmentProbe:
        assert (vehicle_type, home_depot_id, shift_id) == ("cv", "D0", "AM")
        calls[customers] = calls.get(customers, 0) + 1
        length = float(len(customers))
        return hybrid_decoder._SegmentProbe(
            SimpleNamespace(
                earliest_departure_second=0.0,
                return_second=length,
                drive_energy_kwh=length,
            )
        )

    monkeypatch.setattr(hybrid_decoder, "_probe_segment", fake_probe)
    block = ("C1", "C2", "C3", "C4")
    segments, gaps = hybrid_decoder._split_block(
        block,
        vehicle_type="cv",
        home_depot_id="D0",
        shift_id="AM",
        spec=object(),
        physical_slot_hints={},
        structure_stats=structure_stats,
    )

    expected = {
        block[start:end]
        for start in range(len(block))
        for end in range(start + 1, len(block) + 1)
    }
    assert calls == {customers: 1 for customers in expected}
    assert len(structure_stats) == 1
    block_stats = structure_stats[0]
    assert block_stats.length == len(block)
    assert block_stats.probe_segment_calls == len(expected)
    assert block_stats.d2_cache_misses == len(expected)
    assert block_stats.d2_cache_hits > 0
    assert block_stats.labels_created >= block_stats.labels_surviving
    assert (
        block_stats.labels_pruned
        == block_stats.labels_created - block_stats.labels_surviving
    )
    assert not gaps
    assert segments
    with pytest.raises(FrozenInstanceError):
        segments[0].return_second = 999.0


def test_decoder_structure_stats_are_disabled_by_default() -> None:
    assert not hybrid_decoder.decoder_structure_stats_enabled()

    hybrid_decoder.begin_decoder_structure_stats()
    try:
        assert hybrid_decoder.decoder_structure_stats_enabled()
    finally:
        snapshot = hybrid_decoder.end_decoder_structure_stats()

    assert not hybrid_decoder.decoder_structure_stats_enabled()
    assert snapshot.to_dict() == {
        "schema_version": 1,
        "decode_count": 0,
        "decoder_calls": [],
    }


def test_pre_rewrite_oracle_is_byte_exact_and_frozen() -> None:
    assert hashlib.sha256(_ORACLE_PATH.read_bytes()).hexdigest() == _ORACLE_SHA256


def test_dag_split_preserves_legacy_energy_dominance_before_lex_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oracle = _load_oracle_module()
    block = ("C1", "C2", "C3", "C4")
    energy_by_bounds = {
        (0, 1): 0.0,
        (0, 2): 10.0,
        (1, 2): 0.0,
        (2, 4): 0.0,
    }

    old_result = _run_split_with_arc_table(
        oracle, monkeypatch, block, energy_by_bounds
    )
    new_result = _run_split_with_arc_table(
        hybrid_decoder, monkeypatch, block, energy_by_bounds
    )

    assert _split_signature(new_result) == _split_signature(old_result)
    assert tuple(segment.customer_ids for segment in new_result[0]) == (
        ("C1",),
        ("C2",),
        ("C3", "C4"),
    )


def test_dag_split_keeps_middle_tolerance_history_needed_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oracle = _load_oracle_module()
    block = tuple(f"C{index}" for index in range(1, 8))
    epsilon = 1.0e-9
    energy_by_bounds = {
        (0, 1): 0.0,
        (0, 2): 10.0 + 0.4 * epsilon,
        (0, 3): 10.0 + 0.9 * epsilon,
        (1, 4): 10.0,
        (1, 5): 10.0 - 0.3 * epsilon,
        (2, 4): 0.0,
        (3, 4): 0.0,
        (4, 6): 0.0,
        (5, 6): 0.0,
        (6, 7): 0.0,
    }

    old_result = _run_split_with_arc_table(
        oracle, monkeypatch, block, energy_by_bounds
    )
    new_result = _run_split_with_arc_table(
        hybrid_decoder, monkeypatch, block, energy_by_bounds
    )

    assert _split_signature(new_result) == _split_signature(old_result)
    assert tuple(segment.customer_ids for segment in new_result[0]) == (
        ("C1", "C2"),
        ("C3", "C4"),
        ("C5", "C6"),
        ("C7",),
    )


def test_dag_split_matches_oracle_for_exhaustive_and_random_small_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oracle = _load_oracle_module()
    for permutation in itertools.permutations(range(5)):
        block = tuple(f"C{value}" for value in permutation)
        energy_by_bounds: dict[tuple[int, int], float] = {}
        for start in range(len(block)):
            for end in range(start + 1, len(block) + 1):
                values = permutation[start:end]
                if end == start + 1 or (sum(values) + start + end) % 3:
                    energy_by_bounds[start, end] = float(
                        (sum(values) * 7 + start * 3 + end) % 13
                    )
        old_result = _run_split_with_arc_table(
            oracle, monkeypatch, block, energy_by_bounds
        )
        new_result = _run_split_with_arc_table(
            hybrid_decoder, monkeypatch, block, energy_by_bounds
        )
        assert _split_signature(new_result) == _split_signature(old_result)

    rng = random.Random(20260817)
    tolerance_energies = (0.0, 0.4e-9, 0.9e-9, 1.1e-9, 0.1, 1.0, 10.0)
    for length in range(2, 9):
        for _case in range(20):
            values = list(range(length))
            rng.shuffle(values)
            block = tuple(f"R{value}" for value in values)
            energy_by_bounds = {}
            for start in range(length):
                for end in range(start + 1, length + 1):
                    if end == start + 1 or rng.random() < 0.55:
                        energy_by_bounds[start, end] = rng.choice(
                            tolerance_energies
                        )
            old_result = _run_split_with_arc_table(
                oracle, monkeypatch, block, energy_by_bounds
            )
            new_result = _run_split_with_arc_table(
                hybrid_decoder, monkeypatch, block, energy_by_bounds
            )
            assert _split_signature(new_result) == _split_signature(old_result)


def test_dag_split_matches_oracle_through_length_twelve_and_is_polynomial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oracle = _load_oracle_module()
    for length in range(1, 13):
        block = tuple(f"C{index}" for index in range(length))
        limited_arcs = {
            (start, end): float((end - start) % 2)
            for start in range(length)
            for end in range(start + 1, min(length, start + 3) + 1)
        }
        old_result = _run_split_with_arc_table(
            oracle, monkeypatch, block, limited_arcs
        )
        new_result = _run_split_with_arc_table(
            hybrid_decoder, monkeypatch, block, limited_arcs
        )
        assert _split_signature(new_result) == _split_signature(old_result)

    length = 12
    block = tuple(f"L{index}" for index in range(length))
    all_arcs = {
        (start, end): 0.0
        for start in range(length)
        for end in range(start + 1, length + 1)
    }
    old_stats: list[Any] = []
    new_stats: list[Any] = []
    old_result = _run_split_with_arc_table(
        oracle,
        monkeypatch,
        block,
        all_arcs,
        structure_stats=old_stats,
    )
    new_result = _run_split_with_arc_table(
        hybrid_decoder,
        monkeypatch,
        block,
        all_arcs,
        structure_stats=new_stats,
    )

    assert _split_signature(new_result) == _split_signature(old_result)
    assert old_stats[0].labels_created == 2**length - 1
    assert old_stats[0].labels_surviving == 2**length - 1
    assert new_stats[0].labels_created == length * (length + 1) // 2
    assert new_stats[0].labels_surviving == length
    assert new_stats[0].labels_pruned == (
        new_stats[0].labels_created - new_stats[0].labels_surviving
    )
    assert new_stats[0].peak_labels_at_position == 1
    assert new_stats[0].final_position_labels == 1
    assert new_stats[0].probe_segment_calls == length * (length + 1) // 2
    assert new_stats[0].d2_cache_misses == length * (length + 1) // 2
    assert new_stats[0].d2_cache_hits == length * (length + 1) // 2


def test_dag_split_preserves_success_and_failure_gap_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oracle = _load_oracle_module()
    block = ("C1", "C2", "C3")

    successful_arcs = {(0, 1): 0.0, (1, 2): 0.0, (2, 3): 0.0}
    old_success = _run_split_with_arc_table(
        oracle, monkeypatch, block, successful_arcs
    )
    new_success = _run_split_with_arc_table(
        hybrid_decoder, monkeypatch, block, successful_arcs
    )
    assert _split_signature(new_success) == _split_signature(old_success)
    assert new_success[1] == ()

    incomplete_arcs = {(0, 1): 0.0}
    old_failure = _run_split_with_arc_table(
        oracle, monkeypatch, block, incomplete_arcs
    )
    new_failure = _run_split_with_arc_table(
        hybrid_decoder, monkeypatch, block, incomplete_arcs
    )
    assert _split_signature(new_failure) == _split_signature(old_failure)
    assert new_failure[1][0].detail == "infeasible bounds 1:3"
    assert all(segment.return_second is None for segment in new_failure[0])


def test_legacy_dominance_tolerance_matches_oracle_nextafter_boundaries() -> None:
    oracle = _load_oracle_module()
    segment = hybrid_decoder.SplitSegment(
        ("C1",),
        "ev",
        "D0",
        "AM",
        0.0,
        1.0,
        0.0,
    )
    inside = math.nextafter(1.0e-9, 0.0)
    outside = math.nextafter(1.0e-9, math.inf)

    for energy, expected_survival_count in ((inside, 2), (outside, 1)):
        survives, _candidate = hybrid_decoder._legacy_split_extension_survives(
            position=0,
            accumulated_energy=energy,
            segment=segment,
            minimum_energy_by_position={0: 0.0},
        )
        oracle_labels = oracle._prune_split_labels(
            [
                oracle._SplitLabel(1, (), 0.0, 0.0, 0),
                oracle._SplitLabel(1, (), 0.0, energy, 0),
            ]
        )
        assert len(oracle_labels) == expected_survival_count
        assert survives is (expected_survival_count == 2)
