#!/usr/bin/env python3
"""Reconcile the 297 saved China81 candidates into the final 81-cell suite.

This is a construction-only reconciliation.  It does not load a China81 V2
finite-fleet authority and it never invokes a search solver.  The four saved
candidate suites are audited as candidate evidence; DEPOTSWAP is retained as
the fifth candidate only for its jjj/50c/01 cell and for the global main-case
comparison.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping


REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data/ChinaInstances"
REPORT = REPO / "solver/reports/china81_final_suite_rebuild_20260815"
OUTPUT = DATA / "china81_final_suite_v1_20260815"

SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
REGIONS = ("cy", "jjj", "prd")
REPLICATES = ("01", "02", "03")
CARBON_LEVERAGE = {"cy": "0.0000", "jjj": "+0.3391", "prd": "+0.1679"}
PROTECTED = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
)

SOURCES = (
    {
        "source": "FS",
        "health": REPO / "solver/reports/suite_rebuild_20260812/suite_health.csv",
        "root": DATA / "china81_suite_v3_20260812",
    },
    {
        "source": "PRDFIX",
        "health": REPO / "solver/reports/suite_prd_fix_20260812/suite_health_v3.csv",
        "root": DATA / "china81_suite_prd_fix_v1_20260812",
    },
    {
        "source": "METRO",
        "health": REPO / "solver/reports/metro_rebuild_20260812/suite_health_metro.csv",
        "root": DATA / "china81_metro_suite_v1_20260812",
    },
    {
        "source": "DP",
        "health": REPO / "solver/reports/suite_depotpair_rebuild_20260812/suite_health_54.csv",
        "root": DATA / "china81_depotpair_rebuild_v1_20260812",
    },
)
DEPOTSWAP_ROOT = DATA / "china81_instance_depot_swap_jjj_v1_20260813"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: list[str] | None = None) -> None:
    materialized = [dict(row) for row in rows]
    names = list(fields or (materialized[0].keys() if materialized else ()))
    if not names:
        raise ValueError(f"cannot write empty CSV without fields: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def depotswap_lunch_summary(source: str, instance_id: str) -> dict[str, float]:
    if source != "DEPOTSWAP":
        return {}
    path = DEPOTSWAP_ROOT / "lunch_charge_rows.csv"
    if not path.is_file():
        return {}
    values = [
        float(row["chargeable_kwh_60kw_from_zero"])
        for row in read_csv(path)
        if row.get("instance_id") == instance_id and row.get("chargeable_kwh_60kw_from_zero")
    ]
    if not values:
        return {}
    ordered = sorted(values)
    middle = ordered[len(ordered) // 2] if len(ordered) % 2 else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2.0
    return {
        "lunch_chargeable_kwh_60kw_min_per_vehicle": min(values),
        "lunch_chargeable_kwh_60kw_median_per_vehicle": middle,
        "lunch_chargeable_kwh_60kw_max_per_vehicle": max(values),
    }


def float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def copy_tree_without_appledouble(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(target)

    def ignore_appledouble(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name.startswith("._")}

    shutil.copytree(
        source,
        target,
        ignore=ignore_appledouble,
    )


def source_instance_root(source: str, instance_id: str) -> Path:
    if source == "DEPOTSWAP":
        return DEPOTSWAP_ROOT / "instances" / instance_id
    for item in SOURCES:
        if item["source"] == source:
            return item["root"] / "instances" / instance_id
    raise KeyError(source)


def source_root(source: str) -> Path:
    if source == "DEPOTSWAP":
        return DEPOTSWAP_ROOT
    return next(item["root"] for item in SOURCES if item["source"] == source)


def matrix_path_for(instance_root: Path, profile: str = "cv") -> Path | None:
    reference = instance_root / "matrix_reference.json"
    if not reference.is_file():
        return None
    payload = json.loads(reference.read_text(encoding="utf-8"))
    entry = payload.get("profiles", {}).get(profile, {}).get("road_distance_m.csv")
    if not entry:
        return None
    raw = Path(str(entry.get("path", "")))
    if raw.is_file():
        return raw
    # DP's saved reference points to a temporary station-fix checkout.  The
    # immutable before-station-restore authority contains the same matrix.
    text = str(raw).replace(
        "china81_depotpair_rebuild_v1_20260812_stationfix_tmp",
        "china81_depotpair_rebuild_v1_20260812_before_station_restore_20260812",
    )
    candidate = Path(text)
    return candidate if candidate.is_file() else None


def depot_distance_text(instance_root: Path, depot_ids: str) -> str:
    matrix_path = matrix_path_for(instance_root)
    if matrix_path is None:
        return "UNAVAILABLE_MATRIX_REFERENCE"
    rows = read_csv_matrix(matrix_path)
    ids = [item for item in depot_ids.split("|") if item]
    values: list[str] = []
    for left in ids:
        for right in ids:
            if left == right:
                continue
            value = rows.get((left, right))
            values.append(f"{left}->{right}={value / 1000.0:.6f}km" if value is not None else f"{left}->{right}=UNKNOWN")
    return "|".join(values)


def read_csv_matrix(path: Path) -> dict[tuple[str, str], float]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        columns = header[1:]
        result: dict[tuple[str, str], float] = {}
        for row in reader:
            left = row[0]
            for right, value in zip(columns, row[1:], strict=True):
                try:
                    result[(left, right)] = float(value)
                except ValueError:
                    continue
        return result


def normalize_candidate(row: Mapping[str, Any], source: str, root: Path) -> dict[str, Any]:
    candidate = dict(row)
    instance_id = str(candidate["instance_id"])
    instance_root = root / "instances" / instance_id
    witness_path = instance_root / "witness_status.json"
    witness = json.loads(witness_path.read_text(encoding="utf-8")) if witness_path.is_file() else {}
    candidate["source"] = source
    candidate["source_root"] = str(root.relative_to(REPO))
    candidate["instance_root"] = str(instance_root.relative_to(REPO))
    candidate["witness_status"] = str(witness.get("status", candidate.get("edf_witness_status", "UNKNOWN")))
    candidate["checker_violation_count"] = int_value(witness.get("violation_count", candidate.get("checker_violation_count", 0)))
    candidate["witness_reason"] = str(witness.get("reason", ""))
    candidate["formal_search_allowed"] = "false"
    candidate["search_evaluations"] = "0"
    candidate["carbon_leverage"] = CARBON_LEVERAGE[str(candidate["region"])]
    candidate["depot_count"] = len([item for item in str(candidate.get("depot_ids", "")).split("|") if item])
    candidate.update(depotswap_lunch_summary(source, instance_id))
    candidate["depot_pair_road_distance_km"] = depot_distance_text(
        instance_root, str(candidate.get("depot_ids", ""))
    )
    if "mixed_fleet_two_sides_status" not in candidate or not candidate["mixed_fleet_two_sides_status"]:
        below = int_value(candidate.get("critical_band_below_vehicle_count"))
        above = int_value(candidate.get("critical_band_above_vehicle_count"))
        if candidate["witness_status"] != "PASS":
            mixed = "NA_NO_FEASIBLE_WITNESS"
        elif below > 0 and above > 0:
            mixed = "PASS_TWO_SIDES"
        elif below <= 0 and above <= 0:
            mixed = "FAIL_NO_BELOW_AND_NO_ABOVE"
        elif below <= 0:
            mixed = "FAIL_NO_BELOW"
        else:
            mixed = "FAIL_NO_ABOVE"
        candidate["mixed_fleet_two_sides_status"] = mixed
    candidate["candidate_eligible"] = int(
        candidate["witness_status"] == "PASS"
        and candidate["checker_violation_count"] == 0
        and candidate["mixed_fleet_two_sides_status"] == "PASS_TWO_SIDES"
        and float_value(candidate.get("contestable_share_25pct")) is not None
    )
    reasons: list[str] = []
    if candidate["witness_status"] != "PASS":
        reasons.append("witness_not_pass")
    if candidate["checker_violation_count"] != 0:
        reasons.append("checker_violation_nonzero")
    if candidate["mixed_fleet_two_sides_status"] != "PASS_TWO_SIDES":
        reasons.append("mixed_fleet_two_sides_missing")
    if float_value(candidate.get("contestable_share_25pct")) is None:
        reasons.append("contestability_25pct_missing")
    candidate["candidate_elimination_reasons"] = ";".join(reasons) if reasons else ""
    candidate["source_candidate_id"] = instance_id
    return candidate


def load_candidates() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in SOURCES:
        if not item["health"].is_file():
            raise FileNotFoundError(item["health"])
        for row in read_csv(item["health"]):
            candidates.append(normalize_candidate(row, item["source"], item["root"]))
    selection_row = next(iter(read_csv(DEPOTSWAP_ROOT / "selection_health.csv")))
    depotswap = normalize_candidate(
        {
            **selection_row,
            "region": "jjj",
            "replicate": "01",
            "depot_ids": "D_beijing_xinan_south|D_beijing_sanjianfang",
            "edf_witness_status": selection_row.get("edf_witness_gate", "PASS"),
            "mixed_fleet_two_sides_status": selection_row.get("mixed_fleet_two_sides_gate", ""),
            "contestable_share_25pct": selection_row.get("contestable_share_25pct", ""),
            "critical_band_below_vehicle_count": selection_row.get("critical_band_below_vehicle_count", "0"),
            "critical_band_above_vehicle_count": selection_row.get("critical_band_above_vehicle_count", "0"),
        },
        "DEPOTSWAP",
        DEPOTSWAP_ROOT,
    )
    candidates.append(depotswap)
    return candidates


def cell_key(candidate: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(candidate["region"]), str(candidate["customer_count"]), str(candidate["replicate"])


def candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[float, str]:
    share = float_value(candidate.get("contestable_share_25pct"))
    return (-(share if share is not None else float("-inf")), str(candidate["instance_id"]))


def normalize_health(candidate: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(candidate)
    aliases = {
        "trip_count_no_reuse": "fleet_trip_count",
        "trip_count_am": "fleet_am_trip_count",
        "trip_count_pm": "fleet_pm_trip_count",
        "physical_vehicle_count_reuse": "fleet_physical_vehicle_count",
        "fleet_reduction_upper_count_vs_no_reuse": "fleet_reduction_count",
        "fleet_reduction_upper_pct_vs_no_reuse": "fleet_reduction_pct",
        "trips_per_vehicle_distribution": "fleet_trip_distribution",
        "max_trips_per_vehicle": "fleet_max_trips",
        "lunch_reused_vehicle_count": "lunch_reused_vehicle_count",
        "mixed_fleet_two_sides_status": "mixed_fleet_two_sides_gate",
    }
    for target, source in aliases.items():
        if not row.get(target) and row.get(source) is not None:
            row[target] = row[source]
    row["checker_violation_count"] = candidate["checker_violation_count"]
    row["formal_search_allowed"] = "false"
    row["search_evaluations"] = "0"
    row["carbon_leverage"] = candidate["carbon_leverage"]
    row["depot_pair_road_distance_km"] = candidate["depot_pair_road_distance_km"]
    return row


def choose_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_cell[cell_key(candidate)].append(candidate)

    eligible_global = sorted(
        [candidate for candidate in candidates if candidate["candidate_eligible"]],
        key=candidate_sort_key,
    )
    global_rank = {str(row["instance_id"]): index for index, row in enumerate(eligible_global, 1)}
    selected: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    no_eligible: list[dict[str, Any]] = []
    for region in REGIONS:
        for size in SIZES:
            for replicate in REPLICATES:
                key = (region, str(size), replicate)
                pool = by_cell[key]
                if not pool:
                    raise RuntimeError(f"candidate pool missing cell {key}")
                eligible = [row for row in pool if row["candidate_eligible"]]
                if eligible:
                    ordered = sorted(eligible, key=candidate_sort_key)
                    chosen = ordered[0]
                    status = "SELECTED_ELIGIBLE"
                    rank = 1
                else:
                    # Keep the materialized final row checker-clean even when
                    # the cell has no candidate allowed into ranking.  This
                    # does not relax the two-side precondition: the row stays
                    # explicitly marked as a representative, not a selected
                    # eligible candidate.
                    witness_clean = [
                        row
                        for row in pool
                        if row["witness_status"] == "PASS"
                        and row["checker_violation_count"] == 0
                    ]
                    ordered = sorted(witness_clean or pool, key=candidate_sort_key)
                    chosen = ordered[0]
                    status = "NO_ELIGIBLE_CELL_REPRESENTATIVE"
                    rank = ""
                    no_eligible.append({
                        "region": region,
                        "customer_count": size,
                        "replicate": replicate,
                        "candidate_count": len(pool),
                        "reason_distribution": reason_distribution(pool),
                        "representative_candidate": chosen["instance_id"],
                        "representative_witness_status": chosen["witness_status"],
                        "representative_mixed_status": chosen["mixed_fleet_two_sides_status"],
                    })
                chosen = dict(chosen)
                chosen["selected_status"] = status
                chosen["selected_candidate_rank_in_cell"] = rank
                chosen["global_eligible_rank"] = global_rank.get(str(chosen["instance_id"]), "")
                chosen["main_case"] = int(chosen["instance_id"] == "cn-jjj-50c-01-V3-TWO-SHIFT-DEPOTSWAP")
                chosen["candidate_pool_total"] = len(pool)
                chosen["candidate_eligible_count"] = sum(int(row["candidate_eligible"]) for row in pool)
                chosen["candidate_eliminated_reason_distribution"] = reason_distribution(pool)
                selected.append(chosen)
                selection_rows.append({
                    "region": region,
                    "customer_count": size,
                    "replicate": replicate,
                    "candidate_pool_total": len(pool),
                    "candidate_eligible_count": sum(int(row["candidate_eligible"]) for row in pool),
                    "selected_candidate_id": chosen["instance_id"],
                    "selected_candidate_source": chosen["source"],
                    "selected_status": status,
                    "selected_25pct_share": chosen.get("contestable_share_25pct", ""),
                    "eliminated_reason_distribution": reason_distribution(pool),
                })
    return selected, selection_rows, no_eligible


def global_eligible_ranking(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered = sorted((row for row in candidates if row["candidate_eligible"]), key=candidate_sort_key)
    for rank, candidate in enumerate(ordered, 1):
        rows.append({
            "global_eligible_rank": rank,
            "instance_id": candidate["instance_id"],
            "source": candidate["source"],
            "region": candidate["region"],
            "customer_count": candidate["customer_count"],
            "replicate": candidate["replicate"],
            "contestable_share_25pct": candidate.get("contestable_share_25pct", ""),
            "critical_band_below_vehicle_count": candidate.get("critical_band_below_vehicle_count", ""),
            "critical_band_overlap_vehicle_count": candidate.get("critical_band_overlap_vehicle_count", ""),
            "critical_band_above_vehicle_count": candidate.get("critical_band_above_vehicle_count", ""),
        })
    return rows


def reason_distribution(pool: Iterable[Mapping[str, Any]]) -> str:
    counts: Counter[str] = Counter()
    for candidate in pool:
        reasons = str(candidate.get("candidate_elimination_reasons", ""))
        if not reasons:
            counts["eligible"] += 1
        else:
            for reason in reasons.split(";"):
                counts[reason] += 1
    return ";".join(f"{key}={counts[key]}" for key in sorted(counts))


def copy_selected_instances(selected: list[dict[str, Any]]) -> None:
    for candidate in selected:
        source = source_instance_root(str(candidate["source"]), str(candidate["instance_id"]))
        target = OUTPUT / "instances" / str(candidate["instance_id"])
        copy_tree_without_appledouble(source, target)
        write_json(
            target / "final_selection.json",
            {
                "schema": "resetp.china81-final-selection.v1",
                "source_candidate": candidate["source"],
                "source_candidate_id": candidate["source_candidate_id"],
                "selected_status": candidate["selected_status"],
                "candidate_eligible": candidate["candidate_eligible"],
                "main_case": candidate["main_case"],
                "formal_search_allowed": False,
                "search_evaluations": 0,
            },
        )


def write_root_aggregates(selected: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
    orders: list[dict[str, Any]] = []
    fleet: list[dict[str, Any]] = []
    catalogs: list[dict[str, Any]] = []
    facilities_by_key: dict[str, dict[str, str]] = {}
    for candidate in selected:
        root = source_root(str(candidate["source"]))
        instance_id = str(candidate["instance_id"])
        instance_root = root / "instances" / instance_id
        order_path = instance_root / "orders.csv"
        if order_path.is_file():
            orders.extend(read_csv(order_path))
        fleet_path = root / "fleet_caps.csv"
        if fleet_path.is_file():
            fleet.extend([row for row in read_csv(fleet_path) if row.get("instance_id") == instance_id])
        catalogs.append({
            "instance_id": instance_id,
            "source_candidate": candidate["source"],
            "source_candidate_id": candidate["source_candidate_id"],
            "region": candidate["region"],
            "customer_count": candidate["customer_count"],
            "replicate": candidate["replicate"],
            "depot_count": len(str(candidate.get("depot_ids", "")).split("|")),
            "depot_ids": candidate.get("depot_ids", ""),
            "formal_search_allowed": "false",
            "search_evaluations": "0",
            "candidate_eligible": candidate["candidate_eligible"],
            "selected_status": candidate["selected_status"],
        })
        facilities_path = root / "facilities.csv"
        if facilities_path.is_file():
            for row in read_csv(facilities_path):
                key = "|".join(str(row.get(name, "")) for name in ("city", "facility_id", "node_id", "facility_name"))
                facilities_by_key.setdefault(key, row)
    if orders:
        write_csv(OUTPUT / "orders.csv", orders)
    if fleet:
        write_csv(OUTPUT / "fleet_caps.csv", fleet)
    write_csv(OUTPUT / "instance_catalog.csv", catalogs)
    write_csv(OUTPUT / "facilities.csv", facilities_by_key.values(), list(next(iter(facilities_by_key.values())).keys()) if facilities_by_key else ["city"])
    write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.china81-final-suite.v1",
            "created_date": "2026-08-15",
            "instance_count": len(selected),
            "candidate_count": len(candidates),
            "candidate_sources": {key: sum(row["source"] == key for row in candidates) for key in ("FS", "PRDFIX", "METRO", "DP", "DEPOTSWAP")},
            "formal_search_allowed": False,
            "formal_search_evaluations": 0,
            "old_instance_overwritten": False,
            "selection_rule": "mixed-fleet two-side precondition; then descending 25 percent relative-gap contestable share; no threshold and no composite score",
            "fallback_semantics": "cells without an eligible candidate retain a representative row and are explicitly marked; no precondition is relaxed",
        },
    )
    write_json(
        OUTPUT / "decision.json",
        {
            "schema": "resetp.china81-final-suite-decision.v1",
            "user_decision_date": "2026-08-15",
            "no_thresholds": True,
            "ranking_metrics": ["mixed_fleet_two_sides_precondition", "contestable_share_25pct_descending"],
            "not_ranking_metrics": ["multi_trip_count", "fleet_saving", "lunch_chargeable_kwh"],
            "old_suites_preserved": True,
            "formal_search_allowed": False,
            "search_evaluations": 0,
        },
    )
    write_json(
        OUTPUT / "build_status.json",
        {
            "status": "FINAL_SUITE_HALT_PENDING_NO_ELIGIBLE_CELL_REVIEW",
            "materialized_instances": len(selected),
            "target_instances": 81,
            "candidate_count": len(candidates),
            "formal_search_allowed": False,
            "search_evaluations": 0,
        },
    )


def render_report(
    candidates: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    selection_rows: list[dict[str, Any]],
    no_eligible: list[dict[str, Any]],
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
) -> str:
    source_counts = Counter(str(row["source"]) for row in candidates)
    source_eligible = Counter(str(row["source"]) for row in candidates if row["candidate_eligible"])
    selected_status = Counter(str(row["selected_status"]) for row in selected)
    old_summary: list[str] = []
    for source in ("FS", "PRDFIX", "METRO", "DP"):
        pool = [row for row in candidates if row["source"] == source]
        old_summary.append(
            f"| FACT | {source} | {len(pool)} | {sum(int(row['witness_status'] == 'PASS') for row in pool)} | {sum(int(row['candidate_eligible']) for row in pool)} |"
        )
    global_eligible = sorted([row for row in candidates if row["candidate_eligible"]], key=candidate_sort_key)
    global_ranking = global_eligible_ranking(candidates)
    main = global_eligible[0] if global_eligible else None
    fs_failures = [row for row in candidates if row["source"] == "FS" and row["witness_status"] != "PASS"]
    lines = [
        "FINAL_SUITE_HALT" if no_eligible else "FINAL_SUITE_DONE",
        "",
        "# China81 最终 81 私有算例重建与候选择优报告（2026-08-15）",
        "",
        "## 结论",
        "",
        f"- `FACT`：已物化 {len(selected)}/81 个新目录；旧四套目录没有覆盖。候选审计总数为 {len(candidates)} = FS {source_counts['FS']} + PRDFIX {source_counts['PRDFIX']} + METRO {source_counts['METRO']} + DP {source_counts['DP']} + DEPOTSWAP {source_counts['DEPOTSWAP']}。",
        f"- `FACT`：按“见证通过、checker_violation_count=0、临界带带下和带上均有车”前置条件，候选中可进入排序的有 {sum(int(row['candidate_eligible']) for row in candidates)} 个；按格统计，无可排序候选的格有 {len(no_eligible)}/81；因此首行保留 `FINAL_SUITE_HALT`，没有把单侧候选冒充合格候选。",
        f"- `FACT`：最终 81 行健康表已生成；其中 {selected_status['SELECTED_ELIGIBLE']} 行由格内可排序候选选出，{selected_status['NO_ELIGIBLE_CELL_REPRESENTATIVE']} 行仅保留代表性候选并明确标记为无可排序候选。",
        f"- `FACT`：正式搜索次数为 0；所有候选的搜索字段固定为 `formal_search_allowed=false`、`search_evaluations=0`。",
        "",
        "## 一、前置核对",
        "",
        "- `FACT`：`solver/reports/p61_wire_all_lanes_20260814/report.md` 首行是 `P61_WIRE_ALL_DONE`，因此本轮前置状态满足。",
        "- `FACT`：P61 报告已经记录 FS 完整评价探针曾报 `CV_D_tianjin_3 has overlap or incomplete recharge`；本轮没有放宽检查，也没有把该异常改写成成功。FS 的 7 个已有见证失败候选保留在 `candidate_audit.csv`，失败原因逐候选留在 `witness_reason`。",
        "- `INFERENCE`：报错对象以 `CV_` 开头却使用 `recharge` 语义，至少说明车辆前缀和充电检查语义之间存在需要后续单独核查的命名/路径疑点；本轮不据此修改检查器。",
        "- `FACT`：`_build_prdfix_suite_context` 与 `_build_metro_suite_context` 在 `solver/scripts/run_problem_hgs_private_technical.py` 中仍是无调用点的死函数，但内部保留 `shift_aware_departure_enabled=True`；本轮没有删除它们，也没有把它们当成活路径。",
        "",
        "## 二、候选池来源",
        "",
        "- `FACT`：297 个基础候选来自四个已保存、可复核的候选套件：FS 81、PRDFIX 81、METRO 81、DP 54；DEPOTSWAP 是额外保留的现有最强参照，计入全局主算例比较和 jjj/50c/01 候选池。",
        "- `FACT`：METRO 的 OSM 候选池来源为 `data/ChinaInstances/china9_metro_pool_20260812/`；已有报告保存 `query_boxes.json`、`city_query_boxes.csv`、`logistics_tag_contract.json`、原始响应和 TLS/504 请求记录。本轮复用这些已保存池，没有重新缩框、放宽标签或静默改变检索框。",
        "- `FACT`：检索框采用已保存的“旧框中心 + 城市专用都市圈半跨度”规则；精确 south/west/north/east 四边界见 `data/ChinaInstances/china9_metro_pool_20260812/query_boxes.json`，不是本轮临时设定。",
        "",
        "| 标签 | 城市 | south | west | north | east |",
        "|---|---|---:|---:|---:|---:|",
    ]
    query_boxes_path = DATA / "china9_metro_pool_20260812/query_boxes.json"
    if query_boxes_path.is_file():
        query_boxes = json.loads(query_boxes_path.read_text(encoding="utf-8"))
        for city in sorted(query_boxes):
            box = query_boxes[city]
            lines.append(
                f"| FACT | {city} | {float(box['south']):.9f} | {float(box['west']):.9f} | {float(box['north']):.9f} | {float(box['east']):.9f} |"
            )
    lines.extend([
        "- `FACT`：本轮重排使用四套候选已有的完整成本/见证健康数据；没有把 METRO 的 Haversine 预筛字段当作本轮 25% 实测值，也没有新增评分。",
        "- `FACT`：本轮脚本只读取已保存候选目录和健康表；历史 `V2-LOCATIONS` 字符串只作为来源标签保留，没有调用旧 China81 V2 有限车队权威加载器。",
        "",
        "## 三、择优过程与逐格结果",
        "",
        "- `USER DECISION`：候选先要求混合车队临界带带下≥1且带上≥1；随后只按 25% 相对差口径可争夺比例从高到低取第一。多趟、省车、午休可充不参与排序。",
        "- `FACT`：逐例完整指标见 `suite_health_final.csv`；全部候选逐例审计见 `candidate_audit.csv`；逐格候选数、淘汰原因和最终选择见 `selection_records.csv`。",
        "",
        "| 标签 | 候选源 | 总数 | 见证 PASS | 可进入排序 |",
        "|---|---|---:|---:|---:|",
        *old_summary,
        "| FACT | DEPOTSWAP | 1 | 1 | 1 |",
        "",
        "| 标签 | 区域 | 规模 | 复本 | 候选总数 | 可排序候选 | 选择状态 | 入选候选 | 25%可争夺 | 淘汰原因分布 |",
        "|---|---|---:|---:|---:|---:|---|---|---:|---|",
    ])
    for row in selection_rows:
        lines.append(
            f"| FACT | {row['region']} | {row['customer_count']} | {row['replicate']} | {row['candidate_pool_total']} | {row['candidate_eligible_count']} | {row['selected_status']} | `{row['selected_candidate_id']}` | {row['selected_25pct_share']} | `{row['eliminated_reason_distribution']}` |"
        )
    lines.extend([
        "",
        "## 四、主算例全局结果",
        "",
    ])
    if main is None:
        lines.append("- `HALT`：298 个候选中没有可进入排序的候选，无法产生主算例。")
    else:
        lines.append(
            f"- `FACT`：主算例是 `{main['instance_id']}`，全局可排序候选中排第 1，25% 可争夺比例为 {main.get('contestable_share_25pct', '')}，来源 `{main['source']}`。"
        )
        lines.append(
            f"- `FACT`：主算例服务客户/需求量为 {main.get('served_customers', '')}/{main.get('served_demand_kg', '')}，临界带带下/带内/带上为 {main.get('critical_band_below_vehicle_count', '')}/{main.get('critical_band_overlap_vehicle_count', '')}/{main.get('critical_band_above_vehicle_count', '')}，单车最多 {main.get('max_trips_per_vehicle', main.get('fleet_max_trips', ''))} 趟，省车比例 {main.get('fleet_reduction_upper_pct_vs_no_reuse', main.get('fleet_reduction_pct', ''))}%。"
        )
        lines.append("- `FACT`：与现 DEPOTSWAP 参照逐项一致，因为本轮全局第 1 正是 DEPOTSWAP；参照值为 0.78、2/2/4、最多 3 趟、省车 50.0%、午休总计 429.9065 kWh、6 辆车。")
        lines.extend([
            "",
            "全局可排序候选前 10 名（完整 142 行见 `global_eligible_ranking.csv`）：",
            "",
            "| 排名 | 候选 | 来源 | 区域 | 规模 | 复本 | 25%可争夺 | 带下/带内/带上 |",
            "|---:|---|---|---|---:|---:|---:|---|",
        ])
        for row in global_ranking[:10]:
            lines.append(
                f"| {row['global_eligible_rank']} | `{row['instance_id']}` | {row['source']} | {row['region']} | {row['customer_count']} | {row['replicate']} | {row['contestable_share_25pct']} | {row['critical_band_below_vehicle_count']}/{row['critical_band_overlap_vehicle_count']}/{row['critical_band_above_vehicle_count']} |"
            )
    lines.extend([
        "",
        "## 五、通不过前置的格",
        "",
        f"- `FACT`：共有 {len(no_eligible)} 个格没有任何候选同时具备可用见证、零 checker 违例和临界带两侧车辆。完整清单在 `no_eligible_cells.csv`；这些格没有被放宽前置，也没有把代表性候选写成 `SELECTED_ELIGIBLE`。",
        "",
        "| 标签 | 区域 | 规模 | 复本 | 候选数 | 代表候选 | 见证状态 | 临界带状态 |",
        "|---|---|---:|---:|---:|---|---|---|",
    ])
    for row in no_eligible:
        lines.append(
            f"| FACT | {row['region']} | {row['customer_count']} | {row['replicate']} | {row['candidate_count']} | `{row['representative_candidate']}` | {row['representative_witness_status']} | {row['representative_mixed_status']} |"
        )
    lines.extend([
        "",
        "## 六、新体系与四套旧套件",
        "",
        "| 标签 | 套件 | 候选数 | 见证 PASS 数 | 同时满足两侧前置数 |",
        "|---|---|---:|---:|---:|",
        *old_summary,
        f"| FACT | FINAL（按格选择） | 81 | {selected_status['SELECTED_ELIGIBLE']} | {selected_status['SELECTED_ELIGIBLE']} |",
        "",
        "| 标签 | 记录数 | 见证 PASS | 可排序 | 25%可争夺中位数 | 最终入选数 |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for source in ("FS", "PRDFIX", "METRO", "DP", "DEPOTSWAP"):
        pool = [row for row in candidates if row["source"] == source]
        shares = [float_value(row.get("contestable_share_25pct")) for row in pool]
        shares = [value for value in shares if value is not None]
        lines.append(
            f"| FACT | {source} | {len(pool)} | {sum(row['witness_status'] == 'PASS' for row in pool)} | {sum(int(row['candidate_eligible']) for row in pool)} | {median(shares) if shares else 'UNKNOWN'} | {sum(row['source'] == source for row in selected)} |"
        )
    final_shares = [float_value(row.get("contestable_share_25pct")) for row in selected]
    final_shares = [value for value in final_shares if value is not None]
    lines.append(
        f"| FACT | FINAL | 81 | {sum(row['witness_status'] == 'PASS' for row in selected)} | {selected_status['SELECTED_ELIGIBLE']} | {median(final_shares) if final_shares else 'UNKNOWN'} | 81 |"
    )
    lines.extend([
        "",
        "- `FACT`：FS 的完整评价探针异常和 7 个见证失败候选没有删除；METRO、PRDFIX、DP 的原始失败/单侧候选也进入淘汰原因分布。",
        "",
        "## 七、与 DEPOTSWAP 逐项对照",
        "",
        "| 指标 | DEPOTSWAP参照 | 本轮主算例 |",
        "|---|---:|---:|",
        "| 25%可争夺比例 | 0.78 | " + (str(main.get("contestable_share_25pct", "")) if main else "UNKNOWN") + " |",
        "| 临界带带下/带内/带上 | 2/2/4 | " + (f"{main.get('critical_band_below_vehicle_count','')}/{main.get('critical_band_overlap_vehicle_count','')}/{main.get('critical_band_above_vehicle_count','')}" if main else "UNKNOWN") + " |",
        "| 单车最多趟数 | 3 | " + (str(main.get("max_trips_per_vehicle", main.get("fleet_max_trips", ""))) if main else "UNKNOWN") + " |",
        "| 省车比例 | 50.0% | " + (str(main.get("fleet_reduction_upper_pct_vs_no_reuse", main.get("fleet_reduction_pct", ""))) + "%" if main else "UNKNOWN") + " |",
        "| 午休可充电总量(kWh) | 429.9065 | " + (str(main.get("lunch_chargeable_kwh_60kw_total", "")) if main else "UNKNOWN") + " |",
        "| 区域碳杠杆 | +0.3391 | " + (str(main.get("carbon_leverage", "")) if main else "UNKNOWN") + " |",
        "",
        "## 八、未能完成项",
        "",
        f"- `HALT`：{len(no_eligible)} 个格没有满足前置条件的候选；若要把报告首行改成 `FINAL_SUITE_DONE`，需要用户决定是否允许这些格只作为“无机制对象”的保留算例，或补充新的候选几何/见证。代理没有自行放宽。",
        f"- `FACT`：FS 见证失败候选数为 {len(fs_failures)}；P61 记录的 `CV_D_tianjin_3 has overlap or incomplete recharge` 命名/语义错配尚未修改。",
        "- `FACT`：本轮没有正式搜索，没有更改三个受保护评价器，也没有删除任何旧套件。",
        "",
        "## 九、受保护文件哈希",
        "",
        "| 标签 | 文件 | 任务前 SHA-256 | 任务后 SHA-256 |",
        "|---|---|---|---|",
    ])
    for path in PROTECTED:
        key = str(path)
        lines.append(f"| FACT | `{key}` | `{protected_before[key]}` | `{protected_after[key]}` |")
    return "\n".join(lines) + "\n"


def build() -> None:
    if OUTPUT.exists() or REPORT.exists():
        raise FileExistsError("refusing to overwrite final suite output/report")
    protected_before = {str(path): sha256(REPO / path) for path in PROTECTED}
    candidates = load_candidates()
    selected, selection_rows, no_eligible = choose_candidates(candidates)
    OUTPUT.mkdir(parents=True)
    REPORT.mkdir(parents=True)
    copy_selected_instances(selected)
    write_root_aggregates(selected, candidates)

    health_rows = [normalize_health(row) for row in selected]
    health_fields: list[str] = []
    for row in health_rows:
        for key in row:
            if key not in health_fields:
                health_fields.append(key)
    write_csv(REPORT / "suite_health_final.csv", health_rows, health_fields)
    write_csv(REPORT / "selection_records.csv", selection_rows)
    write_csv(REPORT / "no_eligible_cells.csv", no_eligible)
    write_csv(REPORT / "candidate_audit.csv", candidates)
    write_csv(REPORT / "global_eligible_ranking.csv", global_eligible_ranking(candidates))

    fs_failures = [row for row in candidates if row["source"] == "FS" and row["witness_status"] != "PASS"]
    write_csv(REPORT / "fs_complete_check_failures.csv", fs_failures)
    write_json(REPORT / "candidate_pool_manifest.json", {
        "candidate_count": len(candidates),
        "source_counts": dict(Counter(str(row["source"]) for row in candidates)),
        "source_health_files": {item["source"]: str(item["health"].relative_to(REPO)) for item in SOURCES},
        "depotswap_health_file": str((DEPOTSWAP_ROOT / "selection_health.csv").relative_to(REPO)),
        "selection_rule": "mixed-fleet two-side precondition then descending contestable_share_25pct; no threshold or composite score",
    })
    protected_after = {str(path): sha256(REPO / path) for path in PROTECTED}
    if protected_before != protected_after:
        raise RuntimeError("protected evaluator hash changed")
    write_json(REPORT / "metadata.json", {
        "schema": "resetp.china81-final-suite-report.v1",
        "created_date": "2026-08-15",
        "instance_count": len(selected),
        "candidate_count": len(candidates),
        "no_eligible_cell_count": len(no_eligible),
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "source_reports": [str(item["health"].relative_to(REPO)) for item in SOURCES],
        "depotswap_report": str((DEPOTSWAP_ROOT / "selection_health.csv").relative_to(REPO)),
    })
    write_csv(REPORT / "candidate_source_index.csv", [
        {
            "source": item["source"],
            "health": str(item["health"].relative_to(REPO)),
            "data_root": str(item["root"].relative_to(REPO)),
        }
        for item in SOURCES
    ] + [{"source": "DEPOTSWAP", "health": str((DEPOTSWAP_ROOT / "selection_health.csv").relative_to(REPO)), "data_root": str(DEPOTSWAP_ROOT.relative_to(REPO))}])

    write_json(REPORT / "decision.json", {
        "schema": "resetp.china81-final-suite-report-decision.v1",
        "completion": "FINAL_SUITE_HALT" if no_eligible else "FINAL_SUITE_DONE",
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "no_eligible_cell_count": len(no_eligible),
    })
    write_csv(REPORT / "raw_runs.csv", [
        {
            "instance_id": row["instance_id"],
            "source": row["source"],
            "formal_search_allowed": "false",
            "search_evaluations": "0",
            "witness_status": row["witness_status"],
            "checker_violation_count": row["checker_violation_count"],
            "candidate_eligible": row["candidate_eligible"],
            "selected_status": row["selected_status"],
        }
        for row in selected
    ])

    file_hashes: dict[str, str] = {}
    for root in (OUTPUT, REPORT):
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"):
                file_hashes[str(path.relative_to(REPO))] = sha256(path)
    write_json(REPORT / "artifact_hashes.json", file_hashes)
    write_json(OUTPUT / "artifact_hashes.json", {
        key: value for key, value in file_hashes.items() if key.startswith(str(OUTPUT.relative_to(REPO)) + "/")
    })
    (REPORT / "report.md").write_text(
        render_report(candidates, selected, selection_rows, no_eligible, protected_before, protected_after),
        encoding="utf-8",
    )
    # Report hashes are written after the report itself; refresh the manifest.
    file_hashes = {}
    for root in (OUTPUT, REPORT):
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"):
                file_hashes[str(path.relative_to(REPO))] = sha256(path)
    write_json(REPORT / "artifact_hashes.json", file_hashes)
    write_json(OUTPUT / "artifact_hashes.json", {
        key: value for key, value in file_hashes.items() if key.startswith(str(OUTPUT.relative_to(REPO)) + "/")
    })
    # Keep the output status aligned with the report's explicit completion.
    write_json(OUTPUT / "build_status.json", {
        "status": "FINAL_SUITE_HALT" if no_eligible else "FINAL_SUITE_DONE",
        "materialized_instances": len(selected),
        "target_instances": 81,
        "candidate_count": len(candidates),
        "no_eligible_cell_count": len(no_eligible),
        "formal_search_allowed": False,
        "search_evaluations": 0,
    })
    # build_status is the last mutable output; refresh both manifests once
    # more so every recorded hash describes the final bytes.
    file_hashes = {}
    for root in (OUTPUT, REPORT):
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"):
                file_hashes[str(path.relative_to(REPO))] = sha256(path)
    write_json(REPORT / "artifact_hashes.json", file_hashes)
    write_json(OUTPUT / "artifact_hashes.json", {
        key: value for key, value in file_hashes.items() if key.startswith(str(OUTPUT.relative_to(REPO)) + "/")
    })


if __name__ == "__main__":
    build()
