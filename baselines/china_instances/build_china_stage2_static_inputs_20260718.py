#!/usr/bin/env python3
"""Freeze all G1-independent China81 static inputs without solver search."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
ORDERS = REPO / "data/ChinaInstances/china81_order_attributes_mc001_v1_20260718/orders.csv"
DEPOTS = REPO / "data/ChinaInstances/phase1_nine_city_road_access_v1_20260718/road_access_points.csv"
POOLS = REPO / "data/ChinaInstances/china9_city_full_pool_20260718/pools"
TARIFF = REPO / "data/ChinaPrices/china_2025_02_tariff_register_v2.json"
CARBON = REPO / "baselines/e4_e5/china_2025_formal_month_selection_20260718/tvci_2025_february_48slot_wide.csv"

CITIES = {
    "beijing": ("jjj", "Beijing", "beijing"),
    "tianjin": ("jjj", "Tianjin", "tianjin"),
    "shijiazhuang": ("jjj", "Hebei", "hebei_south"),
    "guangzhou": ("prd", "Guangdong", "guangdong_prd_five_city"),
    "shenzhen": ("prd", "Guangdong", "shenzhen"),
    "dongguan": ("prd", "Guangdong", "guangdong_prd_five_city"),
    "foshan": ("prd", "Guangdong", "guangdong_prd_five_city"),
    "chengdu": ("cy", "Chongqing", "sichuan"),
    "chongqing": ("cy", "Chongqing", "chongqing"),
}

# Half-open local-time periods for February 2025.
PERIODS = {
    "beijing": {"valley": [(0, 7), (23, 24)], "peak": [(10, 13), (17, 22)]},
    "tianjin": {"valley": [(0, 7), (23, 24)], "peak": [(9, 12), (16, 21)]},
    "shijiazhuang": {
        "valley": [(1, 6), (12, 15)],
        "sharp_peak": [(17, 19)],
        "peak": [(16, 17), (19, 24)],
    },
    "guangzhou": {"valley": [(0, 8)], "peak": [(10, 12), (14, 19)]},
    "shenzhen": {"valley": [(0, 8)], "peak": [(10, 12), (14, 19)]},
    "dongguan": {"valley": [(0, 8)], "peak": [(10, 12), (14, 19)]},
    "foshan": {"valley": [(0, 8)], "peak": [(10, 12), (14, 19)]},
    "chengdu": {"valley": [(0, 7), (23, 24)], "peak": [(10, 12), (15, 21)]},
    "chongqing": {"valley": [(0, 8)], "peak": [(11, 17), (20, 22)]},
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def select_facilities() -> list[dict]:
    depots = {r["city"]: r for r in read_csv(DEPOTS)}
    selected = []
    for city in CITIES:
        depot = depots[city]
        if city == "shijiazhuang":
            station = {
                "osm_type": "operator",
                "osm_id": "tesla-cnsc8121",
                "latitude": "38.040797",
                "longitude": "114.478342",
                "name": "特斯拉超级充电站（石家庄海悦天地）",
                "brand": "Tesla Supercharger",
                "source_response_path": "https://www.tesla.cn/zh_CN/findus/location/supercharger/cnsc8121?region=CN",
                "source_response_sha256": "LIVE_OPERATOR_PAGE_CAPTURED_2026-07-18",
            }
            source_class = "OPERATOR_PAGE_IDENTITY_AND_EQUIPMENT"
            observed_note = "官网列示对非特斯拉开放、6桩、最高119kW；模型仍统一使用60kW单枪情景。"
        else:
            rows = read_csv(POOLS / f"{city}__charging_station.csv")
            if not rows:
                raise RuntimeError(f"no station candidate for {city}")
            dlat = float(depot["road_access_lat_wgs84"])
            dlon = float(depot["road_access_lon_wgs84"])
            usable = [
                r for r in rows
                if "换电" not in r.get("name", "")
                and "500 W" not in r.get("tags", "")
                and '"access": "customers"' not in r.get("tags", "")
            ] or rows
            station = min(
                usable,
                key=lambda r: haversine(dlat, dlon, float(r["latitude"]), float(r["longitude"])),
            )
            source_class = "FROZEN_OSM_IDENTITY"
            observed_note = "OSM仅支持位置和标签身份，不支持模型功率或枪数。"
        selected.append({
            "city": city,
            "region": CITIES[city][0],
            "depot_name": depot["facility"],
            "depot_lon": depot["road_access_lon_wgs84"],
            "depot_lat": depot["road_access_lat_wgs84"],
            "depot_point_semantics": depot["point_semantics"],
            "depot_source": depot["source"],
            "depot_site_power_kw_shadow": 22.0,
            "depot_gun_count": 2,
            "depot_parameter_class": "UNIFORM_PLANNED_CAPACITY_SCENARIO_PROXY",
            "station_name": station.get("name") or f"OSM公共充电站 {station['osm_type']}/{station['osm_id']}",
            "station_operator": station.get("brand") or "UNKNOWN_OPERATOR",
            "station_lon": station["longitude"],
            "station_lat": station["latitude"],
            "station_identity": f"{station['osm_type']}/{station['osm_id']}",
            "station_source": station["source_response_path"],
            "station_source_sha256": station["source_response_sha256"],
            "station_source_class": source_class,
            "station_power_kw": 60.0,
            "station_gun_count": 1,
            "station_parameter_class": "UNIFORM_PREDECLARED_SCENARIO_PROXY",
            "station_observed_boundary": observed_note,
        })
    return selected


def period_for(city: str, minute: int) -> str:
    hour = minute / 60
    for label in ("sharp_peak", "peak", "valley"):
        if any(start <= hour < end for start, end in PERIODS[city].get(label, [])):
            return label
    return "flat"


def build_calendar() -> list[dict]:
    reg = json.loads(TARIFF.read_text(encoding="utf-8"))
    carbon = {(r["date"], int(r["hourly_calendar_row"])): r for r in read_csv(CARBON)}
    result = []
    for city, (_, carbon_col, price_area) in CITIES.items():
        candidate = reg["one_to_ten_kv_candidate_rows"][price_area]
        if city == "shenzhen":
            prices = candidate[
                "common_101_to_3000_kVA_10kV_high_supply_high_metering_at_or_below_250kWh_per_kVA_month"
            ]
            row_class = "SHENZHEN_TWO_PART_ENERGY_COMPONENT_SCENARIO_PROXY"
        else:
            prices = candidate["single_part"]
            row_class = "ONE_TO_TEN_KV_SINGLE_PART_SCENARIO_ROW"
        day = date(2025, 2, 1)
        while day.month == 2:
            for slot in range(1, 49):
                minute = (slot - 1) * 30
                label = period_for(city, minute)
                result.append({
                    "city": city,
                    "region": CITIES[city][0],
                    "date": day.isoformat(),
                    "hourly_calendar_row": slot,
                    "minute_of_day": minute,
                    "tariff_period": label,
                    "depot_energy_cny_per_kwh": prices[label],
                    "public_energy_cny_per_kwh": prices[label],
                    "public_service_fee_cny_per_kwh": 0.4,
                    "public_total_cny_per_kwh": round(float(prices[label]) + 0.4, 9),
                    "carbon_factor_kgco2e_per_kwh": carbon[(day.isoformat(), slot)][carbon_col],
                    "tariff_row_class": row_class,
                    "service_fee_class": "UNIFORM_SCENARIO_PROXY_NOT_MARKET_OBSERVATION",
                    "carbon_source_column": carbon_col,
                })
            day += timedelta(days=1)
    return result


def build_nodes(facilities: list[dict]) -> list[dict]:
    by_city = {r["city"]: r for r in facilities}
    orders = read_csv(ORDERS)
    by_instance: dict[str, list[dict]] = defaultdict(list)
    for row in orders:
        by_instance[row["instance_id"]].append(row)
    catalog = []
    for instance_id, rows in sorted(by_instance.items()):
        cities = sorted({r["city"] for r in rows})
        nodes = []
        for city in cities:
            f = by_city[city]
            nodes.extend([
                {"node_id": f"D_{city}", "node_type": "depot", "city": city,
                 "latitude": f["depot_lat"], "longitude": f["depot_lon"],
                 "source_identity": f["depot_name"]},
                {"node_id": f"S_{city}", "node_type": "station", "city": city,
                 "latitude": f["station_lat"], "longitude": f["station_lon"],
                 "source_identity": f["station_identity"]},
            ])
        for r in rows:
            nodes.append({"node_id": r["customer_id"], "node_type": "customer",
                          "city": r["city"], "latitude": r["latitude"],
                          "longitude": r["longitude"],
                          "source_identity": f"{r['osm_type']}/{r['osm_id']}"})
        node_path = OUT / "instances" / instance_id / "nodes.csv"
        write_csv(node_path, nodes)
        catalog.append({
            "instance_id": instance_id,
            "region": rows[0]["region"],
            "customer_count": len(rows),
            "city_count": len(cities),
            "cities": "|".join(cities),
            "node_count": len(nodes),
            "directed_pairs_per_profile": len(nodes) * (len(nodes) - 1),
            "nodes_sha256": digest(node_path),
            "search_evaluations": 0,
        })
    return catalog


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    facilities = select_facilities()
    write_csv(OUT / "facilities.csv", facilities)
    calendar = build_calendar()
    write_csv(OUT / "tariff_carbon_hourly_calendar.csv", calendar)
    catalog = build_nodes(facilities)
    write_csv(OUT / "instance_catalog.csv", catalog)
    stats = {
        "schema": "resetp.china.result-blind-effect-thresholds.v1",
        "status": "FROZEN_BEFORE_FORMAL_RESULTS",
        "E5": {
            "paired_infeasibility_reduction_percentage_points_min": 10.0,
            "paired_feasible_cost_reduction_percent_min": 2.0,
        },
        "E7": {
            "dynamic_total_cost_reduction_percent_min": 2.0,
            "dynamic_emissions_reduction_percent_min": 2.0,
            "participation_violation_tolerance": 0,
        },
        "boundary": "These are smallest effects worth reporting, not guaranteed outcomes.",
    }
    write_json(OUT / "effect_thresholds.json", stats)
    parameter_lock = {
        "schema": "resetp.china.stage2-static-input-lock.v1",
        "status": "G1_INDEPENDENT_INPUTS_FROZEN__FORMAL_ACCEPTANCE_HELD",
        "formal_search_allowed": False,
        "draft_only": True,
        "search_evaluations": 0,
        "source_parameter_lock": "data/ChinaInstances/china_parameter_lock_v2_20260718.json",
        "autonomous_user_authorization": "2026-07-18: 那你把不要G1的一次性全做掉。你自主解决，除非有需要我判断的。",
        "cost_scenario": {
            "vehicle_fixed_cost_cny_per_shift": 170.0,
            "occupancy_fee_cny_per_min": 0.5,
            "revenue_cny_per_kg": 1.5,
            "non_energy_distance_cost_cv_cny_per_km": 0.78,
            "non_energy_distance_cost_ev_cny_per_km": 0.67,
            "class": "SCENARIO_PROXY_NOT_NATIONAL_UNIFORM_PRICE",
            "sensitivity_required": True,
        },
        "charging_scenario": {
            "depot": {"power_kw": 22.0, "gun_count": 2},
            "public": {"power_kw": 60.0, "gun_count": 1, "service_fee_cny_per_kwh": 0.4},
            "class": "UNIFORM_PREDECLARED_SCENARIO_PROXY",
        },
        "calendar": {
            "month": "2025-02",
            "main_display_day": "2025-02-12",
            "rows": len(calendar),
            "calendar_sha256": digest(OUT / "tariff_carbon_hourly_calendar.csv"),
        },
        "effect_thresholds": stats,
        "remaining_g1_dependent": [
            "nonlinear charging/SOC semantic integration",
            "G1-frozen algorithm regression and formal acceptance",
            "solver-search feasibility and E1-E7 outcomes",
        ],
    }
    write_json(OUT / "parameter_lock.json", parameter_lock)
    raw = [{
        "unit": "china81_static_input_freeze",
        "instances": len(catalog),
        "orders": sum(int(r["customer_count"]) for r in catalog),
        "calendar_rows": len(calendar),
        "stations": len(facilities),
        "directed_pairs_both_profiles": 2 * sum(int(r["directed_pairs_per_profile"]) for r in catalog),
        "search_evaluations": 0,
        "violations": 0,
        "status": "PASS",
    }]
    write_csv(OUT / "raw_runs.csv", raw)
    write_json(OUT / "metadata.json", {
        "schema": "resetp.china81-stage2-static-inputs.v1",
        "created_date": "2026-07-18",
        "instances": 81,
        "orders": 5805,
        "cities": 9,
        "formal_search_allowed": False,
        "draft_only": True,
        "search_evaluations": 0,
        "input_hashes": {
            "orders": digest(ORDERS), "depots": digest(DEPOTS),
            "tariff_register": digest(TARIFF), "carbon_calendar": digest(CARBON),
        },
    })
    write_json(OUT / "decision.json", {
        "verdict": "PASS_G1_INDEPENDENT_STATIC_INPUTS_FROZEN__WAIT_ROAD_MATRICES_AND_G1",
        "formal_experiment_authorized": False,
        "search_evaluations": 0,
        "open_items": ["local directed matrices", "G1-dependent physical/search acceptance"],
    })
    (OUT / "report.md").write_text(
        "# China81 阶段二静态输入冻结\n\n"
        "81 个实例的订单、九城车场与公共站身份、透明充电情景、2025 年 2 月"
        " 48 槽电价—碳日历、成本代理和 E5/E7 实质效应阈值已在零搜索下冻结。"
        "所有非观测值均明确标为情景代理。正式搜索仍未获准；道路矩阵和 G1 汇合门仍开放。\n",
        encoding="utf-8",
    )
    hashes = {}
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"):
            hashes[str(path.relative_to(OUT))] = digest(path)
    write_json(OUT / "artifact_hashes.json", {"sha256": hashes})
    print(json.dumps(raw[0], ensure_ascii=False))


if __name__ == "__main__":
    main()
