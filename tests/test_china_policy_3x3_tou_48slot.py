from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "baselines/e4_e5/china_policy_3x3_tou_48slot.py"
SPEC = importlib.util.spec_from_file_location("china_policy_3x3_tou_48slot", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load mapping script: {SCRIPT_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ChinaPolicyTou48SlotTests(unittest.TestCase):
    def test_each_region_has_48_slots_and_exact_band_price_readback(self) -> None:
        for region, config in MODULE.REGION_CONFIGS.items():
            rows = MODULE.region_rows(region)
            self.assertEqual(len(rows), 48, region)
            for row in rows:
                start = MODULE.minute(row["start_time"])
                expected_band = MODULE.band_for_interval(start, start + 30, config["periods"])
                expected_price = MODULE.decimal_text(config["tariffs"][expected_band])
                self.assertEqual(row["tariff_band"], expected_band, (region, row))
                self.assertEqual(
                    row["electricity_yuan_per_kWh"],
                    expected_price,
                    (region, row),
                )

    def test_cross_midnight_and_noon_boundaries(self) -> None:
        crossing = MODULE.map_periods_to_slots(
            (
                MODULE.period("23:00", "01:00", "valley"),
                MODULE.period("01:00", "23:00", "flat"),
            )
        )
        self.assertEqual(crossing[0]["tariff_band"], "valley")
        self.assertEqual(crossing[-1]["tariff_band"], "valley")
        self.assertEqual(len(crossing), 48)

        beijing = MODULE.region_rows("beijing")
        self.assertEqual(beijing[21]["tariff_band"], "peak")
        self.assertEqual(beijing[22]["tariff_band"], "sharp_peak")
        self.assertEqual(beijing[25]["tariff_band"], "sharp_peak")
        self.assertEqual(beijing[26]["tariff_band"], "flat")
        self.assertEqual(beijing[32]["tariff_band"], "sharp_peak")

        guangdong = MODULE.region_rows("guangdong")
        self.assertEqual(guangdong[15]["tariff_band"], "valley")
        self.assertEqual(guangdong[16]["tariff_band"], "flat")
        self.assertEqual(guangdong[22]["tariff_band"], "sharp_peak")
        self.assertEqual(guangdong[30]["tariff_band"], "sharp_peak")

        chongqing = MODULE.region_rows("chongqing")
        self.assertEqual(chongqing[15]["tariff_band"], "valley")
        self.assertEqual(chongqing[16]["tariff_band"], "flat")
        self.assertEqual(chongqing[23]["tariff_band"], "peak")
        self.assertEqual(chongqing[24]["tariff_band"], "sharp_peak")


if __name__ == "__main__":
    unittest.main()
