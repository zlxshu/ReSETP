#!/usr/bin/env python3
"""Build a zero-search Shanghai-2025 policy and price scenario.

Every numeric input is tied to a frozen official source snapshot.  The carbon
price is explicitly an internal shadow-price scenario because road logistics
is outside the 2025 national compliance-market sector list.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data/Carbon/中国情景/raw_20260717"
DEFAULT_OUTPUT = REPO / "baselines/e4_e5/china_policy_price_gate_20260717"
SOURCE_HASHES = {
    "MEE_national_carbon_market_2025.html": "223cb0b47110495b65508c1bbf65a14a788c4d1282897245e81a3d113484039d",
    "CNEEEX_CEA_2025-06-30.html": "e5a2a4ceb23fc9ca98f98ca9f8f70e67545c44d8807552ab1dfe8b0b0415678d",
    "CNEEEX_monthly_2025-12-31.html": "3f404020f45f673d1a65468641a92492c884e265e33b8b4fa6c89e61c4620b5a",
    "MEE_national_carbon_market_report_2025.pdf": "ba325d41186b700249f631b5e61f05eafe65ef2c607cc2d5c521c1614bc01930",
    "Shanghai_TOU_policy_2022_50.html": "528dc606786a40e9df4ee9dfb5741872f32940f11e20d023bc79497356718937",
    "Shanghai_2025_07_industrial_tou_tariff_10kV.pdf": "e2293dcc5fb15da3eaad204c929447a1a6dfa757248610b38ef1dec674157bf9",
    "Shanghai_charging_service_fee_cap_2021_43.html": "9c473443a6fa49e00df3a3311398854377cb6d6d2c62c293d666629f9ad01657",
    "Shanghai_charging_service_fee_median_2024.html": "6df1fc27a1c7a36f36030df7ef18fe5a0ed53d3e90f6ef50d12078f32a63935f",
    "Shanghai_diesel_2025-07-15.html": "71e7f59b67eaabb60f3ed42ac8fa73ead072c44dd4f690843d31b6868d66c46b",
    "Shanghai_diesel_2025-12-22.html": "b7d6346fdde6d662094497a3fefac121d69bdb49c1b4d10460e0bc918a4a61c5",
    "Shanghai_diesel_2025-01-16.html": "39df5433ea2ecb763668d30f16ea08b4ee2843706687e22d946d3e931bb352f7",
    "MEE_2023_power_CO2_factors.pdf": "d43b60a3eaad9f3fe59ca37c204d3d0e1b6ea52742a092f0d856971a3f018e5a",
    "NDRC_land_transport_GHG_guideline.pdf": "84aadb948141b5229f9339254dd305bbf54b435e140827244d9e3c69b289bb31",
}


class PriceGateError(RuntimeError):
    """Raised when a frozen source or derived scenario violates the contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def html_text(name: str) -> str:
    return BeautifulSoup((RAW / name).read_bytes(), "html.parser").get_text(
        " ", strip=True
    )


