from __future__ import annotations

from setp_solver.algorithms.resetp_alns.support.charging import _available_station_visits
from setp_solver.check import STATION_CAPACITY, _check_station_capacity
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.solution import ChargingAction, Solution
from setp_solver.station_copies import physical_station_id, with_station_visit_copies


def test_station_copies_share_geometry_and_physical_identity() -> None:
    nodes = [
        Node("D", "d", 0.0, 0.0),
        Node("C", "c", 1.0, 0.0, demand=1.0),
        Node("S", "f", 0.5, 0.0, charge_power_kw=50.0, station_chargers=1),
    ]
    instance = Instance(
        nodes=nodes,
        distance_matrix=[[0.0, 10.0, 4.0], [10.0, 0.0, 6.0], [4.0, 6.0, 0.0]],
    )
    expanded = with_station_visit_copies(instance)
    copies = [node for node in expanded.nodes if physical_station_id(node) == "S"]
    assert [node.node_id for node in copies] == ["S", "S__visit_2"]
    assert expanded.distance("D", "S__visit_2") == expanded.distance("D", "S")
    assert expanded.distance("S__visit_2", "C") == expanded.distance("S", "C")


def test_next_unused_copy_represents_a_repeat_visit() -> None:
    stations = [
        Node("S", "f", 0.0, 0.0),
        Node("S__visit_2", "f", 0.0, 0.0, physical_station_id="S"),
        Node("T", "f", 1.0, 0.0),
    ]
    first = _available_station_visits(stations, ["D"])
    second = _available_station_visits(stations, ["D", "S"])
    assert [node.node_id for node in first] == ["S", "T"]
    assert [node.node_id for node in second] == ["S__visit_2", "T"]


def test_station_copies_do_not_multiply_charger_capacity() -> None:
    instance = with_station_visit_copies(
        Instance(
            nodes=[
                Node("D", "d", 0.0, 0.0),
                Node("C", "c", 1.0, 0.0, demand=1.0),
                Node(
                    "S",
                    "f",
                    0.5,
                    0.0,
                    due_time=86_400.0,
                    charge_power_kw=50.0,
                    station_chargers=1,
                ),
            ],
            distance_matrix=[[0.0, 10.0, 4.0], [10.0, 0.0, 6.0], [4.0, 6.0, 0.0]],
        )
    )
    actions = [
        ChargingAction("EV1", "S", 1.0, 2.0, 8 * 3600.0),
        ChargingAction("EV2", "S__visit_2", 1.0, 2.0, 8 * 3600.0),
    ]
    violations = _check_station_capacity(
        Solution(charging_actions=actions),
        {node.node_id: node for node in instance.nodes},
        instance,
        DEFAULT_PRICES,
    )
    assert [violation.type for violation in violations] == [STATION_CAPACITY]
    assert violations[0].location.startswith("S@slot")
