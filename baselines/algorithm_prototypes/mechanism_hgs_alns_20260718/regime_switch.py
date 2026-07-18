"""Result-blind activation rule for the isolated multi-depot search skeleton."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _values_for_key(payload: Any, target: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == target:
                values.append(value)
            values.extend(_values_for_key(value, target))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(_values_for_key(value, target))
    return values


def activation_decision(bundle_dir: str | Path) -> dict[str, Any]:
    """Enable only an explicitly contracted multi-depot, single-horizon case.

    No objective value, solution, seed, or prior result is read.
    """

    bundle = Path(bundle_dir)
    instance = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
    metadata = dict(instance.get("metadata", {}))
    depot_count = sum(
        str(row.get("node_type", "")).lower() == "d"
        for row in instance.get("nodes", [])
    )
    manifest_path = bundle / "scenario_manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else {}
    )
    categories = {
        str(value).strip().lower()
        for value in _values_for_key(manifest, "e2_category")
        if value is not None
    }
    explicit_regimes = {
        str(value).strip().lower()
        for value in (
            metadata.get("algorithm_regime"),
            metadata.get("search_regime"),
        )
        if value is not None
    }
    multi_shift = (
        "three_shift_manifest" in metadata
        or "three_shift" in str(metadata.get("source", "")).lower()
        or any("shift" in value for value in explicit_regimes)
    )
    contracted_multidepot = (
        "multidepot" in categories
        or "multidepot_single_horizon" in explicit_regimes
    )
    enabled = depot_count >= 2 and contracted_multidepot and not multi_shift
    reasons = []
    if depot_count < 2:
        reasons.append("SINGLE_DEPOT")
    if not contracted_multidepot:
        reasons.append("NO_EXPLICIT_MULTIDEPOT_CONTRACT")
    if multi_shift:
        reasons.append("MULTI_SHIFT_PRESENT")
    if enabled:
        reasons.append("EXPLICIT_MULTIDEPOT_SINGLE_HORIZON")
    return {
        "enabled": enabled,
        "depot_count": depot_count,
        "categories": sorted(categories),
        "explicit_regimes": sorted(explicit_regimes),
        "multi_shift": multi_shift,
        "reasons": reasons,
        "result_fields_read": False,
    }