def pdf_text(name: str) -> str:
    completed = subprocess.run(
        ["pdftotext", "-layout", str(RAW / name), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def require(text: str, fragment: str, failures: list[str], label: str) -> None:
    if compact(fragment) not in compact(text):
        failures.append(f"source marker missing for {label}: {fragment}")


def write_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def write_json(path: Path, payload: Any) -> None:
    write_text(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise PriceGateError(f"refuse to write empty CSV: {path.name}")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    write_text(path, buffer.getvalue())


def verify_sources() -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for name, expected in SOURCE_HASHES.items():
        path = RAW / name
        if not path.is_file():
            failures.append(f"frozen source missing: {name}")
            continue
        actual = sha256(path)
        rows.append(
            {
                "source": name,
                "path": str(path.relative_to(REPO)),
                "bytes": path.stat().st_size,
                "sha256": actual,
                "expected_sha256": expected,
                "hash_match": int(actual == expected),
            }
        )
        if actual != expected:
            failures.append(f"frozen source hash differs: {name}")
    return rows, failures


def verify_numeric_markers(failures: list[str]) -> None:
    cea_day = html_text("CNEEEX_CEA_2025-06-30.html")
    cea_month = html_text("CNEEEX_monthly_2025-12-31.html")
    mee_market = html_text("MEE_national_carbon_market_2025.html")
    market_report = pdf_text("MEE_national_carbon_market_report_2025.pdf")
    tou_policy = html_text("Shanghai_TOU_policy_2022_50.html")
    tariff = pdf_text("Shanghai_2025_07_industrial_tou_tariff_10kV.pdf")
    fee_cap = html_text("Shanghai_charging_service_fee_cap_2021_43.html")
    fee_median = html_text("Shanghai_charging_service_fee_median_2024.html")
    factors = pdf_text("MEE_2023_power_CO2_factors.pdf")
    guideline = pdf_text("NDRC_land_transport_GHG_guideline.pdf")

    require(cea_day, "收盘价75.02元/吨", failures, "CEA base price")
    require(cea_month, "最低价56.32元/吨", failures, "CEA low price")
    require(market_report, "峰值105.65元/吨", failures, "CEA high price")
    require(mee_market, "全年交易均价为62.36元/吨", failures, "CEA annual mean")
    require(mee_market, "年底收盘价为74.63元/吨", failures, "CEA year-end close")
    for sector in ("发电行业", "钢铁行业", "水泥行业", "铝冶炼行业"):
        require(mee_market, sector, failures, f"2025 compliance sector {sector}")
    require(
        tou_policy,
        "高峰时段：8:00-15:00、18:00-21:00",
        failures,
        "Shanghai summer peak periods",
    )
    require(
        tou_policy,
        "7月、8月12:00-14:00为尖峰时段",
        failures,
        "Shanghai July sharp-peak period",
    )
    for value in ("0.3191", "0.6811", "1.1637", "1.4352"):
        require(tariff, value, failures, f"Shanghai 10kV tariff {value}")
    require(fee_cap, "上限为每千瓦时1.3元", failures, "charging fee cap")
    require(fee_median, "中位数为每千瓦时0.42元", failures, "charging fee median")
    for name, value in (
        ("Shanghai_diesel_2025-12-22.html", "6.31"),
        ("Shanghai_diesel_2025-07-15.html", "6.88"),
        ("Shanghai_diesel_2025-01-16.html", "7.41"),
    ):
        text = html_text(name)
        require(text, "0号柴油", failures, f"diesel identity {name}")
        require(text, value, failures, f"diesel value {name}")
    for value in ("0.5306", "0.5737", "0.5827"):
        require(factors, value, failures, f"MEE power factor {value}")
    for value in ("0.84", "43.330", "20.20×10-3", "98%"):
        require(guideline, value, failures, f"diesel factor input {value}")


def tou_rows() -> list[dict[str, Any]]:
    prices = {
        "valley": 0.3191,
        "flat": 0.6811,
        "peak": 1.1637,
        "sharp_peak": 1.4352,
    }
    rows: list[dict[str, Any]] = []
    for slot in range(48):
        start_minutes = slot * 30
        hour = start_minutes / 60.0
        if hour < 6.0 or hour >= 22.0:
            band = "valley"
        elif 6.0 <= hour < 8.0 or 15.0 <= hour < 18.0 or 21.0 <= hour < 22.0:
            band = "flat"
        elif 12.0 <= hour < 14.0:
            band = "sharp_peak"
        else:
            band = "peak"
        rows.append(
            {
                "slot": slot + 1,
                "start_time": f"{start_minutes // 60:02d}:{start_minutes % 60:02d}",
                "end_time": f"{((start_minutes + 30) // 60) % 24:02d}:{(start_minutes + 30) % 60:02d}",
                "tariff_band": band,
                "electricity_yuan_per_kWh": f"{prices[band]:.4f}",
            }
        )
    counts = {band: sum(row["tariff_band"] == band for row in rows) for band in prices}
    if counts != {"valley": 16, "flat": 12, "peak": 16, "sharp_peak": 4}:
        raise PriceGateError(f"unexpected Shanghai July slot counts: {counts}")
    return rows


def scenario_rows() -> list[dict[str, Any]]:
    return [
        {
            "parameter": "carbon_shadow_price",
            "scenario": label,
            "value": f"{value:.5f}",
            "unit": "yuan_per_tCO2e",
            "model_value": f"{value / 1000.0:.8f}",
            "model_unit": "yuan_per_kgCO2e",
            "interpretation": "internal shadow price / policy expansion / upstream pass-through; not a current legal road-logistics compliance cost",
        }
        for label, value in (("observed_low", 56.32), ("base", 75.02), ("observed_high", 105.65))
    ] + [
        {
            "parameter": "diesel_price",
            "scenario": label,
            "value": f"{value:.2f}",
            "unit": "yuan_per_L",
            "model_value": f"{value:.8f}",
            "model_unit": "yuan_per_L",
            "interpretation": "official Shanghai maximum retail price on the named date; not a fleet bulk-purchase transaction price",
        }
        for label, value in (("official_date_low", 6.31), ("base_2025-07-15", 6.88), ("official_date_high", 7.41))
    ] + [
        {
            "parameter": "public_charging_service_fee",
            "scenario": label,
            "value": f"{value:.2f}",
            "unit": "yuan_per_kWh",
            "model_value": f"{value:.8f}",
            "model_unit": "yuan_per_kWh",
            "interpretation": description,
        }
        for label, value, description in (
            ("depot_owned", 0.0, "no public charging service fee"),
            ("public_typical", 0.42, "2024 Shanghai public-station median"),
            ("public_guidance_cap", 1.30, "government guidance ceiling, not a typical transaction price"),
        )
    ]


def emission_rows() -> list[dict[str, Any]]:
    # NDRC land-transport GHG guide (trial): printed p. 15 gives diesel
    # density 0.84 t/m3; printed p. 60 gives 43.330 GJ/t, 20.20e-3 tC/GJ,
    # and a 98% oxidation rate.  Printed pp. 10-11 define AD and EF.
    density_t_per_l = 0.84 / 1000.0
    energy_gj_per_l = density_t_per_l * 43.330
    carbon_t_per_l = energy_gj_per_l * 20.20e-3
    oxidized_carbon_t_per_l = carbon_t_per_l * 0.98
    diesel_kgco2_per_l = (
        oxidized_carbon_t_per_l * 44.0 / 12.0 * 1000.0
    )
    if not math.isclose(density_t_per_l, 0.00084, abs_tol=1e-15):
        raise PriceGateError("official diesel density conversion differs")
    if not math.isclose(energy_gj_per_l, 0.0363972, abs_tol=1e-15):
        raise PriceGateError("official diesel energy conversion differs")
    if not math.isclose(
        diesel_kgco2_per_l,
        2.6419028944,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise PriceGateError("official diesel CO2 factor formula differs")
    return [
        {
            "factor": "Shanghai purchased electricity annual average",
            "value": "0.5737",
            "unit": "kgCO2_per_kWh",
            "boundary": "operational purchased electricity; annual average, not TVCI",
        },
        {
            "factor": "Mainland China purchased electricity annual average",
            "value": "0.5306",
            "unit": "kgCO2_per_kWh",
            "boundary": "operational purchased electricity; annual average, not TVCI",
        },
        {
            "factor": "diesel combustion",
            "value": f"{diesel_kgco2_per_l:.10f}",
            "unit": "kgCO2_per_L",
            "boundary": "CO2 from fuel combustion only; excludes CH4, N2O, urea, upstream fuel, vehicle and battery manufacturing",
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refuse to overwrite existing output: {args.output}")
    temporary = args.output.with_name(f".{args.output.name}.tmp-{os.getpid()}")
    if temporary.exists():
        raise SystemExit(f"temporary output already exists: {temporary}")
    temporary.mkdir(parents=True)

    sources, failures = verify_sources()
    verify_numeric_markers(failures)
    tou = tou_rows()
    scenarios = scenario_rows()
    emissions = emission_rows()
    write_csv(temporary / "source_evidence.csv", sources)
    write_csv(temporary / "price_scenarios.csv", scenarios)
    write_csv(temporary / "shanghai_july_tou_48slot.csv", tou)
    write_csv(temporary / "emission_factors.csv", emissions)
    status = "PASS_CHINA_POLICY_PRICE_ZERO_SEARCH_GATE" if not failures else "HALT_CHINA_POLICY_PRICE_GATE"
    metadata = {
        "schema_version": "resetp.china-policy-price.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decision": status,
        "scenario_identity": "Shanghai, July 2025, CNY",
        "carbon_price_semantics": "internal shadow price / policy expansion / upstream pass-through; road logistics is not in the listed 2025 compliance sectors",
        "carbon_market_2025_listed_sectors": ["power generation", "steel", "cement", "aluminium smelting"],
        "electricity_tariff_identity": "Shanghai general industrial and commercial two-part tariff, 10 kV, July 2025, final time-of-use energy charge",
        "diesel_price_identity": "Shanghai official maximum retail price for grade-0 diesel",
        "emissions_boundary": "delivery-operation CO2: diesel combustion plus purchased-electricity indirect emissions",
        "source_count": len(sources),
        "search_evaluations": 0,
        "script_sha256": sha256(Path(__file__)),
        "python": sys.version,
        "platform": platform.platform(),
        "pdftotext_version": subprocess.run(
            ["pdftotext", "-v"], capture_output=True, text=True, check=False
        ).stderr.strip().splitlines()[0],
    }
    write_json(temporary / "metadata.json", metadata)
    decision = {
        "decision": status,
        "failure_count": len(failures),
        "failures": failures,
        "search_evaluations": 0,
        "authorizes": (
            ["use the frozen Shanghai July-2025 price scenario", "use CEA observations as internal shadow-price scenarios", "use the 48-slot tariff mapping"]
            if not failures
            else []
        ),
        "does_not_authorize": [
            "calling CEA a current legal road-logistics carbon tax or allowance cost",
            "calling official maximum diesel retail prices fleet transaction prices",
            "mixing operational CO2 and life-cycle CO2e",
            "path-search experiments before E7 closeout and ALNS G0",
        ],
    }
    write_json(temporary / "decision.json", decision)
    write_text(
        temporary / "report.md",
        "# China policy and price zero-search gate\n\n"
        f"Decision: `{status}`.\n\n"
        "The machine-readable scenario is Shanghai, July 2025, in CNY. The 48-slot electricity tariff preserves the official valley/flat/peak/sharp-peak periods. "
        "Carbon-price observations are retained only as internal shadow-price or policy scenarios because the 2025 compliance-sector list does not include road logistics. "
        "Diesel values are official maximum retail prices, and the emissions boundary remains delivery-operation CO2.\n\n"
        + ("No source or unit failures were observed.\n" if not failures else "Failures:\n" + "\n".join(f"- {row}" for row in failures) + "\n"),
    )
    protected = [
        "source_evidence.csv",
        "price_scenarios.csv",
        "shanghai_july_tou_48slot.csv",
        "emission_factors.csv",
        "metadata.json",
        "decision.json",
        "report.md",
    ]
    write_json(
        temporary / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "artifacts": {name: sha256(temporary / name) for name in protected},
        },
    )
    os.replace(temporary, args.output)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
