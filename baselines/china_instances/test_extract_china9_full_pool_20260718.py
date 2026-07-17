#!/usr/bin/env python3
"""Read-back tests for the China nine-city full-pool extraction package."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract_china9_full_pool_20260718 as extractor


OUTPUT = extractor.DEFAULT_OUTPUT


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class China9PoolReadbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required = [
            "metadata.json",
            "raw_runs.csv",
            "decision.json",
            "artifact_hashes.json",
            "report.md",
            "city_query_boxes.csv",
            "old_snapshot_counts.csv",
            "city_counts.csv",
            "station_parameter_summary.csv",
            "shortlist_candidates.csv",
            "appledouble_cleanup.json",
        ]
        missing = [name for name in required if not (OUTPUT / name).exists()]
        if missing:
            raise AssertionError(f"run --mode offline-audit first; missing {missing}")

    def test_count_table_has_nine_by_three_rows_and_old_counts_recompute(self) -> None:
        counts = read_rows(OUTPUT / "city_counts.csv")
        old = read_rows(OUTPUT / "old_snapshot_counts.csv")
        self.assertEqual(len(counts), 27)
        self.assertEqual(len(old), 27)
        old_index = {(row["city"], row["feature"]): row["old_count"] for row in old}
        for row in counts:
            self.assertEqual(row["old_count"], old_index[(row["city"], row["feature"])])

    def test_query_boxes_contain_every_current_draft_coordinate(self) -> None:
        boxes = {row["city"]: row for row in read_rows(OUTPUT / "city_query_boxes.csv")}
        self.assertEqual(set(boxes), set(extractor.CITIES))
        for node_path in extractor.EXISTING_INSTANCES.glob("cn-*/nodes.csv"):
            for row in extractor.read_csv(node_path):
                city = row.get("source_anchor", "")
                if city not in boxes:
                    continue
                box = boxes[city]
                lat, lon = float(row["latitude"]), float(row["longitude"])
                self.assertGreaterEqual(lat, float(box["south"]))
                self.assertLessEqual(lat, float(box["north"]))
                self.assertGreaterEqual(lon, float(box["west"]))
                self.assertLessEqual(lon, float(box["east"]))

    def test_hashes_recompute_for_every_listed_artifact(self) -> None:
        manifest = json.loads((OUTPUT / "artifact_hashes.json").read_text(encoding="utf-8"))
        for relative, expected in manifest["files"].items():
            path = extractor.REPO / relative
            self.assertTrue(path.exists(), relative)
            self.assertEqual(file_sha256(path), expected, relative)
        for relative, expected in manifest["legacy_source_files"].items():
            path = extractor.REPO / relative
            self.assertTrue(path.exists(), relative)
            self.assertEqual(file_sha256(path), expected, relative)
        for relative, expected in manifest["external_code_files"].items():
            path = extractor.REPO / relative
            self.assertTrue(path.exists(), relative)
            self.assertEqual(file_sha256(path), expected, relative)

    def test_legacy_counts_match_hardening_baseline(self) -> None:
        expected = {
            "beijing": (963, 18, 2),
            "tianjin": (79, 5, 1),
            "shijiazhuang": (22, 1, 0),
            "shenzhen": (297, 39, 4),
            "dongguan": (29, 19, 0),
            "guangzhou": (651, 29, 2),
            "foshan": (332, 26, 4),
            "chengdu": (442, 39, 4),
            "chongqing": (80, 11, 1),
        }
        rows = read_rows(OUTPUT / "old_snapshot_counts.csv")
        actual = {
            city: tuple(
                int(next(row["old_count"] for row in rows if row["city"] == city and row["feature"] == feature))
                for feature in ("named_poi", "logistics_candidate", "charging_station")
            )
            for city in extractor.CITIES
        }
        self.assertEqual(actual, expected)

    def test_shortlist_excludes_obvious_non_logistics_and_has_region_rows(self) -> None:
        rows = read_rows(OUTPUT / "shortlist_candidates.csv")
        self.assertTrue(rows)
        for row in rows:
            self.assertFalse(extractor.obvious_non_logistics(json.loads(row["tags"])), row)
        for region in ("jjj", "prd", "cy"):
            region_rows = [row for row in rows if row["region"] == region]
            self.assertGreaterEqual(len(region_rows), 8, region)
            self.assertLessEqual(len(region_rows), 12, region)

    def test_offline_package_does_not_claim_new_counts(self) -> None:
        decision = json.loads((OUTPUT / "decision.json").read_text(encoding="utf-8"))
        if decision["verdict"] == "HALT_ENV_NETWORK_EGRESS_UNAVAILABLE":
            counts = read_rows(OUTPUT / "city_counts.csv")
            self.assertTrue(all(row["new_status"] == "NOT_EXTRACTED" for row in counts))
            self.assertTrue(all(row["new_count"] == "" for row in counts))

    def test_zero_station_response_is_extracted_zero_not_missing(self) -> None:
        counts = {
            row["city"]: row
            for row in read_rows(OUTPUT / "city_counts.csv")
            if row["feature"] == "charging_station"
        }
        station_rows = {row["city"]: row for row in read_rows(OUTPUT / "station_parameter_summary.csv")}
        for city, count_row in counts.items():
            summary = station_rows[city]
            if count_row["new_status"] == "EXTRACTED":
                self.assertEqual(summary["status"], "EXTRACTED", city)
                self.assertEqual(summary["station_count"], count_row["new_count"], city)
            else:
                self.assertEqual(summary["status"], "NOT_EXTRACTED", city)
                self.assertEqual(summary["station_count"], "", city)


if __name__ == "__main__":
    unittest.main()
