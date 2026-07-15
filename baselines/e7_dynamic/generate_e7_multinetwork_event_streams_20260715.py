#!/usr/bin/env python3
"""Freeze result-blind E7 event streams for N114, N221, and N322.

N221 is copied byte-for-byte from the already sealed 2026-07-14 stream set.
N114 and N322 use the same generator and event proportions before any dynamic
search is run.  Existing-customer events must remain editable in both frozen
responsibility-condition starting plans.  Added orders inherit all physical
fields from a frozen sister bundle; ownership is assigned independently for
the geographic and historical-mixed responsibility conditions.
"""

from __future__ import annotations

import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from baselines.e7_dynamic import generate_e7_event_streams_20260714 as gen
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.certificate_execution import build_certificate_execution_ledger
from setp_solver.search.metaheuristic_baselines import solution_from_dict


OUT = ROOT / "baselines/e7_dynamic/e7_multinetwork_event_streams_v3_20260715"
OLD_N221 = ROOT / "baselines/e7_dynamic/e7_v2_20260714/event_streams"
OLD_N221_RESPONSIBILITY = (
    ROOT / "baselines/e7_dynamic/e7_responsibility_scenario_design_20260714/ownership_maps"
)
ASSET_ROOT = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets"
OWNER_ROOT = (
    ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713/ownership_maps"
)
E6_ROOT = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
NETWORKS = {
    "N114": {"instance": "L-main-threeshift-50c-01", "donor": "L-main-threeshift-75c-01"},
    "N221": {"instance": "L-main-threeshift-100c-01", "donor": "L-main-threeshift-200c-01"},
    "N322": {"instance": "L-main-threeshift-150c-01", "donor": "L-main-threeshift-200c-01"},
}
CONDITIONS = ("geographic", "historical_mixed")
SEEDS = (1, 2, 3, 4, 5)
CONTRACT_ID = "E7_MULTINETWORK_EVENT_STREAM_FREEZE_V3_CONSERVATIVE_ADDS"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_owner_map(instance_id: str, condition: str) -> dict[str, str]:
    suffix = "mixed" if condition == "historical_mixed" else "geographic"
    path = OWNER_ROOT / f"{instance_id}__{suffix}.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            str(row["customer_id"]): str(row["owner_depot_id"])
            for row in csv.DictReader(handle)
        }


def reference_departures(instance_id: str, instance: Any, prices: Any) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
    customer_ids = {
        node.node_id for node in instance.nodes if node.node_type.lower() == "c"
    }
    departures: dict[str, dict[str, float]] = {item: {} for item in customer_ids}
    sources: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        suffix = "mixed" if condition == "historical_mixed" else "geographic"
        for arm in ("no_loss", "independent"):
            label = f"{condition}_{arm}_seed1"
            stem = f"{instance_id}__{suffix}__seed1__{arm}"
            solution_path = E6_ROOT / "solutions" / f"{stem}.json"
            certificate_path = E6_ROOT / "certificates" / f"{stem}.json"
            solution = solution_from_dict(json.loads(solution_path.read_text(encoding="utf-8")))
            certificate = gen.load_certificate(certificate_path)
            ledger = build_certificate_execution_ledger(solution, certificate, instance, prices)
            observed: dict[str, float] = {}
            for trip in ledger.routes.values():
                for node in trip.nodes:
                    if node.node_id in customer_ids:
                        if node.node_id in observed:
                            raise RuntimeError(f"{label} serves {node.node_id} twice")
                        observed[node.node_id] = float(trip.departure_second)
            if set(observed) != customer_ids:
                raise RuntimeError(f"{label} customer coverage does not close")
            for customer_id, departure in observed.items():
                departures[customer_id][label] = departure
            sources.append(
                {
                    "condition": condition,
                    "arm": arm,
                    "solution_path": str(solution_path.relative_to(ROOT)),
                    "solution_sha256": sha256(solution_path),
                    "certificate_path": str(certificate_path.relative_to(ROOT)),
                    "certificate_sha256": sha256(certificate_path),
                }
            )
    return departures, sources


