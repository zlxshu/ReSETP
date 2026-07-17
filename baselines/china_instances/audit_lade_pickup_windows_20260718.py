"""Audit observed LaDe-P Chongqing pickup windows without proposing a generator."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SOURCE = (
    REPO
    / "data/ChinaInstances/open_sources_20260717"
    / "huggingface_Cainiao-AI_LaDe/pickup_cq.csv"
)
SOURCE_METADATA = SOURCE.parent / "SOURCE_METADATA.json"
OUTPUT = REPO / "data/ChinaInstances/china_lade_pickup_window_audit_20260718"
EXPECTED_SHA256 = "d58248d1aca9cf155bd202f311dff73f8562174d4e4041160a3996878143b056"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_time(value: str) -> datetime:
    return datetime.strptime(f"2000-{value}", "%Y-%m-%d %H:%M:%S")


def quantile_from_counter(counter: Counter[int], probability: float) -> float | None:
    total = sum(counter.values())
    if total == 0:
        return None
    target = probability * (total - 1)
    lower_rank = int(target)
    upper_rank = min(lower_rank + 1, total - 1)

    def at_rank(rank: int) -> int:
        cumulative = 0
        for value, count in sorted(counter.items()):
            cumulative += count
            if cumulative > rank:
                return value
        raise RuntimeError("counter rank lookup failed")

    lower = at_rank(lower_rank)
    upper = at_rank(upper_rank)
    return lower + (target - lower_rank) * (upper - lower)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_hash = sha256(SOURCE)
    errors: list[str] = []
    if source_hash != EXPECTED_SHA256:
        errors.append(f"SOURCE_SHA256_MISMATCH:{source_hash}")

    required = {
        "order_id",
        "city",
        "courier_id",
        "accept_time",
        "time_window_start",
        "time_window_end",
        "pickup_time",
        "aoi_id",
        "ds",
    }
    rows = 0
    malformed = 0
    cities: Counter[str] = Counter()
    couriers: set[str] = set()
    aois: set[str] = set()
    dates: set[str] = set()
    width_minutes: Counter[int] = Counter()
    start_minute_of_day: Counter[int] = Counter()
    pickup_observed = 0
    pickup_inside_inclusive = 0
    pickup_before = 0
    pickup_after = 0
    accept_to_window_start_minutes: Counter[int] = Counter()
    window_start_to_pickup_minutes: Counter[int] = Counter()

    with SOURCE.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            errors.append(f"SCHEMA_MISSING:{sorted(required - set(reader.fieldnames or []))}")
        else:
            for row in reader:
                rows += 1
                try:
                    start = parse_time(row["time_window_start"])
                    end = parse_time(row["time_window_end"])
                    accept = parse_time(row["accept_time"])
                except (ValueError, TypeError):
                    malformed += 1
                    continue
                width = int(round((end - start).total_seconds() / 60))
                accept_gap = int(round((start - accept).total_seconds() / 60))
                if width < 0:
                    malformed += 1
                    continue
                width_minutes[width] += 1
                start_minute_of_day[start.hour * 60 + start.minute] += 1
                accept_to_window_start_minutes[accept_gap] += 1
                cities[row["city"]] += 1
                couriers.add(row["courier_id"])
                aois.add(row["aoi_id"])
                dates.add(row["ds"])
                if row["pickup_time"]:
                    try:
                        pickup = parse_time(row["pickup_time"])
                    except ValueError:
                        malformed += 1
                        continue
                    pickup_observed += 1
                    window_start_to_pickup_minutes[
                        int(round((pickup - start).total_seconds() / 60))
                    ] += 1
                    if pickup < start:
                        pickup_before += 1
                    elif pickup > end:
                        pickup_after += 1
                    else:
                        pickup_inside_inclusive += 1

    if rows == 0:
        errors.append("NO_ROWS")
    if set(cities) != {"Chongqing"}:
        errors.append(f"CITY_SCOPE_UNEXPECTED:{dict(cities)}")

    def distribution(counter: Counter[int]) -> dict[str, Any]:
        return {
            "n": sum(counter.values()),
            "unique_values": len(counter),
            "min": min(counter) if counter else None,
            "p05": quantile_from_counter(counter, 0.05),
            "p25": quantile_from_counter(counter, 0.25),
            "median": quantile_from_counter(counter, 0.50),
            "p75": quantile_from_counter(counter, 0.75),
            "p95": quantile_from_counter(counter, 0.95),
            "max": max(counter) if counter else None,
        }

    summary = {
        "schema": "resetp.china.lade-pickup-window-audit.v1",
        "source": {
            "path": str(SOURCE.relative_to(REPO)),
            "sha256": source_hash,
            "repository": "Cainiao-AI/LaDe",
            "repository_revision": json.loads(SOURCE_METADATA.read_text(encoding="utf-8")).get("sha"),
            "declared_license_card": "Apache-2.0",
            "license_boundary": "repository card and README wording must both be reported; no formal generator adoption here",
        },
        "scope": {
            "scenario": "pickup",
            "city": "Chongqing",
            "rows": rows,
            "unique_couriers": len(couriers),
            "unique_aois": len(aois),
            "unique_ds_dates": len(dates),
            "malformed_rows": malformed,
        },
        "observed_distributions": {
            "window_width_minutes": distribution(width_minutes),
            "window_start_minute_from_midnight": distribution(start_minute_of_day),
            "accept_to_window_start_minutes": distribution(accept_to_window_start_minutes),
            "window_start_to_pickup_minutes": distribution(window_start_to_pickup_minutes),
        },
        "pickup_completion": {
            "pickup_time_observed": pickup_observed,
            "inside_window_inclusive": pickup_inside_inclusive,
            "before_window": pickup_before,
            "after_window": pickup_after,
            "inside_share": (
                pickup_inside_inclusive / pickup_observed if pickup_observed else None
            ),
        },
        "scientific_boundary": (
            "These are observed Chinese platform pickup windows and pickup timestamps. "
            "They are not delivery promise windows, shipment weights, service durations, "
            "depot operations or a formal instance generator."
        ),
    }
    write_json(OUTPUT / "summary.json", summary)

    with (OUTPUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value", "count"])
        writer.writeheader()
        for metric, counter in (
            ("window_width_minutes", width_minutes),
            ("window_start_minute_from_midnight", start_minute_of_day),
        ):
            for value, count in sorted(counter.items()):
                writer.writerow({"metric": metric, "value": value, "count": count})

    verdict = "PASS_OBSERVED_PICKUP_WINDOW_EVIDENCE_AUDIT" if not errors else "HALT_DATA_AUDIT"
    write_json(
        OUTPUT / "decision.json",
        {
            "schema": "resetp.china.lade-pickup-window-audit-decision.v1",
            "verdict": verdict,
            "formal_search_allowed": False,
            "formal_generator_method_approved": False,
            "errors": errors,
            "rows": rows,
        },
    )
    write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.china.lade-pickup-window-audit-metadata.v1",
            "script": str(Path(__file__).resolve().relative_to(REPO)),
            "search_evaluations": 0,
            "descriptive_audit_only": True,
        },
    )
    (OUTPUT / "report.md").write_text(
        f"""# LaDe-P 重庆取件时间窗事实审计

