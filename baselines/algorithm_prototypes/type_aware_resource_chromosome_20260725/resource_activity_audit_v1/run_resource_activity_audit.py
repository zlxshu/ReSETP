#!/usr/bin/env python3
"""Read-only activity audit for depot/powertrain labels in sealed China81 v7.

This script does not call a solver, completion routine, evaluator, or scorer.
It only parses the already sealed ``solution_witnesses.json`` files and
materialises reproducible descriptive evidence for the next algorithm-design
decision.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
AUDIT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = (
    REPO_ROOT
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724/"
    "full_gate/tasks"
)
ARMS = ("HGS-M", "MV-HGS-SP")
EXPECTED_TASKS = 405


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_task_name(task_name: str) -> tuple[str, int]:
    parts = task_name.split("__")
    if len(parts) != 3 or not parts[2].startswith("seed"):
        raise ValueError(f"unexpected task directory name: {task_name}")
    return parts[1], int(parts[2].removeprefix("seed"))


def audit_arm(
    *,
    task_name: str,
    instance_id: str,
    seed: int,
    arm: str,
    witness: dict[str, Any],
) -> dict[str, Any]:
    routes = witness["routes"]
    actions = witness.get("charging_actions", [])
    depots = {str(route["home_depot_id"]) for route in routes}

    customers: list[str] = []
    labels: Counter[str] = Counter()
    route_types: Counter[str] = Counter()
    for route in routes:
        depot = str(route["home_depot_id"])
        vehicle_type = str(route["vehicle_type"]).lower()
        sequence = [str(node) for node in route["node_sequence"]]
        if vehicle_type not in {"cv", "ev"}:
            raise ValueError(f"{task_name}/{arm}: bad vehicle type {vehicle_type}")
        if len(sequence) < 2 or sequence[0] != depot or sequence[-1] != depot:
            raise ValueError(f"{task_name}/{arm}: route endpoints do not match depot")
        route_types[vehicle_type] += 1
        label = f"{depot}|{vehicle_type}"
        route_customers = sequence[1:-1]
        customers.extend(route_customers)
        labels.update({label: len(route_customers)})

    if len(customers) != len(set(customers)):
        raise ValueError(f"{task_name}/{arm}: duplicate customer in witness")

    action_counts = Counter(str(action["vehicle_id"]) for action in actions)
    public_actions = sum(
        str(action["station_id"]) not in depots for action in actions
    )
    zero_start_actions = sum(
        abs(float(action["charge_start_second"])) <= 1e-12
        for action in actions
    )
    ev_customer_count = sum(
        count for label, count in labels.items() if label.endswith("|ev")
    )
    distinct_vehicle_classes = sum(
        int(route_types[vehicle_type] > 0) for vehicle_type in ("cv", "ev")
    )

    return {
        "task_name": task_name,
        "instance_id": instance_id,
        "seed": seed,
        "arm": arm,
        "route_count": len(routes),
        "customer_count": len(customers),
        "depot_count_used": len(depots),
        "distinct_resource_labels": len(labels),
        "distinct_vehicle_classes": distinct_vehicle_classes,
        "cv_route_count": route_types["cv"],
        "ev_route_count": route_types["ev"],
        "ev_route_share": (
            route_types["ev"] / len(routes) if routes else 0.0
        ),
        "ev_customer_count": ev_customer_count,
        "ev_customer_share": (
            ev_customer_count / len(customers) if customers else 0.0
        ),
        "charging_action_count": len(actions),
        "depot_charging_action_count": len(actions) - public_actions,
        "public_charging_action_count": public_actions,
        "zero_start_charging_action_count": zero_start_actions,
        "vehicles_with_multiple_charging_actions": sum(
            count > 1 for count in action_counts.values()
        ),
        "cross_site_service_count": len(witness.get("cross_site_services", [])),
        "resource_label_customer_counts_json": json.dumps(
            dict(sorted(labels.items())),
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def main() -> None:
    witness_paths = sorted(SOURCE_DIR.glob("*/solution_witnesses.json"))
    if len(witness_paths) != EXPECTED_TASKS:
        raise RuntimeError(
            f"expected {EXPECTED_TASKS} sealed tasks, found {len(witness_paths)}"
        )

    input_rows: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for path in witness_paths:
        task_name = path.parent.name
        instance_id, seed = parse_task_name(task_name)
        payload = json.loads(path.read_text(encoding="utf-8"))
        input_rows.append(
            {
                "task_name": task_name,
                "relative_path": str(path.relative_to(REPO_ROOT)),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
        for arm in ARMS:
            if arm not in payload:
                raise KeyError(f"{task_name}: missing arm {arm}")
            rows.append(
                audit_arm(
                    task_name=task_name,
                    instance_id=instance_id,
                    seed=seed,
                    arm=arm,
                    witness=payload[arm],
                )
            )

    fieldnames = list(rows[0])
    with (AUDIT_DIR / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with (AUDIT_DIR / "input_hashes.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(input_rows[0]))
        writer.writeheader()
        writer.writerows(input_rows)

    by_arm: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        selected = [row for row in rows if row["arm"] == arm]
        by_arm[arm] = {
            "solutions": len(selected),
            "routes": sum(int(row["route_count"]) for row in selected),
            "customers": sum(int(row["customer_count"]) for row in selected),
            "solutions_using_both_vehicle_classes": sum(
                int(row["distinct_vehicle_classes"]) == 2 for row in selected
            ),
            "solutions_with_at_least_three_resource_labels": sum(
                int(row["distinct_resource_labels"]) >= 3 for row in selected
            ),
            "mean_distinct_resource_labels": mean(
                int(row["distinct_resource_labels"]) for row in selected
            ),
            "ev_routes": sum(int(row["ev_route_count"]) for row in selected),
            "ev_route_share": (
                sum(int(row["ev_route_count"]) for row in selected)
                / sum(int(row["route_count"]) for row in selected)
            ),
            "ev_customers": sum(
                int(row["ev_customer_count"]) for row in selected
            ),
            "ev_customer_share": (
                sum(int(row["ev_customer_count"]) for row in selected)
                / sum(int(row["customer_count"]) for row in selected)
            ),
            "charging_actions": sum(
                int(row["charging_action_count"]) for row in selected
            ),
            "public_charging_actions": sum(
                int(row["public_charging_action_count"]) for row in selected
            ),
            "zero_start_charging_actions": sum(
                int(row["zero_start_charging_action_count"]) for row in selected
            ),
            "vehicles_with_multiple_charging_actions": sum(
                int(row["vehicles_with_multiple_charging_actions"])
                for row in selected
            ),
            "solutions_with_cross_site_service": sum(
                int(row["cross_site_service_count"]) > 0 for row in selected
            ),
            "cross_site_services": sum(
                int(row["cross_site_service_count"]) for row in selected
            ),
        }

    input_manifest_digest = hashlib.sha256(
        "".join(
            f"{row['relative_path']}:{row['sha256']}\n" for row in input_rows
        ).encode()
    ).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "task_id": "E2-TARC-RESOURCE-ACTIVITY-AUDIT-001",
        "created_at_utc": now,
        "mode": "READ_ONLY_ZERO_SEARCH_DESCRIPTIVE_AUDIT",
        "source_directory": str(SOURCE_DIR.relative_to(REPO_ROOT)),
        "expected_tasks": EXPECTED_TASKS,
        "observed_tasks": len(witness_paths),
        "arms": list(ARMS),
        "input_manifest_sha256": input_manifest_digest,
        "solver_calls": 0,
        "completion_calls": 0,
        "objective_evaluations": 0,
        "protected_files_modified": False,
    }
    write_json(AUDIT_DIR / "metadata.json", metadata)

    decision = {
        "decision": "EVIDENCE_ONLY_RESOURCE_TYPE_ACTIVITY_AUDIT",
        "task_id": metadata["task_id"],
        "input_integrity": "PASS_405_SEALED_WITNESS_FILES",
        "summary_by_arm": by_arm,
        "hard_interpretation": {
            "supported": [
                "depot and powertrain labels are directly observable for every "
                "customer in the sealed witnesses",
                "the audit quantifies whether low-cardinality resource labels "
                "are active enough to justify a representation gate",
            ],
            "not_supported": [
                "algorithmic improvement",
                "causal benefit from a type-aware chromosome",
                "public BKS or SOTA performance",
                "shared-public-charger search value",
            ],
        },
        "next_action_boundary": (
            "Use these descriptive facts only to freeze or reject a separate "
            "zero-objective representability/decoder contract. Do not launch "
            "performance search from this audit alone."
        ),
    }
    write_json(AUDIT_DIR / "decision.json", decision)

    report_lines = [
        "# E2 type-aware resource chromosome: sealed-witness activity audit",
        "",
        "This is a read-only descriptive audit of the 405 sealed corrected "
        "China81 v7 witness files. It performs no solver, completion, objective, "
        "or scorer call.",
        "",
        "## Direct results",
        "",
    ]
    for arm in ARMS:
        summary = by_arm[arm]
        report_lines.extend(
            [
                f"### {arm}",
                "",
                f"- solutions: {summary['solutions']}",
                f"- routes: {summary['routes']}",
                "- solutions using both CV and EV: "
                f"{summary['solutions_using_both_vehicle_classes']}/405",
                "- solutions with at least three depot/powertrain labels: "
                f"{summary['solutions_with_at_least_three_resource_labels']}/405",
                "- mean distinct depot/powertrain labels: "
                f"{summary['mean_distinct_resource_labels']:.6f}",
                f"- EV route share: {summary['ev_route_share']:.6%}",
                f"- EV customer share: {summary['ev_customer_share']:.6%}",
                "- public charging actions: "
                f"{summary['public_charging_actions']}/"
                f"{summary['charging_actions']}",
                "- charging actions at second zero: "
                f"{summary['zero_start_charging_actions']}/"
                f"{summary['charging_actions']}",
                "- vehicles with multiple charging actions: "
                f"{summary['vehicles_with_multiple_charging_actions']}",
                "- solutions with cross-site service: "
                f"{summary['solutions_with_cross_site_service']}/405",
                "",
            ]
        )
    report_lines.extend(
        [
            "## Claim boundary",
            "",
            "The results can establish only whether depot/powertrain labels are "
            "present and how active they are in the protected solutions. They "
            "do not establish that inheriting those labels improves search. "
            "The absence of public-station actions also means that a new method "
            "cannot justify itself primarily as public-charger optimization on "
            "this frozen panel.",
            "",
        ]
    )
    (AUDIT_DIR / "report.md").write_text(
        "\n".join(report_lines), encoding="utf-8"
    )

    artifact_paths = sorted(
        path
        for path in AUDIT_DIR.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    write_json(
        AUDIT_DIR / "artifact_hashes.json",
        {
            str(path.relative_to(AUDIT_DIR)): sha256(path)
            for path in artifact_paths
        },
    )


if __name__ == "__main__":
    main()
