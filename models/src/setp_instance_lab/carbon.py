from __future__ import annotations

import csv
from collections import Counter, defaultdict
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SLOT_SECONDS = 1800
VALID_ALIGNMENT_MODES = {"none", "fixed_utc_anchor", "daily_profile", "first_csv_record"}

_DATETIME_COL = "Datetime (UTC)"
_ACTUAL_COL = "Actual Carbon Intensity (gCO2/kWh)"
_FORECAST_COL = "Forecast Carbon Intensity (gCO2/kWh)"
_INDEX_COL = "Index"
_INDEX_CODES = {
    "very low": 0,
    "low": 1,
    "moderate": 2,
    "high": 3,
    "very high": 4,
}


def load_carbon_profile(
    csv_path: str,
    alignment_mode: str,
    anchor_utc: str | None,
    n_slots: int,
) -> list[dict[str, Any]]:
    mode = _normalize_mode(alignment_mode)
    if mode == "none":
        return []
    if n_slots <= 0:
        raise ValueError(f"n_slots must be positive, got {n_slots}")

    rows = _read_rows(csv_path)
    if not rows:
        raise ValueError(f"No valid carbon intensity rows found in {csv_path}")

    if mode == "fixed_utc_anchor":
        if not anchor_utc:
            raise ValueError("carbon_time_anchor_utc is required for fixed_utc_anchor mode")
        anchor = _parse_utc_datetime(anchor_utc)
        return _build_fixed_profile(rows, anchor, n_slots)
    if mode == "first_csv_record":
        anchor = rows[0]["datetime_utc"]
        print(f"using first_csv_record mode, anchor = {_format_utc(anchor)}")
        return _build_fixed_profile(rows, anchor, n_slots)
    if mode == "daily_profile":
        anchor = _parse_utc_datetime(anchor_utc) if anchor_utc else rows[0]["datetime_utc"]
        return _build_daily_profile(rows, anchor, n_slots)

    raise ValueError(f"Unsupported carbon alignment mode: {alignment_mode}")


def carbon_profile_metadata(
    profile: list[dict[str, Any]],
    *,
    alignment_mode: str,
    source_path: str,
    anchor_utc: str | None = None,
) -> dict[str, Any]:
    if not profile:
        return {}
    anchor = _parse_utc_datetime(anchor_utc) if anchor_utc else profile[0]["datetime_utc"]
    return {
        "carbon_alignment_mode": alignment_mode,
        "carbon_time_anchor_utc": _format_utc(anchor),
        "carbon_profile_source": str(source_path),
        "carbon_n_slots": len(profile),
        "carbon_unit": "gCO2/kWh",
        "carbon_slot_seconds": SLOT_SECONDS,
    }


def _normalize_mode(raw: str | None) -> str:
    mode = (raw or "none").strip().lower()
    if mode not in VALID_ALIGNMENT_MODES:
        raise ValueError(f"Unsupported carbon alignment mode: {raw}")
    return mode


