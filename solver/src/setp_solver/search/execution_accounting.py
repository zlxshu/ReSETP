"""Execution accounting that books certified whole trips exactly once.

Dynamic replanning must not turn already served customers into artificial
``depot-customer-depot`` fragments for reporting.  Doing so changes distance,
fixed dispatch cost, fuel use, emissions, and profit even when the physical
trip did not change.  This module keeps the complete source ``Route`` as the
accounting unit and accepts it only when a matching :class:`TripExecution`
witness says that the trip has started or completed.

The ledger is deliberately independent from the dynamic scheduler.  It does
not modify routes, infer missing arcs, or run a search.  Re-registering the
same certified route is idempotent; changing any already-booked route or
booking the same customer twice is a hard error.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, Mapping

from ..cost import _price, evaluate
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import Route, Solution, physical_vehicle_id
from .certificate_execution import (
    COMPLETED,
    IN_PROGRESS,
    NOT_STARTED,
    CertificateExecutionLedger,
    TripExecution,
)


EXECUTION_ACCOUNTING_CONTRACT_ID = "E7_WHOLE_TRIP_EXECUTION_ACCOUNTING_V1"
ACCOUNTING_TOLERANCE = 1e-6

_COST_FIELDS = (
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_transship",
    "cost_carbon",
)
_ADDITIVE_FIELDS = (
    *_COST_FIELDS,
    "distance_total",
    "distance_cv",
    "distance_ev",
    "fuel_liters",
    "electricity_kwh",
    "depot_charging_kwh",
    "station_charging_kwh",
    "ev_drive_kwh",
    "E_total",
    "E_cv_direct",
    "E_ev_indirect",
    "revenue",
    "demand_kg",
)


@dataclass(frozen=True)
class ExecutionTotals:
    """Seven cost items and their physical/revenue accounting witnesses."""

    cost_fix: float
    cost_km: float
    cost_fuel: float
    cost_elec: float
    cost_occ: float
    cost_transship: float
    cost_carbon: float
    total_cost: float
    distance_total: float
    distance_cv: float
    distance_ev: float
    fuel_liters: float
    electricity_kwh: float
    depot_charging_kwh: float
    station_charging_kwh: float
    ev_drive_kwh: float
    E_total: float
    E_cv_direct: float
    E_ev_indirect: float
    revenue: float
    demand_kg: float
    customers_served: int
    realized_profit: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class BookedTrip:
    """One original certified route, never a reconstructed customer fragment."""

    route_id: str
    route_signature: str
    accounting_source_sha256: str
    physical_vehicle_id: str
    trip_index: int
    vehicle_type: str
    home_depot_id: str
    execution_state: str
    customer_ids: tuple[str, ...]
    totals: ExecutionTotals


@dataclass(frozen=True)
class ExecutionAccountingSummary:
    contract_id: str
    booked_route_count: int
    booked_customer_count: int
    trips: Mapping[str, BookedTrip]
    by_depot: Mapping[str, ExecutionTotals]
    system: ExecutionTotals


@dataclass(frozen=True)
class _TripBase:
    execution: TripExecution
    execution_state: str
    route: Route
    customer_ids: tuple[str, ...]
    accounting_source_sha256: str
    values: Mapping[str, float]


class ExecutionAccountingLedger:
    """Incremental whole-trip cost/revenue ledger for a certified solution."""

    def __init__(
        self,
        source_solution: Solution,
        instance: Instance,
        carbon_profile: list[dict[str, Any]],
        prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
        *,
        carbon_quota_kg: float = 0.0,
        revenue_per_kg: float | None = None,
    ) -> None:
        route_ids = [route.vehicle_id for route in source_solution.routes]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError(f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: source solution has duplicate route ids")
        self._solution = source_solution
        self._instance = instance
        self._carbon_profile = carbon_profile
        self._prices = prices
        self._carbon_quota_kg = float(carbon_quota_kg)
        self._revenue_per_kg = (
            _price(prices, "revenue_per_kg")
            if revenue_per_kg is None
            else float(revenue_per_kg)
        )
        self._routes = {route.vehicle_id: route for route in source_solution.routes}
        self._nodes = {node.node_id: node for node in instance.nodes}
        self._actions_by_route: dict[str, list[Any]] = {route_id: [] for route_id in route_ids}
        for action in source_solution.charging_actions:
            if action.vehicle_id not in self._routes:
                raise ValueError(
                    f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: charging action is detached "
                    f"from source route {action.vehicle_id}"
                )
            self._actions_by_route[action.vehicle_id].append(action)

        all_customers = {
            node_id
            for route in source_solution.routes
            for node_id in route.node_sequence
            if self._is_customer(node_id)
        }
        self._cross_by_customer: dict[str, Any] = {}
        for service in source_solution.cross_site_services:
            if service.customer_id in self._cross_by_customer:
                raise ValueError(
                    f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: duplicate cross-site record "
                    f"for customer {service.customer_id}"
                )
            if service.customer_id not in all_customers:
                raise ValueError(
                    f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: cross-site customer "
                    f"{service.customer_id} is absent from every source route"
                )
            self._cross_by_customer[service.customer_id] = service

        self._records: dict[str, _TripBase] = {}
        self._customer_claims: dict[str, str] = {}

    @property
    def booked_route_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._records))

    def register_trip(self, execution: TripExecution, *, at_second: float) -> bool:
        """Book one started/completed trip; return ``True`` only on first booking.

        A trip becomes an indivisible accounting commitment at departure.  A
        later call at/after return may upgrade its state to ``completed`` but
        never adds its costs or customer revenue a second time.
        """

        state = execution.state_at(float(at_second))
        if state == NOT_STARTED:
            raise ValueError(
                f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: route {execution.route_id} "
                "has not departed and cannot be booked"
            )
        if state not in {IN_PROGRESS, COMPLETED}:
            raise ValueError(f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: unsupported execution state {state}")

        try:
            route = self._routes[execution.route_id]
        except KeyError as exc:
            raise ValueError(
                f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: certified route "
                f"{execution.route_id} is absent from the complete source solution"
            ) from exc
        self._validate_binding(execution, route)
        customer_ids = self._route_customers(route)
        source_signature = self._accounting_source_sha256(execution, route, customer_ids)

        existing = self._records.get(execution.route_id)
        if existing is not None:
            if existing.execution.route_signature != execution.route_signature:
                raise ValueError(
                    f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: booked route "
                    f"{execution.route_id} changed signature"
                )
            if existing.accounting_source_sha256 != source_signature:
                raise ValueError(
                    f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: booked route "
                    f"{execution.route_id} changed accounting evidence"
                )
            if existing.execution_state == IN_PROGRESS and state == COMPLETED:
                self._records[execution.route_id] = replace(existing, execution_state=COMPLETED)
            return False

        duplicates_within_trip = sorted({customer for customer in customer_ids if customer_ids.count(customer) > 1})
        if duplicates_within_trip:
            raise ValueError(
                f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: route {execution.route_id} "
                f"would book customer revenue more than once: {duplicates_within_trip}"
            )
        duplicate_claims = {
            customer: self._customer_claims[customer]
            for customer in customer_ids
            if customer in self._customer_claims
        }
        if duplicate_claims:
            raise ValueError(
                f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: duplicate customer revenue claim "
                f"for route {execution.route_id}: {duplicate_claims}"
            )

        route_cross = []
        for customer_id in customer_ids:
            service = self._cross_by_customer.get(customer_id)
            if service is None:
                continue
            if service.served_by_depot_id != route.home_depot_id:
                raise ValueError(
                    f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: cross-site service depot "
                    f"for {customer_id} disagrees with route {route.vehicle_id}"
                )
            route_cross.append(service)
        route_solution = Solution(
            routes=[route],
            charging_actions=list(self._actions_by_route[route.vehicle_id]),
            cross_site_services=route_cross,
        )
        # Carbon quota is a system-level term.  Evaluate every complete trip
        # with the no-trading sentinel, then allocate the one aggregate carbon
        # term in ``summary``.
        evaluated = evaluate(
            route_solution,
            self._instance,
            self._carbon_profile,
            self._prices,
            carbon_quota_kg=math.inf,
        )
        revenue = sum(float(self._nodes[customer].demand) for customer in customer_ids) * self._revenue_per_kg
        demand = sum(float(self._nodes[customer].demand) for customer in customer_ids)
        values = {
            field: float(evaluated[field])
            for field in _ADDITIVE_FIELDS
            if field not in {"cost_carbon", "revenue", "demand_kg"}
        }
        values.update(
            {
                "cost_carbon": 0.0,
                "revenue": float(revenue),
                "demand_kg": float(demand),
            }
        )
        self._records[execution.route_id] = _TripBase(
            execution=execution,
            execution_state=state,
            route=route,
            customer_ids=customer_ids,
            accounting_source_sha256=source_signature,
            values=MappingProxyType(values),
        )
        for customer_id in customer_ids:
            self._customer_claims[customer_id] = execution.route_id
        return True

    def register_started_or_completed(
        self,
        execution_ledger: CertificateExecutionLedger,
        *,
        at_second: float,
    ) -> tuple[str, ...]:
        """Book every certified route that has departed by ``at_second``."""

        added: list[str] = []
        for execution in sorted(
            execution_ledger.routes.values(),
            key=lambda trip: (trip.departure_second, trip.route_id),
        ):
            if execution.state_at(float(at_second)) == NOT_STARTED:
                continue
            if self.register_trip(execution, at_second=at_second):
                added.append(execution.route_id)
        return tuple(added)

    def summary(self) -> ExecutionAccountingSummary:
        """Return an immutable system/depot/trip snapshot and verify closure."""

        carbon_shares = self._carbon_cost_shares()
        trips: dict[str, BookedTrip] = {}
        for route_id, base in sorted(self._records.items()):
            values = dict(base.values)
            values["cost_carbon"] = carbon_shares.get(route_id, 0.0)
            totals = _make_totals(values, len(base.customer_ids))
            trips[route_id] = BookedTrip(
                route_id=route_id,
                route_signature=base.execution.route_signature,
                accounting_source_sha256=base.accounting_source_sha256,
                physical_vehicle_id=base.execution.physical_vehicle_id,
                trip_index=base.execution.trip_index,
                vehicle_type=base.execution.vehicle_type,
                home_depot_id=base.execution.home_depot_id,
                execution_state=base.execution_state,
                customer_ids=base.customer_ids,
                totals=totals,
            )

        by_depot_lists: dict[str, list[ExecutionTotals]] = {}
        for trip in trips.values():
            by_depot_lists.setdefault(trip.home_depot_id, []).append(trip.totals)
        by_depot = {
            depot_id: _sum_totals(rows)
            for depot_id, rows in sorted(by_depot_lists.items())
        }
        system = _sum_totals([trip.totals for trip in trips.values()])
        self._assert_reference_cost_closure(system)
        _assert_depot_closure(system, by_depot)
        return ExecutionAccountingSummary(
            contract_id=EXECUTION_ACCOUNTING_CONTRACT_ID,
            booked_route_count=len(trips),
            booked_customer_count=len(self._customer_claims),
            trips=MappingProxyType(trips),
            by_depot=MappingProxyType(by_depot),
            system=system,
        )

    def _validate_binding(self, execution: TripExecution, route: Route) -> None:
        expected_signature = whole_route_signature(route)
        if execution.route_signature != expected_signature:
            raise ValueError(
                f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: route {route.vehicle_id} "
                "does not match its certified whole-route signature"
            )
        if execution.route_id != route.vehicle_id:
            raise ValueError(f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: route id binding changed")
        if execution.physical_vehicle_id != physical_vehicle_id(route.vehicle_id):
            raise ValueError(f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: physical vehicle binding changed")
        if execution.vehicle_type.lower() != route.vehicle_type.lower():
            raise ValueError(f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: vehicle type binding changed")
        if execution.home_depot_id != route.home_depot_id:
            raise ValueError(f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: home depot binding changed")

    def _route_customers(self, route: Route) -> tuple[str, ...]:
        unknown = [node_id for node_id in route.node_sequence if node_id not in self._nodes]
        if unknown:
            raise ValueError(
                f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: route {route.vehicle_id} has unknown nodes {unknown}"
            )
        return tuple(node_id for node_id in route.node_sequence if self._is_customer(node_id))

    def _is_customer(self, node_id: str) -> bool:
        node = self._nodes.get(node_id)
        return node is not None and node.node_type.lower() == "c"

    def _accounting_source_sha256(
        self,
        execution: TripExecution,
        route: Route,
        customer_ids: tuple[str, ...],
    ) -> str:
        actions = sorted(
            (
                action.vehicle_id,
                action.station_id,
                float(action.energy_kwh),
                float(action.occupancy_minutes),
                float(action.charge_start_second),
                int(action.charge_day_offset),
            )
            for action in self._actions_by_route[route.vehicle_id]
        )
        cross = sorted(
            (service.customer_id, service.served_by_depot_id)
            for customer_id in customer_ids
            if (service := self._cross_by_customer.get(customer_id)) is not None
        )
        return _canonical_sha256(
            {
                "route_signature": execution.route_signature,
                "physical_vehicle_id": execution.physical_vehicle_id,
                "trip_index": execution.trip_index,
                "vehicle_type": execution.vehicle_type.lower(),
                "home_depot_id": execution.home_depot_id,
                "departure_second": execution.departure_second,
                "return_second": execution.return_second,
                "drive_energy_kwh": execution.drive_energy_kwh,
                "charging_actions": actions,
                "cross_site_services": cross,
            }
        )

    def _carbon_cost_shares(self) -> dict[str, float]:
        if not self._records:
            return {}
        emissions = {
            route_id: float(record.values["E_total"])
            for route_id, record in self._records.items()
        }
        total_emissions = sum(emissions.values())
        carbon_cost = (
            0.0
            if math.isinf(self._carbon_quota_kg)
            else (total_emissions - self._carbon_quota_kg) * _price(self._prices, "carbon_price")
        )
        route_ids = sorted(self._records)
        if abs(total_emissions) <= ACCOUNTING_TOLERANCE:
            return {
                route_id: carbon_cost if index == 0 else 0.0
                for index, route_id in enumerate(route_ids)
            }
        shares: dict[str, float] = {}
        remaining = carbon_cost
        for route_id in route_ids[:-1]:
            share = carbon_cost * emissions[route_id] / total_emissions
            shares[route_id] = share
            remaining -= share
        shares[route_ids[-1]] = remaining
        return shares

    def _assert_reference_cost_closure(self, system: ExecutionTotals) -> None:
        booked = set(self._records)
        customers = set(self._customer_claims)
        subset = Solution(
            routes=[route for route in self._solution.routes if route.vehicle_id in booked],
            charging_actions=[
                action
                for action in self._solution.charging_actions
                if action.vehicle_id in booked
            ],
            cross_site_services=[
                service
                for service in self._solution.cross_site_services
                if service.customer_id in customers
            ],
        )
        expected = evaluate(
            subset,
            self._instance,
            self._carbon_profile,
            self._prices,
            carbon_quota_kg=self._carbon_quota_kg,
        )
        for field in (
            *_COST_FIELDS,
            "distance_total",
            "distance_cv",
            "distance_ev",
            "fuel_liters",
            "electricity_kwh",
            "depot_charging_kwh",
            "station_charging_kwh",
            "ev_drive_kwh",
            "E_total",
            "E_cv_direct",
            "E_ev_indirect",
        ):
            if abs(float(getattr(system, field)) - float(expected[field])) > ACCOUNTING_TOLERANCE:
                raise ValueError(
                    f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: system {field} does not "
                    "close to full-route evaluation"
                )
        if abs(system.total_cost - float(expected["total_cost"])) > ACCOUNTING_TOLERANCE:
            raise ValueError(
                f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: system total cost does not "
                "close to full-route evaluation"
            )


def whole_route_signature(route: Route) -> str:
    """Return the same stable whole-route signature used by the clock ledger."""

    return _canonical_sha256(
        {
            "route_id": route.vehicle_id,
            "vehicle_type": route.vehicle_type.lower(),
            "home_depot_id": route.home_depot_id,
            "node_sequence": list(route.node_sequence),
        }
    )


def _make_totals(values: Mapping[str, float], customers_served: int) -> ExecutionTotals:
    normalized = {field: float(values.get(field, 0.0)) for field in _ADDITIVE_FIELDS}
    total_cost = sum(normalized[field] for field in _COST_FIELDS)
    revenue = normalized["revenue"]
    return ExecutionTotals(
        **normalized,
        total_cost=total_cost,
        customers_served=int(customers_served),
        realized_profit=revenue - total_cost,
    )


def _sum_totals(rows: list[ExecutionTotals]) -> ExecutionTotals:
    values = {
        field: sum(float(getattr(row, field)) for row in rows)
        for field in _ADDITIVE_FIELDS
    }
    return _make_totals(values, sum(row.customers_served for row in rows))


def _assert_depot_closure(
    system: ExecutionTotals,
    by_depot: Mapping[str, ExecutionTotals],
) -> None:
    for field in (*_ADDITIVE_FIELDS, "total_cost", "realized_profit"):
        depot_sum = sum(float(getattr(row, field)) for row in by_depot.values())
        if abs(float(getattr(system, field)) - depot_sum) > ACCOUNTING_TOLERANCE:
            raise ValueError(
                f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: depot {field} does not close to system total"
            )
    if system.customers_served != sum(row.customers_served for row in by_depot.values()):
        raise ValueError(
            f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: depot customer count does not close to system total"
        )
    if abs(system.total_cost - sum(getattr(system, field) for field in _COST_FIELDS)) > ACCOUNTING_TOLERANCE:
        raise ValueError(f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: seven cost items do not close")
    if abs(system.realized_profit - (system.revenue - system.total_cost)) > ACCOUNTING_TOLERANCE:
        raise ValueError(f"{EXECUTION_ACCOUNTING_CONTRACT_ID}: realized profit does not close")


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
