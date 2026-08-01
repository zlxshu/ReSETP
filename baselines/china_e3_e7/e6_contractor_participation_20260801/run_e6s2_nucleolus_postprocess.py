#!/usr/bin/env python3
"""Compute the approved E6-S2 nucleolus from the frozen 15-coalition panel."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for path in (HERE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from e6_cooperative_game import Coalition, coalitions, core_violations, nucleolus

SOURCE = HERE / "formal_e6a_panel_20260801"
OUTPUT = HERE / "formal_e6s2_nucleolus_20260801"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_game(raw: dict[str, float], members: tuple[str, ...]) -> dict[Coalition, float]:
    values = {
        tuple(sorted(name.split("+"))): float(value)
        for name, value in raw.items()
    }
    expected = set(coalitions(members))
    if set(values) != expected:
        raise RuntimeError("settlement file does not contain the complete 15-coalition game")
    return values


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"output already exists: {OUTPUT}")
    OUTPUT.mkdir(parents=False)

    rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    source_hashes: dict[str, str] = {}
    settlement_files = sorted(SOURCE.glob("units/*/seed_*/settlement_results.json"))
    if len(settlement_files) != 60:
        raise RuntimeError(f"expected 60 settlement files, found {len(settlement_files)}")

    for source in settlement_files:
        relative = source.relative_to(SOURCE)
        instance_id = relative.parts[1]
        seed = int(relative.parts[2].split("_")[-1])
        payload = json.loads(source.read_text(encoding="utf-8"))
        members = tuple(sorted(payload["standalone_profit_cny"]))
        profits = parse_game(payload["coalition_profit_cny"], members)
        costs = parse_game(payload["coalition_cost_cny"], members)
        allocation = nucleolus(profits, members)
        violations = core_violations(allocation, profits, members)
        if violations:
            raise RuntimeError(f"nucleolus is outside the core: {instance_id} seed {seed}")
        if abs(sum(allocation.values()) - profits[members]) > 1e-6:
            raise RuntimeError("nucleolus profit allocation does not close")

        standalone = {member: float(payload["standalone_profit_cny"][member]) for member in members}
        owned_revenue = {
            member: profits[(member,)] + costs[(member,)] for member in members
        }
        cost_share = {
            member: owned_revenue[member] - allocation[member] for member in members
        }
        if abs(sum(cost_share.values()) - costs[members]) > 1e-6:
            raise RuntimeError("nucleolus cost shares do not close")

        shapley = {
            member: float(payload["method_A"]["shapley_profit_cny"][member])
            for member in members
        }
        min_gain = min(allocation[member] - standalone[member] for member in members)
        summaries.append(
            {
                "instance_id": instance_id,
                "seed": seed,
                "nucleolus_in_core": True,
                "shapley_in_core": not core_violations(shapley, profits, members),
                "minimum_member_gain_over_standalone_cny": min_gain,
                "maximum_abs_profit_difference_from_shapley_cny": max(
                    abs(allocation[member] - shapley[member]) for member in members
                ),
            }
        )
        for member in members:
            rows.append(
                {
                    "instance_id": instance_id,
                    "seed": seed,
                    "contractor": member,
                    "standalone_profit_cny": standalone[member],
                    "shapley_profit_cny": shapley[member],
                    "nucleolus_profit_cny": allocation[member],
                    "nucleolus_cost_share_cny": cost_share[member],
                    "nucleolus_gain_over_standalone_cny": allocation[member] - standalone[member],
                    "nucleolus_minus_shapley_cny": allocation[member] - shapley[member],
                }
            )
        source_hashes[str(relative)] = sha256(source)

    fields = list(rows[0])
    with (OUTPUT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    min_gains = [float(row["minimum_member_gain_over_standalone_cny"]) for row in summaries]
    differences = [float(row["maximum_abs_profit_difference_from_shapley_cny"]) for row in summaries]
    decision = {
        "schema": "resetp.e6s2-nucleolus-decision.v1",
        "status": "PASS_E6S2_NUCLEOLUS_COMPLETE",
        "unit_count": len(summaries),
        "member_rows": len(rows),
        "nucleolus_in_core_units": sum(bool(row["nucleolus_in_core"]) for row in summaries),
        "shapley_in_core_units": sum(bool(row["shapley_in_core"]) for row in summaries),
        "minimum_member_gain_over_standalone_cny": min(min_gains),
        "mean_of_unit_minimum_member_gain_cny": sum(min_gains) / len(min_gains),
        "maximum_abs_profit_difference_from_shapley_cny": max(differences),
        "units": summaries,
    }
    metadata = {
        "schema": "resetp.e6s2-nucleolus-metadata.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_panel": str(SOURCE.relative_to(REPO)),
        "source_settlement_sha256": source_hashes,
        "route_search_executed": False,
        "solver_reruns": 0,
        "postprocess_source_sha256": {
            "run_e6s2_nucleolus_postprocess.py": sha256(Path(__file__).resolve()),
            "e6_cooperative_game.py": sha256(HERE / "e6_cooperative_game.py"),
        },
        "allocation_method": "exact sequential linear-programming nucleolus",
        "game": "four-contractor transferable-utility profit game",
    }
    write_json(OUTPUT / "metadata.json", metadata)
    write_json(OUTPUT / "decision.json", decision)
    report = (
        "# E6-S2 核仁分配\n\n"
        "状态：PASS_E6S2_NUCLEOLUS_COMPLETE。\n\n"
        f"直接读取原 E6 正式面板的 60 个完整联盟账本，没有重跑路线。核仁在核内 "
        f"{decision['nucleolus_in_core_units']}/60；原 Shapley 在核内 "
        f"{decision['shapley_in_core_units']}/60。\n\n"
        "核仁相对各家单干利润的最小增益，在全部承包商与单元中的最小值为 "
        f"{decision['minimum_member_gain_over_standalone_cny']:.3f} 元；"
        "60 个单元各自最弱成员增益的均值为 "
        f"{decision['mean_of_unit_minimum_member_gain_cny']:.3f} 元。\n\n"
        "这里的作用是给出唯一且满足所有子联盟稳定条件的分法；Shapley 保留为对照。"
        "本步骤只改变事后分账，不改变客户分配、车辆路线或合作总收益。\n"
        "\n后处理脚本与核仁计算模块的 SHA-256 已登记在 metadata.json。\n"
    )
    (OUTPUT / "report.md").write_text(report, encoding="utf-8")
    artifacts = {
        name: sha256(OUTPUT / name)
        for name in ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
    }
    write_json(
        OUTPUT / "artifact_hashes.json",
        {"schema": "resetp.artifact-hashes.v1", "artifacts": artifacts},
    )


if __name__ == "__main__":
    main()
