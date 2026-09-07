from __future__ import annotations

import csv
import json
import math
import unittest
from pathlib import Path

from setp_solver.china81 import DEFAULT_CHINA81_DATE, _load_time_profile
from setp_solver.cost import (
    CARBON_SLOT_SECONDS,
    carbon_profile_row_for_slot,
    carbon_slot_index,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CALENDAR_PATH = (
    REPO_ROOT
    / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
    / "tariff_carbon_hourly_calendar.csv"
)
INSTANCE_DIR = (
    REPO_ROOT
    / "data/ChinaInstances/china81_final_suite_v2_20260815/instances"
    / "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
)
CITY = "beijing"
DATE = DEFAULT_CHINA81_DATE


def _calendar_rows() -> list[dict[str, str]]:
    with CALENDAR_PATH.open(newline="", encoding="utf-8") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row["city"].strip().lower() == CITY and row["date"] == DATE
        ]


def _profile() -> list[dict[str, object]]:
    # Use the production China81 loader; expected values still come from the
    # source CSV rows read independently by _calendar_rows().
    return _load_time_profile(
        CALENDAR_PATH,
        cities={CITY},
        date=DATE,
        require_explicit_mapping=True,
    )


def _reference_slot(t_second: float, n_slots: int) -> int:
    raw = math.floor(float(t_second) / CARBON_SLOT_SECONDS)
    return max(0, min(n_slots - 1, int(raw)))


class CarbonGateTests(unittest.TestCase):
    def test_authority_has_48_ordered_half_hour_rows(self) -> None:
        rows = _calendar_rows()

        self.assertEqual(DATE, "2025-02-12")
        self.assertEqual(len(rows), 48)
        self.assertEqual(
            [int(row["minute_of_day"]) for row in rows],
            list(range(0, 24 * 60, 30)),
        )

    def test_authority_has_24_hourly_carbon_slots(self) -> None:
        rows = _calendar_rows()

        self.assertEqual(len(rows) // 2, 24)
        for hour in range(24):
            left = rows[2 * hour]["carbon_factor_kgco2e_per_kwh"]
            right = rows[2 * hour + 1]["carbon_factor_kgco2e_per_kwh"]
            self.assertEqual(left, right, msg=f"hour={hour:02d}:00")

    def test_carbon_slot_index_round_trips_on_48_slot_grid(self) -> None:
        n_slots = len(_calendar_rows())

        self.assertEqual(CARBON_SLOT_SECONDS, 1800.0)
        for slot_index in range(n_slots):
            for t_second in (
                slot_index * CARBON_SLOT_SECONDS,
                (slot_index + 1) * CARBON_SLOT_SECONDS - 1.0,
            ):
                expected = _reference_slot(t_second, n_slots)
                self.assertEqual(expected, slot_index)
                self.assertEqual(
                    carbon_slot_index(t_second, n_slots=n_slots),
                    expected,
                    msg=f"t={t_second}",
                )

    def test_profile_rows_round_trip_to_authority_values(self) -> None:
        rows = _calendar_rows()
        profile = _profile()

        self.assertEqual(len(profile), len(rows))
        for slot_index, source_row in enumerate(rows):
            actual = carbon_profile_row_for_slot(profile, slot_index)
            self.assertEqual(
                actual["time_index"],
                int(source_row["hourly_calendar_row"]),
                msg=f"slot={slot_index}",
            )
            self.assertEqual(
                actual["horizon_second_start"],
                float(source_row["minute_of_day"]) * 60.0,
                msg=f"slot={slot_index}",
            )
            self.assertEqual(
                actual["actual_gco2_per_kwh"],
                float(source_row["carbon_factor_kgco2e_per_kwh"]) * 1000.0,
                msg=f"slot={slot_index}",
            )

    def test_formal_depot_return_deadline_precedes_carbon_window_end(self) -> None:
        with (INSTANCE_DIR / "nodes.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            depots = [
                row
                for row in csv.DictReader(handle)
                if row["node_type"].strip().lower() == "depot"
            ]
        contract = json.loads(
            (INSTANCE_DIR / "shift_contract.json").read_text(encoding="utf-8")
        )

        self.assertTrue(depots)
        shift_end_minutes = [
            float(shift["end_minute"])
            for shift in contract["shifts"].values()
        ]
        return_deadline = max(shift_end_minutes) * 60.0
        attendance_deadline = float(contract["attendance"]["end_minute"]) * 60.0
        window_end = len(_calendar_rows()) * CARBON_SLOT_SECONDS
        self.assertEqual(return_deadline, attendance_deadline)
        self.assertLessEqual(return_deadline, window_end)


if __name__ == "__main__":
    unittest.main()
