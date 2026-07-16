#!/usr/bin/env python3
"""Zero-long-run feasibility audit for a faithful Goeke--Schneider benchmark.

This script does not run a routing algorithm.  It extracts the 180 published
comparison values from Table 11, verifies the local public instances and fleet
fields, and records whether the current ReSETP experiment can be compared with
those values without changing the benchmark contract.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
DEFAULT_PDF = Path(
    "/Users/zhouleixishu/Zotero/storage/PGY3QPNT/"
    "Goeke和Schneider _ 2015 _ Routing a mixed fleet of electric and conventional vehicles.pdf"
)
DEFAULT_RAW = REPO / "models/data_bundle/raw_instances/goeke_uk"
DEFAULT_OUT = REPO / "baselines/e2_alns/goeke_public_benchmark_feasibility_20260716"
OFFICIAL_ARCHIVE_SHA256 = "459a542b067723746d345ada6f5cdfc77aa4ca8776bbd84a0b68d47636e696c7"
SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
ROW_RE = re.compile(
    r"E-UK(10|15|20|25|50|75|100|150|200)_(\d{2})\s+"
    r"(\d+)\s+(\d+)\s+([0-9]+\.[0-9]+)\s+([0-9]+\.[0-9]+)"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_reference(pdf: Path) -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory(prefix="goeke-benchmark-") as temp_dir:
        text_path = Path(temp_dir) / "paper.txt"
        subprocess.run(["pdftotext", "-layout", str(pdf), str(text_path)], check=True)
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    marker = "Appendix A. Overview of complete results on E-VRPTWMF"
    start = text.rfind(marker)
    if start < 0:
        raise RuntimeError("Table 11 appendix marker not found")
    rows: list[dict[str, object]] = []
    for match in ROW_RE.finditer(text[start:]):
        size, suffix, m_cv, m_ev, distance, runtime = match.groups()
        rows.append(
            {
                "instance": f"E-UK{size}_{suffix}",
                "customers": int(size),
                "published_used_cv": int(m_cv),
                "published_used_ev": int(m_ev),
                "published_best_distance_km": float(distance),
                "published_mean_runtime_min": float(runtime),
                "published_runs": 10,
                "published_status": "comparison_value_not_proven_BKS",
            }
        )
    if len(rows) != 180 or len({row["instance"] for row in rows}) != 180:
        raise RuntimeError(f"expected 180 unique Table 11 rows, found {len(rows)}")
    return sorted(rows, key=lambda row: (int(row["customers"]), str(row["instance"])))


def raw_fleet(path: Path) -> tuple[int, int, int]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    total = re.search(r"m\s+numVeh\s+/([0-9]+)/", text)
    cv = re.search(r"m\s+numPetrolVeh\s+/([0-9]+)/", text)
    ev = re.search(r"m\s+numElectroVeh\s+/([0-9]+)/", text)
    if not total or not cv or not ev:
        raise RuntimeError(f"fleet fields missing in {path}")
    return int(total.group(1)), int(cv.group(1)), int(ev.group(1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--official-zip", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    rows = extract_reference(args.paper_pdf)
    raw_files = sorted(args.raw_root.glob("E-UK*.txt"))
    raw_by_name = {path.stem: path for path in raw_files}
    raw_by_filename = {path.name: path for path in raw_files}
    size_counts = Counter(int(row["customers"]) for row in rows)
    missing = [str(row["instance"]) for row in rows if row["instance"] not in raw_by_name]
    fleet_identity_failures: list[dict[str, object]] = []
    for row in rows:
        path = raw_by_name[str(row["instance"])]
        total, cv, ev = raw_fleet(path)
        # Table 11's first vehicle-count column is numerically identical to
        # ``numVeh`` in every public file, while its second column is identical
        # to ``numElectroVeh``.  Treating the first column as the conventional
        # count creates the earlier spurious 178/180 mismatch.  The adapter
        # therefore freezes the observable identity and derives the used CV
        # count as total minus EV.
        row["published_total_vehicles"] = row.pop("published_used_cv")
        row["published_used_ev"] = row.pop("published_used_ev")
        row["derived_published_used_cv"] = int(row["published_total_vehicles"]) - int(row["published_used_ev"])
        row["raw_num_veh_field"] = total
        row["raw_num_petrol_veh_field"] = cv
        row["raw_num_electro_veh_field"] = ev
        row["published_counts_match_raw_composition"] = (
            int(row["published_total_vehicles"]) == total
            and int(row["published_used_ev"]) == ev
            and int(row["derived_published_used_cv"]) == cv
        )
        row["raw_sha256"] = sha256(path)
        if not row["published_counts_match_raw_composition"]:
            fleet_identity_failures.append(row)

    official_match_count = None
    official_zip_sha256 = None
    if args.official_zip:
        official_zip_sha256 = sha256(args.official_zip)
        with zipfile.ZipFile(args.official_zip) as archive:
            official_names = {
                Path(name).name: name
                for name in archive.namelist()
                if Path(name).name.startswith("E-UK") and name.endswith(".txt")
            }
            official_match_count = sum(
                raw_by_filename[name].read_bytes() == archive.read(official_names[name])
                for name in raw_by_filename.keys() & official_names.keys()
            )

    raw_csv = out / "raw_runs.csv"
    with raw_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    checks = {
        "published_table11_complete": len(rows) == 180 and all(size_counts[size] == 20 for size in SIZES),
        "local_instance_set_complete": len(raw_files) == 180 and not missing,
        "published_vehicle_columns_match_raw_total_ev_and_derived_cv": not fleet_identity_failures,
        "local_files_match_official_archive": official_match_count == 180,
        "published_values_are_bks": False,
        "original_goeke_java_source_locally_available": False,
        "current_resetp_objective_matches_distance_only": False,
        "current_resetp_single_trip_contract_matches": False,
        "current_resetp_charging_contract_matches": False,
    }
    decision = {
        "decision": "HALT_DIRECT_BKS_CLAIM_ADAPTER_REQUIRED",
        "direct_public_comparison_ready": False,
        "reason": (
            "The public instances and all 180 Table 11 comparison values are present and identity-checked, "
            "but Table 11 reports the best of ten ALNS runs under distance minimization, not proven BKS. "
            "The current ReSETP experiment minimizes a seven-part operating cost and permits physical "
            "vehicles to perform multiple trips with a different charging scheduler. A dedicated frozen "
            "single-depot, single-trip, 80 kWh, distance-only adapter must pass an independent evaluator "
            "before any Gap% against Table 11 is reported."
        ),
        "checks": checks,
        "reference_row_count": len(rows),
        "raw_instance_count": len(raw_files),
        "missing_instances": missing,
        "fleet_identity_failure_count": len(fleet_identity_failures),
        "official_archive_match_count": official_match_count,
        "recommended_scope": (
            "Build and validate the adapter on E-UK10_01, E-UK15_01 and E-UK20_01 first; only after exact "
            "route-distance, fleet, time-window, battery and full-recharge semantics agree should a formal "
            "9 sizes x 20 instances x 10 runs benchmark be scheduled."
        ),
    }
    (out / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "zero_long_run_public_benchmark_feasibility_audit",
        "paper_pdf": str(args.paper_pdf),
        "paper_pdf_sha256": sha256(args.paper_pdf),
        "paper_doi": "10.1016/j.ejor.2015.01.049",
        "dataset_doi": "10.17632/bd7rm5fw6k.1",
        "official_archive_expected_sha256": OFFICIAL_ARCHIVE_SHA256,
        "official_archive_observed_sha256": official_zip_sha256,
        "raw_root": str(args.raw_root),
        "table11_semantics": "best of 10 ALNS runs; distance minimization; comparison values, not BKS",
        "script": str(Path(__file__).resolve()),
        "script_sha256": sha256(Path(__file__).resolve()),
    }
    (out / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = f"""# Goeke--Schneider公开基准零长跑可行性审计

