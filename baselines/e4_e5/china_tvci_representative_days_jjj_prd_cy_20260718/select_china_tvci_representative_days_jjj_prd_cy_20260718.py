#!/usr/bin/env python3
"""Blind quarterly representative-day selection for three China TVCI curves.

The only data input is the frozen 2025 48-slot wide TVCI CSV.  The module has
no solver, route, price, or experiment-result dependency by design.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

REGIONS = ("Beijing", "Guangdong", "Chongqing")
SELECTION_RULES = (
    "median_daily_mean",
    "maximum_intraday_range",
    "minimum_intraday_range",
)
SLOTS_PER_DAY = 48
SOURCE_YEAR = 2025


@dataclass(frozen=True)
class DailyMetric:
    region: str
    date: date
    day_index: int
    daily_mean: float
    intraday_range: float
    daily_min: float
    daily_max: float


def _quarter(day: date) -> int:
    return (day.month - 1) // 3 + 1


def load_daily_metrics(source_path: Path) -> dict[str, list[DailyMetric]]:
    """Read and validate only the fixed 2025 48-slot source."""

    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    values: dict[str, dict[date, list[float]]] = {
        region: defaultdict(list) for region in REGIONS
    }
    day_indices: dict[date, int] = {}
    slot_ids: dict[date, list[int]] = defaultdict(list)
    row_count = 0

    with source_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("source CSV has no header")
        required = {"date", "day_index", "hourly_calendar_row", *REGIONS}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"source CSV missing columns: {sorted(missing)}")

        for row in reader:
            row_count += 1
            day = date.fromisoformat(row["date"])
            if day.year != SOURCE_YEAR:
                raise ValueError(f"unexpected source year: {day}")
            day_index = int(row["day_index"])
            slot = int(row["hourly_calendar_row"])
            if not 1 <= slot <= SLOTS_PER_DAY:
                raise ValueError(f"invalid half-hour slot {slot} on {day}")
            prior_index = day_indices.setdefault(day, day_index)
            if prior_index != day_index:
                raise ValueError(f"day index changes within {day}")
            slot_ids[day].append(slot)
            for region in REGIONS:
                value = float(row[region])
                if not math.isfinite(value):
                    raise ValueError(f"non-finite {region} value on {day}")
                values[region][day].append(value)

    expected_dates = {
        date(SOURCE_YEAR, 1, 1).fromordinal(
            date(SOURCE_YEAR, 1, 1).toordinal() + offset
        )
        for offset in range(365)
    }
    if set(day_indices) != expected_dates:
        raise ValueError("source dates are not the complete 2025 calendar")
    if row_count != 365 * SLOTS_PER_DAY:
        raise ValueError(f"expected 17520 rows, observed {row_count}")

    metrics: dict[str, list[DailyMetric]] = {region: [] for region in REGIONS}
    for day in sorted(expected_dates):
        slots = slot_ids[day]
        if sorted(slots) != list(range(1, SLOTS_PER_DAY + 1)):
            raise ValueError(f"slot conservation failed on {day}")
        for region in REGIONS:
            day_values = values[region][day]
            if len(day_values) != SLOTS_PER_DAY:
                raise ValueError(f"{region} has {len(day_values)} slots on {day}")
            # The frozen source was made by copying each hourly value twice.
            for left, right in zip(day_values[::2], day_values[1::2]):
                if not math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12):
                    raise ValueError(f"half-hour duplication failed for {region} on {day}")
            daily_min = min(day_values)
            daily_max = max(day_values)
            metrics[region].append(
                DailyMetric(
                    region=region,
                    date=day,
                    day_index=day_indices[day],
                    daily_mean=sum(day_values) / SLOTS_PER_DAY,
                    intraday_range=daily_max - daily_min,
                    daily_min=daily_min,
                    daily_max=daily_max,
                )
            )
    return metrics


def choose_metric(quarter_metrics: Iterable[DailyMetric], rule: str) -> DailyMetric:
    candidates = list(quarter_metrics)
    if not candidates:
        raise ValueError("empty quarter")
    if rule == "median_daily_mean":
        target = statistics.median(metric.daily_mean for metric in candidates)
        return min(candidates, key=lambda metric: (abs(metric.daily_mean - target), metric.date))
    if rule == "maximum_intraday_range":
        return min(candidates, key=lambda metric: (-metric.intraday_range, metric.date))
    if rule == "minimum_intraday_range":
        return min(candidates, key=lambda metric: (metric.intraday_range, metric.date))
    raise ValueError(f"unknown selection rule: {rule}")


def select_representative_days(
    metrics_by_region: dict[str, list[DailyMetric]],
) -> list[dict[str, object]]:
    """Apply the Shanghai four-quarter, three-rule contract verbatim."""

    selected: list[dict[str, object]] = []
    for region in REGIONS:
        metrics = metrics_by_region[region]
        if len(metrics) != 365:
            raise ValueError(f"{region} expected 365 daily metrics")
        for quarter in range(1, 5):
            quarter_metrics = [
                metric for metric in metrics if _quarter(metric.date) == quarter
            ]
            for rule in SELECTION_RULES:
                metric = choose_metric(quarter_metrics, rule)
                selected.append(
                    {
                        "region": region,
                        "quarter": quarter,
                        "selection_rule": rule,
                        "date": metric.date.isoformat(),
                        "day_index": metric.day_index,
                        "daily_mean_tCO2_per_MWh": f"{metric.daily_mean:.8f}",
                        "intraday_range_tCO2_per_MWh": f"{metric.intraday_range:.8f}",
                        "daily_min_tCO2_per_MWh": f"{metric.daily_min:.8f}",
                        "daily_max_tCO2_per_MWh": f"{metric.daily_max:.8f}",
                        "result_blind_selection": 1,
                    }
                )
    return selected


def write_selection(rows: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "region",
        "quarter",
        "selection_rule",
        "date",
        "day_index",
        "daily_mean_tCO2_per_MWh",
        "intraday_range_tCO2_per_MWh",
        "daily_min_tCO2_per_MWh",
        "daily_max_tCO2_per_MWh",
        "result_blind_selection",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metrics = load_daily_metrics(args.source)
    rows = select_representative_days(metrics)
    if len(rows) != len(REGIONS) * 4 * len(SELECTION_RULES):
        raise ValueError(f"expected 36 selected rows, observed {len(rows)}")
    write_selection(rows, args.output)
    print(f"selected_rows={len(rows)} source={args.source} output={args.output}")


if __name__ == "__main__":
    main()
