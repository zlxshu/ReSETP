#!/usr/bin/env python3
"""S6-SUP-01: source-bound export of the 50-customer simulation instance."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
STATIC_ROOT = ROOT / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
NODES_PATH = STATIC_ROOT / "instances" / INSTANCE_ID / "nodes.csv"
ORDERS_PATH = ROOT / "data/ChinaInstances/china81_order_attributes_mc001_v1_20260718/orders.csv"
CATALOG_PATH = STATIC_ROOT / "instance_catalog.csv"
STATIC_MANIFEST = STATIC_ROOT / "artifact_hashes.json"
LOADER_PATH = ROOT / "solver/src/setp_solver/china81.py"
HORIZON_START_SECOND = 6 * 60 * 60
HORIZON_END_SECOND = 22 * 60 * 60

DETAIL_FIELDS = [
    "编号",
    "节点类型",
    "经度",
    "纬度",
    "ET",
    "LT",
    "需求量(kg)",
    "服务时长(min)",
]
SOURCE_FIELDS = [
    "node_id",
    "node_type",
    "city",
    "source_longitude",
    "source_latitude",
    "source_et_minute",
    "source_lt_minute",
    "source_demand_kg",
    "source_service_minutes",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def scalar(value: str | float | int) -> str:
    """Render an integer-valued source scalar without invented decimals."""
    decimal = Decimal(str(value))
    if decimal == decimal.to_integral_value():
        return str(decimal.quantize(Decimal("1")))
    return format(decimal.normalize(), "f")


def local_hhmm(minutes_from_midnight: str | float) -> str:
    """Display source minutes as local HH:MM, rounded to the nearest minute."""
    minute = float(minutes_from_midnight)
    total_minutes = math.floor(minute + 0.5)
    if total_minutes < 0 or total_minutes > 24 * 60:
        raise ValueError(f"invalid minute-of-day value: {minutes_from_midnight}")
    hour, minute_part = divmod(total_minutes, 60)
    return f"{hour:02d}:{minute_part:02d}"


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def build_rows() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    node_rows = read_csv(NODES_PATH)
    order_rows = [
        row for row in read_csv(ORDERS_PATH)
        if row["instance_id"] == INSTANCE_ID
    ]
    orders = {row["customer_id"]: row for row in order_rows}
    selected_nodes = [
        row for row in node_rows
        if row["node_type"].strip().lower() in {"customer", "depot", "station"}
    ]
    customers = sorted(
        [row for row in selected_nodes if row["node_type"].strip().lower() == "customer"],
        key=lambda row: row["node_id"],
    )
    depots = sorted(
        [row for row in selected_nodes if row["node_type"].strip().lower() == "depot"],
        key=lambda row: row["city"].strip().lower(),
    )
    stations = sorted(
        [row for row in selected_nodes if row["node_type"].strip().lower() == "station"],
        key=lambda row: row["city"].strip().lower(),
    )
    if (
        len(customers) != 50
        or len(depots) != 2
        or len(stations) != 2
        or len(selected_nodes) != 54
    ):
        raise RuntimeError(
            f"source selection mismatch: customers={len(customers)}, "
            f"depots={len(depots)}, stations={len(stations)}, "
            f"selected={len(selected_nodes)}"
        )
    if [row["node_id"] for row in customers] != [f"C{i:03d}" for i in range(1, 51)]:
        raise RuntimeError("customer node IDs are not exactly C001--C050")
    if len(orders) != 50 or set(orders) != {f"C{i:03d}" for i in range(1, 51)}:
        raise RuntimeError("order source does not match C001--C050")

    detail_rows: list[dict[str, str]] = []
    source_rows: list[dict[str, str]] = []
    for number, node in enumerate(customers, start=1):
        order = orders[node["node_id"]]
        if order["city"].strip().lower() != node["city"].strip().lower():
            raise RuntimeError(f"city mismatch for {node['node_id']}")
        detail_rows.append({
            "编号": str(number),
            "节点类型": "客户",
            "经度": f"{float(node['longitude']):.4f}",
            "纬度": f"{float(node['latitude']):.4f}",
            "ET": local_hhmm(order["time_window_early_minute"]),
            "LT": local_hhmm(order["time_window_late_minute"]),
            "需求量(kg)": scalar(order["demand_kg"]),
            "服务时长(min)": scalar(order["service_minutes"]),
        })
        source_rows.append({
            "node_id": node["node_id"],
            "node_type": node["node_type"],
            "city": node["city"],
            "source_longitude": node["longitude"],
            "source_latitude": node["latitude"],
            "source_et_minute": order["time_window_early_minute"],
            "source_lt_minute": order["time_window_late_minute"],
            "source_demand_kg": order["demand_kg"],
            "source_service_minutes": order["service_minutes"],
        })

    for number, node in enumerate(depots, start=51):
        detail_rows.append({
            "编号": str(number),
            "节点类型": "车场",
            "经度": f"{float(node['longitude']):.4f}",
            "纬度": f"{float(node['latitude']):.4f}",
            "ET": "06:00",
            "LT": "22:00",
            "需求量(kg)": "-",
            "服务时长(min)": "-",
        })
        source_rows.append({
            "node_id": node["node_id"],
            "node_type": node["node_type"],
            "city": node["city"],
            "source_longitude": node["longitude"],
            "source_latitude": node["latitude"],
            "source_et_minute": "",
            "source_lt_minute": "",
            "source_demand_kg": "",
            "source_service_minutes": "",
        })

    for number, node in enumerate(stations, start=53):
        detail_rows.append({
            "编号": str(number),
            "节点类型": "充电站",
            "经度": f"{float(node['longitude']):.4f}",
            "纬度": f"{float(node['latitude']):.4f}",
            "ET": "06:00",
            "LT": "22:00",
            "需求量(kg)": "-",
            "服务时长(min)": "-",
        })
        source_rows.append({
            "node_id": node["node_id"],
            "node_type": node["node_type"],
            "city": node["city"],
            "source_longitude": node["longitude"],
            "source_latitude": node["latitude"],
            "source_et_minute": "",
            "source_lt_minute": "",
            "source_demand_kg": "",
            "source_service_minutes": "",
        })
    return detail_rows, source_rows, {
        "source_node_rows": len(node_rows),
        "source_order_rows_for_instance": len(order_rows),
        "selected_customer_rows": len(customers),
        "selected_depot_rows": len(depots),
        "selected_station_rows": len(stations),
    }


def write_tex(rows: list[dict[str, str]]) -> None:
    lines = [
        "% Auto-generated by run_s6_sup_01.py; paired table body only.",
        "% ET/LT are local HH:MM display values rounded from source minutes-of-day.",
    ]
    if len(rows) % 2:
        raise RuntimeError("paired TeX export requires an even row count")

    def cells(row: dict[str, str]) -> list[str]:
        return [
            row["编号"],
            row["节点类型"],
            row["经度"],
            row["纬度"],
            f"[{row['ET']},{row['LT']}]",
            row["需求量(kg)"],
            row["服务时长(min)"],
        ]

    half = len(rows) // 2
    for left, right in zip(rows[:half], rows[half:]):
        lines.append(" & ".join((*cells(left), *cells(right))) + r" \\")
    lines.append(r"\bottomrule")
    (OUT / "instance_details_table_body.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def artifact_files() -> list[Path]:
    excluded = {"artifact_hashes.json"}
    return sorted(
        path for path in OUT.rglob("*")
        if path.is_file()
        and path.name not in excluded
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    detail_rows, source_rows, counts = build_rows()
    write_csv(OUT / "instance_details.csv", detail_rows, DETAIL_FIELDS)
    write_csv(OUT / "source_extract.csv", source_rows, SOURCE_FIELDS)
    write_tex(detail_rows)

    source_paths = {
        "nodes": NODES_PATH,
        "orders": ORDERS_PATH,
        "instance_catalog": CATALOG_PATH,
        "static_input_manifest": STATIC_MANIFEST,
        "china81_loader_contract": LOADER_PATH,
        "script": Path(__file__).resolve(),
    }
    source_hashes = {
        rel(path): sha256(path)
        for path in source_paths.values()
        if path.is_file()
    }
    raw_ledger = [
        {
            "source_role": "nodes",
            "source_path": rel(NODES_PATH),
            "sha256": sha256(NODES_PATH),
            "row_count": len(read_csv(NODES_PATH)),
            "selected_row_count": (
                counts["selected_customer_rows"]
                + counts["selected_depot_rows"]
                + counts["selected_station_rows"]
            ),
        },
        {
            "source_role": "orders_for_instance",
            "source_path": rel(ORDERS_PATH),
            "sha256": sha256(ORDERS_PATH),
            "row_count": len(read_csv(ORDERS_PATH)),
            "selected_row_count": counts["source_order_rows_for_instance"],
        },
        {
            "source_role": "instance_catalog",
            "source_path": rel(CATALOG_PATH),
            "sha256": sha256(CATALOG_PATH),
            "row_count": len(read_csv(CATALOG_PATH)),
            "selected_row_count": 1,
        },
    ]
    write_csv(
        OUT / "raw_runs.csv",
        raw_ledger,
        ["source_role", "source_path", "sha256", "row_count", "selected_row_count"],
    )

    metadata = {
        "schema_version": "resetp.e2.s6-sup-01-instance-details.v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "instance_id": INSTANCE_ID,
        "construction": "China81 V2-LOCATIONS frozen static nodes joined to MC001 order attributes",
        "source_files": {key: rel(path) for key, path in source_paths.items()},
        "source_sha256": source_hashes,
        "output": {
            "rows": len(detail_rows),
            "customers": counts["selected_customer_rows"],
            "depots": counts["selected_depot_rows"],
            "stations": counts["selected_station_rows"],
            "customer_numbering": "C001--C050 -> 1--50",
            "depot_numbering": "source depots sorted by city: Guangzhou -> 51, Shenzhen -> 52",
            "station_numbering": "source stations sorted by city: Guangzhou -> 53, Shenzhen -> 54",
            "coordinate_order": "longitude, latitude",
            "coordinate_display_decimals": 4,
            "time_source_unit": "minutes from midnight",
            "time_display": "local HH:MM rounded to nearest minute; raw fractional source values are preserved in source_extract.csv",
            "depot_time_contract": "06:00--22:00 from solver CHINA81 horizon constants",
            "station_time_contract": "06:00--22:00 from solver CHINA81 horizon constants",
        },
        "protected_scope": {
            "main_tex_modified": False,
            "evaluator_modified": False,
            "sealed_inputs_modified": False,
        },
    }
    write_json(OUT / "metadata.json", metadata)
    decision = {
        "schema_version": "resetp.e2.s6-decision.v2",
        "decision": "PASS_S6_SUP_01_INSTANCE_DETAILS",
        "instance_id": INSTANCE_ID,
        "rows": len(detail_rows),
        "source_bound": True,
        "source_hashes_recorded": True,
        "data_entered_by_hand": False,
        "time_display_is_presentation_only": True,
    }
    write_json(OUT / "decision.json", decision)
    report = [
        "# S6-SUP-01 仿真算例详细信息表",
        "",
        "机器判定：`PASS_S6_SUP_01_INSTANCE_DETAILS`。",
        "",
        f"从冻结节点源导出 50 个客户、2 个车场和 2 个公共充电站，共 {len(detail_rows)} 行；客户编号为 1--50，车场为广州 51、深圳 52，充电站为广州 53、深圳 54。",
        "",
        "经纬度来自节点源的 longitude/latitude 字段并格式化为四位小数；ET/LT 来自订单源的分钟-of-day 字段，按本地时刻四舍五入到 HH:MM。完整小数源值另存于 `source_extract.csv`，没有手填或从图表反推。车场和充电站 ET/LT 使用冻结加载器的 06:00--22:00 时域，需求量和服务时长留 `-`。",
        "",
        "输入文件及 SHA-256 已写入 `metadata.json` 和 `raw_runs.csv`；主 TeX、评价器和封存输入没有修改。",
    ]
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "source_files": source_hashes,
            "files": {
                rel(path): sha256(path)
                for path in artifact_files()
            },
            "appledouble_excluded": True,
        },
    )
    print("PASS_S6_SUP_01_INSTANCE_DETAILS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
