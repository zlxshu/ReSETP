#!/usr/bin/env python3
"""Zero-search audit for the frozen Solomon/DIMACS VRPTW benchmark contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile


EXPECTED_ZIP_SHA256 = "8a0a72cbe6b7f8f9988ace4ebde0378ec34943acaaac47f2c408915e41887747"
EXPECTED_CONTROLLER_COMMIT = "87de6d63eca1c8d4b5862c7a850fdc5a40595fe1"
EXPECTED_CLASS_COUNTS = {"C1": 9, "C2": 8, "R1": 12, "R2": 11, "RC1": 8, "RC2": 8}


@dataclass(frozen=True)
class Node:
    idx: int
    x: int
    y: int
    demand: int
    ready: int
    due: int
    service: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def instance_class(name: str) -> str:
    match = re.fullmatch(r"(RC|C|R)([12])\d{2}", name)
    if not match:
        raise ValueError(f"unexpected Solomon instance name: {name}")
    return f"{match.group(1)}{match.group(2)}"


def parse_instance(data: bytes) -> tuple[str, int, int, list[Node]]:
    text = data.decode("ascii")
    lines = text.splitlines()
    name = next(line.strip().upper() for line in lines if line.strip())
    vehicle_match = re.search(r"NUMBER\s+CAPACITY\s+(\d+)\s+(\d+)", text, re.DOTALL)
    if not vehicle_match:
        raise ValueError(f"vehicle header missing in {name}")
    max_vehicles, capacity = map(int, vehicle_match.groups())
    nodes: list[Node] = []
    for line in lines:
        values = re.fullmatch(r"\s*(\d+)\s+(-?\d+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*", line)
        if values:
            nodes.append(Node(*map(int, values.groups())))
    return name, max_vehicles, capacity, nodes


def truncated_distance(a: Node, b: Node) -> float:
    return math.floor(10.0 * math.hypot(a.x - b.x, a.y - b.y)) / 10.0


def distance_matrix_sha256(nodes: list[Node]) -> str:
    payload = "\n".join(
        ",".join(f"{truncated_distance(a, b):.1f}" for b in nodes)
        for a in nodes
    ).encode("ascii")
    return sha256_bytes(payload)


def parse_bks(script: Path) -> dict[str, tuple[float, int, int]]:
    pattern = re.compile(
        r"Instances/Solomon/([A-Z0-9]+)\.txt\s+\$2\s+(\d+)\s+([0-9.]+)\s+([01])\s+\$3"
    )
    found: dict[str, tuple[float, int, int]] = {}
    for name, time_limit, bks, optimal in pattern.findall(script.read_text(encoding="utf-8")):
        found[name] = (float(bks), int(optimal), int(time_limit))
    return found


def git_commit(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--zip",
        type=Path,
        default=Path("/Volumes/移动硬盘（512G）/VRP/算例/solomon-100.zip"),
    )
    parser.add_argument("--controller", type=Path, default=Path("/private/tmp/VRPTWController"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("baselines/e2_alns/e2_solomon_dimacs_adapter_20260717"),
    )
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"refuse to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    zip_hash = sha256_path(args.zip)
    if zip_hash != EXPECTED_ZIP_SHA256:
        failures.append(f"zip hash mismatch: {zip_hash}")

    controller_commit = git_commit(args.controller)
    if controller_commit != EXPECTED_CONTROLLER_COMMIT:
        failures.append(f"controller commit mismatch: {controller_commit}")
    bks = parse_bks(args.controller / "genScript1.sh")
    if len(bks) != 56:
        failures.append(f"expected 56 Solomon BKS rows, found {len(bks)}")

    official_dir = args.controller / "Instances" / "Solomon"
    rows: list[dict[str, object]] = []
    with ZipFile(args.zip) as archive:
        members = {Path(name).name.lower(): name for name in archive.namelist() if name.lower().endswith(".txt")}
        for name in sorted(bks):
            member = members.get(f"{name.lower()}.txt")
            if member is None:
                failures.append(f"missing zip member for {name}")
                continue
            local_data = archive.read(member)
            official_path = official_dir / f"{name}.txt"
            official_data = official_path.read_bytes()
            byte_equal = local_data == official_data
            parsed_name, max_vehicles, capacity, nodes = parse_instance(local_data)
            ids_ok = [node.idx for node in nodes] == list(range(101))
            node_fields_ok = (
                len(nodes) == 101
                and ids_ok
                and nodes[0].demand == 0
                and all(node.demand >= 0 and node.ready <= node.due and node.service >= 0 for node in nodes)
            )
            if parsed_name != name:
                failures.append(f"name mismatch for {name}: {parsed_name}")
            if not byte_equal:
                failures.append(f"local/official bytes differ for {name}")
            if not node_fields_ok:
                failures.append(f"invalid node structure for {name}")
            reference, optimal, time_limit = bks[name]
            rows.append(
                {
                    "instance": name,
                    "class": instance_class(name),
                    "customers": len(nodes) - 1,
                    "max_vehicles": max_vehicles,
                    "capacity": capacity,
                    "reference_value": f"{reference:.1f}",
                    "optimal_flag": optimal,
                    "standardized_time_limit_s": time_limit,
                    "zip_member": member,
                    "instance_sha256": sha256_bytes(local_data),
                    "official_byte_equal": int(byte_equal),
                    "node_structure_ok": int(node_fields_ok),
                    "distance_matrix_sha256": distance_matrix_sha256(nodes),
                    "distance_rule": "floor(10*euclidean)/10",
                    "search_evaluations": 0,
                }
            )

    class_counts = Counter(str(row["class"]) for row in rows)
    if dict(class_counts) != EXPECTED_CLASS_COUNTS:
        failures.append(f"class counts mismatch: {dict(class_counts)}")
    if any(int(row["optimal_flag"]) != 1 for row in rows):
        failures.append("not all Solomon references are marked optimal")

    raw_runs = output / "raw_runs.csv"
    fieldnames = list(rows[0]) if rows else []
    with raw_runs.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "audit": "Solomon DIMACS VRPTW zero-search adapter gate",
        "created_at_utc": now,
        "search_performed": False,
        "zip_path": str(args.zip),
        "zip_sha256": zip_hash,
        "controller_path": str(args.controller),
        "controller_commit": controller_commit,
        "controller_gen_script_sha256": sha256_path(args.controller / "genScript1.sh"),
        "rules": {
            "objective": "total route distance only",
            "time_windows": "hard",
            "vehicle_count": "upper bound, not lexicographic objective",
            "distance": "Euclidean truncated to one decimal place",
            "cpu_baseline_passmark_single_thread": 2000,
            "standardized_time_limit_s": 1800,
        },
        "expected_instances": 56,
        "class_counts": dict(class_counts),
    }
    write_json(output / "metadata.json", metadata)

    verdict = "PASS_SOLOMON_DIMACS_ZERO_SEARCH_ADAPTER_GATE" if not failures else "FAIL_SOLOMON_DIMACS_ZERO_SEARCH_ADAPTER_GATE"
    decision = {
        "verdict": verdict,
        "failures": failures,
        "instances_verified": len(rows),
        "all_references_marked_optimal": bool(rows) and all(int(row["optimal_flag"]) == 1 for row in rows),
        "formal_search_authorized": False,
        "next_gate": "freeze final algorithm outside Solomon, then run formal benchmark after E7",
    }
    write_json(output / "decision.json", decision)

    report_lines = [
        "# Solomon/DIMACS 零搜索适配审计",
        "",
        f"判定：`{verdict}`。",
        "",
        f"核对 {len(rows)}/56 个 Solomon 100 客户算例；本轮路径搜索评价次数为 0。",
        f"六类数量：{dict(class_counts)}。",
        "距离口径为 `floor(10 * Euclidean) / 10`，车辆数为上限，目标仅为总距离。",
        "BKS/最优标志来自冻结的 DIMACS 控制器 `genScript1.sh`；56项均标记为已证明最优。",
        "本地压缩包内算例逐项与冻结控制器版本作字节比较。",
        "",
        "该门只证明数据、BKS、目标和解析口径一致，不证明本文算法性能，也不授权在E7运行期间修改共享内核。",
    ]
    if failures:
        report_lines.extend(["", "## 失败项", "", *[f"- {item}" for item in failures]])
    (output / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    artifact_paths = [
        output / "metadata.json",
        raw_runs,
        output / "decision.json",
        output / "report.md",
        Path(__file__).resolve(),
    ]
    artifact_hashes = {str(path): sha256_path(path) for path in artifact_paths}
    write_json(output / "artifact_hashes.json", artifact_hashes)

    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
