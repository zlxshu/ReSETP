"""Diagnostic route-pool recombination helpers for ALNS structural probes."""

from __future__ import annotations

from dataclasses import dataclass, replace

from setp_solver.solution import ChargingAction, Route, Solution, route_trip_vehicle_id


def canonical_route_key(route: Route, actions: list[ChargingAction] | tuple[ChargingAction, ...]) -> tuple[object, ...]:
    """Key a route by served sequence, fleet type, and charging skeleton."""

    customers = tuple(node for node in route.node_sequence if str(node).upper().startswith("C"))
    stations = tuple(action.station_id for action in actions if action.vehicle_id == route.vehicle_id)
    return (customers, str(route.vehicle_type).lower(), stations)


@dataclass(frozen=True)
class RouteRecord:
    key: tuple[object, ...]
    route: Route
    actions: tuple[ChargingAction, ...]
    customers: frozenset[str]
    score: float


class RoutePool:
    """Small deterministic pool of high-quality complete routes."""

    def __init__(self, *, max_routes: int = 512) -> None:
        self.max_routes = max(1, int(max_routes))
        self.records: dict[tuple[object, ...], RouteRecord] = {}

    def record_solution(self, solution: Solution, *, objective: float) -> None:
        route_count = max(1, len(solution.routes))
        route_score = float(objective) / route_count
        for route in solution.routes:
            actions = [action for action in solution.charging_actions if action.vehicle_id == route.vehicle_id]
            self.record_route(route, actions, score=route_score)

    def record_route(
        self,
        route: Route,
        actions: list[ChargingAction] | tuple[ChargingAction, ...],
        *,
        score: float,
    ) -> None:
        key = canonical_route_key(route, actions)
        customers = frozenset(key[0])
        if not customers:
            return
        record = RouteRecord(
            key=key,
            route=route,
            actions=tuple(actions),
            customers=customers,
            score=float(score),
        )
        previous = self.records.get(key)
        if previous is None or record.score < previous.score - 1e-12:
            self.records[key] = record
        self._trim()

    def recombine(self, customers: set[str] | frozenset[str]) -> Solution | None:
        """Greedily cover all customers with disjoint stored routes."""

        uncovered = set(customers)
        selected: list[RouteRecord] = []
        available = sorted(self.records.values(), key=lambda item: (item.score, len(item.customers), item.key))
        while uncovered:
            feasible = [record for record in available if record.customers and record.customers <= uncovered]
            if not feasible:
                return None
            best = min(feasible, key=lambda item: (item.score / max(1, len(item.customers)), item.score, item.key))
            selected.append(best)
            uncovered -= set(best.customers)
            available.remove(best)
        return self._solution_from_records(selected)

    def _solution_from_records(self, records: list[RouteRecord]) -> Solution:
        cv_index = 0
        ev_index = 0
        routes: list[Route] = []
        actions: list[ChargingAction] = []
        for record in records:
            vehicle_type = str(record.route.vehicle_type).lower()
            if vehicle_type == "ev":
                ev_index += 1
                vehicle_id = route_trip_vehicle_id(f"EV{ev_index}", 1)
            else:
                cv_index += 1
                vehicle_id = route_trip_vehicle_id(f"CV{cv_index}", 1)
            routes.append(replace(record.route, vehicle_id=vehicle_id))
            actions.extend(replace(action, vehicle_id=vehicle_id) for action in record.actions)
        return Solution(routes=routes, charging_actions=actions)

    def _trim(self) -> None:
        if len(self.records) <= self.max_routes:
            return
        keep = sorted(self.records.values(), key=lambda item: (item.score, item.key))[: self.max_routes]
        self.records = {record.key: record for record in keep}