判决：`{verdict}`。本任务只做原始数据质量和描述统计，不提出或批准正式生成方法。

数据共{rows}条，全部城市字段为重庆，覆盖{len(couriers)}名配送员、{len(aois)}个AOI和{len(dates)}个日期编码。时间窗宽度中位数为{summary["observed_distributions"]["window_width_minutes"]["median"]}分钟，范围为{summary["observed_distributions"]["window_width_minutes"]["min"]}--{summary["observed_distributions"]["window_width_minutes"]["max"]}分钟。

有取件完成时刻的记录为{pickup_observed}条，其中闭区间内完成{pickup_inside_inclusive}条、早于窗口{pickup_before}条、晚于窗口{pickup_after}条。该完成率是平台取件事实描述，不是模型服务水平目标。

这些字段只能称中国平台取件时间窗与取件时刻，不能冒充配送承诺窗、需求重量、服务时长、车场运营或正式算例生成器。任何把该分布用于正式算例的方法仍须用户批准。
""",
        encoding="utf-8",
    )
    artifacts = {}
    for path in sorted(OUTPUT.iterdir()):
        if path.is_file() and path.name != "artifact_hashes.json":
            artifacts[path.name] = sha256(path)
    write_json(
        OUTPUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "artifacts": artifacts,
        },
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
