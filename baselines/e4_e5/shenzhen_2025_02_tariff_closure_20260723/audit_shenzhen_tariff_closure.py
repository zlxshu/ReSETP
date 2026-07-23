#!/usr/bin/env python3
"""Zero-search audit for the Shenzhen 2025-02 depot-charging tariff scenario."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SNAPSHOTS = OUT / "source_snapshots"

REGISTER_V2 = ROOT / "data/ChinaPrices/china_2025_02_tariff_register_v2.json"
SHENZHEN_API = (
    ROOT
    / "data/ChinaPrices/official_snapshots/china_2025_02_nine_city/"
    "shenzhen_2025_02_api.json"
)
SHENZHEN_SCAN = (
    ROOT
    / "data/ChinaPrices/official_snapshots/china_2025_02_nine_city/"
    "shenzhen_2025_02.webp"
)
BUILDER = ROOT / "baselines/china_instances/build_china_stage2_static_inputs_20260718.py"
CALENDAR = (
    ROOT
    / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718/"
    "tariff_carbon_48slot_calendar.csv"
)
FACILITIES = (
    ROOT
    / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718/facilities.csv"
)

EV_POLICY = SNAPSHOTS / "gd_ev_tariff_2018_313.html"
GD_2023_NOTICE = SNAPSHOTS / "gd_transmission_2023_148.html"
SZ_2023_ATTACHMENT = SNAPSHOTS / "shenzhen_grid_transmission_tariff_2023_attachment3.docx"
SZ_2026_QNA = SNAPSHOTS / "shenzhen_power_2026_qna.html"

EXPECTED = {
    "sharp_peak": 1.43716875,
    "peak": 1.15526875,
    "flat": 0.75776875,
    "valley": 0.25716875,
}
EXPECTED_TRANSMISSION = 0.1804
EXPECTED_DECOMPOSITION_FEN = {
    "agent_purchase": 51.13,
    "transmission": 18.04,
    "system_operation": 3.84,
    "government_funds": 2.766875,
}
ROW_KEY = (
    "common_101_to_3000_kVA_10kV_high_supply_high_metering_"
    "at_or_below_250kWh_per_kVA_month"
)
OLD_ROW_CLASS = "SHENZHEN_TWO_PART_ENERGY_COMPONENT_SCENARIO_PROXY"
NEW_ROW_CLASS = (
    "SHENZHEN_INDEPENDENT_METERED_EV_CHARGING_LARGE_USE_101_TO_3000_KVA_"
    "10KV_HIGH_HIGH_LE_250_ENERGY_ONLY_BASIC_FEE_EXEMPT_SCENARIO"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def normalized_html_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="strict")
    no_tags = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", "", html.unescape(no_tags))


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("word/document.xml").decode("utf-8")
    raw = raw.replace("</w:p>", "\n")
    return html.unescape(re.sub(r"<[^>]+>", "", raw))


def parse_2025_table() -> dict[str, float]:
    payload = json.loads(SHENZHEN_API.read_text(encoding="utf-8"))
    lines = payload["data"]["content"].splitlines()
    target = next(
        line
        for line in lines
        if "工商业用电(101至3000kVA)" in line
        and "10千伏高供高计" in line
        and "250kWh" in line
        and "及以下" in line
    )
    cells = [cell.strip() for cell in target.strip().strip("|").split("|")]
    require(len(cells) == 12, f"unexpected Shenzhen table width: {len(cells)}")
    return {
        "flat_direct": float(cells[1]) / 100.0,
        "agent_purchase_fen": float(cells[2]),
        "transmission_fen": float(cells[3]),
        "system_operation_fen": float(cells[4]),
        "government_funds_fen": float(cells[5]),
        "sharp_peak": float(cells[6]) / 100.0,
        "peak": float(cells[7]) / 100.0,
        "flat": float(cells[8]) / 100.0,
        "valley": float(cells[9]) / 100.0,
        "maximum_demand_cny_per_kw_month": float(cells[10]),
        "transformer_capacity_cny_per_kva_month": float(cells[11]),
    }


def audit() -> tuple[list[dict[str, str]], dict[str, object]]:
    evidence_rows: list[dict[str, str]] = []

    def add(
        evidence_id: str,
        evidence_type: str,
        source: Path,
        claim: str,
        observed: str,
    ) -> None:
        evidence_rows.append(
            {
                "evidence_id": evidence_id,
                "evidence_type": evidence_type,
                "source_path": source.relative_to(ROOT).as_posix(),
                "source_sha256": sha256(source),
                "claim": claim,
                "observed": observed,
                "status": "PASS",
            }
        )

    policy_text = normalized_html_text(EV_POLICY)
    require(
        "深圳市各类已安装独立电表的电动汽车充电设施用电"
        "，按报装容量执行相对应的大量用电或高需求用电电价标准" in policy_text,
        "2018 policy does not contain the Shenzhen independent-meter rule",
    )
    require("均免收基本电费" in policy_text, "2018 policy does not waive basic fees")
    add(
        "SZ-EV-RULE",
        "official_policy",
        EV_POLICY,
        "Independently metered Shenzhen EV charging uses the corresponding "
        "large-use or high-demand tariff by declared capacity.",
        "rule_present",
    )
    add(
        "SZ-EV-BASIC-FEE",
        "official_policy",
        EV_POLICY,
        "Independently metered EV charging facilities are exempt from basic fees.",
        "basic_fee_exempt",
    )

    qna_text = normalized_html_text(SZ_2026_QNA)
    require(
        "实际报装容量，执行相对应大量用电或高需求用电电价标准"
        "，且均免收容（需）量电费" in qna_text,
        "2026 Shenzhen Power Supply Bureau Q&A does not confirm the rule",
    )
    add(
        "SZ-EV-RULE-CURRENT-CHECK",
        "official_utility_confirmation",
        SZ_2026_QNA,
        "Shenzhen Power Supply Bureau still describes the capacity-based "
        "large-use/high-demand rule and capacity/demand-fee exemption.",
        "current_confirmation_present",
    )

    notice_text = normalized_html_text(GD_2023_NOTICE)
    require(
        "深圳市输配电价按附件3执行" in notice_text,
        "2023 Guangdong notice does not identify Shenzhen attachment 3",
    )
    add(
        "SZ-INDEPENDENT-PRICE-ZONE",
        "official_policy",
        GD_2023_NOTICE,
        "Shenzhen transmission tariff is governed by a separate attachment.",
        "independent_price_zone_confirmed",
    )

    attachment_text = re.sub(r"\s+", "", docx_text(SZ_2023_ATTACHMENT))
    require("工商业用电（101至3000千伏安）" in attachment_text, "capacity class missing")
    require("10千伏高供高计" in attachment_text, "10 kV high/high column missing")
    require("每月每千伏安用电250千瓦时及以下" in attachment_text, "utilization row missing")
    require("0.1804" in attachment_text, "0.1804 transmission component missing")
    add(
        "SZ-TRANSMISSION-ROW",
        "official_tariff_attachment",
        SZ_2023_ATTACHMENT,
        "The Shenzhen 101-3000 kVA, 10 kV high-supply/high-metering, "
        "at-or-below-250 kWh/kVA-month transmission component is 0.1804 CNY/kWh.",
        f"{EXPECTED_TRANSMISSION:.4f}",
    )

    parsed = parse_2025_table()
    for name, expected in EXPECTED_DECOMPOSITION_FEN.items():
        require(
            abs(parsed[f"{name}_fen"] - expected) <= 1e-12,
            f"2025 decomposition mismatch for {name}",
        )
    recomputed_flat = sum(EXPECTED_DECOMPOSITION_FEN.values()) / 100.0
    require(abs(recomputed_flat - EXPECTED["flat"]) <= 1e-12, "flat recomputation failed")
    require(abs(parsed["flat_direct"] - EXPECTED["flat"]) <= 1e-12, "direct flat mismatch")
    for period, expected in EXPECTED.items():
        require(abs(parsed[period] - expected) <= 1e-12, f"{period} mismatch")
        add(
            f"SZ-2025-02-{period.upper()}",
            "archived_grid_original_scan_recalculation",
            SHENZHEN_API,
            f"2025-02 Shenzhen selected scenario {period} energy price.",
            f"{parsed[period]:.8f}",
        )
    add(
        "SZ-2025-02-SCAN-BYTES",
        "archived_grid_original_scan",
        SHENZHEN_SCAN,
        "The visible Shenzhen Power Supply Bureau 2025-02 tariff scan is retained.",
        "scan_hash_bound",
    )

    register = json.loads(REGISTER_V2.read_text(encoding="utf-8"))
    candidate = register["one_to_ten_kv_candidate_rows"]["shenzhen"][ROW_KEY]
    for period, expected in EXPECTED.items():
        require(abs(float(candidate[period]) - expected) <= 1e-12, f"v2 {period} mismatch")
    add(
        "SZ-V2-REGISTER",
        "preregistered_machine_register",
        REGISTER_V2,
        "The selected numerical row existed in the pre-search v2 tariff register.",
        ROW_KEY,
    )

    builder_text = BUILDER.read_text(encoding="utf-8")
    require(ROW_KEY in builder_text, "pre-search builder did not select the row")
    require(OLD_ROW_CLASS in builder_text, "pre-search builder row label missing")
    add(
        "SZ-PRESEARCH-SELECTION",
        "pre_search_builder",
        BUILDER,
        "The zero-search static-input builder selected the same row before E3-E7 search.",
        ROW_KEY,
    )

    with FACILITIES.open(encoding="utf-8-sig", newline="") as handle:
        facility_rows = list(csv.DictReader(handle))
    shenzhen_facility = next(row for row in facility_rows if row["city"] == "shenzhen")
    require(float(shenzhen_facility["depot_power_kw"]) == 22.0, "power mismatch")
    require(int(shenzhen_facility["depot_gun_count"]) == 2, "charger count mismatch")
    add(
        "SZ-DEPOT-CHARGING-SCENARIO",
        "frozen_scenario_input",
        FACILITIES,
        "Shenzhen depot charging is a transparent 22 kW x 2 charger scenario proxy.",
        "22_kW_x_2",
    )

    with CALENDAR.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["city"] == "shenzhen"]
    require(len(rows) == 28 * 48, f"unexpected Shenzhen calendar rows: {len(rows)}")
    require({row["tariff_row_class"] for row in rows} == {OLD_ROW_CLASS}, "row class drift")
    # The February 48-slot calendar has no sharp-peak slots. The sharp-peak
    # table value is still bound above for the paper's complete tariff row.
    period_column = {"peak": "peak", "flat": "flat", "valley": "valley"}
    for key, csv_period in period_column.items():
        values = {
            float(row["depot_energy_cny_per_kwh"])
            for row in rows
            if row["tariff_period"] == csv_period
        }
        require(values == {EXPECTED[key]}, f"calendar mismatch for {key}: {values}")
    add(
        "SZ-FROZEN-CALENDAR",
        "frozen_static_input",
        CALENDAR,
        "All 28x48 Shenzhen rows use the selected scenario values.",
        "1344_rows_numeric_match",
    )

    recalculation = {
        "schema": "resetp.shenzhen-tariff-independent-recalculation.v1",
        "status": "PASS",
        "search_evaluations": 0,
        "formal_month": "2025-02",
        "scope": "preregistered_scenario_row_not_observed_depot_contract",
        "selected_row": {
            "customer_class": "independently_metered_EV_charging_facility",
            "declared_capacity_class": "above_100_below_315_kVA_within_101_to_3000_large_use",
            "voltage_and_metering": "10_kV_high_supply_high_metering",
            "monthly_utilization_class": "at_or_below_250_kWh_per_kVA",
            "scenario_status": "pre_search_scenario_choice_not_site_observation",
            "row_class_v3": NEW_ROW_CLASS,
        },
        "energy_price_cny_per_kwh": EXPECTED,
        "flat_price_recalculation": {
            "components_fen_per_kwh": EXPECTED_DECOMPOSITION_FEN,
            "sum_fen_per_kwh": sum(EXPECTED_DECOMPOSITION_FEN.values()),
            "sum_cny_per_kwh": recomputed_flat,
            "direct_table_cny_per_kwh": parsed["flat_direct"],
            "absolute_difference": abs(recomputed_flat - parsed["flat_direct"]),
        },
        "basic_fee": {
            "maximum_demand_table_value_cny_per_kw_month": parsed[
                "maximum_demand_cny_per_kw_month"
            ],
            "transformer_capacity_table_value_cny_per_kva_month": parsed[
                "transformer_capacity_cny_per_kva_month"
            ],
            "scenario_applied_cny": 0.0,
            "reason": "粤发改价格〔2018〕313号 exempts independently metered EV charging",
        },
        "data_effect": {
            "tariff_numeric_change": False,
            "frozen_calendar_rewritten": False,
            "solver_or_evaluator_change": False,
            "paper_row_added": True,
        },
    }
    return evidence_rows, recalculation


def write_outputs() -> None:
    evidence_rows, recalculation = audit()

    with (OUT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(evidence_rows[0]))
        writer.writeheader()
        writer.writerows(evidence_rows)

    (OUT / "independent_recalculation.json").write_text(
        json.dumps(recalculation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    source_paths = [
        EV_POLICY,
        GD_2023_NOTICE,
        SZ_2023_ATTACHMENT,
        SZ_2026_QNA,
        SHENZHEN_API,
        SHENZHEN_SCAN,
        REGISTER_V2,
        BUILDER,
        CALENDAR,
        FACILITIES,
    ]
    source_manifest = {
        "schema": "resetp.shenzhen-tariff-source-manifest.v1",
        "retrieved_or_verified_date": "2026-07-23",
        "sources": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256(path),
            }
            for path in source_paths
        ],
        "urls": {
            "gd_ev_tariff_2018_313": (
                "https://drc.gd.gov.cn/ywtz/content/post_833857.html"
            ),
            "gd_transmission_2023_148": (
                "https://drc.gd.gov.cn/ywtz/content/mpost_4186770.html"
            ),
            "shenzhen_grid_attachment_3": (
                "https://drc.gd.gov.cn/attachment/0/521/521210/4186770.docx"
            ),
            "shenzhen_power_2026_qna": (
                "https://szjgdj.sz.gov.cn/home/ztzl/mxq/jmlb/content/post_1656254.html"
            ),
            "shenzhen_2025_02_archive_page": (
                "https://energydc.cn/policy/shenzhen/2025-02/"
                "a1b09a22-f059-11f0-964f-46a1f660a16e"
            ),
        },
        "source_boundary": (
            "Policy and transmission-rule sources are official government/utility bytes. "
            "The 2025-02 total price is retained as a third-party digital archive of a "
            "visibly branded Shenzhen Power Supply Bureau original scan; an original "
            "utility URL was not located."
        ),
    }
    (OUT / "source_manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    metadata = {
        "task_id": "SHENZHEN-2025-02-TARIFF-CLOSURE-001",
        "date": "2026-07-23",
        "execution_type": "zero_search_evidence_audit",
        "search_evaluations": 0,
        "formal_experiment_authorized": False,
        "protected_files_changed": False,
        "parent_register": REGISTER_V2.relative_to(ROOT).as_posix(),
        "parent_register_sha256": sha256(REGISTER_V2),
        "audit_script_sha256": sha256(Path(__file__)),
    }
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    decision = {
        "verdict": "PASS_SHENZHEN_2025_02_EV_CHARGING_SCENARIO_ROW_CLOSED",
        "scope": "preregistered_scenario_row_only",
        "selected_row_class": NEW_ROW_CLASS,
        "energy_price_cny_per_kwh": EXPECTED,
        "basic_fee_cny": 0.0,
        "numeric_change_from_frozen_static_input": False,
        "observed_named_depot_contract_closed": False,
        "observed_contract_status": "UNKNOWN_NOT_CLAIMED",
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "claim_boundary": (
            "This closes the paper and future E3-E7 preregistered Shenzhen charging "
            "scenario. It does not establish the actual voltage, meter location, "
            "declared capacity, utilization or billing contract of the named Shenzhen depot."
        ),
    }
    (OUT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = f"""# 深圳 2025-02 独立价区充电电价情景闭合

