"""Independent dynamic-order disclosures inside the 06:00--22:00 horizon."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import random

from setp_solver.china81 import (
    CHINA81_HORIZON_END_SECOND,
    CHINA81_HORIZON_START_SECOND,
)
from setp_solver.instance_loader import Instance
from setp_solver.search.dynamic import DynamicEvent

DYNAMIC_ORDER_SHARE = 0.20


@dataclass(frozen=True)
class H0G2Stream:
    instance_id: str
    stream_seed: int
    initial_customer_ids: tuple[str, ...]
    events: tuple[DynamicEvent, ...]


def build_h0_g2_stream(
    instance: Instance,
    *,
    instance_id: str,
    stream_seed: int,
) -> H0G2Stream:
    """Reveal about 20% of existing orders independently before their windows."""

    customers = sorted(
        (node for node in instance.nodes if node.node_type.lower() == "c"),
        key=lambda node: node.node_id,
    )
    dynamic_count = round(len(customers) * DYNAMIC_ORDER_SHARE)
    eligible = [
        node
        for node in customers
        if float(node.ready_time) > CHINA81_HORIZON_START_SECOND
    ]
    if len(eligible) < dynamic_count:
        raise ValueError("not enough orders have a pre-window disclosure interval")

    seed_bytes = hashlib.sha256(
        f"{instance_id}:{int(stream_seed)}:E7-H0-G2".encode("utf-8")
    ).digest()
    rng = random.Random(int.from_bytes(seed_bytes[:8], "big"))
    rng.shuffle(eligible)
    selected = sorted(eligible[:dynamic_count], key=lambda node: node.node_id)

    events: list[DynamicEvent] = []
    for index, node in enumerate(selected, start=1):
        latest = min(float(node.ready_time), float(CHINA81_HORIZON_END_SECOND))
        appearance = rng.uniform(
            float(CHINA81_HORIZON_START_SECOND),
            math.nextafter(latest, -math.inf),
        )
        events.append(
            DynamicEvent(
                event_id=f"ADD_{index:03d}_{node.node_id}",
                event_type="add",
                t_appear=appearance,
                customer_id=node.node_id,
                old_demand=0.0,
                new_demand=float(node.demand),
                x=float(node.x),
                y=float(node.y),
                new_ready_time=float(node.ready_time),
                new_due_time=float(node.due_time),
                new_service_time=float(node.service_time),
                demand_source="china81_original_order",
                time_window_source="china81_original_order",
                service_time_source="china81_original_order",
                donor_customer_id=node.node_id,
                source="E7-H0-G2-independent-disclosure",
            )
        )

    events.sort(key=lambda event: (float(event.t_appear), str(event.event_id)))
    dynamic_ids = {event.customer_id for event in events}
    return H0G2Stream(
        instance_id=str(instance_id),
        stream_seed=int(stream_seed),
        initial_customer_ids=tuple(
            node.node_id for node in customers if node.node_id not in dynamic_ids
        ),
        events=tuple(events),
    )
