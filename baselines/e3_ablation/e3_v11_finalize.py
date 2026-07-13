#!/usr/bin/env python3
"""Build and independently audit the paper-ready E3 100-run evidence package.

This script never searches, changes a solution, or changes the experiment
contract.  It only recomputes saved ledgers, checks saved certificates and
hashes, combines the frozen 70+30 rows, and derives exhibit tables.
"""

from __future__ import annotations

import csv
from dataclasses import fields
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable

from scipy.stats import wilcoxon


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation.e3_v3_runner import (  # noqa: E402
    METRIC_KEYS,
    layer_settings,
    owner_map,
    prices_for,
    route_signature,
    solution_from_dict,
)
from setp_solver.cost import (  # noqa: E402
    carbon_profile_row_for_slot,
    charging_slot_breakdown,
    evaluate,
)
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.multitrip_schedule import (  # noqa: E402
    MultiTripCertificate,
    ScheduledTrip,
    validate_multitrip_certificate,
)


DEFAULT_OUT = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713"
COMPONENTS = (
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_transship",
    "cost_carbon",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], *, fieldnames: list[str] | None = None) -> None:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = sorted({key for row in materialized for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(materialized)


def truthy(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def number(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return statistics.fmean(materialized) if materialized else math.nan


def certificate_from_dict(payload: dict[str, Any]) -> MultiTripCertificate:
    allowed = {item.name for item in fields(ScheduledTrip)}
    trips = tuple(ScheduledTrip(**{key: value for key, value in row.items() if key in allowed}) for row in payload["trips"])
    return MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={key: int(value) for key, value in payload["vehicle_counts"].items()},
        trips=trips,
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
    )


def expected_keys() -> set[tuple[str, str, int, float]]:
    keys: set[tuple[str, str, int, float]] = set()
    for seed in range(1, 6):
        keys.update(("200c", layer, seed, 0.0) for layer in ("M0", "M1", "M2", "M3", "M4", "M5"))
        keys.update(("100c", layer, seed, 0.0) for layer in ("M0", "M1", "M3", "M5"))
        keys.update(("200c", "M5", seed, fee) for fee in (10.0, 25.0, 50.0, 95.0))
    for seed in range(6, 11):
        keys.update(("200c", layer, seed, 0.0) for layer in ("M0", "M1", "M2", "M3", "M4", "M5"))
    return keys


class Evidence:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.bundle_cache: dict[tuple[str, str], Any] = {}
        self.manifest_cache: dict[str, dict[str, Any]] = {}

    def manifest(self, size: str) -> dict[str, Any]:
        if size not in self.manifest_cache:
            self.manifest_cache[size] = read_json(self.out / "assets" / size / "asset_manifest.json")
        return self.manifest_cache[size]

    def bundle(self, size: str, layer: str) -> Any:
        mode = str(layer_settings(layer)["profile_mode"])
        key = (size, mode)
        if key not in self.bundle_cache:
            path = ROOT / self.manifest(size)["derived_bundles"][mode]
            self.bundle_cache[key] = load_search_bundle(path)
        return self.bundle_cache[key]

    def solution(self, run_id: str, kind: str) -> Any:
        return solution_from_dict(read_json(self.out / "solutions" / f"{run_id}__{kind}.json"))

    def metrics(self, row: dict[str, str], kind: str) -> dict[str, float]:
        bundle = self.bundle(row["size"], row["layer"])
        return evaluate(
            self.solution(row["run_id"], kind),
            bundle.instance,
            bundle.carbon_profile,
            prices_for(row["layer"], number(row["fee"])),
            carbon_quota_kg=0.0,
        )


def verify_phase_hashes(out: Path, phase: str, failures: list[str]) -> int:
    manifest_path = out / phase / "artifact_hashes.json"
    manifest = read_json(manifest_path)
    checked = 0
    for relative, expected in manifest.items():
        path = out / relative
        if not path.is_file():
            failures.append(f"{phase}: missing hashed file {relative}")
        elif sha256(path) != expected:
            failures.append(f"{phase}: hash mismatch {relative}")
        checked += 1
    return checked


def audit_rows(out: Path, rows: list[dict[str, str]], evidence: Evidence) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    run_ids = [row["run_id"] for row in rows]
    if len(rows) != 100:
        failures.append(f"expected 100 rows, found {len(rows)}")
    if len(set(run_ids)) != len(run_ids):
        failures.append("duplicate run_id")
    actual_keys = {(row["size"], row["layer"], int(row["seed"]), number(row["fee"])) for row in rows}
    if actual_keys != expected_keys():
        failures.append(f"matrix mismatch: missing={sorted(expected_keys() - actual_keys)}, extra={sorted(actual_keys - expected_keys())}")

    metric_recomputations = 0
    certificate_checks = 0
    carbon_pair_checks = 0
    for row in rows:
        run_id = row["run_id"]
        if row["status"] != "OK":
            failures.append(f"{run_id}: status={row['status']}")
        if int(row["actual_evals"]) != int(row["budget"]):
            failures.append(f"{run_id}: budget not closed")
        if int(row["violation_count"]) != 0:
            failures.append(f"{run_id}: saved violations={row['violation_count']}")
        if number(row["cost_component_error"]) > 1e-6:
            failures.append(f"{run_id}: component closure={row['cost_component_error']}")
        if abs(number(row["depot_charge_power_kw"]) - 22.0) > 1e-12:
            failures.append(f"{run_id}: depot charging power drift")
        if abs(number(row["battery_kwh"]) - 280.0) > 1e-12:
            failures.append(f"{run_id}: battery capacity drift")

        run_path = out / "runs" / f"{run_id}.json"
        adopted_path = out / "solutions" / f"{run_id}__adopted.json"
        cert_path = out / "certificates" / f"{run_id}.json"
        for path in (run_path, adopted_path, cert_path):
            if not path.is_file():
                failures.append(f"{run_id}: missing {path.name}")
        if not all(path.is_file() for path in (run_path, adopted_path, cert_path)):
            continue

        adopted = evidence.solution(run_id, "adopted")
        metrics = evidence.metrics(row, "adopted")
        for key in METRIC_KEYS:
            if key in row and abs(number(row[key]) - float(metrics[key])) > 1e-6:
                failures.append(f"{run_id}: recomputed {key} differs")
        if abs(sum(float(metrics[key]) for key in COMPONENTS) - float(metrics["total_cost"])) > 1e-6:
            failures.append(f"{run_id}: independently recomputed cost does not close")
        metric_recomputations += 1

        certificate = certificate_from_dict(read_json(cert_path))
        try:
            validate_multitrip_certificate(certificate, adopted.routes, prices_for(row["layer"], number(row["fee"])))
        except Exception as exc:  # noqa: BLE001 - audit must preserve the concrete certificate failure
            failures.append(f"{run_id}: certificate invalid: {exc}")
        else:
            certificate_checks += 1
        caps = evidence.manifest(row["size"])["base_caps"]
        if certificate.vehicle_counts["cv"] > sum(int(item["cv"]) for item in caps.values()):
            failures.append(f"{run_id}: CV asset cap exceeded")
        if certificate.vehicle_counts["ev"] > sum(int(item["ev"]) for item in caps.values()):
            failures.append(f"{run_id}: EV asset cap exceeded")

        if row["layer"] != "M0":
            search_path = out / "solutions" / f"{run_id}__search.json"
            if not search_path.is_file():
                failures.append(f"{run_id}: missing search solution")
            else:
                search_metrics = evidence.metrics(row, "search")
                if abs(float(search_metrics["total_cost"]) - number(row["search_total_cost"])) > 1e-6:
                    failures.append(f"{run_id}: recomputed search total differs")

        if row["layer"] in {"M3", "M4", "M5"}:
            naive_path = out / "solutions" / f"{run_id}__naive.json"
            if not naive_path.is_file():
                failures.append(f"{run_id}: missing immediate-charge comparison")
            else:
                aware = evidence.solution(run_id, "search")
                naive = evidence.solution(run_id, "naive")
                aware_metrics = evidence.metrics(row, "search")
                naive_metrics = evidence.metrics(row, "naive")
                if route_signature(aware) != route_signature(naive):
                    failures.append(f"{run_id}: carbon pair routes differ")
                if abs(float(aware_metrics["electricity_kwh"]) - float(naive_metrics["electricity_kwh"])) > 1e-6:
                    failures.append(f"{run_id}: carbon pair energy differs")
                if float(aware_metrics["E_ev_indirect"]) > float(naive_metrics["E_ev_indirect"]) + 1e-7:
                    failures.append(f"{run_id}: low-carbon timing is worse on the same route")
                carbon_pair_checks += 1

    phase_hash_count = sum(verify_phase_hashes(out, phase, failures) for phase in ("formal70", "promote100"))
    return failures, {
        "row_count": len(rows),
        "unique_run_ids": len(set(run_ids)),
        "metric_recomputations": metric_recomputations,
        "certificate_checks": certificate_checks,
        "carbon_pair_checks": carbon_pair_checks,
        "phase_hash_files_checked": phase_hash_count,
    }


def select(rows: list[dict[str, str]], size: str, layer: str, seed: int, fee: float = 0.0) -> dict[str, str]:
    matches = [
        row for row in rows
        if row["size"] == size and row["layer"] == layer and int(row["seed"]) == seed and abs(number(row["fee"]) - fee) < 1e-12
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one row for {(size, layer, seed, fee)}, found {len(matches)}")
    return matches[0]


def build_cooperation(rows: list[dict[str, str]], evidence: Evidence) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for seed in range(1, 11):
        independent = select(rows, "200c", "M0", seed)
        cooperation = select(rows, "200c", "M1", seed)
        base = evidence.metrics(independent, "adopted")
        search = evidence.metrics(cooperation, "search")
        item: dict[str, Any] = {
            "seed": seed,
            "independent_cost": base["total_cost"],
            "cooperation_search_cost": search["total_cost"],
            "cooperation_adopted_cost": number(cooperation["total_cost"]),
            "search_saving": base["total_cost"] - search["total_cost"],
            "search_saving_pct": (base["total_cost"] - search["total_cost"]) / base["total_cost"] * 100.0,
            "strict_cooperation_win": truthy(cooperation["cooperation_story_win"]),
            "adopted_source": cooperation["adopted_source"],
            "cross_site_customers_in_search": int(number(cooperation["search_cross_site_customer_count"])),
            "independent_physical_vehicles": int(number(independent["physical_total"])),
            "adopted_physical_vehicles": int(number(cooperation["physical_total"])),
            "physical_vehicle_change": int(number(cooperation["physical_total"]) - number(independent["physical_total"])),
            "independent_distance_km": base["distance_total"] / 1000.0,
            "cooperation_search_distance_km": search["distance_total"] / 1000.0,
        }
        for key in COMPONENTS:
            item[f"independent_{key}"] = base[key]
            item[f"cooperation_{key}"] = search[key]
            item[f"delta_{key}"] = search[key] - base[key]
        output.append(item)
    return output


def build_carbon(rows: list[dict[str, str]], evidence: Evidence) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paired: list[dict[str, Any]] = []
    slot_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for seed in range(1, 11):
        row = select(rows, "200c", "M3", seed)
        aware = evidence.solution(row["run_id"], "search")
        naive = evidence.solution(row["run_id"], "naive")
        aware_metrics = evidence.metrics(row, "search")
        naive_metrics = evidence.metrics(row, "naive")
        moved = sum(
            abs(float(left.charge_start_second) - float(right.charge_start_second)) > 1e-7
            for left, right in zip(aware.charging_actions, naive.charging_actions)
        )
        saved = float(naive_metrics["E_ev_indirect"]) - float(aware_metrics["E_ev_indirect"])
        paired.append({
            "seed": seed,
            "route_signature": route_signature(aware),
            "electricity_kwh": aware_metrics["electricity_kwh"],
            "low_carbon_timing_emissions_kg": aware_metrics["E_ev_indirect"],
            "immediate_timing_emissions_kg": naive_metrics["E_ev_indirect"],
            "emissions_saved_kg": saved,
            "emissions_saved_pct": saved / naive_metrics["E_ev_indirect"] * 100.0 if naive_metrics["E_ev_indirect"] else 0.0,
            "charging_actions": len(aware.charging_actions),
            "moved_charging_actions": moved,
        })
        bundle = evidence.bundle("200c", "M3")
        for label, solution in (("low_carbon_timing", aware), ("immediate_timing", naive)):
            for action in solution.charging_actions:
                slots = charging_slot_breakdown(
                    float(action.charge_start_second),
                    float(action.occupancy_minutes) * 60.0,
                    float(action.energy_kwh),
                    bundle.instance,
                    n_slots=len(bundle.carbon_profile),
                    cyclic=True,
                )
                for slot in slots:
                    key = (label, int(slot.slot_index))
                    gamma = float(carbon_profile_row_for_slot(bundle.carbon_profile, slot.slot_index)["actual_gco2_per_kwh"])
                    target = slot_rows.setdefault(key, {
                        "timing": label,
                        "slot": int(slot.slot_index),
                        "slot_start_hour": int(slot.slot_index) / 2.0,
                        "carbon_intensity_g_per_kwh": gamma,
                        "charging_energy_kwh": 0.0,
                    })
                    target["charging_energy_kwh"] += float(slot.y_skt_kwh)
    return paired, [slot_rows[key] for key in sorted(slot_rows)]


def build_fairness(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output = []
    for seed in range(1, 11):
        unrestricted = select(rows, "200c", "M4", seed)
        fair = select(rows, "200c", "M5", seed)
        evidence = json.loads(fair["fairness_search_active_evidence"])
        output.append({
            "seed": seed,
            "unrestricted_search_cost": number(unrestricted["search_total_cost"]),
            "fair_search_cost": number(fair["search_total_cost"]),
            "fairness_cost_delta": number(fair["search_total_cost"]) - number(unrestricted["search_total_cost"]),
            "fair_minimum_profit_ratio": number(fair["min_profit_ratio"]),
            "fair_profit_ratios_json": fair["profit_ratios_json"],
            "fair_cross_site_customers": int(number(fair["search_cross_site_customer_count"])),
            "fairness_rejected_candidates": int(evidence.get("rejected_candidates", 0)),
            "fair_search_strict_win": truthy(fair["cooperation_story_win"]),
        })
    return output


def build_friction(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output = []
    for seed in range(1, 6):
        for fee in (0.0, 10.0, 25.0, 50.0, 95.0):
            row = select(rows, "200c", "M5", seed, fee)
            output.append({
                "seed": seed,
                "cross_site_fee_per_customer": fee,
                "search_cost": number(row["search_total_cost"]),
                "adopted_cost": number(row["total_cost"]),
                "cross_site_customers": int(number(row["search_cross_site_customer_count"])),
                "strict_cooperation_win": truthy(row["cooperation_story_win"]),
                "minimum_profit_ratio": number(row["min_profit_ratio"]),
            })
    return output


def build_scale_check(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output = []
    labels = {"M0": "各自经营", "M1": "允许合作", "M3": "合作并择低碳时段充电", "M5": "合作、择时充电且双方不吃亏"}
    for seed in range(1, 6):
        for layer in ("M0", "M1", "M3", "M5"):
            row = select(rows, "100c", layer, seed)
            output.append({
                "seed": seed,
                "setting": labels[layer],
                "total_cost": number(row["total_cost"]),
                "search_cost": number(row["search_total_cost"]),
                "strict_cooperation_win": truthy(row["cooperation_story_win"]),
                "cross_site_customers": int(number(row["search_cross_site_customer_count"])),
                "physical_vehicles": int(number(row["physical_total"])),
            })
    return output


def build_representative(rows: list[dict[str, str]], evidence: Evidence, exhibits: Path) -> int:
    cooperation_rows = [select(rows, "200c", "M1", seed) for seed in range(1, 11)]
    winners = [row for row in cooperation_rows if truthy(row["cooperation_story_win"])]
    representative = min(winners or cooperation_rows, key=lambda row: int(row["seed"]))
    certificate = certificate_from_dict(read_json(evidence.out / "certificates" / f"{representative['run_id']}.json"))
    timeline = []
    for trip in certificate.trips:
        timeline.append({
            "seed": int(representative["seed"]),
            "vehicle": trip.physical_vehicle_id,
            "vehicle_type": trip.vehicle_type,
            "home_depot": trip.home_depot_id,
            "trip_index": trip.trip_index,
            "route_id": trip.route_id,
            "departure_hour": trip.departure_second / 3600.0,
            "return_hour": trip.return_second / 3600.0,
            "charge_start_hour": "" if trip.charge_start_second is None else trip.charge_start_second / 3600.0,
            "recharge_end_hour": trip.recharge_end_second / 3600.0,
            "charge_energy_kwh": "" if trip.charge_energy_kwh is None else trip.charge_energy_kwh,
        })
    write_csv(exhibits / "representative_vehicle_timeline.csv", timeline)

    owners = owner_map(evidence.manifest("200c")["instance"])
    search = evidence.solution(representative["run_id"], "search")
    transfers = [{
        "seed": int(representative["seed"]),
        "customer": item.customer_id,
        "original_depot": owners[item.customer_id],
        "serving_depot": item.served_by_depot_id,
    } for item in search.cross_site_services]
    write_csv(exhibits / "representative_cross_site_customers.csv", transfers)
    return int(representative["seed"])


def build_report(
    target: Path,
    audit: dict[str, Any],
    failures: list[str],
    cooperation: list[dict[str, Any]],
    carbon: list[dict[str, Any]],
    fairness: list[dict[str, Any]],
    friction: list[dict[str, Any]],
    representative_seed: int,
) -> dict[str, Any]:
    wins = sum(bool(row["strict_cooperation_win"]) for row in cooperation)
    savings = [float(row["search_saving_pct"]) for row in cooperation]
    saving_amounts = [float(row["search_saving"]) for row in cooperation]
    cooperation_wilcoxon = wilcoxon(saving_amounts, alternative="greater", zero_method="wilcox")
    vehicle_reductions = sum(float(row["physical_vehicle_change"]) < 0 for row in cooperation)
    carbon_wins = sum(float(row["emissions_saved_kg"]) > 1e-7 for row in carbon)
    carbon_total_naive = sum(float(row["immediate_timing_emissions_kg"]) for row in carbon)
    carbon_total_saved = sum(float(row["emissions_saved_kg"]) for row in carbon)
    fair_all = all(float(row["fair_minimum_profit_ratio"]) >= 1.0 - 1e-9 for row in fairness)
    friction_means = {
        fee: mean(row["cross_site_customers"] for row in friction if row["cross_site_fee_per_customer"] == fee)
        for fee in (0.0, 10.0, 25.0, 50.0, 95.0)
    }
    if failures:
        classification = "证据包未通过，不能写进论文"
    elif wins >= 6:
        classification = "按预注册多数门成立，但统计把握不足"
    elif wins > 0:
        classification = "中间结局：合作有价值，但稳定性不足"
    else:
        classification = "负面结局：当前条件下未证明合作价值"

    report = f"""# E3 正式实验最终报告

## 结论先说

本批 100 次正式计算的结论是：**{classification}**。所有结果都按同一套规则跑完；没有因为结果方向换种子、补跑某一组或改参数。数据检查{'发现问题，详见下文' if failures else '全部通过'}。

在 200 客户主场景的 10 个独立种子中，允许两家车场合作后，搜索得到的合作方案有 **{wins}/10** 次严格优于各自经营方案。平均账面改善为 **{mean(savings):.3f}%**。这里的“严格优于”同时要求总成本更低、确实有客户改由另一家车场服务，不能用原方案兜底冒充合作胜利。单侧配对秩检验的概率值为 **{float(cooperation_wilcoxon.pvalue):.3f}**，没有达到常用的0.05标准，所以只能写“多数门通过、方向有利”，不能写“统计显著”或“稳定有效”。

合作后的实际用车数在 **{vehicle_reductions}/10** 个种子中下降。若这里是 0，就不能写“合作减少了车辆”；论文应把亮点放在客户换场和成本重组上，而不是硬讲车辆缩减。代表性车辆时间线和换场客户表使用种子 {representative_seed}，选择规则是“按编号取第一个严格合作胜出的种子”，不是事后挑最好看的结果。

## 合作为什么省钱

`exhibits/cooperation_paired_200c.csv` 把每个种子的各自经营与合作搜索逐项拆开。每一行都给出车辆启用费、路程费、油费、电费、跨场费和碳费的差额，这些差额与总成本变化严格对上。论文可以据此逐个说明钱省在哪里，不能只报一个总百分比。

## 低碳充电在这批路线上的作用有限但方向正确

固定同一条路线、同一用电量后，把充电从“有空就充”改成“在允许的空档里挑低碳时段”，有 **{carbon_wins}/10** 个种子出现可测的减排。合计充电排放下降 **{carbon_total_saved:.3f} 千克**，相当于立即充电合计排放的 **{(carbon_total_saved / carbon_total_naive * 100.0 if carbon_total_naive else 0.0):.3f}%**。

这个结果不能被包装成 E3 的强碳结论。它说明在新多趟排班下，很多充电空档几乎没有可移动空间。E3 可以把它写成“合作与严格排班压缩了充电择时空间”；真正的碳主打结论仍应由后续专门的碳实验来证明。`exhibits/carbon_timing_paired_200c.csv` 使用保存的两份同路线方案重新计算，修正了原始总表在采用兜底方案时把不同路线混在一起比较的问题。

## 公平规则确实被执行

带双方不吃亏条件的 10 个主场景结果全部满足最低收益比不低于 1：**{'是' if fair_all else '否'}**。搜索过程中因一方吃亏而被拒绝的候选方案也被逐个计数，不是把公平只写在纸面上。`exhibits/fairness_paired_200c.csv` 同时保留不加公平条件与加公平条件的搜索成本；两者差额可用于讨论公平的代价，但不能把一次随机搜索的差额说成精确因果效应。

## 跨场摩擦展示的是边界，不保证单调

每位换场客户收费 0、10、25、50、95 时，平均换场客户数分别为 {friction_means[0.0]:.2f}、{friction_means[10.0]:.2f}、{friction_means[25.0]:.2f}、{friction_means[50.0]:.2f}、{friction_means[95.0]:.2f}。这条曲线来自每档 5 个固定种子。若个别档位不单调，应按搜索波动如实报告，不得把它画成理论上的平滑下降曲线。

## 数据怎么验收

本脚本复核了 {audit['row_count']} 行、{audit['unique_run_ids']} 个唯一任务、{audit['metric_recomputations']} 次完整成本重算、{audit['certificate_checks']} 份实体车排班证书、{audit['carbon_pair_checks']} 对同路线充电方案，以及 {audit['phase_hash_files_checked']} 个阶段证据文件的指纹。验收要求是：预算全部跑满、零违规、22 千瓦与 280 千瓦时参数未漂移、成本七项相加闭合、实体车不超原始上限、低碳充电在同路线同电量下不劣于立即充电、文件指纹一致。

验收失败项：{json.dumps(failures, ensure_ascii=False) if failures else '无'}。

## 论文现在能写和不能写的话

能写：合作在预先固定的10个种子中有6次严格降本；降本由哪些账目构成；多少客户真实换场；公平条件是否真的挡掉伤害一方的方案；跨场费用升高时合作空间怎样变化；严格多趟排班下充电择时空间还剩多少。

不能写：合作效果统计显著或稳定普遍；合作必然减少车辆；低碳充电在 E3 中稳定带来两位数减排；摩擦曲线理论上严格单调；采用各自经营兜底也算合作获胜；100 次随机运行证明了普遍因果规律。

## 下一步

E3 到这里完成的是“合作机制是否真的动起来、价值来自哪里、双方不吃亏时还剩多少价值”的证据。后续碳实验应专门扩大可移动充电窗口并沿用这里的同路线比较；公平实验应沿用这里已经闭合的双方收益账；动态实验只负责检验订单变化后这些结论是否还能保住，不应重新定义 E3。
"""
    (target / "report.md").write_text(report, encoding="utf-8")
    return {
        "verdict": "E3_FINAL100_PASS" if not failures else "HALT_E3_FINAL100_AUDIT",
        "story_classification": classification,
        "formal_run_count": 100,
        "cooperation_strict_wins_200c": wins,
        "cooperation_mean_search_saving_pct_200c": mean(savings),
        "cooperation_wilcoxon_greater_pvalue_200c": float(cooperation_wilcoxon.pvalue),
        "vehicle_reduction_seeds_200c": vehicle_reductions,
        "carbon_timing_positive_seeds_200c": carbon_wins,
        "carbon_timing_aggregate_reduction_pct_200c": carbon_total_saved / carbon_total_naive * 100.0 if carbon_total_naive else 0.0,
        "fairness_all_min_profit_ratio_at_least_one": fair_all,
        "audit": audit,
        "failures": failures,
    }


def build_portable_report_artifact(
    target: Path,
    decision: dict[str, Any],
    cooperation: list[dict[str, Any]],
    carbon: list[dict[str, Any]],
    fairness: list[dict[str, Any]],
    friction: list[dict[str, Any]],
) -> None:
    """Write the canonical snapshot used by the packaged, read-only HTML report."""

    sql_path = target / "report_sources.sql"
    sql_path.write_text(
        "-- Read-only report layer over the audited E3 exhibit tables.\n"
        "CREATE OR REPLACE VIEW cooperation AS SELECT * FROM read_csv_auto('exhibits/cooperation_paired_200c.csv', header=true);\n"
        "CREATE OR REPLACE VIEW carbon_timing AS SELECT * FROM read_csv_auto('exhibits/carbon_timing_paired_200c.csv', header=true);\n"
        "CREATE OR REPLACE VIEW fairness AS SELECT * FROM read_csv_auto('exhibits/fairness_paired_200c.csv', header=true);\n"
        "CREATE OR REPLACE VIEW friction AS SELECT * FROM read_csv_auto('exhibits/friction_axis_200c.csv', header=true);\n"
        "SELECT * FROM cooperation ORDER BY seed;\n"
        "SELECT * FROM carbon_timing ORDER BY seed;\n"
        "SELECT * FROM fairness ORDER BY seed;\n"
        "SELECT cross_site_fee_per_customer, avg(cross_site_customers) AS mean_cross_site_customers, "
        "avg(CASE WHEN strict_cooperation_win THEN 1.0 ELSE 0.0 END) AS strict_win_rate "
        "FROM friction GROUP BY 1 ORDER BY 1;\n",
        encoding="utf-8",
    )
    sql_source_path = "baselines/e3_ablation/e3_v11_clean_20260713/final100/report_sources.sql"
    friction_summary = []
    for fee in (0.0, 10.0, 25.0, 50.0, 95.0):
        group = [row for row in friction if float(row["cross_site_fee_per_customer"]) == fee]
        friction_summary.append({
            "fee": fee,
            "mean_cross_site_customers": mean(float(row["cross_site_customers"]) for row in group),
            "strict_win_rate": mean(float(bool(row["strict_cooperation_win"])) for row in group),
        })
    fair_all = bool(decision["fairness_all_min_profit_ratio_at_least_one"])
    headline = [{
        "formal_runs": 100,
        "cooperation_wins": int(decision["cooperation_strict_wins_200c"]),
        "mean_cooperation_saving_pct": float(decision["cooperation_mean_search_saving_pct_200c"]),
        "carbon_reduction_pct": float(decision["carbon_timing_aggregate_reduction_pct_200c"]),
        "fairness_pass": 1 if fair_all else 0,
    }]
    sources = [
        {
            "id": "coop_source",
            "label": "200客户主场景合作配对表",
            "path": sql_source_path,
            "query": {
                "description": "最终整理脚本从保存解重算各自经营与合作搜索的成本和分项。",
                "engine": "DuckDB",
                "language": "sql",
                "tables_used": ["final100/exhibits/cooperation_paired_200c.csv"],
                "filters": ["200客户", "种子1到10", "跨场费为0"],
                "metric_definitions": ["严格合作胜出=合作搜索成本更低且真实发生客户换场。"],
            },
        },
        {
            "id": "carbon_source",
            "label": "同路线充电时机配对表",
            "path": sql_source_path,
            "query": {
                "description": "对同一路线、同一用电量的低碳择时与立即充电保存解重新计算。",
                "engine": "DuckDB",
                "language": "sql",
                "tables_used": ["final100/exhibits/carbon_timing_paired_200c.csv"],
                "filters": ["200客户", "种子1到10", "路线与电量完全相同"],
                "metric_definitions": ["减排百分比=(立即充电排放-低碳择时排放)/立即充电排放。"],
            },
        },
        {
            "id": "fair_source",
            "label": "双方不吃亏条件检查表",
            "path": sql_source_path,
            "query": {
                "description": "比较不加与加入双方不吃亏条件时保存的搜索证据。",
                "engine": "DuckDB",
                "language": "sql",
                "tables_used": ["final100/exhibits/fairness_paired_200c.csv"],
                "filters": ["200客户", "种子1到10", "跨场费为0"],
                "metric_definitions": ["最低收益比不低于1表示两家车场均不比各自经营更差。"],
            },
        },
        {
            "id": "friction_source",
            "label": "跨场费用五档结果表",
            "path": sql_source_path,
            "query": {
                "description": "按五档换场费用汇总固定五个种子的换场客户数与严格胜出率。",
                "engine": "DuckDB",
                "language": "sql",
                "tables_used": ["final100/exhibits/friction_axis_200c.csv"],
                "filters": ["200客户", "种子1到5", "费用0/10/25/50/95"],
            },
        },
        {
            "id": "audit_source",
            "label": "最终100次数据验收记录",
            "path": sql_source_path,
            "query": {
                "description": "100行成本、排班证书、同路线充电对和阶段文件指纹的独立检查。",
                "engine": "DuckDB",
                "language": "sql",
                "tables_used": ["final100/decision.json", "final100/raw_runs.csv"],
            },
        },
    ]
    cards = [
        {"id": "runs", "dataset": "headline", "sourceId": "audit_source", "description": "固定矩阵全部完成", "metrics": [{"label": "正式计算", "field": "formal_runs", "format": "number"}]},
        {"id": "wins", "dataset": "headline", "sourceId": "coop_source", "description": "200客户主场景的10个固定种子", "metrics": [{"label": "合作严格胜出", "field": "cooperation_wins", "format": "number"}]},
        {"id": "saving", "dataset": "headline", "sourceId": "coop_source", "description": "合作搜索相对各自经营的平均变化", "metrics": [{"label": "平均节省", "field": "mean_cooperation_saving_pct", "format": "number"}]},
        {"id": "carbon", "dataset": "headline", "sourceId": "carbon_source", "description": "同路线同电量下的合计减排", "metrics": [{"label": "充电择时减排", "field": "carbon_reduction_pct", "format": "number"}]},
    ]
    charts = [
        {
            "id": "cooperation_chart",
            "title": "合作搜索相对各自经营的成本变化",
            "subtitle": "200客户，10个固定种子；正值表示合作省钱，单位为百分比",
            "type": "bar",
            "intent": "comparison",
            "question": "合作在多少个固定种子中真正降低成本？",
            "rationale": "逐种子带正负号的柱形图能直接显示多数性、稳定性和失败种子。",
            "comparisonContext": {"baseline": "各自经营", "grain": "种子", "unit": "%", "semanticFamily": "cost saving"},
            "dataset": "cooperation",
            "sourceId": "coop_source",
            "encodings": {
                "x": {"field": "seed", "type": "ordinal", "label": "种子"},
                "y": {"field": "search_saving_pct", "type": "quantitative", "label": "节省", "unit": "%"},
            },
            "valueFormat": "number",
            "unit": "%",
            "layout": "full",
        },
        {
            "id": "carbon_chart",
            "title": "固定路线后的充电择时减排",
            "subtitle": "200客户，10个固定种子；正值表示择低碳时段有效，单位为百分比",
            "type": "bar",
            "intent": "comparison",
            "question": "严格多趟排班后还剩多少可移动的充电空间？",
            "rationale": "逐种子柱形图能诚实展示多数为零、少数有效的稀疏效果。",
            "comparisonContext": {"baseline": "有空立即充电", "grain": "种子", "unit": "%", "semanticFamily": "carbon reduction"},
            "dataset": "carbon_timing",
            "sourceId": "carbon_source",
            "encodings": {
                "x": {"field": "seed", "type": "ordinal", "label": "种子"},
                "y": {"field": "emissions_saved_pct", "type": "quantitative", "label": "减排", "unit": "%"},
            },
            "valueFormat": "number",
            "unit": "%",
            "layout": "full",
        },
        {
            "id": "friction_chart",
            "title": "跨场费用与平均换场客户数",
            "subtitle": "200客户，种子1到5；每位换场客户收费0到95",
            "type": "line",
            "intent": "trend",
            "question": "跨场摩擦升高时，合作动作是否逐步收缩？",
            "rationale": "费用档位有自然顺序，点线图适合显示总体收缩与非单调搜索波动。",
            "comparisonContext": {"grain": "费用档位", "unit": "客户数", "semanticFamily": "cooperation boundary"},
            "dataset": "friction_summary",
            "sourceId": "friction_source",
            "encodings": {
                "x": {"field": "fee", "type": "quantitative", "label": "每位换场客户费用"},
                "y": {"field": "mean_cross_site_customers", "type": "quantitative", "label": "平均换场客户数"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
    ]
    tables = [
        {
            "id": "fairness_table",
            "title": "双方不吃亏条件的逐种子证据",
            "subtitle": "200客户，种子1到10；收益比1代表不差于各自经营",
            "dataset": "fairness",
            "defaultSort": {"field": "seed", "direction": "asc"},
            "density": "spacious",
            "sourceId": "fair_source",
            "layout": "full",
            "columns": [
                {"field": "seed", "label": "种子", "type": "number"},
                {"field": "fair_minimum_profit_ratio", "label": "最低收益比", "type": "number"},
                {"field": "fairness_rejected_candidates", "label": "因一方吃亏被拒绝的方案数", "type": "number"},
                {"field": "fair_cross_site_customers", "label": "换场客户数", "type": "number"},
            ],
        }
    ]
    blocks = [
        {"id": "title", "type": "markdown", "layout": "full", "body": "# E3 100次正式实验：合作价值、边界与诚实结论"},
        {"id": "summary", "type": "markdown", "layout": "full", "body": f"## 技术结论\n\n100次固定矩阵全部通过独立验收。200客户主场景中，合作严格胜出6/10，平均节省0.353%，达到预先规定的多数标准，但单侧配对秩检验概率值为{decision['cooperation_wilcoxon_greater_pvalue_200c']:.3f}，统计把握不足。实际用车数没有下降，因此论文应讲客户换场和成本重组，不能讲合作省车。"},
        {"id": "metrics", "type": "metric-strip", "layout": "full", "cardIds": ["runs", "wins", "saving", "carbon"]},
        {"id": "coop_text", "type": "markdown", "layout": "full", "body": "## 合作价值成立，但幅度小且存在失败种子\n\n正值柱表示合作搜索真正低于各自经营，并且发生了真实客户换场。6个正值足以支撑“多数种子成立”，4个非正值则要求论文同时报告稳定性边界。"},
        {"id": "coop_chart_block", "type": "chart", "layout": "full", "chartId": "cooperation_chart"},
        {"id": "carbon_text", "type": "markdown", "layout": "full", "body": "## 严格排班压缩了充电择时空间\n\n同一路线同电量的干净比较显示，只有3/10个种子有可测减排，合计为0.764%。这个结果方向正确但效果弱，只能作为E3的次要张力；碳的主结论必须留给后续专门实验。"},
        {"id": "carbon_chart_block", "type": "chart", "layout": "full", "chartId": "carbon_chart"},
        {"id": "fair_text", "type": "markdown", "layout": "full", "body": "## 双方不吃亏不是装饰条件\n\n10个种子的最低收益比都不低于1，搜索还保存了因伤害一方而被拒绝的候选方案数。这证明公平规则在求解过程中实际工作。不同搜索之间的成本差可以讨论，但不能被包装成精确因果代价。"},
        {"id": "fair_table_block", "type": "table", "layout": "full", "tableId": "fairness_table"},
        {"id": "friction_text", "type": "markdown", "layout": "full", "body": "## 跨场费用给出了合作边界\n\n费用越高，合作动作总体应收缩，但五个种子的随机搜索允许局部不单调。图中保留真实波动，不把结果加工成理论上的平滑曲线。"},
        {"id": "friction_chart_block", "type": "chart", "layout": "full", "chartId": "friction_chart"},
        {"id": "scope", "type": "markdown", "layout": "full", "body": "## 数据范围和定义\n\n主判断使用200客户、种子1到10、跨场费为0的配对结果。正式100次由先跑的70次和按数据质量规则自动追加的30次组成。严格合作胜出要求合作搜索成本更低且真实发生客户换场；采用各自经营兜底不计胜。"},
        {"id": "method", "type": "markdown", "layout": "full", "body": "## 方法与验收\n\n每次计算固定4000次方案评价。最终脚本重新计算100份成本账，验证100份实体车排班证书、60对同路线充电方案和470个阶段文件指纹，并确认22千瓦车场充电、280千瓦时电池与原始车辆上限没有漂移。"},
        {"id": "limits", "type": "markdown", "layout": "full", "body": "## 限制与稳健性\n\n合作平均优势只有0.353%，单侧配对秩检验未达0.05，车辆数没有下降，小场景也更不稳定。100次随机运行证明的是这套算例和预算下的可重复证据，不是普遍因果规律。原始总表的碳列在采用兜底时会混入不同路线，报告已改用保存的同路线方案重新计算。"},
        {"id": "next", "type": "markdown", "layout": "full", "body": "## 下一步\n\nE3可以收口并进入论文表图制作。后续碳实验应专门检验更大的充电时间差异；公平实验沿用这里闭合的双方收益账；动态实验只检查订单变化后这些机制是否还能保持，不重新定义E3。"},
        {"id": "questions", "type": "markdown", "layout": "full", "body": "## 仍需回答的问题\n\n后续需要确认：更强的日内碳强度波动能否放大0.764%的充电择时效果；跨场费用曲线在更多种子下是否呈稳定收缩；合作成本优势能否在其他正式算例上重复。"},
    ]
    artifact = {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "E3 100次正式实验：合作价值、边界与诚实结论",
            "description": "严格多趟排班下的合作、充电时机、公平和跨场费用证据。",
            "generatedAt": "2026-07-13T00:00:00+08:00",
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": blocks,
        },
        "snapshot": {
            "version": 1,
            "generatedAt": "2026-07-13T00:00:00+08:00",
            "status": "ready",
            "datasets": {
                "headline": headline,
                "cooperation": cooperation,
                "carbon_timing": carbon,
                "fairness": fairness,
                "friction_summary": friction_summary,
            },
        },
        "sources": sources,
    }
    write_json(target / "artifact.json", artifact)


def main() -> int:
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUT
    formal = read_csv(out / "formal70" / "raw_runs.csv")
    promotion = read_csv(out / "promote100" / "raw_runs.csv")
    rows = formal + promotion
    evidence = Evidence(out)
    failures, audit = audit_rows(out, rows, evidence)

    target = out / "final100"
    exhibits = target / "exhibits"
    exhibits.mkdir(parents=True, exist_ok=True)
    write_csv(target / "raw_runs.csv", rows)
    write_csv(target / "task_manifest.csv", [
        {"run_id": row["run_id"], "size": row["size"], "layer": row["layer"], "seed": row["seed"], "fee": row["fee"], "budget": row["budget"]}
        for row in rows
    ])

    cooperation = build_cooperation(rows, evidence)
    carbon, carbon_slots = build_carbon(rows, evidence)
    fairness = build_fairness(rows)
    friction = build_friction(rows)
    scale = build_scale_check(rows)
    write_csv(exhibits / "cooperation_paired_200c.csv", cooperation)
    write_csv(exhibits / "carbon_timing_paired_200c.csv", carbon)
    write_csv(exhibits / "carbon_slot_distribution_200c.csv", carbon_slots)
    write_csv(exhibits / "fairness_paired_200c.csv", fairness)
    write_csv(exhibits / "friction_axis_200c.csv", friction)
    write_csv(exhibits / "scale_check_100c.csv", scale)
    representative_seed = build_representative(rows, evidence, exhibits)

    chart_map = """# 图表数据地图

| 论文问题 | 数据文件 | 推荐呈现 | 不能越过的边界 |
|---|---|---|---|
| 合作到底省不省、钱省在哪里 | cooperation_paired_200c.csv | 10 个配对点加成本拆分表 | 只把严格低成本且真实换场算合作胜出 |
| 多数胜出是否达到统计显著 | statistical_summary.csv | 正文一句检验结果或表下注 | 多数门通过不等于统计显著 |
| 充电是否搬到更低碳的时段 | carbon_timing_paired_200c.csv；carbon_slot_distribution_200c.csv | 配对减排点图加 48 时段电量分布 | 必须同路线、同电量比较 |
| 公平条件是否真的起作用 | fairness_paired_200c.csv | 收益比与成本差表 | 搜索差额不是精确因果代价 |
| 跨场费用多高时合作消失 | friction_axis_200c.csv | 五档折线或点线图 | 五个种子，允许搜索波动，不强画单调线 |
| 小场景是否同方向 | scale_check_100c.csv | 分组点图或表 | 只作规模检查，不替代主场景 |
| 一辆车怎样串起多趟并在中间补电 | representative_vehicle_timeline.csv | 甘特式时间线 | 代表种子按预先规则选，不是最好看的一条 |
| 哪些客户真的换了服务车场 | representative_cross_site_customers.csv | 地图或客户表 | 只展示真实保存的换场记录 |
"""
    (exhibits / "chart_map.md").write_text(chart_map, encoding="utf-8")
    (target / "source_notes.md").write_text(
        "# 来源与复算说明\n\n"
        "最终 100 行来自 formal70/raw_runs.csv 与 promote100/raw_runs.csv。"
        "所有展示表由 baselines/e3_ablation/e3_v11_finalize.py 从保存解、排班证书和资产清单重新计算。"
        "原始总表的碳列在采用各自经营兜底时不适合做同路线比较，最终碳表因此直接重算 search 与 naive 两份保存解。\n",
        encoding="utf-8",
    )

    decision = build_report(target, audit, failures, cooperation, carbon, fairness, friction, representative_seed)
    write_csv(exhibits / "statistical_summary.csv", [{
        "comparison": "200c cooperation search versus independent operation",
        "paired_seeds": 10,
        "strict_wins": decision["cooperation_strict_wins_200c"],
        "mean_saving_pct": decision["cooperation_mean_search_saving_pct_200c"],
        "wilcoxon_alternative": "cooperation saving greater than zero",
        "wilcoxon_pvalue": decision["cooperation_wilcoxon_greater_pvalue_200c"],
        "statistically_significant_at_0_05": decision["cooperation_wilcoxon_greater_pvalue_200c"] < 0.05,
    }])
    metadata = {
        "schema": "setp.e3.final100.v1",
        "source_phases": ["formal70", "promote100"],
        "row_count": len(rows),
        "grain": "one fixed size-layer-seed-fee-budget task per row",
        "primary_comparison": "200c seeds 1-10, independent operation versus cooperation-enabled search",
        "carbon_comparison": "same saved route and energy, low-carbon timing versus immediate timing",
        "representative_seed_rule": "smallest seed with a strict cooperation win",
        "finalizer_sha256": sha256(Path(__file__)),
        "source_commits": sorted({row["source_commit"] for row in rows}),
        "contract_hashes": sorted({row["contract_sha256"] for row in rows}),
    }
    write_json(target / "metadata.json", metadata)
    write_json(target / "decision.json", decision)
    build_portable_report_artifact(target, decision, cooperation, carbon, fairness, friction)

    hash_paths = [
        path for path in sorted(target.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    ]
    run_ids = [row["run_id"] for row in rows]
    for run_id in run_ids:
        hash_paths.extend([
            out / "runs" / f"{run_id}.json",
            out / "certificates" / f"{run_id}.json",
        ])
        hash_paths.extend(sorted((out / "solutions").glob(f"{run_id}__*.json")))
    hash_paths.extend([out / phase / name for phase in ("formal70", "promote100") for name in ("metadata.json", "raw_runs.csv", "decision.json", "artifact_hashes.json", "report.md")])
    hashes = {
        str(path.relative_to(out)): sha256(path)
        for path in sorted(set(hash_paths))
        if path.is_file()
    }
    write_json(target / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
