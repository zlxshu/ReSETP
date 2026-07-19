#!/usr/bin/env python3
"""Freeze the result-blind X-CVRP comparison foundation without running a solver.

The script snapshots the current CVRPLIB X-100 catalogue, downloads the 20
pre-registered safety/development/confirmation/holdout instances and BKS
solutions, independently checks the BKS routes, and publishes the mandatory
five evidence surfaces.

It deliberately uses only the Python standard library so the evidence can be
recreated on a clean machine.  Solver search is never imported or invoked.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    REPO_ROOT
    / "baselines"
    / "algorithm_foundation"
    / "x_cvrp_selection_20260719"
)
CVRPLIB_ROOT = "https://galgos.inf.puc-rio.br"
CATALOGUE_URL = f"{CVRPLIB_ROOT}/cvrplib/en/instances"
HGS_INSTANCE_DIR = (
    REPO_ROOT
    / "build"
    / "official-hgs-cvrp-1a927955cd28"
    / "source"
    / "Instances"
    / "CVRP"
)
HGS_COMMIT = "1a927955cd2861a29d978f0d359d6e647db9319c"
USER_AGENT = "ReSETP-zero-search-foundation-freezer/2026-07-19"

ROLE_INDICES: dict[str, tuple[int, ...]] = {
    "safety_optimal": tuple(range(1, 6)),
    "development_headroom": tuple(range(76, 81)),
    "confirmation_headroom": tuple(range(86, 91)),
    "holdout_headroom": tuple(range(96, 101)),
}

EXPECTED_NAMES: dict[str, tuple[str, ...]] = {
    "safety_optimal": (
        "X-n101-k25",
        "X-n106-k14",
        "X-n110-k13",
        "X-n115-k10",
        "X-n120-k6",
    ),
    "development_headroom": (
        "X-n586-k159",
        "X-n599-k92",
        "X-n613-k62",
        "X-n627-k43",
        "X-n641-k35",
    ),
    "confirmation_headroom": (
        "X-n733-k159",
        "X-n749-k98",
        "X-n766-k71",
        "X-n783-k48",
        "X-n801-k40",
    ),
    "holdout_headroom": (
        "X-n916-k207",
        "X-n936-k151",
        "X-n957-k87",
        "X-n979-k58",
        "X-n1001-k43",
    ),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalise_newlines(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


class RowParser(HTMLParser):
    """Collect text cells and links from every HTML table row."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self.in_row = False
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.cells: list[str] = []
        self.links: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "tr":
            self.in_row = True
            self.cells = []
            self.links = []
        elif self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.cell_parts = []
        elif self.in_row and tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.in_row and tag in {"td", "th"} and self.in_cell:
            value = " ".join("".join(self.cell_parts).split())
            self.cells.append(value)
            self.in_cell = False
            self.cell_parts = []
        elif tag == "tr" and self.in_row:
            self.rows.append({"cells": list(self.cells), "links": list(self.links)})
            self.in_row = False
            self.in_cell = False


def parse_number(text: str) -> float:
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if not cleaned:
        raise ValueError(f"cannot parse number from {text!r}")
    return float(cleaned)


@dataclass(frozen=True)
class XRow:
    index: int
    name: str
    customers: int
    catalogue_k: int
    capacity: int
    bks: float
    optimal: bool
    instance_url: str
    bks_url: str


def parse_x_rows(page: bytes) -> list[XRow]:
    parser = RowParser()
    parser.feed(page.decode("utf-8", errors="strict"))
    rows: list[XRow] = []
    for row in parser.rows:
        links = row["links"]
        instance_links = [
            href for href in links if "/cvrplib/en/download/instance/" in href
        ]
        if not instance_links:
            continue
        cells = row["cells"]
        if not cells or not cells[0].startswith("X-"):
            continue
        bks_links = [href for href in links if "/cvrplib/en/download/bks/" in href]
        if len(cells) < 6 or len(bks_links) != 1:
            raise ValueError(f"unexpected X row: cells={cells!r} links={links!r}")
        rows.append(
            XRow(
                index=len(rows) + 1,
                name=cells[0],
                customers=int(parse_number(cells[1])),
                catalogue_k=int(parse_number(cells[2])),
                capacity=int(parse_number(cells[3])),
                bks=parse_number(cells[4]),
                optimal=cells[5].strip().lower() == "yes",
                instance_url=urllib.parse.urljoin(
                    CVRPLIB_ROOT,
                    instance_links[0],
                ),
                bks_url=urllib.parse.urljoin(CVRPLIB_ROOT, bks_links[0]),
            )
        )
    if len(rows) != 100:
        raise ValueError(f"expected 100 X rows, found {len(rows)}")
    return rows


