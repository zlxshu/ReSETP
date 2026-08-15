"""P34 A1 potential-market dynamic-order streams for China81.

The historical China81 stream hides orders from a table that already contains
the day's final customers.  This module instead treats one 150-customer
instance as a public potential market and samples a private 50- or 100-order
day from it.  The truth stream, the public algorithm view, and the algorithm's
internal scenario use separate random streams and separate data structures.

The constructed day inherits customer attributes from China81.  It is a
disclosed simulation scenario, not an observed order day.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import random
from statistics import fmean
from typing import Any, Protocol, Sequence

from .china81 import (
    CHINA81_HORIZON_START_SECOND,
    ENDOGENOUS_FLEET_PARAMETERS,
    China81Bundle,
)
from .instance_loader import Node


CONTRACT_ID = "P34_A1_POTENTIAL_MARKET_DYNAMIC_DAY_V1"
SCENARIO_CLASS = "constructed_potential_market_order_day"
TRIGGER_POLICY_ID = "qiu_500kg_or_30_minutes_protocol_transfer"
TRIGGER_INTERVAL_SECONDS = 30.0 * 60.0
DEMAND_THRESHOLD_KG = 500.0
RECEPTION_START_SECOND = 8.0 * 60.0 * 60.0
RECEPTION_END_SECOND = 10.0 * 60.0 * 60.0
DYNAMIC_ORDER_SHARE = 0.20
DYNAMIC_ORDER_SHARE_SOURCE = (
    "existing China81 H0-G2 disclosure share named in the P34 defect; "
    "only its sampling universe is replaced"
)
_TOL = 1.0e-9


@dataclass(frozen=True)
class TriggerProtocol:
    """The approved P10 E trigger rule and its provenance."""

    policy_id: str = TRIGGER_POLICY_ID
    interval_seconds: float = TRIGGER_INTERVAL_SECONDS
    demand_threshold_kg: float = DEMAND_THRESHOLD_KG
    reception_start_second: float = RECEPTION_START_SECOND
    reception_end_second: float = RECEPTION_END_SECOND
    source: str = (
        "Qiu Yingying thesis pp.23-24 eqs.3-2/3-3 and pp.47-56; "
        "30 minutes and 500 kg transferred as a simulation protocol"
    )


QIU_TRIGGER_PROTOCOL = TriggerProtocol()


@dataclass(frozen=True)
class PotentialPosition:
    potential_customer_id: str
    x: float
    y: float
    city: str | None


@dataclass(frozen=True)
class DemandDistribution:
    """Location-anonymous empirical demand distribution known in advance."""

    distribution_id: str
    source: str
    unit: str
    empirical_values_kg: tuple[float, ...]

    def as_dict(self, *, include_values: bool = True) -> dict[str, Any]:
        values = self.empirical_values_kg
        payload: dict[str, Any] = {
            "distribution_id": self.distribution_id,
            "source": self.source,
            "unit": self.unit,
            "count": len(values),
            "minimum": min(values),
            "q25": _linear_quantile(values, 0.25),
            "median": _linear_quantile(values, 0.50),
            "q75": _linear_quantile(values, 0.75),
            "maximum": max(values),
            "mean": fmean(values),
            "quantile_method": "linear interpolation over sorted values",
        }
        if include_values:
            payload["empirical_values_kg"] = list(values)
        return payload


@dataclass(frozen=True)
class AlgorithmScenarioOrder:
    """One future order sampled only from the public prior."""

    potential_customer_id: str
    sampled_demand_kg: float


@dataclass(frozen=True)
class DirectServiceOption:
    depot_id: str
    vehicle_type: str
    direct_travel_second: float
    payload_capacity_kg: float


@dataclass(frozen=True)
class ConstructedOrder:
    event_id: str
    customer_id: str
    appearance_second: float
    demand_kg: float
    x: float
    y: float
    city: str | None
    ready_second: float
    due_second: float
    service_second: float
    initially_visible: bool
    source_potential_customer_id: str
    order_attribute_source: str
    compatible_depot_id: str
    compatible_vehicle_type: str
    compatible_payload_capacity_kg: float
    direct_travel_second: float
    trigger_batch_index: int = 0
    trigger_second: float = 0.0
    trigger_cause: str = ""
    serviceable_at_reveal: bool = False
    serviceable_at_trigger: bool = False
    reveal_slack_second: float = 0.0
    trigger_slack_second: float = 0.0

    def as_visible_dict(self) -> dict[str, Any]:
        """Return fields that become known only after this order is revealed."""

        return {
            "event_id": self.event_id,
            "customer_id": self.customer_id,
            "appearance_second": self.appearance_second,
            "demand_kg": self.demand_kg,
            "x": self.x,
            "y": self.y,
            "city": self.city,
            "ready_second": self.ready_second,
            "due_second": self.due_second,
            "service_second": self.service_second,
            "initially_visible": self.initially_visible,
        }


class TriggerableOrder(Protocol):
    event_id: str
    customer_id: str
    appearance_second: float
    demand_kg: float


@dataclass(frozen=True)
class TriggerEvent:
    """Small public input type for testing or reusing the trigger rule."""

    event_id: str
    customer_id: str
    appearance_second: float
    demand_kg: float


@dataclass(frozen=True)
class TriggerBatch:
    policy_id: str
    batch_index: int
    trigger_second: float
    cause: str
    event_ids: tuple[str, ...]
    customer_ids: tuple[str, ...]
    demand_kg: float


@dataclass(frozen=True)
class ServiceabilityValidation:
    event_id: str
    customer_id: str
    reveal_arrival_second: float
    trigger_arrival_second: float
    due_second: float
    reveal_pass: bool
    trigger_pass: bool


@dataclass(frozen=True)
class ConstructedDynamicDay:
    """Private oracle truth plus a separately reproducible scenario stream."""

    contract_id: str
    scenario_class: str
    constructed_day_instance_id: str
    region: str
    potential_pool_instance_id: str
    fleet_authority_instance_id: str
    potential_pool_source_paths: tuple[tuple[str, str], ...]
    fleet_source_paths: tuple[tuple[str, str], ...]
    customer_count: int
    potential_customer_count: int
    initial_visible_order_count: int
    dynamic_order_count: int
    dynamic_order_share: float
    dynamic_order_share_source: str
    market_sampling_seed: int
    true_order_stream_seed: int
    algorithm_scenario_seed: int
    actual_random_stream_id: str
    algorithm_scenario_random_stream_id: str
    fleet_parameter_class_id: str
    fleet_caps_by_depot: tuple[tuple[str, int, int, int], ...]
    potential_positions: tuple[PotentialPosition, ...]
    demand_distribution: DemandDistribution
    actual_orders: tuple[ConstructedOrder, ...]
    trigger_batches: tuple[TriggerBatch, ...]
    algorithm_scenario_customer_ids: tuple[str, ...]
    algorithm_scenario_orders: tuple[AlgorithmScenarioOrder, ...]
    truth_stream_sha256: str
    algorithm_scenario_sha256: str
    trigger_protocol: TriggerProtocol


@dataclass(frozen=True)
class AlgorithmVisibleInformation:
    """Public information boundary presented to the online algorithm."""

    contract_id: str
    scenario_class: str
    region: str
    potential_pool_instance_id: str
    known_daily_order_count: int
    as_of_second: float
    potential_positions: tuple[PotentialPosition, ...]
    demand_distribution: DemandDistribution
    revealed_orders: tuple[dict[str, Any], ...]
    internal_scenario_seed: int
    internal_scenario_random_stream_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "scenario_class": self.scenario_class,
            "region": self.region,
            "potential_pool_instance_id": self.potential_pool_instance_id,
            "known_daily_order_count": self.known_daily_order_count,
            "as_of_second": self.as_of_second,
            "potential_positions": [
                asdict(position) for position in self.potential_positions
            ],
            "demand_distribution": self.demand_distribution.as_dict(),
            "revealed_orders": list(self.revealed_orders),
            "internal_scenario": {
                "seed": self.internal_scenario_seed,
                "random_stream_id": self.internal_scenario_random_stream_id,
                "sampling_rule": (
                    "sample independently from all registered potential positions"
                ),
            },
        }


def generate_constructed_dynamic_day(
    potential_pool: China81Bundle,
    fleet_authority: China81Bundle,
    *,
    customer_count: int,
    market_sampling_seed: int,
    true_order_stream_seed: int,
    algorithm_scenario_seed: int,
    trigger_protocol: TriggerProtocol = QIU_TRIGGER_PROTOCOL,
) -> ConstructedDynamicDay:
    """Generate one private truth day and one independent internal scenario.

    The selected truth ids and truth seeds never enter
    :func:`algorithm_visible_information`.
    """

    customers = tuple(
        sorted(
            (
                node
                for node in potential_pool.instance.nodes
                if node.node_type.lower() == "c"
            ),
            key=lambda node: node.node_id,
        )
    )
    fleet_customers = tuple(
        node
        for node in fleet_authority.instance.nodes
        if node.node_type.lower() == "c"
    )
    _validate_inputs(
        potential_pool,
        fleet_authority,
        customers=customers,
        fleet_customer_count=len(fleet_customers),
        customer_count=customer_count,
        trigger_protocol=trigger_protocol,
    )

    positions = tuple(
        PotentialPosition(
            potential_customer_id=node.node_id,
            x=float(node.x),
            y=float(node.y),
            city=node.city,
        )
        for node in customers
    )
    distribution = DemandDistribution(
        distribution_id=(
            f"{potential_pool.instance_id}__location_anonymous_empirical_demand"
        ),
        source=(
            "constructed prior from the sorted demand multiset in the "
            "registered 150-position China81 potential pool"
        ),
        unit="kg",
        empirical_values_kg=tuple(
            sorted(float(node.demand) for node in customers)
        ),
    )

    selection_rng = _independent_rng(
        market_sampling_seed,
        potential_pool.instance_id,
        customer_count,
        "private-actual-customer-selection",
    )
    selected_ids = {
        node.node_id
        for node in selection_rng.sample(list(customers), customer_count)
    }
    selected_nodes = tuple(
        node for node in customers if node.node_id in selected_ids
    )

    truth_rng = _independent_rng(
        true_order_stream_seed,
        potential_pool.instance_id,
        customer_count,
        "private-actual-reveal-times",
    )
    dynamic_count = round(customer_count * DYNAMIC_ORDER_SHARE)
    dynamic_ids = {
        node.node_id
        for node in truth_rng.sample(list(selected_nodes), dynamic_count)
    }
    draft_orders: list[ConstructedOrder] = []
    initial_index = 0
    dynamic_index = 0
    for node in selected_nodes:
        option = _shortest_compatible_direct_option(
            potential_pool,
            fleet_authority,
            node,
        )
        initially_visible = node.node_id not in dynamic_ids
        if initially_visible:
            initial_index += 1
            event_id = f"INITIAL_{initial_index:03d}_{node.node_id}"
            appearance = float(CHINA81_HORIZON_START_SECOND)
        else:
            dynamic_index += 1
            event_id = f"ADD_{dynamic_index:03d}_{node.node_id}"
            latest_after_maximum_wait = (
                float(node.due_time)
                - option.direct_travel_second
                - trigger_protocol.interval_seconds
            )
            latest_reveal = min(
                math.nextafter(
                    trigger_protocol.reception_end_second,
                    -math.inf,
                ),
                latest_after_maximum_wait,
            )
            if latest_reveal < trigger_protocol.reception_start_second - _TOL:
                raise ValueError(
                    f"sampled order {node.node_id} has no reveal time that "
                    "remains directly serviceable after the approved maximum "
                    "trigger wait"
                )
            appearance = truth_rng.uniform(
                trigger_protocol.reception_start_second,
                latest_reveal,
            )
        draft_orders.append(
            ConstructedOrder(
                event_id=event_id,
                customer_id=node.node_id,
                appearance_second=float(appearance),
                demand_kg=float(node.demand),
                x=float(node.x),
                y=float(node.y),
                city=node.city,
                ready_second=float(node.ready_time),
                due_second=float(node.due_time),
                service_second=float(node.service_time),
                initially_visible=initially_visible,
                source_potential_customer_id=node.node_id,
                order_attribute_source=(
                    f"{potential_pool.instance_id}: registered constructed "
                    "China81 potential-customer attributes"
                ),
                compatible_depot_id=option.depot_id,
                compatible_vehicle_type=option.vehicle_type,
                compatible_payload_capacity_kg=option.payload_capacity_kg,
                direct_travel_second=option.direct_travel_second,
            )
        )

    draft_orders.sort(
        key=lambda order: (order.appearance_second, order.event_id)
    )
    batches = build_trigger_batches(
        [order for order in draft_orders if not order.initially_visible],
        trigger_protocol,
    )
    batch_by_event = {
        event_id: batch
        for batch in batches
        for event_id in batch.event_ids
    }
    actual_orders: list[ConstructedOrder] = []
    for order in draft_orders:
        batch = batch_by_event.get(order.event_id)
        trigger_second = (
            order.appearance_second
            if batch is None
            else batch.trigger_second
        )
        reveal_slack = (
            order.due_second
            - order.appearance_second
            - order.direct_travel_second
        )
        trigger_slack = (
            order.due_second
            - trigger_second
            - order.direct_travel_second
        )
        actual_orders.append(
            replace(
                order,
                trigger_batch_index=(0 if batch is None else batch.batch_index),
                trigger_second=trigger_second,
                trigger_cause=(
                    "initial_visibility" if batch is None else batch.cause
                ),
                serviceable_at_reveal=reveal_slack >= -_TOL,
                serviceable_at_trigger=trigger_slack >= -_TOL,
                reveal_slack_second=reveal_slack,
                trigger_slack_second=trigger_slack,
            )
        )

    scenario_orders = _sample_algorithm_scenario_from_prior(
        potential_pool_instance_id=potential_pool.instance_id,
        customer_count=customer_count,
        positions=positions,
        demand_distribution=distribution,
        scenario_seed=algorithm_scenario_seed,
        revealed_customer_ids={
            order.customer_id
            for order in actual_orders
            if order.initially_visible
        },
    )
    scenario_ids = tuple(
        order.potential_customer_id for order in scenario_orders
    )
    truth_hash = _payload_sha256(
        [asdict(order) for order in actual_orders]
    )
    scenario_hash = _payload_sha256(
        [asdict(order) for order in scenario_orders]
    )
    private_identity_hash = _payload_sha256(
        {
            "potential_pool_instance_id": potential_pool.instance_id,
            "customer_count": customer_count,
            "market_sampling_seed": int(market_sampling_seed),
            "true_order_stream_seed": int(true_order_stream_seed),
            "truth_stream_sha256": truth_hash,
        }
    )
    day = ConstructedDynamicDay(
        contract_id=CONTRACT_ID,
        scenario_class=SCENARIO_CLASS,
        constructed_day_instance_id=(
            f"{potential_pool.instance_id}__constructed-{customer_count}c-day__"
            f"{private_identity_hash[:16]}"
        ),
        region=potential_pool.region,
        potential_pool_instance_id=potential_pool.instance_id,
        fleet_authority_instance_id=fleet_authority.instance_id,
        potential_pool_source_paths=tuple(
            sorted(potential_pool.source_paths.items())
        ),
        fleet_source_paths=tuple(
            sorted(fleet_authority.source_paths.items())
        ),
        customer_count=customer_count,
        potential_customer_count=len(customers),
        initial_visible_order_count=customer_count - dynamic_count,
        dynamic_order_count=dynamic_count,
        dynamic_order_share=DYNAMIC_ORDER_SHARE,
        dynamic_order_share_source=DYNAMIC_ORDER_SHARE_SOURCE,
        market_sampling_seed=int(market_sampling_seed),
        true_order_stream_seed=int(true_order_stream_seed),
        algorithm_scenario_seed=int(algorithm_scenario_seed),
        actual_random_stream_id=(
            f"{CONTRACT_ID}:private-actual-selection-and-reveal"
        ),
        algorithm_scenario_random_stream_id=(
            f"{CONTRACT_ID}:algorithm-internal-future-scenario"
        ),
        fleet_parameter_class_id=fleet_authority.fleet_parameter_class_id,
        fleet_caps_by_depot=tuple(
            (
                depot_id,
                int(caps["num_cv"]),
                int(caps["num_ev"]),
                int(caps["total_fleet_cap"]),
            )
            for depot_id, caps in sorted(
                fleet_authority.fleet_caps_by_depot.items()
            )
        ),
        potential_positions=positions,
        demand_distribution=distribution,
        actual_orders=tuple(actual_orders),
        trigger_batches=batches,
        algorithm_scenario_customer_ids=scenario_ids,
        algorithm_scenario_orders=scenario_orders,
        truth_stream_sha256=truth_hash,
        algorithm_scenario_sha256=scenario_hash,
        trigger_protocol=trigger_protocol,
    )
    validations = validate_day_serviceability(day)
    if not validations or not all(
        item.reveal_pass and item.trigger_pass for item in validations
    ):
        raise AssertionError(
            "constructed dynamic day failed direct serviceability validation"
        )
    return day


def algorithm_visible_information(
    day: ConstructedDynamicDay,
    *,
    as_of_second: float,
) -> AlgorithmVisibleInformation:
    """Return only public prior information and orders revealed by ``as_of``."""

    timestamp = float(as_of_second)
    if not math.isfinite(timestamp):
        raise ValueError("algorithm-view timestamp must be finite")
    revealed = tuple(
        order.as_visible_dict()
        for order in day.actual_orders
        if order.appearance_second <= timestamp + _TOL
    )
    return AlgorithmVisibleInformation(
        contract_id=day.contract_id,
        scenario_class=day.scenario_class,
        region=day.region,
        potential_pool_instance_id=day.potential_pool_instance_id,
        known_daily_order_count=day.customer_count,
        as_of_second=timestamp,
        potential_positions=day.potential_positions,
        demand_distribution=day.demand_distribution,
        revealed_orders=revealed,
        internal_scenario_seed=day.algorithm_scenario_seed,
        internal_scenario_random_stream_id=(
            day.algorithm_scenario_random_stream_id
        ),
    )


def sample_algorithm_internal_scenario(
    visible_information: AlgorithmVisibleInformation,
) -> tuple[AlgorithmScenarioOrder, ...]:
    """Reproduce an internal scenario using public information only."""

    return _sample_algorithm_scenario_from_prior(
        potential_pool_instance_id=(
            visible_information.potential_pool_instance_id
        ),
        customer_count=visible_information.known_daily_order_count,
        positions=visible_information.potential_positions,
        demand_distribution=visible_information.demand_distribution,
        scenario_seed=visible_information.internal_scenario_seed,
        revealed_customer_ids={
            str(order["customer_id"])
            for order in visible_information.revealed_orders
        },
    )


def build_trigger_batches(
    orders: Sequence[TriggerableOrder],
    protocol: TriggerProtocol = QIU_TRIGGER_PROTOCOL,
) -> tuple[TriggerBatch, ...]:
    """Apply the approved demand-mass-or-maximum-wait trigger rule."""

    ordered = sorted(
        orders,
        key=lambda order: (float(order.appearance_second), str(order.event_id)),
    )
    if len({str(order.event_id) for order in ordered}) != len(ordered):
        raise ValueError("dynamic order event ids must be unique")
    for order in ordered:
        if not (
            protocol.reception_start_second
            <= float(order.appearance_second)
            < protocol.reception_end_second
        ):
            raise ValueError(
                f"event {order.event_id} appears outside the registered window"
            )
        if not math.isfinite(float(order.demand_kg)) or order.demand_kg <= 0.0:
            raise ValueError(f"event {order.event_id} has invalid demand")

    batches: list[TriggerBatch] = []
    pending: list[TriggerableOrder] = []
    cursor = 0
    deadline = (
        protocol.reception_start_second + protocol.interval_seconds
    )
    while cursor < len(ordered):
        appearance = float(ordered[cursor].appearance_second)
        while deadline < appearance - _TOL:
            if pending:
                batches.append(
                    _trigger_batch(
                        protocol,
                        len(batches) + 1,
                        deadline,
                        "maximum_wait",
                        pending,
                    )
                )
                pending = []
            deadline = min(
                deadline + protocol.interval_seconds,
                protocol.reception_end_second,
            )

        while (
            cursor < len(ordered)
            and abs(
                float(ordered[cursor].appearance_second) - appearance
            )
            <= _TOL
        ):
            pending.append(ordered[cursor])
            cursor += 1

        cumulative_demand = sum(
            float(order.demand_kg) for order in pending
        )
        if cumulative_demand >= protocol.demand_threshold_kg - _TOL:
            batches.append(
                _trigger_batch(
                    protocol,
                    len(batches) + 1,
                    appearance,
                    "demand_threshold",
                    pending,
                )
            )
            pending = []
            deadline = min(
                appearance + protocol.interval_seconds,
                protocol.reception_end_second,
            )
        elif abs(appearance - deadline) <= _TOL:
            batches.append(
                _trigger_batch(
                    protocol,
                    len(batches) + 1,
                    deadline,
                    "maximum_wait",
                    pending,
                )
            )
            pending = []
            deadline = min(
                deadline + protocol.interval_seconds,
                protocol.reception_end_second,
            )

    if pending:
        trigger = min(deadline, protocol.reception_end_second)
        batches.append(
            _trigger_batch(
                protocol,
                len(batches) + 1,
                trigger,
                (
                    "window_end"
                    if trigger == protocol.reception_end_second
                    else "maximum_wait"
                ),
                pending,
            )
        )

    consumed = [event_id for batch in batches for event_id in batch.event_ids]
    expected = [str(order.event_id) for order in ordered]
    if sorted(consumed) != sorted(expected):
        raise AssertionError("trigger rule did not consume every event exactly once")
    return tuple(batches)


def validate_day_serviceability(
    day: ConstructedDynamicDay,
) -> tuple[ServiceabilityValidation, ...]:
    """Recompute reveal- and trigger-time direct-service inequalities."""

    return tuple(
        ServiceabilityValidation(
            event_id=order.event_id,
            customer_id=order.customer_id,
            reveal_arrival_second=(
                order.appearance_second + order.direct_travel_second
            ),
            trigger_arrival_second=(
                order.trigger_second + order.direct_travel_second
            ),
            due_second=order.due_second,
            reveal_pass=(
                order.appearance_second + order.direct_travel_second
                <= order.due_second + _TOL
            ),
            trigger_pass=(
                order.trigger_second + order.direct_travel_second
                <= order.due_second + _TOL
            ),
        )
        for order in day.actual_orders
    )


def demand_summary(values: Sequence[float]) -> dict[str, float | int | str]:
    """Return the report-ready distribution used by the sample generator."""

    ordered = tuple(sorted(float(value) for value in values))
    if not ordered:
        raise ValueError("demand summary requires at least one value")
    return {
        "count": len(ordered),
        "minimum_kg": min(ordered),
        "q25_kg": _linear_quantile(ordered, 0.25),
        "median_kg": _linear_quantile(ordered, 0.50),
        "q75_kg": _linear_quantile(ordered, 0.75),
        "maximum_kg": max(ordered),
        "mean_kg": fmean(ordered),
        "total_kg": sum(ordered),
        "quantile_method": "linear interpolation over sorted values",
    }


def _validate_inputs(
    potential_pool: China81Bundle,
    fleet_authority: China81Bundle,
    *,
    customers: Sequence[Node],
    fleet_customer_count: int,
    customer_count: int,
    trigger_protocol: TriggerProtocol,
) -> None:
    if len(customers) != 150:
        raise ValueError("P34 A1 potential market must contain exactly 150 customers")
    if customer_count not in {50, 100}:
        raise ValueError("P34 A1 constructed days support 50 or 100 orders")
    if fleet_customer_count != customer_count:
        raise ValueError(
            "fleet authority must come from the corresponding daily order scale"
        )
    if potential_pool.region != fleet_authority.region:
        raise ValueError("potential pool and fleet authority regions differ")
    if (
        fleet_authority.fleet_parameter_class_id
        != ENDOGENOUS_FLEET_PARAMETERS.parameter_class_id
        or fleet_authority.has_additional_total_fleet_cap
    ):
        raise ValueError(
            "P34 A1 requires the approved endogenous Rd/Re fleet parameter class"
        )
    if trigger_protocol != QIU_TRIGGER_PROTOCOL:
        raise ValueError(
            "P34 A1 generator accepts only the user-approved P10 E protocol"
        )


def _shortest_compatible_direct_option(
    potential_pool: China81Bundle,
    fleet_authority: China81Bundle,
    customer: Node,
) -> DirectServiceOption:
    depots = {
        node.node_id: node
        for node in potential_pool.instance.nodes
        if node.node_type.lower() == "d"
    }
    options: list[DirectServiceOption] = []
    for depot_id, caps in fleet_authority.fleet_caps_by_depot.items():
        if depot_id not in depots:
            continue
        for vehicle_type in ("cv", "ev"):
            if int(caps[f"num_{vehicle_type}"]) < 1:
                continue
            parameters = potential_pool.instance.vehicle_profile(vehicle_type)
            if parameters is None:
                continue
            payload = float(parameters.payload_capacity_kg)
            if float(customer.demand) > payload + _TOL:
                continue
            _, travel, _ = potential_pool.instance.arc_metrics(
                depot_id,
                customer.node_id,
                vehicle_type,
                fallback_speed_mps=1.0,
            )
            options.append(
                DirectServiceOption(
                    depot_id=depot_id,
                    vehicle_type=vehicle_type,
                    direct_travel_second=float(travel),
                    payload_capacity_kg=payload,
                )
            )
    if not options:
        raise ValueError(
            f"potential customer {customer.node_id} has no compatible direct depot"
        )
    return min(
        options,
        key=lambda option: (
            option.direct_travel_second,
            option.depot_id,
            option.vehicle_type,
        ),
    )


def _trigger_batch(
    protocol: TriggerProtocol,
    index: int,
    trigger_second: float,
    cause: str,
    orders: Sequence[TriggerableOrder],
) -> TriggerBatch:
    ordered = sorted(
        orders,
        key=lambda order: (float(order.appearance_second), str(order.event_id)),
    )
    return TriggerBatch(
        policy_id=protocol.policy_id,
        batch_index=int(index),
        trigger_second=float(trigger_second),
        cause=str(cause),
        event_ids=tuple(str(order.event_id) for order in ordered),
        customer_ids=tuple(str(order.customer_id) for order in ordered),
        demand_kg=sum(float(order.demand_kg) for order in ordered),
    )


def _independent_rng(
    seed: int,
    potential_pool_instance_id: str,
    customer_count: int,
    stream_name: str,
) -> random.Random:
    material = json.dumps(
        {
            "contract_id": CONTRACT_ID,
            "potential_pool_instance_id": potential_pool_instance_id,
            "customer_count": int(customer_count),
            "stream_name": str(stream_name),
            "seed": int(seed),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))


def _sample_algorithm_scenario_from_prior(
    *,
    potential_pool_instance_id: str,
    customer_count: int,
    positions: Sequence[PotentialPosition],
    demand_distribution: DemandDistribution,
    scenario_seed: int,
    revealed_customer_ids: set[str],
) -> tuple[AlgorithmScenarioOrder, ...]:
    if customer_count > len(positions):
        raise ValueError("internal scenario is larger than the potential pool")
    remaining_count = customer_count - len(revealed_customer_ids)
    if remaining_count < 0:
        raise ValueError("revealed order count exceeds the registered day size")
    available_positions = [
        position
        for position in positions
        if position.potential_customer_id not in revealed_customer_ids
    ]
    if remaining_count > len(available_positions):
        raise ValueError("internal scenario exceeds unrevealed potential positions")
    values = demand_distribution.empirical_values_kg
    if remaining_count > len(values):
        raise ValueError("internal scenario is larger than the demand prior")
    rng = _independent_rng(
        scenario_seed,
        potential_pool_instance_id,
        customer_count,
        "algorithm-internal-future-scenario",
    )
    selected_ids = sorted(
        position.potential_customer_id
        for position in rng.sample(available_positions, remaining_count)
    )
    sampled_demands = rng.sample(list(values), remaining_count)
    return tuple(
        AlgorithmScenarioOrder(
            potential_customer_id=customer_id,
            sampled_demand_kg=float(demand),
        )
        for customer_id, demand in zip(
            selected_ids,
            sampled_demands,
            strict=True,
        )
    )


def _payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _linear_quantile(values: Sequence[float], probability: float) -> float:
    ordered = tuple(sorted(float(value) for value in values))
    if not ordered:
        raise ValueError("quantile requires at least one value")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("quantile probability must be in [0, 1]")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])
