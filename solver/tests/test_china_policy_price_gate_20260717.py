from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "baselines/e4_e5/china_policy_price_gate_20260717"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(name: str) -> list[dict[str, str]]:
    with (EVIDENCE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_decision_and_artifact_hashes_are_closed() -> None:
    decision = json.loads((EVIDENCE / "decision.json").read_text(encoding="utf-8"))
    assert decision["decision"] == "PASS_CHINA_POLICY_PRICE_ZERO_SEARCH_GATE"
    assert decision["failure_count"] == 0
    assert decision["search_evaluations"] == 0
    assert any("internal shadow-price" in row for row in decision["authorizes"])
    assert any("legal road-logistics" in row for row in decision["does_not_authorize"])
    manifest = json.loads((EVIDENCE / "artifact_hashes.json").read_text(encoding="utf-8"))
    for name, expected in manifest["artifacts"].items():
        assert sha256(EVIDENCE / name) == expected


def test_all_official_source_snapshots_match_the_frozen_hashes() -> None:
    rows = read_csv("source_evidence.csv")
    assert len(rows) == 13
    assert {row["hash_match"] for row in rows} == {"1"}
    for row in rows:
        assert sha256(ROOT / row["path"]) == row["sha256"] == row["expected_sha256"]


def test_july_tou_mapping_preserves_official_bands_and_prices() -> None:
    rows = read_csv("shanghai_july_tou_48slot.csv")
    assert len(rows) == 48
    assert Counter(row["tariff_band"] for row in rows) == {
        "valley": 16,
        "flat": 12,
        "peak": 16,
        "sharp_peak": 4,
    }
    prices = {
        band: {float(row["electricity_yuan_per_kWh"]) for row in rows if row["tariff_band"] == band}
        for band in ("valley", "flat", "peak", "sharp_peak")
    }
    assert prices == {
        "valley": {0.3191},
        "flat": {0.6811},
        "peak": {1.1637},
        "sharp_peak": {1.4352},
    }
    by_start = {row["start_time"]: row["tariff_band"] for row in rows}
    assert by_start["05:30"] == "valley"
    assert by_start["06:00"] == "flat"
    assert by_start["08:00"] == "peak"
    assert by_start["12:00"] == "sharp_peak"
    assert by_start["14:00"] == "peak"
    assert by_start["15:00"] == "flat"
    assert by_start["18:00"] == "peak"
    assert by_start["21:00"] == "flat"
    assert by_start["22:00"] == "valley"


def test_carbon_diesel_and_service_fee_scenarios_keep_units_and_semantics() -> None:
    rows = read_csv("price_scenarios.csv")
    lookup = {(row["parameter"], row["scenario"]): row for row in rows}
    assert float(lookup[("carbon_shadow_price", "base")]["value"]) == 75.02
    assert float(lookup[("carbon_shadow_price", "base")]["model_value"]) == 0.07502
    assert float(lookup[("diesel_price", "base_2025-07-15")]["value"]) == 6.88
    assert float(lookup[("public_charging_service_fee", "public_typical")]["value"]) == 0.42
    assert float(lookup[("public_charging_service_fee", "public_guidance_cap")]["value"]) == 1.30
    assert "not a current legal" in lookup[("carbon_shadow_price", "base")]["interpretation"]


def test_diesel_emission_factor_recomputes_from_the_frozen_formula() -> None:
    rows = {row["factor"]: row for row in read_csv("emission_factors.csv")}
    expected_tco2_per_t = 43.330 * 20.20e-3 * 0.98 * 44.0 / 12.0
    density_kg_per_l = 6.88 / (8000.0 / 1000.0)
    expected_kgco2_per_l = expected_tco2_per_t * density_kg_per_l
    actual = float(rows["diesel combustion"]["value"])
    assert math.isclose(actual, expected_kgco2_per_l, rel_tol=0.0, abs_tol=5e-9)
    assert rows["Shanghai purchased electricity annual average"]["value"] == "0.5737"
    assert "not TVCI" in rows["Shanghai purchased electricity annual average"]["boundary"]