def parse_vrp(data: bytes) -> dict[str, Any]:
    lines = normalise_newlines(data).decode("ascii").splitlines()
    fields: dict[str, str] = {}
    coordinates: dict[int, tuple[int, int]] = {}
    demands: dict[int, int] = {}
    depots: list[int] = []
    section = "header"
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line == "NODE_COORD_SECTION":
            section = "coordinates"
            continue
        if line == "DEMAND_SECTION":
            section = "demands"
            continue
        if line == "DEPOT_SECTION":
            section = "depots"
            continue
        if line == "EOF":
            break
        if section == "header":
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip().strip('"')
        elif section == "coordinates":
            node, x_coord, y_coord = (int(value) for value in line.split())
            coordinates[node] = (x_coord, y_coord)
        elif section == "demands":
            node, demand = (int(value) for value in line.split())
            demands[node] = demand
        elif section == "depots":
            depot = int(line)
            if depot != -1:
                depots.append(depot)
    dimension = int(fields["DIMENSION"])
    capacity = int(fields["CAPACITY"])
    if fields.get("EDGE_WEIGHT_TYPE") != "EUC_2D":
        raise ValueError(f"unexpected edge type: {fields.get('EDGE_WEIGHT_TYPE')}")
    if len(coordinates) != dimension or len(demands) != dimension:
        raise ValueError("coordinate/demand count does not match dimension")
    if len(depots) != 1:
        raise ValueError(f"expected one depot, found {depots}")
    return {
        "name": fields["NAME"],
        "dimension": dimension,
        "capacity": capacity,
        "coordinates": coordinates,
        "demands": demands,
        "depot": depots[0],
    }


def parse_solution(data: bytes) -> tuple[list[list[int]], float]:
    routes: list[list[int]] = []
    declared_cost: float | None = None
    for raw_line in normalise_newlines(data).decode("ascii").splitlines():
        line = raw_line.strip()
        route_match = re.fullmatch(r"Route #\d+:\s*(.*)", line)
        if route_match:
            customers = route_match.group(1).strip()
            routes.append([int(item) for item in customers.split()] if customers else [])
            continue
        cost_match = re.fullmatch(r"Cost\s+([0-9]+(?:\.[0-9]+)?)", line)
        if cost_match:
            declared_cost = float(cost_match.group(1))
    if not routes or declared_cost is None:
        raise ValueError("solution lacks routes or cost")
    return routes, declared_cost


def euc_2d(a: tuple[int, int], b: tuple[int, int]) -> int:
    return math.floor(math.hypot(a[0] - b[0], a[1] - b[1]) + 0.5)


