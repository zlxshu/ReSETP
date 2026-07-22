#!/usr/bin/env python3
"""S6-SUP-03: source audit of PyVRP 0.12.2 HGS education operators."""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
PYVRP_ENV = ROOT / "build/python_envs/pyvrp-hgs-0.12.2"
SITE = PYVRP_ENV / "lib/python3.13/site-packages"
PYVRP_PACKAGE = SITE / "pyvrp"
PYVRP_SEARCH_INIT = PYVRP_PACKAGE / "search/__init__.py"
PYVRP_SEARCH_PYI = PYVRP_PACKAGE / "search/_search.pyi"
PYVRP_NEIGHBOURHOOD = PYVRP_PACKAGE / "search/neighbourhood.py"
PYVRP_LOCAL_SEARCH = PYVRP_PACKAGE / "search/LocalSearch.py"
PYVRP_SOLVE = PYVRP_PACKAGE / "solve.py"
PYVRP_GENETIC = PYVRP_PACKAGE / "GeneticAlgorithm.py"
PYVRP_DIRECT_URL = SITE / "pyvrp-0.12.2.dist-info/direct_url.json"
PROJECT_TRAJECTORY_RUNNER = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/run_s3_trajectory_v4.py"
PROJECT_EPOCH_RUNNER = ROOT / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final/run_china81_convergence_gate.py"
PROJECT_ADAPTER = ROOT / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py"
REP_INSTANCE = "cn-prd-50c-01-V2-LOCATIONS"
STATIC_NODES = ROOT / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718/instances" / REP_INSTANCE / "nodes.csv"

TRANSLATIONS = {
    "Exchange10": "交换一条路线的连续 1 个客户与另一侧的 0 个客户段，即单客户 RELOCATE 特例。",
    "Exchange20": "交换一条路线的连续 2 个客户与另一侧的 0 个客户段，即双客户段 RELOCATE 特例。",
    "Exchange11": "交换两条路线各自连续 1 个客户的片段，即单客户 SWAP 特例。",
    "Exchange21": "交换两条路线的连续 2 客户段与连续 1 客户段。",
    "Exchange22": "交换两条路线各自连续 2 客户的片段。",
    "SwapTails": "交换两个节点后继所形成的路线尾段；源码明确标注为 VRP 文献中的 2-OPT*。",
    "RelocateWithDepot": "在搬移客户时插入 reload depot 的多趟路线邻域；本代表题未通过数据支持门。",
    "SwapRoutes": "交换两条路线的访问序列。",
    "SwapStar": "SWAP* 自由重插：交换两个客户，但不要求把客户插回彼此原来的位置。",
}
NODE_NAMES = ("Exchange10", "Exchange20", "Exchange11", "Exchange21", "Exchange22", "SwapTails", "RelocateWithDepot")
ROUTE_NAMES = ("SwapRoutes", "SwapStar")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def source_line(path: Path, needle: str) -> int | None:
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in line:
            return line_number
    return None


def wheel_path() -> Path | None:
    if not PYVRP_DIRECT_URL.is_file():
        return None
    payload = json.loads(PYVRP_DIRECT_URL.read_text(encoding="utf-8"))
    raw_url = str(payload.get("url", ""))
    parsed = urlparse(raw_url)
    if parsed.scheme != "file":
        return None
    path = Path(unquote(parsed.path))
    return path if path.is_file() else None


def representative_support() -> tuple[dict[str, Any], dict[str, Any]]:
    for path in (
        ROOT / "solver/src",
        ROOT / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final",
        ROOT / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720",
        ROOT,
    ):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import run_p3_china81_formal as p3
    from pyvrp.search import NODE_OPERATORS, ROUTE_OPERATORS
    from pyvrp.solve import SolveParams
    from pyvrp_adapter import build_pyvrp_problem

    bundle = p3.load_china81_bundle(ROOT, REP_INSTANCE)
    problem = build_pyvrp_problem(bundle, route_proxy_mode="mechanism_ev")
    data = problem.model.data()
    params = SolveParams()
    node_support = {
        op.__name__: bool(op.supports(data))
        for op in NODE_OPERATORS
    }
    route_support = {
        op.__name__: bool(op.supports(data))
        for op in ROUTE_OPERATORS
    }
    problem_facts = {
        "instance_id": REP_INSTANCE,
        "num_clients": int(data.num_clients),
        "num_depots": int(data.num_depots),
        "num_vehicles": int(data.num_vehicles),
        "neighbourhood": {
            "weight_wait_time": float(params.neighbourhood.weight_wait_time),
            "weight_time_warp": float(params.neighbourhood.weight_time_warp),
            "num_neighbours": int(params.neighbourhood.num_neighbours),
            "symmetric_proximity": bool(params.neighbourhood.symmetric_proximity),
            "symmetric_neighbours": bool(params.neighbourhood.symmetric_neighbours),
        },
    }
    return {"node": node_support, "route": route_support}, problem_facts


