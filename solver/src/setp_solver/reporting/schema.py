from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "setp-reporting.v1"

EXPERIMENT_FIELDS = [
    "schema_version",
    "experiment_id",
    "instance",
    "algorithm",
    "seed",
    "budget",
    "cost_fixed",
    "cost_distance",
    "cost_fuel",
    "cost_electricity",
    "cost_occupancy",
    "cost_cross_site",
    "cost_carbon_trading",
    "total_cost",
    "diesel_carbon_kg",
    "charging_carbon_kg",
    "total_carbon_kg",
    "stake",
    "ev_count",
    "cv_count",
    "cross_site_customers",
    "profit_by_depot_json",
    "feasible",
    "elapsed_seconds",
    "evals",
    "source_report_path",
]

EXPERIMENT_FIELD_LABELS = {
    "schema_version": "schema版本",
    "experiment_id": "实验ID",
    "instance": "算例",
    "algorithm": "算法",
    "seed": "种子",
    "budget": "预算",
    "cost_fixed": "固定成本",
    "cost_distance": "里程成本",
    "cost_fuel": "燃油成本",
    "cost_electricity": "电费",
    "cost_occupancy": "占用成本",
    "cost_cross_site": "跨场成本",
    "cost_carbon_trading": "碳交易成本",
    "total_cost": "总成本",
    "diesel_carbon_kg": "柴油碳",
    "charging_carbon_kg": "充电碳",
    "total_carbon_kg": "总碳",
    "stake": "充电碳占比",
    "ev_count": "电车数",
    "cv_count": "油车数",
    "cross_site_customers": "跨场客户数",
    "profit_by_depot_json": "各场Π_d",
    "feasible": "可行",
    "elapsed_seconds": "耗时s",
    "evals": "评估数",
    "source_report_path": "来源报告",
}

_EXPERIMENT_LABEL_TO_FIELD = {label: field for field, label in EXPERIMENT_FIELD_LABELS.items()}


def blank_record() -> dict[str, Any]:
    return {field: "" for field in EXPERIMENT_FIELDS}


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    out = blank_record()
    out.update(record)
    out["schema_version"] = out.get("schema_version") or SCHEMA_VERSION
    for key, value in list(out.items()):
        if value is None:
            out[key] = ""
        elif isinstance(value, bool):
            out[key] = "是" if value else "否"
    return out


def write_records(records: list[dict[str, Any]], csv_path: str | Path, json_path: str | Path) -> None:
    normalized = [normalize_record(record) for record in records]
    csv_file = Path(csv_path)
    json_file = Path(json_path)
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.parent.mkdir(parents=True, exist_ok=True)
    csv_fields = [EXPERIMENT_FIELD_LABELS[field] for field in EXPERIMENT_FIELDS]
    with csv_file.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for row in normalized:
            writer.writerow({EXPERIMENT_FIELD_LABELS[field]: row.get(field, "") for field in EXPERIMENT_FIELDS})
    with json_file.open("w", encoding="utf-8") as handle:
        json.dump({"schema_version": SCHEMA_VERSION, "records": normalized}, handle, indent=2, ensure_ascii=False)


def read_rows(csv_path: str | Path) -> list[dict[str, str]]:
    with Path(csv_path).open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_records(csv_path: str | Path) -> list[dict[str, str]]:
    return [
        {_EXPERIMENT_LABEL_TO_FIELD.get(key, key): value for key, value in row.items()}
        for row in read_rows(csv_path)
    ]


def write_rows(csv_path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