def validate_solution(
    problem: dict[str, Any],
    routes: list[list[int]],
    declared_cost: float,
    row: XRow,
) -> dict[str, Any]:
    depot = problem["depot"]
    coordinates = problem["coordinates"]
    demands = problem["demands"]
    capacity = problem["capacity"]
    expected_customers = set(coordinates) - {depot}
    ordered_customers = sorted(expected_customers)
    if depot != 1:
        raise ValueError(
            "the frozen X solution-ID adapter expects TSPLIB depot node 1"
        )
    mapped_routes: list[list[int]] = []
    for route in routes:
        mapped_route: list[int] = []
        for solution_customer in route:
            if not 1 <= solution_customer <= len(ordered_customers):
                raise ValueError(
                    f"solution customer ID outside 1..{len(ordered_customers)}: "
                    f"{solution_customer}"
                )
            mapped_route.append(ordered_customers[solution_customer - 1])
        mapped_routes.append(mapped_route)
    visits = [customer for route in mapped_routes for customer in route]
    visit_set = set(visits)
    duplicates = sorted(
        customer for customer in visit_set if visits.count(customer) > 1
    )
    missing = sorted(expected_customers - visit_set)
    extras = sorted(visit_set - expected_customers)
    route_loads = [
        sum(demands[customer] for customer in route) for route in mapped_routes
    ]
    overloaded = [
        {"route": index + 1, "load": load}
        for index, load in enumerate(route_loads)
        if load > capacity
    ]
    computed_cost = 0
    for route in mapped_routes:
        path = [depot, *route, depot]
        computed_cost += sum(
            euc_2d(coordinates[left], coordinates[right])
            for left, right in zip(path, path[1:])
        )
    checks = {
        "instance_name_matches": problem["name"] == row.name,
        "customer_count_matches": problem["dimension"] - 1 == row.customers,
        "capacity_matches": capacity == row.capacity,
        "solution_routes_are_nonempty": all(mapped_routes),
        "all_customers_exactly_once": (
            len(visits) == len(expected_customers)
            and not duplicates
            and not missing
            and not extras
        ),
        "capacity_feasible": not overloaded,
        "computed_cost_matches_solution": abs(computed_cost - declared_cost) < 1e-9,
        "solution_cost_matches_catalogue": abs(declared_cost - row.bks) < 1e-9,
    }
    return {
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "computed_cost": computed_cost,
        "declared_cost": declared_cost,
        "route_count": len(routes),
        "catalogue_k": row.catalogue_k,
        "solution_customer_id_convention": "one_based_without_depot",
        "max_route_load": max(route_loads, default=0),
        "duplicates": duplicates,
        "missing": missing,
        "extras": extras,
        "overloaded": overloaded,
    }


