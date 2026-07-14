#!/usr/bin/env python3
"""Freeze two E7 customer-responsibility scenarios before formal search.

The geographic scenario keeps the existing nearest-depot responsibility rule.
The historical-mixed scenario reuses the already frozen E3 mixed maps: existing
customers keep the 100-customer-map responsibility, while a new customer
inherits the responsibility of its frozen donor in the 200-customer map.
No routing result is read when either scenario is constructed.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
E3_OWNERS = (
    ROOT
    / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713/ownership_maps"
)
EVENT_ROOT = ROOT / "baselines/e7_dynamic/e7_v2_20260714/event_streams"
OUT = ROOT / "baselines/e7_dynamic/e7_responsibility_scenario_design_20260714"
STREAMS = (1, 2, 3, 4, 5)
CONDITIONS = ("geographic", "historical_mixed")
CONTRACT_ID = "E7_RESPONSIBILITY_SCENARIOS_V1_PRE_RESULT_TWO_ENDPOINTS"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fields: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_owners(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    owners = {
        str(row["customer_id"]): str(row["owner_depot_id"])
        for row in rows
    }
    if len(owners) != len(rows) or set(owners.values()) - {"D0", "D1"}:
        raise RuntimeError(f"invalid owner map {path}")
    return owners


def load_events(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise RuntimeError(f"invalid event stream {path}")
    return rows


def source_paths() -> dict[str, Path]:
    paths = {
        "base_geographic": E3_OWNERS / "L-main-threeshift-100c-01__geographic.csv",
        "base_mixed": E3_OWNERS / "L-main-threeshift-100c-01__mixed.csv",
        "donor_mixed": E3_OWNERS / "L-main-threeshift-200c-01__mixed.csv",
    }
    for seed in STREAMS:
        paths[f"events_seed{seed}"] = EVENT_ROOT / f"stream_seed{seed}.events.json"
        paths[f"nearest_seed{seed}"] = EVENT_ROOT / f"stream_seed{seed}.owners.csv"
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing frozen inputs: " + ", ".join(missing))
    return paths


def build() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = source_paths()
    base_geographic = load_owners(paths["base_geographic"])
    base_mixed = load_owners(paths["base_mixed"])
    donor_mixed = load_owners(paths["donor_mixed"])
    if set(base_geographic) != set(base_mixed):
        raise RuntimeError("the two frozen base maps cover different customers")
    base_changed = sum(
        base_geographic[customer] != base_mixed[customer]
        for customer in base_geographic
    )
    rows: list[dict[str, Any]] = []
    outputs: dict[str, Any] = {}
    for seed in STREAMS:
        events = load_events(paths[f"events_seed{seed}"])
        nearest = load_owners(paths[f"nearest_seed{seed}"])
        add_events = [row for row in events if row["event_type"] == "add"]
        add_ids = {str(row["customer_id"]) for row in add_events}
        expected = set(base_geographic) | add_ids
        if set(nearest) != expected:
            raise RuntimeError(f"stream {seed} nearest owner coverage differs")
        if any(nearest[key] != value for key, value in base_geographic.items()):
            raise RuntimeError(
                f"stream {seed} existing nearest owners differ from E3 geographic map"
            )
        historical = dict(base_mixed)
        for event in add_events:
            donor = str(event.get("donor_customer_id", ""))
            if donor not in donor_mixed:
                raise RuntimeError(
                    f"stream {seed} donor {donor} is absent from the frozen mixed map"
                )
            historical[str(event["customer_id"])] = donor_mixed[donor]
        if set(historical) != expected:
            raise RuntimeError(f"stream {seed} historical owner coverage differs")
        scenario_maps = {
            "geographic": nearest,
            "historical_mixed": historical,
        }
        add_changed = sum(
            historical[customer] != nearest[customer]
            for customer in add_ids
        )
        for condition, owners in scenario_maps.items():
            output = OUT / "ownership_maps" / f"stream_seed{seed}__{condition}.csv"
            owner_rows = [
                {"customer_id": customer, "owner_depot_id": owners[customer]}
                for customer in sorted(owners)
            ]
            write_csv(output, owner_rows, ["customer_id", "owner_depot_id"])
            row = {
                "stream_seed": seed,
                "condition": condition,
                "customer_count": len(owners),
                "base_customer_count": len(base_geographic),
                "new_customer_count": len(add_ids),
                "base_owner_changes_from_geographic": (
                    0 if condition == "geographic" else base_changed
                ),
                "new_owner_changes_from_nearest": (
                    0 if condition == "geographic" else add_changed
                ),
                "d0_customer_count": sum(value == "D0" for value in owners.values()),
                "d1_customer_count": sum(value == "D1" for value in owners.values()),
                "ownership_path": str(output.relative_to(ROOT)),
                "ownership_sha256": sha256(output),
                "status": "PASS",
            }
            rows.append(row)
            outputs[f"seed{seed}_{condition}"] = row
    return rows, outputs


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows, outputs = build()
    write_csv(
        OUT / "raw_runs.csv",
        rows,
        list(rows[0]),
    )
    sources = source_paths()
    metadata = {
        "schema": "setp.e7.responsibility_scenarios.v1",
        "contract_id": CONTRACT_ID,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "conditions": {
            "geographic": (
                "Existing and newly added customers are assigned to the nearest depot."
            ),
            "historical_mixed": (
                "Existing customers reuse the frozen E3 mixed map; every added customer "
                "inherits its frozen donor customer's owner from the E3 200-customer "
                "mixed map."
            ),
        },
        "pre_registration": (
            "Both conditions and all five streams are retained regardless of later "
            "routing results. No search output is read during construction."
        ),
        "source_files": {
            name: {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path),
            }
            for name, path in sources.items()
        },
    }
    write_json(OUT / "metadata.json", metadata)
    write_json(
        OUT / "decision.json",
        {
            "verdict": "E7_RESPONSIBILITY_SCENARIOS_PASS",
            "formal_use_allowed": True,
            "conditions": list(CONDITIONS),
            "stream_count": len(STREAMS),
            "output_count": len(outputs),
            "base_owner_changes_from_geographic": max(
                int(row["base_owner_changes_from_geographic"]) for row in rows
            ),
            "new_owner_changes_from_nearest_by_stream": {
                str(seed): next(
                    int(row["new_owner_changes_from_nearest"])
                    for row in rows
                    if row["stream_seed"] == seed
                    and row["condition"] == "historical_mixed"
                )
                for seed in STREAMS
            },
        },
    )
    report = [
        "# E7客户责任情形设计",
        "",
        "本设计在正式动态搜索前固定两类经营情形。地理情形沿用最近车场责任；历史交错情形沿用E3已冻结的两张客户责任表，不重新抽样，也不读取任何路线结果。",
        "",
        f"历史交错情形中，初始{len(load_owners(sources['base_geographic']))}名客户有{max(int(row['base_owner_changes_from_geographic']) for row in rows)}名与最近车场责任不同；五条订单流中，新增客户分别有"
        + "、".join(
            str(
                next(
                    int(row["new_owner_changes_from_nearest"])
                    for row in rows
                    if row["stream_seed"] == seed
                    and row["condition"] == "historical_mixed"
                )
            )
            for seed in STREAMS
        )
        + "名延续历史客户关系而非最近车场责任。两类情形和全部订单流均须报告，后续结果方向不参与保留或删除决定。",
    ]
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    artifact_hashes = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", artifact_hashes)
    print(json.dumps(json.loads((OUT / "decision.json").read_text()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
