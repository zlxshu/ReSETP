from __future__ import annotations

from pathlib import Path

from setp_solver.china81 import (
    CHINA81_HORIZON_END_SECOND,
    CHINA81_HORIZON_START_SECOND,
    load_china81_bundle,
)

from .stream import build_h0_g2_stream

REPO = Path(__file__).resolve().parents[3]
INSTANCES = (
    "cn-prd-50c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
    "cn-prd-150c-01-V2-LOCATIONS",
)


def test_h0_g2_is_reproducible_independent_and_never_expired() -> None:
    for instance_id, expected in zip(INSTANCES, (10, 20, 30), strict=True):
        instance = load_china81_bundle(REPO, instance_id).instance
        first = build_h0_g2_stream(
            instance,
            instance_id=instance_id,
            stream_seed=1,
        )
        replay = build_h0_g2_stream(
            instance,
            instance_id=instance_id,
            stream_seed=1,
        )
        assert first == replay
        assert len(first.events) == expected
        assert len({event.t_appear for event in first.events}) == expected
        assert all(
            CHINA81_HORIZON_START_SECOND <= event.t_appear < event.new_ready_time
            and event.new_due_time <= CHINA81_HORIZON_END_SECOND
            for event in first.events
        )
