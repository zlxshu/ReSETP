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