## 结论

判决：`{decision['decision']}`。数据层已经闭合：本地有9个规模、每个规模20个实例，共180个原始文件；论文表11的180个比较值全部可抽取；本地180个文件与Mendeley官方压缩包逐字节一致。算法比较层尚未闭合，当前不得写BKS或Gap%。

## 为什么不能直接比较

Goeke和Schneider表11报告的是“以行驶距离为目标、10次ALNS中的最好值”，原文称其为供后续研究比较的结果，并未证明为全局BKS。ReSETP当前目标为固定费、里程费、燃油费、电费、占用费、跨场费和碳成本之和；同时采用实体车多趟排班和本文的充电调度。即使客户坐标和车队数量相同，两个目标值仍不属于同一数学问题。

重新逐项核对后，早期“178/180项车队字段冲突”的判断被推翻。表11第一车辆列在180个实例上逐项等于原始文件的`numVeh`，第二车辆列逐项等于`numElectroVeh`，两者之差逐项等于`numPetrolVeh`。因此适配器冻结“总车辆数—电动车数—派生燃油车数”口径；这也说明表11第一列不能脱离公开文件直接解释成燃油车数。

## 可执行下一步

先建立独立的公开基准适配器，冻结为单车场、单趟、80 kWh、90 km/h、原车队上限、原时间窗和全充电语义，只优化总距离。先在E-UK10_01、E-UK15_01和E-UK20_01上核对独立评价器；三项通过后，才考虑180实例乘10次的正式批次。该批次必须与论文主实验分栏，不能把表11比较值称作世界最优值。

## 核验摘要

- 表11行数：{len(rows)}；各规模均为20个实例。
- 本地原始实例：{len(raw_files)}；缺失：{len(missing)}。
- 本地文件与Mendeley官方压缩包逐字节一致：{official_match_count}/180。
- 表11第一车辆列=`numVeh`、第二车辆列=`numElectroVeh`、两者之差=`numPetrolVeh`：{180 - len(fleet_identity_failures)}/180逐项成立。
- 原作者Java源码：本地未找到；公开数据页只确认实例数据，故不能声称已忠实运行原算法。
"""
    (out / "report.md").write_text(report, encoding="utf-8")
    hashes = {path.name: sha256(path) for path in (out / "metadata.json", raw_csv, out / "decision.json", out / "report.md")}
    (out / "artifact_hashes.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": decision["decision"], "rows": len(rows), "output": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
