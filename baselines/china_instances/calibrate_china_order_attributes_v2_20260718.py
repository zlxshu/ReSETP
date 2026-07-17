"""Build the source-audited China V2 order-attribute calibration package.

This script performs no solver search and does not generate formal instances.
It turns the ten-day Chinese freight case published with Zhang (2025) into a
machine-auditable calibration surface.  Observed fields, literature parameters
and constructed scenario proxies are deliberately kept separate.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "data/ChinaInstances/open_sources_20260717/figshare_28113608"
OUTPUT = REPO / "data/ChinaInstances/china_order_attribute_calibration_v2_20260718"
SOURCE_VEHICLE_CAPACITY_M3 = 7.2
TARGET_BOX_PAYLOAD_KG = 1000
LOCAL_ORIGIN_MINUTE = 8 * 60

EXPECTED_COLUMNS = {
    "Order number",
    "Pickup time window (early)",
    "Pickup time window (late)",
    "Delivery time window (early)",
    "Delivery time window (late)",
    "Volume of goods (m3)",
    "Loading and unloading time (h)",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def quantiles(series: pd.Series) -> dict[str, float]:
    return {
        "min": round(float(series.min()), 6),
        "p05": round(float(series.quantile(0.05)), 6),
        "p25": round(float(series.quantile(0.25)), 6),
        "median": round(float(series.quantile(0.50)), 6),
        "p75": round(float(series.quantile(0.75)), 6),
        "p95": round(float(series.quantile(0.95)), 6),
        "max": round(float(series.max()), 6),
        "mean": round(float(series.mean()), 6),
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((SOURCE / "SOURCE_METADATA.json").read_text(encoding="utf-8"))
    supplied_md5 = {row["name"]: row["supplied_md5"] for row in metadata["files"]}

    frames: list[pd.DataFrame] = []
    daily_rows: list[dict[str, Any]] = []
    source_files: list[dict[str, Any]] = []
    errors: list[str] = []

    for day in range(1, 11):
        path = SOURCE / f"Day%20{day}.xlsx"
        if not path.is_file():
            errors.append(f"MISSING_SOURCE_DAY_{day}")
            continue
        md5 = hashlib.md5(path.read_bytes()).hexdigest()  # nosec: source-integrity check only
        expected_md5 = supplied_md5.get(f"Day {day}.xlsx")
        if md5 != expected_md5:
            errors.append(f"MD5_MISMATCH_DAY_{day}:{md5}!={expected_md5}")
        frame = pd.read_excel(path, sheet_name="order")
        missing = sorted(EXPECTED_COLUMNS - set(frame.columns))
        if missing:
            errors.append(f"COLUMN_MISSING_DAY_{day}:{missing}")
            continue
        frame = frame.copy()
        frame["source_day"] = day
        frame["source_row"] = range(1, len(frame) + 1)
        frames.append(frame)
        source_files.append(
            {
                "day": day,
                "path": str(path.relative_to(REPO)),
                "rows": len(frame),
                "supplied_md5": expected_md5,
                "computed_md5": md5,
                "sha256": sha256(path),
            }
        )

    if errors or len(frames) != 10:
        write_json(
            OUTPUT / "decision.json",
            {
                "schema": "resetp.china.order-attribute-calibration-decision.v2",
                "decision": "HALT_SOURCE_INTEGRITY_OR_SCHEMA_FAILURE",
                "formal_instance_generation_allowed": False,
                "errors": errors,
            },
        )
        return 2

    orders = pd.concat(frames, ignore_index=True)
    orders["source_order_uid"] = orders.apply(
        lambda row: f"figshare28113608-d{int(row['source_day']):02d}-r{int(row['source_row']):03d}", axis=1
    )
    orders["delivery_early_minute"] = (
        LOCAL_ORIGIN_MINUTE + 60 * orders["Delivery time window (early)"].astype(float)
    ).round(6)
    orders["delivery_late_minute"] = (
        LOCAL_ORIGIN_MINUTE + 60 * orders["Delivery time window (late)"].astype(float)
    ).round(6)
    orders["delivery_width_minute"] = (
        60
        * (
            orders["Delivery time window (late)"].astype(float)
            - orders["Delivery time window (early)"].astype(float)
        )
    ).round(6)
    orders["pickup_width_minute"] = (
        60
        * (
            orders["Pickup time window (late)"].astype(float)
            - orders["Pickup time window (early)"].astype(float)
        )
    ).round(6)
    orders["demand_kg_capacity_share_proxy"] = (
        orders["Volume of goods (m3)"].astype(float) / SOURCE_VEHICLE_CAPACITY_M3 * TARGET_BOX_PAYLOAD_KG
    ).round().astype(int)
    orders["service_minutes_literature_rule"] = (
        60 * orders["Loading and unloading time (h)"].astype(float)
    ).round(6)

    relation_residual = (
        orders["Loading and unloading time (h)"].astype(float)
        - 0.1 * orders["Volume of goods (m3)"].astype(float)
    ).abs()
    if float(relation_residual.max()) > 1e-9:
        errors.append(f"SERVICE_RELATION_NOT_EXACT:max_residual={float(relation_residual.max())}")
    if orders["demand_kg_capacity_share_proxy"].max() >= TARGET_BOX_PAYLOAD_KG:
        errors.append("PROXY_DEMAND_NOT_BELOW_TARGET_PAYLOAD")
    if orders["delivery_early_minute"].min() < 360 or orders["delivery_late_minute"].max() > 1320:
        errors.append("DELIVERY_WINDOWS_OUTSIDE_0600_2200")

    export_columns = [
        "source_order_uid",
        "source_day",
        "source_row",
        "Order number",
        "Volume of goods (m3)",
        "Loading and unloading time (h)",
        "Delivery time window (early)",
        "Delivery time window (late)",
        "Pickup time window (early)",
        "Pickup time window (late)",
        "demand_kg_capacity_share_proxy",
        "service_minutes_literature_rule",
        "delivery_early_minute",
        "delivery_late_minute",
        "delivery_width_minute",
        "pickup_width_minute",
    ]
    empirical_path = OUTPUT / "empirical_order_attribute_rows.csv"
    orders[export_columns].to_csv(empirical_path, index=False, float_format="%.6f")

    volume_counts = (
        orders["Volume of goods (m3)"].value_counts().sort_index().rename_axis("volume_m3").reset_index(name="count")
    )
    volume_counts["share"] = volume_counts["count"] / len(orders)
    volume_counts["mapped_demand_kg"] = (
        volume_counts["volume_m3"] / SOURCE_VEHICLE_CAPACITY_M3 * TARGET_BOX_PAYLOAD_KG
    ).round().astype(int)

    for day, frame in orders.groupby("source_day", sort=True):
        daily_rows.append(
            {
                "day": int(day),
                "orders": len(frame),
                "mean_volume_m3": round(float(frame["Volume of goods (m3)"].mean()), 6),
                "mean_proxy_demand_kg": round(float(frame["demand_kg_capacity_share_proxy"].mean()), 6),
                "mean_delivery_window_minutes": round(float(frame["delivery_width_minute"].mean()), 6),
                "min_delivery_window_minutes": round(float(frame["delivery_width_minute"].min()), 6),
                "max_delivery_window_minutes": round(float(frame["delivery_width_minute"].max()), 6),
            }
        )
    raw_runs_path = OUTPUT / "raw_runs.csv"
    with raw_runs_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(daily_rows[0]))
        writer.writeheader()
        writer.writerows(daily_rows)

    calibration = {
        "schema": "resetp.china.order-attribute-calibration.v2",
        "source_scope": {
            "jurisdiction": "China",
            "case_description": "anonymous real-world less-than-truckload city-logistics enterprise in central China",
            "days": 10,
            "orders": len(orders),
            "observed_company_or_city_claim_allowed": False,
        },
        "source": {
            "dataset_doi": "10.6084/m9.figshare.28113608.v1",
            "dataset_license": "CC BY 4.0",
            "article_doi": "10.1371/journal.pone.0318432",
            "article": "Zhang J. A collaborative freight delivery problem with time windows under a crowdsourcing environment. PLOS ONE, 2025.",
            "source_files": source_files,
        },
        "classification": {
            "observed_fields": [
                "volume_m3",
                "pickup_window_early_and_late",
                "delivery_window_early_and_late",
            ],
            "literature_parameters_not_observed_stop_measurements": [
                "source_vehicle_capacity_7.2_m3",
                "loading_and_unloading_time_0.1_hour_per_m3",
            ],
            "constructed_scenario_proxy": [
                "demand_kg = round(volume_m3 / 7.2m3 * 1000kg)",
                "time origin conversion: minute_from_midnight = 480 + 60 * source_hour",
            ],
        },
        "statistics": {
            "volume_m3_counts": volume_counts.to_dict(orient="records"),
            "proxy_demand_kg": quantiles(orders["demand_kg_capacity_share_proxy"]),
            "service_minutes": quantiles(orders["service_minutes_literature_rule"]),
            "delivery_window_width_minutes": quantiles(orders["delivery_width_minute"]),
            "delivery_early_minute_from_midnight": quantiles(orders["delivery_early_minute"]),
            "delivery_late_minute_from_midnight": quantiles(orders["delivery_late_minute"]),
            "pickup_window_width_minutes": quantiles(orders["pickup_width_minute"]),
            "service_rule_max_absolute_residual_hour": round(float(relation_residual.max()), 12),
        },
        "proposed_generator_awaiting_user_approval": {
            "base_profile": "joint empirical-row resampling from all 1222 delivery rows",
            "joint_fields_preserved": [
                "mapped demand",
                "service duration",
                "delivery window start",
                "delivery window width",
            ],
            "sampling_rule": "seeded random permutation cycles; reshuffle each cycle; no result-dependent replacement",
            "formal_instance_application": "blocked until depot entrances and directed road-time matrices pass",
            "sensitivity_profiles": {
                "wide_pickup_proxy": "joint empirical-row resampling using pickup-window width; sensitivity only",
                "tight_delivery_lower_half": "sample only delivery rows at or below the preregistered global median width; sensitivity only",
            },
        },
        "scientific_boundary": (
            "The source volumes and promise-window fields are observed Chinese case data. "
            "Kilogram demand is a capacity-share scenario proxy, not observed shipment weight. "
            "Service duration follows the published case parameter and is not an observed stop-duration measurement."
        ),
    }
    calibration_path = OUTPUT / "calibration.json"
    write_json(calibration_path, calibration)

    decision = {
        "schema": "resetp.china.order-attribute-calibration-decision.v2",
        "decision": (
            "PASS_EVIDENCE_AUDIT_AWAITING_MODEL_TRANSFORMATION_APPROVAL"
            if not errors
            else "HALT_CALIBRATION_GATE_FAILED"
        ),
        "formal_instance_generation_allowed": False,
        "contract_lock_allowed": False,
        "reason_formal_blocked": (
            "the volume-to-kilogram capacity-share conversion and associated joint generator require explicit user "
            "approval; verified depot entrances and same-path directed road distance/time/energy matrices are also pending"
        ),
        "errors": errors,
        "order_count": len(orders),
        "calibration_sha256": sha256(calibration_path),
        "empirical_rows_sha256": sha256(empirical_path),
    }
    decision_path = OUTPUT / "decision.json"
    write_json(decision_path, decision)

    generated = datetime.now(timezone.utc).isoformat()
    write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.china.order-attribute-calibration-metadata.v2",
            "generated_at_utc": generated,
            "script": str(Path(__file__).resolve().relative_to(REPO)),
            "algorithm_search_evaluations": 0,
            "result_blind": True,
            "input_source": str(SOURCE.relative_to(REPO)),
        },
    )

    report = f"""# 中国 V2 订单硬参数标定报告