def role_for(index: int) -> str:
    matches = [role for role, indices in ROLE_INDICES.items() if index in indices]
    if len(matches) > 1:
        raise ValueError(f"index {index} assigned to multiple roles: {matches}")
    return matches[0] if matches else "formal_x100_only"


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_hash_manifest(root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "artifact_hashes.json":
            continue
        if path.name.startswith("._") or "__pycache__" in path.parts:
            continue
        entries.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return {
        "algorithm": "sha256",
        "excludes": ["artifact_hashes.json", "._*", "__pycache__"],
        "files": entries,
    }


def main() -> int:
    if OUTPUT_DIR.exists():
        raise FileExistsError(
            f"refusing to overwrite immutable evidence directory: {OUTPUT_DIR}"
        )
    OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{OUTPUT_DIR.name}.tmp-",
            dir=OUTPUT_DIR.parent,
        )
    )
    started = datetime.now(timezone.utc)
    try:
        source_dir = temp_dir / "sources"
        instance_dir = source_dir / "instances"
        bks_dir = source_dir / "bks"
        instance_dir.mkdir(parents=True)
        bks_dir.mkdir(parents=True)

        page = fetch(CATALOGUE_URL)
        (source_dir / "official_instances_page.html").write_bytes(page)
        rows = parse_x_rows(page)

        for role, expected_names in EXPECTED_NAMES.items():
            actual_names = tuple(rows[index - 1].name for index in ROLE_INDICES[role])
            if actual_names != expected_names:
                raise ValueError(
                    f"{role} identity drift: expected {expected_names}, got {actual_names}"
                )

        selected_indices = {
            index for indices in ROLE_INDICES.values() for index in indices
        }
        selected_records: list[dict[str, Any]] = []
        row_records: list[dict[str, Any]] = []

        for row in rows:
            role = role_for(row.index)
            record: dict[str, Any] = {
                "index": row.index,
                "name": row.name,
                "customers": row.customers,
                "catalogue_k": row.catalogue_k,
                "capacity": row.capacity,
                "bks": row.bks,
                "optimal": row.optimal,
                "role": role,
                "instance_url": row.instance_url,
                "bks_url": row.bks_url,
                "downloaded_and_audited": row.index in selected_indices,
            }
            if row.index in selected_indices:
                instance_bytes = fetch(row.instance_url)
                solution_bytes = fetch(row.bks_url)
                instance_path = instance_dir / f"{row.name}.vrp"
                solution_path = bks_dir / f"{row.name}.sol"
                instance_path.write_bytes(instance_bytes)
                solution_path.write_bytes(solution_bytes)

                hgs_path = HGS_INSTANCE_DIR / f"{row.name}.vrp"
                if not hgs_path.is_file():
                    raise FileNotFoundError(
                        f"fixed official HGS instance copy missing: {hgs_path}"
                    )
                hgs_bytes = hgs_path.read_bytes()
                normalised_match = normalise_newlines(instance_bytes) == normalise_newlines(
                    hgs_bytes
                )
                if not normalised_match:
                    raise ValueError(
                        f"official web instance differs from fixed HGS copy: {row.name}"
                    )

                problem = parse_vrp(instance_bytes)
                routes, declared_cost = parse_solution(solution_bytes)
                validation = validate_solution(problem, routes, declared_cost, row)
                if not validation["all_checks_pass"]:
                    raise ValueError(
                        f"BKS validation failed for {row.name}: {validation}"
                    )
                record.update(
                    {
                        "instance_sha256": sha256_bytes(instance_bytes),
                        "instance_normalised_sha256": sha256_bytes(
                            normalise_newlines(instance_bytes)
                        ),
                        "hgs_copy_sha256": sha256_bytes(hgs_bytes),
                        "hgs_copy_normalised_sha256": sha256_bytes(
                            normalise_newlines(hgs_bytes)
                        ),
                        "hgs_copy_normalised_match": normalised_match,
                        "bks_solution_sha256": sha256_bytes(solution_bytes),
                        "bks_validation": validation,
                    }
                )
                selected_records.append(record)
            row_records.append(record)

        safety_records = [
            record for record in selected_records if record["role"] == "safety_optimal"
        ]
        headroom_records = [
            record
            for record in selected_records
            if record["role"] != "safety_optimal"
        ]
        checks = {
            "catalogue_has_exactly_100_x_instances": len(rows) == 100,
            "selection_has_exactly_20_instances": len(selected_records) == 20,
            "role_names_match_pre_registration": all(
                tuple(rows[index - 1].name for index in ROLE_INDICES[role])
                == EXPECTED_NAMES[role]
                for role in ROLE_INDICES
            ),
            "safety_block_currently_proven_optimal": all(
                record["optimal"] for record in safety_records
            ),
            "development_confirmation_holdout_currently_open": all(
                not record["optimal"] for record in headroom_records
            ),
            "all_selected_instances_match_fixed_hgs_copy_after_newline_normalisation": all(
                record["hgs_copy_normalised_match"] for record in selected_records
            ),
            "all_selected_bks_routes_independently_validated": all(
                record["bks_validation"]["all_checks_pass"]
                for record in selected_records
            ),
            "solver_search_was_not_imported_or_run": True,
            "china81_was_not_read_or_run": True,
            "stage2_was_not_started": True,
        }
        if not all(checks.values()):
            raise ValueError(f"foundation checks failed: {checks}")

        with (temp_dir / "raw_runs.csv").open(
            "w",
            encoding="utf-8",
            newline="",
        ) as stream:
            fieldnames = [
                "index",
                "name",
                "customers",
                "catalogue_k",
                "capacity",
                "bks",
                "optimal",
                "role",
                "downloaded_and_audited",
                "instance_url",
                "bks_url",
                "instance_sha256",
                "instance_normalised_sha256",
                "bks_solution_sha256",
                "bks_all_checks_pass",
            ]
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            for record in row_records:
                writer.writerow(
                    {
                        "index": record["index"],
                        "name": record["name"],
                        "customers": record["customers"],
                        "catalogue_k": record["catalogue_k"],
                        "capacity": record["capacity"],
                        "bks": f"{record['bks']:.2f}",
                        "optimal": str(record["optimal"]).lower(),
                        "role": record["role"],
                        "downloaded_and_audited": str(
                            record["downloaded_and_audited"]
                        ).lower(),
                        "instance_url": record["instance_url"],
                        "bks_url": record["bks_url"],
                        "instance_sha256": record.get("instance_sha256", ""),
                        "instance_normalised_sha256": record.get(
                            "instance_normalised_sha256",
                            "",
                        ),
                        "bks_solution_sha256": record.get(
                            "bks_solution_sha256",
                            "",
                        ),
                        "bks_all_checks_pass": str(
                            record.get("bks_validation", {}).get(
                                "all_checks_pass",
                                "",
                            )
                        ).lower(),
                    }
                )

        write_json(
            temp_dir / "selection.json",
            {
                "contract": "ALGO-COMPARE-FOUNDATION-001",
                "catalogue_url": CATALOGUE_URL,
                "catalogue_page_sha256": sha256_bytes(page),
                "fixed_hgs_commit": HGS_COMMIT,
                "final_public_scope": "all_100_X_instances",
                "private_scope": "China81_only_not_run",
                "roles": {
                    role: [
                        next(
                            record
                            for record in selected_records
                            if record["index"] == index
                        )
                        for index in indices
                    ]
                    for role, indices in ROLE_INDICES.items()
                },
            },
        )

        finished = datetime.now(timezone.utc)
        metadata = {
            "contract": "ALGO-COMPARE-FOUNDATION-001",
            "task": "freeze X-100 catalogue and pre-registered 20-instance blocks",
            "started_at_utc": started.isoformat(),
            "finished_at_utc": finished.isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "catalogue_url": CATALOGUE_URL,
            "catalogue_page_sha256": sha256_bytes(page),
            "fixed_hgs_commit": HGS_COMMIT,
            "x_instances_catalogued": len(rows),
            "x_optimal_yes": sum(row.optimal for row in rows),
            "x_optimal_no": sum(not row.optimal for row in rows),
            "selected_instances_downloaded": len(selected_records),
            "search_evaluations": 0,
            "solver_imports": 0,
            "china81_search_allowed": False,
            "stage2_allowed": False,
        }
        write_json(temp_dir / "metadata.json", metadata)

        verdict = "PASS_X_CVRP_COMPARISON_FOUNDATION_ZERO_SEARCH"
        decision = {
            "verdict": verdict,
            "checks": checks,
            "formal_x100_search_allowed": False,
            "confirmation_search_allowed": False,
            "holdout_search_allowed": False,
            "china81_search_allowed": False,
            "stage2_allowed": False,
            "next_action": (
                "fix comparison contracts and build a same-path "
                "mode=hgs|lns|hybrid attribution harness"
            ),
        }
        write_json(temp_dir / "decision.json", decision)

        report_lines = [
            "# X-CVRP 算法比较基础零搜索冻结报告",
            "",
            f"- 判定：`{verdict}`",
            f"- CVRPLIB X 目录：{len(rows)} 题；当前页面 Opt=yes "
            f"{metadata['x_optimal_yes']} 题、Opt=no {metadata['x_optimal_no']} 题。",
            "- 阶段块：5 题安全块、5 题开发块、5 题确认块、5 题封存块。",
            "- 20/20 原始实例与固定官方 HGS 提交的副本仅换行符不同，"
            "换行归一化后逐字节一致。",
            "- 20/20 官方 BKS 路线已独立复算：按 CVRPLIB 的无车场客户编号"
            "映射后客户恰好一次、容量可行，整数欧氏距离与解文件及当前官方"
            "页面一致。目录中的 |K| 是算例标识字段，不冒充 BKS 实际路线数。",
            "- 求解器导入 0 次，搜索评价 0 次；未读取或运行 China81，"
            "未进入阶段二。",
            "",
            "## 边界",
            "",
            "本证据只证明算例、BKS、阶段身份和来源冻结正确，"
            "不证明任何混合算法有效。确认块与封存块当前只完成数据冻结，"
            "不得运行求解器。",
            "",
            "## 下一步",
            "",
            "建立同一工作器的 `hgs|lns|hybrid` 三模式，先证明关闭增强时"
            " hybrid 与 HGS 固定迭代逐位一致，再允许开发块的最低成本质量门。",
        ]
        (temp_dir / "report.md").write_text(
            "\n".join(report_lines) + "\n",
            encoding="utf-8",
        )
        write_json(
            temp_dir / "artifact_hashes.json",
            build_hash_manifest(temp_dir),
        )

        os.replace(temp_dir, OUTPUT_DIR)
        print(
            json.dumps(
                {
                    "verdict": verdict,
                    "output": str(OUTPUT_DIR),
                    "catalogued": len(rows),
                    "selected": len(selected_records),
                    "search_evaluations": 0,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
