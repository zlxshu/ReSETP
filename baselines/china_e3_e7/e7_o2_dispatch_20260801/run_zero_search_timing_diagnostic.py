#!/usr/bin/env python3
"""Check how much dispatch waiting each frozen H0/G2 order can tolerate."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for entry in (ROOT, ROOT / "solver/src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime import load_bundle
from baselines.china_e3_e7.e7_h0_g2_foundation_20260801.stream import build_h0_g2_stream
from baselines.china_e3_e7.e7_o1_replanning_20260801.diagnose_fixed30_count20_failure import (
    canonical_sha256,
    route_clock,
    sha256,
    write_csv,
    write_json,
)
from setp_solver.solution import Route


INSTANCES = (
    "cn-prd-50c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
    "cn-prd-150c-01-V2-LOCATIONS",
)
SEEDS = (1, 2, 3, 4, 5)
WAITS_MINUTES = (0, 10, 20, 30)
EXPECTED_ORDERS = dict(zip(INSTANCES, (10, 20, 30), strict=True))
DEFAULT_OUTPUT = HERE / "zero_search_15_streams_20260801"
HASHED_FILES = ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
STREAM_SOURCE = ROOT / "baselines/china_e3_e7/e7_h0_g2_foundation_20260801/stream.py"
CLOCK_SOURCE = (
    ROOT
    / "baselines/china_e3_e7/e7_o1_replanning_20260801"
    / "diagnose_fixed30_count20_failure.py"
)


def stream_sha256(stream: Any) -> str:
    return canonical_sha256(
        {
            "instance_id": stream.instance_id,
            "stream_seed": stream.stream_seed,
            "initial_customer_ids": list(stream.initial_customer_ids),
            "events": [asdict(event) for event in stream.events],
        }
    )


def legal_asset_classes(bundle: Any) -> list[tuple[str, str, int]]:
    classes: list[tuple[str, str, int]] = []
    for depot, caps in sorted(bundle.fleet_caps_by_depot.items()):
        for vehicle_type, key in (("cv", "num_cv"), ("ev", "num_ev")):
            count = int(caps[key])
            if count > 0:
                classes.append((depot, vehicle_type, count))
    return classes


def order_row(bundle: Any, stream: Any, event: Any, stream_hash: str) -> dict[str, Any]:
    candidates = []
    for depot, vehicle_type, fleet_count in legal_asset_classes(bundle):
        route = Route(
            f"CLOCK-{depot}-{vehicle_type}-{event.customer_id}",
            vehicle_type,
            depot,
            [depot, str(event.customer_id), depot],
        )
        preferred, latest = route_clock(route, bundle.instance, bundle.prices)
        candidates.append(
            {
                "depot_id": depot,
                "vehicle_type": vehicle_type,
                "fleet_count": fleet_count,
                "preferred_departure_second": preferred,
                "latest_departure_second": latest,
            }
        )
    best = max(candidates, key=lambda candidate: candidate["latest_departure_second"])
    appearance = float(event.t_appear)
    row: dict[str, Any] = {
        "instance_id": stream.instance_id,
        "stream_seed": stream.stream_seed,
        "stream_sha256": stream_hash,
        "event_id": event.event_id,
        "customer_id": event.customer_id,
        "demand_kg": event.new_demand,
        "appearance_second": appearance,
        "ready_second": event.new_ready_time,
        "due_second": event.new_due_time,
        "service_second": event.new_service_time,
        "candidate_count": len(candidates),
        "best_depot_id": best["depot_id"],
        "best_vehicle_type": best["vehicle_type"],
        "best_latest_departure_second": best["latest_departure_second"],
        "best_slack_at_appearance_seconds": best["latest_departure_second"] - appearance,
        "depot_type_clocks_json": json.dumps(
            candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    }
    for wait in WAITS_MINUTES:
        margin = float(best["latest_departure_second"]) - appearance - wait * 60.0
        row[f"margin_after_wait_{wait}m_seconds"] = margin
        row[f"feasible_after_wait_{wait}m"] = margin >= -1e-9
    return row


def build_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    streams: list[dict[str, Any]] = []
    for instance_id in INSTANCES:
        bundle = load_bundle(instance_id)
        for seed in SEEDS:
            stream = build_h0_g2_stream(bundle.instance, instance_id=instance_id, stream_seed=seed)
            digest = stream_sha256(stream)
            if len(stream.events) != EXPECTED_ORDERS[instance_id]:
                raise RuntimeError(f"unexpected event count for {instance_id} seed {seed}")
            streams.append(
                {
                    "instance_id": instance_id,
                    "stream_seed": seed,
                    "event_count": len(stream.events),
                    "stream_sha256": digest,
                }
            )
            rows.extend(order_row(bundle, stream, event, digest) for event in stream.events)
    return rows, streams


def summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for instance_id in (*INSTANCES, "ALL"):
        selected = [row for row in rows if instance_id == "ALL" or row["instance_id"] == instance_id]
        item: dict[str, Any] = {"instance_id": instance_id, "order_count": len(selected)}
        for wait in WAITS_MINUTES:
            count = sum(bool(row[f"feasible_after_wait_{wait}m"]) for row in selected)
            item[f"feasible_after_wait_{wait}m_count"] = count
            item[f"feasible_after_wait_{wait}m_pct"] = 100.0 * count / len(selected)
        result.append(item)
    return result


def render_report(rows: Sequence[Mapping[str, Any]], summaries: Sequence[Mapping[str, Any]]) -> str:
    tightest = min(rows, key=lambda row: float(row["best_slack_at_appearance_seconds"]))
    lines = [
        "# E7-O2 发车等待零搜索体检",
        "",
        "## 结论",
        "",
        "本体检只回答一个问题：订单出现以后，若从合法车场直接派一辆现有车型去服务，立即出发或再等10、20、30分钟是否还赶得上。没有运行求解器，也没有决定O2正式发车规则。",
        "",
        "| 规模 | 订单 | 立即可达 | 等10分钟 | 等20分钟 | 等30分钟 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        label = "合计" if item["instance_id"] == "ALL" else str(item["instance_id"]).split("-")[2]
        lines.append(
            f"| {label} | {item['order_count']} | "
            + " | ".join(
                f"{item[f'feasible_after_wait_{wait}m_count']} ({item[f'feasible_after_wait_{wait}m_pct']:.1f}%)"
                for wait in WAITS_MINUTES
            )
            + " |"
        )
    lines += [
        "",
        "## 最紧订单",
        "",
        f"最紧的是 {tightest['instance_id']}、流 {tightest['stream_seed']} 的 {tightest['customer_id']}。订单出现时，从所有合法车场和车型中取最宽松方案后，只剩 {float(tightest['best_slack_at_appearance_seconds']) / 60.0:.3f} 分钟可等。",
        "",
        "## 口径",
        "",
        "每个订单都保留，raw_runs.csv 共300行。每行同时保存所有合法车场—车型的最迟发车时刻以及最宽松值。时间计算直接复用O1失败诊断的路网与倒推时钟函数。30分钟只是本次体检的观察点，不是O2正式上限；D1、D2、等待损失和正式求解均未进入。",
    ]
    return "\n".join(lines) + "\n"


def generate(output: Path) -> None:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite {output}")
    rows, streams = build_rows()
    summaries = summary(rows)
    metadata = {
        "schema": "resetp.e7-o2-zero-search-timing-diagnostic.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "formal_result": False,
        "zero_search": True,
        "o2_effect_experiment": False,
        "instances": list(INSTANCES),
        "stream_seeds": list(SEEDS),
        "stream_count": len(streams),
        "streams": streams,
        "wait_observation_minutes": list(WAITS_MINUTES),
        "raw_row_count": len(rows),
        "source_sha256": {
            str(STREAM_SOURCE.relative_to(ROOT)): sha256(STREAM_SOURCE),
            str(CLOCK_SOURCE.relative_to(ROOT)): sha256(CLOCK_SOURCE),
            str(Path(__file__).relative_to(ROOT)): sha256(Path(__file__)),
        },
        "generation_command": "PYTHONPATH=solver/src:. build/python_envs/pyvrp-hgs-0.12.2/bin/python "
        "baselines/china_e3_e7/e7_o2_dispatch_20260801/run_zero_search_timing_diagnostic.py",
        "check_command": "PYTHONPATH=solver/src:. build/python_envs/pyvrp-hgs-0.12.2/bin/python "
        "baselines/china_e3_e7/e7_o2_dispatch_20260801/run_zero_search_timing_diagnostic.py --check",
    }
    decision = {
        "status": "PASS_E7_O2_ZERO_SEARCH_TIMING_DIAGNOSTIC",
        "formal_result": False,
        "all_orders_retained": len(rows) == 300,
        "stream_count": len(streams),
        "order_count": len(rows),
        "summary": summaries,
        "solver_runs": 0,
        "search_evaluations": 0,
        "o2_started": False,
        "o2_effect_experiment": False,
        "d1_selected": False,
        "d2_selected": False,
        "waiting_loss_used": False,
        "formal_30_minute_limit_selected": False,
    }
    output.mkdir(parents=True)
    write_json(output / "metadata.json", metadata)
    write_csv(output / "raw_runs.csv", rows)
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(render_report(rows, summaries), encoding="utf-8")
    write_json(output / "artifact_hashes.json", {name: sha256(output / name) for name in HASHED_FILES})


def check(output: Path) -> None:
    hashes = json.loads((output / "artifact_hashes.json").read_text(encoding="utf-8"))
    if set(hashes) != set(HASHED_FILES) or any(sha256(output / name) != digest for name, digest in hashes.items()):
        raise RuntimeError("artifact hashes do not close")
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    decision = json.loads((output / "decision.json").read_text(encoding="utf-8"))
    with (output / "raw_runs.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if metadata["formal_result"] or decision["formal_result"] or len(rows) != 300:
        raise RuntimeError("scope or row count is wrong")
    expected_streams = {(instance, seed) for instance in INSTANCES for seed in SEEDS}
    actual_streams = {(row["instance_id"], int(row["stream_seed"])) for row in rows}
    if actual_streams != expected_streams:
        raise RuntimeError("15-stream coverage is wrong")
    rebuilt_rows, rebuilt_streams = build_rows()
    if [row["stream_sha256"] for row in metadata["streams"]] != [row["stream_sha256"] for row in rebuilt_streams]:
        raise RuntimeError("H0/G2 stream hashes changed")
    rebuilt = {(str(row["instance_id"]), int(row["stream_seed"]), str(row["event_id"])): row for row in rebuilt_rows}
    for row in rows:
        key = (row["instance_id"], int(row["stream_seed"]), row["event_id"])
        source = rebuilt[key]
        clocks = json.loads(row["depot_type_clocks_json"])
        latest = max(float(clock["latest_departure_second"]) for clock in clocks)
        appearance = float(row["appearance_second"])
        if abs(latest - float(row["best_latest_departure_second"])) > 1e-9:
            raise RuntimeError(f"best clock arithmetic failed for {key}")
        if len(clocks) != int(row["candidate_count"]) or row["stream_sha256"] != source["stream_sha256"]:
            raise RuntimeError(f"candidate or stream evidence failed for {key}")
        for wait in WAITS_MINUTES:
            margin = latest - appearance - wait * 60.0
            stored = float(row[f"margin_after_wait_{wait}m_seconds"])
            feasible = row[f"feasible_after_wait_{wait}m"] == "True"
            if abs(margin - stored) > 1e-9 or feasible != (margin >= -1e-9):
                raise RuntimeError(f"wait arithmetic failed for {key} at {wait}m")
    for relative, digest in metadata["source_sha256"].items():
        if sha256(ROOT / relative) != digest:
            raise RuntimeError(f"source changed: {relative}")
    print("PASS_E7_O2_ZERO_SEARCH_TIMING_DIAGNOSTIC_CHECK")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    check(output) if args.check else generate(output)


if __name__ == "__main__":
    main()