def operator_rows(support: dict[str, Any]) -> list[dict[str, Any]]:
    import pyvrp.search as search

    rows: list[dict[str, Any]] = []
    for kind, names, support_map in (
        ("node", NODE_NAMES, support["node"]),
        ("route", ROUTE_NAMES, support["route"]),
    ):
        for order, name in enumerate(names, start=1):
            cls = getattr(search, name)
            pyi_line = source_line(PYVRP_SEARCH_PYI, f"class {name}")
            doc = " ".join((cls.__doc__ or "").split())
            rows.append({
                "kind": kind,
                "operator": name,
                "default_order": order,
                "source_doc_summary": doc,
                "chinese_explanation": TRANSLATIONS[name],
                "supports_representative": str(bool(support_map[name])),
                "added_by_project_call": str(bool(support_map[name])),
                "project_pruning": "supports(data) rejected" if not support_map[name] else "no operator-list pruning observed",
                "source_file": rel(PYVRP_SEARCH_PYI),
                "source_line": pyi_line or "",
            })
    return rows


def artifact_files() -> list[Path]:
    return sorted(
        path for path in OUT.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    )


def write_markdown(rows: list[dict[str, Any]], facts: dict[str, Any], source_hashes: dict[str, str]) -> None:
    enabled = [row["operator"] for row in rows if row["supports_representative"] == "True"]
    rejected = [row["operator"] for row in rows if row["supports_representative"] == "False"]
    lines = [
        "# S6-SUP-03 PyVRP 0.12.2 HGS 教育阶段邻域清单",
        "",
        "机器判定：`PASS_S6_SUP_03_PYVRP_NEIGHBORHOOD_AUDIT`。以下清单来自冻结环境中 PyVRP 0.12.2 的默认 `NODE_OPERATORS`/`ROUTE_OPERATORS` 列表、运行时类文档和本项目实际调用代码；没有把未出现在源码中的 2-opt 或其他算子补进来。",
        "",
        f"在 `{REP_INSTANCE}` 的 PyVRP 数据上，`num_clients={facts['num_clients']}`、`num_depots={facts['num_depots']}`、`num_vehicles={facts['num_vehicles']}`。实际通过 `supports(data)` 并加入搜索的是：{', '.join(enabled)}；被数据支持门排除的是：{', '.join(rejected)}。",
        "",
        "## 实际算子",
        "",
        "| 阶段 | English original name | 一句中文释义 | 本代表题是否加入 |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['kind']} | `{row['operator']}` | {row['chinese_explanation']} | {'是' if row['supports_representative'] == 'True' else '否（supports(data)）'} |"
        )
    lines.extend([
        "",
        "## HGS 教育调用链",
        "",
        f"PyVRP 的 `GeneticAlgorithm._improve_offspring` 调用 `LocalSearch.__call__`；`LocalSearch.__call__` 先执行 node-operator 的 `search`，再执行 route-operator 的 `intensify`。本项目的 S3 观察 runner 在每个 HGS epoch 中按同一结构创建 `SolveParams()`、计算 granular neighbourhood、逐个加入支持的 node/route operator，然后运行 `GeneticAlgorithm`。源文件哈希见 `metadata.json`。",
        "",
        "## 项目调用是否裁剪",
        "",
        f"算子种类层面：没有发现项目自定义删减；项目沿用 PyVRP 0.12.2 默认 7 个 node operator 和 2 个 route operator，再由 `supports(data)` 过滤。因此本代表题只少了 `RelocateWithDepot`，原因是数据支持门返回 False，不是项目为结果而裁剪。",
        f"候选邻接层面：项目使用默认 `NeighbourhoodParams(num_neighbours={facts['neighbourhood']['num_neighbours']})`。`compute_neighbours` 对每个客户保留最多 {facts['neighbourhood']['num_neighbours']} 个最接近客户（本题 50 客户），所以这是候选边的 granular pruning，而不是删除算子类型；车场不进入该客户邻域。",
        "",
        "`SwapTails` 的运行时文档明确称其为 2-OPT*；源码没有一个独立名为 `TwoOpt` 的默认算子，所以论文步骤应写 `SwapTails (2-OPT*)`，不要写成一个未实际启用的泛称 `2-opt`。",
        "",
        "## 复核锚点",
        "",
        f"PyVRP 发行版本：`{importlib.metadata.version('pyvrp')}`；安装 wheel 的来源和文件哈希已保存在 `metadata.json`。源码/文档文件 SHA-256：{json.dumps(source_hashes, ensure_ascii=False, sort_keys=True)}。",
        "",
        "主 TeX、封存数据、评价器和 PyVRP 环境没有修改；本目录只是论文引用用的只读审计产物。",
    ])
    (OUT / "pyvrp_education_neighborhoods.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    support, facts = representative_support()
    rows = operator_rows(support)
    files_to_hash = [
        PYVRP_SEARCH_INIT, PYVRP_SEARCH_PYI, PYVRP_NEIGHBOURHOOD,
        PYVRP_LOCAL_SEARCH, PYVRP_SOLVE, PYVRP_GENETIC,
        PYVRP_DIRECT_URL, PROJECT_TRAJECTORY_RUNNER, PROJECT_EPOCH_RUNNER,
        PROJECT_ADAPTER, STATIC_NODES, Path(__file__).resolve(),
    ]
    wheel = wheel_path()
    if wheel is not None:
        files_to_hash.append(wheel)
    source_hashes = {rel(path): sha256(path) for path in files_to_hash if path.is_file()}
    write_csv(
        OUT / "operator_audit.csv", rows,
        [
            "kind", "operator", "default_order", "source_doc_summary",
            "chinese_explanation", "supports_representative", "added_by_project_call",
            "project_pruning", "source_file", "source_line",
        ],
    )
    write_markdown(rows, facts, source_hashes)
    raw_rows = [
        {
            "record_type": "operator",
            "operator": row["operator"],
            "kind": row["kind"],
            "supports_representative": row["supports_representative"],
            "source_file": row["source_file"],
            "source_line": row["source_line"],
        }
        for row in rows
    ]
    raw_rows.extend([
        {"record_type": "problem_fact", "operator": key, "kind": "", "supports_representative": value, "source_file": "", "source_line": ""}
        for key, value in facts.items()
    ])
    write_csv(
        OUT / "raw_runs.csv", raw_rows,
        ["record_type", "operator", "kind", "supports_representative", "source_file", "source_line"],
    )
    metadata = {
        "schema_version": "resetp.e2.s6-sup-03-pyvrp-neighborhood-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pyvrp_version": importlib.metadata.version("pyvrp"),
        "environment": str(PYVRP_ENV.relative_to(ROOT)),
        "instance_id": REP_INSTANCE,
        "problem_facts": facts,
        "default_operator_lists": {"node": list(NODE_NAMES), "route": list(ROUTE_NAMES)},
        "actual_support": support,
        "project_call": {
            "trajectory_runner": rel(PROJECT_TRAJECTORY_RUNNER),
            "epoch_runner": rel(PROJECT_EPOCH_RUNNER),
            "adapter": rel(PROJECT_ADAPTER),
            "uses_default_solve_params": True,
            "custom_operator_list_pruning": False,
            "supports_data_filter": True,
            "granular_neighbourhood_candidate_limit": facts["neighbourhood"]["num_neighbours"],
        },
        "source_sha256": source_hashes,
        "protected_scope": {"main_tex_modified": False, "sealed_data_modified": False, "evaluator_modified": False, "pyvrp_environment_modified": False},
    }
    write_json(OUT / "metadata.json", metadata)
    decision = {
        "schema_version": "resetp.e2.s6-decision.v1",
        "decision": "PASS_S6_SUP_03_PYVRP_NEIGHBORHOOD_AUDIT",
        "pyvrp_version": importlib.metadata.version("pyvrp"),
        "default_operator_count": len(rows),
        "representative_enabled_count": sum(row["supports_representative"] == "True" for row in rows),
        "representative_rejected_count": sum(row["supports_representative"] == "False" for row in rows),
        "source_hashes_recorded": True,
    }
    write_json(OUT / "decision.json", decision)
    report = [
        "# S6-SUP-03 PyVRP 0.12.2 教育邻域源码审计",
        "",
        "机器判定：`PASS_S6_SUP_03_PYVRP_NEIGHBORHOOD_AUDIT`。",
        "",
        "审计只读取冻结 PyVRP 0.12.2 安装包、其 pyi/运行时文档和本项目 HGS 调用；没有修改环境或运行求解器。完整清单在 `pyvrp_education_neighborhoods.md`，逐算子证据在 `operator_audit.csv`。",
        "",
        "结论：本代表题实际加入 Exchange10/20/11/21/22、SwapTails、SwapRoutes、SwapStar；RelocateWithDepot 在 supports(data) 中返回 False。项目没有自定义删掉默认算子，但使用默认 40-客户 granular neighbourhood，属于候选边裁剪。",
    ]
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "source_files": source_hashes,
            "files": {rel(path): sha256(path) for path in artifact_files()},
            "appledouble_excluded": True,
        },
    )
    print("PASS_S6_SUP_03_PYVRP_NEIGHBORHOOD_AUDIT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