结论：`{decision["decision"]}`。本包只完成订单证据审计并提出转换候选，不锁定转换方法、不生成正式算例，也没有运行算法搜索。

## 数据与边界

来源为 Figshare 数据集 DOI `10.6084/m9.figshare.28113608.v1`，许可为 CC BY 4.0，对应 Zhang（2025）PLOS ONE 论文 DOI `10.1371/journal.pone.0318432`。论文将其描述为中国中部某真实零担城市物流企业的 10 个高峰日历史数据；城市和企业匿名，因此不得写成武汉或任何具名公司。

10 天共 {len(orders)} 条订单。原始观测字段是货物体积、取货时间窗和交付时间窗。文献给出的 7.2 立方米车辆容量和每立方米 0.1 小时装卸时间是案例参数，不是逐站实测。公斤需求采用容量占比转换：

`demand_kg = round(volume_m3 / 7.2 * 1000)`

其中 1000 公斤来自当前已锁定的中国厢式电车额定载重。该数值必须称为“容量占比构造代理”，不能称为企业实测重量。

## 标定结果

货物体积只取 1.0、1.5、2.0、2.5、3.0 立方米五档，对应 {", ".join(str(value) for value in volume_counts["mapped_demand_kg"].tolist())} 公斤。交付时间窗宽度中位数为 {calibration["statistics"]["delivery_window_width_minutes"]["median"]:.2f} 分钟，范围为 {calibration["statistics"]["delivery_window_width_minutes"]["min"]:.2f}–{calibration["statistics"]["delivery_window_width_minutes"]["max"]:.2f} 分钟；交付最晚时刻全部落在当前 06:00–22:00 城配运营窗内。

候选方案是整行联合经验重采样，同时保留需求、服务时长、时间窗起点和宽度之间的关系。它以及宽窗、紧窗敏感性设计都属于建模方案，必须经用户批准后才能写入正式合同。

## 尚未放行

当前首先被“体积到公斤的容量占比转换尚未获用户批准”阻断；即使获批，车场入口和同一路径有向道路距离、时间、能耗矩阵仍是后续阻断。缺一项即 HALT，不得用直线距离或统一车速偷偷替代。
"""
    report_path = OUTPUT / "report.md"
    report_path.write_text(report, encoding="utf-8")

    artifacts = {}
    for path in sorted(OUTPUT.iterdir()):
        if path.is_file() and path.name != "artifact_hashes.json":
            artifacts[str(path.relative_to(REPO))] = sha256(path)
    write_json(
        OUTPUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "artifacts": artifacts,
        },
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