def _read_rows(csv_path: str) -> list[dict[str, Any]]:
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Carbon profile CSV not found: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        standard_missing = {_DATETIME_COL, _ACTUAL_COL, _FORECAST_COL, _INDEX_COL} - fieldnames
        if not standard_missing:
            for line_no, row in enumerate(reader, start=2):
                try:
                    label = str(row[_INDEX_COL]).strip()
                    rows.append(
                        {
                            "datetime_utc": _parse_utc_datetime(str(row[_DATETIME_COL])),
                            "actual_gco2_per_kwh": float(row[_ACTUAL_COL]),
                            "forecast_gco2_per_kwh": float(row[_FORECAST_COL]),
                            "index_label": label,
                            "index_code": _index_code(label),
                        }
                    )
                except ValueError as exc:
                    raise ValueError(f"Invalid carbon CSV row {line_no}: {exc}") from exc
                except (TypeError, KeyError) as exc:
                    raise ValueError(f"Invalid carbon CSV row {line_no}: {exc}") from exc
        elif {"from", "forecast", "index"} <= fieldnames:
            # v2026-06-12: Q1 regional NESO CSV has one row per DNO region and
            # no actual column; use the existing regional口径 as all-region
            # average forecast by half-hour timestamp.
            buckets: dict[datetime, list[float]] = defaultdict(list)
            labels: dict[datetime, list[str]] = defaultdict(list)
            for line_no, row in enumerate(reader, start=2):
                try:
                    stamp = _parse_utc_datetime(str(row["from"]))
                    buckets[stamp].append(float(row["forecast"]))
                    labels[stamp].append(str(row["index"]).strip())
                except ValueError as exc:
                    raise ValueError(f"Invalid regional carbon CSV row {line_no}: {exc}") from exc
                except (TypeError, KeyError) as exc:
                    raise ValueError(f"Invalid regional carbon CSV row {line_no}: {exc}") from exc
            for stamp, values in buckets.items():
                label = _dominant_label(labels[stamp])
                value = sum(values) / len(values)
                rows.append(
                    {
                        "datetime_utc": stamp,
                        "actual_gco2_per_kwh": value,
                        "forecast_gco2_per_kwh": value,
                        "index_label": label,
                        "index_code": _index_code(label),
                    }
                )
        else:
            missing = {_DATETIME_COL, _ACTUAL_COL, _FORECAST_COL, _INDEX_COL} - fieldnames
            raise ValueError(f"Carbon CSV missing required columns: {', '.join(sorted(missing))}")
    rows.sort(key=lambda item: item["datetime_utc"])
    return rows


def _parse_utc_datetime(raw: str) -> datetime:
    text = raw.strip()
    if not text:
        raise ValueError("empty UTC timestamp")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"cannot parse UTC timestamp {raw!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _index_code(label: str) -> int:
    key = " ".join(label.strip().lower().split())
    if key not in _INDEX_CODES:
        raise ValueError(f"unknown carbon intensity Index label: {label!r}")
    return _INDEX_CODES[key]


def _dominant_label(labels: list[str]) -> str:
    # v2026-06-12: deterministic regional metadata label; gamma values use the
    # numeric all-region average, while the label is descriptive only.
    counts = Counter(" ".join(label.strip().lower().split()) for label in labels)
    return min(counts, key=lambda label: (-counts[label], _INDEX_CODES.get(label, 999), label))


def _build_fixed_profile(rows: list[dict[str, Any]], anchor: datetime, n_slots: int) -> list[dict[str, Any]]:
    times = [row["datetime_utc"] for row in rows]
    profile = []
    for i in range(n_slots):
        target = anchor + timedelta(seconds=i * SLOT_SECONDS)
        idx = bisect_right(times, target) - 1
        if idx < 0:
            raise ValueError(f"Carbon lookup time {_format_utc(target)} is before CSV coverage")
        if target > times[-1]:
            raise ValueError(f"Carbon lookup time {_format_utc(target)} is after CSV coverage")
        profile.append(_profile_row(rows[idx], i))
    return profile


def _build_daily_profile(rows: list[dict[str, Any]], anchor: datetime, n_slots: int) -> list[dict[str, Any]]:
    by_second = sorted((_seconds_of_day(row["datetime_utc"]), row) for row in rows)
    seconds = [item[0] for item in by_second]
    profile = []
    anchor_second = _seconds_of_day(anchor)
    for i in range(n_slots):
        target_second = (anchor_second + i * SLOT_SECONDS) % 86400
        idx = bisect_right(seconds, target_second) - 1
        if idx < 0:
            idx = len(by_second) - 1
        profile.append(_profile_row(by_second[idx][1], i))
    return profile


def _profile_row(source: dict[str, Any], time_index: int) -> dict[str, Any]:
    return {
        "time_index": int(time_index),
        "datetime_utc": source["datetime_utc"],
        "actual_gco2_per_kwh": source["actual_gco2_per_kwh"],
        "forecast_gco2_per_kwh": source["forecast_gco2_per_kwh"],
        "index_label": source["index_label"],
        "index_code": source["index_code"],
        "horizon_second_start": int(time_index * SLOT_SECONDS),
    }


def _seconds_of_day(dt: datetime) -> int:
    utc = dt.astimezone(timezone.utc)
    return utc.hour * 3600 + utc.minute * 60 + utc.second


def _format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()