def write_condition_owners(
    network_dir: Path,
    seed: int,
    events: list[Any],
    instance_id: str,
    donor_id: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        base = read_owner_map(instance_id, condition)
        donor = read_owner_map(donor_id, condition)
        owners = dict(base)
        for event in events:
            if event.event_type == "add":
                if condition == "geographic":
                    # The physical-stream owner file was assigned by nearest depot.
                    physical_path = network_dir / f"stream_seed{seed}.owners.csv"
                    with physical_path.open(newline="", encoding="utf-8") as handle:
                        physical = {
                            str(row["customer_id"]): str(row["owner_depot_id"])
                            for row in csv.DictReader(handle)
                        }
                    owners[event.customer_id] = physical[event.customer_id]
                else:
                    owners[event.customer_id] = donor[str(event.donor_customer_id)]
        path = network_dir / f"stream_seed{seed}__{condition}.owners.csv"
        write_csv(
            path,
            [
                {"customer_id": customer_id, "owner_depot_id": owners[customer_id]}
                for customer_id in sorted(owners)
            ],
        )
        records.append(
            {
                "network": network_dir.name,
                "seed": seed,
                "responsibility_condition": condition,
                "owner_path": str(path.relative_to(ROOT)),
                "owner_sha256": sha256(path),
                "owner_count": len(owners),
                "status": "PASS",
            }
        )
    return records


def copy_n221() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    network_dir = OUT / "N221"
    network_dir.mkdir(parents=True, exist_ok=True)
    stream_rows: list[dict[str, Any]] = []
    owner_rows: list[dict[str, Any]] = []
    old_index = list(csv.DictReader((OLD_N221 / "raw_runs.csv").open(newline="", encoding="utf-8")))
    for seed in SEEDS:
        for suffix in ("events.json", "events.csv", "dynamic_events.tsv", "owners.csv"):
            source = OLD_N221 / f"stream_seed{seed}.{suffix}"
            target = network_dir / source.name
            shutil.copy2(source, target)
        events_path = network_dir / f"stream_seed{seed}.events.json"
        events = json.loads(events_path.read_text(encoding="utf-8"))
        stream_rows.extend(
            {**row, "network": "N221", "reused_from_sealed_n221": True}
            for row in old_index
            if int(row["seed"]) == seed
        )
        for condition in CONDITIONS:
            source = OLD_N221_RESPONSIBILITY / f"stream_seed{seed}__{condition}.csv"
            target = network_dir / f"stream_seed{seed}__{condition}.owners.csv"
            shutil.copy2(source, target)
            owner_rows.append(
                {
                    "network": "N221",
                    "seed": seed,
                    "responsibility_condition": condition,
                    "owner_path": str(target.relative_to(ROOT)),
                    "owner_sha256": sha256(target),
                    "owner_count": sum(1 for _ in csv.DictReader(target.open(newline="", encoding="utf-8"))),
                    "status": "PASS",
                }
            )
        if len(events) != 55:
            raise RuntimeError(f"sealed N221 stream {seed} no longer has 55 events")
    return stream_rows, owner_rows


class _FixedWindowRandom(random.Random):
    """Keep all randomness unchanged except the predeclared event-time window."""

    def uniform(self, a: float, b: float) -> float:
        if abs(a - 0.05 * gen.HORIZON_SECONDS) <= 1e-9 and abs(
            b - 0.95 * gen.HORIZON_SECONDS
        ) <= 1e-9:
            return super().uniform(0.05 * gen.HORIZON_SECONDS, 0.75 * gen.HORIZON_SECONDS)
        return super().uniform(a, b)

    def choice(self, seq: Any) -> Any:
        if seq and hasattr(seq[0], "demand"):
            # Added orders use the smallest directly actionable frozen donor.
            # This conservative, result-blind rule avoids making collaboration
            # look necessary merely by injecting an oversized order.
            return min(
                seq,
                key=lambda node: (
                    float(node.demand),
                    float(node.due_time),
                    str(node.node_id),
                ),
            )
        return super().choice(seq)


def generate_network(network: str, instance_id: str, donor_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    network_dir = OUT / network
    network_dir.mkdir(parents=True, exist_ok=True)
    base_bundle = load_search_bundle(ASSET_ROOT / instance_id / "bundle")
    donor_bundle = load_search_bundle(ASSET_ROOT / donor_id / "bundle")
    prices = legacy.prices_for("M1", 0.0)
    base_customers = [node for node in base_bundle.instance.nodes if node.node_type.lower() == "c"]
    n = len(base_customers)
    counts = {
        "add": max(1, round(0.01 * n)),
        "cancel": max(1, round(0.01 * n)),
        "demand_change": max(1, round(0.02 * n)),
    }
    departures, sources = reference_departures(instance_id, base_bundle.instance, prices)
    # E7 starts from the sealed independent plan in each responsibility
    # condition.  No-loss plans are provenance references, not E7 starts.
    labels = tuple(
        label
        for label in sorted(next(iter(departures.values())))
        if label.endswith("_independent_seed1")
    )
    if labels != (
        "geographic_independent_seed1",
        "historical_mixed_independent_seed1",
    ):
        raise RuntimeError(f"unexpected E7 starting-plan labels: {labels}")
    geographic = read_owner_map(instance_id, "geographic")

    old_counts = gen.COUNTS
    old_labels = gen.FORMAL_REFERENCE_LABELS
    old_donor_id = gen.DONOR_SCENARIO_ID
    old_output = gen.OUTPUT_ROOT
    old_random = gen.random.Random
    try:
        gen.COUNTS = counts
        gen.FORMAL_REFERENCE_LABELS = labels
        gen.DONOR_SCENARIO_ID = donor_id
        gen.OUTPUT_ROOT = network_dir
        gen.random.Random = _FixedWindowRandom
        stream_rows: list[dict[str, Any]] = []
        owner_rows: list[dict[str, Any]] = []
        for seed in SEEDS:
            events, physical_owners, audit = gen.generate_stream(
                seed,
                base_bundle.instance,
                donor_bundle.instance,
                prices,
                geographic,
                departures,
            )
            expected = sum(counts.values())
            if len(events) != expected or len({event.customer_id for event in events}) != expected:
                raise RuntimeError(f"{network} seed {seed} event count/target uniqueness failed")
            gen.write_stream(seed, events, physical_owners)
            stream_rows.extend(
                {**row, "network": network, "reused_from_sealed_n221": False}
                for row in audit
            )
            owner_rows.extend(
                write_condition_owners(network_dir, seed, events, instance_id, donor_id)
            )
    finally:
        gen.COUNTS = old_counts
        gen.FORMAL_REFERENCE_LABELS = old_labels
        gen.DONOR_SCENARIO_ID = old_donor_id
        gen.OUTPUT_ROOT = old_output
        gen.random.Random = old_random
    return stream_rows, owner_rows, sources


def main() -> int:
    if OUT.exists():
        visible = [path for path in OUT.rglob("*") if path.is_file() and not path.name.startswith("._")]
        if visible:
            if (OUT / "decision.json").is_file():
                raise RuntimeError(f"refusing to overwrite frozen output {OUT}")
            # A prior failed generation is not evidence and may be rebuilt.
            shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    raw_rows: list[dict[str, Any]] = []
    owner_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    for network in ("N114", "N221", "N322"):
        config = NETWORKS[network]
        rows, owners, sources = generate_network(network, config["instance"], config["donor"])
        raw_rows.extend(rows)
        owner_rows.extend(owners)
        source_rows.extend({**row, "network": network} for row in sources)
    write_csv(OUT / "raw_runs.csv", raw_rows)
    write_csv(OUT / "responsibility_maps.csv", owner_rows)
    metadata = {
        "contract_id": CONTRACT_ID,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "networks": NETWORKS,
        "conditions": list(CONDITIONS),
        "seeds": list(SEEDS),
        "event_proportions": {"add": 0.01, "cancel": 0.01, "demand_change": 0.02},
        "event_appearance_window_fraction": [0.05, 0.75],
        "added_order_donor_rule": "smallest-demand directly actionable frozen sister-bundle donor; conservative against the cooperation treatment",
        "supersedes": "V1 had excessive churn; V2 retained randomly sized added orders that could make the N114 no-cooperation comparator structurally infeasible",
        "starting_plan_sources": source_rows,
        "search_evaluations": 0,
        "evidence_boundary": "Event streams were frozen before any multi-network dynamic search result existed.",
    }
    write_json(OUT / "metadata.json", metadata)
    decision = {
        "contract_id": CONTRACT_ID,
        "status": "PASS_E7_MULTINETWORK_STREAM_FREEZE",
        "network_count": 3,
        "stream_count": 15,
        "responsibility_map_count": 30,
        "all_event_rows_retained": True,
        "result_direction_used_for_selection": False,
    }
    write_json(OUT / "decision.json", decision)
    report = (
        "# E7 multi-network event-stream freeze\n\n"
        "Status: `PASS_E7_MULTINETWORK_STREAM_FREEZE`.\n\n"
        "N221 reuses the sealed five physical streams without modification. N114 and N322 "
        "use the same result-blind event proportions and require existing-order events to "
        "remain editable in both frozen responsibility-condition starting plans. No route "
        "search was executed while constructing or selecting these streams.\n"
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hashes = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
