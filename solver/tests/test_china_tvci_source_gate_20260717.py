from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "baselines/e4_e5/china_tvci_source_gate_20260717_v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(name: str) -> list[dict[str, str]]:
    with (EVIDENCE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_decision_is_scoped_to_2025_and_records_future_nulls() -> None:
    decision = json.loads((EVIDENCE / "decision.json").read_text(encoding="utf-8"))
    assert decision["decision"] == (
        "PASS_CHINA_TVCI_2025_SOURCE_GATE_WITH_FUTURE_YEAR_NULLS_RECORDED"
    )
    assert decision["search_evaluations"] == 0
    assert decision["failure_count"] == 0
    assert decision["warning_count"] == 2
    assert any("2055" in warning and "6" in warning for warning in decision["warnings"])
    assert any("2060" in warning and "51" in warning for warning in decision["warnings"])
    assert any("2055 or 2060" in row for row in decision["does_not_authorize"])


def test_all_published_artifact_hashes_recompute() -> None:
    manifest = json.loads((EVIDENCE / "artifact_hashes.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "resetp.artifact-hashes.v1"
    for relative, expected in manifest["artifacts"].items():
        assert sha256(EVIDENCE / relative) == expected


def test_workbook_profile_has_primary_completeness_and_scoped_future_missingness() -> None:
    rows = {int(row["year"]): row for row in read_csv("raw_runs.csv")}
    assert set(rows) == set(range(2025, 2061, 5))
    assert rows[2025]["observed_hours"] == "8760"
    assert rows[2025]["null_count"] == "0"
    assert rows[2025]["source_gate_pass"] == "1"
    assert rows[2040]["observed_hours"] == "8784"
    assert rows[2060]["observed_hours"] == "8784"
    assert rows[2055]["null_count"] == "6"
    assert rows[2060]["null_count"] == "51"
    assert rows[2055]["source_gate_pass"] == "0"
    assert rows[2060]["source_gate_pass"] == "0"

    summaries = read_csv("annual_region_summary.csv")
    missing = {
        (int(row["year"]), row["region"]): int(row["missing_value_count"])
        for row in summaries
        if int(row["missing_value_count"])
    }
    assert missing == {(2055, "Gansu"): 6, (2060, "Gansu"): 50, (2060, "Xinjiang"): 1}


def test_half_hour_conversion_duplicates_hours_and_preserves_daily_integral() -> None:
    rows = read_csv("tvci_2025_48slot_wide.csv")
    assert len(rows) == 365 * 48
    counts = Counter(row["date"] for row in rows)
    assert set(counts.values()) == {48}
    for day_start in range(0, len(rows), 48):
        day = rows[day_start : day_start + 48]
        assert [int(row["half_hour_interval_index"]) for row in day] == list(range(1, 49))
        for hour in range(24):
            first, second = day[2 * hour : 2 * hour + 2]
            assert first["source_hour"] == second["source_hour"]
            for region in ("Mainland China", "Shanghai", "Jiangsu", "Sichuan", "Xinjiang"):
                assert first[region] == second[region]
        slot_integral = 0.5 * sum(float(row["Shanghai"]) for row in day)
        hourly_integral = sum(float(day[2 * hour]["Shanghai"]) for hour in range(24))
        assert math.isclose(slot_integral, hourly_integral, rel_tol=0.0, abs_tol=1e-12)


def test_shanghai_representative_days_are_result_blind_and_distinct() -> None:
    rows = read_csv("selected_days_shanghai_2025.csv")
    assert len(rows) == 12
    assert len({row["date"] for row in rows}) == 12
    assert Counter(int(row["quarter"]) for row in rows) == {1: 3, 2: 3, 3: 3, 4: 3}
    assert Counter(row["selection_rule"] for row in rows) == {
        "median_daily_mean": 4,
        "maximum_intraday_range": 4,
        "minimum_intraday_range": 4,
    }
    assert {row["result_blind_selection"] for row in rows} == {"1"}
