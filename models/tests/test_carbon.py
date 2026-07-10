from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from setp_instance_lab import ScenarioConfig, generate_scenario, write_scenario_bundle
from setp_instance_lab.carbon import load_carbon_profile


REPO_ROOT = Path(__file__).resolve().parents[2]
REGIONAL_CARBON_CSV = REPO_ROOT / "data" / "Carbon" / "时变碳强度" / "regional_carbon_intensity_2025-11-01_to_2025-11-30.csv"


class CarbonProfileTests(unittest.TestCase):
    def test_fixed_anchor_maps_model_seconds_to_utc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(Path(tmp), 20)
            profile = load_carbon_profile(path, "fixed_utc_anchor", "2025-11-19T08:00:00+00:00", 3)
            self.assertEqual(profile[0]["datetime_utc"].isoformat(), "2025-11-19T08:00:00+00:00")
            self.assertEqual(profile[2]["datetime_utc"].isoformat(), "2025-11-19T09:00:00+00:00")
            self.assertEqual(profile[2]["horizon_second_start"], 3600)

    def test_fixed_anchor_requires_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(Path(tmp), 3)
            with self.assertRaisesRegex(ValueError, "carbon_time_anchor_utc"):
                load_carbon_profile(path, "fixed_utc_anchor", None, 1)

    def test_index_mapping_and_unknown_label_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(Path(tmp), 4, labels=("Low", "Moderate", "High", "Very High"))
            profile = load_carbon_profile(path, "fixed_utc_anchor", "2025-11-19T08:00:00+00:00", 4)
            self.assertEqual([row["index_code"] for row in profile], [1, 2, 3, 4])
            bad = self._write_csv(Path(tmp), 1, labels=("unknown",), name="bad.csv")
            with self.assertRaisesRegex(ValueError, "unknown carbon intensity Index"):
                load_carbon_profile(bad, "fixed_utc_anchor", "2025-11-19T08:00:00+00:00", 1)

    def test_sixteen_slots_and_insufficient_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(Path(tmp), 16)
            profile = load_carbon_profile(path, "fixed_utc_anchor", "2025-11-19T08:00:00+00:00", 16)
            self.assertEqual(len(profile), 16)
            self.assertEqual([row["horizon_second_start"] for row in profile], [i * 1800 for i in range(16)])
            short_path = self._write_csv(Path(tmp), 15, name="short.csv")
            with self.assertRaisesRegex(ValueError, "after CSV coverage"):
                load_carbon_profile(short_path, "fixed_utc_anchor", "2025-11-19T08:00:00+00:00", 16)

    def test_eighteen_slots_from_default_32400_horizon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(Path(tmp), 32, start_time="2025-11-13T08:00:00+00:00")
            profile = load_carbon_profile(path, "fixed_utc_anchor", "2025-11-13T08:00:00+00:00", 18)
            self.assertEqual(len(profile), 18)
            self.assertEqual(profile[0]["datetime_utc"].isoformat(), "2025-11-13T08:00:00+00:00")
            self.assertEqual(profile[17]["datetime_utc"].isoformat(), "2025-11-13T16:30:00+00:00")
            self.assertEqual([row["horizon_second_start"] for row in profile], [i * 1800 for i in range(18)])
            self.assertEqual(profile[-1]["horizon_second_start"], 30600)

    def test_regional_csv_20251113_midnight_anchor_round_trips_48_slots(self) -> None:
        # v2026-06-12: Q1 requires the regional CSV to produce the full 24h/48-slot gamma table.
        profile = load_carbon_profile(
            str(REGIONAL_CARBON_CSV),
            "fixed_utc_anchor",
            "2025-11-13T00:00:00+00:00",
            48,
        )
        expected = self._regional_expected_average_by_from(REGIONAL_CARBON_CSV, "2025-11-13")

        self.assertEqual(len(profile), 48)
        self.assertEqual(profile[0]["datetime_utc"].isoformat(), "2025-11-13T00:00:00+00:00")
        self.assertEqual(profile[-1]["datetime_utc"].isoformat(), "2025-11-13T23:30:00+00:00")
        self.assertEqual([row["horizon_second_start"] for row in profile], [i * 1800 for i in range(48)])
        for row in profile:
            key = row["datetime_utc"].strftime("%Y-%m-%dT%H:%MZ")
            self.assertEqual(row["actual_gco2_per_kwh"], expected[key], msg=key)

    def test_previous_hold_uses_previous_row_between_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_csv(Path(tmp), 3)
            profile = load_carbon_profile(path, "fixed_utc_anchor", "2025-11-19T08:15:00+00:00", 1)
            self.assertEqual(profile[0]["datetime_utc"].isoformat(), "2025-11-19T08:00:00+00:00")

    def test_bundle_writes_carbon_profile_and_manifest_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            carbon_path = self._write_csv(tmp_path, 20)
            config = ScenarioConfig(
                n_depots=1,
                n_stations=1,
                n_customers=3,
                seed=3,
                carbon_alignment_mode="fixed_utc_anchor",
                carbon_time_anchor_utc="2025-11-19T08:00:00+00:00",
                carbon_profile_path=carbon_path,
                min_customer_distance=10,
            )
            scenario = generate_scenario(config)
            out_dir = tmp_path / "bundle"
            paths = write_scenario_bundle(scenario, out_dir, config=config.to_dict(), export_dynamic=False)
            carbon_out = out_dir / "carbon_profile.csv"
            self.assertTrue(carbon_out.is_file())
            manifest = json.loads(Path(paths["scenario_manifest_json"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["files"]["carbon_profile_csv"], "carbon_profile.csv")
            self.assertIn("carbon_profile_csv", manifest["hashes"])
            self.assertEqual(manifest["metadata"]["carbon_alignment_mode"], "fixed_utc_anchor")
            self.assertEqual(manifest["metadata"]["carbon_n_slots"], 18)
            instance = json.loads((out_dir / "instance.json").read_text(encoding="utf-8"))
            self.assertEqual(instance["metadata"]["carbon_unit"], "gCO2/kWh")

    def test_none_mode_does_not_write_carbon_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ScenarioConfig(n_depots=1, n_stations=1, n_customers=3, seed=4, min_customer_distance=10)
            scenario = generate_scenario(config)
            out_dir = Path(tmp) / "bundle"
            paths = write_scenario_bundle(scenario, out_dir, config=config.to_dict(), export_dynamic=False)
            self.assertFalse((out_dir / "carbon_profile.csv").exists())
            manifest = json.loads(Path(paths["scenario_manifest_json"]).read_text(encoding="utf-8"))
            self.assertNotIn("carbon_profile_csv", manifest["files"])
            self.assertNotIn("carbon_alignment_mode", manifest["config"])

    def _write_csv(
        self,
        root: Path,
        row_count: int,
        *,
        labels: tuple[str, ...] = ("Low",),
        name: str = "carbon.csv",
        start_time: str = "2025-11-19T08:00:00+00:00",
    ) -> str:
        path = root / name
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "Datetime (UTC)",
                "Actual Carbon Intensity (gCO2/kWh)",
                "Forecast Carbon Intensity (gCO2/kWh)",
                "Index",
            ])
            for i in range(row_count):
                writer.writerow([
                    (start + timedelta(minutes=30 * i)).isoformat(),
                    100 + i,
                    110 + i,
                    labels[i % len(labels)],
                ])
        return str(path)

    def _regional_expected_average_by_from(self, path: Path, day: str) -> dict[str, float]:
        buckets: dict[str, list[float]] = {}
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row["from"].startswith(day):
                    buckets.setdefault(row["from"], []).append(float(row["forecast"]))
        return {key: sum(values) / len(values) for key, values in buckets.items()}


if __name__ == "__main__":
    unittest.main()
