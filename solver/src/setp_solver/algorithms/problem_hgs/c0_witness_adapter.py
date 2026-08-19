"""C0 witness materialisation for the private Problem-HGS path.

The saved witness is a route-and-timing skeleton.  This adapter deliberately
does not invent charging or SOC fields: the existing C2 charging repair owns
that later step.  It only performs the CSV -> Route -> Solution -> Duty
conversion and restores the canonical registered fleet slots.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from math import isfinite
from typing import Any

from setp_solver.solution import Route, Solution

from .fleet_registry import register_all_vehicle_slots
from .model import DutyIndividual


_REQUIRED_WITNESS_FIELDS = frozenset(
    {
        "instance_id",
        "witness_status",
        "physical_vehicle_id",
        "route_vehicle_id",
        "depot_id",
        "shift_id",
        "customers",
        "departure_minute",
        "return_minute",
    }
)


def _route_vehicle_id(row: Mapping[str, str]) -> str:
    """Preserve the historical route-id normalisation used by the runner."""

    physical_vehicle_id = str(row["physical_vehicle_id"])
    prefix, separator, suffix = physical_vehicle_id.rpartition("_")
    if not separator or not suffix:
        raise ValueError(
            "witness physical_vehicle_id must end with a registered index"
        )
    try:
        normalized_base = f"{prefix}_{int(suffix)}"
    except ValueError as exc:
        raise ValueError(
            "witness physical_vehicle_id has a non-numeric registered index"
        ) from exc
    route_vehicle_id = str(row["route_vehicle_id"])
    if "#" not in route_vehicle_id:
        return normalized_base
    return normalized_base + "#" + route_vehicle_id.split("#", 1)[1]


def _numeric_witness_field(row: Mapping[str, str], field: str) -> float:
    value = str(row[field]).strip()
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"witness {field} is not numeric: {value!r}") from exc
    if not isfinite(number):
        raise ValueError(f"witness {field} is not finite: {value!r}")
    return number


def adapt_witness_rows_to_duty(
    witness_rows: Iterable[Mapping[str, str]],
    *,
    instance_id: str,
    bundle: Any,
    register_idle_duties: Callable[[DutyIndividual, Any], DutyIndividual]
    | None = None,
) -> DutyIndividual:
    """Convert saved route rows into a canonical, registered Duty individual.

    The route rows carry the six C0 input groups that are available in the
    saved witness: bundle/customer/fleet context; physical and route identity;
    shift and route-clock fields; customer coverage and volume checks.  A
    route-only witness has no charging/SOC columns, so ``charging_actions``
    stays empty and C2 is the explicit owner of charging reconstruction.
    """

    rows = [dict(row) for row in witness_rows]
    if not rows:
        raise ValueError(f"saved health witness is absent for {instance_id}")
    missing = sorted(_REQUIRED_WITNESS_FIELDS.difference(rows[0]))
    if missing:
        raise ValueError(
            "saved health witness is missing required fields: "
            + ", ".join(missing)
        )
    if any(str(row.get("instance_id", "")) != instance_id for row in rows):
        raise ValueError(f"saved health witness contains another instance: {instance_id}")
    if {
        str(row.get("witness_status", "")).strip()
        for row in rows
    } != {"PASS"}:
        raise ValueError(f"saved health witness is absent or failed for {instance_id}")

    customer_nodes = {
        str(node.node_id): node
        for node in bundle.instance.nodes
        if str(node.node_type).lower() == "c"
    }
    routes: list[Route] = []
    served_customers: list[str] = []
    for row in rows:
        physical_vehicle_id = str(row["physical_vehicle_id"]).strip()
        if not physical_vehicle_id.startswith(("CV_", "EV_")):
            raise ValueError(
                f"witness vehicle identity is not CV/EV: {physical_vehicle_id}"
            )
        vehicle_type = "ev" if physical_vehicle_id.startswith("EV_") else "cv"
        depot_id = str(row["depot_id"]).strip()
        shift_id = str(row["shift_id"]).strip()
        if not depot_id or not shift_id:
            raise ValueError("witness depot_id and shift_id cannot be empty")
        _numeric_witness_field(row, "departure_minute")
        _numeric_witness_field(row, "return_minute")
        customers = tuple(
            customer.strip()
            for customer in str(row["customers"]).split("|")
            if customer.strip()
        )
        if not customers:
            raise ValueError("witness route has no customers")
        if len(customers) != len(set(customers)):
            raise ValueError("witness route repeats a customer")
        unknown = sorted(set(customers).difference(customer_nodes))
        if unknown:
            raise ValueError(
                "witness route contains unknown customers: " + ", ".join(unknown)
            )
        if row.get("customer_count", "").strip():
            try:
                customer_count = int(row["customer_count"])
            except ValueError as exc:
                raise ValueError("witness customer_count is not an integer") from exc
            if customer_count != len(customers):
                raise ValueError("witness customer_count disagrees with customers")
        for optional_field in ("volume_m3", "demand_kg"):
            if row.get(optional_field, "").strip():
                _numeric_witness_field(row, optional_field)
        if str(row["route_vehicle_id"]).count("#") > 1:
            raise ValueError("witness route_vehicle_id has multiple trip suffixes")
        routes.append(
            Route(
                vehicle_id=_route_vehicle_id(row),
                vehicle_type=vehicle_type,
                home_depot_id=depot_id,
                node_sequence=[depot_id, *customers, depot_id],
            )
        )
        served_customers.extend(customers)

    if len(served_customers) != len(set(served_customers)):
        raise ValueError("saved health witness repeats customers")
    if set(served_customers) != set(customer_nodes):
        raise ValueError("saved health witness does not cover customers exactly once")

    skeleton = Solution(routes=routes)
    individual = DutyIndividual.from_solution(skeleton)
    register = register_idle_duties or register_all_vehicle_slots
    return register(individual, bundle)
