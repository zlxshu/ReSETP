"""Gate diagnostics for the solver search handoff.

v2026-06-11: Coordinates B2/G1-G6 reporting without changing model semantics.
Use these helpers from tests or one-off gate scripts; they only call the
shared cost/check/search adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..cost import CARBON_N_SLOTS, CARBON_SLOT_SECONDS
from .bundle import load_search_bundle


@dataclass(frozen=True)
class B2GateResult:
    return_deadline: float
    source_depot_ids: list[str]
    window_end: float
    safe: bool


def b2_feasible_domain_gate(bundle_dir: str | Path) -> B2GateResult:
    """Return the corrected B2 overflow gate based on depot return deadlines."""

    bundle = load_search_bundle(bundle_dir)
    depots = [node for node in bundle.instance.nodes if node.node_type.lower() == "d"]
    if not depots:
        raise ValueError("No depot nodes found for B2 return-deadline gate")
    return_deadline = max(float(node.due_time) for node in depots)
    sources = sorted(node.node_id for node in depots if abs(float(node.due_time) - return_deadline) <= 1e-9)
    # v2026-06-12: Q1 shifted bundles carry 48 slots; legacy fixtures carry 18.
    window_end = (len(bundle.carbon_profile) or CARBON_N_SLOTS) * CARBON_SLOT_SECONDS
    return B2GateResult(return_deadline, sources, window_end, return_deadline <= window_end + 1e-6)
