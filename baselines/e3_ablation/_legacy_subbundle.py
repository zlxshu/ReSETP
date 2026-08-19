"""Legacy baseline-only helpers extracted from the retired fairness runner."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import shutil
from typing import Any

import numpy as np

from setp_solver.instance_loader import Instance, Node


def _subinstance_for_depot(
    instance: Instance,
    depot_id: str,
    owners: dict[str, str],
) -> Instance:
    keep_ids = {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() == "f"
        or node.node_id == depot_id
        or (
            node.node_type.lower() == "c"
            and owners.get(node.node_id) == depot_id
        )
    }
    nodes = [node for node in instance.nodes if node.node_id in keep_ids]
    old_index = instance.node_index
    indices = [old_index[node.node_id] for node in nodes]
    matrix = np.asarray(instance.distance_matrix, dtype=float)[
        np.ix_(indices, indices)
    ].tolist()
    return Instance(nodes=nodes, distance_matrix=matrix)


def _write_subbundle(
    path: Path,
    instance: Instance,
    source_bundle_dir: Path,
    depot_id: str,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    instance_payload = {
        "scenario_id": f"{source_bundle_dir.name}__independent_{depot_id}",
        "seed": 0,
        "nodes": [_node_payload(node) for node in instance.nodes],
        "distance_unit": "meter",
        "time_unit": "second",
        "demand_unit": "kg",
        "metadata": {
            "source_bundle_dir": str(source_bundle_dir),
            "independent_depot_id": depot_id,
            "build_note": (
                "v2026-06-12: V1 independent-depot Pi_d0 subbundle."
            ),
        },
    }
    (path / "instance.json").write_text(
        json.dumps(
            instance_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    np.save(
        path / "distance_matrix.npy",
        np.asarray(instance.distance_matrix, dtype=float),
    )
    shutil.copyfile(
        source_bundle_dir / "carbon_profile.csv",
        path / "carbon_profile.csv",
    )
    manifest = {
        "schema_version": "setp-independent-depot-subbundle.v1",
        "source_bundle_dir": str(source_bundle_dir),
        "independent_depot_id": depot_id,
        "customer_count": sum(
            1
            for node in instance.nodes
            if node.node_type.lower() == "c"
        ),
    }
    (path / "scenario_manifest.json").write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _node_payload(node: Node) -> dict[str, Any]:
    payload = asdict(node)
    if payload.get("charge_power_kw") is None:
        payload.pop("charge_power_kw", None)
    return payload
