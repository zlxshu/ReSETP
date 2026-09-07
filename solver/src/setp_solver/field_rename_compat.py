"""Compatibility boundary for the 2026-08-15 input-field rename.

The active data packages use the descriptive names.  The legacy spellings
are kept only here so an old, already-sealed package can still be inspected
without changing its bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

HOURLY_CALENDAR_FILENAME = "tariff_carbon_hourly_calendar.csv"

HOURLY_CALENDAR_ROW = "hourly_calendar_row"
LEGACY_CALENDAR_ROW = "half_hour_slot"

CONFIGURED_DEPOT_GUN_COUNT_IF_FINITE = "configured_depot_gun_count_if_finite"
LEGACY_CONFIGURED_DEPOT_GUN_COUNT_IF_FINITE = "depot_charger_count"

def resolve_calendar_path(parameter_root: Path) -> Path:
    """Return the active calendar path."""

    current = parameter_root / HOURLY_CALENDAR_FILENAME
    if current.is_file():
        return current
    raise FileNotFoundError(
        f"calendar is missing under {parameter_root}: "
        f"{HOURLY_CALENDAR_FILENAME}"
    )


def renamed_value(
    row: Mapping[str, str],
    current_name: str,
    legacy_name: str,
) -> str:
    """Read a renamed column with current-name priority and legacy fallback."""

    if current_name in row:
        return str(row[current_name])
    if legacy_name in row:
        return str(row[legacy_name])
    raise KeyError(f"row has neither {current_name!r} nor the legacy column")


def calendar_row_number(row: Mapping[str, str]) -> int:
    return int(renamed_value(row, HOURLY_CALENDAR_ROW, LEGACY_CALENDAR_ROW))


def configured_depot_gun_count(row: Mapping[str, str]) -> int:
    return int(
        renamed_value(
            row,
            CONFIGURED_DEPOT_GUN_COUNT_IF_FINITE,
            LEGACY_CONFIGURED_DEPOT_GUN_COUNT_IF_FINITE,
        )
    )
