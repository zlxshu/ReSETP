"""Charging-station identity helpers."""

from __future__ import annotations

from .instance_loader import Node

def physical_station_id(node: Node) -> str:
    return node.physical_station_id or node.node_id