判定：`PASS_SHENZHEN_2025_02_EV_CHARGING_SCENARIO_ROW_CLOSED`。

## 闭合结果

深圳不是沿用广东珠三角五市的一般工商业行。粤发改价格〔2018〕313号规定，深圳
独立计量的电动汽车充电设施按实际报装容量执行相应的大量用电或高需求用电电价，
并免收基本电费；深圳供电局 2026 年公开答复再次确认该规则仍按同一口径办理。

本文在任何 E3--E7 正式搜索前已经由静态输入构造器选择
`101--3000 kVA / 10 kV高供高计 / 每月每kVA用电量不超过250 kWh`
这一档。该档属于透明构造情景，不是深圳命名车场真实合同观测。按 2025 年 2 月
保存原表，尖峰、峰、平、谷分别为
`{EXPECTED['sharp_peak']:.8f}`、`{EXPECTED['peak']:.8f}`、
`{EXPECTED['flat']:.8f}`、`{EXPECTED['valley']:.8f}` 元/kWh。
平段由代购电、输配电、系统运行费和政府性基金附加
`51.13 + 18.04 + 3.84 + 2.766875 = 75.776875` 分/kWh 独立闭合。

## 为什么可以关闭原缺口

旧登记把深圳卡在“没有严格匹配的单一制数值行”。专项充电政策表明，这一前提不适用：
深圳独立计量充电设施应走大量用电/高需求用电专门规则；表内 48/22 元基本费列不进入
本文充电情景，因为专项政策明确免收基本电费。既有静态日历的电能量数值与新闭合行
逐位一致，故不重写封存 CSV、不改求解器、不改评价器，也不改变任何 E2 成绩。

## 边界

本判定只关闭“论文与未来 E3--E7 的预注册深圳充电电价情景”。普洛斯深圳龙华魔方
供应链大厦的真实报装容量、电压、计量点位置、月利用小时和合同账单仍未知；论文不得
把本情景写成该命名车场的实测合同。2025 年 2 月总电价数值仍来自保存的深圳供电局
原表扫描数字档案，尚未找到原始供电局发布 URL；政策规则与输配电价附件则已保存
政府原始字节并绑定 SHA-256。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")

    excluded = {"artifact_hashes.json"}
    hashes = []
    for path in sorted(OUT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(OUT).as_posix()
        if (
            rel in excluded
            or path.name.startswith("._")
            or "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
        ):
            continue
        hashes.append({"path": rel, "sha256": sha256(path)})
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(
            {
                "schema": "resetp.artifact-hashes.v1",
                "exclusions": [
                    "artifact_hashes.json",
                    "._*",
                    "__pycache__",
                    ".pytest_cache",
                ],
                "artifacts": hashes,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_outputs()
